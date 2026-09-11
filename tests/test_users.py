from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_list_users() -> None:
    response = client.get("/api/v1/users")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    # Confirma estrutura do schema UserRead e presença do created_at
    user = next((u for u in data if u["id"] == 1), data[0])
    assert "id" in user
    assert "name" in user
    assert "email" in user
    assert "role" in user
    assert user["role"] in {"admin", "professional", "patient"}
    assert "is_active" in user
    assert "created_at" in user

    # Valida formato ISO do created_at
    created_at = datetime.fromisoformat(user["created_at"])
    assert isinstance(created_at, datetime)
