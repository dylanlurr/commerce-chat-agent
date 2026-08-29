import csv
from io import StringIO

from sqlalchemy.orm import Session

from .models import Product


REQUIRED_COLUMNS = {"sku", "name", "description", "price", "currency", "stock"}


def upsert_products_from_csv(raw_csv: str, db: Session) -> int:
    reader = csv.DictReader(StringIO(raw_csv))
    headers = set(reader.fieldnames or [])
    missing = REQUIRED_COLUMNS - headers
    if missing:
        raise ValueError(f"Missing required CSV columns: {', '.join(sorted(missing))}")

    uploaded = 0
    for row in reader:
        sku = (row.get("sku") or "").strip()
        if not sku:
            continue

        product = db.query(Product).filter(Product.sku == sku).first()
        if product is None:
            product = Product(sku=sku)
            db.add(product)

        product.name = (row.get("name") or "").strip()
        product.description = (row.get("description") or "").strip()
        product.price = float(row.get("price") or 0)
        product.currency = ((row.get("currency") or "USD").strip() or "USD").upper()
        product.stock = int(float(row.get("stock") or 0))
        uploaded += 1

    db.commit()
    return uploaded
