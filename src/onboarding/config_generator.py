"""Tenant configuration generator and plain-English review summaries.

Converts DataFrame profile reports into validated tenant configuration dictionaries
compatible with config.yaml, CustomerSchema, ProductSchema, and InteractionSchema,
and generates plain-English summary reports for stakeholder review.
"""

from __future__ import annotations

from typing import Any

from src.core.schema import (
    CustomerSchema,
    FeatureSpec,
    InteractionSchema,
    ProductSchema,
)
from src.onboarding.profiler import ColumnProfile, ProfileReport
from src.utils.config import get_tenant_config

# Common positive / negative tokens for interaction source detection
POSITIVE_TOKENS: frozenset[str] = frozenset(
    {"yes", "1", "true", "y", "t", "dsl", "fiber optic"}
)
NEGATIVE_PREFIXES: tuple[str, ...] = ("no", "0", "false", "n", "f")


def generate_tenant_config(
    profile_report: ProfileReport | list[ColumnProfile],
    tenant_id: str,
    data_source_path: str,
) -> dict[str, Any]:
    """Generate a validated tenant configuration dictionary from a profile report.

    Parameters
    ----------
    profile_report : ProfileReport | list[ColumnProfile]
        Column profiling report from ``profile_dataframe``.
    tenant_id : str
        Unique identifier for the tenant.
    data_source_path : str
        Relative or absolute path to the dataset file (CSV or JSON).

    Returns
    -------
    dict[str, Any]
        A valid tenant config block ready for serialization or config.yaml.

    Raises
    ------
    ValueError
        If the profile report is empty or the generated configuration fails
        structural or schema validation.
    """
    if not profile_report:
        raise ValueError("Cannot generate tenant config from an empty profile report.")

    # 1. Data Source block
    ds_type = "json" if data_source_path.lower().endswith(".json") else "csv"
    data_source = {
        "type": ds_type,
        "path": data_source_path,
    }

    # 2. ID Column Detection
    id_candidates = [col for col in profile_report if col.is_id_column]
    if id_candidates:
        id_column = id_candidates[0].name
    else:
        # Fallback: column name containing 'id' or highest uniqueness
        named_ids = [
            col
            for col in profile_report
            if "id" in col.name.lower() and col.unique_count > 1
        ]
        if named_ids:
            id_column = named_ids[0].name
        else:
            sorted_by_uniqueness = sorted(
                profile_report,
                key=lambda c: c.unique_count,
                reverse=True,
            )
            id_column = sorted_by_uniqueness[0].name

    # 3. Customer Features block
    customer_features: list[dict[str, Any]] = []
    segmentation_candidate: str | None = None

    for col in profile_report:
        if col.name == id_column:
            continue

        dtype = "numeric" if col.suggested_dtype == "numeric" else "categorical"
        feature_entry: dict[str, Any] = {
            "name": col.name,
            "dtype": dtype,
        }

        if dtype == "categorical" and col.distinct_values:
            feature_entry["allowed_values"] = [str(v) for v in col.distinct_values]
            if len(col.distinct_values) <= 10:
                feature_entry["encoding"] = "one_hot"
        elif dtype == "numeric" and segmentation_candidate is None:
            # Candidate for segmentation (e.g. tenure, signup_days, age)
            if col.unique_count > 5:
                segmentation_candidate = col.name

        customer_features.append(feature_entry)

    # 4. Interaction Source & Service Columns
    service_cols = [
        col for col in profile_report if col.is_binary_service and col.name != id_column
    ]
    service_column_names = [col.name for col in service_cols]

    # Detect positive and negative values observed across service columns
    positive_vals: list[str] = []
    negative_vals: list[str] = []

    for col in service_cols:
        if not col.distinct_values:
            continue
        for val in col.distinct_values:
            val_str = str(val).strip()
            val_lower = val_str.lower()
            if val_lower in POSITIVE_TOKENS:
                if val_str not in positive_vals:
                    positive_vals.append(val_str)
            elif any(
                val_lower == prefix or val_lower.startswith(prefix + " ")
                for prefix in NEGATIVE_PREFIXES
            ):
                if val_str not in negative_vals:
                    negative_vals.append(val_str)

    # Defaults if none explicitly detected
    if not positive_vals:
        positive_vals = ["Yes"]
    if not negative_vals:
        negative_vals = ["No"]

    interactions = {
        "source": "custom_services",
        "service_columns": service_column_names,
        "positive_values": positive_vals,
        "negative_values": negative_vals,
    }

    # 5. Products block
    products = {
        "derived_from": "interaction_source",
        "category_column": "category",
    }

    # 6. Assemble configuration dictionary
    tenant_config: dict[str, Any] = {
        "data_source": data_source,
        "customers": {
            "id_column": id_column,
            "features": customer_features,
        },
        "products": products,
        "interactions": interactions,
    }

    if segmentation_candidate is not None:
        tenant_config["segmentation"] = {
            "field": segmentation_candidate,
            "split": "median",
        }

    # 7. Immediate validation against schemas and TenantConfig parser
    _validate_tenant_config(tenant_config, tenant_id)

    return tenant_config


def generate_review_summary(
    profile_report: ProfileReport | list[ColumnProfile],
) -> str:
    """Produce a short, plain-English summary of auto-detected dataset properties.

    Suitable for presenting to a stakeholder or reviewer before an auto-generated
    tenant configuration is accepted.

    Parameters
    ----------
    profile_report : ProfileReport | list[ColumnProfile]
        The profile report generated by ``profile_dataframe``.

    Returns
    -------
    str
        Multi-line plain-English onboarding summary.
    """
    if not profile_report:
        return "No data columns found in profile report."

    total_rows = profile_report[0].total_rows
    lines: list[str] = [
        f"Detected {total_rows:,} rows across {len(profile_report)} columns."
    ]

    # 1. Customer ID column
    id_candidates = [c for c in profile_report if c.is_id_column]
    if id_candidates:
        id_col = id_candidates[0]
        uniqueness_pct = (
            (id_col.unique_count / total_rows * 100.0) if total_rows > 0 else 0.0
        )
        conf_desc = (
            "high confidence"
            if id_col.confidence_score >= 0.90
            else (
                "medium confidence"
                if id_col.confidence_score >= 0.70
                else "low confidence"
            )
        )
        lines.append(
            f"Customer ID column: '{id_col.name}' "
            f"({uniqueness_pct:.1f}% unique values) — {conf_desc}."
        )
    else:
        lines.append(
            "Customer ID column: No explicit ID column detected with high confidence."
        )

    # 2. Numeric customer fields
    numeric_cols = [
        c.name
        for c in profile_report
        if c.suggested_dtype == "numeric" and not c.is_id_column
    ]
    if numeric_cols:
        plural = "s" if len(numeric_cols) > 1 else ""
        lines.append(
            f"Found {len(numeric_cols)} numeric customer field{plural}: "
            f"{', '.join(numeric_cols)}."
        )

    # 3. Categorical fields (non-service, non-ID)
    cat_cols = [
        c
        for c in profile_report
        if c.suggested_dtype == "categorical"
        and not c.is_id_column
        and not c.is_binary_service
    ]
    if cat_cols:
        cat_details = []
        for c in cat_cols:
            if c.distinct_values:
                val_sample = ", ".join(str(v) for v in c.distinct_values[:5])
                if len(c.distinct_values) > 5:
                    val_sample += f", ... (+{len(c.distinct_values) - 5} more)"
                cat_details.append(
                    f"{c.name} ({len(c.distinct_values)} values: {val_sample})"
                )
            else:
                cat_details.append(f"{c.name} ({c.unique_count} values)")
        plural = "s" if len(cat_cols) > 1 else ""
        lines.append(
            f"Found {len(cat_cols)} categorical field{plural}: "
            f"{'; '.join(cat_details)}."
        )

    # 4. Binary service-style columns
    service_cols = [
        c.name for c in profile_report if c.is_binary_service and not c.is_id_column
    ]
    if service_cols:
        lines.append(
            f"Found {len(service_cols)} binary service-style columns that will "
            f"be treated as products: {', '.join(service_cols)}."
        )

    # 5. Columns needing review
    review_cols = [c for c in profile_report if c.needs_review]
    if review_cols:
        count = len(review_cols)
        noun = "column" if count == 1 else "columns"
        verb = "needs" if count == 1 else "need"
        lines.append(f"{count} {noun} {verb} your review before we proceed:")
        for c in review_cols:
            reason = c.review_reason or "Low confidence inference."
            lines.append(f"  - '{c.name}': {reason}")
    else:
        lines.append(
            "All columns inferred with high confidence — no manual review needed."
        )

    return "\n".join(lines)


def _validate_tenant_config(config: dict[str, Any], tenant_id: str) -> None:
    """Validate generated tenant config structure against schemas and parser."""
    # 1. Structural checks
    required_sections = ("data_source", "customers", "products", "interactions")
    for section in required_sections:
        if section not in config:
            raise ValueError(f"Generated config missing required section '{section}'")

    # 2. CustomerSchema validation
    customer_block = config["customers"]
    if not customer_block.get("id_column"):
        raise ValueError("Generated config missing 'customers.id_column'")
    if not customer_block.get("features"):
        raise ValueError(
            "Generated config must have at least one feature in 'customers.features'"
        )

    try:
        feature_specs = [
            FeatureSpec(
                name=f["name"],
                dtype=f["dtype"],
                allowed_values=f.get("allowed_values"),
                encoding=f.get("encoding", "passthrough"),
            )
            for f in customer_block["features"]
        ]
        CustomerSchema(features=feature_specs)
    except Exception as e:
        raise ValueError(f"Invalid CustomerSchema generated: {e}") from e

    # 3. ProductSchema validation
    prod_block = config["products"]
    cat_col = prod_block.get("category_column", "category")
    try:
        category_spec = FeatureSpec(
            name=cat_col,
            dtype="categorical",
            allowed_values=["Core", "Add-on"] if cat_col == "category" else None,
            encoding="one_hot",
        )
        ProductSchema(category=category_spec)
    except Exception as e:
        raise ValueError(f"Invalid ProductSchema generated: {e}") from e

    # 4. InteractionSchema validation
    try:
        InteractionSchema()
    except Exception as e:
        raise ValueError(f"Invalid InteractionSchema: {e}") from e

    # 5. Parser validation via get_tenant_config
    full_config_mock = {"tenants": {tenant_id: config}}
    try:
        get_tenant_config(full_config_mock, tenant_id)
    except Exception as e:
        raise ValueError(
            f"Generated tenant config failed get_tenant_config validation: {e}"
        ) from e
