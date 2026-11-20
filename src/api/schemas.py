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
    price: float | None = Field(None, description="Product price if available")
    image_url: str | None = Field(None, description="Product image URL if available")


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


class SimilarProductItem(BaseModel):
    rank: int = Field(..., description="1-indexed priority ranking of similar product")
    product_id: str = Field(..., description="Unique product or service identifier")
    product_name: str = Field(..., description="Product display name")
    category: str | None = Field(None, description="Product category if available")
    brand: str | None = Field(None, description="Product brand if available")
    price: float | None = Field(None, description="Product price if available")
    image_url: str | None = Field(None, description="Product image URL if available")
    similarity: float = Field(..., description="Similarity score between 0.0 and 1.0 (rounded)")
    reasons: list[str] = Field(default_factory=list, description="Explanations for similarity recommendation")


class SimilarProductsResponse(BaseModel):
    tenant_id: str = Field(..., description="Authenticated tenant identifier")
    product_id: str = Field(..., description="Target product identifier queried")
    product_name: str = Field(..., description="Target product name")
    similar: list[SimilarProductItem] = Field(
        default_factory=list, description="Ranked list of similar products"
    )
    fallback: bool = Field(False, description="Whether fallback recommendations were used")
    reason: str | None = Field(
        None,
        description="Explanation when fallback is true: unknown_product, inactive_product, or limited_product_data",
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


# ---------------------------------------------------------------------------
# Dashboard Schemas
# ---------------------------------------------------------------------------


class DashboardDatasetStats(BaseModel):
    customers: int | None = Field(None, description="Total unique customers in dataset")
    products: int | None = Field(None, description="Total unique products in dataset")
    interactions: int | None = Field(None, description="Total recorded interactions in dataset")


class DashboardModelMetrics(BaseModel):
    ndcg: float | None = Field(None, description="NDCG@5 ranking metric")
    precision: float | None = Field(None, description="Precision@5 recommendation precision")
    recall: float | None = Field(None, description="Recall@5 recommendation recall")


class DashboardOverviewResponse(BaseModel):
    tenant_id: str = Field(..., description="Tenant identifier")
    status: str = Field("not_started", description="Training/model status: 'completed', 'running', 'queued', 'failed', 'stalled', 'not_started'")
    ready: bool = Field(False, description="Whether a trained model is ready for live serving")
    winning_model: str | None = Field(None, description="Display name of winning model")
    winner_key: str | None = Field(None, description="Key identifier of winning model")
    metrics: DashboardModelMetrics | None = Field(None, description="Winning model metrics")
    dataset_stats: DashboardDatasetStats | None = Field(None, description="Dataset size statistics")
    requests_today: int = Field(0, description="Total recommendation requests served today (UTC)")
    active_key_count: int = Field(0, description="Number of active API keys issued for tenant")
    last_trained: str | None = Field(None, description="ISO timestamp of last training completion")


class DashboardModelLeaderboardItem(BaseModel):
    id: str = Field(..., description="Model identifier: 'xgboost', 'hybrid', 'collaborative', 'content'")
    name: str = Field(..., description="Display name of the model")
    ndcg: float | None = Field(None, description="NDCG@5 ranking score")
    precision: float | None = Field(None, description="Precision@5 score")
    recall: float | None = Field(None, description="Recall@5 score")
    status: str = Field("not_started", description="Model status: 'done', 'failed', 'training', 'stalled', 'queued', 'not_started'")
    is_winner: bool = Field(False, description="Whether this model is the deployed tournament winner")
    color: str | None = Field(None, description="UI accent color for model display")


class DashboardModelsResponse(BaseModel):
    tenant_id: str = Field(..., description="Tenant identifier")
    status: str = Field("not_started", description="Overall training status")
    winner_key: str | None = Field(None, description="Winning model key")
    winner_name: str | None = Field(None, description="Winning model display name")
    winner_metrics: DashboardModelMetrics | None = Field(None, description="Winning model metrics")
    models: list[DashboardModelLeaderboardItem] = Field(default_factory=list, description="Leaderboard of candidate models")
    dataset_stats: DashboardDatasetStats | None = Field(None, description="Dataset size statistics")
    last_trained: str | None = Field(None, description="ISO timestamp of last training")


class DashboardDailyEvent(BaseModel):
    date: str = Field(..., description="Date (YYYY-MM-DD)")
    day: str = Field(..., description="Day label (e.g. 'Mon', 'Tue' or 'MM/DD')")
    views: int = Field(0, description="View event count")
    clicks: int = Field(0, description="Click event count")
    cart_adds: int = Field(0, description="Add to cart event count")
    purchases: int = Field(0, description="Purchase event count")
    total: int = Field(0, description="Total events on this date")


class DashboardTopProduct(BaseModel):
    product_id: str = Field(..., description="Product ID")
    name: str = Field(..., description="Product title/display name")
    recs: int = Field(0, description="Number of times recommended")


class DashboardAnalyticsResponse(BaseModel):
    tenant_id: str = Field(..., description="Tenant identifier")
    days: int = Field(7, description="Number of days covered")
    total_events: int = Field(0, description="Total interaction events in period")
    total_recommendations: int = Field(0, description="Total recommendations served in period")
    requests_today: int = Field(0, description="Recommendations served today")
    fallback_rate: float | None = Field(None, description="Fallback recommendation percentage (0.0 to 1.0)")
    ctr: float | None = Field(None, description="Click-through rate (null if untracked)")
    events_by_day: list[DashboardDailyEvent] = Field(default_factory=list, description="Daily event breakdown")
    top_products: list[DashboardTopProduct] = Field(default_factory=list, description="Top recommended products")
    similar_requests: int = Field(0, description="Total similar product requests served in period")
    top_similar_source_products: list[DashboardTopProduct] = Field(
        default_factory=list, description="Top 5 queried source products for similar recommendations"
    )


class DashboardEventItem(BaseModel):
    ts: str | None = Field(None, description="Event ISO timestamp")
    event_type: str = Field(..., description="Event type ('view', 'add_to_cart', 'purchase', etc.)")
    product_id: str | None = Field(None, description="Target product identifier")
    product_name: str | None = Field(None, description="Enriched product title if known")
    session_id: str | None = Field(None, description="Client session ID")
    customer_id: str | None = Field(None, description="Customer ID")
    time_ago: str | None = Field(None, description="Human-friendly relative time string")


class DashboardEventsResponse(BaseModel):
    tenant_id: str = Field(..., description="Tenant identifier")
    events: list[DashboardEventItem] = Field(default_factory=list, description="Latest tracked interaction events")


# ---------------------------------------------------------------------------
# Tenant Catalogue Schemas
# ---------------------------------------------------------------------------

class ProductCreateRequest(BaseModel):
    product_id: str = Field(..., description="Unique product identifier (required)")
    product_name: str = Field(..., description="Product title/display name (required)")
    category: str = Field(..., description="Product category (required)")
    brand: str | None = Field(None, description="Brand name")
    price: float | None = Field(None, ge=0.0, description="Product unit price (>= 0)")
    in_stock: int | None = Field(1, description="Stock status (1 for in stock, 0 for out of stock)")
    description: str | None = Field(None, description="Product description")
    image_url: str | None = Field(None, description="URL of product image")
    product_url: str | None = Field(None, description="URL of product page")

    model_config = {"extra": "allow"}


class ProductUpdateRequest(BaseModel):
    product_name: str | None = Field(None, description="Updated product name")
    category: str | None = Field(None, description="Updated category")
    brand: str | None = Field(None, description="Updated brand")
    price: float | None = Field(None, ge=0.0, description="Updated price (>= 0)")
    in_stock: int | None = Field(None, description="Updated stock status (1 or 0)")
    description: str | None = Field(None, description="Updated description")
    image_url: str | None = Field(None, description="Updated image URL")
    product_url: str | None = Field(None, description="Updated product URL")
    status: str | None = Field(None, description="Updated status ('active' or 'archived')")

    model_config = {"extra": "allow"}


class CatalogProductsResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list, description="List of product records")
    total: int = Field(0, description="Total matching products count")
    page: int = Field(1, description="Current page number")
    page_size: int = Field(20, description="Page size limit")
    total_pages: int = Field(1, description="Total number of pages")


class CatalogSummaryResponse(BaseModel):
    active: int = Field(0, description="Count of active products")
    archived: int = Field(0, description="Count of archived products")
    out_of_stock: int = Field(0, description="Count of active products with in_stock=0")
    by_category: dict[str, int] = Field(default_factory=dict, description="Product counts grouped by category")
    products_added_since_last_training: int | None = Field(
        0, description="Number of products created since the last completed model training run"
    )
    products_changed_since_last_training: int = Field(
        0, description="Number of active products updated since the last completed model training run"
    )
    never_trained: bool = Field(
        False, description="Whether the tenant has never completed a model training run"
    )


class BulkCatalogActionRequest(BaseModel):
    action: str = Field(..., description="Action to perform: 'archive', 'restore', or 'delete'")
    product_ids: list[str] = Field(..., max_length=500, description="List of product IDs (up to 500)")


class BulkCatalogActionResponse(BaseModel):
    action: str = Field(..., description="Executed bulk action")
    affected: int = Field(..., description="Number of products affected")
    product_ids: list[str] = Field(default_factory=list, description="IDs of affected products")


class UploadRowError(BaseModel):
    row: int = Field(..., description="1-indexed row number in the uploaded file")
    message: str = Field(..., description="Description of the validation failure")


class UploadPreviewResponse(BaseModel):
    upload_id: str = Field(..., description="Unique pending upload identifier")
    mode: str = Field(..., description="Upload mode ('upsert' or 'replace')")
    to_add: int = Field(0, description="Number of new products that will be added")
    to_update: int = Field(0, description="Number of existing products that will be updated")
    to_archive: int = Field(
        0, description="Number of active products that will be archived (replace mode only)"
    )
    total_rows: int = Field(0, description="Total valid rows parsed from the file")
    errors: list[UploadRowError] = Field(default_factory=list, description="List of row-level errors")


class UploadCommitResponse(BaseModel):
    status: str = Field("committed", description="Commit status")
    upload_id: str = Field(..., description="ID of the committed upload")
    mode: str = Field(..., description="Upload mode applied")
    applied: int = Field(0, description="Total items processed")
    added: int = Field(0, description="Number of new items added")
    updated: int = Field(0, description="Number of existing items updated")
    archived: int = Field(0, description="Number of items archived")


class CatalogHistoryItem(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID")
    who: str = Field(..., description="Identifier of the actor")
    when: str = Field(..., description="ISO 8601 UTC timestamp")
    action: str = Field(..., description="Action name (create, update, archive, restore, etc.)")
    product_ids_count: int = Field(0, description="Count of affected product IDs")
    product_ids: list[str] = Field(default_factory=list, description="Sample of affected product IDs")
    details: dict[str, Any] = Field(default_factory=dict, description="Additional context")


class CatalogHistoryResponse(BaseModel):
    changes: list[CatalogHistoryItem] = Field(default_factory=list, description="Audit change history")


class CatalogUndoResponse(BaseModel):
    status: str = Field("restored", description="Status of the undo operation")
    snapshot: str = Field(..., description="Filename of the snapshot restored")
    message: str = Field(..., description="Confirmation message")
    total_products: int = Field(0, description="Total products in the restored catalogue")

