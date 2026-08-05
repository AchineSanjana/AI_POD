"""Core domain types and contracts for the recommendation engine."""

from src.core.schema import (
    CustomerSchema,
    FeatureSpec,
    InteractionSchema,
    ProductSchema,
)

__all__ = [
    "CustomerSchema",
    "FeatureSpec",
    "InteractionSchema",
    "ProductSchema",
]
