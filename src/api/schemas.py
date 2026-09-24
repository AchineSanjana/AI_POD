"""Pydantic schemas and typed response models for versioned /v1 API endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Recommendations Schemas
# ---------------------------------------------------------------------------


class RecommendationItem(BaseModel):
    rank: int = Field(..., description="1-indexed priority ranking of recommendation")
    product_id: str = Field(..., description="Unique product or service identifier")
    product_name: str | None = Field(None, description="Human-readable product name if available")
    category: str | None = Field(None, description="Product category or tier if available")


class RecommendationsResponse(BaseModel):
    tenant_id: str = Field(..., description="Authenticated tenant identity resolved from API key")
    customer_id: str = Field(..., description="Customer ID scored for recommendations")
    recommendations: list[RecommendationItem] = Field(
        ..., description="List of top recommended items ranked by relevance"
    )


class RecommendationRequest(BaseModel):
    customer_id: str = Field(..., description="Customer ID to score")
    top_n: int = Field(5, ge=1, le=50, description="Number of recommendations to return")
    tenant_id: str | None = Field(
        None,
        description="Ignored. The tenant identity is always derived from the X-API-Key header.",
    )


# ---------------------------------------------------------------------------
# Onboarding Schemas
# ---------------------------------------------------------------------------


class OnboardUploadResponse(BaseModel):
    tenant_id: str = Field(..., description="Authenticated tenant identifier")
    file_path: str = Field(..., description="Relative destination path of uploaded raw dataset")
    rows: int = Field(..., description="Total row count of uploaded dataset")
    columns: list[str] = Field(..., description="Column names present in dataset")
    message: str = Field(..., description="Human-readable result summary")


class ColumnProfileInfo(BaseModel):
    name: str = Field(..., description="Column name")
    inferred_type: str = Field(..., description="Inferred coarse type (e.g. numeric, categorical)")
    suggested_dtype: str = Field(..., description="Suggested storage/processing dtype")
    confidence_score: float = Field(..., description="Confidence score between 0.0 and 1.0")
    needs_review: bool = Field(..., description="True if column is ambiguous and requires decision")
    review_reason: str | None = Field(None, description="Explanation why review is requested")


class OnboardValidateRequest(BaseModel):
    data_file: str | None = Field(
        None,
        description="Optional custom path to raw data file; defaults to tenant's uploaded file",
    )


class OnboardValidateResponse(BaseModel):
    tenant_id: str = Field(..., description="Authenticated tenant identifier")
    is_valid: bool = Field(..., description="True if raw dataset can be parsed and profiled")
    candidate_config: dict[str, Any] = Field(
        ..., description="Auto-generated candidate tenant configuration block"
    )
    needs_review: list[ColumnProfileInfo] = Field(
        default_factory=list, description="Columns requiring human confirmation or review"
    )
    summary: str = Field(..., description="Plain-English summary of dataset profile")


class OnboardConfirmRequest(BaseModel):
    overrides: dict[str, str] | None = Field(
        None, description="Explicit column decisions (e.g. {'PaymentMethod': 'categorical'})"
    )
    auto_accept: bool = Field(
        False, description="Accept auto-detected best guesses for all ambiguous fields"
    )
    candidate_config: dict[str, Any] | None = Field(
        None, description="Optional modified configuration block to confirm and persist"
    )


class OnboardConfirmResponse(BaseModel):
    tenant_id: str = Field(..., description="Authenticated tenant identifier")
    status: str = Field(..., description="Onboarding confirmation status ('confirmed', 'error')")
    config_saved: bool = Field(..., description="True if saved into config.yaml")
    message: str = Field(..., description="Human-readable confirmation message")


class OnboardTrainRequest(BaseModel):
    run_pipeline: bool = Field(
        True, description="Whether to execute end-to-end data transformation and model training"
    )


class OnboardTrainResponse(BaseModel):
    tenant_id: str = Field(..., description="Authenticated tenant identifier")
    status: str = Field(..., description="Training status ('queued', 'running', 'complete', 'failed')")
    status_url: str = Field(..., description="URL endpoint to poll for training status updates")
    message: str = Field(..., description="Training execution details")
    trained: bool = Field(False, description="True if model artifact was successfully generated")
    model_path: str | None = Field(None, description="Relative path to trained model artifact if complete")


class OnboardStatusResponse(BaseModel):
    tenant_id: str = Field(..., description="Authenticated tenant identifier")
    status: str = Field(
        ...,
        description="Overall onboarding/training status ('not_started', 'needs_configuration', 'ready_to_train', 'queued', 'running', 'complete', 'active', 'failed')",
    )
    has_data: bool = Field(..., description="True if raw data file is present")
    has_config: bool = Field(..., description="True if tenant configuration is saved in config.yaml")
    has_model: bool = Field(..., description="True if trained model artifact exists")
    model_path: str | None = Field(None, description="Path to trained model artifact if available")
    error: str | None = Field(None, description="Detailed error message if training failed")
    message: str = Field(..., description="Current tenant lifecycle summary")
