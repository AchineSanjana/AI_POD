"""Dataframe profiler for onboarding raw datasets.

Inspects raw pandas DataFrames and infers data types, categorical values,
null percentages, primary ID columns, binary-style service columns,
and confidence scores with ambiguity review flags.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

SuggestedDtype = Literal["numeric", "categorical", "likely_free_text_or_id"]

ID_HINTS: tuple[str, ...] = ("id", "_id", "customerid", "user", "key")
NUMERIC_HINTS: frozenset[str] = frozenset(
    {
        "amount",
        "price",
        "charge",
        "charges",
        "fee",
        "cost",
        "total",
        "count",
        "rate",
        "score",
        "tenure",
        "age",
        "salary",
        "revenue",
        "qty",
        "quantity",
        "balance",
        "num",
        "pct",
        "percent",
    }
)
DATE_HINTS: frozenset[str] = frozenset(
    {"date", "time", "timestamp", "year", "month", "day", "created", "updated"}
)
CATEGORICAL_HINTS: frozenset[str] = frozenset(
    {
        "type",
        "category",
        "status",
        "class",
        "segment",
        "method",
        "contract",
        "gender",
        "plan",
        "code",
        "tier",
        "mode",
    }
)
BINARY_TOKENS: frozenset[str] = frozenset(
    {"yes", "no", "true", "false", "1", "0", "y", "n", "t", "f"}
)


@dataclass(frozen=True)
class ColumnProfile:
    """Inferred profile and metadata for a single DataFrame column."""

    name: str
    suggested_dtype: SuggestedDtype
    null_percentage: float
    is_id_column: bool
    is_binary_service: bool
    confidence_score: float = 1.0
    needs_review: bool = False
    review_reason: str | None = None
    distinct_values: list[Any] | None = None
    unique_count: int = 0
    null_count: int = 0
    total_rows: int = 0

    @property
    def column_name(self) -> str:
        """Alias for name."""
        return self.name

    def to_dict(self) -> dict[str, Any]:
        """Convert profile to a serializable dictionary representation."""
        return {
            "name": self.name,
            "suggested_dtype": self.suggested_dtype,
            "null_percentage": self.null_percentage,
            "is_id_column": self.is_id_column,
            "is_binary_service": self.is_binary_service,
            "confidence_score": self.confidence_score,
            "needs_review": self.needs_review,
            "review_reason": self.review_reason,
            "distinct_values": self.distinct_values,
            "unique_count": self.unique_count,
            "null_count": self.null_count,
            "total_rows": self.total_rows,
        }


class ProfileReport(list[ColumnProfile]):
    """Structured report containing ColumnProfile instances for all columns.

    Inherits from ``list[ColumnProfile]`` for direct iteration and list semantics,
    while also supporting column-name lookup via ``report["col"]`` or
    ``report.get_column("col")`` and dictionary serialization via ``report.to_dict()``.
    """

    def get_column(self, name: str) -> ColumnProfile | None:
        """Find a ColumnProfile by column name, returning None if not found."""
        for col in self:
            if col.name == name:
                return col
        return None

    def __getitem__(self, item: int | slice | str) -> Any:  # type: ignore[override]
        """Support lookup by column name or integer/slice index."""
        if isinstance(item, str):
            for col in self:
                if col.name == item:
                    return col
            raise KeyError(f"Column '{item}' not found in profile report")
        return super().__getitem__(item)

    def to_dict(self) -> dict[str, dict[str, Any]]:
        """Return a dictionary mapping column names to their profile dictionaries."""
        return {col.name: col.to_dict() for col in self}

    def to_list(self) -> list[dict[str, Any]]:
        """Return a list of column profile dictionaries."""
        return [col.to_dict() for col in self]


def profile_dataframe(
    df: pd.DataFrame,
    confidence_threshold: float = 0.7,
) -> ProfileReport:
    """Inspect a raw pandas DataFrame and infer column-level profiling metadata.

    For every column in ``df``, infers:
    - **Suggested dtype**: ``"numeric"`` if >95% of non-null values parse cleanly to
      int/float, otherwise ``"categorical"`` (<= 50 unique values) or
      ``"likely_free_text_or_id"`` (> 50 unique values).
    - **Categorical values**: Distinct values found (up to 50 unique values) for
      categorical columns.
    - **Null percentage**: Proportion of nulls in the column (0.0 to 100.0).
    - **ID column detection**: Uniqueness > 98% AND column name contains ID hints
      like ``"id"``, ``"_id"``, ``"customerID"``, ``"user"``, ``"key"``
      (case-insensitive).
    - **Binary service column**: Only 2-3 distinct non-null values, at least one of
      which is commonly ``"Yes"``/``"No"``/``"1"``/``"0"``/``"True"``/``"False"``.
    - **Confidence score & review flag**: Confidence (0.0 to 1.0) assessing signal
      clarity; columns below ``confidence_threshold`` are marked ``needs_review=True``
      with a descriptive ``review_reason``.

    Parameters
    ----------
    df : pd.DataFrame
        The raw DataFrame to profile.
    confidence_threshold : float, default 0.7
        Threshold below which columns are marked ``needs_review=True``.

    Returns
    -------
    ProfileReport
        A structured report (list of ``ColumnProfile`` dataclasses) with helper lookups.
    """
    total_rows = len(df)
    profiles: list[ColumnProfile] = []

    for col in df.columns:
        col_name = str(col)
        series = df[col]

        # 1. Null statistics
        null_count = int(series.isna().sum())
        null_percentage = (null_count / total_rows * 100.0) if total_rows > 0 else 0.0

        # 2. Non-null values & uniqueness
        non_null = series.dropna()
        non_null_count = len(non_null)
        unique_non_null = list(pd.unique(non_null))
        unique_count = len(unique_non_null)

        # 3. Numeric parse check & suggested dtype
        suggested_dtype: SuggestedDtype
        distinct_values: list[Any] | None = None
        parse_rate = 0.0

        if non_null_count == 0:
            suggested_dtype = "categorical"
            distinct_values = []
        else:
            is_numeric_type = (
                pd.api.types.is_numeric_dtype(non_null)
                and not pd.api.types.is_bool_dtype(non_null)
            )

            if is_numeric_type:
                parse_rate = 1.0
            else:
                parsed = pd.to_numeric(non_null, errors="coerce")
                parse_rate = float(parsed.notna().sum()) / float(non_null_count)

            if parse_rate > 0.95:
                suggested_dtype = "numeric"
                distinct_values = None
            elif unique_count <= 50:
                suggested_dtype = "categorical"
                distinct_values = sorted(unique_non_null, key=lambda x: str(x))
            else:
                suggested_dtype = "likely_free_text_or_id"
                distinct_values = None

        # 4. ID column detection
        uniqueness_ratio = (unique_count / total_rows) if total_rows > 0 else 0.0
        col_lower = col_name.lower()
        has_id_hint = any(hint in col_lower for hint in ID_HINTS)
        is_id_column = bool(uniqueness_ratio > 0.98 and has_id_hint)

        # 5. Binary "has this service" style column detection
        normalized_vals = {str(v).strip().lower() for v in unique_non_null}
        has_binary_token = bool(normalized_vals & BINARY_TOKENS)
        is_binary_service = bool(unique_count in (2, 3) and has_binary_token)

        # 6. Confidence score & ambiguity evaluation
        confidence_score, review_reason = _evaluate_confidence(
            col_lower=col_lower,
            non_null_count=non_null_count,
            suggested_dtype=suggested_dtype,
            unique_count=unique_count,
            parse_rate=parse_rate,
            uniqueness_ratio=uniqueness_ratio,
            is_id_column=is_id_column,
            has_id_hint=has_id_hint,
            is_binary_service=is_binary_service,
        )

        needs_review = bool(confidence_score < confidence_threshold)
        if needs_review and review_reason is None:
            final_review_reason = (
                f"Confidence score ({confidence_score:.2f}) is below threshold "
                f"({confidence_threshold:.2f}) — data supports inference but column "
                f"name lacks specific pattern hints."
            )
        elif needs_review:
            final_review_reason = review_reason
        else:
            final_review_reason = None

        profiles.append(
            ColumnProfile(
                name=col_name,
                suggested_dtype=suggested_dtype,
                null_percentage=round(null_percentage, 4),
                is_id_column=is_id_column,
                is_binary_service=is_binary_service,
                confidence_score=round(confidence_score, 2),
                needs_review=needs_review,
                review_reason=final_review_reason,
                distinct_values=distinct_values,
                unique_count=unique_count,
                null_count=null_count,
                total_rows=total_rows,
            )
        )

    return ProfileReport(profiles)


def _evaluate_confidence(
    col_lower: str,
    non_null_count: int,
    suggested_dtype: SuggestedDtype,
    unique_count: int,
    parse_rate: float,
    uniqueness_ratio: float,
    is_id_column: bool,
    has_id_hint: bool,
    is_binary_service: bool,
) -> tuple[float, str | None]:
    """Calculate confidence score (0.0 to 1.0) and potential review reason."""
    # Case 1: All null values
    if non_null_count == 0:
        return (
            0.0,
            "Column contains only null values — unable to reliably infer data type.",
        )

    has_numeric_hint = any(hint in col_lower for hint in NUMERIC_HINTS)
    has_date_hint = any(hint in col_lower for hint in DATE_HINTS)
    has_categorical_hint = any(hint in col_lower for hint in CATEGORICAL_HINTS)

    # Case 2: Suggested numeric
    if suggested_dtype == "numeric":
        # Ambiguous: 2-4 distinct values in a numeric column (coded categories/flags)
        if 2 <= unique_count <= 4:
            return (
                0.50,
                f"Only {unique_count} distinct numeric values found — this might be a "
                f"category coded as numbers, not a true numeric feature.",
            )
        # Ambiguous: Marginal parse rate (2% - 5% parse failure)
        if parse_rate < 0.98:
            fail_pct = round((1.0 - parse_rate) * 100.0, 1)
            return (
                0.55,
                f"{fail_pct}% of non-null values failed numeric parsing — verify if "
                f"column is truly numeric or dirty categorical data.",
            )
        # High confidence: name matches numeric / date hints
        if has_numeric_hint or has_date_hint:
            return 0.95, None
        # Medium confidence: clean numbers, generic name
        return 0.80, None

    # Case 3: ID column
    if is_id_column:
        return 0.95, None

    # Case 4: High uniqueness without ID naming hints
    if uniqueness_ratio > 0.95 and not has_id_hint:
        return (
            0.50,
            f"High uniqueness ({uniqueness_ratio * 100.0:.1f}%) but column name lacks "
            f"clear ID naming hints — could be a primary key or high-cardinality "
            f"categorical feature.",
        )

    # Case 5: Categorical column
    if suggested_dtype == "categorical":
        if is_binary_service:
            return 0.95, None
        if has_categorical_hint:
            return 0.90, None
        return 0.80, None

    # Case 6: Likely free text or ID (> 50 unique values)
    return 0.75, None
