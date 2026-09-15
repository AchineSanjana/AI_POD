"""TelcoAdapter — thin backward-compatibility wrapper around GenericConfigAdapter for Telco dataset."""

from __future__ import annotations

import pandas as pd

from typing import TYPE_CHECKING, Any

# pyrefly: ignore [missing-import]
from src.core.schema import CustomerSchema, ProductSchema
# pyrefly: ignore [missing-import]
from src.data.adapters.generic_config_adapter import GenericConfigAdapter
if TYPE_CHECKING:
    from src.storage.base_storage import StorageBackend
# pyrefly: ignore [missing-import]
from src.data.interaction_extraction import (
    _INTERNET_PRODUCTS,
    _INTERNET_SERVICE_COLUMN,
    _binary_service_columns,
    _humanize,
)
# pyrefly: ignore [missing-import]
from src.utils.config import (
    InteractionSourceConfig,
    get_interaction_source_config,
    get_tenant_config,
    load_config,
)
# pyrefly: ignore [missing-import]
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Columns included in the customers table (raw column names before rename).
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


class TelcoAdapter(GenericConfigAdapter):
    """Wraps the Telco CSV pipeline behind the DataAdapter interface.

    Deprecation Notice:
        TelcoAdapter is retained as a thin wrapper around GenericConfigAdapter for
        backward compatibility. Prefer using GenericConfigAdapter(get_tenant_config(config, "telco_default")) directly.

    Args:
        config: Full config dict from :func:`~src.utils.config.load_config`.
            Defaults to project-default config when ``None``.
        customer_schema: Validates customers DataFrame before returning.
        product_schema: Validates products DataFrame before returning.
    """

    def __init__(
        self,
        config: dict | None = None,
        customer_schema: CustomerSchema | None = None,
        product_schema: ProductSchema | None = None,
        storage: Any = None,
    ) -> None:
        cfg = config or load_config()
        tenant_config = get_tenant_config(cfg, "telco_default")

        super().__init__(
            tenant_config=tenant_config,
            customer_schema=customer_schema,
            product_schema=product_schema,
            storage=storage,
        )
        self._config: dict = cfg
        self._isc: InteractionSourceConfig = get_interaction_source_config(cfg)
