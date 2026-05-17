"""HTTP routers."""

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

__all__ = [
    "activities",
    "auth",
    "companies",
    "contacts",
    "deals",
    "health",
    "leads",
    "pipeline_stages",
    "workspaces",
]
