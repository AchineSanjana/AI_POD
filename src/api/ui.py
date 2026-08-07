from __future__ import annotations

import json

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from src.api.recommendations import get_model_for_tenant


router = APIRouter(tags=["ui"])


def get_sample_customer_ids(tenant_id: str = "telco_default", limit: int = 20) -> list[str]:
    try:
        model = get_model_for_tenant(tenant_id)
    except Exception:
        return []

    customers = getattr(model, "customers_", None)
    if customers is None or customers.empty:
        return []

    if "customerID" in customers.columns:
        customers = customers.rename(columns={"customerID": "customer_id"})

    return customers["customer_id"].dropna().astype(str).head(limit).tolist()


def build_home_page(tenant_id: str = "telco_default", default_customer_id: str | None = None) -> str:
    sample_ids = get_sample_customer_ids(tenant_id)
    effective_customer_id = default_customer_id or (sample_ids[0] if sample_ids else "7590-VHVEG")
    options_html = "".join(f'<option value="{customer_id}"></option>' for customer_id in sample_ids)
    sample_ids_json = json.dumps(sample_ids)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Recommendations UI</title>
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
      grid-template-columns: 320px minmax(0, 1fr);
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

    .field input {{
      width: 100%;
      padding: 12px 14px;
      border: 1px solid var(--border);
      border-radius: 10px;
      font: inherit;
      outline: none;
      background: #fff;
    }}

    .field input:focus {{
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
        <p class="subtext">Enter a Tenant ID and Customer ID to fetch recommendations from the FastAPI app.</p>
        <div class="simple-row">
          <span class="pill">FastAPI</span>
          <span class="pill">Multi-Tenant</span>
          <span class="pill">Model-backed</span>
        </div>
      </div>

      <div class="content">
        <div class="panel">
          <h2>Get recommendations</h2>
          <form id="recommendation-form">
            <div class="field">
              <label for="tenant_id">Tenant ID</label>
              <input id="tenant_id" name="tenant_id" value="{tenant_id}" required />
            </div>

            <div class="field">
              <label for="customer_id">Customer ID</label>
              <input id="customer_id" name="customer_id" list="customer-suggestions" value="{effective_customer_id}" required />
              <datalist id="customer-suggestions">
                {options_html}
              </datalist>
            </div>

            <div class="field">
              <label for="top_n">Top N</label>
              <input id="top_n" name="top_n" type="number" min="1" max="50" value="5" required />
            </div>

            <div class="actions">
              <button type="submit">Get recommendations</button>
              <a class="link-button" href="/docs" target="_blank" rel="noreferrer">API docs</a>
            </div>
          </form>

          <div id="status" class="status" aria-live="polite">Ready to fetch recommendations.</div>
          <div class="meta">Known customer samples for '{tenant_id}': {len(sample_ids)}</div>
          <div class="meta"><a href="/health" target="_blank" rel="noreferrer">Health check</a></div>
        </div>

        <div class="results">
          <div class="results-header">
            <div>
              <h2>Recommendations</h2>
              <p id="results-meta">Results will appear here after you search.</p>
            </div>
          </div>

          <div id="results">
            <div class="table-wrap">
              <table>
                <thead>
                  <tr><th>Rank</th><th>Product</th><th>Product ID</th><th>Category</th></tr>
                </thead>
                <tbody>
                  <tr><td colspan="4" style="color: var(--muted);">No recommendations loaded yet.</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script>
    const sampleCustomerIds = {sample_ids_json};
    const form = document.getElementById('recommendation-form');
    const statusEl = document.getElementById('status');
    const resultsEl = document.getElementById('results');
    const resultsMetaEl = document.getElementById('results-meta');

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
            <div class="product-id">${{item.product_name ? 'Recommended from the local model' : 'No display name found'}}</div>
          </td>
          <td>${{item.product_id}}</td>
          <td>${{item.category ? `<span class="category-tag">${{item.category}}</span>` : ''}}</td>
        </tr>
      `).join('');

      resultsEl.innerHTML = `
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Rank</th><th>Product</th><th>Product ID</th><th>Category</th></tr>
            </thead>
            <tbody>${{rows || '<tr><td colspan="4">No recommendations found.</td></tr>'}}</tbody>
          </table>
        </div>
      `;
      resultsMetaEl.textContent = `Recommendations for ${{payload.customer_id}} (Tenant: ${{payload.tenant_id || 'default'}})`;
    }}

    form.addEventListener('submit', async (event) => {{
      event.preventDefault();
      const tenantId = document.getElementById('tenant_id').value.trim();
      const customerId = document.getElementById('customer_id').value.trim();
      const topN = Number(document.getElementById('top_n').value || 5);

      if (!customerId || !tenantId) {{
        setStatus('Enter both Tenant ID and Customer ID.', 'error');
        return;
      }}

      setStatus('Loading recommendations...', '');
      resultsMetaEl.textContent = 'Fetching fresh recommendations...';

      try {{
        const response = await fetch(`/recommendations/${{encodeURIComponent(customerId)}}?tenant_id=${{encodeURIComponent(tenantId)}}&top_n=${{topN}}`);
        const payload = await response.json();

        if (!response.ok) {{
          throw new Error(payload.detail || 'Request failed');
        }}

        setStatus(`Loaded recommendations for ${{customerId}} (Tenant: ${{tenantId}}).`, 'success');
        renderRecommendations(payload);
      }} catch (error) {{
        resultsMetaEl.textContent = 'Unable to load recommendations.';
        setStatus(error.message, 'error');
      }}
    }});
  </script>
</body>
</html>
"""


@router.get("/ui", response_class=HTMLResponse)
def home(
    tenant_id: str = Query("telco_default", description="Tenant ID"),
    customer_id: str | None = Query(None, description="Default Customer ID"),
) -> HTMLResponse:
    return HTMLResponse(build_home_page(tenant_id=tenant_id, default_customer_id=customer_id))