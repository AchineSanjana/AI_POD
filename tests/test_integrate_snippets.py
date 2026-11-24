"""Tests for IntegrateStep snippet generation safety and product placeholder logic.

Verifies:
1. Snippets always use aipod.escape and aipod.sanitizeUrl for rendering API data.
2. No secret key ('sk-') ever appears in snippets.
3. Dynamic product ID uses first active catalogue product when present, or 'YOUR_PRODUCT_ID' placeholder.
4. IntegrateStep.jsx source code contains the required security escaping and comments.
"""
from pathlib import Path
import re


def generate_snippets(
    raw_pk: str,
    catalog_products: list[dict],
    tenant_id: str = "e2e_tenant_snippet",
    api_base: str = "http://127.0.0.1:8000",
) -> dict[str, str]:
    """Mirror snippet generation logic from IntegrateStep.jsx."""
    key_unavailable = "Key not available, regenerate in Dashboard > API Keys"
    is_pk_available = bool(raw_pk and raw_pk != key_unavailable and not raw_pk.startswith("sk-"))
    effective_pk = raw_pk if is_pk_available else key_unavailable

    first_active_product_id = ""
    for p in catalog_products:
        if p.get("status") == "active":
            first_active_product_id = p.get("product_id", "")
            break
    if not first_active_product_id and catalog_products:
        first_active_product_id = catalog_products[0].get("product_id", "")

    example_product_id = first_active_product_id or "YOUR_PRODUCT_ID"

    html_snippet = f"""<script
  src="{api_base}/sdk.js"
  data-tenant-key="{effective_pk}">
</script>

<script>
  // Track events
  aipod.track('view', {{ product_id: '{example_product_id}' }});
  aipod.track('purchase', {{ product_id: '{example_product_id}' }});

  // Identify on login
  aipod.identify('cust_12345');

  // Render recommendations
  // Always wrap API values with aipod.escape and URLs with aipod.sanitizeUrl to prevent XSS injection
  aipod.getRecommendations({{
    top_n: 4,
    containerId: 'ai-recs',
    template: (item) =>
      `<div class="product">
        <img src="${{aipod.sanitizeUrl(item.image_url)}}" alt="${{aipod.escape(item.product_name)}}" />
        <span>${{aipod.escape(item.product_name)}}</span>
      </div>`
  }});
</script>"""

    npm_snippet = f"""npm install @aipod/sdk

import {{ AIPod }} from '@aipod/sdk';

const aipod = new AIPod({{ tenantKey: '{effective_pk}' }});

aipod.track('view', {{ product_id: '{example_product_id}' }});
aipod.identify('cust_12345');

// Always wrap API values with aipod.escape and URLs with aipod.sanitizeUrl to prevent XSS injection
const recs = await aipod.getRecommendations({{ top_n: 5 }});"""

    similar_widget_snippet = f"""// Render similar products widget
aipod.getSimilar({{
  product_id: '{example_product_id}',
  containerId: 'similar-products',
  top_n: 4,
  same_category: true
}});"""

    return {
        "html": html_snippet,
        "npm": npm_snippet,
        "similar": similar_widget_snippet,
    }


def test_integrate_snippets_with_active_product():
    products = [
        {"product_id": "ARCHIVED-01", "status": "archived"},
        {"product_id": "PROD-ACTIVE-99", "status": "active"},
    ]
    snippets = generate_snippets("pk-test-abc", products)
    assert "PROD-ACTIVE-99" in snippets["html"]
    assert "PROD-ACTIVE-99" in snippets["npm"]
    assert "PROD-ACTIVE-99" in snippets["similar"]
    assert "aipod.escape" in snippets["html"]
    assert "aipod.sanitizeUrl" in snippets["html"]
    assert "sk-" not in snippets["html"]
    assert "sk-" not in snippets["npm"]
    assert "sk-" not in snippets["similar"]


def test_integrate_snippets_without_products():
    snippets = generate_snippets("pk-test-abc", [])
    assert "YOUR_PRODUCT_ID" in snippets["html"]
    assert "YOUR_PRODUCT_ID" in snippets["npm"]
    assert "YOUR_PRODUCT_ID" in snippets["similar"]
    assert "aipod.escape" in snippets["html"]
    assert "aipod.sanitizeUrl" in snippets["html"]
    assert "sk-" not in snippets["html"]


def test_integrate_snippets_rejects_secret_key():
    snippets = generate_snippets("sk-leaked-key-12345", [{"product_id": "P1", "status": "active"}])
    assert "sk-leaked-key-12345" not in snippets["html"]
    assert "sk-leaked-key-12345" not in snippets["npm"]
    assert "Key not available" in snippets["html"]
    assert "Key not available" in snippets["npm"]


def test_integrate_step_jsx_file_contains_safe_template():
    jsx_path = Path("frontend/src/pages/onboarding/IntegrateStep.jsx")
    assert jsx_path.exists(), "IntegrateStep.jsx must exist"
    content = jsx_path.read_text(encoding="utf-8")
    assert "aipod.escape" in content, "IntegrateStep.jsx must use aipod.escape in template"
    assert "aipod.sanitizeUrl" in content, "IntegrateStep.jsx must use aipod.sanitizeUrl in template"
    assert "YOUR_PRODUCT_ID" in content, "IntegrateStep.jsx must have YOUR_PRODUCT_ID placeholder"
    assert "rawPk.startsWith('sk-')" in content, "IntegrateStep.jsx must reject sk- keys"

