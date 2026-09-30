"""CLI script to run the SQS tracking events background worker.

Can run either as a continuous daemon worker polling SQS or as a single-pass
batch execution (suitable for cron schedules or scheduled tasks).

Usage:
    # Run once and exit:
    python scripts/run_tracking_worker.py --once

    # Run continuously polling every 15 seconds:
    python scripts/run_tracking_worker.py --interval 15 --wait-time 10
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from src.queue.tracking_worker import (
    TrackingWorker,
    process_tracking_batch,
)
from src.utils.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("tracking_worker_cli")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run background worker to ingest SQS tracking events into S3 interactions."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process a single batch of messages and exit immediately.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=10.0,
        help="Seconds to sleep between batch polling cycles in continuous mode (default: 10.0).",
    )
    parser.add_argument(
        "--wait-time",
        type=int,
        default=10,
        help="SQS long-polling wait time in seconds (0-20, default: 10).",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=10,
        help="Maximum messages to pull per batch (1-10, default: 10).",
    )
    parser.add_argument(
        "--queue-url",
        type=str,
        default=None,
        help="Explicit SQS Queue URL (overrides environment and config).",
    )
    args = parser.parse_args()

    config = load_config()

    if args.once:
        logger.info("Executing single batch processing cycle...")
        processed = process_tracking_batch(
            queue_url=args.queue_url,
            max_messages=args.max_messages,
            wait_time_seconds=args.wait_time,
        )
        logger.info("Batch completed: processed %d message(s).", processed)
        sys.exit(0)

    # Continuous daemon mode
    logger.info(
        "Starting tracking worker daemon (interval=%.1fs, wait_time=%ds, max_messages=%d)...",
        args.interval,
        args.wait_time,
        args.max_messages,
    )
    worker = TrackingWorker(
        queue_url=args.queue_url,
        poll_interval=args.interval,
        wait_time_seconds=args.wait_time,
        max_messages=args.max_messages,
    )

    def _handle_exit(signum, frame):
        logger.info("Shutdown signal received (%s). Stopping worker...", signum)
        worker.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)

    worker.start()
    try:
        while worker.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        _handle_exit(signal.SIGINT, None)


if __name__ == "__main__":
    main()
