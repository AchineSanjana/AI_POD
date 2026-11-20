"""Similar Products module for AI_POD tenant catalogue."""

from __future__ import annotations

from src.similarity.feature_matrix import SimilarityIndex, build_similarity_index
from src.similarity.service import (
    clear_similarity_cache,
    find_similar_products,
    get_similarity_index,
)
from src.similarity.specs_parser import extract_numeric_specs, parse_specs_string

__all__ = [
    "SimilarityIndex",
    "build_similarity_index",
    "clear_similarity_cache",
    "extract_numeric_specs",
    "find_similar_products",
    "get_similarity_index",
    "parse_specs_string",
]

