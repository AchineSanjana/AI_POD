import joblib
from fastapi.testclient import TestClient

from app.api.recommendations import MODEL_PATH
from app.main import app


client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_recommendations_for_known_customer():
    model = joblib.load(MODEL_PATH)
    customer_id = model.customers_.iloc[0]["customer_id"]

    response = client.get("/recommendations", params={"customer_id": customer_id, "top_n": 3})
    assert response.status_code == 200

    payload = response.json()
    assert payload["customer_id"] == customer_id
    assert isinstance(payload["recommendations"], list)
    assert len(payload["recommendations"]) <= 3
    assert payload["recommendations"]
    assert "product_id" in payload["recommendations"][0]


def test_get_recommendations_for_unknown_customer():
    response = client.get("/recommendations/999", params={"top_n": 3})
    assert response.status_code == 404