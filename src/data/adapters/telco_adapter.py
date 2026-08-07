"""TelcoAdapter — wraps the existing load_telco / reshape_telco logic behind
the ``DataAdapter`` interface.

This is a pure structural refactor: every value, column name, and computation
is identical to the original ``reshape_telco.py`` functions.  The only
behavioural change is that ``to_interactions()`` reads the service-column list
and negative-value set from ``InteractionSourceConfig`` (parsed from
``config.yaml``) instead of the module-level constants that remain in
``reshape_telco.py`` for backward compatibility.

Usage::

    from src.utils.config import (
        build_customer_schema_from_config,
        build_product_schema_from_config,
        get_interaction_source_config,
        load_config,
    )
    from src.data.adapters.telco_adapter import TelcoAdapter

    cfg = load_config()
    adapter = TelcoAdapter(
        config=cfg,
        customer_schema=build_customer_schema_from_config(cfg),
        product_schema=build_product_schema_from_config(cfg),
    )
    adapter.load_raw()
    customers    = adapter.to_customers()
    products     = adapter.to_products()
    interactions = adapter.to_interactions()
"""

from __future__ import annotations

import pandas as pd

# pyrefly: ignore [missing-import]
from src.core.schema import CustomerSchema, ProductSchema
# pyrefly: ignore [missing-import]
from src.data.base_adapter import DataAdapter
# pyrefly: ignore [missing-import]
from src.data.load_telco import load_raw_telco
# pyrefly: ignore [missing-import]
from src.utils.config import (
    InteractionSourceConfig,
    get_interaction_source_config,
    load_config,
)
# pyrefly: ignore [missing-import]
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Columns included in the customers table (raw column names before rename).
# Mirrors CUSTOMER_COLUMNS in reshape_telco.py — kept here as the single
# source of truth once reshape_telco.py is wired through this adapter.
_CUSTOMER_COLUMNS = [
    "customerID",
    "gender",
    "SeniorCitizen",
    "Partner",
    "Dependents",
    "tenure",
    "Contract",
    "PaperlessBilling",
    "PaymentMethod",
    "MonthlyCharges",
    "TotalCharges",
    "Churn",
]

# Products built from the categorical InternetService column.
# These are defined statically — same as reshape_telco.build_products_table().
_INTERNET_PRODUCTS = [
    {
        "product_id": "InternetService_DSL",
        "product_name": "Internet - DSL",
        "category": "Core",
    },
    {
        "product_id": "InternetService_Fiber",
        "product_name": "Internet - Fiber Optic",
        "category": "Core",
    },
]

# Columns whose service value drives InternetService product rows.
# "InternetService" is excluded from the binary loop and handled separately.
_INTERNET_SERVICE_COLUMN = "InternetService"


def _humanize(col: str) -> str:
    """``PhoneService`` → ``'Phone Service'``, ``StreamingTV`` → ``'Streaming TV'``.

    Mirrors the private helper in reshape_telco.py exactly.
    """
    out: list[str] = []
    for i, ch in enumerate(col):
        prev_is_lower = i > 0 and col[i - 1].islower()
        if ch.isupper() and out and prev_is_lower:
            out.append(" ")
        out.append(ch)
    return "".join(out)


def _binary_service_columns(isc: InteractionSourceConfig) -> list[str]:
    """Return service columns that have simple Yes/No semantics.

    Derived by removing ``InternetService`` from the full ``service_columns``
    list — identical to the ``BINARY_SERVICE_COLUMNS`` constant in
    ``reshape_telco.py``.
    """
    return [c for c in isc.service_columns if c != _INTERNET_SERVICE_COLUMN]


class TelcoAdapter(DataAdapter):
    """Wraps the Telco CSV pipeline behind the :class:`~src.data.base_adapter.DataAdapter` interface.

    Args:
        config: Full config dict from :func:`~src.utils.config.load_config`.
            Defaults to the project-default config when ``None``.
        customer_schema: Validates the customers DataFrame before returning it.
        product_schema: Validates the products DataFrame before returning it.
    """

    def __init__(
        self,
        config: dict | None = None,
        customer_schema: CustomerSchema | None = None,
        product_schema: ProductSchema | None = None,
    ) -> None:
        from src.utils.config import (  # local import avoids circular at module level
            build_customer_schema_from_config,
            build_product_schema_from_config,
        )

        self._config: dict = config or load_config()
        self._isc: InteractionSourceConfig = get_interaction_source_config(self._config)

        resolved_customer_schema = customer_schema or build_customer_schema_from_config(
            self._config
        )
        resolved_product_schema = product_schema or build_product_schema_from_config(
            self._config
        )
        super().__init__(
            customer_schema=resolved_customer_schema,
            product_schema=resolved_product_schema,
        )

    # ------------------------------------------------------------------
    # DataAdapter interface
    # ------------------------------------------------------------------

    def load_raw(self) -> pd.DataFrame:
        """Load and lightly clean the raw Telco CSV.

        Delegates entirely to :func:`~src.data.load_telco.load_raw_telco`:
        reads ``data/raw/telco_customer_churn.csv``, strips column whitespace,
        and coerces ``TotalCharges`` to numeric.

        The result is stored on ``self._raw`` for the ``to_*`` methods to use.
        """
        self._raw = load_raw_telco(self._config)
        return self._raw

    def to_customers(self) -> pd.DataFrame:
        """Build and validate the customers table.

        Mirrors :func:`reshape_telco.build_customers_table` exactly, plus
        centralises the ``customerID → customer_id`` rename that previously
        lived ad-hoc in ``src/api/ui.py`` and pipeline scripts.

        Returns:
            DataFrame with columns:
            ``customer_id``, ``gender``, ``SeniorCitizen``, ``Partner``,
            ``Dependents``, ``tenure``, ``Contract``, ``PaperlessBilling``,
            ``PaymentMethod``, ``MonthlyCharges``, ``TotalCharges``, ``Churn``.

        Raises:
            ValueError: If the schema validation fails.
        """
        raw = self._ensure_raw()
        available = [c for c in _CUSTOMER_COLUMNS if c in raw.columns]
        df = raw[available].copy()
        df = df.rename(columns={"customerID": "customer_id"})
        logger.info(f"Built customers table: {len(df):,} rows")

        # Validate structure and values before returning.
        self.customer_schema.validate_values(df)
        return df

    def to_products(self) -> pd.DataFrame:
        """Build and validate the static product catalog.

        Mirrors :func:`reshape_telco.build_products_table` exactly.

        The binary-service columns are derived from ``InteractionSourceConfig``
        (minus ``InternetService``).  ``InternetService`` is expanded into two
        products: ``InternetService_DSL`` and ``InternetService_Fiber``.

        Returns:
            DataFrame with columns: ``product_id``, ``product_name``, ``category``
            where ``category`` is ``"Core"`` or ``"Add-on"``.

        Raises:
            ValueError: If the schema validation fails.
        """
        binary_cols = _binary_service_columns(self._isc)
        products: list[dict] = []

        for col in binary_cols:
            products.append(
                {
                    "product_id": col,
                    "product_name": _humanize(col),
                    "category": (
                        "Core" if col in ("PhoneService", "MultipleLines") else "Add-on"
                    ),
                }
            )

        products.extend(_INTERNET_PRODUCTS)

        df = pd.DataFrame(products)
        logger.info(f"Built products table: {len(df)} products")

        self.product_schema.validate_values(df)
        return df

    def to_interactions(self) -> pd.DataFrame:
        """Build and validate the long-format interaction table.

        Mirrors :func:`reshape_telco.build_interactions_table` exactly, but
        reads the binary service column list and negative-value set from
        ``InteractionSourceConfig`` instead of module-level constants.

        One row is emitted per (customer, product) pair where the customer
        is currently subscribed to that product.

        Returns:
            DataFrame with columns: ``customer_id``, ``product_id``.

        Raises:
            ValueError: If the schema validation fails.
        """
        raw = self._ensure_raw()
        binary_cols = _binary_service_columns(self._isc)
        negative: set[str] = set(self._isc.negative_values)

        rows: list[dict] = []
        for _, row in raw.iterrows():
            customer_id: str = row["customerID"]

            # Binary Yes/No columns
            for col in binary_cols:
                if col in raw.columns and row[col] not in negative:
                    rows.append({"customer_id": customer_id, "product_id": col})

            # Categorical InternetService → two distinct product IDs
            internet = row.get(_INTERNET_SERVICE_COLUMN)
            if internet == "DSL":
                rows.append(
                    {"customer_id": customer_id, "product_id": "InternetService_DSL"}
                )
            elif internet == "Fiber optic":
                rows.append(
                    {"customer_id": customer_id, "product_id": "InternetService_Fiber"}
                )

        df = pd.DataFrame(rows)
        logger.info(f"Built interactions table: {len(df):,} customer-product rows")

        self.interaction_schema.validate(df)
        return df

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_raw(self) -> pd.DataFrame:
        """Return ``self._raw``, calling ``load_raw()`` automatically if needed."""
        if self._raw is None:
            self.load_raw()
        return self._raw  # type: ignore[return-value]
