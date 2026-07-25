"""SANDBOX ONLY -- not part of the main recommendation pipeline.

Pulls product data from the free DummyJSON API purely to practice the
API-calling pattern (pagination, error handling, JSON -> DataFrame) that
will later point at the real company site API. DummyJSON's catalog is
generic e-commerce data, not telecom data, so its output is never joined
with the Telco customer/product tables.

Usage:
    python -m src.data.dummyjson_pipeline
"""

import os

import pandas as pd
import requests
from dotenv import load_dotenv

from src.utils.config import load_config, resolve_path
from src.utils.logger import get_logger

load_dotenv()
logger = get_logger(__name__)

DEFAULT_BASE_URL = os.getenv("DUMMYJSON_BASE_URL", "https://dummyjson.com")


def fetch_all_products(base_url: str = DEFAULT_BASE_URL, page_size: int = 30) -> pd.DataFrame:
    """Paginate through the DummyJSON /products endpoint and return a DataFrame."""
    all_products = []
    skip = 0

    while True:
        url = f"{base_url}/products"
        params = {"limit": page_size, "skip": skip}

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Request to DummyJSON failed: {e}")
            raise

        payload = response.json()
        batch = payload.get("products", [])
        all_products.extend(batch)

        logger.info(f"Fetched {len(batch)} products (skip={skip})")

        skip += page_size
        if skip >= payload.get("total", 0) or not batch:
            break

    df = pd.DataFrame(all_products)
    logger.info(f"Total products fetched: {len(df)}")
    return df


def save_sandbox_pull(df: pd.DataFrame, config: dict | None = None) -> None:
    config = config or load_config()
    out_dir = resolve_path(config["paths"]["external_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "dummyjson_products.json"
    df.to_json(out_path, orient="records", indent=2)
    logger.info(f"Saved sandbox pull to {out_path}")


if __name__ == "__main__":
    products_df = fetch_all_products()
    save_sandbox_pull(products_df)
    print(products_df.head())
