"""CLI script and scheduled runner for tenant training readiness checking (Step 21.2).

Can run as a single-pass execution (--once, suitable for cron jobs) or as a continuous
daemon running on a schedule (e.g., every 1 hour).

Usage:
    # Run once for all untrained tenants:
    python scripts/check_training_readiness.py --once

    # Run once with custom thresholds:
    python scripts/check_training_readiness.py --once --min-customers 10 --min-interactions 50

    # Run continuously checking every hour:
    python scripts/check_training_readiness.py --interval-hours 1.0
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from src.scheduler.readiness_checker import check_untrained_tenants_readiness
from src.scheduler.scheduler import (
    DEFAULT_READINESS_CHECK_INTERVAL_HOURS,
    BackgroundScheduler,
)
from src.utils.config import (
    MIN_CUSTOMERS_TO_TRAIN,
    MIN_INTERACTIONS_TO_TRAIN,
    load_config,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("check_training_readiness_cli")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check untrained tenants against data thresholds and mark ready-to-train."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run readiness check once and exit immediately (ideal for cron jobs).",
    )
    parser.add_argument(
        "--min-customers",
        type=int,
        default=None,
        help=f"Minimum unique customers required to mark ready-to-train (default: {MIN_CUSTOMERS_TO_TRAIN} or config).",
    )
    parser.add_argument(
        "--min-interactions",
        type=int,
        default=None,
        help=f"Minimum interactions required to mark ready-to-train (default: {MIN_INTERACTIONS_TO_TRAIN} or config).",
    )
    parser.add_argument(
        "--interval-hours",
        type=float,
        default=DEFAULT_READINESS_CHECK_INTERVAL_HOURS,
        help=f"Hours between check cycles in continuous mode (default: {DEFAULT_READINESS_CHECK_INTERVAL_HOURS}).",
    )
    args = parser.parse_args()

    config = load_config()

    if args.once:
        logger.info("Executing single training readiness check...")
        results = check_untrained_tenants_readiness(
            config=config,
            min_customers=args.min_customers,
            min_interactions=args.min_interactions,
        )
        logger.info(
            "Readiness check completed: %d checked, %d newly marked ready, %d below threshold",
            len(results["checked"]),
            len(results["marked_ready"]),
            len(results["below_threshold"]),
        )
        print(f"Readiness check completed: {results}")
        sys.exit(0)

    # Continuous daemon mode using BackgroundScheduler
    interval_seconds = args.interval_hours * 3600.0
    logger.info(
        "Starting training readiness checker daemon (interval=%.1f hours / %.0fs)...",
        args.interval_hours,
        interval_seconds,
    )
    scheduler = BackgroundScheduler(check_interval_seconds=min(30.0, interval_seconds / 4))
    scheduler.register_job(
        name="training_readiness_check",
        fn=check_untrained_tenants_readiness,
        interval_seconds=interval_seconds,
        kwargs={
            "config": config,
            "min_customers": args.min_customers,
            "min_interactions": args.min_interactions,
        },
        run_immediately=True,
    )

    def _handle_exit(signum, frame):
        logger.info("Shutdown signal received (%s). Stopping scheduler...", signum)
        scheduler.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)

    scheduler.start()
    try:
        while scheduler.is_alive():
            time.sleep(1.0)
    except KeyboardInterrupt:
        _handle_exit(signal.SIGINT, None)


if __name__ == "__main__":
    main()
