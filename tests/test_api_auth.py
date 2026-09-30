"""Tests for API Key authentication, header validation, and tenant isolation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.auth import TENANT_AUTH_MAPPING, get_current_tenant, load_tenant_auth
from src.api.recommendations import get_model_for_tenant


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_auth_mapping_loaded_from_config():
    """Verify tenants_auth mapping from config.yaml is properly loaded."""
    mapping = load_tenant_auth()
    assert isinstance(mapping, dict)
    assert "sk-telco-xxxx" in mapping
    assert mapping["sk-telco-xxxx"] == "telco_default"
    assert "sk-ecommerce-xxxx" in mapping
    assert mapping["sk-ecommerce-xxxx"] == "fixture_ecommerce"


def test_valid_api_key_resolves_to_tenant(client: TestClient):
    """Confirm a valid API key in X-API-Key header resolves to the mapped tenant_id."""
    model = get_model_for_tenant("telco_default")
    customer_id = model.customers_.iloc[0]["customer_id"]

    # Test GET endpoint with telco key
    resp_telco = client.get(
        "/recommendations",
        params={"customer_id": customer_id, "top_n": 2},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert resp_telco.status_code == 200
    assert resp_telco.json()["tenant_id"] == "telco_default"

    # Test GET /{customer_id} endpoint with ecommerce key
    ecom_model = get_model_for_tenant("fixture_ecommerce")
    ecom_customer_id = ecom_model.customers_.iloc[0]["customer_id"]

    resp_ecom = client.get(
        f"/recommendations/{ecom_customer_id}",
        headers={"X-API-Key": "sk-ecommerce-xxxx"},
    )
    assert resp_ecom.status_code == 200
    assert resp_ecom.json()["tenant_id"] == "fixture_ecommerce"


def test_missing_api_key_rejected_with_401(client: TestClient):
    """Confirm request with missing X-API-Key is rejected with 401 Unauthorized and clear JSON."""
    # GET /recommendations
    resp = client.get("/recommendations", params={"customer_id": "any_customer"})
    assert resp.status_code == 401
    error = resp.json()
    assert "detail" in error
    assert "API key is missing" in error["detail"]

    # GET /recommendations/{customer_id}
    resp_path = client.get("/recommendations/any_customer")
    assert resp_path.status_code == 401
    assert "API key is missing" in resp_path.json()["detail"]

    # POST /recommendations
    resp_post = client.post("/recommendations", json={"customer_id": "any_customer"})
    assert resp_post.status_code == 401
    assert "API key is missing" in resp_post.json()["detail"]


def test_invalid_api_key_rejected_with_401(client: TestClient):
    """Confirm request with invalid X-API-Key is rejected with 401 Unauthorized and clear JSON."""
    resp = client.get(
        "/recommendations",
        params={"customer_id": "any_customer"},
        headers={"X-API-Key": "sk-totally-bogus-key"},
    )
    assert resp.status_code == 401
    error = resp.json()
    assert "detail" in error
    assert "Invalid API Key" in error["detail"]


def test_cross_tenant_spoofing_prevented_in_body_and_query(client: TestClient):
    """Confirm a request with key for Tenant A cannot access Tenant B's data via body or query.

    Even if caller specifies tenant_id='fixture_ecommerce' in the request body (POST)
    or query string (GET), the system strictly binds the request to 'telco_default'.
    """
    telco_model = get_model_for_tenant("telco_default")
    telco_cust = telco_model.customers_.iloc[0]["customer_id"]
    telco_products = set(telco_model.products_["product_id"].astype(str))

    ecom_model = get_model_for_tenant("fixture_ecommerce")
    ecom_products = set(ecom_model.products_["product_id"].astype(str))

    # Assert catalogs are disjoint
    assert telco_products.isdisjoint(ecom_products)

    # 1. POST attempt to spoof tenant_id in JSON body
    post_resp = client.post(
        "/recommendations",
        json={
            "customer_id": telco_cust,
            "tenant_id": "fixture_ecommerce",
            "top_n": 3,
        },
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert post_resp.status_code == 200
    post_data = post_resp.json()
    # Server-side resolved tenant must strictly be telco_default
    assert post_data["tenant_id"] == "telco_default"
    rec_ids = {str(r["product_id"]) for r in post_data["recommendations"]}
    assert rec_ids.issubset(telco_products)
    assert rec_ids.isdisjoint(ecom_products)

    # 2. GET attempt to spoof tenant_id in query params
    get_resp = client.get(
        "/recommendations",
        params={
            "customer_id": telco_cust,
            "tenant_id": "fixture_ecommerce",
            "top_n": 3,
        },
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["tenant_id"] == "telco_default"
    get_rec_ids = {str(r["product_id"]) for r in get_data["recommendations"]}
    assert get_rec_ids.issubset(telco_products)
    assert get_rec_ids.isdisjoint(ecom_products)

    # 3. Attempting to query Tenant B's customer ID using Tenant A's key must return 404
    ecom_cust = ecom_model.customers_.iloc[0]["customer_id"]
    cross_resp = client.post(
        "/recommendations",
        json={
            "customer_id": ecom_cust,
            "tenant_id": "fixture_ecommerce",
        },
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert cross_resp.status_code == 404
    assert f"Customer '{ecom_cust}' not found for tenant 'telco_default'" in cross_resp.json()["detail"]


def test_get_tenant_auth_mapping_local_file():
    """Verify get_tenant_auth_mapping loads from config/tenants_auth.local.yaml in local mode."""
    from src.utils.config import get_tenant_auth_mapping

    mapping = get_tenant_auth_mapping({"storage": {"backend": "local"}})
    assert isinstance(mapping, dict)
    assert "sk-telco-xxxx" in mapping
    assert mapping["sk-telco-xxxx"] == "telco_default"


def test_get_tenant_auth_mapping_aws_ssm(monkeypatch):
    """Verify get_tenant_auth_mapping loads from SSM Parameter Store when STORAGE_BACKEND=s3."""
    import json
    import boto3
    from moto import mock_aws
    from src.utils.config import get_tenant_auth_mapping

    with mock_aws():
        ssm = boto3.client("ssm", region_name="us-east-1")
        ssm.put_parameter(
            Name="/ai_pod/tenants_auth",
            Value=json.dumps({"sk-aws-ssm-key": "tenant_ssm_prod"}),
            Type="SecureString",
        )

        monkeypatch.setenv("STORAGE_BACKEND", "s3")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        monkeypatch.delenv("TENANTS_AUTH_SECRET_NAME", raising=False)

        mapping = get_tenant_auth_mapping()
        assert mapping == {"sk-aws-ssm-key": "tenant_ssm_prod"}


def test_get_tenant_auth_mapping_aws_secrets_manager(monkeypatch):
    """Verify get_tenant_auth_mapping loads from Secrets Manager when secret name is configured."""
    import json
    import boto3
    from moto import mock_aws
    from src.utils.config import get_tenant_auth_mapping

    with mock_aws():
        sm = boto3.client("secretsmanager", region_name="us-east-1")
        sm.create_secret(
            Name="prod/ai_pod/tenants_auth",
            SecretString=json.dumps({"sk-aws-sm-key": "tenant_sm_prod"}),
        )

        monkeypatch.setenv("STORAGE_BACKEND", "s3")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        monkeypatch.setenv("TENANTS_AUTH_SECRET_NAME", "prod/ai_pod/tenants_auth")

        mapping = get_tenant_auth_mapping()
        assert mapping == {"sk-aws-sm-key": "tenant_sm_prod"}


def test_get_tenant_auth_mapping_local_fallback(monkeypatch, tmp_path):
    """Verify fallback when config/tenants_auth.local.yaml does not exist."""
    from src.utils.config import get_tenant_auth_mapping

    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setattr(
        "src.utils.config.resolve_path",
        lambda rel: tmp_path / "non_existent.yaml",
    )

    # Fallback to config dict if present
    cfg = {"tenants_auth": {"sk-custom-key": "custom_tenant"}}
    assert get_tenant_auth_mapping(cfg) == {"sk-custom-key": "custom_tenant"}


def test_key_storage_schema_extended():
    """Verify key storage schema has tenant_id, key_type ('private'|'public'), and created_at."""
    from src.utils.config import get_tenant_auth_records

    records = get_tenant_auth_records()
    assert isinstance(records, dict)
    assert "sk-telco-xxxx" in records
    assert "pk-telco-xxxx" in records

    sk_rec = records["sk-telco-xxxx"]
    assert sk_rec["tenant_id"] == "telco_default"
    assert sk_rec["key_type"] == "private"
    assert "created_at" in sk_rec

    pk_rec = records["pk-telco-xxxx"]
    assert pk_rec["tenant_id"] == "telco_default"
    assert pk_rec["key_type"] == "public"
    assert "created_at" in pk_rec


def test_public_key_works_for_track_and_recommendations(client: TestClient):
    """Confirm a public key works for POST /v1/track and GET /v1/recommendations."""
    model = get_model_for_tenant("telco_default")
    customer_id = model.customers_.iloc[0]["customer_id"]

    # 1. GET /v1/recommendations with public key -> 200 OK
    resp_rec = client.get(
        "/v1/recommendations",
        params={"customer_id": customer_id, "top_n": 3},
        headers={"X-API-Key": "pk-telco-xxxx"},
    )
    assert resp_rec.status_code == 200
    rec_data = resp_rec.json()
    assert rec_data["tenant_id"] == "telco_default"
    assert len(rec_data["recommendations"]) <= 3

    # 2. POST /v1/track with public key -> 202 Accepted
    resp_track = client.post(
        "/v1/track",
        json={
            "customer_id": customer_id,
            "session_id": "sess_123",
            "event_type": "view",
            "product_id": "InternetService",
        },
        headers={"X-API-Key": "pk-telco-xxxx"},
    )
    assert resp_track.status_code == 202
    assert resp_track.json() == {"status": "accepted"}


def test_public_key_rejected_with_403_everywhere_else(client: TestClient):
    """Confirm a public key is rejected with 403 Forbidden for all endpoints other than POST /v1/track and GET /v1/recommendations."""
    public_key = "pk-telco-xxxx"

    # POST /v1/recommendations (only GET is permitted)
    resp_post_rec = client.post(
        "/v1/recommendations",
        json={"customer_id": "any_cust", "top_n": 2},
        headers={"X-API-Key": public_key},
    )
    assert resp_post_rec.status_code == 403
    assert "Forbidden" in resp_post_rec.json()["detail"]

    # GET /v1/recommendations/{customer_id}
    resp_path_rec = client.get(
        "/v1/recommendations/any_cust",
        headers={"X-API-Key": public_key},
    )
    assert resp_path_rec.status_code == 403

    # POST /v1/onboard/upload
    resp_upload = client.post(
        "/v1/onboard/upload",
        json={"csv_content": "id,val\n1,2"},
        headers={"X-API-Key": public_key},
    )
    assert resp_upload.status_code == 403

    # POST /v1/onboard/validate
    resp_validate = client.post(
        "/v1/onboard/validate",
        headers={"X-API-Key": public_key},
    )
    assert resp_validate.status_code == 403

    # POST /v1/onboard/confirm
    resp_confirm = client.post(
        "/v1/onboard/confirm",
        json={"candidate_config": {}},
        headers={"X-API-Key": public_key},
    )
    assert resp_confirm.status_code == 403

    # POST /v1/onboard/train
    resp_train = client.post(
        "/v1/onboard/train",
        headers={"X-API-Key": public_key},
    )
    assert resp_train.status_code == 403

    # GET /v1/onboard/status
    resp_status = client.get(
        "/v1/onboard/status",
        headers={"X-API-Key": public_key},
    )
    assert resp_status.status_code == 403

    # GET /v1/onboard/config
    resp_cfg = client.get(
        "/v1/onboard/config",
        headers={"X-API-Key": public_key},
    )
    assert resp_cfg.status_code == 403

    # GET /v1/onboard/keys (discovery/admin endpoint should not be accessible with public key)
    resp_keys = client.get(
        "/v1/onboard/keys",
        headers={"X-API-Key": public_key},
    )
    assert resp_keys.status_code == 403

    # GET /onboarding/status (legacy endpoint)
    resp_legacy_status = client.get(
        "/onboarding/status",
        headers={"X-API-Key": public_key},
    )
    assert resp_legacy_status.status_code == 403


def test_private_key_continues_to_work_everywhere(client: TestClient):
    """Confirm a private key continues to work everywhere it already does, and track is public-only."""
    private_key = "sk-telco-xxxx"
    model = get_model_for_tenant("telco_default")
    customer_id = model.customers_.iloc[0]["customer_id"]

    # 1. GET /v1/recommendations
    resp1 = client.get(
        "/v1/recommendations",
        params={"customer_id": customer_id, "top_n": 2},
        headers={"X-API-Key": private_key},
    )
    assert resp1.status_code == 200

    # 2. POST /v1/recommendations
    resp2 = client.post(
        "/v1/recommendations",
        json={"customer_id": customer_id, "top_n": 2},
        headers={"X-API-Key": private_key},
    )
    assert resp2.status_code == 200

    # 3. GET /v1/recommendations/{customer_id}
    resp3 = client.get(
        f"/v1/recommendations/{customer_id}",
        headers={"X-API-Key": private_key},
    )
    assert resp3.status_code == 200

    # 4. POST /v1/track is authenticated by public key only, so private key is rejected with 403
    resp4 = client.post(
        "/v1/track",
        json={"session_id": "sess_1", "product_id": "prod_1", "event_type": "view"},
        headers={"X-API-Key": private_key},
    )
    assert resp4.status_code == 403

    # 5. GET /v1/onboard/status
    resp5 = client.get(
        "/v1/onboard/status",
        headers={"X-API-Key": private_key},
    )
    assert resp5.status_code == 200
    assert resp5.json()["tenant_id"] == "telco_default"


def test_public_key_tenant_isolation(client: TestClient):
    """Confirm public key strictly binds requests to mapped tenant and cannot access another tenant's data."""
    from src.api.tracking import clear_queue, get_queued_events
    clear_queue()

    telco_model = get_model_for_tenant("telco_default")
    telco_cust = telco_model.customers_.iloc[0]["customer_id"]
    ecom_model = get_model_for_tenant("fixture_ecommerce")
    ecom_cust = ecom_model.customers_.iloc[0]["customer_id"]

    # Querying Tenant B's customer with Tenant A's public key must return 404
    resp = client.get(
        "/v1/recommendations",
        params={"customer_id": ecom_cust, "tenant_id": "fixture_ecommerce"},
        headers={"X-API-Key": "pk-telco-xxxx"},
    )
    assert resp.status_code == 404
    assert f"Customer '{ecom_cust}' not found for tenant 'telco_default'" in resp.json()["detail"]

    # Tracking event with Tenant A's public key is strictly attributed to Tenant A
    track_resp = client.post(
        "/v1/track",
        json={
            "customer_id": telco_cust,
            "session_id": "sess_1",
            "product_id": "prod_1",
            "event_type": "view",
            "tenant_id": "fixture_ecommerce",
        },
        headers={"X-API-Key": "pk-telco-xxxx"},
    )
    assert track_resp.status_code == 202
    events = get_queued_events()
    assert len(events) == 1
    assert events[0]["tenant_id"] == "telco_default"


def test_issue_keys_script_and_endpoint(client: TestClient):
    """Confirm issuing both a private and a public key for a tenant at once works via utility and endpoint."""
    from src.utils.key_manager import issue_tenant_keys

    # 1. Via Python/admin script function
    res = issue_tenant_keys("brand_new_tenant")
    assert res["status"] == "ok"
    assert res["tenant_id"] == "brand_new_tenant"
    assert res["private_key"]["key_type"] == "private"
    assert res["public_key"]["key_type"] == "public"
    assert res["private_key"]["key"].startswith("sk-brand_new_tenant-")
    assert res["public_key"]["key"].startswith("pk-brand_new_tenant-")
    assert res["private_key"]["created_at"] is not None
    assert res["public_key"]["created_at"] is not None

    # Immediate usability check: public key works for track
    resp_track = client.post(
        "/v1/track",
        json={"session_id": "sess_new", "product_id": "prod_new", "event_type": "view"},
        headers={"X-API-Key": res["public_key"]["key"]},
    )
    assert resp_track.status_code == 202
    assert resp_track.json() == {"status": "accepted"}

    # Immediate usability check: public key rejected on onboarding
    resp_reject = client.get(
        "/v1/onboard/status",
        headers={"X-API-Key": res["public_key"]["key"]},
    )
    assert resp_reject.status_code == 403

    # Immediate usability check: private key works on onboarding
    resp_priv = client.get(
        "/v1/onboard/status",
        headers={"X-API-Key": res["private_key"]["key"]},
    )
    assert resp_priv.status_code == 200
    assert resp_priv.json()["tenant_id"] == "brand_new_tenant"

    # 2. Via POST /v1/onboard/issue-keys endpoint
    ep_resp = client.post(
        "/v1/onboard/issue-keys",
        json={"tenant_id": "endpoint_tenant"},
    )
    assert ep_resp.status_code == 200
    ep_data = ep_resp.json()
    assert ep_data["status"] == "ok"
    assert ep_data["tenant_id"] == "endpoint_tenant"
    assert ep_data["private_key"]["key"].startswith("sk-endpoint_tenant-")
    assert ep_data["public_key"]["key"].startswith("pk-endpoint_tenant-")


