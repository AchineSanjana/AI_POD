"""Amazon EventBridge client and scheduled rule setup for AI_POD periodic retraining.

Configures an EventBridge scheduled rule (e.g., cron or rate expression) to trigger
scheduled model retraining across tenants on a recurring timer (e.g. nightly at 02:00 UTC).
"""

from __future__ import annotations

import logging
import os
from typing import Any
import boto3

from src.utils.config import load_config

logger = logging.getLogger(__name__)

DEFAULT_RULE_NAME = "ai-pod-nightly-retrain"
DEFAULT_SCHEDULE_EXPRESSION = "cron(0 2 * * ? *)"  # Nightly at 02:00 UTC
DEFAULT_RULE_DESCRIPTION = "Triggers nightly AI_POD recommendation model retraining across tenants"


def get_aws_region(config: dict | None = None) -> str:
    """Resolve AWS region from environment or configuration."""
    if os.environ.get("AWS_DEFAULT_REGION"):
        return os.environ["AWS_DEFAULT_REGION"]
    if os.environ.get("AWS_REGION"):
        return os.environ["AWS_REGION"]
    if config:
        storage_cfg = config.get("storage", {})
        if storage_cfg.get("region"):
            return storage_cfg["region"]
    return "us-east-1"


def get_eventbridge_client(region_name: str | None = None) -> Any:
    """Return a boto3 EventBridge client."""
    region = region_name or get_aws_region()
    return boto3.client("events", region_name=region)


def setup_retrain_eventbridge_rule(
    rule_name: str = DEFAULT_RULE_NAME,
    schedule_expression: str = DEFAULT_SCHEDULE_EXPRESSION,
    target_endpoint_url: str | None = None,
    target_arn: str | None = None,
    region_name: str | None = None,
    state: str = "ENABLED",
    description: str = DEFAULT_RULE_DESCRIPTION,
) -> dict[str, Any]:
    """Provision or update an Amazon EventBridge scheduled rule for model retraining.

    Args:
        rule_name: Name of the EventBridge rule.
        schedule_expression: Standard cron or rate expression (e.g. 'cron(0 2 * * ? *)').
        target_endpoint_url: Optional API destination endpoint URL to call when triggered.
        target_arn: Optional AWS ARN of the target (e.g. Lambda, ECS Task, API Destination).
        region_name: AWS region.
        state: 'ENABLED' or 'DISABLED'.
        description: Human-readable description of the rule.

    Returns:
        dict containing rule metadata, ARN, and attached targets.
    """
    client = get_eventbridge_client(region_name=region_name)
    logger.info("Setting up EventBridge rule '%s' with schedule '%s'...", rule_name, schedule_expression)

    # 1. Put Rule
    rule_resp = client.put_rule(
        Name=rule_name,
        ScheduleExpression=schedule_expression,
        State=state,
        Description=description,
    )
    rule_arn = rule_resp.get("RuleArn")

    # 2. Put Target if specified
    targets: list[dict[str, Any]] = []
    if target_arn:
        target_entry = {
            "Id": "ai-pod-retrain-target",
            "Arn": target_arn,
        }
        client.put_targets(Rule=rule_name, Targets=[target_entry])
        targets.append(target_entry)
    elif target_endpoint_url:
        target_entry = {
            "Id": "ai-pod-retrain-api-destination",
            "Arn": rule_arn,  # placeholder when API destination ARN is managed by CDK/CloudFormation
        }
        targets.append({"endpoint_url": target_endpoint_url})

    logger.info("EventBridge rule '%s' configured successfully (ARN: %s)", rule_name, rule_arn)
    return {
        "rule_name": rule_name,
        "rule_arn": rule_arn,
        "schedule_expression": schedule_expression,
        "state": state,
        "description": description,
        "targets": targets,
    }


def get_retrain_eventbridge_rule(
    rule_name: str = DEFAULT_RULE_NAME,
    region_name: str | None = None,
) -> dict[str, Any] | None:
    """Retrieve existing EventBridge rule configuration if it exists."""
    client = get_eventbridge_client(region_name=region_name)
    try:
        rule = client.describe_rule(Name=rule_name)
        return {
            "rule_name": rule.get("Name"),
            "rule_arn": rule.get("Arn"),
            "schedule_expression": rule.get("ScheduleExpression"),
            "state": rule.get("State"),
            "description": rule.get("Description"),
        }
    except Exception as exc:
        logger.debug("EventBridge rule '%s' not found or error: %s", rule_name, exc)
        return None
