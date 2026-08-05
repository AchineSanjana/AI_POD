"""Loads config/config.yaml and exposes it as a plain dict.

Usage:
    from src.utils.config import load_config
    cfg = load_config()
    cfg["paths"]["processed_dir"]
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.core.schema import CustomerSchema, FeatureSpec, ProductSchema

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


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
