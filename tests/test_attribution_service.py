"""Unit tests for attribution_service helpers.

Exercises the service functions directly against the DB session so we can
assert the lower-level behavior without going through the HTTP layer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models.attribution import Attribution, TouchType
from app.models.contact import Contact
from app.models.deal import CloseReason, Deal
from app.models.pipeline_stage import PipelineStage
from app.models.visitor_session import VisitorSession
from app.models.workspace import Workspace
from app.routers.tracking import _rate_limiter
from app.services.attribution_service import (
    create_attribution_from_session,
    get_funnel_report,
    link_deal_to_attributions,
    resolve_first_touch,
)
from tests.helpers import register_workspace


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    _rate_limiter.reset()


async def _workspace(client: AsyncClient) -> Workspace:
    ws = await register_workspace(client)
    async with SessionLocal() as session:
        result = await session.execute(
            select(Workspace).where(Workspace.slug == ws.workspace_slug)
        )
        return result.scalar_one()


async def test_resolve_first_touch_returns_none_when_absent(
    client: AsyncClient,
) -> None:
    workspace = await _workspace(client)
    async with SessionLocal() as session:
        contact = Contact(
            workspace_id=workspace.id,
            email=f"x-{uuid.uuid4().hex[:6]}@example.com",
        )
        session.add(contact)
        await session.commit()
        await session.refresh(contact)

        result = await resolve_first_touch(session, workspace.id, contact.id)
        assert result is None


async def test_create_attribution_from_session_copies_utm_fields(
    client: AsyncClient,
) -> None:
    workspace = await _workspace(client)
    async with SessionLocal() as session:
        contact = Contact(
            workspace_id=workspace.id,
            email=f"x-{uuid.uuid4().hex[:6]}@example.com",
        )
        session.add(contact)
        await session.flush()

        vs = VisitorSession(
            workspace_id=workspace.id,
            session_id=f"sid-{uuid.uuid4().hex[:8]}",
            source="google_ads",
            campaign="spring",
            medium="cpc",
            gclid="abc123",
            landing_page_url="https://acme.com/",
            first_seen_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
        )
        session.add(vs)
        await session.flush()

        attr = await create_attribution_from_session(
            session,
            workspace_id=workspace.id,
            contact_id=contact.id,
            session=vs,
            touch_type=TouchType.FIRST_TOUCH,
        )
        await session.commit()

        assert attr.source == "google_ads"
        assert attr.campaign == "spring"
        assert attr.gclid == "abc123"
        assert attr.session_id == vs.id
        assert attr.touch_type == TouchType.FIRST_TOUCH


async def test_link_deal_to_attributions_backfills_all_rows(
    client: AsyncClient,
) -> None:
    workspace = await _workspace(client)
    async with SessionLocal() as session:
        contact = Contact(
            workspace_id=workspace.id,
            email=f"x-{uuid.uuid4().hex[:6]}@example.com",
        )
        session.add(contact)
        await session.flush()

        # Stub pipeline stage so the deal is valid.
        stage = (
            await session.execute(
                select(PipelineStage).where(
                    PipelineStage.workspace_id == workspace.id
                ).limit(1)
            )
        ).scalar_one()

        deal = Deal(
            workspace_id=workspace.id,
            contact_id=contact.id,
            pipeline_stage_id=stage.id,
            name="D",
        )
        session.add(deal)
        await session.flush()

        # Two attributions, neither linked to the deal yet.
        for touch in (TouchType.FIRST_TOUCH, TouchType.LAST_TOUCH):
            session.add(
                Attribution(
                    workspace_id=workspace.id,
                    contact_id=contact.id,
                    touch_type=touch,
                    source="google_ads",
                    occurred_at=datetime.now(UTC),
                )
            )
        await session.commit()

        count = await link_deal_to_attributions(
            session,
            workspace_id=workspace.id,
            contact_id=contact.id,
            deal_id=deal.id,
        )
        await session.commit()
        assert count == 2

        rows = list(
            (
                await session.execute(
                    select(Attribution).where(Attribution.contact_id == contact.id)
                )
            ).scalars()
        )
        assert all(r.deal_id == deal.id for r in rows)


async def test_link_deal_does_not_overwrite_existing_deal_id(
    client: AsyncClient,
) -> None:
    workspace = await _workspace(client)
    async with SessionLocal() as session:
        contact = Contact(
            workspace_id=workspace.id,
            email=f"x-{uuid.uuid4().hex[:6]}@example.com",
        )
        session.add(contact)
        await session.flush()

        stage = (
            await session.execute(
                select(PipelineStage).where(
                    PipelineStage.workspace_id == workspace.id
                ).limit(1)
            )
        ).scalar_one()

        deal_a = Deal(
            workspace_id=workspace.id, contact_id=contact.id,
            pipeline_stage_id=stage.id, name="A",
        )
        deal_b = Deal(
            workspace_id=workspace.id, contact_id=contact.id,
            pipeline_stage_id=stage.id, name="B",
        )
        session.add_all([deal_a, deal_b])
        await session.flush()

        attr = Attribution(
            workspace_id=workspace.id,
            contact_id=contact.id,
            deal_id=deal_a.id,
            touch_type=TouchType.FIRST_TOUCH,
            occurred_at=datetime.now(UTC),
        )
        session.add(attr)
        await session.commit()

        count = await link_deal_to_attributions(
            session,
            workspace_id=workspace.id,
            contact_id=contact.id,
            deal_id=deal_b.id,
        )
        await session.commit()
        # Only NULL deal_id rows are affected — the one pre-set to deal_a stays.
        assert count == 0

        await session.refresh(attr)
        assert attr.deal_id == deal_a.id


async def test_funnel_report_computes_rates(client: AsyncClient) -> None:
    workspace = await _workspace(client)
    async with SessionLocal() as session:
        # Spin up two visitor sessions + two contacts + one won deal.
        for i in range(2):
            vs = VisitorSession(
                workspace_id=workspace.id,
                session_id=f"sid-{i}-{uuid.uuid4().hex[:6]}",
                first_seen_at=datetime.now(UTC),
                last_seen_at=datetime.now(UTC),
            )
            session.add(vs)
        await session.flush()

        stage = (
            await session.execute(
                select(PipelineStage).where(
                    PipelineStage.workspace_id == workspace.id, PipelineStage.is_won.is_(True)
                )
            )
        ).scalar_one()

        contact = Contact(
            workspace_id=workspace.id,
            email=f"f-{uuid.uuid4().hex[:6]}@example.com",
        )
        session.add(contact)
        await session.flush()

        deal = Deal(
            workspace_id=workspace.id,
            contact_id=contact.id,
            pipeline_stage_id=stage.id,
            name="F",
            close_reason=CloseReason.WON,
            closed_at=datetime.now(UTC),
        )
        session.add(deal)
        await session.commit()

        report = await get_funnel_report(
            session,
            workspace_id=workspace.id,
            start_date=datetime.now(UTC) - timedelta(days=1),
            end_date=datetime.now(UTC) + timedelta(days=1),
        )
        assert report["sessions"] >= 2
        assert report["won"] >= 1
        # All rates should be present, even if None.
        assert set(report["conversion_rates"].keys()) == {
            "pageview_to_session",
            "session_to_lead",
            "lead_to_deal",
            "deal_to_won",
        }
