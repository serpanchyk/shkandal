from fastapi.testclient import TestClient
from shkandal_backend.app import create_app
from shkandal_backend.config import BackendConfig


def test_healthz() -> None:
    app = create_app(BackendConfig(service_name="backend-test"))
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"service": "backend-test", "status": "ok"}
