from fastapi.testclient import TestClient

from app.main import create_app


def test_chat_uses_tools_without_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = create_app()

    with TestClient(app) as client:
        search = client.post("/chat", json={"message": "search headphones"})
        assert search.status_code == 200
        assert search.json()["tool_used"] == "search_products"

        add = client.post("/chat", json={"message": "add sku1"})
        assert add.status_code == 200
        assert add.json()["tool_used"] == "add_to_cart"

        checkout = client.post("/chat", json={"message": "checkout"})
        assert checkout.status_code == 200
        assert checkout.json()["tool_used"] == "checkout"
