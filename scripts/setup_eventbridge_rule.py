"""Admin CLI script to create or update an Amazon EventBridge scheduled rule for retraining.

Usage:
    # Setup default nightly rule (02:00 UTC):
    python scripts/setup_eventbridge_rule.py

    # Setup with custom schedule and API destination endpoint:
    python scripts/setup_eventbridge_rule.py --rule-name custom-nightly-retrain \\
        --schedule "cron(0 3 * * ? *)" --endpoint-url "https://api.yourdomain.com/v1/retrain/scheduled"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.integrations.aws.eventbridge import (  # noqa: E402
    DEFAULT_RULE_NAME,
    DEFAULT_SCHEDULE_EXPRESSION,
    get_aws_region,
    setup_retrain_eventbridge_rule,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or update Amazon EventBridge scheduled rule for model retraining."
    )
    parser.add_argument(
        "--rule-name",
        default=DEFAULT_RULE_NAME,
        help=f"Name of the EventBridge rule (default: {DEFAULT_RULE_NAME})",
    )
    parser.add_argument(
        "--schedule",
        default=DEFAULT_SCHEDULE_EXPRESSION,
        help=f"Cron or rate schedule expression (default: {DEFAULT_SCHEDULE_EXPRESSION})",
    )
    parser.add_argument(
        "--endpoint-url",
        default=None,
        help="Optional API destination endpoint URL called on trigger (e.g. https://api.yourdomain.com/v1/retrain/scheduled)",
    )
    parser.add_argument(
        "--target-arn",
        default=None,
        help="Optional AWS Target ARN (Lambda / ECS / API Destination)",
    )
    parser.add_argument(
        "--region",
        default=None,
        help=f"AWS Region (default: {get_aws_region()})",
    )
    parser.add_argument(
        "--state",
        choices=["ENABLED", "DISABLED"],
        default="ENABLED",
        help="Rule state (default: ENABLED)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = setup_retrain_eventbridge_rule(
            rule_name=args.rule_name,
            schedule_expression=args.schedule,
            target_endpoint_url=args.endpoint_url,
            target_arn=args.target_arn,
            region_name=args.region,
            state=args.state,
        )
        print("Successfully configured Amazon EventBridge scheduled rule:")
        print(f"  Rule Name: {result['rule_name']}")
        print(f"  Schedule:  {result['schedule_expression']}")
        print(f"  State:     {result['state']}")
        print(f"  ARN:       {result.get('rule_arn')}")
        if result.get("targets"):
            print(f"  Targets:   {result['targets']}")
        return 0
    except Exception as exc:
        print(f"Error configuring EventBridge rule '{args.rule_name}': {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
