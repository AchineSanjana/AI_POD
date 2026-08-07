"""CLI entry point: loads raw Telco data and produces the reshaped
customers/products/interactions tables in data/processed/.

Usage:
    python scripts/run_pipeline.py
"""

import sys
from pathlib import Path

# Allow running as `python scripts/run_pipeline.py` from the project root
sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.data.adapters.telco_adapter import TelcoAdapter
from src.utils.config import (
    build_customer_schema_from_config,
    build_product_schema_from_config,
    load_config,
    resolve_path,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


def main():
    config = load_config()

    adapter = TelcoAdapter(
        config=config,
        customer_schema=build_customer_schema_from_config(config),
        product_schema=build_product_schema_from_config(config),
    )

    logger.info("Starting data pipeline...")
    customers, products, interactions = adapter.run()

    # Persist to data/processed/ — same paths reshape_telco.run() used.
    out_dir = resolve_path(config["paths"]["processed_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    customers.to_csv(out_dir / config["paths"]["customers_out"], index=False)
    products.to_csv(out_dir / config["paths"]["products_out"], index=False)
    interactions.to_csv(out_dir / config["paths"]["interactions_out"], index=False)

    logger.info(f"Wrote customers/products/interactions tables to {out_dir}")

    logger.info("Pipeline complete. Summary:")
    for name, df in [("customers", customers), ("products", products), ("interactions", interactions)]:
        logger.info(f"  {name}: {df.shape[0]:,} rows x {df.shape[1]} columns")


if __name__ == "__main__":
    main()
