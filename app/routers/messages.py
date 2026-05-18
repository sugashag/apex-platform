"""Single-message lookup + test helpers."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.dependencies import CurrentUser, DbSession
from app.models.message import Message
from app.models.thread import Thread
from app.schemas.message import MessageResponse

router = APIRouter(prefix="/messages", tags=["messages"])


async def _load_message(db: DbSession, message_id: UUID, workspace_id: UUID) -> Message:
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.workspace_id == workspace_id,
        )
    )
    message = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        )
    return message


@router.get("/{message_id}", response_model=MessageResponse)
async def get_message(
    message_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> MessageResponse:
    message = await _load_message(db, message_id, current_user.workspace_id)
    subject_result = await db.execute(
        select(Thread.subject).where(Thread.id == message.thread_id)
    )
    subject = subject_result.scalar_one_or_none()
    base = MessageResponse.model_validate(message)
    return base.model_copy(update={"thread_subject": subject})


@router.post("/{message_id}/mark-opened", response_model=MessageResponse)
async def mark_message_opened(
    message_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> MessageResponse:
    message = await _load_message(db, message_id, current_user.workspace_id)
    if message.opened_at is None:
        message.opened_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(message)
    return MessageResponse.model_validate(message)
