# AI_POD

SLT recommendation engine.

## Roadmap

- [x] Build a reproducible preprocessing pipeline for the Telco dataset
- [x] Implement content-based, collaborative-filtering, hybrid, and learned ranking recommenders
- [x] Add offline evaluation metrics for precision, recall, and NDCG
- [x] Generate evaluation results and document the final winners
- [x] Provide a CLI for retrieving saved recommendations

## Model Choice

The shipped primary recommender is the learned ranking model in [src/models/ranking_model.py](src/models/ranking_model.py). The content-based, collaborative-filtering, and hybrid models remain in the codebase as baselines and fallbacks for comparison and debugging.

## Setup

Follow these steps in order — each one builds on the last.

### 1. Clone/open the project

Open the AI_POD folder in VS Code.

### 2. Open a terminal in VS Code

Use Terminal → New Terminal (or Ctrl+` / Cmd+`).

### 3. Create a virtual environment

```bash
python -m venv venv
```

### 4. Activate the virtual environment

- Mac/Linux:

```bash
source venv/bin/activate
```

- Windows (PowerShell):

```powershell
venv\Scripts\activate
```

### 5. Point VS Code at the virtual environment

Press Ctrl+Shift+P (Cmd+Shift+P on Mac) → type Python: Select Interpreter → choose the venv interpreter for this workspace.

### 6. Install dependencies

```bash
pip install -r requirements.txt
```

### 7. Get the dataset

Download the Telco Customer Churn dataset from Kaggle:
https://www.kaggle.com/datasets/mosapabdelghany/telcom-customer-churn-dataset

Place the CSV at:

```text
data/raw/telco_customer_churn.csv
```

### 8. Run the pipeline

```bash
python scripts/run_pipeline.py
```

This writes the processed customers, products, and interactions tables under the data/processed folder.

### 9. Run the tests

```bash
python -m pytest tests/ -v
```

### 10. Get recommendations

Use the CLI script to print recommendations for a specific customer from the saved model:

```bash
python scripts/get_recommendations.py --customer_id 7590-VHVEG --top_n 5
```

You can also override the model artifact path if needed:

```bash
python scripts/get_recommendations.py --customer_id 7590-VHVEG --model_path models/final_model.joblib
```

### 11. Review the evaluation results

Open [docs/evaluation_results.md](docs/evaluation_results.md) and the exploration notebook at [notebooks/01_data_exploration.ipynb](notebooks/01_data_exploration.ipynb) for the offline analysis and example outputs.

## Final Results

The final offline evaluation shows that the learned ranking model is the strongest overall recommender:

- Precision@5: 0.293
- Recall@5: 0.880
- NDCG@5: 0.751

The hybrid model was the next strongest overall baseline, while collaborative filtering performed best for established customers with richer history. The ranking model also led the newer-customer segment with an NDCG@5 of 0.784.

## How to get recommendations

The repository includes a simple CLI for generating saved-model recommendations for one customer at a time:

```bash
python scripts/get_recommendations.py --customer_id <customer_id> --top_n 5
```

The script reads the processed customer and product tables, loads the saved model artifact, and prints the ranked product IDs alongside their product names and categories.

## Troubleshooting

| Problem                                       | Likely fix                                                                         |
| --------------------------------------------- | ---------------------------------------------------------------------------------- |
| ModuleNotFoundError when running scripts      | Activate the virtual environment and ensure VS Code is using the same interpreter. |
| FileNotFoundError on telco_customer_churn.csv | Place the CSV at data/raw/telco_customer_churn.csv before running the pipeline.    |
| Notebook kernel does not show the venv        | Restart VS Code or select the notebook kernel manually.                            |
| pip install fails on Windows                  | Make sure the terminal is running inside the activated venv.                       |
