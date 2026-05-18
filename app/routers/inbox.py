"""Shared inbox — list, view, assign, snooze, resolve, reply to threads."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import CurrentUser, DbSession
from app.models.contact import Contact
from app.models.email_account import EmailAccount
from app.models.message import Message, MessageDirection
from app.models.thread import Thread, ThreadStatus
from app.models.user import User
from app.schemas.message import MessageResponse
from app.schemas.thread import (
    ThreadAssign,
    ThreadCreate,
    ThreadDetailResponse,
    ThreadListResponse,
    ThreadReply,
    ThreadResponse,
    ThreadSnooze,
)
from app.services.email_service import email_service
from app.utils.pagination import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/inbox", tags=["inbox"])


async def _load_thread(
    db: AsyncSession, thread_id: UUID, workspace_id: UUID
) -> Thread:
    result = await db.execute(
        select(Thread).where(
            Thread.id == thread_id,
            Thread.workspace_id == workspace_id,
        )
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found"
        )
    return thread


async def _hydrate_thread(db: AsyncSession, thread: Thread) -> ThreadResponse:
    """Build a ThreadResponse with contact_name, assignee_name, counts."""
    contact_name: str | None = None
    if thread.contact_id is not None:
        c_result = await db.execute(
            select(Contact.first_name, Contact.last_name, Contact.email).where(
                Contact.id == thread.contact_id
            )
        )
        row = c_result.first()
        if row is not None:
            first, last, email = row
            parts = [p for p in (first, last) if p]
            contact_name = " ".join(parts) if parts else email

    assignee_name: str | None = None
    if thread.assignee_id is not None:
        u_result = await db.execute(
            select(User.first_name, User.last_name, User.email).where(
                User.id == thread.assignee_id
            )
        )
        row = u_result.first()
        if row is not None:
            first, last, email = row
            parts = [p for p in (first, last) if p]
            assignee_name = " ".join(parts) if parts else email

    count_result = await db.execute(
        select(func.count(), func.max(Message.sent_at)).where(
            Message.thread_id == thread.id
        )
    )
    count_row = count_result.first()
    msg_count = int(count_row[0]) if count_row else 0
    last_msg_at = count_row[1] if count_row else None

    base = ThreadResponse.model_validate(thread)
    return base.model_copy(
        update={
            "contact_name": contact_name,
            "assignee_name": assignee_name,
            "message_count": msg_count,
            "last_message_at": last_msg_at,
        }
    )


@router.get("", response_model=ThreadListResponse)
async def list_threads(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    status_filter: Annotated[ThreadStatus | None, Query(alias="status")] = None,
    assignee_id: UUID | None = None,
    contact_id: UUID | None = None,
    deal_id: UUID | None = None,
    search: Annotated[
        str | None,
        Query(description="Substring search across subject or contact name/email."),
    ] = None,
) -> PaginatedResponse[ThreadResponse]:
    stmt = select(Thread).where(Thread.workspace_id == current_user.workspace_id)
    if status_filter is not None:
        stmt = stmt.where(Thread.status == status_filter)
    if assignee_id is not None:
        stmt = stmt.where(Thread.assignee_id == assignee_id)
    if contact_id is not None:
        stmt = stmt.where(Thread.contact_id == contact_id)
    if deal_id is not None:
        stmt = stmt.where(Thread.deal_id == deal_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.outerjoin(Contact, Contact.id == Thread.contact_id).where(
            or_(
                Thread.subject.ilike(like),
                Contact.email.ilike(like),
                Contact.first_name.ilike(like),
                Contact.last_name.ilike(like),
            )
        )

    count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total = int(count_result.scalar_one())

    stmt = (
        stmt.order_by(Thread.updated_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    result = await db.execute(stmt)
    threads = list(result.scalars().all())
    items = [await _hydrate_thread(db, t) for t in threads]
    return PaginatedResponse.build(items=items, total=total, params=pagination)


@router.get("/{thread_id}", response_model=ThreadDetailResponse)
async def get_thread(
    thread_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> ThreadDetailResponse:
    thread = await _load_thread(db, thread_id, current_user.workspace_id)
    msgs_result = await db.execute(
        select(Message)
        .where(Message.thread_id == thread.id)
        .order_by(Message.created_at.asc())
    )
    messages = [MessageResponse.model_validate(m) for m in msgs_result.scalars().all()]
    hydrated = await _hydrate_thread(db, thread)
    return ThreadDetailResponse(
        **hydrated.model_dump(),
        messages=messages,
    )


@router.post("/{thread_id}/assign", response_model=ThreadResponse)
async def assign_thread(
    thread_id: UUID,
    payload: ThreadAssign,
    db: DbSession,
    current_user: CurrentUser,
) -> ThreadResponse:
    thread = await _load_thread(db, thread_id, current_user.workspace_id)
    if payload.assignee_id is not None:
        user_result = await db.execute(
            select(User).where(
                User.id == payload.assignee_id,
                User.workspace_id == current_user.workspace_id,
            )
        )
        if user_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Assignee must belong to the same workspace",
            )
    thread.assignee_id = payload.assignee_id
    await db.commit()
    await db.refresh(thread)
    return await _hydrate_thread(db, thread)


@router.post("/{thread_id}/resolve", response_model=ThreadResponse)
async def resolve_thread(
    thread_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> ThreadResponse:
    thread = await _load_thread(db, thread_id, current_user.workspace_id)
    thread.status = ThreadStatus.RESOLVED
    thread.resolved_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(thread)
    return await _hydrate_thread(db, thread)


@router.post("/{thread_id}/reopen", response_model=ThreadResponse)
async def reopen_thread(
    thread_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> ThreadResponse:
    thread = await _load_thread(db, thread_id, current_user.workspace_id)
    thread.status = ThreadStatus.OPEN
    thread.resolved_at = None
    thread.snoozed_until = None
    await db.commit()
    await db.refresh(thread)
    return await _hydrate_thread(db, thread)


@router.post("/{thread_id}/snooze", response_model=ThreadResponse)
async def snooze_thread(
    thread_id: UUID,
    payload: ThreadSnooze,
    db: DbSession,
    current_user: CurrentUser,
) -> ThreadResponse:
    thread = await _load_thread(db, thread_id, current_user.workspace_id)
    thread.status = ThreadStatus.SNOOZED
    thread.snoozed_until = payload.snoozed_until
    await db.commit()
    await db.refresh(thread)
    return await _hydrate_thread(db, thread)


@router.post(
    "/{thread_id}/reply",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reply_to_thread(
    thread_id: UUID,
    payload: ThreadReply,
    db: DbSession,
    current_user: CurrentUser,
) -> MessageResponse:
    thread = await _load_thread(db, thread_id, current_user.workspace_id)

    if payload.body_text is None and payload.body_html is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="One of body_text or body_html is required",
        )

    # Recipient list = the contact's email (if any), else the from_email of the
    # most recent inbound message.
    to_emails: list[str] = []
    if thread.contact_id is not None:
        c_result = await db.execute(
            select(Contact.email).where(Contact.id == thread.contact_id)
        )
        addr = c_result.scalar_one_or_none()
        if addr is not None:
            to_emails.append(addr)
    if not to_emails:
        last_inbound = await db.execute(
            select(Message.from_email)
            .where(
                Message.thread_id == thread.id,
                Message.direction == MessageDirection.INBOUND,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        addr = last_inbound.scalar_one_or_none()
        if addr is not None:
            to_emails.append(addr)
    if not to_emails:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Thread has no recipient to reply to",
        )

    from_account: EmailAccount | None = None
    if thread.email_account_id is not None:
        acct_result = await db.execute(
            select(EmailAccount).where(EmailAccount.id == thread.email_account_id)
        )
        from_account = acct_result.scalar_one_or_none()

    cc = [str(e) for e in payload.cc_emails] if payload.cc_emails else None
    message = await email_service.send_message(
        db,
        thread,
        body_text=payload.body_text,
        body_html=payload.body_html,
        from_account=from_account,
        actor_id=current_user.id,
        to_emails=to_emails,
        cc_emails=cc,
    )
    await db.commit()
    await db.refresh(message)
    return MessageResponse.model_validate(message)


@router.post(
    "/threads",
    response_model=ThreadDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_thread(
    payload: ThreadCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> ThreadDetailResponse:
    """Compose a new outbound thread (the first message is sent immediately)."""
    if payload.body_text is None and payload.body_html is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="One of body_text or body_html is required",
        )
    if payload.contact_id is not None:
        check = await db.execute(
            select(Contact.id).where(
                Contact.id == payload.contact_id,
                Contact.workspace_id == current_user.workspace_id,
            )
        )
        if check.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="contact_id must belong to the same workspace",
            )

    from_account: EmailAccount | None = None
    if payload.email_account_id is not None:
        acct_result = await db.execute(
            select(EmailAccount).where(
                EmailAccount.id == payload.email_account_id,
                EmailAccount.workspace_id == current_user.workspace_id,
            )
        )
        from_account = acct_result.scalar_one_or_none()
        if from_account is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="email_account_id must belong to the same workspace",
            )

    now = datetime.now(UTC)
    thread = Thread(
        workspace_id=current_user.workspace_id,
        contact_id=payload.contact_id,
        deal_id=payload.deal_id,
        email_account_id=payload.email_account_id,
        subject=payload.subject,
        sla_first_response_due_at=(
            now + timedelta(minutes=settings.SLA_FIRST_RESPONSE_MINUTES)
        ),
        sla_resolution_due_at=(
            now + timedelta(minutes=settings.SLA_RESOLUTION_MINUTES)
        ),
    )
    db.add(thread)
    await db.flush()

    to_emails = [str(e) for e in payload.to_emails]
    cc = [str(e) for e in payload.cc_emails] if payload.cc_emails else None
    message = await email_service.send_message(
        db,
        thread,
        body_text=payload.body_text,
        body_html=payload.body_html,
        from_account=from_account,
        actor_id=current_user.id,
        to_emails=to_emails,
        cc_emails=cc,
    )
    await db.commit()
    await db.refresh(thread)
    await db.refresh(message)

    hydrated = await _hydrate_thread(db, thread)
    return ThreadDetailResponse(
        **hydrated.model_dump(),
        messages=[MessageResponse.model_validate(message)],
    )
