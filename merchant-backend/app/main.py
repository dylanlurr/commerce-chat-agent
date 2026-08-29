from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .db import engine, get_db
from .models import Base, Product
from .schemas import ProductOut, UploadResult
from .services import upsert_products_from_csv


def create_app() -> FastAPI:
    app = FastAPI(title="Merchant Backend")

    @app.on_event("startup")
    def startup() -> None:
        Base.metadata.create_all(bind=engine)

    @app.post("/products/upload", response_model=UploadResult)
    async def upload_products(file: UploadFile = File(...), db: Session = Depends(get_db)) -> UploadResult:
        content = (await file.read()).decode("utf-8")
        try:
            uploaded = upsert_products_from_csv(content, db)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return UploadResult(uploaded=uploaded)

    @app.get("/products", response_model=list[ProductOut])
    def list_products(db: Session = Depends(get_db)) -> list[ProductOut]:
        products = db.query(Product).order_by(Product.name.asc()).all()
        return products

    return app


app = create_app()
