"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import engine
from app.middleware import WorkspaceContextMiddleware
from app.routers import (
    activities,
    auth,
    companies,
    contacts,
    deals,
    health,
    leads,
    pipeline_stages,
    workspaces,
)

API_V1_PREFIX = "/api/v1"


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

# Platform routes — kept unversioned for now.
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(workspaces.router)

# CRM routes — versioned under /api/v1.
app.include_router(companies.router, prefix=API_V1_PREFIX)
app.include_router(contacts.router, prefix=API_V1_PREFIX)
app.include_router(pipeline_stages.router, prefix=API_V1_PREFIX)
app.include_router(deals.router, prefix=API_V1_PREFIX)
app.include_router(leads.router, prefix=API_V1_PREFIX)
app.include_router(activities.router, prefix=API_V1_PREFIX)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": "apex", "version": settings.VERSION, "docs": "/docs"}
