"""CLI script to execute the scheduled model retraining cycle across all tenants.

Replaces manually running the training command per tenant:
1. For newly ready untrained tenants: kicks off their first training run.
2. For already-trained tenants: kicks off a retrain incorporating newly arrived interactions.
3. Skips any tenant with an active or queued training run in progress (collision prevention).
4. Emits a per-tenant summary report.

Usage:
    # Trigger background training runs and exit immediately:
    python scripts/run_scheduled_retrain.py

    # Wait for all background training jobs to complete before exiting:
    python scripts/run_scheduled_retrain.py --wait --timeout 60
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.scheduler.retrain_orchestrator import run_scheduled_retraining  # noqa: E402
from src.utils.config import load_config  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_scheduled_retrain_cli")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run scheduled model retraining cycle across all tenants."
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for all background training threads to complete before exiting.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Maximum seconds to wait if --wait is specified (default: 60.0s).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    logger.info("Executing scheduled retraining cycle (wait=%s, timeout=%.1fs)...", args.wait, args.timeout)

    report = run_scheduled_retraining(
        config=config,
        wait_for_completion=args.wait,
        timeout_seconds=args.timeout,
    )

    print("\n--- Scheduled Retraining Summary Report ---")
    print(f"Timestamp:                 {report['timestamp']}")
    print(f"Total Tenants Checked:     {report['total_tenants_checked']}")
    print(f"First Trainings Triggered: {report['first_trainings_triggered']}")
    print(f"Retrainings Triggered:     {report['retrainings_triggered']}")
    print(f"Skipped (In Progress):     {report['skipped_in_progress']}")
    print(f"Skipped (Other):           {report['skipped_other']}")
    print("\nPer-Tenant Breakdown:")
    for summary in report["summaries"]:
        status_line = (
            f"  - Tenant: {summary['tenant_id']:<20} "
            f"Type: {summary['tenant_type']:<16} "
            f"Action: {summary['action']:<14} "
            f"Status: {summary['status']:<10}"
        )
        if summary.get("reason"):
            status_line += f" Reason: {summary['reason']}"
        print(status_line)
    print("-------------------------------------------\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
