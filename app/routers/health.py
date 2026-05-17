"""Health check endpoint."""

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.database import engine

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, Any]:
    """Liveness + DB connectivity check."""
    db_status = "connected"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_status = "disconnected"

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "database": db_status,
    }
