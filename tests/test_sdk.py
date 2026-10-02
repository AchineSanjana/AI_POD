"""Tests for the client-side JavaScript SDK (sdk.js) and static file serving."""

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from src.api.app import app
from src.api.auth import load_tenant_auth
from src.api.tracking import clear_queue
from src.utils.config import PROJECT_ROOT


@pytest.fixture(autouse=True)
def setup_auth():
    load_tenant_auth()
    clear_queue()
    yield
    clear_queue()


@pytest.fixture
def client():
    return TestClient(app)


def test_sdk_served_at_root(client):
    """GET /sdk.js must serve the JavaScript SDK with application/javascript content-type."""
    res = client.get("/sdk.js")
    assert res.status_code == 200
    assert "application/javascript" in res.headers["content-type"]
    content = res.text
    assert "AIPod" in content
    assert "data-tenant-key" in content
    assert "session_id" in content
    assert "track" in content
    assert "identify" in content
    assert "getRecommendations" in content


def test_sdk_served_at_v1(client):
    """GET /v1/sdk.js must also serve the JavaScript SDK."""
    res = client.get("/v1/sdk.js")
    assert res.status_code == 200
    assert "application/javascript" in res.headers["content-type"]
    assert "AIPod" in res.text


def test_sdk_served_from_static_mount(client):
    """GET /static/sdk.js should be reachable via the mounted static directory."""
    res = client.get("/static/sdk.js")
    assert res.status_code == 200
    assert "AIPod" in res.text


def test_test_sdk_page_served(client):
    """GET /test-sdk and /test_sdk.html must serve the manual verification sandbox page."""
    res1 = client.get("/test-sdk")
    assert res1.status_code == 200
    assert "text/html" in res1.headers["content-type"]
    assert "AI_POD JavaScript SDK Verification" in res1.text
    assert "sdk.js" in res1.text

    res2 = client.get("/test_sdk.html")
    assert res2.status_code == 200
    assert res2.text == res1.text


def test_sdk_track_contract_with_public_key(client):
    """Verify that POST /v1/track accepts the exact JSON payload structured by sdk.js."""
    payload = {
        "event_type": "view",
        "product_id": "prod_101",
        "session_id": "sess_abc123xyz",
        "customer_id": "cust_live_001",
        "quantity": 1,
        "timestamp": "2026-10-01T10:00:00.000Z",
    }
    # Public key configured for telco_default
    headers = {"X-API-Key": "pk-telco-xxxx"}

    res = client.post("/v1/track", json=payload, headers=headers)
    assert res.status_code == 202
    data = res.json()
    assert data["status"] == "accepted"


def test_sdk_recommendations_contract_with_public_key(client):
    """Verify that GET /v1/recommendations works seamlessly with public API key used by sdk.js."""
    from src.api.recommendations import get_model_for_tenant

    model = get_model_for_tenant("telco_default")
    customer_id = model.customers_.iloc[0]["customer_id"]

    headers = {"X-API-Key": "pk-telco-xxxx"}
    res = client.get(f"/v1/recommendations?customer_id={customer_id}&top_n=5", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "recommendations" in data
    assert isinstance(data["recommendations"], list)
    assert "fallback" in data
    assert data["fallback"] is False


def test_sdk_file_structure_and_documentation():
    """Verify that static/sdk.js contains the architectural rationale for localStorage and cookies."""
    sdk_path = PROJECT_ROOT / "static" / "sdk.js"
    assert sdk_path.exists(), "sdk.js file must exist in static/ directory"

    code = sdk_path.read_text(encoding="utf-8")

    # Documented persistence design: localStorage primary, cookie fallback
    assert "localStorage" in code
    assert "cookie" in code
    assert "PERSISTENCE MECHANISM" in code
    assert "WHY localStorage IS PRIMARY" in code
    assert "WHY FIRST-PARTY COOKIE IS FALLBACK" in code

    # Core SDK functions
    assert "AIPod.track" in code or "track:" in code
    assert "AIPod.identify" in code or "identify:" in code
    assert "AIPod.getRecommendations" in code or "getRecommendations:" in code
    assert "renderWidget" in code
    assert "window.AIPod = AIPod" in code

    # Fail silently requirement: extensive try-catch wrapping
    assert "try {" in code
    assert "} catch" in code


def test_sdk_render_widget_optional_helper():
    """Verify renderWidget exists, handles container resolution, and is optional."""
    sdk_path = PROJECT_ROOT / "static" / "sdk.js"
    code = sdk_path.read_text(encoding="utf-8")
    assert "renderWidget: function" in code
    assert "containerId" in code
    assert "aipod-product-card" in code
    assert "aipod-widget-grid" in code


def test_storefront_uses_sdk_and_public_key(client):
    """Verify demo/storefront.html loads sdk.js with a public key and calls AIPod.getRecommendations()."""
    res = client.get("/storefront")
    assert res.status_code == 200
    html = res.text

    # Script tag loads sdk.js with public key for online_retail
    assert 'src="/sdk.js"' in html or "src='/sdk.js'" in html
    assert 'data-tenant-key="pk-online-retail-xxxx"' in html

    # Exercises real SDK integration pattern
    assert "AIPod.getRecommendations(" in html
    assert "AIPod.identify(" in html
    assert "AIPod.track(" in html


def test_instacart_grocery_demo_page(client):
    """Verify demo/instacart_grocery.html meets the Instacart simulation requirements."""
    res = client.get("/instacart")
    assert res.status_code == 200
    html = res.text

    # Header and Brand
    assert "Fresh Cart Co." in html

    # Exact stop block and placeholder CONFIG
    assert "// STOP — before this page will work, fill in CONFIG above:" in html
    assert 'baseUrl: "https://your-engine.com"' in html
    assert 'publicKey: "PASTE_YOUR_PUBLIC_KEY_HERE"' in html

    # Exact visible warning banner text
    assert "⚠ Demo not connected yet — add your public key in CONFIG to activate live recommendations." in html

    # Shopping as dropdown with plausible Instacart user_ids and explanatory comment
    assert "shopperSelect" in html
    assert 'value="2455"' in html
    assert "plausible Instacart user_ids" in html or "Instacart user_id" in html

    # Recommended for You section and SDK integration
    assert "Recommended for You" in html
    assert "AIPod.getRecommendations(" in html
    assert "AIPod.track(" in html
    assert "AIPod.identify(" in html
    assert "fallback" in html

    # Department structure
    assert "Browse by Department" in html
    assert "Produce" in html
    assert "Dairy Eggs" in html or "Dairy &amp; Eggs" in html
    assert "Snacks" in html
    assert "Beverages" in html
    assert "Frozen" in html

    # Price note for Instacart items
    assert "*illustrative" in html or "Illustrative placeholder" in html or "illustrative placeholder" in html

    # Collapsible Setup Checklist panel and header button
    assert "setupToggleBtn" in html
    assert "setupChecklistDrawer" in html
    assert "Setup Checklist" in html
    assert "Go to the onboarding page and sign up as a new company" in html
    assert "Copy the private key shown once at signup" in html
    assert "Copy the public key shown at signup" in html
    assert "Paste the public key into" in html
    assert "Use the private key to upload the Instacart dataset" in html
    assert "Wait for training" in html
    assert "Refresh this page" in html
    assert "plain static text, not functional" in html

    # Live in-memory settings drawer (not persisted)
    assert "configDrawer" in html
    assert "headerConfigBtn" in html or "configToggleBtn" in html
    assert "not persisted" in html


def test_hm_fashion_demo_page(client):
    """Verify demo/hm_fashion.html meets the H&M simulation requirements."""
    res = client.get("/hm")
    assert res.status_code == 200
    html = res.text

    # Header and Brand
    assert "Thread &amp; Co." in html or "Thread & Co." in html

    # Exact stop block and placeholder CONFIG
    assert "// STOP — before this page will work, fill in CONFIG above:" in html
    assert 'baseUrl: "https://your-engine.com"' in html
    assert 'publicKey: "PASTE_YOUR_PUBLIC_KEY_HERE"' in html

    # Exact visible warning banner text
    assert "⚠ Demo not connected yet — add your public key in CONFIG to activate live recommendations." in html

    # Shopping as dropdown with plausible H&M customer_ids and age/membership metadata
    assert "shopperSelect" in html
    assert "Active member" in html
    assert "32, Active member" in html or "32" in html
    assert "00000dba" in html

    # Recommended for You section and SDK integration
    assert "Recommended for You" in html
    assert "AIPod.getRecommendations(" in html
    assert "AIPod.track(" in html
    assert "AIPod.identify(" in html
    assert "fallback" in html

    # Garment groups, colours, swatches, and illustrative price
    assert "Dresses" in html
    assert "Knitwear" in html
    assert "Trousers" in html
    assert "Swatch" in html or "swatch" in html
    assert "*illustrative" in html or "Illustrative placeholder" in html or "illustrative" in html

    # Collapsible Setup Checklist panel and header button
    assert "setupToggleBtn" in html
    assert "setupChecklistDrawer" in html
    assert "Setup Checklist" in html
    assert "Go to the onboarding page and sign up as a new company" in html
    assert "Thread &amp; Co." in html or "Thread & Co." in html
    assert "Copy the private key shown once at signup" in html
    assert "Copy the public key shown at signup" in html
    assert "Paste the public key into" in html
    assert ("Use the private key to upload the H&amp;M dataset" in html or
            "Use the private key to upload the H&M dataset" in html)
    assert "Wait for training" in html
    assert "Refresh this page" in html
    assert "plain static text, not functional" in html

    # Live in-memory settings drawer (not persisted)
    assert "configDrawer" in html
    assert "headerConfigBtn" in html or "configToggleBtn" in html
    assert "not persisted" in html




