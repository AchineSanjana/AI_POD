"""FastAPI router for tenant-managed product catalogue administration.

Endpoints:
- GET    /v1/catalog/products: Server-side paginated catalogue search and filter.
- GET    /v1/catalog/summary: Operational counts (active, archived, out of stock, by category, added since last training).
- POST   /v1/catalog/products: Add single product (409 on duplicate ID).
- PATCH  /v1/catalog/products/{product_id}: Partially update product.
- DELETE /v1/catalog/products/{product_id}: Archive product or permanently delete if already archived.
- POST   /v1/catalog/products/{product_id}/restore: Restore an archived product.
- POST   /v1/catalog/bulk: Bulk archive, restore, or delete up to 500 product IDs.
- GET    /v1/catalog/template: Download CSV catalogue template.
- POST   /v1/catalog/upload: Preview multipart file upload (CSV, JSON, XLSX <=20MB, max 100k rows).
- POST   /v1/catalog/upload/{upload_id}/commit: Commit pending upload with automatic snapshot.
- GET    /v1/catalog/history: Last 50 changes from part-file audit log.
- POST   /v1/catalog/undo: Restore snapshot taken before last commit (keeps 10 snapshots).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)

from src.api.auth import get_tenant_for_admin_action
from src.api.rate_limiter import check_rate_limit
from src.api.schemas import (
    BulkCatalogActionRequest,
    BulkCatalogActionResponse,
    CatalogHistoryResponse,
    CatalogProductsResponse,
    CatalogSummaryResponse,
    CatalogUndoResponse,
    ProductCreateRequest,
    ProductUpdateRequest,
    UploadCommitResponse,
    UploadPreviewResponse,
)
from src.catalog.audit import get_catalog_history
from src.storage import get_storage_backend
from src.catalog.service import (
    ConcurrentModificationError,
    DuplicateProductError,
    InvalidOperationError,
    ProductNotFoundError,
    SnapshotError,
    add_product,
    bulk_action,
    commit_upload,
    delete_product,
    generate_catalog_template,
    get_catalog_path,
    get_catalog_summary,
    list_products,
    parse_and_preview_upload,
    restore_product,
    undo_last_commit,
    update_product,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/catalog",
    tags=["catalog"],
    dependencies=[
        Depends(check_rate_limit(scope="catalog", tenant_dep=get_tenant_for_admin_action))
    ],
)


def _resolve_actor(
    tenant_id: str = Depends(get_tenant_for_admin_action),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_session_token: str | None = Header(None, alias="X-Session-Token"),
) -> str:
    """Helper to extract a safe actor identifier (account_id or tenant + key_type).

    NEVER stores raw API keys, JWT tokens, or passwords.
    """
    token: str | None = None
    if authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        elif len(parts) == 1:
            token = parts[0]
    if not token and x_session_token:
        token = x_session_token.strip()

    if token:
        try:
            from src.accounts.session import verify_session_token
            payload = verify_session_token(token)
            account_id = payload.get("account_id") or payload.get("sub")
            if account_id:
                return f"account:{account_id}"
        except Exception:
            pass
        return f"tenant:{tenant_id}:session"

    if x_api_key and x_api_key.strip():
        from src.api.auth import get_key_record
        rec = get_key_record(x_api_key.strip())
        key_type = rec.get("key_type", "private") if rec else "private"
        return f"tenant:{tenant_id}:{key_type}_key"

    return f"tenant:{tenant_id}:admin"


@router.get(
    "/products",
    response_model=CatalogProductsResponse,
    summary="Get paginated catalogue products",
)
def get_products(
    response: Response,
    query: str | None = Query(None, description="Search term matching product_id, name, description, brand"),
    category: str | None = Query(None, description="Filter by category"),
    status: str | None = Query(None, description="Filter by status ('active' or 'archived')"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    tenant_id: str = Depends(get_tenant_for_admin_action),
) -> dict[str, Any]:
    """Retrieve products for the authenticated tenant with server-side pagination and filters."""
    result, version_marker = list_products(
        tenant_id=tenant_id,
        query=query,
        category=category,
        status=status,
        page=page,
        page_size=page_size,
    )
    if version_marker:
        response.headers["ETag"] = f'"{version_marker}"'
        response.headers["X-Catalog-Version"] = version_marker
    return result


@router.get(
    "/summary",
    response_model=CatalogSummaryResponse,
    summary="Get catalogue summary metrics",
)
def get_summary(
    response: Response,
    tenant_id: str = Depends(get_tenant_for_admin_action),
) -> dict[str, Any]:
    """Return operational metrics: active, archived, out of stock, by category, and products added since training."""
    from src.catalog import service
    storage = service.get_storage_backend()
    summary = service.get_catalog_summary(tenant_id=tenant_id, storage=storage)
    cat_path = service.get_catalog_path(tenant_id)
    version_marker = storage.get_version_marker(cat_path) if storage.exists(cat_path) else None
    if version_marker:
        response.headers["ETag"] = f'"{version_marker}"'
        response.headers["X-Catalog-Version"] = version_marker
    return summary


@router.post(
    "/products",
    status_code=status.HTTP_201_CREATED,
    summary="Add a product to the catalogue",
)
def create_product(
    payload: ProductCreateRequest,
    tenant_id: str = Depends(get_tenant_for_admin_action),
    who: str = Depends(_resolve_actor),
    if_match: str | None = Header(None, alias="If-Match"),
    x_version: str | None = Header(None, alias="X-Catalog-Version"),
) -> dict[str, Any]:
    """Add a new product to the catalogue. Returns HTTP 409 Conflict if product_id already exists."""
    expected_version = (if_match.strip('"') if if_match else None) or x_version
    try:
        data = payload.model_dump()
        result = add_product(
            tenant_id=tenant_id,
            data=data,
            who=who,
            expected_version=expected_version,
        )
        return result
    except DuplicateProductError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ConcurrentModificationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch(
    "/products/{product_id}",
    summary="Partially update a catalogue product",
)
def patch_product(
    product_id: str,
    payload: ProductUpdateRequest,
    tenant_id: str = Depends(get_tenant_for_admin_action),
    who: str = Depends(_resolve_actor),
    if_match: str | None = Header(None, alias="If-Match"),
    x_version: str | None = Header(None, alias="X-Catalog-Version"),
) -> dict[str, Any]:
    """Update fields on an existing product in the catalogue."""
    expected_version = (if_match.strip('"') if if_match else None) or x_version
    try:
        update_data = payload.model_dump(exclude_unset=True)
        return update_product(
            tenant_id=tenant_id,
            product_id=product_id,
            update_data=update_data,
            who=who,
            expected_version=expected_version,
        )
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConcurrentModificationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete(
    "/products/{product_id}",
    summary="Archive or permanently delete a product",
)
def remove_product(
    product_id: str,
    permanent: bool = Query(False, description="Permanently delete product (only allowed for already-archived items)"),
    tenant_id: str = Depends(get_tenant_for_admin_action),
    who: str = Depends(_resolve_actor),
    if_match: str | None = Header(None, alias="If-Match"),
    x_version: str | None = Header(None, alias="X-Catalog-Version"),
) -> dict[str, Any]:
    """Soft delete (archive) a product. Permanent deletion requires ?permanent=true and product must be archived."""
    expected_version = (if_match.strip('"') if if_match else None) or x_version
    try:
        return delete_product(
            tenant_id=tenant_id,
            product_id=product_id,
            permanent=permanent,
            who=who,
            expected_version=expected_version,
        )
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidOperationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ConcurrentModificationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/products/{product_id}/restore",
    summary="Restore an archived product",
)
def restore_archived_product(
    product_id: str,
    tenant_id: str = Depends(get_tenant_for_admin_action),
    who: str = Depends(_resolve_actor),
    if_match: str | None = Header(None, alias="If-Match"),
    x_version: str | None = Header(None, alias="X-Catalog-Version"),
) -> dict[str, Any]:
    """Restore an archived product back to active status."""
    expected_version = (if_match.strip('"') if if_match else None) or x_version
    try:
        return restore_product(
            tenant_id=tenant_id,
            product_id=product_id,
            who=who,
            expected_version=expected_version,
        )
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConcurrentModificationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/bulk",
    response_model=BulkCatalogActionResponse,
    summary="Bulk archive, restore, or delete products",
)
def bulk_catalog_mutation(
    payload: BulkCatalogActionRequest,
    tenant_id: str = Depends(get_tenant_for_admin_action),
    who: str = Depends(_resolve_actor),
    if_match: str | None = Header(None, alias="If-Match"),
    x_version: str | None = Header(None, alias="X-Catalog-Version"),
) -> dict[str, Any]:
    """Perform bulk action ('archive', 'restore', 'delete') on up to 500 product IDs."""
    expected_version = (if_match.strip('"') if if_match else None) or x_version
    try:
        return bulk_action(
            tenant_id=tenant_id,
            action=payload.action,
            product_ids=payload.product_ids,
            who=who,
            expected_version=expected_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ConcurrentModificationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/template",
    summary="Download catalogue CSV template",
)
def get_template(
    format: str = Query("csv", description="Template format ('csv')"),
    tenant_id: str = Depends(get_tenant_for_admin_action),
) -> Response:
    """Download catalogue header template with an example product row."""
    if format.lower() != "csv":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only 'csv' format is supported for template download.",
        )
    csv_text = generate_catalog_template(format="csv")
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="catalog_template.csv"'},
    )


@router.post(
    "/upload",
    response_model=UploadPreviewResponse,
    summary="Preview catalogue file upload",
)
async def upload_catalog_preview(
    file: UploadFile = File(...),
    mode: str = Form("upsert", description="Upload mode ('upsert' or 'replace')"),
    tenant_id: str = Depends(get_tenant_for_admin_action),
) -> dict[str, Any]:
    """Preview a catalogue file upload (CSV, JSON, XLSX up to 20 MB).

    Performs full row-level validation (<=100k rows, required fields, duplicate IDs, price validity)
    and computes diff metrics (to_add, to_update, to_archive). Does NOT commit changes.
    """
    file_bytes = await file.read()
    filename = file.filename or "upload.csv"
    try:
        return parse_and_preview_upload(
            tenant_id=tenant_id,
            file_bytes=file_bytes,
            filename=filename,
            mode=mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/upload/{upload_id}/commit",
    response_model=UploadCommitResponse,
    summary="Commit pending previewed upload",
)
def commit_upload_changes(
    upload_id: str,
    tenant_id: str = Depends(get_tenant_for_admin_action),
    who: str = Depends(_resolve_actor),
) -> dict[str, Any]:
    """Commit a pending previewed upload.

    Takes a pre-commit snapshot, applies additions/updates/archives, and prunes older snapshots.
    Pending uploads expire after 1 hour.
    """
    try:
        return commit_upload(
            tenant_id=tenant_id,
            upload_id=upload_id,
            who=who,
        )
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidOperationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ConcurrentModificationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/history",
    response_model=CatalogHistoryResponse,
    summary="Get catalogue audit change history",
)
def get_history(
    tenant_id: str = Depends(get_tenant_for_admin_action),
) -> dict[str, Any]:
    """Retrieve the last 50 audit log changes for the tenant's catalogue."""
    changes = get_catalog_history(tenant_id=tenant_id, limit=50)
    return {"changes": changes}


@router.post(
    "/undo",
    response_model=CatalogUndoResponse,
    summary="Undo last commit from snapshot",
)
def undo_last_upload_commit(
    response: Response,
    tenant_id: str = Depends(get_tenant_for_admin_action),
    who: str = Depends(_resolve_actor),
) -> dict[str, Any]:
    """Restore the snapshot taken before the last commit."""
    try:
        res = undo_last_commit(tenant_id=tenant_id, who=who)
        from src.catalog import service
        storage = service.get_storage_backend()
        cat_path = service.get_catalog_path(tenant_id)
        version_marker = storage.get_version_marker(cat_path) if storage.exists(cat_path) else None
        if version_marker:
            response.headers["ETag"] = f'"{version_marker}"'
            response.headers["X-Catalog-Version"] = version_marker
        return res
    except SnapshotError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ConcurrentModificationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

