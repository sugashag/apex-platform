"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import engine
from app.middleware import WorkspaceContextMiddleware
from app.routers import (
    activities,
    assignment_rules,
    auth,
    calls,
    companies,
    contacts,
    deals,
    health,
    inbox,
    leads,
    messages,
    pipeline_stages,
    sms,
    webhooks_resend,
    webhooks_twilio,
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

# Communications routes (Phase 2) — versioned under /api/v1.
app.include_router(inbox.router, prefix=API_V1_PREFIX)
app.include_router(messages.router, prefix=API_V1_PREFIX)
app.include_router(calls.router, prefix=API_V1_PREFIX)
app.include_router(sms.router, prefix=API_V1_PREFIX)
app.include_router(assignment_rules.router, prefix=API_V1_PREFIX)

# Webhooks live outside /api/v1 so external providers hit a stable path.
app.include_router(webhooks_twilio.router)
app.include_router(webhooks_resend.router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": "apex", "version": settings.VERSION, "docs": "/docs"}
