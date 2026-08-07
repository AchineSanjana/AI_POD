"""GenericConfigAdapter — config-driven data adapter implementing the DataAdapter interface."""

from __future__ import annotations

from pathlib import Path
import pandas as pd

# pyrefly: ignore [missing-import]
from src.core.schema import CustomerSchema, FeatureSpec, InteractionSchema, ProductSchema
# pyrefly: ignore [missing-import]
from src.data.base_adapter import DataAdapter
# pyrefly: ignore [missing-import]
from src.data.interaction_extraction import (
    derive_products_from_interaction_source,
    extract_interactions_from_interaction_source,
)
# pyrefly: ignore [missing-import]
from src.utils.config import TenantConfig, resolve_path
# pyrefly: ignore [missing-import]
from src.utils.logger import get_logger

logger = get_logger(__name__)


class GenericConfigAdapter(DataAdapter):
    """Config-driven data adapter that configures data pipeline steps via TenantConfig.

    Args:
        tenant_config: Parsed TenantConfig defining data source, customer schema, product rules,
            and interaction rules.
        customer_schema: Optional CustomerSchema override. Defaults to schema built from tenant_config.
        product_schema: Optional ProductSchema override.
        interaction_schema: Optional InteractionSchema override.
    """

    def __init__(
        self,
        tenant_config: TenantConfig,
        customer_schema: CustomerSchema | None = None,
        product_schema: ProductSchema | None = None,
        interaction_schema: InteractionSchema | None = None,
    ) -> None:
        self.tenant_config = tenant_config

        resolved_customer_schema = customer_schema or CustomerSchema(
            features=tenant_config.customers.features
        )
        if product_schema is not None:
            resolved_product_schema = product_schema
        else:
            cat_col = tenant_config.products.category_column
            category_spec = FeatureSpec(
                name=cat_col,
                dtype="categorical",
                allowed_values=["Core", "Add-on"] if cat_col == "category" else None,
                encoding="one_hot",
            )
            resolved_product_schema = ProductSchema(category=category_spec)

        super().__init__(
            customer_schema=resolved_customer_schema,
            product_schema=resolved_product_schema,
        )

        if interaction_schema is not None:
            self.interaction_schema = interaction_schema

    def load_raw(self) -> pd.DataFrame:
        """Load raw dataset file based on tenant_config.data_source."""
        ds_type = self.tenant_config.data_source.type.lower()
        file_path = resolve_path(self.tenant_config.data_source.path)
        if not file_path.exists():
            file_path = Path(self.tenant_config.data_source.path)

        if ds_type == "csv":
            df = pd.read_csv(file_path)
        elif ds_type == "json":
            df = pd.read_json(file_path)
        else:
            raise ValueError(f"Unsupported data_source type '{ds_type}'")

        df.columns = [str(c).strip() for c in df.columns]
        if "TotalCharges" in df.columns:
            df["TotalCharges"] = pd.to_numeric(df["TotalCharges"], errors="coerce")

        self._raw = df
        return self._raw

    def to_customers(self) -> pd.DataFrame:
        """Build and validate customer table using tenant_config customer rules."""
        raw = self._ensure_raw()
        id_col = self.tenant_config.customers.id_column
        if id_col not in raw.columns:
            raise ValueError(
                f"Column '{id_col}' declared as customers.id_column not found in raw data. "
                f"Available columns: {list(raw.columns)}"
            )

        feature_specs = self.customer_schema.features

        cols_to_select = [
            c for c in [id_col] + [f.name for f in feature_specs] if c in raw.columns
        ]
        df = raw[cols_to_select].copy()

        if id_col in df.columns:
            df = df.rename(columns={id_col: "customer_id"})

        for spec in feature_specs:
            if spec.name not in df.columns:
                continue
            if spec.dtype == "numeric":
                df[spec.name] = pd.to_numeric(df[spec.name], errors="coerce")
            elif spec.dtype == "categorical":
                df[spec.name] = df[spec.name].astype("string")
                if spec.allowed_values is not None:
                    allowed_set = set(str(v) for v in spec.allowed_values)
                    observed_set = set(df[spec.name].dropna().unique())
                    unexpected = sorted(observed_set - allowed_set)
                    if unexpected:
                        logger.warning(
                            f"Feature '{spec.name}' contains values not in allowed_values: {unexpected}"
                        )

        logger.info(f"Built customers table for tenant '{self.tenant_config.tenant_id}': {len(df):,} rows")
        self.customer_schema.validate(df)
        return df

    def to_products(self) -> pd.DataFrame:
        """Build and validate product table using tenant_config product rules."""
        isc = self.tenant_config.interactions.interaction_source
        if self.tenant_config.products.derived_from == "interaction_source" or isc is not None:
            if isc is None:
                raise ValueError(
                    f"Tenant '{self.tenant_config.tenant_id}' requires InteractionSourceConfig for products"
                )
            df = derive_products_from_interaction_source(isc)
        else:
            raw = self._ensure_raw()
            df = raw.copy()

        logger.info(f"Built products table for tenant '{self.tenant_config.tenant_id}': {len(df):,} products")
        self.product_schema.validate_values(df)
        return df

    def to_interactions(self) -> pd.DataFrame:
        """Build and validate interaction table using tenant_config interaction rules."""
        raw = self._ensure_raw()
        isc = self.tenant_config.interactions.interaction_source
        if isc is not None:
            df = extract_interactions_from_interaction_source(
                raw=raw,
                isc=isc,
                id_column=self.tenant_config.customers.id_column,
            )
        else:
            df = raw.copy()

        logger.info(f"Built interactions table for tenant '{self.tenant_config.tenant_id}': {len(df):,} rows")
        self.interaction_schema.validate(df)
        return df

    def _ensure_raw(self) -> pd.DataFrame:
        """Return self._raw, calling load_raw() automatically if needed."""
        if self._raw is None:
            self.load_raw()
        return self._raw  # type: ignore[return-value]
