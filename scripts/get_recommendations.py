"""CLI for fetching saved-model recommendations for a single customer.

Usage:
    python scripts/get_recommendations.py --tenant_id telco_default \\
        --customer_id 7590-VHVEG --top_n 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Allow running as `python scripts/get_recommendations.py` from the project root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.persistence import load_model  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Get saved-model recommendations for a customer"
    )
    parser.add_argument(
        "--tenant_id",
        default="telco_default",
        help="Tenant ID (default: telco_default)",
    )
    parser.add_argument("--customer_id", required=True, help="Customer ID to score")
    parser.add_argument(
        "--top_n",
        type=int,
        default=5,
        help="Number of products to print",
    )
    parser.add_argument(
        "--model_path",
        default=None,
        help="Optional custom path to the saved model artifact",
    )
    return parser.parse_args()


def resolve_model_path(tenant_id: str, custom_model_path: str | None = None) -> Path:
    if custom_model_path is not None:
        p = Path(custom_model_path)
        if not p.exists():
            raise SystemExit(
                f"No trained model found for tenant '{tenant_id}'. "
                "Run the pipeline for this tenant first."
            )
        return p

    model_path = ROOT / "models" / tenant_id / "final_model.joblib"
    if not model_path.exists() and tenant_id == "telco_default":
        legacy_path = ROOT / "models" / "final_model.joblib"
        if legacy_path.exists():
            model_path = legacy_path

    if not model_path.exists():
        raise SystemExit(
            f"No trained model found for tenant '{tenant_id}'. "
            "Run the pipeline for this tenant first."
        )

    return model_path


def load_tenant_data(tenant_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    cust_path = ROOT / "data" / "processed" / tenant_id / "customers.csv"
    prod_path = ROOT / "data" / "processed" / tenant_id / "products.csv"

    if not cust_path.exists() and tenant_id == "telco_default":
        legacy_cust = ROOT / "data" / "processed" / "customers.csv"
        if legacy_cust.exists():
            cust_path = legacy_cust

    if not prod_path.exists() and tenant_id == "telco_default":
        legacy_prod = ROOT / "data" / "processed" / "products.csv"
        if legacy_prod.exists():
            prod_path = legacy_prod

    if not cust_path.exists() or not prod_path.exists():
        raise SystemExit(
            f"Processed data not found for tenant '{tenant_id}'. "
            "Run the pipeline for this tenant first."
        )

    customers = pd.read_csv(cust_path)
    products = pd.read_csv(prod_path)

    if "customerID" in customers.columns:
        customers = customers.rename(columns={"customerID": "customer_id"})

    return customers, products


def main() -> None:
    args = parse_args()
    model_path = resolve_model_path(args.tenant_id, args.model_path)
    customers, products = load_tenant_data(args.tenant_id)
    model = load_model(str(model_path))

    customer_ids = set(customers["customer_id"].astype(str))
    if str(args.customer_id) not in customer_ids:
        raise SystemExit(
            f"Customer '{args.customer_id}' not found for tenant '{args.tenant_id}'"
        )

    customer_lookup = customers.set_index("customer_id")
    customer_row = (
        customer_lookup.loc[args.customer_id]
        if args.customer_id in customer_lookup.index
        else None
    )

    try:
        recommended_ids = model.recommend(args.customer_id, top_k=args.top_n)
    except TypeError:
        try:
            recommended_ids = model.recommend(
                args.customer_id, customer_row, top_k=args.top_n
            )
        except TypeError:
            recommended_ids = model.recommend(customer_row, top_k=args.top_n)

    if not recommended_ids:
        print(f"No recommendations available for {args.customer_id}")
        return

    product_lookup = products.set_index("product_id")

    print(
        f"Recommendations for tenant '{args.tenant_id}' - customer "
        f"'{args.customer_id}':"
    )
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
