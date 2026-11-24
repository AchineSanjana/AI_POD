# Step S3: Similar Products in Dashboard and Onboarding Wizard

## 1. Overview
Step S3 brings the Similar Products engine into the AI_POD dashboard and onboarding wizard:
1. **Interactive Testing in Integrate Wizard**: Merchants can pick an active product from their catalogue, configure `top_n` and category filtering, and preview real similarity recommendations with reason tags, price differences, and scores.
2. **Ready-to-Use Code Snippets**: Auto-generated HTML script tags, JavaScript SDK, and npm snippets embedded with the tenant's real public API key (`pk-...`). Private keys (`sk-...`) are never exposed or stored in client-side code or localStorage.
3. **Catalogue Row Preview Drawer**: Instant "Preview similar" side panel accessible from both the Catalogue table row actions and the Product Drawer for active catalogue items (disabled for archived items with an informative tooltip).
4. **Analytics Telemetry Reporting**: Dedicated "Similar products" analytics section and "Personalised recommendations" mini-block displaying real event metrics, 1-decimal CTR with tooltip explanation, Recharts conversion funnel, top compared source products, and honest empty states.
5. **Overview Metrics Card**: Compact "Similar products: N requests, X% CTR" card auto-refreshed every 30 seconds.
6. **Telemetry Isolation**: All testing requests from the Integrate step and Catalogue drawer send `X-AIPOD-Source: wizard-test`, ensuring merchant testing never skews production metrics.

---

## 2. Files Changed & Created

| File | Type | Description |
|------|------|-------------|
| `frontend/src/api/client.js` | Modified | Added `getSimilarProducts(productId, { topN, sameCategory }, pk)` with header `X-AIPOD-Source: wizard-test`. Configured `BASE_URL` to default to `/v1` in production builds (`!import.meta.env.PROD ? import.meta.env.VITE_API_URL : '/v1'`). |
| `frontend/src/components/SimilarResults.jsx` | Created | Reusable React component for previewing similar products with LKR formatting, price difference calculation, similarity score badges, reason tags, and fallback banner. Strictly restricts images to `http://` or `https://` schemes. |
| `frontend/src/pages/onboarding/IntegrateStep.jsx` | Modified | Added "Test similar products" interactive panel with debounced active catalogue picker, `top_n` slider (3–8), same-category toggle, `<SimilarResults />`, copy-ready integration snippets with real `pk` key, CORS origin notice, and empty catalogue redirect. |
| `frontend/src/pages/dashboard/Catalog.jsx` | Modified | Added "Preview similar" button in product table rows and inside `ProductDrawer`, disabled for archived products with tooltip. Added full-height slide-out side drawer (`.preview-similar-drawer`, 100vw on mobile, 580px on desktop) embedding `<SimilarResults />`. |
| `frontend/src/pages/dashboard/Analytics.jsx` | Modified | Added "Personalised recommendations" mini-block and "Similar products" section with real metrics pills (requests, clicks, add-to-carts, purchases, 1-decimal CTR with tooltip), Recharts funnel bar chart, top compared products list, and honest zero-activity empty state. |
| `frontend/src/pages/dashboard/Overview.jsx` | Modified | Added compact card "Similar products: N requests, X% CTR" auto-refreshing every 30 seconds while the browser tab is visible. |
| `frontend/src/index.css` | Modified | Added responsive CSS rule for mobile viewport to render `.preview-similar-drawer` at full viewport width (`100vw`). |
| `src/api/app.py` | Modified | Added `http://localhost:8000` and `http://127.0.0.1:8000` to default `allowed_origins`; added `@app.get("/verify-email")` and `@app.get("/onboarding/{full_path:path}")` to serve `index.html`; removed redundant root-level `app.include_router(dashboard_router)` to prevent collision between backend API routes and frontend SPA `/dashboard/*` routes. |
| `scripts/verify_s3_browser.py` | Created | Automated Playwright + Chromium verification script verifying all functional assertions, telemetry isolation, XSS protection, and responsive layouts across viewports 390x844 and 1280x900. |
| `tests/test_s3_browser.py` | Created | Pytest wrapper for Playwright browser verification, skipped when Playwright or Chromium is not available. |
| `docs/screenshots/s3_*.png` | Created | 8 full-page screenshots captured during automated browser testing across mobile and desktop viewports. |

---

## 3. Exact API Fields Used

### A. Analytics Page (`GET /v1/dashboard/analytics?days=7`)
- **Similar Products Section**:
  - `similar_requests`: Total similar product recommendation requests (`kind == "similar"`).
  - `similar_clicks`: Total tracked click events with `source == "similar"`.
  - `similar_add_to_carts`: Total tracked add-to-cart events with `source == "similar"`.
  - `similar_purchases`: Total tracked purchase events with `source == "similar"`.
  - `similar_ctr`: Click-through rate defined as distinct `rec_id`s with at least one click divided by non-test requests (displayed as percentage with 1 decimal, e.g. `40.0%`, or `—` when null). Tooltip: *"Share of requests that received at least one click."*
  - `top_similar_source_products`: List of `{ product_id, product_name, count }` displaying the top source products users viewed before clicking similar items.
- **Personalised Recommendations Mini-Block**:
  - `recommendation_clicks`
  - `recommendation_ctr`
  - `recommendation_add_to_carts`
  - `recommendation_purchases`

### B. Overview Page (`GET /v1/dashboard/analytics?days=7` or `/overview`)
- Compact card displaying:
  - `similar_requests`: Formatted integer request count (e.g. `5 requests`).
  - `similar_ctr`: Percentage with 1 decimal (e.g. `40.0% CTR`, or `—% CTR` when null).

### C. Similar Products Endpoint (`GET /v1/recommendations/similar/{product_id}`)
- `rec_id`: 16-character hexadecimal recommendation identifier.
- `target`: Target product details: `product_id`, `product_name`, `category`, `brand`, `price`, `image_url`, `specs`.
- `similar_products`: Array of items with:
  - `product_id`, `product_name`, `category`, `brand`, `price`
  - `price_diff`: Difference relative to target product (`item.price - target.price`), formatted with +/- LKR.
  - `score`: Similarity score formatted as percentage (e.g. `85% match`).
  - `reasons`: Human-readable match reasons (e.g. `["Same category: Smartphones", "Price match (within 10%)"]`).
  - `specs`: Dictionary of normalized specifications (e.g. `{"RAM (GB)": 12, "Storage (GB)": 512}`).
- `fallback`: Boolean indicating whether recommendations fell back to popular items.
- `reason`: Reason string if fallback occurred (e.g. `unknown_product`).

---

## 4. Real Browser Verification Results

The automated Playwright + Chromium browser test suite (`scripts/verify_s3_browser.py`) was executed against a running FastAPI backend and built frontend SPA with two dedicated throwaway accounts:
1. `e2e_tenant_empty_*`: Brand-new unconfigured tenant with no catalogue or telemetry.
2. `e2e_tenant_active_*`: Tenant with a 30-product catalogue (including XSS test payload `<img src=x onerror=alert(1)>`) and 5 live similar requests, 2 clicks, 1 add-to-cart.

### Assertion Summary Table

| Assertion | Viewport: 390x844 (Mobile) | Viewport: 1280x900 (Desktop) | Status |
|-----------|:-------------------------:|:----------------------------:|:------:|
| **(a) Integrate step**: Product picker lists active items, selecting one shows $\ge 3$ result cards with reasons; snippets contain real `pk` key; no `sk-` string appears in HTML or localStorage | **PASS** | **PASS** | Passed |
| **(b) Catalogue Preview**: Clicking "Preview similar" opens the side panel (`.preview-similar-drawer`) with $\ge 3$ similar product cards | **PASS** | **PASS** | Passed |
| **(c) XSS Prevention**: Product named `<img src=x onerror=alert(1)>` renders safely as escaped text (`&lt;img ...&gt;`); 0 malicious `<img>` tags created; 0 dialogs triggered | **PASS** | **PASS** | Passed |
| **(d) Analytics Telemetry**: Analytics page reflects 5 requests, 2 clicks, 40.0% CTR, 1 add-to-cart, funnel counts equal API response; wizard-test requests uncounted | **PASS** | **PASS** | Passed |
| **(e) Overview Card**: Overview page compact card reflects "Similar products: 5 requests, 40.0% CTR" | **PASS** | **PASS** | Passed |
| **(f) Honest Empty State**: Brand-new tenant displays *"No similar-product activity yet"* on Analytics page and *"Catalogue is currently empty"* on Integrate step | **PASS** | **PASS** | Passed |
| **(g) Layout & Stability**: `scrollWidth <= innerWidth` (zero horizontal overflow) across all tested pages and viewports; 0 unhandled console errors | **PASS** | **PASS** | Passed |

---

## 5. Verification Separation

### Verified in a Real Browser (Playwright + Chromium)
- Real user authentication via `/signin` page with session token storage in `localStorage`.
- Real network requests to `/v1/accounts/me`, `/v1/catalog/products`, `/v1/recommendations/similar/*`, and `/v1/dashboard/analytics`.
- Real CSS rendering and viewport adaptations: full-width drawer on mobile (`390px`), 580px side drawer on desktop (`1280px`).
- DOM verification that XSS payload `<img src=x onerror=alert(1)>` is escaped as text with 0 dialogs.
- Interactive component behaviors: dropdown picker change, drawer open/close button clicks, Recharts SVG rendering.
- Telemetry isolation: testing interactions bearing `X-AIPOD-Source: wizard-test` did not increment the production request count.

### Verified by Build, Lint & Automated Test Suite
- `oxlint`: 0 lint errors across 30 files with 104 rules.
- `vite build`: Production build completed cleanly with 0 errors in 3.06s.
- `pytest tests/ -q`: Full test suite passed with **431 passed** out of 431 tests in 1681.15s (28m 01s).

---

## 6. Exact Test, Lint & Build Totals

- **Pytest Suite**: `431 passed` in `1681.15s` (`tests/test_s3_browser.py` included).
- **Frontend Lint**: `Found 22 warnings and 0 errors. Finished in 228ms on 30 files.`
- **Frontend Build**:
  - `dist/index.html`: `0.93 kB` (gzip: `0.49 kB`)
  - `dist/assets/index-l1VivkoS.css`: `8.46 kB` (gzip: `2.68 kB`)
  - `dist/assets/index-CjShGbc1.js`: `884.82 kB` (gzip: `245.56 kB`)
  - Built in `3.06s`.

---

## 7. Modified Existing Tests & Reasons

| Test File | Reason for Modification |
|-----------|-------------------------|
| `tests/test_api_auth.py` | Restored original strict assertions against `telco_default` with no catalogue after removing stray catalogue data. |
| `tests/test_api_multitenancy.py` | Restored original strict assertions verifying empty catalogue response for `telco_default`. |
| `tests/test_pipeline_s3_e2e.py` | Removed workaround copying `telco_default` catalogue into mocked S3. |

*(All other Step S3 changes are purely additive and maintain strict backward compatibility.)*

---

## 8. Captured Screenshots

Screenshots captured during automated browser verification:
- [s3_integrate_390.png](file:///d:/Projects/AI_POD/docs/screenshots/s3_integrate_390.png): Integrate step on mobile (390x844).
- [s3_catalog_390.png](file:///d:/Projects/AI_POD/docs/screenshots/s3_catalog_390.png): Catalogue "Preview similar" drawer on mobile (390x844, viewport-sized).
- [s3_analytics_390.png](file:///d:/Projects/AI_POD/docs/screenshots/s3_analytics_390.png): Analytics page on mobile (390x844, viewport-sized).
- [s3_overview_390.png](file:///d:/Projects/AI_POD/docs/screenshots/s3_overview_390.png): Overview page on mobile (390x844, viewport-sized).
- [s3_integrate_1280.png](file:///d:/Projects/AI_POD/docs/screenshots/s3_integrate_1280.png): Integrate step on desktop (1280x900).
- [s3_catalog_1280.png](file:///d:/Projects/AI_POD/docs/screenshots/s3_catalog_1280.png): Catalogue "Preview similar" drawer on desktop (1280x900).
- [s3_analytics_1280.png](file:///d:/Projects/AI_POD/docs/screenshots/s3_analytics_1280.png): Analytics page on desktop (1280x900).
- [s3_overview_1280.png](file:///d:/Projects/AI_POD/docs/screenshots/s3_overview_1280.png): Overview page on desktop (1280x900).

*(Note on screenshot completeness: As audited, `s3_overview_390.png`, `s3_analytics_390.png`, and `s3_catalog_390.png` above were captured at viewport dimensions (844px high) rather than full scrollable page height. The S3b wrap-up suite re-captured all screenshots with strict `full_page=True` as `docs/screenshots/s3b_*.png`, including the dedicated mobile Analytics similar-products section.)*

---

## 9. Known Limitations & Configuration

### Storefront CORS Origin Configuration
Allowed storefront origins are enforced by the server-side `CORSMiddleware` configured via the `CORS_ORIGINS` environment variable (e.g. `CORS_ORIGINS="https://store.example.com,https://staging.example.com"`).
- **Scope**: CORS origins are a **server-level** configuration, not a per-tenant database configuration.
- **Storefront Behavior**: If a merchant attempts to load the Similar Products SDK snippet or send `/v1/track` events from an origin not present in `CORS_ORIGINS`, the browser blocks the preflight `OPTIONS` request.
- **Guidance in UI**: The Integrate step displays a visible note informing merchants:
  > *"Your storefront's origin must be allowed by the API (CORS_ORIGINS) before the widgets load on your site."*

