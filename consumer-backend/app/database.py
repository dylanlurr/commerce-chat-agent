"""Dynamic database engine and session manager for tenant databases."""

from __future__ import annotations

import uuid
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.models import Merchant

# ── Central Registry Session ─────────────────────────────────────────────────

central_engine = create_async_engine(settings.database_url, echo=False)
central_sessionmaker = async_sessionmaker(
    central_engine, class_=AsyncSession, expire_on_commit=False
)

# ── Tenant Engine & Session Pool ─────────────────────────────────────────────

_tenant_engines: dict[str, AsyncEngine] = {}
_tenant_sessionmakers: dict[str, async_sessionmaker] = {}
_merchant_db_cache: dict[uuid.UUID, str] = {}


def get_tenant_engine(db_name: str) -> AsyncEngine:
    """Get or create an AsyncEngine for a specific tenant database."""
    if db_name not in _tenant_engines:
        db_url = settings.get_tenant_db_url(db_name)
        _tenant_engines[db_name] = create_async_engine(db_url, echo=False, pool_pre_ping=True)
        _tenant_sessionmakers[db_name] = async_sessionmaker(
            _tenant_engines[db_name], class_=AsyncSession, expire_on_commit=False
        )
    return _tenant_engines[db_name]


def get_tenant_sessionmaker(db_name: str) -> async_sessionmaker:
    """Get the sessionmaker for a specific tenant database."""
    if db_name not in _tenant_sessionmakers:
        get_tenant_engine(db_name)
    return _tenant_sessionmakers[db_name]


async def resolve_merchant_db_name(merchant_id: uuid.UUID) -> str:
    """Resolve database_name for a merchant_id from central database."""
    if merchant_id in _merchant_db_cache:
        return _merchant_db_cache[merchant_id]

    async with central_sessionmaker() as session:
        result = await session.execute(select(Merchant).where(Merchant.id == merchant_id))
        merchant = result.scalar_one_or_none()
        if not merchant:
            raise HTTPException(status_code=404, detail=f"Merchant {merchant_id} not found")
        _merchant_db_cache[merchant_id] = merchant.database_name
        return merchant.database_name


async def get_merchant_session(merchant_id: uuid.UUID) -> AsyncSession:
    """Create a new AsyncSession for a merchant's dedicated database."""
    db_name = await resolve_merchant_db_name(merchant_id)
    sm = get_tenant_sessionmaker(db_name)
    return sm()
