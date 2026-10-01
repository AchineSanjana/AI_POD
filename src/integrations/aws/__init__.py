"""AWS integrations package for AI_POD."""

from src.integrations.aws.eventbridge import (
    DEFAULT_RULE_NAME,
    DEFAULT_SCHEDULE_EXPRESSION,
    get_eventbridge_client,
    get_retrain_eventbridge_rule,
    setup_retrain_eventbridge_rule,
)

__all__ = [
    "DEFAULT_RULE_NAME",
    "DEFAULT_SCHEDULE_EXPRESSION",
    "get_eventbridge_client",
    "get_retrain_eventbridge_rule",
    "setup_retrain_eventbridge_rule",
]
