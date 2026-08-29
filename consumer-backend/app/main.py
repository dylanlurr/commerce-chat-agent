"""Consumer Backend — FastAPI application entry point."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routes.chat import router as chat_router

app = FastAPI(
    title="Commerce Agent — Consumer Backend",
    description="Consumer-facing API for AI shopping assistant chat.",
    version="0.1.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(chat_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "consumer-backend"}


# Serve static frontend files (MUST be last — catches all unmatched routes)
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
