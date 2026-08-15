"""Unit and integration tests for DataFrame profiler."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.onboarding.profiler import (
    ColumnProfile,
    ProfileReport,
    profile_dataframe,
)

# ---------------------------------------------------------------------------
# Synthetic Unit Tests
# ---------------------------------------------------------------------------


def test_empty_dataframe():
    """Verify handling of an empty DataFrame."""
    df = pd.DataFrame()
    report = profile_dataframe(df)
    assert isinstance(report, ProfileReport)
    assert len(report) == 0
    assert report.to_dict() == {}


def test_numeric_dtype_inference():
    """Verify numeric columns are inferred as 'numeric'."""
    df = pd.DataFrame(
        {
            "integers": list(range(25)),
            "floats": [i * 1.5 for i in range(25)],
            # 96% numbers, 4% text (24 numbers, 1 text out of 25 rows)
            "mostly_numeric_strings": [str(i) for i in range(24)] + ["corrupt"],
            # 80% numbers, 20% text (20 numbers, 5 text out of 25 rows) -> categorical
            "mixed_strings": ["10", "20", "30", "40", "N/A"] * 5,
        }
    )

    report = profile_dataframe(df)

    assert report["integers"].suggested_dtype == "numeric"
    assert report["integers"].distinct_values is None

    assert report["floats"].suggested_dtype == "numeric"
    assert report["floats"].distinct_values is None

    assert report["mostly_numeric_strings"].suggested_dtype == "numeric"
    assert report["mostly_numeric_strings"].distinct_values is None

    assert report["mixed_strings"].suggested_dtype == "categorical"
    assert report["mixed_strings"].distinct_values is not None


def test_categorical_distinct_values():
    """Verify categorical columns capture sorted distinct values up to 50."""
    df = pd.DataFrame(
        {
            "plan_type": ["Basic", "Pro", "Enterprise", "Basic", "Pro"],
            "rating": [3, 4, 5, 3, 4],  # Numeric with <= 50 uniques is still numeric
        }
    )

    report = profile_dataframe(df)

    plan_col = report["plan_type"]
    assert plan_col.suggested_dtype == "categorical"
    assert plan_col.distinct_values == ["Basic", "Enterprise", "Pro"]
    assert plan_col.unique_count == 3

    rating_col = report["rating"]
    assert rating_col.suggested_dtype == "numeric"
    assert rating_col.distinct_values is None


def test_likely_free_text_or_id():
    """Verify columns with >50 unique non-numeric values are flagged."""
    df = pd.DataFrame(
        {
            "comment_text": [f"User comment number {i}" for i in range(60)],
        }
    )

    report = profile_dataframe(df)

    comment_col = report["comment_text"]
    assert comment_col.suggested_dtype == "likely_free_text_or_id"
    assert comment_col.distinct_values is None
    assert comment_col.unique_count == 60


def test_null_percentage():
    """Verify accurate computation of null counts and percentages."""
    df = pd.DataFrame(
        {
            "no_nulls": [1, 2, 3, 4],
            "half_nulls": [1, None, 3, None],
            "all_nulls": [None, None, None, None],
        }
    )

    report = profile_dataframe(df)

    assert report["no_nulls"].null_count == 0
    assert report["no_nulls"].null_percentage == 0.0

    assert report["half_nulls"].null_count == 2
    assert report["half_nulls"].null_percentage == 50.0

    assert report["all_nulls"].null_count == 4
    assert report["all_nulls"].null_percentage == 100.0
    assert report["all_nulls"].suggested_dtype == "categorical"
    assert report["all_nulls"].distinct_values == []
    assert report["all_nulls"].confidence_score == 0.0
    assert report["all_nulls"].needs_review is True
    assert "only null values" in report["all_nulls"].review_reason.lower()


def test_id_column_detection():
    """Verify ID column detection requires >98% uniqueness AND name hints."""
    n = 100
    df = pd.DataFrame(
        {
            # 100% unique, has "id" -> ID
            "customer_id": [f"CUST_{i:04d}" for i in range(n)],
            # 100% unique, has "user" & "id" -> ID
            "userID": [f"U_{i}" for i in range(n)],
            # 100% unique, has "key" -> ID
            "session_key": [f"KEY_{i}" for i in range(n)],
            # 100% unique, NO hint -> NOT ID
            "random_notes": [f"Note_{i}" for i in range(n)],
            # 3% unique, has "id" -> NOT ID
            "department_id": ["D1", "D2", "D3", "D1", "D2"] * 20,
        }
    )

    report = profile_dataframe(df)

    assert report["customer_id"].is_id_column is True
    assert report["customer_id"].confidence_score >= 0.9
    assert report["customer_id"].needs_review is False

    assert report["userID"].is_id_column is True
    assert report["session_key"].is_id_column is True

    assert report["random_notes"].is_id_column is False
    assert report["random_notes"].needs_review is True
    assert "high uniqueness" in report["random_notes"].review_reason.lower()

    assert report["department_id"].is_id_column is False


def test_binary_service_column_detection():
    """Verify binary service column detection (2-3 distinct values with tokens)."""
    df = pd.DataFrame(
        {
            "has_phone": ["Yes", "No", "Yes", "No"],  # 2 values, Yes/No -> True
            "multiple_lines": [
                "No phone service",
                "No",
                "Yes",
                "No",
            ],  # 3 values, Yes/No -> True
            "internet": [
                "DSL",
                "Fiber optic",
                "No",
                "DSL",
            ],  # 3 values, No -> True
            "active_flag": [1, 0, 1, 0],  # 2 values, 1/0 -> True
            "contract": [
                "Month-to-month",
                "One year",
                "Two year",
                "One year",
            ],  # 3 values, no binary tokens -> False
            "payment": ["Card", "Check", "Bank", "Cash"],  # 4 values -> False
            "single_val": ["Yes", "Yes", "Yes", "Yes"],  # 1 value -> False
        }
    )

    report = profile_dataframe(df)

    assert report["has_phone"].is_binary_service is True
    assert report["multiple_lines"].is_binary_service is True
    assert report["internet"].is_binary_service is True
    assert report["active_flag"].is_binary_service is True
    assert report["contract"].is_binary_service is False
    assert report["payment"].is_binary_service is False
    assert report["single_val"].is_binary_service is False


def test_confidence_scores_and_ambiguous_columns():
    """Verify confidence scoring and ambiguous case detection."""
    df = pd.DataFrame(
        {
            # High confidence: numeric + hint "total_amount"
            "total_amount": [10.5, 20.0, 30.2, 40.8, 50.1] * 5,
            # Medium confidence: clean numeric, generic name
            "score_val": [10.5, 20.0, 30.2, 40.8, 50.1] * 5,
            # Ambiguous low confidence: 3 distinct numeric values (coded category)
            "status_code": [1, 2, 3, 1, 2] * 5,
            # Ambiguous low confidence: 2 distinct numeric values (0/1 flag)
            "SeniorCitizen": [0, 1, 0, 1, 0] * 5,
        }
    )

    report = profile_dataframe(df, confidence_threshold=0.7)

    # High confidence
    amount = report["total_amount"]
    assert amount.confidence_score >= 0.90
    assert amount.needs_review is False
    assert amount.review_reason is None

    # Medium confidence
    score = report["score_val"]
    assert score.confidence_score >= 0.75
    assert score.needs_review is False
    assert score.review_reason is None

    # Ambiguous 3 distinct numeric values
    status = report["status_code"]
    assert status.confidence_score <= 0.55
    assert status.needs_review is True
    assert "3 distinct numeric values found" in status.review_reason

    # Ambiguous 0/1 flag
    senior = report["SeniorCitizen"]
    assert senior.confidence_score <= 0.55
    assert senior.needs_review is True
    assert "2 distinct numeric values found" in senior.review_reason
    assert "category coded as numbers" in senior.review_reason


def test_configurable_confidence_threshold():
    """Verify customizable confidence threshold."""
    df = pd.DataFrame(
        {
            "feature_x": [1.1, 2.2, 3.3, 4.4, 5.5] * 5,  # confidence 0.80
        }
    )

    # With threshold 0.7, 0.80 >= 0.7 -> False
    rep_low = profile_dataframe(df, confidence_threshold=0.7)
    assert rep_low["feature_x"].confidence_score == 0.80
    assert rep_low["feature_x"].needs_review is False

    # With strict threshold 0.9, 0.80 < 0.9 -> True
    rep_high = profile_dataframe(df, confidence_threshold=0.9)
    assert rep_high["feature_x"].confidence_score == 0.80
    assert rep_high["feature_x"].needs_review is True
    assert rep_high["feature_x"].review_reason is not None


def test_report_structures_and_helpers():
    """Verify ColumnProfile and ProfileReport helper methods and properties."""
    df = pd.DataFrame({"cust_id": ["A1", "A2"], "tenure": [12, 24]})
    report = profile_dataframe(df)

    # List indexing and iteration
    assert len(report) == 2
    assert isinstance(report[0], ColumnProfile)
    assert report[0].column_name == "cust_id"

    # Name-based lookup
    cust_col = report["cust_id"]
    assert cust_col.name == "cust_id"
    assert report.get_column("cust_id") == cust_col
    assert report.get_column("unknown_col") is None

    # Key error for missing column
    with pytest.raises(KeyError, match="Column 'missing' not found"):
        _ = report["missing"]

    # Serialization
    profile_dict = cust_col.to_dict()
    assert isinstance(profile_dict, dict)
    assert profile_dict["name"] == "cust_id"
    assert "suggested_dtype" in profile_dict
    assert "confidence_score" in profile_dict
    assert "needs_review" in profile_dict
    assert "review_reason" in profile_dict

    report_dict = report.to_dict()
    assert "cust_id" in report_dict
    assert "tenure" in report_dict

    report_list = report.to_list()
    assert len(report_list) == 2
    assert report_list[0]["name"] == "cust_id"


# ---------------------------------------------------------------------------
# Telco Dataset Integration Tests
# ---------------------------------------------------------------------------


def test_telco_dataset_profiling():
    """Verify profiler inference on the Telco Customer Churn dataset fixture."""
    telco_path = Path("data/raw/telco_customer_churn.csv")
    if not telco_path.exists():
        pytest.skip("data/raw/telco_customer_churn.csv not found")

    df = pd.read_csv(telco_path)
    report = profile_dataframe(df, confidence_threshold=0.7)

    # 1. customerID as an ID column (High confidence, no review)
    customer_id = report["customerID"]
    assert customer_id.is_id_column is True
    assert customer_id.suggested_dtype == "likely_free_text_or_id"
    assert customer_id.null_count == 0
    assert customer_id.confidence_score >= 0.90
    assert customer_id.needs_review is False

    # 2. Contract as categorical with 3 distinct values
    contract = report["Contract"]
    assert contract.suggested_dtype == "categorical"
    assert contract.distinct_values == ["Month-to-month", "One year", "Two year"]
    assert contract.unique_count == 3
    assert contract.is_binary_service is False
    assert contract.confidence_score >= 0.80
    assert contract.needs_review is False

    # 3. tenure and MonthlyCharges as numeric
    tenure = report["tenure"]
    assert tenure.suggested_dtype == "numeric"
    assert tenure.is_id_column is False
    assert tenure.is_binary_service is False
    assert tenure.confidence_score >= 0.90
    assert tenure.needs_review is False

    monthly_charges = report["MonthlyCharges"]
    assert monthly_charges.suggested_dtype == "numeric"
    assert monthly_charges.is_id_column is False
    assert monthly_charges.is_binary_service is False
    assert monthly_charges.confidence_score >= 0.90
    assert monthly_charges.needs_review is False

    # TotalCharges is also numeric
    total_charges = report["TotalCharges"]
    assert total_charges.suggested_dtype == "numeric"
    assert total_charges.confidence_score >= 0.90
    assert total_charges.needs_review is False

    # 4. Ambiguous SeniorCitizen column: 0/1 coded as numeric -> needs_review=True
    senior_citizen = report["SeniorCitizen"]
    assert senior_citizen.suggested_dtype == "numeric"
    assert senior_citizen.unique_count == 2
    assert senior_citizen.confidence_score <= 0.55
    assert senior_citizen.needs_review is True
    assert senior_citizen.review_reason is not None
    assert "2 distinct numeric values found" in senior_citizen.review_reason

    # 5. Service columns as binary-style columns
    binary_service_columns = [
        "PhoneService",
        "MultipleLines",
        "InternetService",
        "OnlineSecurity",
        "OnlineBackup",
        "DeviceProtection",
        "TechSupport",
        "StreamingTV",
        "StreamingMovies",
        "Partner",
        "Dependents",
        "PaperlessBilling",
        "Churn",
    ]

    for col in binary_service_columns:
        assert report[col].is_binary_service is True, f"Failed on {col}"
        assert report[col].confidence_score >= 0.90
        assert report[col].needs_review is False

    # PaymentMethod is categorical with 4 values, not binary
    payment_method = report["PaymentMethod"]
    assert payment_method.suggested_dtype == "categorical"
    assert payment_method.unique_count == 4
    assert payment_method.is_binary_service is False
    assert payment_method.confidence_score >= 0.80
    assert payment_method.needs_review is False
