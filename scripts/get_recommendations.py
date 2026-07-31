"""CLI for fetching saved-model recommendations for a single customer.

Usage:
    python scripts/get_recommendations.py --customer_id 7590-VHVEG --top_n 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Allow running as `python scripts/get_recommendations.py` from the project root.
sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.utils.persistence import load_model


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "final_model.joblib"
CUSTOMERS_PATH = ROOT / "data" / "processed" / "customers.csv"
PRODUCTS_PATH = ROOT / "data" / "processed" / "products.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Get saved-model recommendations for a customer")
    parser.add_argument("--customer_id", required=True, help="Customer ID to score")
    parser.add_argument("--top_n", type=int, default=5, help="Number of products to print")
    parser.add_argument(
        "--model_path",
        default=str(MODEL_PATH),
        help="Path to the saved model artifact",
    )
    return parser.parse_args()


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    customers = pd.read_csv(CUSTOMERS_PATH)
    products = pd.read_csv(PRODUCTS_PATH)

    if "customerID" in customers.columns:
        customers = customers.rename(columns={"customerID": "customer_id"})

    return customers, products


def main() -> None:
    args = parse_args()
    customers, products = load_inputs()
    model = load_model(args.model_path)

    if args.customer_id not in set(customers["customer_id"]):
        raise SystemExit(f"Unknown customer_id: {args.customer_id}")

    recommended_ids = model.recommend(args.customer_id, top_k=args.top_n)

    if not recommended_ids:
        print(f"No recommendations available for {args.customer_id}")
        return

    product_lookup = products.set_index("product_id")

    print(f"Recommendations for {args.customer_id}")
    for rank, product_id in enumerate(recommended_ids, start=1):
        if product_id in product_lookup.index:
            product = product_lookup.loc[product_id]
            product_name = product["product_name"]
            category = product.get("category", "")
            print(f"{rank}. {product_name} ({product_id}) [{category}]")
        else:
            print(f"{rank}. {product_id}")


if __name__ == "__main__":
    main()
