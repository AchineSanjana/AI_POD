"""Feature encoding utilities driven by ``FeatureSpec`` definitions."""

from __future__ import annotations

import re

import pandas as pd

# pyrefly: ignore [missing-import]
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
                # Slugify the feature name too so column names are stable,
                # lower-cased, and consistent regardless of the schema's
                # capitalisation convention (e.g. 'Contract' → 'contract').
                column_name = (
                    f"{prefix}{slugify_feature_value(spec.name)}"
                    f"_{slugify_feature_value(allowed)}"
                )
                encoded[column_name] = int(value == allowed)
            continue

        raise ValueError(f"Unsupported encoding '{spec.encoding}' for feature '{spec.name}'")

    return encoded


def encode_categorical_features(
    df: pd.DataFrame,
    specs: list[FeatureSpec],
    prefix: str = "",
) -> pd.DataFrame:
    """Encode an entire DataFrame's feature columns according to ``FeatureSpec`` definitions.

    This is the DataFrame-level counterpart of ``encode_features``.  It applies
    the same encoding rules to every row and returns a **new** DataFrame
    containing only the encoded columns (the original columns are not carried
    over unless they happen to be passthrough features).

    Numeric features and categorical features with ``encoding='passthrough'``
    are returned as ``{prefix}{feature_name}``.

    Categorical features with ``encoding='one_hot'`` are expanded into one
    boolean column per allowed value:
    ``{prefix}{feature_name}_{slugified_allowed_value}``.

    Columns named in ``specs`` that are absent from ``df`` are silently skipped,
    matching the behaviour of ``encode_features``.

    Args:
        df: Input DataFrame.  Must not be modified in place.
        specs: Feature specifications that control encoding.
        prefix: Optional string prepended to every output column name.

    Returns:
        A new DataFrame with one row per input row and one column per encoded
        feature output.  The index of ``df`` is preserved.

    Raises:
        ValueError: If a ``one_hot`` spec has no ``allowed_values``.
    """
    if df.empty:
        # Build an empty frame with the correct columns so callers can rely on
        # the column set even when there is no data.  We derive the column names
        # directly from the specs rather than calling encode_features (which
        # would silently skip everything because the dummy series has no index
        # keys matching the spec names).
        columns: list[str] = []
        for spec in specs:
            if spec.dtype == "numeric" or spec.encoding == "passthrough":
                columns.append(f"{prefix}{spec.name}")
            elif spec.encoding == "one_hot":
                if not spec.allowed_values:
                    raise ValueError(
                        f"FeatureSpec '{spec.name}' requires allowed_values for one_hot encoding"
                    )
                for allowed in spec.allowed_values:
                    columns.append(
                        f"{prefix}{slugify_feature_value(spec.name)}"
                        f"_{slugify_feature_value(allowed)}"
                    )
            else:
                raise ValueError(
                    f"Unsupported encoding '{spec.encoding}' for feature '{spec.name}'"
                )
        return pd.DataFrame(columns=columns)

    encoded_rows = [
        encode_features(row, specs, prefix=prefix)
        for _, row in df.iterrows()
    ]
    return pd.DataFrame(encoded_rows, index=df.index)
