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


def resolve_path(relative_path: str | Path) -> Path:
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


def get_content_feature_columns(config: dict) -> list[str]:
    """Return feature column names used by content-based / hybrid models."""
    specs = build_content_based_feature_specs_from_config(config)
    return [s.name for s in specs]



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


# ---------------------------------------------------------------------------
# Tenant Configuration Dataclasses & Parsing
# ---------------------------------------------------------------------------


@dataclass
class DataSourceConfig:
    type: str
    path: str


@dataclass
class TenantCustomersConfig:
    id_column: str
    features: list[FeatureSpec]


@dataclass
class TenantProductsConfig:
    derived_from: str
    category_column: str


@dataclass
class TenantInteractionsConfig:
    source: str
    interaction_source: InteractionSourceConfig | None = None


@dataclass
class TenantSegmentationConfig:
    field: str
    split: str = "median"
    threshold: float | None = None
    lower_label: str = "newer"
    upper_label: str = "established"


@dataclass
class TenantConfig:
    tenant_id: str
    data_source: DataSourceConfig
    customers: TenantCustomersConfig
    products: TenantProductsConfig
    interactions: TenantInteractionsConfig
    segmentation: TenantSegmentationConfig | None = None


def get_tenant_config(config: dict, tenant_id: str) -> TenantConfig:
    """Parse and return a structured TenantConfig for the specified tenant_id.

    Reuses InteractionSourceConfig when interactions.source == "interaction_source".

    Args:
        config: Full config dict from :func:`load_config`.
        tenant_id: Key under `tenants` (e.g. 'telco_default').

    Returns:
        A structured TenantConfig object.

    Raises:
        KeyError: If top-level 'tenants' or tenant_id or any required sub-field is missing.
    """
    if "tenants" not in config:
        raise KeyError("Config is missing top-level section 'tenants'")
    tenants = config["tenants"]
    if not isinstance(tenants, dict) or tenant_id not in tenants:
        raise KeyError(f"Tenant '{tenant_id}' not found in config['tenants']")

    block = tenants[tenant_id]
    if not isinstance(block, dict):
        raise KeyError(f"Config for tenant '{tenant_id}' must be a dict")

    # 1. data_source
    if "data_source" not in block:
        raise KeyError(f"Tenant '{tenant_id}' missing required section 'data_source'")
    ds = block["data_source"]
    if not isinstance(ds, dict) or "type" not in ds:
        raise KeyError(f"Tenant '{tenant_id}' data_source missing required field 'type'")
    if "path" not in ds:
        raise KeyError(f"Tenant '{tenant_id}' data_source missing required field 'path'")
    data_source = DataSourceConfig(type=str(ds["type"]), path=str(ds["path"]))

    # 2. customers
    if "customers" not in block:
        raise KeyError(f"Tenant '{tenant_id}' missing required section 'customers'")
    cust = block["customers"]
    if not isinstance(cust, dict) or "id_column" not in cust:
        raise KeyError(f"Tenant '{tenant_id}' customers missing required field 'id_column'")
    if "features" not in cust:
        raise KeyError(f"Tenant '{tenant_id}' customers missing required field 'features'")
    features = [_feature_spec_from_config(entry) for entry in cust["features"]]
    customers = TenantCustomersConfig(
        id_column=str(cust["id_column"]),
        features=features,
    )

    # 3. products
    if "products" not in block:
        raise KeyError(f"Tenant '{tenant_id}' missing required section 'products'")
    prod = block["products"]
    if not isinstance(prod, dict) or "derived_from" not in prod:
        raise KeyError(f"Tenant '{tenant_id}' products missing required field 'derived_from'")
    if "category_column" not in prod:
        raise KeyError(f"Tenant '{tenant_id}' products missing required field 'category_column'")
    products = TenantProductsConfig(
        derived_from=str(prod["derived_from"]),
        category_column=str(prod["category_column"]),
    )

    # 4. interactions
    if "interactions" not in block:
        raise KeyError(f"Tenant '{tenant_id}' missing required section 'interactions'")
    inter = block["interactions"]
    if not isinstance(inter, dict) or "source" not in inter:
        raise KeyError(f"Tenant '{tenant_id}' interactions missing required field 'source'")
    source_name = str(inter["source"])
    isc: InteractionSourceConfig | None = None
    if source_name == "interaction_source":
        isc = get_interaction_source_config(config)
    elif "service_columns" in inter:
        isc = InteractionSourceConfig(
            service_columns=list(inter["service_columns"]),
            positive_values=list(inter.get("positive_values", ["Yes"])),
            negative_values=list(inter.get("negative_values", ["No"])),
        )

    interactions = TenantInteractionsConfig(
        source=source_name,
        interaction_source=isc,
    )

    # 5. optional segmentation
    segmentation: TenantSegmentationConfig | None = None
    if "segmentation" in block and isinstance(block["segmentation"], dict):
        seg = block["segmentation"]
        if "field" in seg:
            thresh = None
            if "threshold" in seg and seg["threshold"] is not None:
                thresh = float(seg["threshold"])
            elif str(seg.get("split", "")).replace(".", "", 1).isdigit():
                thresh = float(seg["split"])
            segmentation = TenantSegmentationConfig(
                field=str(seg["field"]),
                split=str(seg.get("split", "median")),
                threshold=thresh,
                lower_label=str(seg.get("lower_label", "newer")),
                upper_label=str(seg.get("upper_label", "established")),
            )

    return TenantConfig(
        tenant_id=tenant_id,
        data_source=data_source,
        customers=customers,
        products=products,
        interactions=interactions,
        segmentation=segmentation,
    )


def get_tenant_auth_mapping(config: dict) -> dict[str, str]:
    """Return dictionary mapping api_key -> tenant_id from config['tenants_auth']."""
    return dict(config.get("tenants_auth", {}))


def get_storage_backend(config: dict | None = None):
    """Convenience accessor to instantiate the configured storage backend.

    See :func:`src.storage.get_storage_backend`.
    """
    from src.storage import get_storage_backend as _get_backend

    return _get_backend(config)


