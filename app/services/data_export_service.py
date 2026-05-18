"""Workspace data export helpers — contacts, deals, activities as CSV.

These functions return CSV strings ready to be served as ``text/csv`` or
bundled into a ZIP for a full workspace export.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.contact import Contact
from app.models.deal import Deal


def _to_iso(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _cents_to_dollars(value: int | None) -> str:
    if value is None:
        return ""
    return f"{value / 100:.2f}"


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _write_rows(headers: list[str], rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({h: _stringify(row.get(h)) for h in headers})
    return buffer.getvalue()


async def export_contacts_csv(db: AsyncSession, workspace_id: UUID) -> str:
    """Return CSV of all contacts in the workspace, including soft-deleted."""
    result = await db.execute(
        select(Contact)
        .where(Contact.workspace_id == workspace_id)
        .order_by(Contact.created_at.asc())
    )
    contacts = result.scalars().all()

    headers = [
        "id",
        "email",
        "first_name",
        "last_name",
        "phone",
        "title",
        "company_id",
        "owner_id",
        "source",
        "source_campaign",
        "source_medium",
        "lead_score",
        "email_status",
        "is_active",
        "created_at",
        "updated_at",
    ]
    rows = [
        {
            "id": str(c.id),
            "email": c.email,
            "first_name": c.first_name,
            "last_name": c.last_name,
            "phone": c.phone,
            "title": c.title,
            "company_id": str(c.company_id) if c.company_id else "",
            "owner_id": str(c.owner_id) if c.owner_id else "",
            "source": c.source,
            "source_campaign": c.source_campaign,
            "source_medium": c.source_medium,
            "lead_score": c.lead_score,
            "email_status": c.email_status.value,
            "is_active": c.is_active,
            "created_at": _to_iso(c.created_at),
            "updated_at": _to_iso(c.updated_at),
        }
        for c in contacts
    ]
    return _write_rows(headers, rows)


async def export_deals_csv(db: AsyncSession, workspace_id: UUID) -> str:
    """Return CSV of all deals with stage, value, and attribution-style fields."""
    result = await db.execute(
        select(Deal)
        .where(Deal.workspace_id == workspace_id)
        .order_by(Deal.created_at.asc())
    )
    deals = result.scalars().all()

    headers = [
        "id",
        "name",
        "value_dollars",
        "currency",
        "probability",
        "pipeline_stage_id",
        "contact_id",
        "company_id",
        "owner_id",
        "expected_close_date",
        "closed_at",
        "close_reason",
        "msa_signed_at",
        "first_payment_at",
        "is_active",
        "created_at",
        "updated_at",
    ]
    rows = [
        {
            "id": str(d.id),
            "name": d.name,
            "value_dollars": _cents_to_dollars(d.value_cents),
            "currency": d.currency,
            "probability": d.probability,
            "pipeline_stage_id": (
                str(d.pipeline_stage_id) if d.pipeline_stage_id else ""
            ),
            "contact_id": str(d.contact_id) if d.contact_id else "",
            "company_id": str(d.company_id) if d.company_id else "",
            "owner_id": str(d.owner_id) if d.owner_id else "",
            "expected_close_date": (
                d.expected_close_date.isoformat() if d.expected_close_date else ""
            ),
            "closed_at": _to_iso(d.closed_at),
            "close_reason": d.close_reason.value if d.close_reason else "",
            "msa_signed_at": _to_iso(d.msa_signed_at),
            "first_payment_at": _to_iso(d.first_payment_at),
            "is_active": d.is_active,
            "created_at": _to_iso(d.created_at),
            "updated_at": _to_iso(d.updated_at),
        }
        for d in deals
    ]
    return _write_rows(headers, rows)


async def export_activities_csv(db: AsyncSession, workspace_id: UUID) -> str:
    """Return CSV of all activities in the workspace."""
    result = await db.execute(
        select(Activity)
        .where(Activity.workspace_id == workspace_id)
        .order_by(Activity.occurred_at.asc())
    )
    activities = result.scalars().all()

    headers = [
        "id",
        "type",
        "actor_type",
        "actor_id",
        "contact_id",
        "deal_id",
        "lead_id",
        "subject",
        "body",
        "occurred_at",
        "created_at",
    ]
    rows = [
        {
            "id": str(a.id),
            "type": a.type.value,
            "actor_type": a.actor_type.value,
            "actor_id": str(a.actor_id) if a.actor_id else "",
            "contact_id": str(a.contact_id) if a.contact_id else "",
            "deal_id": str(a.deal_id) if a.deal_id else "",
            "lead_id": str(a.lead_id) if a.lead_id else "",
            "subject": a.subject,
            "body": a.body,
            "occurred_at": _to_iso(a.occurred_at),
            "created_at": _to_iso(a.created_at),
        }
        for a in activities
    ]
    return _write_rows(headers, rows)


async def generate_full_export(
    db: AsyncSession, workspace_id: UUID
) -> dict[str, str]:
    """Return a mapping of ``filename -> CSV contents`` for every export."""
    return {
        "contacts.csv": await export_contacts_csv(db, workspace_id),
        "deals.csv": await export_deals_csv(db, workspace_id),
        "activities.csv": await export_activities_csv(db, workspace_id),
    }


def bundle_zip(files: dict[str, str]) -> bytes:
    """Pack a ``{filename: csv}`` mapping into a ZIP archive."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files.items():
            zf.writestr(filename, content)
    return buffer.getvalue()


__all__ = [
    "bundle_zip",
    "export_activities_csv",
    "export_contacts_csv",
    "export_deals_csv",
    "generate_full_export",
]
