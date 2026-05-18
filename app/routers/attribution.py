"""Attribution reporting routes — authenticated, workspace-scoped."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.dependencies import CurrentUser, DbSession
from app.models.attribution import Attribution, TouchType
from app.models.contact import Contact
from app.models.deal import Deal
from app.services.attribution_service import (
    get_cac_report,
    get_campaign_report,
    get_contact_chain,
    get_deal_chain,
    get_funnel_report,
    get_source_report,
)

router = APIRouter(prefix="/attribution", tags=["attribution"])


class AttributionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contact_id: UUID
    deal_id: UUID | None
    session_id: UUID | None
    touch_type: TouchType
    source: str | None
    campaign: str | None
    medium: str | None
    content: str | None
    term: str | None
    landing_page_url: str | None
    referrer_url: str | None
    gclid: str | None
    fbclid: str | None
    occurred_at: datetime


async def _ensure_contact(db: DbSession, contact_id: UUID, workspace_id: UUID) -> None:
    result = await db.execute(
        select(Contact.id).where(
            Contact.id == contact_id,
            Contact.workspace_id == workspace_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found"
        )


async def _ensure_deal(db: DbSession, deal_id: UUID, workspace_id: UUID) -> None:
    result = await db.execute(
        select(Deal.id).where(
            Deal.id == deal_id,
            Deal.workspace_id == workspace_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found"
        )


@router.get("/contacts/{contact_id}", response_model=list[AttributionRead])
async def contact_attribution_chain(
    contact_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> list[Attribution]:
    """Full attribution chain for a contact, chronologically."""
    await _ensure_contact(db, contact_id, current_user.workspace_id)
    return await get_contact_chain(
        db,
        workspace_id=current_user.workspace_id,
        contact_id=contact_id,
    )


@router.get("/deals/{deal_id}", response_model=list[AttributionRead])
async def deal_attribution_chain(
    deal_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> list[Attribution]:
    """Attribution chain for a deal — every touchpoint contributing to close."""
    await _ensure_deal(db, deal_id, current_user.workspace_id)
    return await get_deal_chain(
        db,
        workspace_id=current_user.workspace_id,
        deal_id=deal_id,
    )


@router.get("/report/by-source")
async def report_by_source(
    db: DbSession,
    current_user: CurrentUser,
    start_date: Annotated[datetime | None, Query()] = None,
    end_date: Annotated[datetime | None, Query()] = None,
) -> list[dict[str, Any]]:
    """Aggregate: leads, deals, revenue by `source` over an optional date range."""
    return await get_source_report(
        db,
        workspace_id=current_user.workspace_id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/report/by-campaign")
async def report_by_campaign(
    db: DbSession,
    current_user: CurrentUser,
    start_date: Annotated[datetime | None, Query()] = None,
    end_date: Annotated[datetime | None, Query()] = None,
) -> list[dict[str, Any]]:
    """Same aggregation as by-source, grouped by `utm_campaign`."""
    return await get_campaign_report(
        db,
        workspace_id=current_user.workspace_id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/report/funnel")
async def report_funnel(
    db: DbSession,
    current_user: CurrentUser,
    start_date: Annotated[datetime | None, Query()] = None,
    end_date: Annotated[datetime | None, Query()] = None,
) -> dict[str, Any]:
    """Funnel counts + conversion rates: pageviews → sessions → leads → deals → won."""
    return await get_funnel_report(
        db,
        workspace_id=current_user.workspace_id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/report/cac")
async def report_cac(
    db: DbSession,
    current_user: CurrentUser,
    ad_spend_cents: Annotated[int, Query(ge=0)] = 0,
    start_date: Annotated[datetime | None, Query()] = None,
    end_date: Annotated[datetime | None, Query()] = None,
) -> list[dict[str, Any]]:
    """CAC by source — uses the provided ad_spend_cents as the period total."""
    return await get_cac_report(
        db,
        workspace_id=current_user.workspace_id,
        ad_spend_cents=ad_spend_cents,
        start_date=start_date,
        end_date=end_date,
    )
