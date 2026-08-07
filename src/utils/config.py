"""Loads config/config.yaml and exposes it as a plain dict.

Usage:
    from src.utils.config import load_config
    cfg = load_config()
    cfg["paths"]["processed_dir"]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# pyrefly: ignore [missing-import]
from src.core.schema import CustomerSchema, FeatureSpec, ProductSchema

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


# ---------------------------------------------------------------------------
# InteractionSourceConfig — mirrors the hardcoded constants in reshape_telco.py
# ---------------------------------------------------------------------------


@dataclass
class InteractionSourceConfig:
    """Parsed representation of ``data.interaction_source`` in config.yaml.

    Attributes:
        service_columns: All Telco service columns to include in the
            product/interaction tables.  Mirrors ``BINARY_SERVICE_COLUMNS``
            (plus ``InternetService``) in reshape_telco.py.
        positive_values: Cell values that mean the customer IS subscribed.
        negative_values: Cell values that mean the customer is NOT subscribed.
            Mirrors ``NEGATIVE_VALUES`` in reshape_telco.py.
    """

    service_columns: list[str] = field(default_factory=list)
    positive_values: list[str] = field(default_factory=list)
    negative_values: list[str] = field(default_factory=list)


def get_interaction_source_config(config: dict) -> InteractionSourceConfig:
    """Parse ``data.interaction_source`` from a loaded config dict.

    Args:
        config: The full config dict returned by :func:`load_config`.

    Returns:
        An :class:`InteractionSourceConfig` populated from the YAML block.

    Raises:
        KeyError: If ``data.interaction_source`` (or any required sub-key) is
            absent from the config.
    """
    block: dict = config["data"]["interaction_source"]
    return InteractionSourceConfig(
        service_columns=list(block["service_columns"]),
        positive_values=list(block["positive_values"]),
        negative_values=list(block["negative_values"]),
    )


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def resolve_path(relative_path: str) -> Path:
    """Resolve a path from config.yaml relative to the project root."""
    return PROJECT_ROOT / relative_path


def _feature_spec_from_config(entry: dict) -> FeatureSpec:
    return FeatureSpec(
        name=entry["name"],
        dtype=entry["dtype"],
        allowed_values=entry.get("allowed_values"),
        encoding=entry.get("encoding", "passthrough"),
    )


def build_customer_schema_from_config(config: dict) -> CustomerSchema:
    """Build a ``CustomerSchema`` from ``config['data']['customer_features']``."""
    features = [
        _feature_spec_from_config(entry)
        for entry in config["data"]["customer_features"]
    ]
    return CustomerSchema(features=features)


def build_product_schema_from_config(config: dict) -> ProductSchema:
    """Build a ``ProductSchema`` from ``config['data']`` product fields."""
    data = config["data"]
    category = None
    if "product_category" in data:
        category = _feature_spec_from_config(data["product_category"])

    features = [
        _feature_spec_from_config(entry)
        for entry in data.get("product_features", [])
    ]
    return ProductSchema(features=features, category=category)


# ---------------------------------------------------------------------------
# Fix 1 — model feature-subset helpers
# ---------------------------------------------------------------------------


def build_content_based_feature_specs_from_config(config: dict) -> list[FeatureSpec]:
    """Return ``FeatureSpec`` objects for the content-based model's feature subset.

    The names are taken from ``model.content_based.features`` and resolved
    against the full ``CustomerSchema`` built from ``data.customer_features``.

    Raises ``KeyError`` if ``model.content_based.features`` is absent and
    ``ValueError`` if any listed name is not declared in ``customer_features``.
    """
    names: list[str] = config["model"]["content_based"]["features"]
    schema = build_customer_schema_from_config(config)
    return schema.feature_specs(names)


def build_ranking_feature_specs_from_config(
    config: dict,
) -> tuple[list[FeatureSpec], list[FeatureSpec]]:
    """Return ``(customer_specs, product_specs)`` for the ranking model.

    Customer specs are resolved against ``data.customer_features``.
    Product specs are resolved against the product schema
    (``data.product_category`` + ``data.product_features``).

    Raises ``ValueError`` if any name is not declared in the respective schema.
    """
    ranking_cfg = config["model"]["ranking"]

    customer_schema = build_customer_schema_from_config(config)
    customer_specs = customer_schema.feature_specs(ranking_cfg["customer_features"])

    product_schema = build_product_schema_from_config(config)
    product_specs = product_schema.feature_specs(ranking_cfg["product_features"])

    return customer_specs, product_specs


def validate_model_feature_lists(config: dict) -> None:
    """Validate that all feature names referenced under ``model`` exist in the schemas.

    Checks:
    - ``model.content_based.features`` are a subset of ``data.customer_features``
    - ``model.ranking.customer_features`` are a subset of ``data.customer_features``
    - ``model.ranking.product_features`` are a subset of the product schema
    - No duplicate names within any list

    Raises ``ValueError`` on the first problem found.
    """
    _validate_no_duplicates(
        config["model"]["content_based"]["features"],
        "model.content_based.features",
    )
    _validate_no_duplicates(
        config["model"]["ranking"]["customer_features"],
        "model.ranking.customer_features",
    )
    _validate_no_duplicates(
        config["model"]["ranking"]["product_features"],
        "model.ranking.product_features",
    )

    # Resolution raises ValueError for unknown names automatically.
    build_content_based_feature_specs_from_config(config)
    build_ranking_feature_specs_from_config(config)


def _validate_no_duplicates(names: list[str], list_name: str) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for name in names:
        if name in seen:
            duplicates.append(name)
        seen.add(name)
    if duplicates:
        joined = ", ".join(f"'{n}'" for n in duplicates)
        raise ValueError(f"{list_name}: duplicate feature names: {joined}")
