"""HTTP routers."""

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
    health,
    inbox,
    leads,
    messages,
    pipeline_stages,
    sms,
    tracking,
    workspaces,
)
from app.routers.webhooks import posthog as webhooks_posthog
from app.routers.webhooks import resend as webhooks_resend
from app.routers.webhooks import twilio as webhooks_twilio

__all__ = [
    "activities",
    "agents",
    "assignment_rules",
    "attribution",
    "auth",
    "calls",
    "companies",
    "contacts",
    "deals",
    "drafts",
    "health",
    "inbox",
    "leads",
    "messages",
    "pipeline_stages",
    "sms",
    "tracking",
    "webhooks_posthog",
    "webhooks_resend",
    "webhooks_twilio",
    "workspaces",
]
