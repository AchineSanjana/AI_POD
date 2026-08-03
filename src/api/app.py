from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from src.api.recommendations import router as recommendations_router
from src.api.ui import build_home_page, router as ui_router


app = FastAPI(title="Recommendations API")

app.include_router(ui_router)
app.include_router(recommendations_router)


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