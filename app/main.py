"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import engine
from app.middleware import WorkspaceContextMiddleware
from app.routers import auth, health, workspaces


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application startup/shutdown hooks."""
    yield
    await engine.dispose()


app = FastAPI(
    title="APEX",
    description="AI-Powered CRM Platform — Salesforce alternative for NetSuite shops.",
    version=settings.VERSION,
    lifespan=lifespan,
)

app.add_middleware(WorkspaceContextMiddleware)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(workspaces.router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": "apex", "version": settings.VERSION, "docs": "/docs"}
