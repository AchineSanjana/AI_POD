from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from src.api.auth import get_current_tenant, load_tenant_auth
from src.api.onboarding import get_onboarding_status
from src.api.onboarding import router as onboarding_router
from src.api.rate_limiter import check_rate_limit
from src.api.recommendations import router as recommendations_router
from src.api.ui import build_home_page, router as ui_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_tenant_auth()
    yield


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

# ---------------------------------------------------------------------------
# Versioned /v1 Public API Router
# ---------------------------------------------------------------------------
v1_router = APIRouter(prefix="/v1")
v1_router.include_router(recommendations_router)
v1_router.include_router(onboarding_router)
app.include_router(v1_router)

# ---------------------------------------------------------------------------
# Legacy & UI Routers (Backward Compatibility)
# ---------------------------------------------------------------------------
app.include_router(ui_router)
app.include_router(recommendations_router)
app.include_router(onboarding_router)


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


@app.get("/", response_class=HTMLResponse)
def ui_root():
    return HTMLResponse(build_home_page())


@app.get("/health")
def health_check():
    return {"status": "ok"}