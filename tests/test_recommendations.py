from fastapi.testclient import TestClient

from src.api.app import app
from src.api.recommendations import MODEL_CACHE, clear_model_cache, get_model_for_tenant


client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_recommendations_for_known_customer():
    clear_model_cache()
    model = get_model_for_tenant("telco_default")
    customer_id = model.customers_.iloc[0]["customer_id"]

    response = client.get(
        "/recommendations",
        params={"customer_id": customer_id, "tenant_id": "telco_default", "top_n": 3},
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["customer_id"] == customer_id
    assert payload["tenant_id"] == "telco_default"
    assert isinstance(payload["recommendations"], list)
    assert len(payload["recommendations"]) <= 3
    assert payload["recommendations"]
    assert "product_id" in payload["recommendations"][0]


def test_get_recommendations_missing_tenant_model():
    response = client.get(
        "/recommendations",
        params={"customer_id": "cust_1", "tenant_id": "non_existent_tenant"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == (
        "No trained model found for tenant 'non_existent_tenant'. "
        "Run the pipeline for this tenant first."
    )


def test_get_recommendations_unknown_customer_validation():
    response = client.get(
        "/recommendations/99999",
        params={"tenant_id": "telco_default", "top_n": 3},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Customer '99999' not found for tenant 'telco_default'"


def test_model_caching_behavior():
    clear_model_cache()
    assert "telco_default" not in MODEL_CACHE

    model = get_model_for_tenant("telco_default")
    customer_id = model.customers_.iloc[0]["customer_id"]

    # Request populates cache
    response = client.get(
        f"/recommendations/{customer_id}",
        params={"tenant_id": "telco_default"},
    )
    assert response.status_code == 200
    assert "telco_default" in MODEL_CACHE
    assert MODEL_CACHE["telco_default"] is model


def test_recommendations_with_valid_api_key():
    model = get_model_for_tenant("telco_default")
    customer_id = model.customers_.iloc[0]["customer_id"]

    response = client.get(
        "/recommendations",
        params={"customer_id": customer_id},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "telco_default"
    assert payload["customer_id"] == customer_id


def test_recommendations_with_ecommerce_api_key():
    model = get_model_for_tenant("fixture_ecommerce")
    customer_id = model.customers_.iloc[0]["customer_id"]

    response = client.get(
        f"/recommendations/{customer_id}",
        headers={"X-API-Key": "sk-ecommerce-xxxx"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "fixture_ecommerce"
    assert payload["customer_id"] == customer_id


def test_recommendations_with_invalid_api_key():
    response = client.get(
        "/recommendations",
        params={"customer_id": "any_customer"},
        headers={"X-API-Key": "sk-invalid-key-999"},
    )
    assert response.status_code == 401
    assert "Invalid API Key" in response.json()["detail"]


def test_api_key_overrides_client_tenant_id():
    """Server-side resolution from API key must take precedence over client-supplied tenant_id query param."""
    model = get_model_for_tenant("telco_default")
    customer_id = model.customers_.iloc[0]["customer_id"]

    response = client.get(
        "/recommendations",
        params={"customer_id": customer_id, "tenant_id": "fixture_ecommerce"},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "telco_default"
    assert payload["customer_id"] == customer_id