"""Domain-agnostic data contracts for recommendation-engine tables.

These schemas describe the shape of customers, products, and interactions
DataFrames without binding to any particular industry or source dataset.
Concrete feature definitions (names, dtypes, allowed values) are supplied
when building a schema instance for a given deployment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

FeatureDtype = Literal["numeric", "categorical"]
FeatureEncoding = Literal["passthrough", "one_hot"]


def _validate_required_columns(
    df: pd.DataFrame,
    required: list[str],
    schema_name: str,
) -> None:
    missing = [column for column in required if column not in df.columns]
    if not missing:
        return
    if len(missing) == 1:
        raise ValueError(f"{schema_name}: missing required column '{missing[0]}'")
    joined = ", ".join(f"'{column}'" for column in missing)
    raise ValueError(f"{schema_name}: missing required columns: {joined}")


def _validate_feature_specs(df: pd.DataFrame, features: list[FeatureSpec], schema_name: str) -> None:
    for spec in features:
        if spec.name not in df.columns:
            continue

        series = df[spec.name]

        if spec.dtype == "numeric":
            if not pd.api.types.is_numeric_dtype(series):
                raise ValueError(
                    f"{schema_name}: column '{spec.name}' must be numeric, "
                    f"got dtype '{series.dtype}'"
                )
            continue

        if spec.allowed_values is None:
            continue

        non_null = series.dropna()
        if non_null.empty:
            continue

        allowed = {str(value) for value in spec.allowed_values}
        observed = non_null.astype(str)
        invalid = sorted(set(observed.unique()) - allowed)
        if invalid:
            joined = ", ".join(f"'{value}'" for value in invalid)
            raise ValueError(
                f"{schema_name}: column '{spec.name}' contains values not in "
                f"allowed_values: {joined}"
            )


@dataclass(frozen=True)
class FeatureSpec:
    """Description of a single feature column on a customer or product table."""

    name: str
    dtype: FeatureDtype
    allowed_values: list[str] | None = None
    encoding: FeatureEncoding = "passthrough"


@dataclass
class CustomerSchema:
    """Contract for the customers table.

    Required columns:
        - ``customer_id`` (primary key)
        - every ``FeatureSpec.name`` listed in ``features``
    """

    features: list[FeatureSpec] = field(default_factory=list)

    PRIMARY_KEY: str = field(default="customer_id", init=False, repr=False)

    def required_columns(self) -> list[str]:
        return [self.PRIMARY_KEY, *[feature.name for feature in self.features]]

    def get_feature(self, name: str) -> FeatureSpec | None:
        for feature in self.features:
            if feature.name == name:
                return feature
        return None

    def feature_specs(self, names: list[str]) -> list[FeatureSpec]:
        lookup = {feature.name: feature for feature in self.features}
        missing = [name for name in names if name not in lookup]
        if missing:
            joined = ", ".join(f"'{name}'" for name in missing)
            raise ValueError(f"CustomerSchema: unknown feature names: {joined}")
        return [lookup[name] for name in names]

    def validate(self, df: pd.DataFrame) -> None:
        _validate_required_columns(df, self.required_columns(), "CustomerSchema")

    def validate_values(self, df: pd.DataFrame) -> None:
        """Check numeric dtypes and categorical allowed_values after ``validate()``."""
        self.validate(df)
        _validate_feature_specs(df, self.features, "CustomerSchema")


@dataclass
class ProductSchema:
    """Contract for the products table.

    Required columns:
        - ``product_id`` (primary key)
        - every ``FeatureSpec.name`` listed in ``features``
        - ``category.name`` when ``category`` is set

    Optional columns:
        - ``product_name`` (display label; not validated as required)
    """

    features: list[FeatureSpec] = field(default_factory=list)
    category: FeatureSpec | None = None

    PRIMARY_KEY: str = field(default="product_id", init=False, repr=False)
    DISPLAY_NAME_COLUMN: str = field(default="product_name", init=False, repr=False)

    def required_columns(self) -> list[str]:
        columns = [self.PRIMARY_KEY, *[feature.name for feature in self.features]]
        if self.category is not None:
            columns.append(self.category.name)
        return columns

    def all_feature_specs(self) -> list[FeatureSpec]:
        specs = list(self.features)
        if self.category is not None:
            specs.append(self.category)
        return specs

    def feature_specs(self, names: list[str]) -> list[FeatureSpec]:
        lookup = {feature.name: feature for feature in self.all_feature_specs()}
        missing = [name for name in names if name not in lookup]
        if missing:
            joined = ", ".join(f"'{name}'" for name in missing)
            raise ValueError(f"ProductSchema: unknown feature names: {joined}")
        return [lookup[name] for name in names]

    def validate(self, df: pd.DataFrame) -> None:
        _validate_required_columns(df, self.required_columns(), "ProductSchema")

    def validate_values(self, df: pd.DataFrame) -> None:
        """Check numeric dtypes and categorical allowed_values after ``validate()``."""
        self.validate(df)
        _validate_feature_specs(df, self.all_feature_specs(), "ProductSchema")


@dataclass
class InteractionSchema:
    """Contract for the interactions table (long-format customer–product rows).

    Required columns:
        - ``customer_id`` (foreign key to customers)
        - ``product_id`` (foreign key to products)

    Optional columns:
        - ``timestamp`` (event time; not required by ``validate``)
        - ``weight`` (interaction strength; defaults to ``default_weight`` when absent)
    """

    TIMESTAMP_COLUMN: str = field(default="timestamp", init=False, repr=False)
    WEIGHT_COLUMN: str = field(default="weight", init=False, repr=False)
    default_weight: float = 1.0

    PRIMARY_KEY_COLUMNS: tuple[str, str] = field(
        default=("customer_id", "product_id"),
        init=False,
        repr=False,
    )

    def required_columns(self) -> list[str]:
        return list(self.PRIMARY_KEY_COLUMNS)

    def validate(self, df: pd.DataFrame) -> None:
        _validate_required_columns(df, self.required_columns(), "InteractionSchema")

    def validate_values(self, df: pd.DataFrame) -> None:
        """Check optional weight dtype when the column is present."""
        self.validate(df)
        if self.WEIGHT_COLUMN in df.columns and not pd.api.types.is_numeric_dtype(df[self.WEIGHT_COLUMN]):
            raise ValueError(
                f"InteractionSchema: column '{self.WEIGHT_COLUMN}' must be numeric, "
                f"got dtype '{df[self.WEIGHT_COLUMN].dtype}'"
            )
