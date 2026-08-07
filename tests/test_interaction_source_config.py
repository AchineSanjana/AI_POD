"""Tests for the interaction_source config block (Fix 4 prerequisite).

Verifies that:
- config.yaml parses into an InteractionSourceConfig without error.
- The parsed values match the constants currently hardcoded in reshape_telco.py
  (BINARY_SERVICE_COLUMNS and NEGATIVE_VALUES), ensuring the YAML block is a
  faithful source-of-truth before reshape_telco.py is wired up.
"""

from __future__ import annotations

import pytest

# pyrefly: ignore [missing-import]
from src.utils.config import (
    InteractionSourceConfig,
    get_interaction_source_config,
    load_config,
)

# ---------------------------------------------------------------------------
# Constants copied verbatim from reshape_telco.py — used as the ground truth
# ---------------------------------------------------------------------------

_BINARY_SERVICE_COLUMNS = [
    "PhoneService",
    "MultipleLines",
    "OnlineSecurity",
    "OnlineBackup",
    "DeviceProtection",
    "TechSupport",
    "StreamingTV",
    "StreamingMovies",
]

# reshape_telco also uses InternetService in service_columns (it drives the
# product table), even though it is not in BINARY_SERVICE_COLUMNS.
_ALL_SERVICE_COLUMNS = ["InternetService"] + _BINARY_SERVICE_COLUMNS

_NEGATIVE_VALUES = {"No", "No internet service", "No phone service"}

_POSITIVE_VALUES = {"Yes", "DSL", "Fiber optic"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config()


@pytest.fixture(scope="module")
def isc(cfg: dict) -> InteractionSourceConfig:
    return get_interaction_source_config(cfg)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInteractionSourceConfigParsing:
    def test_returns_correct_type(self, isc: InteractionSourceConfig) -> None:
        assert isinstance(isc, InteractionSourceConfig)

    def test_service_columns_is_list(self, isc: InteractionSourceConfig) -> None:
        assert isinstance(isc.service_columns, list)
        assert len(isc.service_columns) > 0

    def test_positive_values_is_list(self, isc: InteractionSourceConfig) -> None:
        assert isinstance(isc.positive_values, list)
        assert len(isc.positive_values) > 0

    def test_negative_values_is_list(self, isc: InteractionSourceConfig) -> None:
        assert isinstance(isc.negative_values, list)
        assert len(isc.negative_values) > 0


class TestInteractionSourceMatchesHardcodedConstants:
    """Assert the YAML block is consistent with the values in reshape_telco.py."""

    def test_service_columns_contain_all_binary_columns(
        self, isc: InteractionSourceConfig
    ) -> None:
        """Every BINARY_SERVICE_COLUMN from reshape_telco.py must be present."""
        missing = set(_BINARY_SERVICE_COLUMNS) - set(isc.service_columns)
        assert not missing, f"service_columns missing: {missing}"

    def test_service_columns_contain_internet_service(
        self, isc: InteractionSourceConfig
    ) -> None:
        """InternetService must be listed (it drives the products table too)."""
        assert "InternetService" in isc.service_columns

    def test_service_columns_full_match(self, isc: InteractionSourceConfig) -> None:
        """Exact set match — no extra or missing columns vs. _ALL_SERVICE_COLUMNS."""
        assert set(isc.service_columns) == set(_ALL_SERVICE_COLUMNS), (
            f"Mismatch.\n"
            f"  YAML has : {sorted(isc.service_columns)}\n"
            f"  Expected : {sorted(_ALL_SERVICE_COLUMNS)}"
        )

    def test_negative_values_match(self, isc: InteractionSourceConfig) -> None:
        """YAML negative_values must equal NEGATIVE_VALUES from reshape_telco.py."""
        assert set(isc.negative_values) == _NEGATIVE_VALUES, (
            f"Mismatch.\n"
            f"  YAML has : {set(isc.negative_values)}\n"
            f"  Expected : {_NEGATIVE_VALUES}"
        )

    def test_positive_values_match(self, isc: InteractionSourceConfig) -> None:
        """YAML positive_values must equal the expected set."""
        assert set(isc.positive_values) == _POSITIVE_VALUES, (
            f"Mismatch.\n"
            f"  YAML has : {set(isc.positive_values)}\n"
            f"  Expected : {_POSITIVE_VALUES}"
        )

    def test_positive_and_negative_are_disjoint(
        self, isc: InteractionSourceConfig
    ) -> None:
        overlap = set(isc.positive_values) & set(isc.negative_values)
        assert not overlap, f"positive/negative overlap: {overlap}"


class TestGetInteractionSourceConfigErrors:
    def test_missing_block_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            get_interaction_source_config({"data": {}})

    def test_missing_negative_values_raises_key_error(self) -> None:
        cfg = {
            "data": {
                "interaction_source": {
                    "service_columns": ["PhoneService"],
                    "positive_values": ["Yes"],
                    # negative_values intentionally absent
                }
            }
        }
        with pytest.raises(KeyError):
            get_interaction_source_config(cfg)
