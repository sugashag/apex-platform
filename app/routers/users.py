"""Workspace user management — invite, list, role updates, deactivation."""

import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.dependencies import CurrentUser, DbSession
from app.middleware.plan_enforcement import check_user_limit
from app.middleware.rbac import require_admin
from app.models.user import User, UserRole
from app.schemas.user import (
    UserInvite,
    UserInviteResponse,
    UserListResponse,
    UserRead,
    UserUpdate,
)
from app.services.auth import hash_password

router = APIRouter(prefix="/users", tags=["users"])


def _generate_temp_password() -> str:
    """Cryptographically random temporary password for invited users."""
    return secrets.token_urlsafe(16)


@router.post("/invite", response_model=UserInviteResponse, status_code=status.HTTP_201_CREATED)
async def invite_user(
    payload: UserInvite,
    db: DbSession,
    admin: User = Depends(require_admin()),
) -> UserInviteResponse:
    """Invite a new user to the workspace. Returns a one-time temp password."""
    await check_user_limit(db, admin.workspace_id)

    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    temp_password = _generate_temp_password()
    user = User(
        workspace_id=admin.workspace_id,
        email=payload.email,
        hashed_password=hash_password(temp_password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=payload.role,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from exc
    await db.refresh(user)
    return UserInviteResponse(
        user=UserRead.model_validate(user),
        temporary_password=temp_password,
    )


@router.get("", response_model=UserListResponse)
async def list_users(
    db: DbSession, current_user: CurrentUser
) -> UserListResponse:
    """List users in the caller's workspace."""
    result = await db.execute(
        select(User)
        .where(User.workspace_id == current_user.workspace_id)
        .order_by(User.created_at.asc())
    )
    return UserListResponse(
        items=[UserRead.model_validate(u) for u in result.scalars().all()]
    )


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    db: DbSession,
    admin: User = Depends(require_admin()),
) -> UserRead:
    """Update a user's role, name, or active flag (admin only)."""
    if user_id == admin.id and payload.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admins cannot deactivate themselves",
        )
    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.workspace_id == admin.workspace_id,
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return UserRead.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: UUID,
    db: DbSession,
    admin: User = Depends(require_admin()),
) -> None:
    """Soft-delete a user. Admins cannot deactivate themselves."""
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admins cannot deactivate themselves",
        )
    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.workspace_id == admin.workspace_id,
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    user.is_active = False
    await db.commit()


# Backwards-compatible alias — the spec mentions an invite path beneath
# ``/api/v1/users/invite``. Re-export the invite endpoint via the existing
# router prefix so future iterations only need to update one place.
__all__ = ["router", "UserRole"]
