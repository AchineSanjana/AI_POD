import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.auth import (
    get_current_tenant,
    get_key_record,
    is_request_allowed_for_key,
    load_tenant_auth,
)
from src.api.onboarding import get_onboarding_status
from src.api.onboarding import open_router as open_onboarding_router
from src.api.onboarding import router as onboarding_router
from src.api.rate_limiter import check_rate_limit
from src.api.recommendations import router as recommendations_router
from src.api.retrain import router as retrain_router
from src.api.tracking import router as tracking_router
from src.api.ui import build_home_page, router as ui_router
from src.integrations.shopify.api import router as shopify_router
from src.utils.config import PROJECT_ROOT


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_tenant_auth()
    worker = None
    if os.environ.get("ENABLE_TRACKING_WORKER", "").strip().lower() in ("true", "1", "yes"):
        from src.queue.tracking_worker import start_background_tracking_worker
        worker = start_background_tracking_worker()
    yield
    if worker:
        worker.stop()


app = FastAPI(
    title="AI_POD Recommendations & Onboarding API",
    version="1.0.0",
    description="Multi-tenant recommendations engine and automated dataset onboarding API.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_public_key_restrictions(request: Request, call_next):
    """Server-side restriction: public keys are only allowed for POST /v1/track and GET /v1/recommendations."""
    x_api_key = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    if x_api_key:
        record = get_key_record(x_api_key)
        if record and record.get("key_type") == "public":
            if not is_request_allowed_for_key("public", request.method, request.url.path):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            f"Forbidden: Public API keys are only permitted for POST /v1/track and "
                            f"GET /v1/recommendations. Action '{request.method} {request.url.path}' is not allowed."
                        )
                    },
                )
    return await call_next(request)


# ---------------------------------------------------------------------------
# Versioned /v1 Public API Router
# ---------------------------------------------------------------------------
v1_router = APIRouter(prefix="/v1")
v1_router.include_router(recommendations_router)
v1_router.include_router(tracking_router)
v1_router.include_router(onboarding_router)
v1_router.include_router(open_onboarding_router)
v1_router.include_router(shopify_router)
v1_router.include_router(retrain_router)


@v1_router.get("/sdk.js", include_in_schema=False)
@app.get("/sdk.js", include_in_schema=False)
def serve_sdk_file():
    """Serve the client tracking & recommendation JavaScript SDK."""
    sdk_path = PROJECT_ROOT / "static" / "sdk.js"
    if sdk_path.exists():
        return FileResponse(
            sdk_path,
            media_type="application/javascript",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    return HTMLResponse("// SDK file not found", status_code=404)


# Mount static directory for asset delivery (e.g. /static/sdk.js)
static_dir = PROJECT_ROOT / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(v1_router)

# ---------------------------------------------------------------------------
# Legacy & UI Routers (Backward Compatibility)
# ---------------------------------------------------------------------------
app.include_router(ui_router)
app.include_router(recommendations_router)
app.include_router(tracking_router)
app.include_router(onboarding_router)
app.include_router(open_onboarding_router)
app.include_router(shopify_router)
app.include_router(retrain_router)


@app.get(
    "/onboarding/status",
    include_in_schema=False,
    dependencies=[Depends(check_rate_limit(scope="onboarding"))],
)
def legacy_onboarding_status(tenant_id: str = Depends(get_current_tenant)):
    return get_onboarding_status(tenant_id)


@app.get("/api", response_class=HTMLResponse)
def read_root():
    return HTMLResponse(
        "<h1>Recommendations API</h1><p>Open <a href='/'>the demo UI</a> or <a href='/docs'>/docs</a>.</p>"
    )


@app.get("/onboarding", response_class=HTMLResponse)
@app.get("/onboarding.html", response_class=HTMLResponse)
def onboarding_portal():
    portal_file = PROJECT_ROOT / "demo" / "onboarding.html"
    if portal_file.exists():
        return HTMLResponse(portal_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Onboarding Portal Not Found</h1>", status_code=404)


@app.get("/storefront", response_class=HTMLResponse)
@app.get("/storefront.html", response_class=HTMLResponse)
def storefront_portal():
    storefront_file = PROJECT_ROOT / "demo" / "storefront.html"
    if storefront_file.exists():
        return HTMLResponse(storefront_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Storefront Not Found</h1>", status_code=404)


@app.get("/test-sdk", response_class=HTMLResponse)
@app.get("/test_sdk.html", response_class=HTMLResponse)
def test_sdk_page():
    page_file = PROJECT_ROOT / "demo" / "test_sdk.html"
    if page_file.exists():
        return HTMLResponse(page_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Test SDK Page Not Found</h1>", status_code=404)


@app.get("/", response_class=HTMLResponse)
def ui_root():
    return HTMLResponse(build_home_page())


@app.get("/health")
def health_check():
    return {"status": "ok"}