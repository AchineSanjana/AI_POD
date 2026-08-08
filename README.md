# AI_POD: Multi-Tenant Recommendation Engine

A generalized, domain-agnostic, multi-tenant recommendation platform that ingests customer activity across disparate industry domains (e.g. Telecommunications, Entertainment, E-Commerce), normalizes them into domain-neutral schema contracts, trains multiple candidate algorithms, autonomously selects the top-performing model, and serves personalized recommendations via a multi-tenant API.

---

## Architecture Overview

```mermaid
flowchart TD
    subgraph Data Layer
        R1[Raw Data: CSV / Parquet] --> A1[DataAdapter]
        A1 --> |GenericConfigAdapter or Custom Subclass| S1[Domain-Neutral DataFrames]
        S1 --> S_C[CustomerSchema]
        S1 --> S_P[ProductSchema]
        S1 --> S_I[InteractionSchema]
    end

    subgraph Model Suite
        S_C & S_P & S_I --> M1[Content-Based Profile Cosine]
        S_I --> M2[Collaborative Filtering SVD]
        M1 & M2 --> M3[Dynamic Hybrid Ensemble]
        S_C & S_P & S_I --> M4[Learned Ranking XGBoost]
    end

    subgraph Evaluation & Selection
        M1 & M2 & M3 & M4 --> E1[Stratified Train/Test Split]
        E1 --> E2[Precision@k / Recall@k / NDCG@k]
        E2 --> W1[Autonomous Model Selection]
        W1 --> P1[Persist models/{tenant_id}/final_model.joblib]
    end

    subgraph Serving Layer
        P1 --> API[FastAPI /recommendations via X-API-Key]
        P1 --> CLI[scripts/get_recommendations.py CLI]
    end
```

### Key Architectural Tenets
1. **Schema Contracts**: All data adapters must emit DataFrames strictly conforming to [`CustomerSchema`](src/core/schema.py), [`ProductSchema`](src/core/schema.py), and [`InteractionSchema`](src/core/schema.py).
2. **Decoupled Feature Specifications**: Recommenders operate on abstract [`FeatureSpec`](src/core/schema.py) metadata contracts rather than hardcoded column semantics.
3. **Multi-Tenant Isolation**: Data is partitioned under `data/processed/{tenant_id}/`, models are saved under `models/{tenant_id}/`, and API requests are routed securely via header keys.

---

## Onboarding a New Company / Tenant

Adding a new tenant requires zero algorithmic code rewrites. There are two supported onboarding paths:

### Path A: Config-Only Onboarding (Recommended)
For standard tabular data (CSV/Parquet), declare a new tenant block in [`config/config.yaml`](config/config.yaml). The [`GenericConfigAdapter`](src/data/adapters/generic_config_adapter.py) reads this configuration directly:

```yaml
tenants:
  retail_demo:
    data_source:
      type: csv
      path: data/raw/retail_transactions.csv
    customers:
      id_column: user_id
      features:
        - name: signup_days
          dtype: numeric
        - name: membership_level
          dtype: categorical
          allowed_values: ["Bronze", "Silver", "Gold"]
          encoding: one_hot
    products:
      derived_from: interaction_source
      category_column: category
    interactions:
      source: custom_services
      service_columns: ["apparel", "electronics", "home_decor"]
      positive_values: ["Purchased", "Yes"]
      negative_values: ["Returned", "No"]
    segmentation:
      field: signup_days
      split: median
```

### Path B: Custom Adapter Onboarding
For non-standard or highly complex multi-table raw data formats, subclass [`DataAdapter`](src/data/base_adapter.py) directly:

```python
from src.data.base_adapter import DataAdapter
import pandas as pd

class CustomStoreAdapter(DataAdapter):
    def to_customers(self) -> pd.DataFrame:
        # Load and transform raw customer attributes
        ...
    def to_products(self) -> pd.DataFrame:
        # Load and transform raw catalog items
        ...
    def to_interactions(self) -> pd.DataFrame:
        # Return long-format interactions: customer_id, product_id, weight
        ...
```

---

## Running for a Specific Tenant

All execution and evaluation scripts accept a `--tenant_id` flag (defaulting to `telco_default`):

### 1. Ingest, Train, and Select Winning Model
```bash
# Run end-to-end pipeline for a specific tenant
python scripts/run_pipeline.py --tenant_id movielens_demo

# Train models specifically for a tenant
python scripts/train_model.py --tenant_id movielens_demo
```

### 2. Generate Recommendations via CLI
```bash
# Retrieve top-5 recommendations for a customer under a specific tenant
python scripts/get_recommendations.py --tenant_id movielens_demo --customer_id 1 --top_n 5
```

### 3. Generate Offline Evaluation Reports
```bash
# Generate per-tenant evaluation report and multi-tenant generalization proof
python scripts/generate_evaluation_results.py --tenant_id movielens_demo
```

---

## Multi-Tenant API Serving

Start the FastAPI serving service:

```bash
uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload
```

### Recommendation Request (X-API-Key Authentication)
API keys in `config/config.yaml` route requests automatically to their tenant's trained model with complete catalog isolation:

```bash
# Telco Tenant Query
curl -H "X-API-Key: sk-telco-xxxx" \
     "http://localhost:8000/recommendations?customer_id=7590-VHVEG&top_n=5"

# MovieLens Tenant Query
curl -H "X-API-Key: sk-movielens-xxxx" \
     "http://localhost:8000/recommendations?customer_id=1&top_n=5"
```

---

## Example Tenant: Telco

The telecommunications churn dataset is provided as a default benchmark tenant.

### 1. Clone & Set Up Virtual Environment

```bash
# Clone the repository and navigate to root
cd AI_POD

# Create and activate virtual environment
python -m venv venv

# Mac/Linux:
source venv/bin/activate

# Windows (PowerShell):
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Download Telco Dataset
Download the Telco Customer Churn dataset from Kaggle:
https://www.kaggle.com/datasets/mosapabdelghany/telcom-customer-churn-dataset

Place the CSV at:
```text
data/raw/telco_customer_churn.csv
```

### 3. Run Pipeline & Tests
```bash
# Run Telco pipeline
python scripts/run_pipeline.py --tenant_id telco_default

# Run test suite
pytest tests/ -v
```

### 4. Get Telco Recommendations
```bash
python scripts/get_recommendations.py --tenant_id telco_default --customer_id 7590-VHVEG --top_n 5
```

You can also override the model artifact path if needed:
```bash
python scripts/get_recommendations.py --customer_id 7590-VHVEG --model_path models/telco_default/final_model.joblib
```

### 5. Review Telco Evaluation Results
Open [docs/evaluation_results_telco_default.md](docs/evaluation_results_telco_default.md) (and its backward-compatible alias [docs/evaluation_results.md](docs/evaluation_results.md)) as well as [docs/generalization_proof.md](docs/generalization_proof.md).

---

## Generalization Proof & Evaluation Artifacts

* **Multi-Tenant Comparison Report**: [docs/generalization_proof.md](docs/generalization_proof.md)
* **Telco Default Report**: [docs/evaluation_results_telco_default.md](docs/evaluation_results_telco_default.md)
* **MovieLens Demo Report**: [docs/evaluation_results_movielens_demo.md](docs/evaluation_results_movielens_demo.md)
* **Exploration Notebook**: [notebooks/01_data_exploration.ipynb](notebooks/01_data_exploration.ipynb)

---

## Troubleshooting

| Problem | Likely fix |
| --- | --- |
| `ModuleNotFoundError` when running scripts | Activate the virtual environment (`venv/bin/activate` or `venv\Scripts\activate`) and verify `PYTHONPATH`. |
| `FileNotFoundError` on raw CSV | Place the raw data file at the configured `data_source.path` declared in `config/config.yaml`. |
| `HTTPException 401: Invalid or missing X-API-Key` | Provide the corresponding API key header (e.g. `X-API-Key: sk-telco-xxxx`) mapped in `config/config.yaml`. |
| `HTTPException 404: Customer not found` | Confirm the `customer_id` exists in `data/processed/{tenant_id}/customers.csv`. |
| `pytest` failure on missing directory | Run `python scripts/run_pipeline.py --tenant_id <tenant_id>` to generate processed tables and models. |
