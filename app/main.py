"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import engine
from app.middleware import WorkspaceContextMiddleware
from app.routers import (
    activities,
    agents,
    assignment_rules,
    attribution,
    auth,
    calls,
    companies,
    contacts,
    deals,
    drafts,
    forecasts,
    health,
    inbox,
    leads,
    messages,
    pipeline_stages,
    reports,
    sequences,
    sms,
    tracking,
    webhooks_posthog,
    webhooks_resend,
    webhooks_twilio,
    workflows,
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

# AI layer (Phase 3) — versioned under /api/v1.
app.include_router(agents.router, prefix=API_V1_PREFIX)
app.include_router(drafts.router, prefix=API_V1_PREFIX)

# Attribution + Website Integration (Phase 4) — versioned under /api/v1.
app.include_router(attribution.router, prefix=API_V1_PREFIX)

# Automation + Workflows (Phase 5) — versioned under /api/v1.
app.include_router(workflows.router, prefix=API_V1_PREFIX)
app.include_router(workflows.runs_router, prefix=API_V1_PREFIX)
app.include_router(sequences.router, prefix=API_V1_PREFIX)
app.include_router(sequences.enrollments_router, prefix=API_V1_PREFIX)

# Intelligence + Reporting (Phase 6) — versioned under /api/v1.
app.include_router(reports.router, prefix=API_V1_PREFIX)
app.include_router(forecasts.router, prefix=API_V1_PREFIX)

# Public marketing-site tracking endpoints — UNVERSIONED so the JS snippet
# embedded on customers' marketing sites never needs to change when we ship
# a new API version. Auth is via the public tracking_token, not JWT.
app.include_router(tracking.router)

# Webhooks live outside /api/v1 so external providers hit a stable path.
app.include_router(webhooks_twilio.router)
app.include_router(webhooks_resend.router)
app.include_router(webhooks_posthog.router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": "apex", "version": settings.VERSION, "docs": "/docs"}
