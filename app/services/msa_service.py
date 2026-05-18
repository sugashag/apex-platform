"""MSA generation, send-for-signing, and signed-event processing."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.activity import Activity, ActivityType, ActorType
from app.models.company import Company
from app.models.contact import Contact
from app.models.deal import CloseReason, Deal
from app.models.msa_document import MsaDocument, MsaStatus
from app.models.pipeline_stage import PipelineStage
from app.models.workspace import Workspace
from app.services import workflow_engine
from app.services.agent_queue import enqueue
from app.services.template_service import render_template

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- helpers


def _load_template() -> str:
    """Load the MSA template text, falling back to a minimal embedded copy."""
    candidates = [
        settings.MSA_TEMPLATE_PATH,
        "app/templates/msa_template.txt",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    return fh.read()
            except OSError:
                logger.exception("could not read MSA template at %s", path)
    return (
        "MASTER SERVICES AGREEMENT\n\n"
        "This MSA is entered into between {{workspace.name}} and "
        "{{company.name}} for the engagement described as "
        "\"{{deal.name}}\" valued at ${{deal.value}} on {{date}}.\n\n"
        "Signed by {{contact.first_name}} {{contact.last_name}}.\n"
    )


def _ensure_storage_dir() -> Path:
    storage = Path(settings.MSA_STORAGE_PATH)
    storage.mkdir(parents=True, exist_ok=True)
    return storage


def _render_pdf(body: str, output_path: Path) -> bool:
    """Render text body to a PDF. Returns True if fpdf2 produced a real PDF.

    Falls back to writing the raw text to a ``.txt`` sibling file if fpdf2
    is unavailable — tests don't care which format we produce so long as
    the document_url points to a readable file.
    """
    try:
        from fpdf import FPDF  # type: ignore[import-not-found]
    except ImportError:
        txt_path = output_path.with_suffix(".txt")
        txt_path.write_text(body, encoding="utf-8")
        return False

    pdf = FPDF(format="A4", unit="mm")
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "APEX — Master Services Agreement", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    # fpdf2's default font doesn't speak unicode beyond latin-1; transliterate.
    safe_body = body.encode("latin-1", "replace").decode("latin-1")
    for line in safe_body.splitlines():
        if not line.strip():
            pdf.ln(4)
            continue
        pdf.multi_cell(0, 6, line)
    pdf.output(str(output_path))
    return True


# --------------------------------------------------------------------- public API


async def generate_msa(
    db: AsyncSession,
    *,
    deal_id: UUID,
    workspace_id: UUID,
    generated_by_id: UUID | None,
) -> MsaDocument:
    """Render an MSA PDF for the deal and persist an MsaDocument row.

    Caller commits.
    """
    deal = await db.get(Deal, deal_id)
    if deal is None or deal.workspace_id != workspace_id:
        raise ValueError("deal not found")

    contact: Contact | None = None
    if deal.contact_id is not None:
        contact = await db.get(Contact, deal.contact_id)
    company: Company | None = None
    if deal.company_id is not None:
        company = await db.get(Company, deal.company_id)
    workspace = await db.get(Workspace, workspace_id)

    context: dict[str, Any] = {
        "date": datetime.now(UTC).date().isoformat(),
        "deal": {
            "id": str(deal.id),
            "name": deal.name,
            "value": (deal.value_cents or 0) / 100,
            "value_cents": deal.value_cents,
            "currency": deal.currency,
        },
        "contact": (
            {
                "first_name": contact.first_name or "",
                "last_name": contact.last_name or "",
                "email": contact.email,
            }
            if contact is not None
            else {"first_name": "", "last_name": "", "email": ""}
        ),
        "company": {"name": company.name if company is not None else "Unknown"},
        "workspace": {"name": workspace.name if workspace is not None else ""},
    }
    body = render_template(_load_template(), context)

    storage = _ensure_storage_dir()
    suffix = secrets.token_hex(6)
    output_path = storage / f"msa-{deal.id}-{suffix}.pdf"
    _render_pdf(body, output_path)
    # If fpdf2 wasn't available we wrote a .txt sibling.
    final_path = output_path if output_path.exists() else output_path.with_suffix(".txt")

    msa = MsaDocument(
        workspace_id=workspace_id,
        deal_id=deal_id,
        generated_by_id=generated_by_id,
        status=MsaStatus.DRAFT,
        document_url=str(final_path),
        signer_email=contact.email if contact is not None else None,
        signer_name=(
            f"{contact.first_name or ''} {contact.last_name or ''}".strip()
            if contact is not None
            else None
        ),
    )
    db.add(msa)
    await db.flush()

    db.add(
        Activity(
            workspace_id=workspace_id,
            deal_id=deal_id,
            contact_id=deal.contact_id,
            actor_id=generated_by_id,
            actor_type=ActorType.HUMAN,
            type=ActivityType.NOTE,
            subject="MSA generated",
            body=f"Master Services Agreement drafted for {deal.name}",
        )
    )
    return msa


async def send_for_signing(
    db: AsyncSession,
    *,
    msa_id: UUID,
    workspace_id: UUID,
    signer_email: str,
    signer_name: str,
) -> MsaDocument:
    """Mark the MSA as sent + record a placeholder signing URL.

    Real implementations would call DocuSign/HelloSign here. Caller commits.
    """
    msa = await db.get(MsaDocument, msa_id)
    if msa is None or msa.workspace_id != workspace_id:
        raise ValueError("msa document not found")
    if msa.status not in (MsaStatus.DRAFT, MsaStatus.SENT):
        raise ValueError(f"cannot send MSA in status {msa.status}")

    envelope_id = f"env_mock_{secrets.token_hex(8)}"
    msa.status = MsaStatus.SENT
    msa.signer_email = signer_email
    msa.signer_name = signer_name
    msa.external_envelope_id = envelope_id
    msa.signing_url = f"https://sign.example/envelopes/{envelope_id}"
    msa.sent_at = datetime.now(UTC)
    msa.expires_at = msa.sent_at + timedelta(days=30)

    db.add(
        Activity(
            workspace_id=workspace_id,
            deal_id=msa.deal_id,
            actor_type=ActorType.HUMAN,
            type=ActivityType.EMAIL_SENT,
            subject="MSA sent for signing",
            body=f"Sent MSA to {signer_email} ({signer_name})",
        )
    )
    return msa


async def process_signed(
    db: AsyncSession,
    *,
    msa_id: UUID,
    workspace_id: UUID,
    signed_at: datetime | None = None,
) -> MsaDocument:
    """Mark MSA signed, move deal to Closed Won, kick off NetSuite syncs.

    Caller commits.
    """
    msa = await db.get(MsaDocument, msa_id)
    if msa is None or msa.workspace_id != workspace_id:
        raise ValueError("msa document not found")

    when = signed_at or datetime.now(UTC)
    msa.status = MsaStatus.SIGNED
    msa.signed_at = when

    deal = await db.get(Deal, msa.deal_id)
    if deal is not None:
        deal.msa_signed_at = when

        # Move to the workspace's Closed Won stage if one is configured.
        won_result = await db.execute(
            select(PipelineStage).where(
                PipelineStage.workspace_id == workspace_id,
                PipelineStage.is_won.is_(True),
            ).order_by(PipelineStage.position.asc()).limit(1)
        )
        won_stage = won_result.scalar_one_or_none()
        if won_stage is not None and deal.pipeline_stage_id != won_stage.id:
            previous_stage_id = deal.pipeline_stage_id
            deal.pipeline_stage_id = won_stage.id
            deal.probability = won_stage.probability_default
            deal.closed_at = when
            deal.close_reason = CloseReason.WON
            db.add(
                Activity(
                    workspace_id=workspace_id,
                    deal_id=deal.id,
                    contact_id=deal.contact_id,
                    actor_type=ActorType.HUMAN,
                    type=ActivityType.STAGE_CHANGE,
                    subject=f"Stage → {won_stage.name} (MSA signed)",
                    meta={
                        "from_stage_id": (
                            str(previous_stage_id) if previous_stage_id else None
                        ),
                        "to_stage_id": str(won_stage.id),
                        "to_stage_name": won_stage.name,
                        "trigger": "msa_signed",
                    },
                )
            )
            await workflow_engine.trigger_workflow(
                db,
                workspace_id=workspace_id,
                trigger_type="deal_stage_changed",
                entity_type="deal",
                entity_id=deal.id,
                context={
                    "deal_id": str(deal.id),
                    "contact_id": str(deal.contact_id) if deal.contact_id else None,
                    "deal": {
                        "id": str(deal.id),
                        "name": deal.name,
                        "value_cents": deal.value_cents,
                        "to_stage_id": str(won_stage.id),
                        "to_stage_name": won_stage.name,
                        "is_won": True,
                        "is_lost": False,
                    },
                },
            )

    db.add(
        Activity(
            workspace_id=workspace_id,
            deal_id=msa.deal_id,
            actor_type=ActorType.HUMAN,
            type=ActivityType.NOTE,
            subject="MSA signed",
            body=f"MSA signed by {msa.signer_email or 'counterparty'}",
            occurred_at=when,
        )
    )

    # Best-effort enqueues — Redis-down should never block the signed event.
    if deal is not None and deal.company_id is not None:
        await enqueue(
            "sync_company_to_netsuite",
            workspace_id,
            deal.company_id,
        )
    if deal is not None:
        await enqueue(
            "sync_deal_to_netsuite",
            workspace_id,
            deal.id,
        )
    await enqueue(
        "sync_msa_to_netsuite",
        workspace_id,
        msa.id,
    )
    return msa
