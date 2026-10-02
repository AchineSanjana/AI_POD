# Schema Contracts & Configuration Reference Manual

This document is the definitive developer guide for onboarding new datasets and configuring multi-tenant recommendation pipelines in **AI_POD**.

The platform is designed to be **100% domain-agnostic**: whether your data represents telecom subscriptions, movie ratings, e-commerce purchases, or SaaS feature usage, the engine normalizes all inputs into standard schema contracts without modifying recommender algorithms or training code.

---

## 1. Domain-Agnostic Schema Contracts

All data adapters must produce three normalized pandas DataFrames conforming to the contracts defined in [`src/core/schema.py`](file:///d:/Projects/AI_POD/src/core/schema.py).

```
                    ┌─────────────────────────┐
                    │    Raw Tenant Data      │
                    │ (CSV, Parquet, Database)│
                    └────────────┬────────────┘
                                 │
                     [GenericConfigAdapter]
                                 │
     ┌───────────────────────────┼───────────────────────────┐
     ▼                           ▼                           ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ CustomerSchema  │     │  ProductSchema  │     │InteractionSchema│
│ - customer_id   │     │ - product_id    │     │ - customer_id   │
│ - FeatureSpecs  │     │ - product_name  │     │ - product_id    │
│                 │     │ - category      │     │ - weight (1.0)  │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### 1.1 `FeatureSpec` Specification

A [`FeatureSpec`](file:///d:/Projects/AI_POD/src/core/schema.py#L67-L75) defines metadata for a single feature column:

```python
@dataclass(frozen=True)
class FeatureSpec:
    name: str
    dtype: Literal["numeric", "categorical"]
    allowed_values: list[str] | None = None
    encoding: Literal["passthrough", "one_hot"] = "passthrough"
```

| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `name` | `str` | **Yes** | The column name in the customer or product DataFrame. |
| `dtype` | `"numeric"` \| `"categorical"` | **Yes** | Data type of the column. `numeric` enforces `float`/`int` types; `categorical` treats values as discrete tokens. |
| `allowed_values` | `list[str]` \| `None` | Optional | For `categorical` features: the strict set of valid values. Values outside this list trigger descriptive validation warnings/errors. |
| `encoding` | `"passthrough"` \| `"one_hot"` | Optional | How the feature is encoded for ML models (default `"passthrough"`). Set `"one_hot"` for discrete nominal categories in gradient boosting. |

---

### 1.2 `CustomerSchema` Contract

The [`CustomerSchema`](file:///d:/Projects/AI_POD/src/core/schema.py#L77-L115) enforces user-level attributes used by content-based and learned ranking models.

* **Primary Key**: `customer_id` (`str` / `object`) — unique identifier for each customer.
* **Feature Columns**: One column per configured `FeatureSpec.name`.

**Validation Rules**:
1. `validate(df)`: Ensures `customer_id` and all configured `FeatureSpec.name` columns exist.
2. `validate_values(df)`: Enforces numeric dtypes and verifies that categorical columns only contain values in `allowed_values`.

---

### 1.3 `ProductSchema` Contract

The [`ProductSchema`](file:///d:/Projects/AI_POD/src/core/schema.py#L116-L163) represents catalog items available for recommendation.

* **Primary Key**: `product_id` (`str`) — unique product or service identifier.
* **Display Label**: `product_name` (`str`) — human-readable title (e.g. `"Streaming TV"`, `"The Matrix"`).
* **Category**: `category` (`str`, optional) — grouping metadata (e.g. `"Core"`, `"Add-On"`, `"Sci-Fi"`).
* **Feature Columns**: Additional `FeatureSpec` columns describing item attributes.

---

### 1.4 `InteractionSchema` Contract

The [`InteractionSchema`](file:///d:/Projects/AI_POD/src/core/schema.py#L164-L201) standardizes customer-product engagement into canonical long-format rows.

* **Foreign Keys**: `customer_id` (`str`), `product_id` (`str`).
* **Interaction Weight**: `weight` (`float`, optional) — interaction strength (defaults to `1.0` for positive events).
* **Timestamp**: `timestamp` (optional) — interaction event time.

> [!NOTE]
> All primary and foreign keys (`customer_id`, `product_id`) are coerced to strings across all schemas to prevent integer vs. object merge errors.

---

## 2. Declarative Tenant Configuration Reference

Tenant configurations are defined under the top-level `tenants:` dictionary in [`config/config.yaml`](file:///d:/Projects/AI_POD/config/config.yaml).

### Annotated Reference Example: `telco_default`

```yaml
tenants:
  telco_default:
    # -------------------------------------------------------------------------
    # 1. Raw Data Source Location
    # -------------------------------------------------------------------------
    data_source:
      type: csv                           # File format: 'csv' or 'parquet'
      path: data/raw/telco_customer_churn.csv # Path relative to project root

    # -------------------------------------------------------------------------
    # 2. Customer Metadata & Feature Contracts
    # -------------------------------------------------------------------------
    customers:
      id_column: customerID               # Raw ID column to rename to 'customer_id'
      features:
        - name: gender
          dtype: categorical
          allowed_values: ["Female", "Male"]
        - name: SeniorCitizen
          dtype: numeric
        - name: Partner
          dtype: categorical
          allowed_values: ["Yes", "No"]
        - name: Dependents
          dtype: categorical
          allowed_values: ["Yes", "No"]
        - name: tenure
          dtype: numeric
        - name: Contract
          dtype: categorical
          allowed_values: ["Month-to-month", "One year", "Two year"]
          encoding: one_hot               # One-hot encode for XGBoost ranking model
        - name: PaperlessBilling
          dtype: categorical
          allowed_values: ["Yes", "No"]
        - name: PaymentMethod
          dtype: categorical
        - name: MonthlyCharges
          dtype: numeric
        - name: TotalCharges
          dtype: numeric
        - name: Churn
          dtype: categorical
          allowed_values: ["Yes", "No"]

    # -------------------------------------------------------------------------
    # 3. Product Catalog Derivation Rules
    # -------------------------------------------------------------------------
    products:
      derived_from: interaction_source    # Derive catalog from interaction services
      category_column: category           # Output category field name

    # -------------------------------------------------------------------------
    # 4. Interaction Transformation Rules
    # -------------------------------------------------------------------------
    interactions:
      source: interaction_source          # Use configured service column matrix
      service_columns: [
        "PhoneService", "MultipleLines", "OnlineSecurity",
        "OnlineBackup", "DeviceProtection", "TechSupport",
        "StreamingTV", "StreamingMovies"
      ]
      positive_values: ["Yes"]            # Values mapped to positive interactions
      negative_values: ["No", "No internet service", "No phone service"] # Excluded

    # -------------------------------------------------------------------------
    # 5. Domain-Agnostic Customer Segmentation (Optional)
    # -------------------------------------------------------------------------
    segmentation:
      field: tenure                       # Any numeric customer feature
      split: median                       # 'median' split into 'newer' vs 'established'
```

---

## 3. Interaction Source Transformation Engine

Many tabular datasets represent customer activity in wide format (e.g. boolean/enum columns per service). The [`GenericConfigAdapter`](file:///d:/Projects/AI_POD/src/data/adapters/generic_config_adapter.py) pivots wide matrix columns into canonical long-format rows using [`InteractionSourceConfig`](file:///d:/Projects/AI_POD/src/utils/config.py#L182-L188):

```
Wide Format Input:
┌─────────────┬──────────────┬───────────────┬────────────────┐
│ customer_id │ PhoneService │ StreamingTV   │ TechSupport    │
├─────────────┼──────────────┼───────────────┼────────────────┤
│ CUST_001    │ Yes          │ Yes           │ No             │
└─────────────┴──────────────┴───────────────┴────────────────┘
                               │
                       [Pivoting Engine]
                               │
Long Format Output:
┌─────────────┬─────────────────┬────────┐
│ customer_id │ product_id      │ weight │
├─────────────┼─────────────────┼────────┤
│ CUST_001    │ PhoneService    │ 1.0    │
│ CUST_001    │ StreamingTV     │ 1.0    │
└─────────────┴─────────────────┴────────┘
```

### Config Parameters:

1. **`service_columns`** (`list[str]`):
   * The list of column names in the raw table representing available products or services.
   * Each column becomes an entity in the [`ProductSchema`](file:///d:/Projects/AI_POD/src/core/schema.py#L117) catalog.
2. **`positive_values`** (`list[str]`):
   * String tokens representing an active subscription, purchase, or high rating (e.g. `["Yes"]`, `["Purchased"]`, `["4", "5"]`).
   * Rows with these values generate interactions with `weight = 1.0`.
3. **`negative_values`** (`list[str]`):
   * String tokens representing non-engagement, absence of service, or explicit opt-out (e.g. `["No"]`, `["No internet service"]`).
   * These are excluded from positive training interactions.

### 3.2 Transactional Interaction Source (`source: transactional`)

For datasets where each row is an individual transaction or order record (e.g. retail, e-commerce order lines):

```yaml
interactions:
  source: transactional
  customer_id_column: CustomerID
  product_id_column: StockCode
  product_name_column: Description      # used for display, not modeling
  quantity_column: Quantity              # optional, used as interaction "weight"
  transaction_id_column: InvoiceNo       # optional, used to dedupe/group
  exclude_invoice_prefix: "C"            # optional cleaning rule for cancelled orders
```

The [`build_transactional_interactions`](file:///d:/Projects/AI_POD/src/data/interaction_extraction.py) function groups rows by `(customer_id, product_id)`:
- Emits exactly **ONE** interaction row per unique customer–product pair.
- Aggregates `quantity_column` into `weight` (sum of quantities across orders) if specified.
- Automatically removes invalid/missing customer, product, and invoice records.
- Filters out cancelled transactions matching `exclude_invoice_prefix` (e.g. "C" for cancellations in online retail).

---

## 4. Tenant Onboarding Checklist & Troubleshooting

Follow this checklist when adding a new tenant to the system:

### Onboarding Checklist

```markdown
- [ ] 1. Place raw data file under `data/raw/<tenant_id>.<ext>`
- [ ] 2. Add tenant configuration block in `config/config.yaml`
- [ ] 3. Set `data_source.path` to the raw data file path
- [ ] 4. Configure `customers.id_column` to match raw primary key column name
- [ ] 5. Declare all numeric & categorical features under `customers.features`
- [ ] 6. For categorical features with fixed vocabularies, provide `allowed_values`
- [ ] 7. Define `interactions.service_columns`, `positive_values`, and `negative_values`
- [ ] 8. (Optional) Define `segmentation.field` for 'newer' vs 'established' reporting
- [ ] 9. Assign an API key in `config/config.yaml` under `tenants_auth:`
- [ ] 10. Execute pipeline: `python scripts/run_pipeline.py --tenant_id <tenant_id>`
- [ ] 11. Verify offline metrics: `python scripts/generate_evaluation_results.py --tenant_id <tenant_id>`
```

---

### Common Pitfalls & Error Handling Reference

| Error / Pitfall | Cause | Resolution |
| :--- | :--- | :--- |
| `KeyError: Tenant '<tenant>' missing required section 'customers'` | Missing required subfield in YAML configuration. | Verify YAML indentation and confirm all top-level keys (`data_source`, `customers`, `products`, `interactions`) are present. |
| `ValueError: CustomerSchema: missing required column 'customer_id'` | Raw primary key was not mapped. | Ensure `customers.id_column` exactly matches the ID column in your raw CSV/Parquet file. |
| `ValueError: CustomerSchema: column '<col>' contains values not in allowed_values` | Observed data contains categories not listed in `allowed_values`. | Add missing valid values to `allowed_values: [...]` in `config.yaml`, or omit `allowed_values` to allow arbitrary categories. |
| `ValueError: CustomerSchema: column '<col>' must be numeric, got dtype 'object'` | A numeric column contains whitespace, currency symbols, or null strings (e.g. `" "`). | Ensure raw numeric columns are clean or let adapter apply `pd.to_numeric(errors="coerce")`. |
| `KeyError: 'tenants_auth'` or `401 Unauthorized` | API request sent without `X-API-Key` or key not mapped to tenant. | Add `"sk-<tenant>-xxxx": "<tenant_id>"` under `tenants_auth:` in `config.yaml`. |
| `HTTPException 404: Customer not found` | Customer ID queried in API does not exist for that tenant. | Query a valid `customer_id` present in `data/processed/<tenant_id>/customers.csv`. |
| `ValueError: interactions must contain columns: ['customer_id', 'product_id']` | Custom adapter failed to emit canonical primary keys. | Ensure custom `DataAdapter.to_interactions()` returns columns `["customer_id", "product_id"]`. |

---

## 5. End-to-End Execution Commands

```bash
# 1. Run pipeline end-to-end for a tenant (Ingest -> Train -> Evaluate -> Persist)
python scripts/run_pipeline.py --tenant_id movielens_demo

# 2. Test recommendation serving via CLI
python scripts/get_recommendations.py --tenant_id movielens_demo --customer_id 1 --top_n 5

# 3. Generate standalone per-tenant report + generalization proof
python scripts/generate_evaluation_results.py --tenant_id movielens_demo

# 4. Run automated test suite
pytest tests/ -v
```

---

## 6. Company Accounts & Tenant Ownership Schema

AI_POD provides an explicit **Company Account** concept distinct from `tenant_id`. While tenant identifiers represent isolated operational environments (data, models, recommendations), accounts represent the owning legal/corporate entity and developer credentials.

### 6.1 Accounts Storage Schema (Step 15.2 Pattern)

Accounts follow the Step 15.2 local-file-vs-AWS-secure-storage pattern:
- **Local Development**: `config/accounts.local.yaml` (git-ignored, template in `config/accounts.example.yaml`).
- **Production (AWS mode `STORAGE_BACKEND=s3`)**: AWS SSM Parameter Store (`/ai_pod/accounts` or `ACCOUNTS_SSM_PARAM`) or AWS Secrets Manager (`ACCOUNTS_SECRET_NAME`).

```yaml
accounts:
  acc_8f2k1x:
    tenant_id: acme_corp
    company_name: "Acme Corp"
    email: "dev@acme.com"
    password_hash: "<bcrypt hash, never plaintext>"
    created_at: "2026-10-05T10:00:00Z"
    email_verified: false
```

| Field | Type | Description |
| :--- | :--- | :--- |
| `tenant_id` | `str` | Provisioned slugified identifier for the company tenant environment. |
| `company_name` | `str` | Display name of the registered company. |
| `email` | `str` | Normalized (lowercase) primary contact / developer email. |
| `password_hash` | `str` | Strong salted bcrypt hash (e.g. `$2b$12$...`). Plaintext passwords are never stored or logged. |
| `created_at` | `str` | ISO-8601 UTC timestamp of account registration. |
| `email_verified` | `bool` | Email verification flag (default `false`). |

### 6.2 Signup Endpoint: `POST /v1/accounts/signup`

Creates a new account, provisions an isolated tenant environment, and automatically issues API keys:
- **Request Body**: `{"company_name": "...", "email": "...", "password": "..."}`
- **Validation**:
  - Validates email format.
  - Validates password strength (minimum 8 characters).
  - Rejects duplicate email addresses with `409 Conflict`.
- **Security & Password Hashing**: Plaintext password is cryptographically hashed with `bcrypt`; plaintext passwords are never returned in response bodies or emitted to log files.
- **Tenant Provisioning**: Derives `tenant_id` by slugifying `company_name` (appending a short random suffix if a collision occurs).
- **Automatic Key Issuance (Step 15 Integration)**: Automatically calls `issue_tenant_keys` to issue both a private key (`sk-...`) and a public key (`pk-...`) with zero restart or extra manual steps required.
- **IP-Based Rate Limiting**: Since signup is a public, unauthenticated endpoint, it is protected by an independent sliding-window rate limiter keyed by client IP (`SIGNUP_RATE_LIMITER`, defaulting to 5 requests per 60 seconds). Excessive signups from the same IP are rejected with `HTTP 429 Too Many Requests` including standard `Retry-After` headers, leaving signups from other IPs unaffected.
- **Single-Disclosure Policy**: The private key is disclosed in plaintext strictly once in the signup response. Frontend Step 24.4 must prompt the user to copy and store it securely.
- **Response**: HTTP 201 Created with:
  ```json
  {
    "account_id": "acc_8f2k1x",
    "tenant_id": "acme_corp",
    "company_name": "Acme Corp",
    "email": "dev@acme.com",
    "private_key": "sk-acme_corp-xxxxxxxx",
    "public_key": "pk-acme_corp-xxxxxxxx",
    "note": "The private key is shown here once and will not be retrievable in plaintext again. Please store it securely.",
    "warning": "The private key is shown here once and will not be retrievable in plaintext again. Please store it securely.",
    "created_at": "2026-10-02T12:00:00Z",
    "email_verified": false
  }
  ```

### 6.3 Login Endpoint: `POST /v1/accounts/login`

Authenticates company account credentials and issues a short-lived signed JWT session token:
- **Request Body**:
  ```json
  {
    "email": "dev@acme.com",
    "password": "CorrectPassword123!"
  }
  ```
- **Authentication**: Verifies password against the stored bcrypt hash. Rejects incorrect credentials or non-existent emails with `401 Unauthorized` (`"Invalid email or password"`).
- **Session Token**: Generates a signed JWT (`HS256`, 32+ byte HMAC secret) encoding `sub`, `account_id`, `tenant_id`, and expiration timestamp.
- **Response**: HTTP 200 OK:
  ```json
  {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 3600,
    "account_id": "acc_8f2k1x",
    "tenant_id": "acme_corp"
  }
  ```

### 6.4 Profile Endpoint: `GET /v1/accounts/me`

Retrieves public account details for the authenticated user session:
- **Authentication**: Requires a valid session token passed via `Authorization: Bearer <token>` or `X-Session-Token: <token>` (API keys are rejected with `401 Unauthorized`).
- **Privacy Contract**: Returns `company_name`, `tenant_id`, and `public_key` ONLY. Never returns the private key or password information under any circumstances.
- **Response**: HTTP 200 OK:
  ```json
  {
    "company_name": "Acme Corp",
    "tenant_id": "acme_corp",
    "public_key": "pk-acme_corp-xxxxxxxx"
  }
  ```

### 6.5 Key Regeneration Endpoint: `POST /v1/accounts/keys/regenerate`

Invalidates compromised or lost keys and generates a brand-new API key pair:
- **Authentication**: Requires a valid session token (`Authorization: Bearer <token>`).
- **Immediate Invalidation**: All existing API keys associated with the account's `tenant_id` are permanently removed from persistent storage and purged from in-memory authentication caches. Old keys cease functioning immediately across all protected endpoints with `401 Unauthorized`.
- **New Key Generation**: Automatically issues a new `(sk-..., pk-...)` key pair. The new keys become active immediately without service restart.
- **Single-Disclosure Policy**: Returns the new private key strictly once, matching the signup response contract.
- **Response**: HTTP 200 OK:
  ```json
  {
    "account_id": "acc_8f2k1x",
    "tenant_id": "acme_corp",
    "private_key": "sk-acme_corp-newrandomhex",
    "public_key": "pk-acme_corp-newrandomhex",
    "note": "The private key is shown here once and will not be retrievable in plaintext again. Please store it securely.",
    "warning": "The private key is shown here once and will not be retrievable in plaintext again. Please store it securely."
  }
  ```



