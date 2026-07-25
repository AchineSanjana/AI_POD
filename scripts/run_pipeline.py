"""CLI entry point: loads raw Telco data and produces the reshaped
customers/products/interactions tables in data/processed/.

Usage:
    python scripts/run_pipeline.py
"""

import sys
from pathlib import Path

# Allow running as `python scripts/run_pipeline.py` from the project root
sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.data.reshape_telco import run
from src.utils.logger import get_logger

logger = get_logger(__name__)


def main():
    logger.info("Starting data pipeline...")
    tables = run()

    logger.info("Pipeline complete. Summary:")
    for name, df in tables.items():
        logger.info(f"  {name}: {df.shape[0]:,} rows x {df.shape[1]} columns")


if __name__ == "__main__":
    main()
