"""Merchant Backend — FastAPI application entry point."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routes.catalog import router as catalog_router
from app.routes.merchants import router as merchants_router

app = FastAPI(
    title="Commerce Agent — Merchant Backend",
    description="Merchant-facing API for catalog management (CSV upload, product CRUD).",
    version="0.1.0",
)

# CORS — allow both frontends and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(catalog_router)
app.include_router(merchants_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "merchant-backend"}


# Serve static frontend files (MUST be last — catches all unmatched routes)
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
