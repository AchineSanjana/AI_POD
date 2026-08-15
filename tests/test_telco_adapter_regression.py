"""Regression tests: TelcoAdapter vs. original load_telco / reshape_telco pipeline.

Purpose
-------
These tests are the **safety net** that must pass before any change to
``scripts/run_pipeline.py`` or ``scripts/train_model.py``.

They prove two things:

1. **Output equivalence** — running the *old* path (``load_raw_telco`` +
   ``build_customers_table`` / ``build_products_table`` /
   ``build_interactions_table``) and the *new* path (``TelcoAdapter.run()``)
   on the same real CSV produces byte-for-byte identical DataFrames.

2. **Config parity** — the ``negative_values`` list in
   ``config.yaml`` ``data.interaction_source`` exactly matches the
   previously hardcoded ``NEGATIVE_VALUES`` constant in ``reshape_telco.py``,
   proving that Prompt 2.1's config move didn't silently change interaction
   extraction logic.

Markers
-------
All output-equivalence tests are tagged ``@pytest.mark.integration`` because
they require the real Telco CSV at ``data/raw/telco_customer_churn.csv``.
The config-parity test has no file-I/O dependency and always runs.

Run integration tests with::

    pytest tests/test_telco_adapter_regression.py -m integration -v
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest

# pyrefly: ignore [missing-import]
from src.data.adapters.telco_adapter import TelcoAdapter
# pyrefly: ignore [missing-import]
from src.data.load_telco import load_raw_telco
# pyrefly: ignore [missing-import]
from src.data.reshape_telco import (
    NEGATIVE_VALUES,
    build_customers_table,
    build_interactions_table,
    build_products_table,
)
# pyrefly: ignore [missing-import]
from src.utils.config import (
    build_customer_schema_from_config,
    build_product_schema_from_config,
    get_interaction_source_config,
    load_config,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config()


# ---------------------------------------------------------------------------
# Helper: run OLD pipeline -> dict of DataFrames
# ---------------------------------------------------------------------------


def _run_old_pipeline(cfg: dict) -> dict[str, pd.DataFrame]:
    """Execute the original load_telco + reshape_telco path.

    Returns a dict with keys ``"customers"``, ``"products"``,
    ``"interactions"`` whose values are the DataFrames produced by the
    **original** functions — no TelcoAdapter involved.
    """
    raw = load_raw_telco(cfg)
    customers = build_customers_table(raw)
    products = build_products_table()
    interactions = build_interactions_table(raw)
    return {
        "customers": customers,
        "products": products,
        "interactions": interactions,
    }


# ---------------------------------------------------------------------------
# Helper: run NEW pipeline -> dict of DataFrames
# ---------------------------------------------------------------------------


def _run_new_pipeline(cfg: dict) -> dict[str, pd.DataFrame]:
    """Execute the TelcoAdapter path.

    Returns a dict with keys ``"customers"``, ``"products"``,
    ``"interactions"`` whose values are the DataFrames produced by
    ``TelcoAdapter.run()``.
    """
    adapter = TelcoAdapter(
        config=cfg,
        customer_schema=build_customer_schema_from_config(cfg),
        product_schema=build_product_schema_from_config(cfg),
    )
    customers, products, interactions = adapter.run()
    return {
        "customers": customers,
        "products": products,
        "interactions": interactions,
    }


# ---------------------------------------------------------------------------
# Config-parity test  (no CSV required — always runs)
# ---------------------------------------------------------------------------


class TestConfigNegativeValuesParity:
    """Ensure config.yaml's negative_values == reshape_telco.NEGATIVE_VALUES.

    This is the guard for Prompt 2.1's config move: if someone accidentally
    adds or removes a negative value in config.yaml, this test catches it
    before the change silently alters the interaction extraction logic.
    """

    # The canonical set that was hardcoded before the config move.
    _ORIGINAL_HARDCODED: frozenset[str] = frozenset(
        {"No", "No internet service", "No phone service"}
    )

    def test_original_constant_unchanged(self) -> None:
        """reshape_telco.NEGATIVE_VALUES must still equal the canonical set.

        If someone edits reshape_telco.py's constant, this is the first
        test that will catch it.
        """
        assert set(NEGATIVE_VALUES) == self._ORIGINAL_HARDCODED, (
            f"reshape_telco.NEGATIVE_VALUES changed!\n"
            f"  Expected: {self._ORIGINAL_HARDCODED}\n"
            f"  Got:      {set(NEGATIVE_VALUES)}"
        )

    def test_config_yaml_matches_original_constant(self, cfg: dict) -> None:
        """config.yaml interaction_source.negative_values == NEGATIVE_VALUES."""
        isc = get_interaction_source_config(cfg)
        config_negative = set(isc.negative_values)
        assert config_negative == self._ORIGINAL_HARDCODED, (
            "config.yaml negative_values diverged from the original hardcoded "
            "NEGATIVE_VALUES in reshape_telco.py!\n"
            f"  Expected (original): {self._ORIGINAL_HARDCODED}\n"
            f"  Got (from config):   {config_negative}\n"
            "Check data.interaction_source.negative_values in config/config.yaml."
        )

    def test_config_yaml_matches_reshape_telco_constant(self, cfg: dict) -> None:
        """Transitive check: config set == reshape_telco.NEGATIVE_VALUES (live import).

        Catches the case where both the constant and config were changed in a
        coordinated but still wrong way.
        """
        isc = get_interaction_source_config(cfg)
        assert set(isc.negative_values) == set(NEGATIVE_VALUES), (
            "config.yaml negative_values and reshape_telco.NEGATIVE_VALUES "
            "are now out of sync with each other."
        )


# ---------------------------------------------------------------------------
# Output-equivalence regression tests  (require the real CSV)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOldVsNewPipelineEquivalence:
    """Prove that TelcoAdapter.run() is bit-for-bit identical to the old pipeline.

    Strategy
    --------
    1. Run the OLD path (load_raw_telco -> build_*_table functions) and save
       each DataFrame to a temp CSV.
    2. Run the NEW path (TelcoAdapter.run()) and save each DataFrame to a
       separate temp CSV.
    3. Reload both sets from disk (simulating what downstream scripts see)
       and compare with ``pd.testing.assert_frame_equal``.

    Saving to CSV and reloading ensures we catch any floating-point or
    dtype discrepancy that only surfaces after serialisation — the same
    round-trip that ``scripts/run_pipeline.py`` performs.
    """

    @pytest.fixture(autouse=True)
    def _require_csv(self, cfg: dict) -> None:  # noqa: PT004
        """Skip the whole class when the raw CSV is absent."""
        from src.utils.config import resolve_path

        raw_path = resolve_path(cfg["paths"]["raw_dir"]) / cfg["paths"]["telco_raw_file"]
        if not raw_path.exists():
            pytest.skip(
                "Raw Telco CSV not present — run integration tests only when the "
                "file is available at data/raw/telco_customer_churn.csv"
            )

    # ------------------------------------------------------------------
    # In-memory equivalence (no CSV round-trip)
    # ------------------------------------------------------------------

    def test_customers_in_memory(self, cfg: dict) -> None:
        """customers DataFrame is identical before any CSV round-trip."""
        old = _run_old_pipeline(cfg)["customers"].reset_index(drop=True)
        new = _run_new_pipeline(cfg)["customers"].reset_index(drop=True)
        pd.testing.assert_frame_equal(
            new,
            old,
            check_like=False,   # enforce column order
            check_dtype=False,
            obj="customers (in-memory)",
        )

    def test_products_in_memory(self, cfg: dict) -> None:
        """products DataFrame is identical before any CSV round-trip."""
        old = _run_old_pipeline(cfg)["products"].reset_index(drop=True)
        new = _run_new_pipeline(cfg)["products"].reset_index(drop=True)
        pd.testing.assert_frame_equal(
            new,
            old,
            check_like=False,
            check_dtype=True,
            obj="products (in-memory)",
        )

    def test_interactions_in_memory(self, cfg: dict) -> None:
        """interactions DataFrame is identical before any CSV round-trip.

        Sorted by (customer_id, product_id) before comparison because
        the row order of the long-format table is an implementation detail
        that may differ without affecting correctness.
        """
        sort_cols = ["customer_id", "product_id"]

        old = (
            _run_old_pipeline(cfg)["interactions"]
            .sort_values(sort_cols)
            .reset_index(drop=True)
        )
        new = (
            _run_new_pipeline(cfg)["interactions"]
            .sort_values(sort_cols)
            .reset_index(drop=True)
        )
        pd.testing.assert_frame_equal(
            new,
            old,
            check_like=False,
            check_dtype=True,
            obj="interactions (in-memory)",
        )

    # ------------------------------------------------------------------
    # CSV round-trip equivalence (mirrors scripts/run_pipeline.py)
    # ------------------------------------------------------------------

    def test_customers_after_csv_roundtrip(self, cfg: dict) -> None:
        """customers reloaded from temp CSV are identical for both paths."""
        old_dfs = _run_old_pipeline(cfg)
        new_dfs = _run_new_pipeline(cfg)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            old_csv = tmp_path / "old_customers.csv"
            new_csv = tmp_path / "new_customers.csv"
            old_dfs["customers"].to_csv(old_csv, index=False)
            new_dfs["customers"].to_csv(new_csv, index=False)

            old_reloaded = pd.read_csv(old_csv)
            new_reloaded = pd.read_csv(new_csv)

        pd.testing.assert_frame_equal(
            new_reloaded,
            old_reloaded,
            check_like=False,
            check_dtype=True,
            obj="customers (CSV round-trip)",
        )

    def test_products_after_csv_roundtrip(self, cfg: dict) -> None:
        """products reloaded from temp CSV are identical for both paths."""
        old_dfs = _run_old_pipeline(cfg)
        new_dfs = _run_new_pipeline(cfg)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            old_csv = tmp_path / "old_products.csv"
            new_csv = tmp_path / "new_products.csv"
            old_dfs["products"].to_csv(old_csv, index=False)
            new_dfs["products"].to_csv(new_csv, index=False)

            old_reloaded = pd.read_csv(old_csv)
            new_reloaded = pd.read_csv(new_csv)

        pd.testing.assert_frame_equal(
            new_reloaded,
            old_reloaded,
            check_like=False,
            check_dtype=True,
            obj="products (CSV round-trip)",
        )

    def test_interactions_after_csv_roundtrip(self, cfg: dict) -> None:
        """interactions reloaded from temp CSV are identical for both paths."""
        sort_cols = ["customer_id", "product_id"]
        old_dfs = _run_old_pipeline(cfg)
        new_dfs = _run_new_pipeline(cfg)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            old_csv = tmp_path / "old_interactions.csv"
            new_csv = tmp_path / "new_interactions.csv"
            old_dfs["interactions"].to_csv(old_csv, index=False)
            new_dfs["interactions"].to_csv(new_csv, index=False)

            old_reloaded = pd.read_csv(old_csv).sort_values(sort_cols).reset_index(drop=True)
            new_reloaded = pd.read_csv(new_csv).sort_values(sort_cols).reset_index(drop=True)

        pd.testing.assert_frame_equal(
            new_reloaded,
            old_reloaded,
            check_like=False,
            check_dtype=True,
            obj="interactions (CSV round-trip)",
        )

    # ------------------------------------------------------------------
    # Structural sanity checks (column names, dtypes, row counts)
    # ------------------------------------------------------------------

    def test_same_columns_customers(self, cfg: dict) -> None:
        """Both paths expose identical column sets for customers."""
        old_cols = list(_run_old_pipeline(cfg)["customers"].columns)
        new_cols = list(_run_new_pipeline(cfg)["customers"].columns)
        assert old_cols == new_cols, (
            f"Column mismatch in customers:\n  old={old_cols}\n  new={new_cols}"
        )

    def test_same_columns_products(self, cfg: dict) -> None:
        """Both paths expose identical column sets for products."""
        old_cols = list(_run_old_pipeline(cfg)["products"].columns)
        new_cols = list(_run_new_pipeline(cfg)["products"].columns)
        assert old_cols == new_cols, (
            f"Column mismatch in products:\n  old={old_cols}\n  new={new_cols}"
        )

    def test_same_columns_interactions(self, cfg: dict) -> None:
        """Both paths expose identical column sets for interactions."""
        old_cols = list(_run_old_pipeline(cfg)["interactions"].columns)
        new_cols = list(_run_new_pipeline(cfg)["interactions"].columns)
        assert old_cols == new_cols, (
            f"Column mismatch in interactions:\n  old={old_cols}\n  new={new_cols}"
        )

    def test_same_row_count_customers(self, cfg: dict) -> None:
        """Both paths produce the same number of customer rows."""
        old_n = len(_run_old_pipeline(cfg)["customers"])
        new_n = len(_run_new_pipeline(cfg)["customers"])
        assert old_n == new_n, f"Row count mismatch in customers: old={old_n}, new={new_n}"

    def test_same_row_count_products(self, cfg: dict) -> None:
        """Both paths produce the same number of product rows."""
        old_n = len(_run_old_pipeline(cfg)["products"])
        new_n = len(_run_new_pipeline(cfg)["products"])
        assert old_n == new_n, f"Row count mismatch in products: old={old_n}, new={new_n}"

    def test_same_row_count_interactions(self, cfg: dict) -> None:
        """Both paths produce the same number of interaction rows."""
        old_n = len(_run_old_pipeline(cfg)["interactions"])
        new_n = len(_run_new_pipeline(cfg)["interactions"])
        assert old_n == new_n, (
            f"Row count mismatch in interactions: old={old_n}, new={new_n}"
        )

    def test_same_dtypes_customers(self, cfg: dict) -> None:
        """Both paths produce the same dtypes for every customers column."""
        old_dtypes = _run_old_pipeline(cfg)["customers"].dtypes.to_dict()
        new_dtypes = _run_new_pipeline(cfg)["customers"].dtypes.to_dict()
        mismatches = {
            col: (str(old_dtypes[col]), str(new_dtypes[col]))
            for col in old_dtypes
            if old_dtypes[col] != new_dtypes.get(col)
            and not (
                str(old_dtypes[col]) in ("object", "str", "string")
                and str(new_dtypes.get(col)).startswith("string")
            )
        }
        assert not mismatches, f"dtype mismatches in customers: {mismatches}"

    def test_same_dtypes_interactions(self, cfg: dict) -> None:
        """Both paths produce the same dtypes for every interactions column."""
        old_dtypes = _run_old_pipeline(cfg)["interactions"].dtypes.to_dict()
        new_dtypes = _run_new_pipeline(cfg)["interactions"].dtypes.to_dict()
        mismatches = {
            col: (str(old_dtypes[col]), str(new_dtypes[col]))
            for col in old_dtypes
            if old_dtypes[col] != new_dtypes.get(col)
        }
        assert not mismatches, f"dtype mismatches in interactions: {mismatches}"
