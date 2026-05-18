"""Sequence enrollment, due-step processing, and exit-on-reply tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models.sequence_enrollment import (
    SequenceEnrollment,
    SequenceEnrollmentStatus,
)
from app.services import sequence_service
from tests.helpers import register_workspace

API = "/api/v1"


async def _new_contact(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        f"{API}/contacts",
        headers=headers,
        json={
            "email": f"c-{uuid.uuid4().hex[:6]}@example.com",
            "first_name": "Pat",
            "phone": "+15551234567",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_sequence(
    client: AsyncClient, headers: dict[str, str], *, delay_days: int = 0
) -> str:
    resp = await client.post(
        f"{API}/sequences",
        headers=headers,
        json={
            "name": f"Seq {uuid.uuid4().hex[:6]}",
            "steps": [
                {
                    "position": 0,
                    "step_type": "email",
                    "delay_days": delay_days,
                    "subject_template": "Hi {{contact.first_name}}",
                    "body_template": "Hey there",
                },
                {
                    "position": 1,
                    "step_type": "email",
                    "delay_days": 2,
                    "subject_template": "Follow up",
                    "body_template": "Still around?",
                },
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_create_and_get_sequence(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    sid = await _create_sequence(client, ws.headers)
    resp = await client.get(f"{API}/sequences/{sid}", headers=ws.headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["steps"]) == 2
    assert body["enrollment_count"] == 0


async def test_enroll_contact_creates_enrollment(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    sid = await _create_sequence(client, ws.headers)
    contact_id = await _new_contact(client, ws.headers)
    resp = await client.post(
        f"{API}/sequences/{sid}/enroll",
        headers=ws.headers,
        json={"contact_ids": [contact_id]},
    )
    assert resp.status_code == 201, resp.text
    enrollments = resp.json()
    assert len(enrollments) == 1
    assert enrollments[0]["status"] == "active"
    assert enrollments[0]["current_step"] == 0


async def test_duplicate_enrollment_silently_skipped(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    sid = await _create_sequence(client, ws.headers)
    contact_id = await _new_contact(client, ws.headers)

    first = await client.post(
        f"{API}/sequences/{sid}/enroll",
        headers=ws.headers,
        json={"contact_ids": [contact_id]},
    )
    assert first.status_code == 201
    assert len(first.json()) == 1

    second = await client.post(
        f"{API}/sequences/{sid}/enroll",
        headers=ws.headers,
        json={"contact_ids": [contact_id]},
    )
    assert second.status_code == 201
    assert second.json() == []


async def test_process_due_steps_advances_cursor(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    sid = await _create_sequence(client, ws.headers, delay_days=0)
    contact_id = await _new_contact(client, ws.headers)
    await client.post(
        f"{API}/sequences/{sid}/enroll",
        headers=ws.headers,
        json={"contact_ids": [contact_id]},
    )

    async with SessionLocal() as db:
        result = await db.execute(
            select(SequenceEnrollment).where(
                SequenceEnrollment.sequence_id == sid
            )
        )
        enrollment = result.scalar_one()
        # Coerce next_step_at into the past so it's due.
        enrollment.next_step_at = datetime.now(UTC)
        await db.commit()

        count = await sequence_service.process_due_steps(db)
        await db.commit()

        refreshed = await db.get(SequenceEnrollment, enrollment.id)

    assert count == 1
    assert refreshed is not None
    assert refreshed.current_step == 1
    assert refreshed.status == SequenceEnrollmentStatus.ACTIVE


async def test_exit_on_reply_stops_active_enrollment(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    sid = await _create_sequence(client, ws.headers)
    contact_id = await _new_contact(client, ws.headers)
    await client.post(
        f"{API}/sequences/{sid}/enroll",
        headers=ws.headers,
        json={"contact_ids": [contact_id]},
    )

    async with SessionLocal() as db:
        exited = await sequence_service.exit_on_reply(db, uuid.UUID(contact_id))
        await db.commit()

    assert exited == 1

    listed = await client.get(
        f"{API}/sequences/{sid}/enrollments", headers=ws.headers
    )
    assert listed.status_code == 200
    items = listed.json()
    assert items[0]["status"] == "exited_reply"


async def test_manual_exit_endpoint(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    sid = await _create_sequence(client, ws.headers)
    contact_id = await _new_contact(client, ws.headers)
    enroll = await client.post(
        f"{API}/sequences/{sid}/enroll",
        headers=ws.headers,
        json={"contact_ids": [contact_id]},
    )
    enrollment_id = enroll.json()[0]["id"]

    exit_resp = await client.post(
        f"{API}/sequences/enrollments/{enrollment_id}/exit", headers=ws.headers
    )
    assert exit_resp.status_code == 200
    assert exit_resp.json()["status"] == "exited_manual"


async def test_completed_sequence_marked_completed(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    # Single-step sequence — after processing the only step the enrollment
    # should land in 'completed', not 'active'.
    resp = await client.post(
        f"{API}/sequences",
        headers=ws.headers,
        json={
            "name": "OneShot",
            "steps": [
                {
                    "position": 0,
                    "step_type": "email",
                    "delay_days": 0,
                    "subject_template": "Hello",
                    "body_template": "Yo",
                }
            ],
        },
    )
    sid = resp.json()["id"]
    contact_id = await _new_contact(client, ws.headers)
    await client.post(
        f"{API}/sequences/{sid}/enroll",
        headers=ws.headers,
        json={"contact_ids": [contact_id]},
    )

    async with SessionLocal() as db:
        enrollment = (
            await db.execute(
                select(SequenceEnrollment).where(
                    SequenceEnrollment.sequence_id == sid
                )
            )
        ).scalar_one()
        enrollment.next_step_at = datetime.now(UTC)
        await db.commit()

        await sequence_service.process_due_steps(db)
        await db.commit()
        refreshed = await db.get(SequenceEnrollment, enrollment.id)

    assert refreshed is not None
    assert refreshed.status == SequenceEnrollmentStatus.COMPLETED
