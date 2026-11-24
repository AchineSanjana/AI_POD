"""Global pytest fixtures and guards for the test suite."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Generator
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

MONITORED_PATHS = [
    Path("data/catalog"),
    Path("data/telemetry"),
    Path("config/config.yaml"),
    Path("config/accounts.local.yaml"),
    Path("config/tenants_auth.local.yaml"),
]


def _snapshot_state() -> dict[str, int]:
    """Capture relative path -> file size for monitored files and directories."""
    state: dict[str, int] = {}
    for target in MONITORED_PATHS:
        full_target = REPO_ROOT / target
        if not full_target.exists():
            continue
        if full_target.is_file():
            state[str(target.as_posix())] = full_target.stat().st_size
        elif full_target.is_dir():
            for root, _, files in os.walk(full_target):
                for f in files:
                    fp = Path(root) / f
                    try:
                        rel = fp.relative_to(REPO_ROOT).as_posix()
                        state[rel] = fp.stat().st_size
                    except (ValueError, OSError):
                        pass
    return state


def _is_test_tenant(tenant_id: str | None) -> bool:
    """Check if a tenant is an e2e_* or test-created tenant."""
    if not tenant_id:
        return False
    t = str(tenant_id).strip().lower()
    test_prefixes = (
        "e2e_",
        "test_",
        "tenant_cat_",
        "tenant_s3",
        "tenant_seed_",
        "tenant_test_",
        "bench_",
        "mock_",
        "tmp_",
        "endpoint_",
        "brand_new_",
        "no_data_",
        "unconfigured_",
        "perf_",
        "priority_",
        "fixture_",
        "untrained_",
        "non_existent_",
    )
    test_exact = {
        "movielens_demo",
        "nexus_dynamics",
        "rotate_keys_inc",
        "tenant_isolation_a",
        "tenant_isolation_b",
        "test_merchant",
    }
    return any(t.startswith(p) for p in test_prefixes) or t in test_exact


def _load_yaml_safe(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _extract_auth_records(path: Path) -> dict[str, dict[str, Any]]:
    data = _load_yaml_safe(path)
    records = data.get("tenants_auth", {})
    return records if isinstance(records, dict) else {}


def _extract_accounts(path: Path) -> dict[str, dict[str, Any]]:
    data = _load_yaml_safe(path)
    accs = data.get("accounts", {})
    return accs if isinstance(accs, dict) else {}


@pytest.fixture(scope="session", autouse=True)
def guard_repository_state() -> Generator[None, None, None]:
    """Session-scoped guard fixture (Step 3.a).

    Records the state (file paths, sizes, and tenant records) of:
    - data/catalog/
    - data/telemetry/
    - config/config.yaml
    - config/accounts.local.yaml
    - config/tenants_auth.local.yaml

    Fails the session at teardown if tests modified, created, or deleted files or records
    for real tenants (non-e2e / non-test tenants) or modified persistent configuration.
    Cleans up any runtime telemetry part files emitted during the test run so the repository
    remains completely pristine.
    """
    initial_file_state = _snapshot_state()
    initial_auth_records = _extract_auth_records(REPO_ROOT / "config" / "tenants_auth.local.yaml")
    initial_accounts_data = _extract_accounts(REPO_ROOT / "config" / "accounts.local.yaml")

    yield

    # Clean up any runtime telemetry part files created during the test session
    current_files = _snapshot_state()
    for path in current_files:
        if path not in initial_file_state and path.startswith("data/telemetry/") and not path.endswith(".gitkeep"):
            fp = REPO_ROOT / path
            try:
                if fp.is_file():
                    fp.unlink(missing_ok=True)
                parent = fp.parent
                while parent != REPO_ROOT / "data/telemetry" and parent != REPO_ROOT:
                    if parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()
                        parent = parent.parent
                    else:
                        break
            except Exception:
                pass

    final_file_state = _snapshot_state()
    final_auth_records = _extract_auth_records(REPO_ROOT / "config" / "tenants_auth.local.yaml")
    final_accounts_data = _extract_accounts(REPO_ROOT / "config" / "accounts.local.yaml")

    violations: list[str] = []

    # 1. Check config/config.yaml: must never be modified
    cfg_path = "config/config.yaml"
    if cfg_path in initial_file_state:
        if cfg_path not in final_file_state or final_file_state[cfg_path] != initial_file_state[cfg_path]:
            violations.append(f"Persistent config modified: {cfg_path}")

    # 2. Check config/tenants_auth.local.yaml: any changed/added records must only belong to test tenants
    for key, final_rec in final_auth_records.items():
        tenant = final_rec.get("tenant_id") if isinstance(final_rec, dict) else None
        if key not in initial_auth_records:
            # Newly added key record
            if not _is_test_tenant(tenant):
                violations.append(
                    f"Forbidden real tenant key added to config/tenants_auth.local.yaml: {key} (tenant: {tenant})"
                )
        else:
            init_rec = initial_auth_records[key]
            if final_rec != init_rec:
                if not _is_test_tenant(tenant):
                    violations.append(
                        f"Forbidden real tenant key modified in config/tenants_auth.local.yaml: {key} (tenant: {tenant})"
                    )

    # 3. Check config/accounts.local.yaml: any changed/added accounts must only belong to test tenants
    for acc_id, acc in final_accounts_data.items():
        if isinstance(acc, dict):
            email = acc.get("email")
            tenant = acc.get("tenant_id")
            if acc_id not in initial_accounts_data:
                if not _is_test_tenant(tenant):
                    violations.append(
                        f"Forbidden real tenant account added to config/accounts.local.yaml: {email} (tenant: {tenant})"
                    )
            elif acc != initial_accounts_data[acc_id]:
                if not _is_test_tenant(tenant):
                    violations.append(
                        f"Forbidden real tenant account modified in config/accounts.local.yaml: {email} (tenant: {tenant})"
                    )

    # 4. Check data/catalog/ and data/telemetry/ directories
    for path, final_size in final_file_state.items():
        parts = path.split("/")
        if len(parts) >= 3 and parts[0] == "data" and parts[1] in ("catalog", "telemetry"):
            tenant = parts[2]
            if not _is_test_tenant(tenant):
                if path not in initial_file_state:
                    violations.append(
                        f"Newly created file for real tenant: {path} (size: {final_size} bytes)"
                    )
                elif final_size != initial_file_state[path]:
                    violations.append(
                        f"Modified file for real tenant: {path} (initial size: {initial_file_state[path]}, final size: {final_size})"
                    )

    for path, init_size in initial_file_state.items():
        parts = path.split("/")
        if len(parts) >= 3 and parts[0] == "data" and parts[1] in ("catalog", "telemetry"):
            tenant = parts[2]
            if not _is_test_tenant(tenant) and path not in final_file_state:
                violations.append(
                    f"Deleted file for real tenant: {path} (original size: {init_size} bytes)"
                )

    if violations:
        msg = (
            "Repository state guard violation detected!\n"
            "Tests modified files for real / non-test tenants or modified persistent config:\n- "
            + "\n- ".join(violations)
        )
        pytest.fail(msg)
