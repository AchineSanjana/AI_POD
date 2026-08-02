# AI_POD — Project Overview

This document provides a comprehensive, technical overview of the AI_POD codebase, describing architecture, data, model selection, pipeline/engine flow, backend and frontend components, scripts, testing, and developer notes. Use this as a single-stop reference to understand how the project works, where key artifacts live, and how to run or extend the system.

**Project at a glance**

- **Name**: AI_POD
- **Purpose**: A recommendation/modeling project with data pipelines, multiple modeling strategies (collaborative, content-based, hybrid, ranking), evaluation, and a small API for serving recommendations.
- **Top-level layout**:
  - `data/` — raw and processed data inputs and artifacts.
  - `src/` — core libraries: data loaders, evaluation, integrations, models, utilities.
  - `models/` — trained/persisted model artifacts (e.g., `final_model.joblib`).
  - `my-api-app/` — small app exposing an API and minimal UI for recommendations.
  - `scripts/` — convenience scripts to run pipeline, training, evaluation and retrieval.
  - `docs/` — documentation (this file and others).

See these files/folders in the repository for quick navigation: [src](src), [data](data), [models](models), [my-api-app](my-api-app), [scripts](scripts), [tests](tests).

**Important files**

- Project metadata: [pyproject.toml](pyproject.toml) and [requirements.txt](requirements.txt)
- Config: [config/config.yaml](config/config.yaml) and `src/utils/config.py` ([src/utils/config.py](src/utils/config.py))
- Core pipeline entrypoints: `scripts/run_pipeline.py`, `scripts/train_model.py`, `scripts/get_recommendations.py`
- API server: [my-api-app/app/main.py](my-api-app/app/main.py)
- API endpoints: [my-api-app/app/api/recommendations.py](my-api-app/app/api/recommendations.py)
- Models implementations: [src/models/collaborative_filtering.py](src/models/collaborative_filtering.py), [src/models/content_based.py](src/models/content_based.py), [src/models/hybrid.py](src/models/hybrid.py), [src/models/ranking_model.py](src/models/ranking_model.py)
- Evaluation utilities: [src/evaluation/metrics.py](src/evaluation/metrics.py) and [src/evaluation/split.py](src/evaluation/split.py)
- Utilities: logging and persistence in [src/utils/logger.py](src/utils/logger.py) and [src/utils/persistence.py](src/utils/persistence.py)

## Architecture & High-level Flow

The system is divided into three logical layers:

1. Data & preprocessing
   - Raw data is stored in `data/raw/` (e.g. `data/raw/telco_customer_churn.csv`).
   - Processed artifacts (cleaned tables, feature sets, lookups) go to `data/processed/` and `my-api-app/data/processed/` for API inputs.
   - Data loading and reshaping helpers live in `src/data/` (e.g. `load_telco.py`, `reshape_telco.py`, `dummyjson_pipeline.py`).

2. Modeling & evaluation
   - Multiple model strategies are implemented under `src/models`.
   - Training and evaluation are orchestrated by scripts in `scripts/` and helper functions in `src/evaluation`.
   - Model artifacts are persisted to `models/` (eg `models/final_model.joblib`) via `src/utils/persistence.py`.

3. Serving & integrations
   - A minimal API lives in `my-api-app` exposing recommendation endpoints.
   - CLI scripts and small UI components (in `my-api-app/app/ui.py`) support manual testing and quick demoing.
   - Integrations (external APIs, agents) are under `src/integrations`.

## Engine / Pipeline Flow (detailed)

The canonical flow is implemented by `scripts/run_pipeline.py` and related scripts. Steps:

1. Configuration
   - Load app/project config from [config/config.yaml](config/config.yaml) via `src/utils/config.py`.

2. Ingest
   - Read raw CSV/JSON from `data/raw/` using `src/data/load_telco.py` or dataset-specific loaders.

3. Validate & Clean
   - Basic validation, type casting, missing-value handling, and schema conformance are applied.

4. Reshape & Feature Engineering
   - `src/data/reshape_telco.py` and other pipeline modules transform records into model-ready tables.

5. Split / Sampling
   - Use `src/evaluation/split.py` to create train/validation/test folds (time-aware or stratified as required).

6. Model Training
   - Train multiple candidate models (see Models section). The training script saves intermediate artifacts (vectorizers, encoders) and model binaries using `src/utils/persistence.py`.

7. Evaluation & Selection
   - Metrics are calculated in `src/evaluation/metrics.py` using evaluation folds. Common metrics include precision@k, recall@k, NDCG, RMSE (if rating prediction), AUC, and business KPIs where applicable.
   - Candidate models are compared on the hold-out set and on offline simulated business metrics; the best model(s) are selected based on a weighted objective (accuracy metrics + business constraints).

8. Persist Best Model
   - Final model and required processors are saved to `models/` for serving.

9. Deploy to API
   - The API reads persisted artifacts into memory at startup and exposes endpoints to request recommendations.

## Models & Model Selection

Implementations live in `src/models/` and include:

- Collaborative filtering: neighborhood-based or matrix-factorization-style implementations for user-item interactions.
- Content-based: item feature encoders (TF-IDF, embeddings) and cosine/similarity ranking.
- Hybrid: combines collaborative and content signals, often via weighted blending or stacked models.
- Ranking model: a learn-to-rank model trained to reorder candidate items using features from both CF and content models.

Selection process summary:

- Stage 1: Candidate generation — run different algorithms to create candidate lists for users.
- Stage 2: Offline ranking and scoring — compute evaluation metrics on validation/test sets.
- Stage 3: Business validation — sanity checks (e.g., diversity, popularity bias) and domain-specific constraints.
- Stage 4: Final decision — choose the model with best expected online performance. Optionally produce an ensemble (e.g., weighted blend of hybrid + ranking model).

Key evaluation code: [src/evaluation/metrics.py](src/evaluation/metrics.py) and tests in [tests](tests) (e.g., `test_content_based.py`, `test_metrics.py`). Use `pytest` to run the suite.

## Backend (API) details

- App entrypoint: [my-api-app/app/main.py](my-api-app/app/main.py)
- API routes: [my-api-app/app/api/recommendations.py](my-api-app/app/api/recommendations.py)
- Data for API: `my-api-app/data/processed/recommendations.json` is used for seeding or fallback responses.
- Behavior: on startup the service loads models from `models/` (via persistence utilities), warms caches, and serves requests via HTTP. The endpoint accepts user identifiers and returns top-K recommendations formatted as JSON.

## Frontend / UI details

- Minimal UI components exist in `my-api-app/app/ui.py` for demoing or manual queries.
- The UI is lightweight (server-side rendered or small local script) and primarily intended to exercise the API during development.

## Scripts and automation

Key scripts:

- `scripts/run_pipeline.py` — orchestrates the end-to-end pipeline (ingest -> preprocess -> train -> evaluate -> persist).
- `scripts/train_model.py` — focused training script for a single model or experiment.
- `scripts/get_recommendations.py` — sample client/CLI to call the API or the local persisted model to fetch recommendations.
- `scripts/generate_evaluation_results.py` — aggregate evaluation artifacts and produce markdown/CSV reports for documentation.
- `my-api-app/scripts/generate_synthetic_data.py` — helper to create demo/test data for the API.

## Tests

- Unit tests are in the `tests/` top-level folder and `my-api-app/tests/` or similar. Run with `pytest` from the repo root.
- Tests cover models, evaluation metrics, and split logic. Add tests for new models and edge-case behaviors.

## Persistence & artifacts

- Trained model artifacts: stored in `models/` (e.g., `models/final_model.joblib`).
- Processed datasets: `data/processed/` and `my-api-app/data/processed/` for API-friendly artifacts.
- Config and secrets: use `config/config.yaml`; avoid checking secrets into source control.

## Integration & extensibility

- New models: implement new classes under `src/models/` following the signature and persistence conventions used by existing modules.
- Feature stores: add more processors under `src/data/` and register them in the pipeline scripts.
- Online A/B testing: the API is easily wrapped by a gateway that routes a fraction of traffic to alternative models for online testing.

## Developer notes & conventions

- Python packaging: repo uses `pyproject.toml` and `requirements.txt` for dependencies. Use a virtual environment.
- Logging: use `src/utils/logger.py` for consistent log formatting.
- Persistence: use `src/utils/persistence.py` to save/load models and processors to ensure reproducibility.
- Config-driven: scripts read `config/config.yaml`. Favor config flags over hard-coded paths.

## How to run locally (recommended quickstart)

1. Create and activate a virtualenv (recommended):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Run pipeline (ingest -> train -> persist):

```powershell
python scripts/run_pipeline.py
```

3. Run API server (loads persisted model):

```powershell
python my-api-app/app/main.py
```

4. Try sample recommendation client:

```powershell
python scripts/get_recommendations.py --user-id 123
```

5. Run tests:

```powershell
pytest -q
```

## Notes and caveats

- Exact behavior of training scripts and the server depends on configuration in `config/config.yaml` and environment variables.
- If model training is expensive, enable sampling or smaller datasets in config for local development.
- Check `my-api-app/requirements.txt` if the API needs a different dependency set than the main project.

## Appendix: Where to look next

- Data ingestion: [src/data/load_telco.py](src/data/load_telco.py)
- Feature transformations: [src/data/reshape_telco.py](src/data/reshape_telco.py)
- Modeling: [src/models/](src/models)
- Evaluation: [src/evaluation/metrics.py](src/evaluation/metrics.py)
- API: [my-api-app/app/api/recommendations.py](my-api-app/app/api/recommendations.py)

If you want, I can also:

- generate a one-page diagram of the pipeline flow,
- add runnable examples for training a single model with a small sample dataset,
- or create a checklist for productionizing the model (CI/CD, monitoring, retraining schedule).

---

Last updated: autogenerated by assistant.

# AI_POD — Project Overview

This document provides a comprehensive, technical overview of the AI_POD codebase, describing architecture, data, model selection, pipeline/engine flow, backend and frontend components, scripts, testing, and developer notes. Use this as a single-stop reference to understand how the project works, where key artifacts live, and how to run or extend the system.

**Project at a glance**

- **Name**: AI_POD
- **Purpose**: A recommendation/modeling project with data pipelines, multiple modeling strategies (collaborative, content-based, hybrid, ranking), evaluation, and a small API for serving recommendations.
- **Top-level layout**:
  - `data/` — raw and processed data inputs and artifacts.
  - `src/` — core libraries: data loaders, evaluation, integrations, models, utilities.
  - `models/` — trained/persisted model artifacts (e.g., `final_model.joblib`).
  - `my-api-app/` — small app exposing an API and minimal UI for recommendations.
  - `scripts/` — convenience scripts to run pipeline, training, evaluation and retrieval.
  - `docs/` — documentation (this file and others).

See these files/folders in the repository for quick navigation: [src](src), [data](data), [models](models), [my-api-app](my-api-app), [scripts](scripts), [tests](tests).

**Important files**

- Project metadata: [pyproject.toml](pyproject.toml) and [requirements.txt](requirements.txt)
- Config: [config/config.yaml](config/config.yaml) and `src/utils/config.py` ([src/utils/config.py](src/utils/config.py))
- Core pipeline entrypoints: `scripts/run_pipeline.py`, `scripts/train_model.py`, `scripts/get_recommendations.py`
- API server: [my-api-app/app/main.py](my-api-app/app/main.py)
- API endpoints: [my-api-app/app/api/recommendations.py](my-api-app/app/api/recommendations.py)
- Models implementations: [src/models/collaborative_filtering.py](src/models/collaborative_filtering.py), [src/models/content_based.py](src/models/content_based.py), [src/models/hybrid.py](src/models/hybrid.py), [src/models/ranking_model.py](src/models/ranking_model.py)
- Evaluation utilities: [src/evaluation/metrics.py](src/evaluation/metrics.py), [src/evaluation/split.py](src/evaluation/split.py)
- Utilities: logging and persistence in [src/utils/logger.py](src/utils/logger.py) and [src/utils/persistence.py](src/utils/persistence.py)

## Architecture & High-level Flow

The system is divided into three logical layers:

1. Data & preprocessing
   - Raw data is stored in `data/raw/` (e.g. `data/raw/telco_customer_churn.csv`).
   - Processed artifacts (cleaned tables, feature sets, lookups) go to `data/processed/` and `my-api-app/data/processed/` for API inputs.
   - Data loading and reshaping helpers live in `src/data/` (e.g. `load_telco.py`, `reshape_telco.py`, `dummyjson_pipeline.py`).

2. Modeling & evaluation
   - Multiple model strategies are implemented under `src/models`.
   - Training and evaluation are orchestrated by scripts in `scripts/` and helper functions in `src/evaluation`.
   - Model artifacts are persisted to `models/` (eg `models/final_model.joblib`) via `src/utils/persistence.py`.

3. Serving & integrations
   - A minimal API lives in `my-api-app` exposing recommendation endpoints.
   - CLI scripts and small UI components (in `my-api-app/app/ui.py`) support manual testing and quick demoing.
   - Integrations (external APIs, agents) are under `src/integrations`.

## Engine / Pipeline Flow (detailed)

The canonical flow is implemented by `scripts/run_pipeline.py` and related scripts. Steps:

1. Configuration
   - Load app/project config from [config/config.yaml](config/config.yaml) via `src/utils/config.py`.

2. Ingest
   - Read raw CSV/JSON from `data/raw/` using `src/data/load_telco.py` or dataset-specific loaders.

3. Validate & Clean
   - Basic validation, type casting, missing-value handling, and schema conformance are applied.

4. Reshape & Feature Engineering
   - `src/data/reshape_telco.py` and other pipeline modules transform records into model-ready tables.

5. Split / Sampling
   - Use `src/evaluation/split.py` to create train/validation/test folds (time-aware or stratified as required).

6. Model Training
   - Train multiple candidate models (see Models section). The training script saves intermediate artifacts (vectorizers, encoders) and model binaries using `src/utils/persistence.py`.

7. Evaluation & Selection
   - Metrics are calculated in `src/evaluation/metrics.py` using evaluation folds. Common metrics include precision@k, recall@k, NDCG, RMSE (if rating prediction), AUC, and business KPIs where applicable.
   - Candidate models are compared on the hold-out set and on offline simulated business metrics; the best model(s) are selected based on a weighted objective (accuracy metrics + business constraints).

8. Persist Best Model
   - Final model and required processors are saved to `models/` for serving.

9. Deploy to API
   - The API reads persisted artifacts into memory at startup and exposes endpoints to request recommendations.

## Models & Model Selection

Implementations live in `src/models/` and include:

- Collaborative filtering: neighborhood-based or matrix-factorization-style implementations for user-item interactions.
- Content-based: item feature encoders (TF-IDF, embeddings) and cosine/similarity ranking.
- Hybrid: combines collaborative and content signals, often via weighted blending or stacked models.
- Ranking model: a learn-to-rank model trained to reorder candidate items using features from both CF and content models.

Selection process summary:

- Stage 1: Candidate generation — run different algorithms to create candidate lists for users.
- Stage 2: Offline ranking and scoring — compute evaluation metrics on validation/test sets.
- Stage 3: Business validation — sanity checks (e.g., diversity, popularity bias) and domain-specific constraints.
- Stage 4: Final decision — choose the model with best expected online performance. Optionally produce an ensemble (e.g., weighted blend of hybrid + ranking model).

Key evaluation code: [src/evaluation/metrics.py](src/evaluation/metrics.py) and tests in [tests](tests) (e.g., `test_content_based.py`, `test_metrics.py`). Use `pytest` to run the suite.

## Backend (API) details

- App entrypoint: [my-api-app/app/main.py](my-api-app/app/main.py)
- API routes: [my-api-app/app/api/recommendations.py](my-api-app/app/api/recommendations.py)
- Data for API: `my-api-app/data/processed/recommendations.json` is used for seeding or fallback responses.
- Behavior: on startup the service loads models from `models/` (via persistence utilities), warms caches, and serves requests via HTTP. The endpoint accepts user identifiers and returns top-K recommendations formatted as JSON.

## Frontend / UI details

- Minimal UI components exist in `my-api-app/app/ui.py` for demoing or manual queries.
- The UI is lightweight (server-side rendered or small local script) and primarily intended to exercise the API during development.

## Scripts and automation

Key scripts:

- `scripts/run_pipeline.py` — orchestrates the end-to-end pipeline (ingest -> preprocess -> train -> evaluate -> persist).
- `scripts/train_model.py` — focused training script for a single model or experiment.
- `scripts/get_recommendations.py` — sample client/CLI to call the API or the local persisted model to fetch recommendations.
- `scripts/generate_evaluation_results.py` — aggregate evaluation artifacts and produce markdown/CSV reports for documentation.
- `my-api-app/scripts/generate_synthetic_data.py` — helper to create demo/test data for the API.

## Tests

- Unit tests are in the `tests/` top-level folder and `my-api-app/tests/` or similar. Run with `pytest` from the repo root.
- Tests cover models, evaluation metrics, and split logic. Add tests for new models and edge-case behaviors.

## Persistence & artifacts

- Trained model artifacts: stored in `models/` (e.g., `models/final_model.joblib`).
- Processed datasets: `data/processed/` and `my-api-app/data/processed/` for API-friendly artifacts.
- Config and secrets: use `config/config.yaml`; avoid checking secrets into source control.

## Integration & extensibility

- New models: implement new classes under `src/models/` following the signature and persistence conventions used by existing modules.
- Feature stores: add more processors under `src/data/` and register them in the pipeline scripts.
- Online A/B testing: the API is easily wrapped by a gateway that routes a fraction of traffic to alternative models for online testing.

## Developer notes & conventions

- Python packaging: repo uses `pyproject.toml` and `requirements.txt` for dependencies. Use a virtual environment.
- Logging: use `src/utils/logger.py` for consistent log formatting.
- Persistence: use `src/utils/persistence.py` to save/load models and processors to ensure reproducibility.
- Config-driven: scripts read `config/config.yaml`. Favor config flags over hard-coded paths.

## How to run locally (recommended quickstart)

1. Create and activate a virtualenv (recommended):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Run pipeline (ingest -> train -> persist):

```powershell
python scripts/run_pipeline.py
```

3. Run API server (loads persisted model):

```powershell
python my-api-app/app/main.py
```

4. Try sample recommendation client:

```powershell
python scripts/get_recommendations.py --user-id 123
```

5. Run tests:

```powershell
pytest -q
```

## Notes and caveats

- Exact behavior of training scripts and the server depends on configuration in `config/config.yaml` and environment variables.
- If model training is expensive, enable sampling or smaller datasets in config for local development.
- Check `my-api-app/requirements.txt` if the API needs a different dependency set than the main project.

## Appendix: Where to look next

- Data ingestion: [src/data/load_telco.py](src/data/load_telco.py)
- Feature transformations: [src/data/reshape_telco.py](src/data/reshape_telco.py)
- Modeling: [src/models/](src/models)
- Evaluation: [src/evaluation/metrics.py](src/evaluation/metrics.py)
- API: [my-api-app/app/api/recommendations.py](my-api-app/app/api/recommendations.py)

If you want, I can also:

- generate a one-page diagram of the pipeline flow,
- add runnable examples for training a single model with a small sample dataset,
- or create a checklist for productionizing the model (CI/CD, monitoring, retraining schedule).

---

Last updated: autogenerated by assistant.
