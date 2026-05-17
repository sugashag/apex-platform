"""HTTP routers."""

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
    workspaces,
)
from app.routers.webhooks import resend as webhooks_resend
from app.routers.webhooks import twilio as webhooks_twilio

__all__ = [
    "activities",
    "assignment_rules",
    "auth",
    "calls",
    "companies",
    "contacts",
    "deals",
    "health",
    "inbox",
    "leads",
    "messages",
    "pipeline_stages",
    "sms",
    "webhooks_resend",
    "webhooks_twilio",
    "workspaces",
]
