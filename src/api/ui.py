# Domain-agnostic recommendations web UI driven by CustomerSchema, ProductSchema, and tenant config.
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

# Ensure project root is in sys.path for direct script execution
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from src.api.recommendations import get_model_for_tenant
from src.utils.config import get_tenant_auth_mapping, load_config, resolve_path


router = APIRouter(tags=["ui"])


def get_available_tenants() -> list[str]:
    """Retrieve list of configured and discoverable tenant IDs."""
    tenants: set[str] = set()
    try:
        cfg = load_config()
        if "tenants" in cfg and isinstance(cfg["tenants"], dict):
            tenants.update(cfg["tenants"].keys())
    except Exception:
        pass

    try:
        from src.utils.config import get_tenant_auth_records
        records = get_tenant_auth_records()
        for rec in records.values():
            t = rec.get("tenant_id")
            if t:
                tenants.add(str(t))
    except Exception:
        pass

    for default_t in ["telco_default", "fresh_cart_co", "thread_co", "online_retail", "movielens_demo", "movielens_small", "fixture_ecommerce"]:
        tenants.add(default_t)

    ordered_primary = ["telco_default", "fresh_cart_co", "thread_co", "online_retail", "movielens_demo", "movielens_small", "fixture_ecommerce"]
    result = [t for t in ordered_primary if t in tenants]
    result.extend(sorted(t for t in tenants if t not in ordered_primary))
    return result


KNOWN_TENANT_CUSTOMER_SAMPLES: dict[str, list[str]] = {
    "fresh_cart_co": ["C00001", "C00002", "C00003", "C00004", "C00005", "C00006", "C00007", "C00008"],
    "thread_co": [
        "45558fc9ab558902ba40c6fa2942a598fc3526335b2b075903f48c3dd59f6359",
        "19cda62a36781e7af9f3dd8b8fe6e2f6f70989819b43f6b333de54f66c4cd53f",
        "065d539b3d256e308e1e118a098c74c9e4abc8535a5436bdeaad69c898f1cd7a",
        "71ddc3bbbf6060cf2c40c7393b776b10306dbd2346eb6d9f5eeebc8706c1e2bf",
        "48da0dd232ba8d8a393bed2f5f6b1d64fe3cf67c2559f5cb5b56edb4052b3a2a",
    ],
    "telco_default": ["7590-VHVEG", "5575-GNVDE", "3668-QPYBK", "7795-CFOCW", "9237-HQITU"],
    "online_retail": ["13313", "18097", "16656", "16875", "13094"],
    "movielens_demo": ["1", "2", "3", "4", "5"],
    "movielens_small": ["1", "2", "3", "4", "5"],
    "fixture_ecommerce": ["usr_1", "usr_2", "usr_3", "usr_4", "usr_5"],
}


def get_sample_customer_ids(tenant_id: str = "telco_default", limit: int = 25) -> list[str]:
    """Get sample customer IDs for a tenant from model, processed CSV, raw data, or known samples."""
    try:
        model = get_model_for_tenant(tenant_id)
        customers = getattr(model, "customers_", None)
        if customers is not None and not customers.empty:
            for candidate in ["customerID", "customer_id", "customerId", "user_id", "id", "ShopperID"]:
                if candidate in customers.columns:
                    samples = customers[candidate].dropna().astype(str).unique().tolist()
                    if samples:
                        return samples[:limit]
    except Exception:
        pass

    try:
        from src.storage import get_storage_backend
        import io

        storage = get_storage_backend()
        for cust_key in [
            f"data/processed/{tenant_id}/customers.csv",
            f"data/processed/{tenant_id}/interactions.csv",
        ]:
            if storage.exists(cust_key):
                df = pd.read_csv(io.BytesIO(storage.read_file(cust_key)), nrows=200)
                for candidate in ["customerID", "customer_id", "customerId", "user_id", "id"]:
                    if candidate in df.columns:
                        samples = df[candidate].dropna().astype(str).unique().tolist()
                        if samples:
                            return samples[:limit]
    except Exception:
        pass

    # Check known tenant customer samples fallback
    if tenant_id in KNOWN_TENANT_CUSTOMER_SAMPLES:
        return KNOWN_TENANT_CUSTOMER_SAMPLES[tenant_id][:limit]

    return ["C00001", "1", "user_1"]


def build_home_page(tenant_id: str | None = None, default_customer_id: str | None = None) -> str:
    available_tenants = get_available_tenants()
    if not available_tenants:
        available_tenants = ["telco_default"]

    selected_tenant = tenant_id if (tenant_id and tenant_id in available_tenants) else available_tenants[0]

    # Preload sample IDs for each tenant for fast switching in UI
    tenant_samples_map = {t: get_sample_customer_ids(t, limit=25) for t in available_tenants}
    current_samples = tenant_samples_map.get(selected_tenant, [])
    effective_customer_id = default_customer_id or (current_samples[0] if current_samples else "C00001")

    try:
        from src.utils.config import get_tenant_auth_records
        cfg = load_config()
        records = get_tenant_auth_records(cfg)
        tenant_keys_map = {}
        for key, rec in records.items():
            t = rec.get("tenant_id")
            if t:
                # Prefer public keys for browser UI calls
                if t not in tenant_keys_map or rec.get("key_type") == "public" or key.startswith("pk-"):
                    tenant_keys_map[t] = key
    except Exception:
        tenant_keys_map = {}

    # Guarantee a valid public key is permanently mapped for EVERY tenant
    for t in available_tenants:
        if t not in tenant_keys_map:
            tenant_keys_map[t] = f"pk-{t}-xxxx"

    tenant_options_html = "\n".join(
        f'<option value="{t}" {"selected" if t == selected_tenant else ""}>{t}</option>'
        for t in available_tenants
    )
    customer_options_html = "".join(f'<option value="{cid}"></option>' for cid in current_samples)
    tenant_samples_json = json.dumps(tenant_samples_map)
    tenant_keys_json = json.dumps(tenant_keys_map)
    active_pub_key = tenant_keys_map.get(selected_tenant, f"pk-{selected_tenant}-xxxx")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Recommendations UI</title>
  <!-- Load AI_POD Client Tracking & Recommendation SDK with Active Public Key -->
  <script src="/sdk.js" data-tenant-key="{active_pub_key}" id="aipod-sdk"></script>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7fbff;
      --panel: #ffffff;
      --text: #17324d;
      --muted: #5f7286;
      --blue: #0d73c9;
      --green: #18a56b;
      --border: #d9e6f2;
      --shadow: 0 10px 30px rgba(17, 58, 96, 0.08);
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      color: var(--text);
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      min-height: 100vh;
    }}

    .container {{
      max-width: 1080px;
      margin: 0 auto;
      padding: 16px;
    }}

    .page {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }}

    .header {{
      padding: 18px 18px 14px;
      border-bottom: 1px solid var(--border);
    }}

    .eyebrow {{
      display: inline-flex;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(13, 115, 201, 0.08);
      color: var(--blue);
      font-size: 0.84rem;
      font-weight: 700;
      margin-bottom: 10px;
    }}

    h1 {{ margin: 0; font-size: 1.9rem; line-height: 1.1; }}

    .subtext {{ margin: 10px 0 0; color: var(--muted); line-height: 1.6; max-width: 70ch; }}

    .simple-row {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }}

    .pill {{
      display: inline-flex;
      align-items: center;
      padding: 6px 10px;
      border-radius: 999px;
      background: #eef6ff;
      color: var(--blue);
      font-size: 0.84rem;
      font-weight: 700;
    }}

    .content {{
      padding: 18px;
      display: grid;
      gap: 18px;
      grid-template-columns: 340px minmax(0, 1fr);
      align-items: start;
    }}

    .panel {{
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px;
      background: #fff;
    }}

    .panel h2 {{ margin: 0 0 10px; font-size: 1.05rem; }}

    .field {{ margin-bottom: 14px; }}

    .field label {{ display: block; margin-bottom: 6px; font-size: 0.92rem; font-weight: 700; }}

    .field input, .field select {{
      width: 100%;
      padding: 12px 14px;
      border: 1px solid var(--border);
      border-radius: 10px;
      font: inherit;
      outline: none;
      background: #fff;
      color: var(--text);
      transition: border-color 0.2s, box-shadow 0.2s;
    }}

    .field select {{
      cursor: pointer;
      appearance: none;
      -webkit-appearance: none;
      -moz-appearance: none;
      background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%230d73c9' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3e%3cpolyline points='6 9 12 15 18 9'%3e%3c/polyline%3e%3c/svg%3e");
      background-repeat: no-repeat;
      background-position: right 14px center;
      background-size: 16px;
      padding-right: 40px;
      font-weight: 600;
    }}

    .field input:focus, .field select:focus {{
      border-color: rgba(13, 115, 201, 0.65);
      box-shadow: 0 0 0 3px rgba(13, 115, 201, 0.12);
    }}

    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 8px; }}

    button, .link-button {{
      border: 0;
      border-radius: 10px;
      padding: 12px 14px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}

    button {{ color: #fff; background: linear-gradient(135deg, var(--blue), var(--green)); }}

    .link-button {{ color: var(--blue); background: #eef6ff; border: 1px solid var(--border); }}

    .status {{
      margin-top: 12px;
      padding: 10px 12px;
      border-radius: 10px;
      background: #f6f9fc;
      border: 1px solid var(--border);
      min-height: 42px;
      display: flex;
      align-items: center;
      font-weight: 600;
    }}

    .status.error {{ color: #9b1c1c; background: #fff1f1; }}
    .status.success {{ color: #0f7a4f; background: #eefaf4; }}

    .meta {{ margin-top: 10px; color: var(--muted); font-size: 0.92rem; }}

    .results {{ min-width: 0; }}

    .results-header {{ display: flex; justify-content: space-between; gap: 12px; align-items: baseline; margin-bottom: 10px; }}
    .results-header h2 {{ margin: 0; font-size: 1.05rem; }}
    .results-header p {{ margin: 0; color: var(--muted); }}

    .table-wrap {{ width: 100%; overflow-x: auto; border: 1px solid var(--border); border-radius: 14px; background: #fff; }}

    table {{ width: 100%; border-collapse: collapse; min-width: 640px; }}

    thead th {{
      text-align: left;
      padding: 12px 14px;
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      background: #f7fbff;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }}

    tbody td {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
      white-space: nowrap;
    }}

    tbody tr:last-child td {{ border-bottom: 0; }}

    .rank-badge {{
      display: inline-flex;
      min-width: 30px;
      height: 30px;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      background: rgba(13, 115, 201, 0.12);
      color: var(--blue);
      font-weight: 700;
    }}

    .product-name {{ font-weight: 700; }}
    .product-id {{ color: var(--muted); font-size: 0.9rem; margin-top: 3px; }}

    .category-tag {{
      display: inline-flex;
      padding: 5px 9px;
      border-radius: 999px;
      background: rgba(24, 165, 107, 0.1);
      color: var(--green);
      font-size: 0.84rem;
      font-weight: 700;
    }}

    @media (max-width: 900px) {{
      .content {{ grid-template-columns: 1fr; }}
    }}

    @media (max-width: 640px) {{
      .container {{ padding: 10px; }}
      .header, .content {{ padding: 14px; }}
      h1 {{ font-size: 1.5rem; }}
      button, .link-button {{ width: 100%; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="page">
      <div class="header">
        <div class="eyebrow">Multi-Tenant Recommender</div>
        <h1>Recommendation Demo</h1>
        <p class="subtext">Select a Tenant ID from the dropdown and choose or enter a Customer ID to fetch recommendations from the model.</p>
        <div class="simple-row" style="margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap;">
          <a class="pill" href="/telco" style="text-decoration: none; background: #003399; color: #fff; font-weight: bold;">📶 Mobitel Telco Portal</a>
          <a class="pill" href="/hm" style="text-decoration: none; background: #18181b; color: #fff; font-weight: bold;">🧵 Thread &amp; Co. Fashion</a>
          <a class="pill" href="/instacart" style="text-decoration: none; background: #059669; color: #fff; font-weight: bold;">🥑 Fresh Cart Grocery</a>
          <a class="pill" href="/storefront" style="text-decoration: none; background: #d97706; color: #fff; font-weight: bold;">🛍️ Gift &amp; Home Retail</a>
          <a class="pill" href="/onboarding" style="text-decoration: none; background: #6366f1; color: #fff; font-weight: bold;">🚀 Dataset Onboarding</a>
        </div>
      </div>

      <div class="content">
        <div class="panel">
          <h2>Get recommendations</h2>
          <form id="recommendation-form">
            <div class="field">
              <label for="tenant_id">Tenant ID</label>
              <select id="tenant_id" name="tenant_id" required>
                {tenant_options_html}
              </select>
            </div>

            <div class="field">
              <label for="customer_id">Customer ID</label>
              <input id="customer_id" name="customer_id" list="customer-suggestions" value="{effective_customer_id}" placeholder="e.g. 7590-VHVEG or C00001" required />
              <datalist id="customer-suggestions">
                {customer_options_html}
              </datalist>
              <div style="margin-top: 8px; font-size: 0.8rem; color: var(--muted); font-weight: 600;">Sample Customers:</div>
              <div id="sample-chips" style="display: flex; flex-wrap: wrap; gap: 5px; margin-top: 4px;"></div>
            </div>

            <div class="field">
              <label for="top_n">Top N</label>
              <input id="top_n" name="top_n" type="number" min="1" max="50" value="5" required />
            </div>

            <div class="actions">
              <button type="submit" id="submit-btn">Get recommendations</button>
              <a class="link-button" href="/docs" target="_blank" rel="noreferrer">API docs</a>
            </div>
          </form>

          <div id="status" class="status" aria-live="polite">Ready to fetch recommendations.</div>
          <div style="margin-top: 10px; padding: 8px 10px; background: #f1f5f9; border: 1px dashed #cbd5e1; border-radius: 8px; font-size: 0.78rem; color: var(--muted); font-family: monospace; word-break: break-all;">
            🔑 Active Public Key: <span id="active-key-label">{active_pub_key}</span>
          </div>
          <div class="meta">Known customer samples for '<span id="sample-tenant">{selected_tenant}</span>': <span id="sample-count">{len(current_samples)}</span></div>
          <div class="meta"><a href="/health" target="_blank" rel="noreferrer">Health check</a></div>
        </div>

        <div class="results">
          <div class="results-header">
            <div>
              <h2>Recommendations</h2>
              <p id="results-meta">Loading recommendations automatically...</p>
            </div>
          </div>

          <div id="results">
            <div class="table-wrap">
              <table>
                <thead>
                  <tr><th>Rank</th><th>Product</th><th>Product ID</th><th>Category</th></tr>
                </thead>
                <tbody>
                  <tr><td colspan="4" style="color: var(--muted); padding: 20px 14px;">Loading recommendations...</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script>
    const tenantSamplesMap = {tenant_samples_json};
    const tenantKeysMap = {tenant_keys_json};
    const tenantSelect = document.getElementById('tenant_id');
    const customerInput = document.getElementById('customer_id');
    const customerSuggestions = document.getElementById('customer-suggestions');
    const sampleChipsContainer = document.getElementById('sample-chips');
    const sampleTenantEl = document.getElementById('sample-tenant');
    const sampleCountEl = document.getElementById('sample-count');
    const activeKeyLabel = document.getElementById('active-key-label');
    const form = document.getElementById('recommendation-form');
    const statusEl = document.getElementById('status');
    const resultsEl = document.getElementById('results');
    const resultsMetaEl = document.getElementById('results-meta');

    function renderSampleChips(samples) {{
      if (!sampleChipsContainer) return;
      sampleChipsContainer.innerHTML = '';
      (samples || []).slice(0, 6).forEach(id => {{
        const chip = document.createElement('span');
        chip.style.cssText = 'display:inline-block; padding:3px 8px; background:#eef6ff; color:#0d73c9; border:1px solid #d0e4f7; border-radius:6px; font-size:0.76rem; cursor:pointer; font-weight:600; font-family:monospace;';
        chip.textContent = id.length > 14 ? id.substring(0, 10) + '...' : id;
        chip.title = id;
        chip.addEventListener('click', () => {{
          customerInput.value = id;
          fetchAndRenderRecommendations();
        }});
        sampleChipsContainer.appendChild(chip);
      }});
    }}

    function updateCustomerSuggestions(tenantId, autoSelectFirst = true) {{
      const samples = tenantSamplesMap[tenantId] || [];
      customerSuggestions.innerHTML = samples.map(id => `<option value="${{id}}"></option>`).join('');
      if (sampleCountEl) sampleCountEl.textContent = samples.length;
      if (sampleTenantEl) sampleTenantEl.textContent = tenantId;
      
      const key = tenantKeysMap[tenantId] || ('pk-' + tenantId + '-xxxx');
      if (activeKeyLabel) activeKeyLabel.textContent = key;
      if (typeof window.AIPod !== 'undefined') {{
        window.AIPod.init({{ apiKey: key }});
      }}

      renderSampleChips(samples);

      if (autoSelectFirst && samples.length > 0) {{
        customerInput.value = samples[0];
      }}
    }}

    function setStatus(message, kind = '') {{
      statusEl.textContent = message;
      statusEl.className = 'status ' + kind;
    }}

    function renderRecommendations(payload) {{
      const rows = (payload.recommendations || []).map((item) => `
        <tr>
          <td><span class="rank-badge">${{item.rank}}</span></td>
          <td>
            <div class="product-name">${{item.product_name || item.product_id}}</div>
            <div class="product-id">${{item.product_name ? 'ID: ' + item.product_id : 'Recommended from model'}}</div>
          </td>
          <td><code>${{item.product_id}}</code></td>
          <td>${{item.category ? `<span class="category-tag">${{item.category}}</span>` : '<span style="color:#94a3b8;">&mdash;</span>'}}</td>
        </tr>
      `).join('');

      resultsEl.innerHTML = `
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Rank</th><th>Product</th><th>Product ID</th><th>Category</th></tr>
            </thead>
            <tbody>${{rows || '<tr><td colspan="4" style="padding:16px;">No recommendations found for this customer.</td></tr>'}}</tbody>
          </table>
        </div>
      `;
      const fallbackNotice = payload.fallback ? ' (Popularity Fallback)' : ' (Personalized ML)';
      resultsMetaEl.textContent = `Recommendations for '${{payload.customer_id}}' on tenant '${{payload.tenant_id || 'default'}}'${{fallbackNotice}}`;
    }}

    async function fetchAndRenderRecommendations() {{
      const tenantId = tenantSelect.value.trim();
      const customerId = customerInput.value.trim();
      const topN = Number(document.getElementById('top_n').value || 5);

      if (!customerId || !tenantId) {{
        setStatus('Enter both Tenant ID and Customer ID.', 'error');
        return;
      }}

      setStatus(`Loading recommendations for '${{customerId}}' (${{tenantId}})...`, '');
      resultsMetaEl.textContent = 'Fetching recommendations from model...';

      try {{
        const apiKey = tenantKeysMap[tenantId] || ('pk-' + tenantId + '-xxxx');
        const headers = {{ 'X-API-Key': apiKey }};
        const response = await fetch(`/v1/recommendations?customer_id=${{encodeURIComponent(customerId)}}&top_n=${{topN}}&tenant_id=${{encodeURIComponent(tenantId)}}`, {{
          headers: headers
        }});
        const text = await response.text();
        let payload;
        try {{
          payload = JSON.parse(text);
        }} catch (e) {{
          throw new Error(`Server returned HTTP ${{response.status}}: ${{text.substring(0, 100)}}`);
        }}

        if (!response.ok) {{
          throw new Error(payload.detail || 'Request failed');
        }}

        setStatus(`Loaded ${{payload.recommendations ? payload.recommendations.length : 0}} recommendations for ${{customerId}} (Tenant: ${{tenantId}}).`, 'success');
        renderRecommendations(payload);
      }} catch (error) {{
        resultsMetaEl.textContent = 'Unable to load recommendations.';
        setStatus(error.message, 'error');
      }}
    }}

    tenantSelect.addEventListener('change', (e) => {{
      const newTenant = e.target.value;
      updateCustomerSuggestions(newTenant, true);
      fetchAndRenderRecommendations();
    }});

    form.addEventListener('submit', async (event) => {{
      event.preventDefault();
      fetchAndRenderRecommendations();
    }});

    // Initialize sample chips and automatically fetch recommendations as soon as site launches
    const initialSamples = tenantSamplesMap[tenantSelect.value] || [];
    renderSampleChips(initialSamples);
    if (customerInput.value) {{
      fetchAndRenderRecommendations();
    }}
  </script>
</body>
</html>
"""


@router.get("/ui/tenants")
def get_tenants_endpoint() -> dict[str, Any]:
    """Return list of all configured tenants."""
    return {"tenants": get_available_tenants()}


@router.get("/ui/sample-customers")
def get_sample_customers_endpoint(
    tenant_id: str = Query("telco_default", description="Tenant ID")
) -> dict[str, Any]:
    """Return sample customer IDs for the given tenant."""
    return {
        "tenant_id": tenant_id,
        "sample_customer_ids": get_sample_customer_ids(tenant_id),
    }


@router.get("/ui", response_class=HTMLResponse)
def home(
    tenant_id: str | None = Query(None, description="Default selected Tenant ID"),
    customer_id: str | None = Query(None, description="Default Customer ID"),
) -> HTMLResponse:
    return HTMLResponse(build_home_page(tenant_id=tenant_id, default_customer_id=customer_id))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.app:app", host="0.0.0.0", port=8000, reload=True)