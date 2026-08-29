"""Catalog routes — CSV upload with LLM mapping, list, search, edit, and delete products."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select, or_, func, delete

from app.database import get_merchant_session
from app.models import Product, UploadLog, CartItem
from app.schemas import (
    CatalogListResponse,
    ProductResponse,
    ProductUpdate,
    UploadResult,
)
from app.services.csv_processor import process_csv

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.post("/upload", response_model=UploadResult)
async def upload_catalog(
    file: UploadFile = File(...),
    merchant_id: uuid.UUID = Form(...),
):
    """
    Upload a CSV file to ingest products for a merchant.
    Applies LLM-assisted column mapping and ingests into the merchant's dedicated database.
    """
    tenant_db = await get_merchant_session(merchant_id)

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Empty file")

        # Process CSV with LLM-assisted field mapping
        processed = await process_csv(contents, file.filename or "upload.csv")

        upload_id = uuid.uuid4()

        # Create upload log in the merchant's database
        log = UploadLog(
            id=upload_id,
            filename=file.filename,
            total_rows=processed["total_rows"],
            ingested_rows=processed["ingested_rows"],
            skipped_rows=processed["skipped_rows"],
            unmapped_columns=processed["unmapped_columns"],
            inferred_mappings=processed["inferred_mapping"],
            errors=processed["errors"],
        )
        tenant_db.add(log)

        # Insert valid rows into the merchant's dedicated database
        inserted_products: list[Product] = []
        for row in processed["rows"]:
            product = Product(
                upload_id=upload_id,
                title=row["title"],
                description=row["description"],
                price=row["price"],
                category=row["category"],
                attributes=row["attributes"],
                image_url=row["image_url"],
                stock=row["stock"],
            )
            tenant_db.add(product)
            inserted_products.append(product)

        await tenant_db.commit()
        for p in inserted_products:
            await tenant_db.refresh(p)

        return UploadResult(
            upload_id=upload_id,
            filename=file.filename or "upload.csv",
            total_rows=processed["total_rows"],
            ingested_rows=processed["ingested_rows"],
            skipped_rows=processed["skipped_rows"],
            inferred_mapping=processed["inferred_mapping"],
            unmapped_columns=processed["unmapped_columns"],
            errors=processed["errors"],
            products=[ProductResponse.model_validate(p) for p in inserted_products],
        )
    except Exception:
        await tenant_db.rollback()
        raise
    finally:
        await tenant_db.close()


@router.get("", response_model=CatalogListResponse)
async def list_products(
    merchant_id: uuid.UUID = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """List products for a merchant from their dedicated database."""
    tenant_db = await get_merchant_session(merchant_id)
    try:
        offset = (page - 1) * page_size

        count_result = await tenant_db.execute(select(func.count(Product.id)))
        total = count_result.scalar() or 0

        result = await tenant_db.execute(
            select(Product)
            .order_by(Product.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        products = result.scalars().all()

        return CatalogListResponse(
            merchant_id=merchant_id,
            total=total,
            products=[ProductResponse.model_validate(p) for p in products],
        )
    finally:
        await tenant_db.close()


@router.get("/search")
async def search_products(
    merchant_id: uuid.UUID = Query(...),
    query: str = Query("", min_length=0),
):
    """
    Search products by text query in the merchant's dedicated database.
    Used by both the merchant UI and the consumer agent.
    """
    tenant_db = await get_merchant_session(merchant_id)
    try:
        stmt = select(Product)

        if query.strip():
            search_term = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    Product.title.ilike(search_term),
                    Product.description.ilike(search_term),
                    Product.category.ilike(search_term),
                )
            )

        stmt = stmt.order_by(Product.title).limit(20)
        result = await tenant_db.execute(stmt)
        products = result.scalars().all()

        return {
            "merchant_id": str(merchant_id),
            "query": query,
            "results": [ProductResponse.model_validate(p).model_dump(mode="json") for p in products],
        }
    finally:
        await tenant_db.close()


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    merchant_id: uuid.UUID = Query(...),
):
    """Update a product's fields in the merchant's dedicated database."""
    tenant_db = await get_merchant_session(merchant_id)
    try:
        result = await tenant_db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(product, field, value)

        product.updated_at = datetime.utcnow()
        await tenant_db.commit()
        await tenant_db.refresh(product)
        return product
    except Exception:
        await tenant_db.rollback()
        raise
    finally:
        await tenant_db.close()


@router.delete("/{product_id}")
async def delete_product(
    product_id: uuid.UUID,
    merchant_id: uuid.UUID = Query(...),
):
    """Delete a single product from the merchant's dedicated database."""
    tenant_db = await get_merchant_session(merchant_id)
    try:
        result = await tenant_db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        # Delete any cart items referencing this product
        await tenant_db.execute(delete(CartItem).where(CartItem.product_id == product_id))
        await tenant_db.delete(product)
        await tenant_db.commit()

        return {"deleted": str(product_id), "message": f"Product '{product.title}' deleted successfully"}
    except Exception:
        await tenant_db.rollback()
        raise
    finally:
        await tenant_db.close()


@router.delete("/upload/{upload_id}")
async def delete_upload(
    upload_id: uuid.UUID,
    merchant_id: uuid.UUID = Query(...),
):
    """
    Undo / delete an entire CSV upload: deletes all products created during that upload
    and removes the corresponding upload log.
    """
    tenant_db = await get_merchant_session(merchant_id)
    try:
        # Find all product IDs from this upload
        prod_res = await tenant_db.execute(select(Product.id).where(Product.upload_id == upload_id))
        product_ids = prod_res.scalars().all()

        if product_ids:
            # Delete cart items referencing these products
            await tenant_db.execute(delete(CartItem).where(CartItem.product_id.in_(product_ids)))
            # Delete products
            await tenant_db.execute(delete(Product).where(Product.upload_id == upload_id))

        # Delete upload log
        await tenant_db.execute(delete(UploadLog).where(UploadLog.id == upload_id))

        await tenant_db.commit()
        return {
            "deleted_upload_id": str(upload_id),
            "deleted_products_count": len(product_ids),
            "message": f"Successfully deleted upload and {len(product_ids)} associated product(s)",
        }
    except Exception:
        await tenant_db.rollback()
        raise
    finally:
        await tenant_db.close()


@router.delete("/clear/all")
async def clear_all_products(
    merchant_id: uuid.UUID = Query(...),
):
    """Clear all products and cart items in the merchant's dedicated database."""
    tenant_db = await get_merchant_session(merchant_id)
    try:
        await tenant_db.execute(delete(CartItem))
        res = await tenant_db.execute(delete(Product))
        await tenant_db.execute(delete(UploadLog))
        await tenant_db.commit()
        return {"message": "All products and upload logs cleared successfully"}
    except Exception:
        await tenant_db.rollback()
        raise
    finally:
        await tenant_db.close()
