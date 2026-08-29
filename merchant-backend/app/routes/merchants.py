"""Merchant management routes — central registry & database provisioning."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_central_db, provision_merchant_database, drop_merchant_database, _merchant_db_cache
from app.models import Merchant
from app.schemas import MerchantCreate, MerchantResponse

router = APIRouter(prefix="/merchants", tags=["merchants"])


def _generate_db_name(merchant_name: str, merchant_id: uuid.UUID) -> str:
    """Generate a clean, safe PostgreSQL database name for a merchant."""
    clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", merchant_name.lower().strip())
    clean_name = re.sub(r"_+", "_", clean_name).strip("_")
    if not clean_name:
        clean_name = "store"
    short_uuid = merchant_id.hex[:8]
    return f"merchant_{clean_name}_{short_uuid}"


@router.post("", response_model=MerchantResponse, status_code=201)
async def create_merchant(
    payload: MerchantCreate,
    central_db: AsyncSession = Depends(get_central_db),
):
    """
    Create a new merchant, provision a dedicated PostgreSQL database instance for them,
    and register the merchant in the central registry.
    """
    merchant_id = uuid.uuid4()
    db_name = _generate_db_name(payload.name, merchant_id)

    # Step 1: Provision dedicated PostgreSQL database instance and tenant schema
    try:
        await provision_merchant_database(db_name)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to provision merchant database '{db_name}': {str(e)}",
        )

    # Step 2: Register merchant in central registry
    merchant = Merchant(
        id=merchant_id,
        name=payload.name,
        email=payload.email,
        database_name=db_name,
    )
    central_db.add(merchant)
    await central_db.flush()
    await central_db.refresh(merchant)

    return merchant


@router.get("", response_model=list[MerchantResponse])
async def list_merchants(central_db: AsyncSession = Depends(get_central_db)):
    """List all merchants from the central registry."""
    result = await central_db.execute(select(Merchant).order_by(Merchant.created_at.desc()))
    merchants = result.scalars().all()
    return merchants


@router.get("/{merchant_id}", response_model=MerchantResponse)
async def get_merchant(
    merchant_id: uuid.UUID,
    central_db: AsyncSession = Depends(get_central_db),
):
    """Get a single merchant by ID from the central registry."""
    result = await central_db.execute(select(Merchant).where(Merchant.id == merchant_id))
    merchant = result.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return merchant


@router.delete("/{merchant_id}")
async def delete_merchant(
    merchant_id: uuid.UUID,
    central_db: AsyncSession = Depends(get_central_db),
):
    """
    Permanently delete a merchant:
    1. Drop the merchant's dedicated PostgreSQL database instance.
    2. Remove the merchant record from the central registry.
    """
    result = await central_db.execute(select(Merchant).where(Merchant.id == merchant_id))
    merchant = result.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")

    db_name = merchant.database_name
    merchant_name = merchant.name

    # Step 1: Drop the dedicated PostgreSQL database
    try:
        await drop_merchant_database(db_name)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to drop merchant database '{db_name}': {str(e)}",
        )

    # Step 2: Delete from central registry
    await central_db.delete(merchant)
    await central_db.commit()

    # Clear cache
    _merchant_db_cache.pop(merchant_id, None)

    return {
        "deleted_merchant_id": str(merchant_id),
        "database_name": db_name,
        "message": f"Merchant '{merchant_name}' and database '{db_name}' permanently deleted",
    }

