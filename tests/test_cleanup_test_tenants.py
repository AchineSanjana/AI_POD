"""Tests for scripts/cleanup_test_tenants.py.

Verifies:
1. Dry-run discovers target test tenants and alters nothing.
2. Protected tenants are strictly never deleted or touched.
3. --apply creates a zip backup and removes only test tenant resources.
4. Refuses execution on production environment.
5. Refuses execution when lock file exists.
"""
from pathlib import Path
import pytest
import yaml

from scripts.cleanup_test_tenants import (
    PROTECTED_TENANTS,
    discover_test_tenants,
    collect_tenant_resources,
    apply_cleanup,
    is_protected_tenant,
)


@pytest.fixture
def mock_project(tmp_path):
    """Create a temporary project structure with protected and test tenants."""
    proj = tmp_path / "AI_POD"
    proj.mkdir()
    backup_dir = tmp_path / "aipod_backup"

    # Create directories
    for sub in ("raw", "processed", "catalog", "telemetry"):
        (proj / "data" / sub).mkdir(parents=True)
    (proj / "models").mkdir()
    (proj / "status").mkdir()
    (proj / "config").mkdir()

    # Protected tenant: telco_default
    (proj / "data" / "raw" / "telco_default").mkdir()
    (proj / "data" / "raw" / "telco_default" / "interactions.csv").write_text("a,b,c\n1,2,3")
    (proj / "status" / "telco_default.json").write_text('{"tenant_id": "telco_default"}')

    # Test tenant: e2e_test_storefront
    (proj / "data" / "catalog" / "e2e_test_storefront").mkdir()
    (proj / "data" / "catalog" / "e2e_test_storefront" / "catalog.csv").write_text("id,name\nP1,Widget")
    (proj / "status" / "e2e_test_storefront.json").write_text('{"tenant_id": "e2e_test_storefront"}')
    (proj / "models" / "e2e_test_storefront").mkdir()
    (proj / "models" / "e2e_test_storefront" / "model.pkl").write_text("mock")

    # Extra legacy test tenant: tenant_cat_a
    (proj / "data" / "catalog" / "tenant_cat_a").mkdir()
    (proj / "data" / "catalog" / "tenant_cat_a" / "catalog.csv").write_text("id,name\nP2,Gadget")

    # Config files
    cfg_data = {
        "tenants": {
            "telco_default": {"customers": "id"},
            "e2e_test_storefront": {"customers": "id"},
            "tenant_cat_a": {"customers": "id"},
        }
    }
    with open(proj / "config" / "config.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg_data, f)

    auth_data = {
        "keys": {
            "pk-telco": {"tenant_id": "telco_default", "key_type": "public"},
            "sk-telco": {"tenant_id": "telco_default", "key_type": "private"},
            "pk-e2e": {"tenant_id": "e2e_test_storefront", "key_type": "public"},
            "sk-e2e": {"tenant_id": "e2e_test_storefront", "key_type": "private"},
        },
        "tenants": {
            "telco_default": {"status": "active"},
            "e2e_test_storefront": {"status": "active"},
        },
    }
    with open(proj / "config" / "tenants_auth.local.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(auth_data, f)

    return proj, backup_dir


def test_protected_tenants_whitelist():
    """Verify is_protected_tenant correctly identifies all protected tenants."""
    for t in [
        "telco_default",
        "sanjtelco",
        "sanjgrocery",
        "movielens_demo",
        "online_retail",
        "fresh_cart_co",
        "thread_co",
        "carrie_eccomerce",
        "admin",
    ]:
        assert is_protected_tenant(t) is True

    assert is_protected_tenant("e2e_test_tenant") is False
    assert is_protected_tenant("tenant_cat_a") is False


def test_discovery_and_dry_run(mock_project):
    proj, _ = mock_project
    targets = discover_test_tenants(proj, extra_ids=["tenant_cat_a"])
    assert "e2e_test_storefront" in targets
    assert "tenant_cat_a" in targets
    assert "telco_default" not in targets

    resources = collect_tenant_resources(proj, targets)
    assert len(resources["dirs"]) == 3  # catalog/e2e, models/e2e, catalog/tenant_cat_a
    assert len(resources["files"]) == 1  # status/e2e_test_storefront.json

    # In dry run, files remain
    assert (proj / "data" / "catalog" / "e2e_test_storefront").exists()
    assert (proj / "data" / "raw" / "telco_default").exists()


def test_apply_cleanup_with_backup(mock_project):
    proj, backup_dir = mock_project
    targets = discover_test_tenants(proj, extra_ids=["tenant_cat_a"])
    resources = collect_tenant_resources(proj, targets)

    apply_cleanup(proj, resources, backup_dir)

    # 1. Backup archive must exist
    zip_files = list(backup_dir.glob("cleanup_*.zip"))
    assert len(zip_files) == 1
    assert zip_files[0].stat().st_size > 0

    # 2. Test tenants removed
    assert not (proj / "data" / "catalog" / "e2e_test_storefront").exists()
    assert not (proj / "models" / "e2e_test_storefront").exists()
    assert not (proj / "status" / "e2e_test_storefront.json").exists()
    assert not (proj / "data" / "catalog" / "tenant_cat_a").exists()

    # 3. Protected tenant remains intact
    assert (proj / "data" / "raw" / "telco_default").exists()
    assert (proj / "data" / "raw" / "telco_default" / "interactions.csv").exists()
    assert (proj / "status" / "telco_default.json").exists()

    # 4. YAML updated
    with open(proj / "config" / "config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    assert "telco_default" in cfg["tenants"]
    assert "e2e_test_storefront" not in cfg["tenants"]
    assert "tenant_cat_a" not in cfg["tenants"]

    with open(proj / "config" / "tenants_auth.local.yaml", "r", encoding="utf-8") as f:
        auth = yaml.safe_load(f)
    assert "pk-telco" in auth["keys"]
    assert "pk-e2e" not in auth["keys"]


def test_production_guard(mock_project, monkeypatch):
    proj, backup_dir = mock_project
    monkeypatch.setenv("ENV", "production")

    targets = discover_test_tenants(proj)
    resources = collect_tenant_resources(proj, targets)

    with pytest.raises(RuntimeError, match="production"):
        apply_cleanup(proj, resources, backup_dir)


def test_lock_file_guard(mock_project):
    proj, backup_dir = mock_project
    (proj / ".server.lock").write_text("locked")

    targets = discover_test_tenants(proj)
    resources = collect_tenant_resources(proj, targets)

    with pytest.raises(RuntimeError, match="lock file detected"):
        apply_cleanup(proj, resources, backup_dir)

