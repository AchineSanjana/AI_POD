"""Regression and accuracy test suite for auto-generated tenant configs.

Compares auto-generated tenant configurations from raw data files against
existing, manually-crafted configs in config.yaml for telco_default and
fixture_ecommerce, categorizing:
1. Exact matches (dtype, allowed_values)
2. Detail differences (e.g. allowed_values ordering)
3. Needs_review false positives (over-cautious flags on valid manual features)
4. Mispredicted fields / false negatives (genuine misses)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from src.onboarding.config_generator import generate_tenant_config
from src.onboarding.profiler import ProfileReport, profile_dataframe
from src.utils.config import DEFAULT_CONFIG_PATH

# ---------------------------------------------------------------------------
# Comparison Data Structure and Logic
# ---------------------------------------------------------------------------


@dataclass
class ConfigComparisonReport:
    """Structured diff report comparing auto-generated vs manual tenant configs."""

    tenant_id: str
    exact_matches: list[str] = field(default_factory=list)
    detail_differences: list[dict[str, Any]] = field(default_factory=list)
    needs_review_false_positives: list[dict[str, Any]] = field(
        default_factory=list
    )
    mispredicted_fields: list[dict[str, Any]] = field(default_factory=list)
    service_columns_auto: list[str] = field(default_factory=list)
    service_columns_manual: list[str] = field(default_factory=list)

    def format_report(self) -> str:
        """Format human-readable comparison summary."""
        lines = [
            "\n=======================================================",
            f"AUTO-CONFIG ACCURACY REPORT: {self.tenant_id.upper()}",
            "=======================================================",
            f"1. Exact Field Matches ({len(self.exact_matches)}):",
        ]
        if self.exact_matches:
            for f_name in self.exact_matches:
                lines.append(f"   [+] {f_name}")
        else:
            lines.append("   (None)")

        lines.append(
            f"\n2. Detail Differences ({len(self.detail_differences)}):"
        )
        if self.detail_differences:
            for diff in self.detail_differences:
                lines.append(f"   [~] {diff['field']}: {diff['reason']}")
        else:
            lines.append("   (None)")

        lines.append(
            f"\n3. 'needs_review' Flags (Over-cautious / False Positives) "
            f"({len(self.needs_review_false_positives)}):"
        )
        if self.needs_review_false_positives:
            for fp in self.needs_review_false_positives:
                lines.append(
                    f"   [?] {fp['field']}: confidence={fp['confidence']:.2f}, "
                    f"suggested={fp['suggested_dtype']}, "
                    f"manual={fp['manual_dtype']}"
                )
                lines.append(f"       Reason: {fp['reason']}")
        else:
            lines.append("   (None)")

        lines.append(
            f"\n4. Mispredicted Fields / False Negatives "
            f"({len(self.mispredicted_fields)}):"
        )
        if self.mispredicted_fields:
            for fn in self.mispredicted_fields:
                lines.append(f"   [-] {fn['field']}: {fn['reason']}")
        else:
            lines.append("   (None)")

        lines.append("\n5. Service Columns:")
        lines.append(
            f"   Auto Detected ({len(self.service_columns_auto)}): "
            f"{self.service_columns_auto}"
        )
        lines.append(
            f"   Manual Config ({len(self.service_columns_manual)}): "
            f"{self.service_columns_manual}"
        )
        lines.append("=======================================================\n")
        return "\n".join(lines)


def compare_auto_vs_manual_config(
    auto_cfg: dict[str, Any],
    manual_cfg: dict[str, Any],
    report: ProfileReport,
    tenant_id: str,
) -> ConfigComparisonReport:
    """Compare auto-generated config against existing manually-written config."""
    comp = ConfigComparisonReport(tenant_id=tenant_id)

    manual_features = {
        f["name"]: f for f in manual_cfg.get("customers", {}).get("features", [])
    }
    auto_features = {
        f["name"]: f for f in auto_cfg.get("customers", {}).get("features", [])
    }
    needs_review_map = {c.name: c for c in report if c.needs_review}

    auto_service_cols = (
        auto_cfg.get("interactions", {}).get("service_columns", [])
    )
    manual_service_cols = (
        manual_cfg.get("interactions", {}).get("service_columns", [])
    )
    comp.service_columns_auto = list(auto_service_cols)
    comp.service_columns_manual = list(manual_service_cols)

    # 1. Compare customer features in manual config
    for field_name, m_feat in manual_features.items():
        m_dtype = m_feat.get("dtype")
        m_allowed = m_feat.get("allowed_values")

        if field_name in auto_features:
            a_feat = auto_features[field_name]
            a_dtype = a_feat.get("dtype")
            a_allowed = a_feat.get("allowed_values")

            if m_dtype == a_dtype:
                if m_allowed == a_allowed:
                    comp.exact_matches.append(field_name)
                elif m_allowed is not None and a_allowed is not None:
                    if set(m_allowed) == set(a_allowed):
                        comp.detail_differences.append(
                            {
                                "field": field_name,
                                "reason": (
                                    f"allowed_values ordering differs: "
                                    f"auto={a_allowed} vs manual={m_allowed}"
                                ),
                            }
                        )
                    else:
                        comp.detail_differences.append(
                            {
                                "field": field_name,
                                "reason": (
                                    f"allowed_values subset differs: "
                                    f"auto={a_allowed} vs manual={m_allowed}"
                                ),
                            }
                        )
                else:
                    comp.detail_differences.append(
                        {
                            "field": field_name,
                            "reason": (
                                f"allowed_values presence differs: "
                                f"auto={a_allowed} vs manual={m_allowed}"
                            ),
                        }
                    )
            else:
                comp.mispredicted_fields.append(
                    {
                        "field": field_name,
                        "reason": f"Dtype mismatch: manual={m_dtype} vs auto={a_dtype}",
                    }
                )
        else:
            # Field in manual customers was not placed in auto customers
            is_service = field_name in auto_service_cols
            comp.mispredicted_fields.append(
                {
                    "field": field_name,
                    "reason": (
                        "Not in auto customer features "
                        f"(in auto service columns: {is_service})"
                    ),
                }
            )

    # 2. Identify needs_review false positives
    for col_name, col in needs_review_map.items():
        if col_name in manual_features:
            m_dtype = manual_features[col_name].get("dtype")
            comp.needs_review_false_positives.append(
                {
                    "field": col_name,
                    "suggested_dtype": col.suggested_dtype,
                    "confidence": col.confidence_score,
                    "manual_dtype": m_dtype,
                    "reason": col.review_reason,
                }
            )

    return comp


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


def test_auto_config_regression_telco_default():
    """Compare auto-generated telco config against manual telco_default config."""
    raw_path = Path("data/raw/telco_customer_churn.csv")
    if not raw_path.exists():
        pytest.skip(f"{raw_path} not found")

    with open(DEFAULT_CONFIG_PATH, encoding="utf-8") as f:
        full_config = yaml.safe_load(f)

    manual_cfg = full_config["tenants"]["telco_default"]

    df = pd.read_csv(raw_path)
    report = profile_dataframe(df)
    auto_cfg = generate_tenant_config(report, "telco_default", str(raw_path))

    comp_report = compare_auto_vs_manual_config(
        auto_cfg=auto_cfg,
        manual_cfg=manual_cfg,
        report=report,
        tenant_id="telco_default",
    )

    print(comp_report.format_report())

    # Baseline Assertions:
    # 1. Customer ID matches
    assert auto_cfg["customers"]["id_column"] == manual_cfg["customers"]["id_column"]

    # 2. Key numeric/categorical fields matched accurately
    assert "tenure" in comp_report.exact_matches
    assert "MonthlyCharges" in comp_report.exact_matches
    assert "TotalCharges" in comp_report.exact_matches
    assert "SeniorCitizen" in comp_report.exact_matches or any(
        d["field"] == "SeniorCitizen" for d in comp_report.detail_differences
    )

    # 3. Contract, PaymentMethod, gender captured
    matched_or_diff = comp_report.exact_matches + [
        d["field"] for d in comp_report.detail_differences
    ]
    assert "Contract" in matched_or_diff
    assert "gender" in matched_or_diff
    assert "PaymentMethod" in matched_or_diff

    # 4. SeniorCitizen was flagged for review due to only having 0/1 values
    assert any(
        fp["field"] == "SeniorCitizen"
        for fp in comp_report.needs_review_false_positives
    )

    # 5. Service columns detected
    assert len(comp_report.service_columns_auto) >= 9


def test_auto_config_regression_fixture_ecommerce():
    """Compare auto-generated ecommerce config against manual fixture_ecommerce."""
    raw_path = Path("data/raw/fixture_ecommerce.csv")
    if not raw_path.exists():
        pytest.skip(f"{raw_path} not found")

    with open(DEFAULT_CONFIG_PATH, encoding="utf-8") as f:
        full_config = yaml.safe_load(f)

    manual_cfg = full_config["tenants"]["fixture_ecommerce"]

    df = pd.read_csv(raw_path)
    report = profile_dataframe(df)
    auto_cfg = generate_tenant_config(report, "fixture_ecommerce", str(raw_path))

    comp_report = compare_auto_vs_manual_config(
        auto_cfg=auto_cfg,
        manual_cfg=manual_cfg,
        report=report,
        tenant_id="fixture_ecommerce",
    )

    print(comp_report.format_report())

    # Baseline Assertions:
    # 1. Primary ID matches
    assert auto_cfg["customers"]["id_column"] == manual_cfg["customers"]["id_column"]

    # 2. Numeric features matched
    assert "signup_days" in comp_report.exact_matches
    assert "monthly_spend" in comp_report.exact_matches

    # 3. Categorical plan_type matched
    matched_or_diff = comp_report.exact_matches + [
        d["field"] for d in comp_report.detail_differences
    ]
    assert "plan_type" in matched_or_diff

    # 4. Binary service columns matched exactly
    assert set(comp_report.service_columns_auto) == set(
        comp_report.service_columns_manual
    )
