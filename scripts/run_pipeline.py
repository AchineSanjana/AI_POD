"""CLI entry point: loads raw data for a given tenant, builds recommendation tables,
trains & evaluates all models, and saves the winning model artifact.

Usage:
    python scripts/run_pipeline.py --tenant_id telco_default
    python scripts/run_pipeline.py --tenant_id fixture_ecommerce
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow running as `python scripts/run_pipeline.py` from the project root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline.run import run_tenant_pipeline
from src.storage import get_storage_backend
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Recommendation Pipeline for a specific tenant."
    )
    parser.add_argument(
        "--tenant_id",
        type=str,
        default=os.environ.get("TENANT_ID", "telco_default"),
        help="Tenant ID to run pipeline for (default: $TENANT_ID or telco_default)",
    )
    args = parser.parse_args()

    config = load_config()
    storage = get_storage_backend(config)
    run_tenant_pipeline(args.tenant_id, storage=storage, config=config)


if __name__ == "__main__":
    main()
