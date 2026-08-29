"""Pydantic schemas for request/response validation."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Merchant ──────────────────────────────────────────────────────────────────

class MerchantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: Optional[str] = None


class MerchantResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: Optional[str]
    database_name: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Product ───────────────────────────────────────────────────────────────────

class ProductResponse(BaseModel):
    id: uuid.UUID
    upload_id: Optional[uuid.UUID] = None
    title: str
    description: Optional[str]
    price: Decimal
    category: Optional[str]
    attributes: dict[str, Any]
    image_url: Optional[str]
    stock: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProductUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    category: Optional[str] = None
    attributes: Optional[dict[str, Any]] = None
    image_url: Optional[str] = None
    stock: Optional[int] = None


# ── Upload ────────────────────────────────────────────────────────────────────

class UploadResult(BaseModel):
    upload_id: Optional[uuid.UUID] = None
    filename: str
    total_rows: int
    ingested_rows: int
    skipped_rows: int
    inferred_mapping: dict[str, str] = Field(default_factory=dict)
    unmapped_columns: list[str] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    products: list[ProductResponse] = Field(default_factory=list)


# ── Catalog List ──────────────────────────────────────────────────────────────

class CatalogListResponse(BaseModel):
    merchant_id: uuid.UUID
    total: int
    products: list[ProductResponse]
