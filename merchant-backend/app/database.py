"""Database management for central registry and dynamic tenant databases."""

from __future__ import annotations

import uuid
from typing import AsyncGenerator
from fastapi import HTTPException
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.models import Merchant, Base

# ── Central Registry Engine & Session ────────────────────────────────────────

central_engine = create_async_engine(settings.database_url, echo=False)
central_sessionmaker = async_sessionmaker(
    central_engine, class_=AsyncSession, expire_on_commit=False
)


async def get_central_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency yielding a session for the central registry database."""
    async with central_sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


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
    """Resolve database_name for a merchant_id from cache or central database."""
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
    """Create a new AsyncSession for a merchant's database."""
    db_name = await resolve_merchant_db_name(merchant_id)
    sm = get_tenant_sessionmaker(db_name)
    return sm()


# ── Tenant Database Provisioning ─────────────────────────────────────────────

TENANT_SCHEMA_STATEMENTS = [
    'CREATE EXTENSION IF NOT EXISTS "pgcrypto"',
    """
    CREATE TABLE IF NOT EXISTS categories (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name VARCHAR(255) NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        upload_id UUID,
        title VARCHAR(500) NOT NULL,
        description TEXT,
        price NUMERIC(12,2) NOT NULL,
        category VARCHAR(255),
        attributes JSONB DEFAULT '{}'::jsonb,
        image_url VARCHAR(1000),
        stock INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS upload_id UUID",
    """
    CREATE TABLE IF NOT EXISTS upload_logs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        filename VARCHAR(500),
        total_rows INTEGER,
        ingested_rows INTEGER,
        skipped_rows INTEGER,
        unmapped_columns TEXT[] DEFAULT '{}',
        inferred_mappings JSONB DEFAULT '{}'::jsonb,
        errors JSONB DEFAULT '[]'::jsonb,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS carts (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        session_id VARCHAR(255) NOT NULL,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cart_items (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        cart_id UUID NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
        product_id UUID NOT NULL REFERENCES products(id),
        quantity INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        cart_id UUID NOT NULL REFERENCES carts(id),
        session_id VARCHAR(255) NOT NULL,
        total_amount NUMERIC(12,2) NOT NULL,
        status VARCHAR(50) DEFAULT 'completed',
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_products_search ON products 
    USING gin(to_tsvector('english', title || ' ' || COALESCE(description, '') || ' ' || COALESCE(category, '')))
    """,
    "CREATE INDEX IF NOT EXISTS idx_carts_session ON carts(session_id)",
]


import logging

logger = logging.getLogger(__name__)


async def provision_merchant_database(db_name: str) -> None:
    """
    Create a new dedicated PostgreSQL database for a merchant
    and initialize its schema tables and indexes.
    """
    logger.info(f"Starting database provisioning for '{db_name}'...")

    # Step 1: Connect to admin DB with AUTOCOMMIT to execute CREATE DATABASE
    admin_url = settings.get_admin_db_url()
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")

    try:
        async with admin_engine.connect() as conn:
            check_sql = text("SELECT 1 FROM pg_database WHERE datname = :dbname")
            res = await conn.execute(check_sql, {"dbname": db_name})
            if not res.scalar():
                safe_db_name = db_name.replace('"', '""')
                logger.info(f"Executing CREATE DATABASE '{safe_db_name}'...")
                await conn.execute(text(f'CREATE DATABASE "{safe_db_name}"'))
                logger.info(f"Database '{safe_db_name}' created successfully.")
            else:
                logger.info(f"Database '{db_name}' already exists. Proceeding to schema initialization.")
    except Exception as e:
        logger.error(f"Error creating database '{db_name}': {e}", exc_info=True)
        raise RuntimeError(f"Failed to create database '{db_name}': {e}") from e
    finally:
        await admin_engine.dispose()

    # Step 2: Connect to the newly created database and execute schema statements
    tenant_engine = get_tenant_engine(db_name)
    try:
        async with tenant_engine.begin() as conn:
            for idx, stmt in enumerate(TENANT_SCHEMA_STATEMENTS, start=1):
                logger.debug(f"Executing schema statement {idx}/{len(TENANT_SCHEMA_STATEMENTS)} on '{db_name}'")
                await conn.execute(text(stmt))

        # Step 3: Verify that tables exist
        async with tenant_engine.connect() as conn:
            tables_res = await conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            )
            created_tables = {row[0] for row in tables_res.fetchall()}
            expected_tables = {"categories", "products", "upload_logs", "carts", "cart_items", "transactions"}
            missing_tables = expected_tables - created_tables
            if missing_tables:
                raise RuntimeError(f"Database '{db_name}' provisioning failed: missing tables {missing_tables}")

            logger.info(f"Successfully provisioned database '{db_name}' with tables: {sorted(created_tables)}")
    except Exception as e:
        logger.error(f"Error during schema migration for '{db_name}': {e}", exc_info=True)
        raise RuntimeError(f"Failed to initialize schema for '{db_name}': {e}") from e


async def drop_merchant_database(db_name: str) -> None:
    """
    Drop a merchant's dedicated PostgreSQL database.
    Disposes active connection pools first, then drops with FORCE.
    """
    logger.info(f"Dropping database '{db_name}'...")

    # Step 1: Dispose tenant engine if cached to close connections
    if db_name in _tenant_engines:
        try:
            await _tenant_engines[db_name].dispose()
        except Exception as e:
            logger.warning(f"Error disposing engine for '{db_name}': {e}")
        _tenant_engines.pop(db_name, None)
        _tenant_sessionmakers.pop(db_name, None)

    # Step 2: Connect to admin DB and drop with FORCE
    admin_url = settings.get_admin_db_url()
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")

    try:
        async with admin_engine.connect() as conn:
            safe_db_name = db_name.replace('"', '""')
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{safe_db_name}" WITH (FORCE)'))
            logger.info(f"Database '{safe_db_name}' dropped successfully.")
    except Exception as e:
        logger.error(f"Error dropping database '{db_name}': {e}", exc_info=True)
        raise RuntimeError(f"Failed to drop database '{db_name}': {e}") from e
    finally:
        await admin_engine.dispose()



