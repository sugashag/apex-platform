"""AI draft review + send endpoints — nothing auto-sends."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.dependencies import CurrentUser, DbSession
from app.models.ai_draft import AiDraft, AiDraftStatus, AiDraftType
from app.models.contact import Contact
from app.models.thread import Thread
from app.schemas.ai_draft import (
    AiDraftListResponse,
    AiDraftResponse,
    DraftEditAndSendRequest,
)
from app.services.email_service import email_service
from app.utils.pagination import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/drafts", tags=["drafts"])


async def _load_draft(
    db: DbSession, draft_id: UUID, workspace_id: UUID
) -> AiDraft:
    draft = (
        await db.execute(
            select(AiDraft).where(
                AiDraft.id == draft_id,
                AiDraft.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found"
        )
    return draft


def _ensure_pending(draft: AiDraft) -> None:
    if draft.status != AiDraftStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Draft is {draft.status.value}, not pending",
        )


@router.get("", response_model=AiDraftListResponse)
async def list_drafts(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    draft_type: Annotated[AiDraftType | None, Query()] = None,
    status_filter: Annotated[
        AiDraftStatus | None, Query(alias="status")
    ] = AiDraftStatus.PENDING,
    entity_id: UUID | None = None,
) -> PaginatedResponse[AiDraftResponse]:
    stmt = select(AiDraft).where(
        AiDraft.workspace_id == current_user.workspace_id
    )
    if draft_type is not None:
        stmt = stmt.where(AiDraft.draft_type == draft_type)
    if status_filter is not None:
        stmt = stmt.where(AiDraft.status == status_filter)
    if entity_id is not None:
        stmt = stmt.where(AiDraft.entity_id == entity_id)

    total = int(
        (await db.execute(select(func.count()).select_from(stmt.subquery())))
        .scalar_one()
    )
    stmt = (
        stmt.order_by(AiDraft.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    rows = [
        AiDraftResponse.model_validate(d)
        for d in (await db.execute(stmt)).scalars().all()
    ]
    return PaginatedResponse.build(items=rows, total=total, params=pagination)


@router.get("/{draft_id}", response_model=AiDraftResponse)
async def get_draft(
    draft_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> AiDraftResponse:
    draft = await _load_draft(db, draft_id, current_user.workspace_id)
    return AiDraftResponse.model_validate(draft)


async def _send_draft(
    db: DbSession,
    draft: AiDraft,
    actor_id: UUID,
) -> None:
    """Send the draft via the email service (no-op for non-email drafts).

    Recipient resolution:
    - email_reply → reply on the original thread
    - outbound_email → start a new thread with the contact
    """
    if draft.draft_type not in (AiDraftType.EMAIL_REPLY, AiDraftType.OUTBOUND_EMAIL):
        return

    if draft.draft_type == AiDraftType.EMAIL_REPLY:
        if draft.entity_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reply draft missing thread reference",
            )
        thread = (
            await db.execute(
                select(Thread).where(
                    Thread.id == draft.entity_id,
                    Thread.workspace_id == draft.workspace_id,
                )
            )
        ).scalar_one_or_none()
        if thread is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Original thread not found",
            )
        contact = None
        if thread.contact_id is not None:
            contact = (
                await db.execute(
                    select(Contact).where(Contact.id == thread.contact_id)
                )
            ).scalar_one_or_none()
        if contact is None or not contact.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot send — thread has no contact email",
            )
        to_emails = [contact.email]
    else:
        if draft.entity_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Outbound draft missing contact reference",
            )
        contact = (
            await db.execute(
                select(Contact).where(
                    Contact.id == draft.entity_id,
                    Contact.workspace_id == draft.workspace_id,
                )
            )
        ).scalar_one_or_none()
        if contact is None or not contact.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Contact has no email address",
            )
        to_emails = [contact.email]
        thread = Thread(
            workspace_id=draft.workspace_id,
            contact_id=contact.id,
            subject=draft.subject,
        )
        db.add(thread)
        await db.flush()

    await email_service.send_message(
        db,
        thread=thread,
        body_text=draft.body_text,
        body_html=draft.body_html,
        from_account=None,
        actor_id=actor_id,
        to_emails=to_emails,
    )


@router.post("/{draft_id}/approve", response_model=AiDraftResponse)
async def approve_draft(
    draft_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> AiDraftResponse:
    draft = await _load_draft(db, draft_id, current_user.workspace_id)
    _ensure_pending(draft)

    await _send_draft(db, draft, current_user.id)

    draft.status = AiDraftStatus.APPROVED
    draft.reviewed_by_id = current_user.id
    draft.reviewed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(draft)
    return AiDraftResponse.model_validate(draft)


@router.post("/{draft_id}/edit-and-send", response_model=AiDraftResponse)
async def edit_and_send_draft(
    draft_id: UUID,
    payload: DraftEditAndSendRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> AiDraftResponse:
    draft = await _load_draft(db, draft_id, current_user.workspace_id)
    _ensure_pending(draft)

    if payload.subject is not None:
        draft.subject = payload.subject
    if payload.body_html is not None:
        draft.body_html = payload.body_html
    if payload.body_text is not None:
        draft.body_text = payload.body_text

    await _send_draft(db, draft, current_user.id)

    draft.status = AiDraftStatus.EDITED_AND_SENT
    draft.reviewed_by_id = current_user.id
    draft.reviewed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(draft)
    return AiDraftResponse.model_validate(draft)


@router.post("/{draft_id}/discard", response_model=AiDraftResponse)
async def discard_draft(
    draft_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> AiDraftResponse:
    draft = await _load_draft(db, draft_id, current_user.workspace_id)
    _ensure_pending(draft)

    draft.status = AiDraftStatus.DISCARDED
    draft.reviewed_by_id = current_user.id
    draft.reviewed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(draft)
    return AiDraftResponse.model_validate(draft)
