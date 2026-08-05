"""Abstract adapter for loading raw data and producing recommendation tables."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from src.core.schema import CustomerSchema, InteractionSchema, ProductSchema


class DataAdapter(ABC):
    """Convert a domain-specific raw data source into standard recommendation tables.

    Subclasses supply schema instances at construction time and implement loading
    plus conversion into customers, products, and interactions DataFrames.

    Primary-key columns ``customer_id`` and ``product_id`` must contain string
    values in all three output tables so downstream models can join and index
    rows consistently.

    The interactions table must be long-format: one row per active
    customer–product pair, with at least ``customer_id`` and ``product_id``
    columns (matching ``data/processed/interactions.csv``). Optional
    ``timestamp`` and ``weight`` columns are allowed but not required.
    """

    def __init__(
        self,
        customer_schema: CustomerSchema,
        product_schema: ProductSchema,
    ) -> None:
        self.customer_schema = customer_schema
        self.product_schema = product_schema
        self.interaction_schema = InteractionSchema()
        self._raw: Any = None

    @abstractmethod
    def load_raw(self) -> Any:
        """Load the raw data source and return it (typically also stored on ``self._raw``)."""

    @abstractmethod
    def to_customers(self) -> pd.DataFrame:
        """Build the customers table; output must pass ``customer_schema.validate()``.

        The returned DataFrame must include a string ``customer_id`` primary key
        and every feature column declared on ``customer_schema``.
        """

    @abstractmethod
    def to_products(self) -> pd.DataFrame:
        """Build the products table; output must pass ``product_schema.validate()``.

        The returned DataFrame must include a string ``product_id`` primary key
        and every feature column declared on ``product_schema``.
        """

    @abstractmethod
    def to_interactions(self) -> pd.DataFrame:
        """Build the interactions table; output must pass ``InteractionSchema.validate()``.

        Return long-format rows (one per customer–product pair) with string
        ``customer_id`` and ``product_id`` columns. This matches the shape of
        ``data/processed/interactions.csv``: only those two columns are
        required; ``timestamp`` and ``weight`` are optional.
        """

    def run(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Load raw data, convert to tables, validate, and return all three."""
        self._raw = self.load_raw()

        customers = self.to_customers()
        products = self.to_products()
        interactions = self.to_interactions()

        self.customer_schema.validate(customers)
        self.product_schema.validate(products)
        self.interaction_schema.validate(interactions)

        return customers, products, interactions
