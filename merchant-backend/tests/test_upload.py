from pathlib import Path

from fastapi.testclient import TestClient


def test_csv_upload_and_list(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "merchant.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    from app.main import create_app

    app = create_app()
    csv_content = "sku,name,description,price,currency,stock\nSKU1,Phone,Smart phone,499.99,USD,10\n"

    with TestClient(app) as client:
        upload = client.post(
            "/products/upload",
            files={"file": ("catalog.csv", csv_content, "text/csv")},
        )
        assert upload.status_code == 200
        assert upload.json() == {"uploaded": 1}

        products = client.get("/products")
        assert products.status_code == 200
        assert products.json() == [
            {
                "sku": "SKU1",
                "name": "Phone",
                "description": "Smart phone",
                "price": 499.99,
                "currency": "USD",
                "stock": 10,
            }
        ]
