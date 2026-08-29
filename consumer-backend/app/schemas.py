"""Pydantic schemas for the consumer backend."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    merchant_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)


class CartItemResponse(BaseModel):
    product_id: str
    title: str
    price: float
    quantity: int


class CartSummary(BaseModel):
    items: list[CartItemResponse]
    total: float
    item_count: int


class ChatResponse(BaseModel):
    reply: str
    cart_summary: Optional[CartSummary] = None


class ProductInfo(BaseModel):
    id: str
    title: str
    description: Optional[str]
    price: float
    category: Optional[str]
    attributes: dict[str, Any]
    image_url: Optional[str]
    stock: int

    model_config = {"from_attributes": True}
