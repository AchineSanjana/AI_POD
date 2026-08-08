"""Tests for domain-agnostic tenant customer segmentation configuration and evaluation."""

import pandas as pd
import pytest

from src.utils.config import (
    TenantSegmentationConfig,
    get_tenant_config,
    load_config,
)
from scripts.generate_evaluation_results import (
    evaluate_tenant_models,
    format_segment_table,
)


def test_tenant_segmentation_config_parsing():
    """Verify tenant config correctly parses optional segmentation block."""
    config = load_config()

    # telco_default has segmentation on tenure
    telco_cfg = get_tenant_config(config, "telco_default")
    assert telco_cfg.segmentation is not None
    assert telco_cfg.segmentation.field == "tenure"
    assert telco_cfg.segmentation.split == "median"

    # movielens_demo has segmentation on rating_count
    movie_cfg = get_tenant_config(config, "movielens_demo")
    assert movie_cfg.segmentation is not None
    assert movie_cfg.segmentation.field == "rating_count"
    assert movie_cfg.segmentation.split == "median"


def test_tenant_segmentation_optional_graceful_fallback():
    """Verify tenant without segmentation block skips segment evaluation gracefully."""
    config = load_config()
    raw_config = dict(config)
    # Clone telco config without segmentation block
    raw_config["tenants"] = dict(config["tenants"])
    raw_config["tenants"]["no_seg_tenant"] = dict(raw_config["tenants"]["telco_default"])
    raw_config["tenants"]["no_seg_tenant"].pop("segmentation", None)

    no_seg_cfg = get_tenant_config(raw_config, "no_seg_tenant")
    assert no_seg_cfg.segmentation is None

    # format_segment_table returns graceful message
    table_str = format_segment_table("no_seg_tenant", None, None)
    assert "No segmentation field declared" in table_str


def test_format_segment_table_with_metrics():
    """Verify segment breakdown markdown table rendering."""
    sample_seg_data = {
        "newer": {
            "content_based": {"precision@5": 0.2, "recall@5": 0.5, "ndcg@5": 0.4},
            "ranking": {"precision@5": 0.3, "recall@5": 0.7, "ndcg@5": 0.6},
        },
        "established": {
            "content_based": {"precision@5": 0.25, "recall@5": 0.6, "ndcg@5": 0.5},
            "ranking": {"precision@5": 0.35, "recall@5": 0.8, "ndcg@5": 0.7},
        },
    }

    table_md = format_segment_table("test_tenant", sample_seg_data, "test_field")
    assert "### Segment Breakdown (`test_tenant` - Field: `test_field`)" in table_md
    assert "| newer | ranking | 0.300 | 0.700 | 0.600 | ranking |" in table_md
    assert "| established | ranking | 0.350 | 0.800 | 0.700 | ranking |" in table_md
