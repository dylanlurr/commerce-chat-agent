"""Application settings loaded from environment variables."""

import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load .env from project root
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


class Settings(BaseSettings):
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://dylan.lorrenzo@localhost:5432/commerce_agent",
    )
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    merchant_backend_url: str = os.getenv(
        "MERCHANT_BACKEND_URL", "http://localhost:8000"
    )
    consumer_backend_url: str = os.getenv(
        "CONSUMER_BACKEND_URL", "http://localhost:8001"
    )

    def get_tenant_db_url(self, db_name: str) -> str:
        """Construct an async PostgreSQL URL for a specific tenant database."""
        parsed = urlparse(self.database_url)
        # Replace the database path with the tenant's database name
        return urlunparse(parsed._replace(path=f"/{db_name}"))

    def get_admin_db_url(self) -> str:
        """Construct an async PostgreSQL URL connecting to the default 'postgres' database."""
        parsed = urlparse(self.database_url)
        return urlunparse(parsed._replace(path="/postgres"))


settings = Settings()
