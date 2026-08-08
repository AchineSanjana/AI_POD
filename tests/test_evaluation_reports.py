"""Tests for multi-tenant evaluation report generation and alias verification."""

from pathlib import Path
import pytest

from src.utils.config import load_config
from scripts.generate_evaluation_results import (
    DEFAULT_EVAL_REPORT_PATH,
    DOCS_DIR,
    PROOF_REPORT_PATH,
    build_tenant_evaluation_report,
    evaluate_tenant_models,
)


def test_per_tenant_evaluation_report_generation():
    """Verify per-tenant evaluation report files exist and have non-empty content."""
    telco_report = DOCS_DIR / "evaluation_results_telco_default.md"
    movie_report = DOCS_DIR / "evaluation_results_movielens_demo.md"
    default_report = DEFAULT_EVAL_REPORT_PATH
    proof_report = PROOF_REPORT_PATH

    assert telco_report.exists(), "Missing docs/evaluation_results_telco_default.md"
    assert movie_report.exists(), "Missing docs/evaluation_results_movielens_demo.md"
    assert default_report.exists(), "Missing docs/evaluation_results.md"
    assert proof_report.exists(), "Missing docs/generalization_proof.md"

    # Verify alias parity between default report and telco_default
    telco_text = telco_report.read_text(encoding="utf-8")
    default_text = default_report.read_text(encoding="utf-8")
    movie_text = movie_report.read_text(encoding="utf-8")
    proof_text = proof_report.read_text(encoding="utf-8")

    assert telco_text == default_text, "docs/evaluation_results.md should match telco_default report"
    assert "Evaluation Results (telco_default)" in telco_text
    assert "Evaluation Results (movielens_demo)" in movie_text
    assert "Multi-Tenant Generalization Proof & Evaluation Report" in proof_text
    assert "telco_default" in proof_text
    assert "movielens_demo" in proof_text
