"""Feature encoding utilities driven by ``FeatureSpec`` definitions."""

from __future__ import annotations

import re

import pandas as pd

from src.core.schema import FeatureSpec

_VALUE_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def slugify_feature_value(value: str) -> str:
    """Convert a categorical value into a safe suffix for encoded column names."""
    slug = _VALUE_SLUG_PATTERN.sub("_", value.lower().strip())
    return slug.strip("_")


def encode_features(
    row: pd.Series,
    specs: list[FeatureSpec],
    prefix: str = "",
) -> dict[str, object]:
    """Encode a row's features according to each ``FeatureSpec`` definition.

    Numeric features and categorical features with ``encoding='passthrough'``
    are copied as ``{prefix}{feature_name}``.

    Categorical features with ``encoding='one_hot'`` expand into boolean columns
    named ``{prefix}{feature_name}_{slugified_allowed_value}`` for each entry in
    ``allowed_values``.
    """
    encoded: dict[str, object] = {}

    for spec in specs:
        if spec.name not in row.index:
            continue

        value = row[spec.name]

        if spec.dtype == "numeric":
            encoded[f"{prefix}{spec.name}"] = value
            continue

        if spec.encoding == "passthrough":
            encoded[f"{prefix}{spec.name}"] = value
            continue

        if spec.encoding == "one_hot":
            if not spec.allowed_values:
                raise ValueError(
                    f"FeatureSpec '{spec.name}' requires allowed_values for one_hot encoding"
                )
            for allowed in spec.allowed_values:
                column_name = f"{prefix}{spec.name}_{slugify_feature_value(allowed)}"
                encoded[column_name] = int(value == allowed)
            continue

        raise ValueError(f"Unsupported encoding '{spec.encoding}' for feature '{spec.name}'")

    return encoded
