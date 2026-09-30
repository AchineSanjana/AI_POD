"""Admin script to create an Amazon SQS standard queue for tracking events.

Usage:
    python scripts/create_tracking_queue.py
    python scripts/create_tracking_queue.py --queue-name custom-events --region us-east-1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.queue.tracking_queue import create_tracking_queue, get_sqs_config  # noqa: E402


def parse_args() -> argparse.Namespace:
    default_region, _, default_name = get_sqs_config()
    parser = argparse.ArgumentParser(
        description="Create standard Amazon SQS queue for incoming tracking events."
    )
    parser.add_argument(
        "--queue-name",
        "--queue_name",
        default=default_name,
        help=f"Name of the standard SQS queue to create (default: {default_name})",
    )
    parser.add_argument(
        "--region",
        default=default_region,
        help=f"AWS Region (default: {default_region})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        queue_url = create_tracking_queue(
            queue_name=args.queue_name,
            region_name=args.region,
        )
        print("Successfully created SQS tracking queue:")
        print(f"  Queue Name: {args.queue_name}")
        print(f"  Region:     {args.region}")
        print(f"  Queue URL:  {queue_url}")
        print("\nTo use this queue, set the following environment variable or add to config.yaml:")
        print(f"  TRACKING_QUEUE_URL={queue_url}")
        return 0
    except Exception as exc:
        print(f"Error creating SQS queue '{args.queue_name}': {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
