"""SQLAlchemy ORM models for central registry and tenant databases."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Text,
    Numeric,
    Integer,
    DateTime,
    ForeignKey,
    ARRAY,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── Central Registry Model (stored in central commerce_agent DB) ──────────────

class Merchant(Base):
    __tablename__ = "merchants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    email = Column(String(255))
    database_name = Column(String(255), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Tenant Models (stored in each merchant's dedicated database) ──────────────

class Category(Base):
    __tablename__ = "categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)


class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upload_id = Column(UUID(as_uuid=True), nullable=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    price = Column(Numeric(12, 2), nullable=False)
    category = Column(String(255))
    attributes = Column(JSONB, default=dict)
    image_url = Column(String(1000))
    stock = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UploadLog(Base):
    __tablename__ = "upload_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(500))
    total_rows = Column(Integer)
    ingested_rows = Column(Integer)
    skipped_rows = Column(Integer)
    unmapped_columns = Column(ARRAY(String), default=list)
    inferred_mappings = Column(JSONB, default=dict)
    errors = Column(JSONB, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)


class Cart(Base):
    __tablename__ = "carts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    items = relationship("CartItem", back_populates="cart", lazy="selectin", cascade="all, delete-orphan")


class CartItem(Base):
    __tablename__ = "cart_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cart_id = Column(UUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)

    cart = relationship("Cart", back_populates="items")
    product = relationship("Product", lazy="selectin")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cart_id = Column(UUID(as_uuid=True), ForeignKey("carts.id"), nullable=False)
    session_id = Column(String(255), nullable=False)
    total_amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String(50), default="completed")
    created_at = Column(DateTime, default=datetime.utcnow)
