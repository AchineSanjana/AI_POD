"""Queue management and messaging integrations (Amazon SQS)."""

from src.queue.tracking_queue import (
    DEFAULT_QUEUE_NAME,
    DEFAULT_REGION,
    create_tracking_queue,
    get_sqs_client,
    get_sqs_config,
    push_tracking_event_to_sqs,
    resolve_queue_url,
)
from src.queue.tracking_worker import (
    DEFAULT_EVENT_WEIGHTS,
    TrackingWorker,
    append_tenant_interactions,
    detect_identity_transition,
    get_tracking_worker,
    load_identity_mappings,
    process_tracking_batch,
    save_identity_mappings,
    start_background_tracking_worker,
    stop_background_tracking_worker,
    transform_event_to_interaction,
)

__all__ = [
    "DEFAULT_EVENT_WEIGHTS",
    "DEFAULT_QUEUE_NAME",
    "DEFAULT_REGION",
    "TrackingWorker",
    "append_tenant_interactions",
    "create_tracking_queue",
    "detect_identity_transition",
    "get_sqs_client",
    "get_sqs_config",
    "get_tracking_worker",
    "load_identity_mappings",
    "process_tracking_batch",
    "push_tracking_event_to_sqs",
    "resolve_queue_url",
    "save_identity_mappings",
    "start_background_tracking_worker",
    "stop_background_tracking_worker",
    "transform_event_to_interaction",
]
