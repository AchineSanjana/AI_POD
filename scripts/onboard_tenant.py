"""CLI script and workflow for onboarding new tenant datasets.

Inspects raw data, auto-generates tenant configuration, presents a plain-English
review summary, prompts for human confirmation/correction on ambiguous fields,
saves the validated configuration block into config.yaml, and optionally runs
the recommendation pipeline.

Usage:
    python scripts/onboard_tenant.py --file data/raw/telco_customer_churn.csv \\
        --tenant_id acme_corp
    python scripts/onboard_tenant.py --file new_data.csv --tenant_id acme_corp \\
        --auto-accept
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

# Allow running as `python scripts/onboard_tenant.py` from project root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.adapters.generic_config_adapter import GenericConfigAdapter  # noqa: E402
from src.onboarding.config_generator import (  # noqa: E402
    _validate_tenant_config,
    generate_review_summary,
    generate_tenant_config,
)
from src.onboarding.profiler import (  # noqa: E402
    ColumnProfile,
    ProfileReport,
    profile_dataframe,
)
from src.utils.config import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    get_tenant_config,
    resolve_path,
)
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)


def save_tenant_to_config(
    tenant_id: str,
    tenant_block: dict[str, Any],
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    """Save or update a tenant configuration block in config.yaml.

    Parameters
    ----------
    tenant_id : str
        Tenant identifier key under 'tenants'.
    tenant_block : dict[str, Any]
        The validated tenant configuration dictionary.
    config_path : Path, default DEFAULT_CONFIG_PATH
        Path to config.yaml file.
    """
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, encoding="utf-8") as f:
            full_config = yaml.safe_load(f) or {}
    else:
        full_config = {}

    if "tenants" not in full_config:
        full_config["tenants"] = {}

    full_config["tenants"][tenant_id] = tenant_block

    with open(config_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(full_config, f, sort_keys=False, default_flow_style=False)


def handle_review_prompts(
    report: ProfileReport | list[ColumnProfile],
    config_block: dict[str, Any],
    tenant_id: str,
    prompt_fn: Callable[[str], str] = input,
    non_interactive: bool = False,
    overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Interactive decision point for columns flagged with needs_review.

    Parameters
    ----------
    report : ProfileReport | list[ColumnProfile]
        The profile report containing column metadata.
    config_block : dict[str, Any]
        The candidate tenant configuration dictionary.
    tenant_id : str
        Tenant identifier.
    prompt_fn : Callable[[str], str], default input
        Function used to capture user responses.
    non_interactive : bool, default False
        If True, accepts auto-detected defaults without prompting.
    overrides : dict[str, str] | None, default None
        Explicit column overrides mapping column_name -> action.

    Returns
    -------
    dict[str, Any]
        Updated, validated configuration dictionary.
    """
    review_cols = [c for c in report if c.needs_review]
    if not review_cols or non_interactive:
        if overrides:
            _apply_overrides(config_block, report, overrides)
        _validate_tenant_config(config_block, tenant_id)
        return config_block

    print("\n" + "=" * 70)
    print("HUMAN DECISION POINT: REVIEWING AMBIGUOUS COLUMNS")
    print("=" * 70)

    overrides_dict = dict(overrides or {})

    for col in review_cols:
        col_name = col.name
        if col_name in overrides_dict:
            continue

        print(f"\nColumn: '{col_name}'")
        print(f"  Suggested Dtype : {col.suggested_dtype}")
        print(f"  Confidence Score: {col.confidence_score:.2f}")
        print(f"  Review Reason   : {col.review_reason}")
        if col.distinct_values:
            print(f"  Distinct Values : {col.distinct_values[:10]}")

        print("Options:")
        print("  [1] Keep suggested dtype")
        print("  [2] Set as categorical feature")
        print("  [3] Set as numeric feature")
        print("  [4] Treat as binary service column (product)")
        print("  [5] Exclude from feature set")

        try:
            choice = prompt_fn("Select option [1-5, default: 1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = "1"

        if choice == "2":
            overrides_dict[col_name] = "categorical"
        elif choice == "3":
            overrides_dict[col_name] = "numeric"
        elif choice == "4":
            overrides_dict[col_name] = "service"
        elif choice == "5":
            overrides_dict[col_name] = "skip"
        else:
            overrides_dict[col_name] = col.suggested_dtype

    _apply_overrides(config_block, report, overrides_dict)
    _validate_tenant_config(config_block, tenant_id)
    return config_block


def _apply_overrides(
    config_block: dict[str, Any],
    report: ProfileReport | list[ColumnProfile],
    overrides: dict[str, str],
) -> None:
    """Apply manual field-level overrides to the generated config block."""
    col_map = {c.name: c for c in report}
    customer_features = config_block["customers"]["features"]
    service_cols = config_block["interactions"]["service_columns"]

    for col_name, action in overrides.items():
        col = col_map.get(col_name)
        if not col:
            continue

        action_lower = action.lower().strip()

        # 1. Remove from existing customer features
        customer_features[:] = [f for f in customer_features if f["name"] != col_name]

        # 2. Apply requested action
        if action_lower in ("categorical", "cat"):
            feat: dict[str, Any] = {"name": col_name, "dtype": "categorical"}
            if col.distinct_values:
                feat["allowed_values"] = [str(v) for v in col.distinct_values]
                if len(col.distinct_values) <= 10:
                    feat["encoding"] = "one_hot"
            customer_features.append(feat)
            if col_name in service_cols:
                service_cols.remove(col_name)

        elif action_lower in ("numeric", "num"):
            customer_features.append({"name": col_name, "dtype": "numeric"})
            if col_name in service_cols:
                service_cols.remove(col_name)

        elif action_lower in ("service", "product"):
            if col_name not in service_cols:
                service_cols.append(col_name)

        elif action_lower in ("skip", "exclude", "drop"):
            if col_name in service_cols:
                service_cols.remove(col_name)


def onboard_tenant(
    data_file: str | Path,
    tenant_id: str,
    config_path: Path = DEFAULT_CONFIG_PATH,
    prompt_fn: Callable[[str], str] = input,
    non_interactive: bool = False,
    auto_accept: bool = False,
    log_dir: str | Path = "onboarding_logs",
    overrides: dict[str, str] | None = None,
    run_pipeline_flag: bool = False,
) -> dict[str, Any]:
    """Execute complete end-to-end dataset onboarding workflow.

    Parameters
    ----------
    data_file : str | Path
        Path to raw data file.
    tenant_id : str
        Unique identifier for the tenant.
    config_path : Path, default DEFAULT_CONFIG_PATH
        Path to config.yaml.
    prompt_fn : Callable[[str], str], default input
        Input prompt function.
    non_interactive : bool, default False
        If True, executes without waiting for terminal prompts.
    auto_accept : bool, default False
        If True, accepts auto-detected best guesses for all fields and writes
        an audit review log to ``onboarding_logs/{tenant_id}_config_review.txt``.
    log_dir : str | Path, default "onboarding_logs"
        Directory where review audit logs are saved.
    overrides : dict[str, str] | None, default None
        Explicit column adjustments.
    run_pipeline_flag : bool, default False
        If True, triggers pipeline execution after saving.

    Returns
    -------
    dict[str, Any]
        The final verified tenant configuration block.
    """
    file_path = resolve_path(data_file)
    if not file_path.exists():
        file_path = Path(data_file)
        if not file_path.exists():
            raise FileNotFoundError(f"Raw data file not found: {data_file}")

    print(f"\n[INFO] Starting onboarding for tenant '{tenant_id}' from {data_file}...")

    # 1. Load raw data
    ds_str = str(file_path).lower()
    if ds_str.endswith(".json"):
        df = pd.read_json(file_path)
    else:
        df = pd.read_csv(file_path)

    # 2. Run Profiler & Config Generator
    report = profile_dataframe(df)
    config_block = generate_tenant_config(report, tenant_id, str(data_file))

    # 3. Print Plain-English Review Summary
    summary = generate_review_summary(report)
    print("\n" + "=" * 70)
    print("DATASET ONBOARDING & PROFILING SUMMARY")
    print("=" * 70)
    print(summary)
    print("=" * 70)

    # 4. Handle auto-accept vs interactive decision point
    if auto_accept:
        non_interactive = True
        audit_dir = resolve_path(log_dir)
        audit_dir.mkdir(parents=True, exist_ok=True)
        log_file = audit_dir / f"{tenant_id}_config_review.txt"
        log_file.write_text(summary, encoding="utf-8")
        print(f"[INFO] Auto-accept enabled. Audit summary written to {log_file}.")

    final_config_block = handle_review_prompts(
        report=report,
        config_block=config_block,
        tenant_id=tenant_id,
        prompt_fn=prompt_fn,
        non_interactive=non_interactive,
        overrides=overrides,
    )

    # 5. Confirm and write to config.yaml
    should_save = True
    if not non_interactive and not auto_accept:
        try:
            confirm = prompt_fn(
                f"\nSave verified config for '{tenant_id}' into config.yaml? (Y/n): "
            ).strip()
            should_save = confirm.lower() not in ("n", "no")
        except (EOFError, KeyboardInterrupt):
            should_save = True

    if should_save:
        save_tenant_to_config(tenant_id, final_config_block, config_path)
        print(f"[SUCCESS] Tenant '{tenant_id}' saved to {config_path}.")
    else:
        print(f"[WARN] Tenant '{tenant_id}' configuration was NOT saved.")
        return final_config_block

    # 6. Optional pipeline execution
    if run_pipeline_flag:
        print(f"\n[INFO] Running pipeline for tenant '{tenant_id}'...")
        full_cfg = {"tenants": {tenant_id: final_config_block}}
        tenant_cfg = get_tenant_config(full_cfg, tenant_id)
        adapter = GenericConfigAdapter(tenant_cfg)
        customers, products, interactions = adapter.run()
        print(
            f"[SUCCESS] Pipeline completed for tenant '{tenant_id}': "
            f"{len(customers):,} customers, {len(products):,} products, "
            f"{len(interactions):,} interactions."
        )

    return final_config_block


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Onboard a new tenant dataset with profiling and decision review."
    )
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        required=True,
        help="Path to raw dataset file (e.g. data/raw/new_company_data.csv)",
    )
    parser.add_argument(
        "--tenant_id",
        "-t",
        type=str,
        required=True,
        help="Unique tenant ID (e.g. acme_corp)",
    )
    parser.add_argument(
        "--auto-accept",
        "--auto_accept",
        "-a",
        action="store_true",
        help="Skip interactive confirmation, accept best guesses, and write audit log",
    )
    parser.add_argument(
        "--run_pipeline",
        action="store_true",
        help="Immediately run recommendation pipeline for the new tenant",
    )
    parser.add_argument(
        "--non_interactive",
        "--yes",
        "-y",
        action="store_true",
        help="Accept auto-detected choices without interactive prompts",
    )
    parser.add_argument(
        "--config_path",
        type=str,
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to config.yaml (default: config/config.yaml)",
    )
    parser.add_argument(
        "--log_dir",
        type=str,
        default="onboarding_logs",
        help="Directory for review audit logs (default: onboarding_logs)",
    )

    args = parser.parse_args()

    onboard_tenant(
        data_file=args.file,
        tenant_id=args.tenant_id,
        config_path=Path(args.config_path),
        non_interactive=args.non_interactive,
        auto_accept=args.auto_accept,
        log_dir=args.log_dir,
        run_pipeline_flag=args.run_pipeline,
    )


if __name__ == "__main__":
    main()
