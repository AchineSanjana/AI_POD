#!/usr/bin/env python3
"""Cleanup Test Tenants Tool.

Safely discovers and optionally removes test tenants (prefixed with 'e2e_' or specified via --extra-id).
Default mode is DRY RUN (no files modified, no entries deleted).

Safety Guards:
1. Protected Tenants Blacklist: NEVER touches or removes:
   telco_default, sanjtelco, sanjgrocery, movielens_demo, online_retail,
   fresh_cart_co, thread_co, carrie_eccomerce, admin.
2. Refuses execution on production (ENV/AI_POD_ENV in 'production', 'prod').
3. Refuses execution if write locks (.lock, .server.lock) are present.
4. On --apply, creates a zip backup in ../aipod_backup/cleanup_<timestamp>.zip BEFORE modifying anything.
5. Uses atomic writes for YAML configuration updates.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any
import zipfile
import yaml


# Protected tenants that must NEVER be cleaned up
PROTECTED_TENANTS = frozenset({
    "telco_default",
    "sanjtelco",
    "sanjgrocery",
    "movielens_demo",
    "online_retail",
    "fresh_cart_co",
    "thread_co",
    "carrie_eccomerce",
    "admin",
})


def is_protected_tenant(tenant_id: str) -> bool:
    """Return True if tenant_id is in the protected blacklist."""
    return tenant_id.strip().lower() in PROTECTED_TENANTS


def check_production_guard() -> None:
    """Refuse to run destructive operations on production environments."""
    for var in ("ENV", "AI_POD_ENV"):
        val = os.environ.get(var, "").strip().lower()
        if val in ("production", "prod"):
            raise RuntimeError(f"Refusing to execute tenant cleanup: {var}={val} is production!")


def check_write_locks(project_root: Path) -> None:
    """Check for lock files indicating active writes or running servers."""
    lock_patterns = [".server.lock", "*.lock"]
    for pattern in lock_patterns:
        for p in project_root.glob(pattern):
            if p.is_file():
                raise RuntimeError(f"Active lock file detected: {p}. Cannot safely run cleanup.")


def discover_test_tenants(
    project_root: Path,
    extra_ids: list[str] | None = None,
) -> set[str]:
    """Discover all test tenants matching 'e2e_*' or explicit extra_ids."""
    target_tenants: set[str] = set()
    extra_set = {x.strip().lower() for x in (extra_ids or []) if x.strip()}

    def consider_name(name: str):
        cleaned = name.strip()
        if not cleaned:
            return
        lower = cleaned.lower()
        if is_protected_tenant(lower):
            return
        if lower.startswith("e2e_") or lower in extra_set:
            target_tenants.add(cleaned)

    # Scan data directories
    data_dir = project_root / "data"
    for sub in ("raw", "processed", "catalog", "telemetry"):
        sub_dir = data_dir / sub
        if sub_dir.is_dir():
            for entry in sub_dir.iterdir():
                if entry.is_dir():
                    consider_name(entry.name)

    # Scan models directory
    models_dir = project_root / "models"
    if models_dir.is_dir():
        for entry in models_dir.iterdir():
            if entry.is_dir():
                consider_name(entry.name)

    # Scan status directory
    status_dir = project_root / "status"
    if status_dir.is_dir():
        for entry in status_dir.glob("*.json"):
            name = entry.stem.removesuffix("_dataset_stats")
            consider_name(name)

    # Scan YAML configs
    cfg_path = project_root / "config" / "config.yaml"
    if cfg_path.is_file():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for t in (data.get("tenants") or {}).keys():
                consider_name(str(t))
        except Exception:
            pass

    auth_path = project_root / "config" / "tenants_auth.local.yaml"
    if auth_path.is_file():
        try:
            with open(auth_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for rec in (data.get("keys") or {}).values():
                if isinstance(rec, dict) and "tenant_id" in rec:
                    consider_name(str(rec["tenant_id"]))
            for t in (data.get("tenants") or {}).keys():
                consider_name(str(t))
        except Exception:
            pass

    accounts_path = project_root / "config" / "accounts.local.yaml"
    if accounts_path.is_file():
        try:
            with open(accounts_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for acc in (data.get("accounts") or []):
                if isinstance(acc, dict) and "tenant_id" in acc:
                    consider_name(str(acc["tenant_id"]))
        except Exception:
            pass

    # Ensure no protected tenant is ever in target_tenants
    forbidden = target_tenants.intersection(PROTECTED_TENANTS)
    if forbidden:
        raise RuntimeError(f"CRITICAL SAFETY VIOLATION: Protected tenants targeted: {forbidden}")

    return target_tenants


def collect_tenant_resources(
    project_root: Path,
    target_tenants: set[str],
) -> dict[str, Any]:
    """Collect all file paths, directory paths, and YAML modifications for targets."""
    dirs_to_delete: list[Path] = []
    files_to_delete: list[Path] = []
    yaml_updates: dict[Path, dict[str, list[str]]] = {}

    for t in target_tenants:
        # Directories in data/
        for sub in ("raw", "processed", "catalog", "telemetry"):
            d = project_root / "data" / sub / t
            if d.is_dir():
                dirs_to_delete.append(d)

        # Directory in models/
        md = project_root / "models" / t
        if md.is_dir():
            dirs_to_delete.append(md)

        # Files in status/
        sf1 = project_root / "status" / f"{t}.json"
        if sf1.is_file():
            files_to_delete.append(sf1)
        sf2 = project_root / "status" / f"{t}_dataset_stats.json"
        if sf2.is_file():
            files_to_delete.append(sf2)

    # Check YAML entries
    # 1. config/config.yaml
    cfg_file = project_root / "config" / "config.yaml"
    if cfg_file.is_file():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                d = yaml.safe_load(f) or {}
            matching_tenants = [t for t in (d.get("tenants") or {}).keys() if t in target_tenants]
            if matching_tenants:
                yaml_updates[cfg_file] = {"tenants": matching_tenants}
        except Exception:
            pass

    # 2. config/tenants_auth.local.yaml
    auth_file = project_root / "config" / "tenants_auth.local.yaml"
    if auth_file.is_file():
        try:
            with open(auth_file, "r", encoding="utf-8") as f:
                d = yaml.safe_load(f) or {}
            matching_keys = [
                k for k, v in (d.get("keys") or {}).items()
                if isinstance(v, dict) and v.get("tenant_id") in target_tenants
            ]
            matching_tenants = [t for t in (d.get("tenants") or {}).keys() if t in target_tenants]
            if matching_keys or matching_tenants:
                yaml_updates[auth_file] = {
                    "keys": matching_keys,
                    "tenants": matching_tenants,
                }
        except Exception:
            pass

    # 3. config/accounts.local.yaml
    acc_file = project_root / "config" / "accounts.local.yaml"
    if acc_file.is_file():
        try:
            with open(acc_file, "r", encoding="utf-8") as f:
                d = yaml.safe_load(f) or {}
            matching_accs = [
                acc.get("email") or acc.get("tenant_id")
                for acc in (d.get("accounts") or [])
                if isinstance(acc, dict) and acc.get("tenant_id") in target_tenants
            ]
            if matching_accs:
                yaml_updates[acc_file] = {"accounts": [str(x) for x in matching_accs if x]}
        except Exception:
            pass

    return {
        "tenants": sorted(target_tenants),
        "dirs": sorted(dirs_to_delete),
        "files": sorted(files_to_delete),
        "yaml_updates": yaml_updates,
    }


def create_backup_zip(
    project_root: Path,
    backup_dir: Path,
    resources: dict[str, Any],
) -> Path:
    """Create a backup zip file containing all files/directories and YAMLs to be altered."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_path = backup_dir / f"cleanup_{ts}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add YAML configs
        for yfile in resources["yaml_updates"].keys():
            if yfile.is_file():
                rel = yfile.relative_to(project_root)
                zf.write(yfile, arcname=str(rel))

        # Add individual files
        for f in resources["files"]:
            if f.is_file():
                rel = f.relative_to(project_root)
                zf.write(f, arcname=str(rel))

        # Add directories
        for d in resources["dirs"]:
            if d.is_dir():
                for root, _, files in os.walk(d):
                    for file in files:
                        fp = Path(root) / file
                        rel = fp.relative_to(project_root)
                        zf.write(fp, arcname=str(rel))

    return zip_path


def apply_cleanup(
    project_root: Path,
    resources: dict[str, Any],
    backup_dir: Path,
) -> None:
    """Execute cleanup after safety checks and backup creation."""
    check_production_guard()
    check_write_locks(project_root)

    # 1. Create backup
    zip_path = create_backup_zip(project_root, backup_dir, resources)
    print(f"[BACKUP] Created backup archive: {zip_path}")

    # 2. Delete directories
    for d in resources["dirs"]:
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            print(f"[DELETE DIR] {d.relative_to(project_root)}")

    # 3. Delete files
    for f in resources["files"]:
        if f.is_file():
            f.unlink(missing_ok=True)
            print(f"[DELETE FILE] {f.relative_to(project_root)}")

    # 4. Atomic YAML updates
    for yfile, removals in resources["yaml_updates"].items():
        if not yfile.is_file():
            continue
        with open(yfile, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Remove keys
        if "tenants" in removals and "tenants" in data and isinstance(data["tenants"], dict):
            for t in removals["tenants"]:
                data["tenants"].pop(t, None)
        if "keys" in removals and "keys" in data and isinstance(data["keys"], dict):
            for k in removals["keys"]:
                data["keys"].pop(k, None)
        if "accounts" in removals and "accounts" in data and isinstance(data["accounts"], list):
            target_tenants = set(resources["tenants"])
            data["accounts"] = [
                acc for acc in data["accounts"]
                if not (isinstance(acc, dict) and acc.get("tenant_id") in target_tenants)
            ]

        # Write to temp file then atomic replace
        with tempfile.NamedTemporaryFile("w", dir=yfile.parent, delete=False, encoding="utf-8") as tf:
            yaml.safe_dump(data, tf, default_flow_style=False, sort_keys=False)
            temp_name = tf.name

        os.replace(temp_name, str(yfile))
        print(f"[UPDATE YAML] Cleaned entries in {yfile.relative_to(project_root)}")


def main():
    parser = argparse.ArgumentParser(description="Cleanup test tenants from AI_POD.")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Perform dry run without deleting anything (default).")
    parser.add_argument("--apply", action="store_true", help="Perform real deletion after backup.")
    parser.add_argument("--extra-id", action="append", default=[], help="Additional legacy test tenant ID to include (repeatable).")
    parser.add_argument("--backup-dir", type=str, default="", help="Backup directory (default: ../aipod_backup).")
    parser.add_argument("--project-root", type=str, default="", help="AI_POD project root directory.")

    args = parser.parse_args()

    # Determine project root
    if args.project_root:
        project_root = Path(args.project_root).resolve()
    else:
        project_root = Path(__file__).resolve().parent.parent

    # Determine backup dir
    if args.backup_dir:
        backup_dir = Path(args.backup_dir).resolve()
    else:
        backup_dir = (project_root.parent / "aipod_backup").resolve()

    target_tenants = discover_test_tenants(project_root, args.extra_id)
    resources = collect_tenant_resources(project_root, target_tenants)

    print("=========================================================")
    print(" AI_POD Test Tenant Cleanup")
    print("=========================================================")
    print(f"Project root: {project_root}")
    print(f"Discovered test tenants ({len(resources['tenants'])}): {', '.join(resources['tenants']) if resources['tenants'] else 'None'}")
    print(f"Directories to delete: {len(resources['dirs'])}")
    for d in resources["dirs"]:
        print(f"  - {d.relative_to(project_root)}")
    print(f"Files to delete: {len(resources['files'])}")
    for f in resources["files"]:
        print(f"  - {f.relative_to(project_root)}")
    print(f"YAML configs to modify: {len(resources['yaml_updates'])}")
    for yf, rem in resources["yaml_updates"].items():
        print(f"  - {yf.relative_to(project_root)}: {rem}")

    if args.apply:
        print("\n[MODE] APPLY requested. Executing safe cleanup...")
        apply_cleanup(project_root, resources, backup_dir)
        print("\nCleanup completed successfully.")
    else:
        print("\n[MODE] DRY RUN (No changes made).")
        print("To apply cleanup, run: python scripts/cleanup_test_tenants.py --apply")


if __name__ == "__main__":
    main()

