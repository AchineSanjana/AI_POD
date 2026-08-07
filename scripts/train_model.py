"""Train and persist the shipped recommendation model for a given tenant.

Usage:
    python scripts/train_model.py --tenant_id telco_default
    python scripts/train_model.py --tenant_id fixture_ecommerce
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as `python scripts/train_model.py` from the project root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# pyrefly: ignore [missing-import]
from src.data.adapters.generic_config_adapter import GenericConfigAdapter
# pyrefly: ignore [missing-import]
from src.models.ranking_model import LearnedRankingRecommender
# pyrefly: ignore [missing-import]
from src.utils.config import get_tenant_config, load_config, resolve_path
# pyrefly: ignore [missing-import]
from src.utils.logger import get_logger
# pyrefly: ignore [missing-import]
from src.utils.persistence import save_model

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train recommendation model for a specific tenant.")
    parser.add_argument(
        "--tenant_id",
        type=str,
        default="telco_default",
        help="Tenant ID to train model for (default: telco_default)",
    )
    args = parser.parse_args()

    config = load_config()
    tenant_cfg = get_tenant_config(config, args.tenant_id)
    adapter = GenericConfigAdapter(tenant_cfg)

    customers, products, interactions = adapter.run()

    final_model = LearnedRankingRecommender(customer_specs=tenant_cfg.customers.features).fit(
        customers,
        interactions,
        products,
    )

    model_dir = resolve_path(Path("models") / args.tenant_id)
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = save_model(final_model, model_dir / "final_model.joblib")
    logger.info(f"Saved trained model for tenant '{args.tenant_id}' to {model_path}")


if __name__ == "__main__":
    main()