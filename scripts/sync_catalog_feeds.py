"""CLI script and scheduled runner for synchronizing product catalog feeds into S3.

Can run as a single-pass execution (--once, suitable for cron jobs) or as a continuous
daemon running on a schedule (e.g., every 4 hours).

Usage:
    # Run once for all tenants with catalog_feed_url:
    python scripts/sync_catalog_feeds.py --once

    # Run once for a specific tenant:
    python scripts/sync_catalog_feeds.py --tenant_id fixture_ecommerce --once

    # Run continuously polling every 4 hours:
    python scripts/sync_catalog_feeds.py --interval-hours 4
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from src.catalog.feed_sync import sync_all_tenant_catalogs, sync_tenant_catalog
from src.scheduler.scheduler import (
    DEFAULT_CATALOG_SYNC_INTERVAL_HOURS,
    BackgroundScheduler,
)
from src.utils.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sync_catalog_feeds_cli")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync tenant product catalog feeds (Google Shopping XML/JSON) into S3."
    )
    parser.add_argument(
        "--tenant_id",
        type=str,
        default=None,
        help="Optional specific tenant_id to sync. If omitted, syncs all tenants with catalog_feed_url.",
    )
    parser.add_argument(
        "--feed-url",
        type=str,
        default=None,
        help="Optional explicit feed URL override (used when --tenant_id is provided).",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["upsert", "replace"],
        default="upsert",
        help="Sync mode: 'upsert' (default) updates matching and keeps untouched, 'replace' overwrites.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run sync once and exit immediately (ideal for cron jobs).",
    )
    parser.add_argument(
        "--interval-hours",
        type=float,
        default=DEFAULT_CATALOG_SYNC_INTERVAL_HOURS,
        help=f"Hours between sync cycles in continuous mode (default: {DEFAULT_CATALOG_SYNC_INTERVAL_HOURS}).",
    )
    args = parser.parse_args()

    config = load_config()

    if args.once:
        if args.tenant_id:
            logger.info("Executing single catalog sync for tenant '%s'...", args.tenant_id)
            res = sync_tenant_catalog(
                tenant_id=args.tenant_id,
                feed_url=args.feed_url,
                mode=args.mode,
                config=config,
            )
            logger.info("Sync result for '%s': %s", args.tenant_id, res)
        else:
            logger.info("Executing single catalog sync for all configured tenants...")
            results = sync_all_tenant_catalogs(config=config, mode=args.mode)
            logger.info("Catalog sync completed for %d tenant(s): %s", len(results), results)
        sys.exit(0)

    # Continuous daemon mode using shared BackgroundScheduler
    interval_seconds = args.interval_hours * 3600.0
    logger.info(
        "Starting catalog sync daemon (interval=%.1f hours / %.0fs)...",
        args.interval_hours,
        interval_seconds,
    )

    scheduler = BackgroundScheduler(check_interval_seconds=30.0)

    def _job_wrapper():
        if args.tenant_id:
            sync_tenant_catalog(
                tenant_id=args.tenant_id,
                feed_url=args.feed_url,
                mode=args.mode,
                config=config,
            )
        else:
            sync_all_tenant_catalogs(config=config, mode=args.mode)

    scheduler.register_job(
        name="catalog_feed_sync",
        fn=_job_wrapper,
        interval_seconds=interval_seconds,
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
            time.sleep(0.5)
    except KeyboardInterrupt:
        _handle_exit(signal.SIGINT, None)


if __name__ == "__main__":
    main()
