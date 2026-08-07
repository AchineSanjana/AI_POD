"""Core domain types and contracts for the recommendation engine."""

from src.core.encoding import encode_categorical_features, encode_features
from src.core.schema import (
    CustomerSchema,
    FeatureSpec,
    InteractionSchema,
    ProductSchema,
)

__all__ = [
    "CustomerSchema",
    "encode_categorical_features",
    "encode_features",
    "FeatureSpec",
    "InteractionSchema",
    "ProductSchema",
]
