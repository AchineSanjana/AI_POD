"""Pydantic schemas and typed response models for versioned /v1 API endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    fallback: bool = Field(
        False,
        description="True if recommendations are fallback popularity-based rather than personalized",
    )
    reason: str | None = Field(
        None,
        description="Explanation when fallback is true: model_not_trained, unknown_customer, or no_history",
    )


class SampleCustomersResponse(BaseModel):
    tenant_id: str = Field(..., description="Authenticated tenant identifier")
    customer_ids: list[str] = Field(
        default_factory=list,
        description="List of sample customer IDs extracted from processed data",
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
    status: str = Field(..., description="Training status ('queued', 'running', 'completed', 'complete', 'failed')")
    status_url: str = Field(..., description="URL endpoint to poll for training status updates")
    message: str = Field(..., description="Training execution details")
    trained: bool = Field(False, description="True if model artifact was successfully generated")
    model_path: str | None = Field(None, description="Relative path to trained model artifact if complete")


class OnboardStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    tenant_id: str = Field(..., description="Authenticated tenant identifier")
    status: str = Field(
        ...,
        description="Overall onboarding/training status ('not_started', 'ready_to_train', 'queued', 'running', 'completed', 'complete', 'active', 'failed', 'stalled')",
    )
    ready: bool = Field(False, description="True if recommendations are ready to serve")
    has_data: bool = Field(False, description="True if raw data file is present")
    has_config: bool = Field(False, description="True if tenant configuration is saved in config.yaml")
    has_model: bool = Field(False, description="True if trained model artifact exists")
    model_path: str | None = Field(None, description="Path to trained model artifact if available")
    stage: str | None = Field(None, description="Current training pipeline stage")
    error: str | None = Field(None, description="Detailed error message if training failed")
    message: str = Field(..., description="Current tenant lifecycle summary")
    models: dict[str, str] | None = Field(None, description="Candidate model training statuses")
    metrics: dict[str, Any] | None = Field(None, description="Evaluation metrics for models")
    winner_model: str | None = Field(None, description="Display name of winning model")
    winner_key: str | None = Field(None, description="Key of winning model")
    dataset: dict[str, int] | None = Field(None, description="Dataset row counts")
    started_at: str | None = Field(None, description="UTC ISO timestamp when training started")
    updated_at: str | None = Field(None, description="UTC ISO timestamp when status was last updated")


# ---------------------------------------------------------------------------
# Tracking Schemas
# ---------------------------------------------------------------------------


class TrackEventPayload(BaseModel):
    event_type: str = Field(..., description="'view' | 'add_to_cart' | 'purchase'")
    customer_id: str | None = Field(None, description="string or null if anonymous")
    session_id: str = Field(..., description="Browser session identifier")
    product_id: str = Field(..., description="Product identifier")
    quantity: float | int | None = Field(None, description="Optional numerical quantity")
    timestamp: str | None = Field(None, description="Optional ISO-8601 timestamp")


class TrackEventAcceptedResponse(BaseModel):
    status: str = Field("accepted", description="Status confirmation")


# ---------------------------------------------------------------------------
# Key Management Schemas
# ---------------------------------------------------------------------------


class KeyDetail(BaseModel):
    key: str = Field(..., description="API key string")
    key_type: str = Field(..., description="Key permission tier: 'private' | 'public'")
    created_at: str = Field(..., description="UTC ISO timestamp of issuance")


class IssueKeysRequest(BaseModel):
    tenant_id: str = Field(..., description="Unique tenant identifier")
    private_key: str | None = Field(None, description="Optional custom private key")
    public_key: str | None = Field(None, description="Optional custom public key")


class IssueKeysResponse(BaseModel):
    status: str = Field("ok", description="Status of operation")
    tenant_id: str = Field(..., description="Tenant identifier")
    private_key: KeyDetail = Field(..., description="Issued private organization key")
    public_key: KeyDetail = Field(..., description="Issued public client key")
    sk: str = Field(..., description="Private key string convenience accessor")
    pk: str = Field(..., description="Public key string convenience accessor")


# ---------------------------------------------------------------------------
# Scheduled Retraining Schemas (EventBridge / Step 21.2)
# ---------------------------------------------------------------------------


class ScheduledRetrainTenantSummary(BaseModel):
    tenant_id: str = Field(..., description="Tenant identifier")
    tenant_type: str = Field(..., description="'new_ready', 'already_trained', 'below_threshold', or 'in_progress'")
    action: str = Field(..., description="'first_training', 'retrain', or 'skipped'")
    status: str = Field(..., description="'queued', 'running', 'skipped', 'failed', or 'complete'")
    reason: str | None = Field(None, description="Explanation for action/skip")
    message: str | None = Field(None, description="Detailed status message")


class ScheduledRetrainResponse(BaseModel):
    status: str = Field("ok", description="Overall execution status ('ok', 'partial', 'error')")
    timestamp: str = Field(..., description="UTC ISO timestamp of execution")
    total_tenants_checked: int = Field(..., description="Total tenants evaluated")
    first_trainings_triggered: int = Field(..., description="New ready tenants started on first training")
    retrainings_triggered: int = Field(..., description="Already-trained tenants started on retrain")
    skipped_in_progress: int = Field(..., description="Tenants skipped due to collision with running job")
    skipped_other: int = Field(..., description="Tenants skipped (e.g. below threshold / untrained)")
    summaries: list[ScheduledRetrainTenantSummary] = Field(..., description="Per-tenant run summary list")


class ScheduledRetrainRequest(BaseModel):
    wait_for_completion: bool = Field(False, description="Wait for background training jobs to finish before responding")
    timeout_seconds: float = Field(30.0, description="Max seconds to wait if wait_for_completion is True")
