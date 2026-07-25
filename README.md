# AI_POD
SLT recommendation engine

## Setup

Follow these steps in order — each one builds on the last.

### 1. Clone/open the project
Open the `telecom-recommendation-engine` folder in VS Code.

### 2. Open a terminal in VS Code
`Terminal` → `New Terminal` (or `` Ctrl+` `` / `` Cmd+` ``).

### 3. Create a virtual environment
```bash
python -m venv venv
```
This creates an isolated Python environment just for this project, so its
packages don't clash with anything else on your machine.

### 4. Activate the virtual environment
- **Mac/Linux:**
```bash
  source venv/bin/activate
```
- **Windows (PowerShell):**
```powershell
  venv\Scripts\activate
```
You'll know it worked when your terminal prompt shows `(venv)` at the start.

### 5. Point VS Code at the virtual environment
Press `Ctrl+Shift+P` (`Cmd+Shift+P` on Mac) → type **"Python: Select
Interpreter"** → choose the one listed as:
venv (3.11.x) .\venv\Scripts\python.exe Workspace

Don't pick a `base`/`Conda`/`Global` interpreter — those are system-wide and
won't match the packages you're about to install.

### 6. Install dependencies
```bash
pip install -r requirements.txt
```

### 7. Set up environment variables
```bash
cp .env.example .env        # Windows: copy .env.example .env
```
Leave everything blank for now — those variables are only needed once the
company API / agent integrations (in `src/integrations/`) are switched on.

### 8. Get the dataset
Download the Telco Customer Churn dataset from Kaggle:
https://www.kaggle.com/datasets/mosapabdelghany/telcom-customer-churn-dataset

Place the CSV at:
data/raw/telco_customer_churn.csv

### 9. Run the pipeline
```bash
python scripts/run_pipeline.py
```
Success looks like:
Pipeline complete. Summary:
customers: 7,043 rows x 12 columns
products: 10 rows x 3 columns
interactions: ... rows x 2 columns

### 10. Run the tests
```bash
python -m pytest tests/ -v
```
All 6 tests should pass.

### 11. Open the exploration notebook
Open `notebooks/01_data_exploration.ipynb` in VS Code. When prompted to
select a kernel, choose the same `venv` interpreter from step 5. Run the
cells top to bottom.

---

### Troubleshooting

| Problem | Likely fix |
|---|---|
| `ModuleNotFoundError` when running scripts | Your virtual environment isn't activated, or VS Code is using the wrong interpreter — redo steps 4–5. |
| `FileNotFoundError` on `telco_customer_churn.csv` | The CSV isn't at `data/raw/telco_customer_churn.csv` — check step 8. |
| Notebook kernel doesn't show `venv` | Restart VS Code after creating the virtual environment, or manually select the kernel via the notebook's top-right kernel picker. |
| `pip install` fails on Windows | Make sure you're inside `(venv)` in the terminal prompt before running it. |

