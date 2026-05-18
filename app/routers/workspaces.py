"""Workspace routes."""

import secrets
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.dependencies import CurrentUser, DbSession
from app.models.user import UserRole
from app.models.workspace import Workspace
from app.schemas.workspace import (
    TrackingSnippetResponse,
    WorkspaceCreate,
    WorkspaceRead,
)
from app.services.tracking_service import build_tracking_snippet

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> Workspace:
    """Create a new workspace. Only admins of an existing workspace may call this."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create workspaces",
        )

    workspace = Workspace(
        name=payload.name,
        slug=payload.slug,
        tracking_token=secrets.token_urlsafe(32),
    )
    db.add(workspace)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workspace slug already in use",
        ) from exc
    await db.refresh(workspace)
    return workspace


@router.get("/{workspace_id}", response_model=WorkspaceRead)
async def get_workspace(
    workspace_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> Workspace:
    """Fetch a workspace by id. Caller must belong to that workspace."""
    if current_user.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-workspace access denied",
        )

    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    return workspace


@router.get(
    "/{workspace_id}/tracking-snippet",
    response_model=TrackingSnippetResponse,
)
async def get_tracking_snippet(
    workspace_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> TrackingSnippetResponse:
    """Return the marketing-site JS snippet to paste before </body>.

    The snippet captures UTM params + click IDs on landing, registers a
    visitor session against the public ``tracking_token``, and intercepts
    forms whose ``data-apex-form`` attribute identifies the form_id.
    """
    if current_user.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-workspace access denied",
        )

    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    if workspace.tracking_token is None:
        # Backfill a token for workspaces created before this column existed.
        workspace.tracking_token = secrets.token_urlsafe(32)
        await db.commit()
        await db.refresh(workspace)

    snippet = build_tracking_snippet(
        tracking_token=workspace.tracking_token,
        api_base_url=settings.API_BASE_URL,
    )
    return TrackingSnippetResponse(
        tracking_token=workspace.tracking_token,
        api_base_url=settings.API_BASE_URL,
        snippet=snippet,
    )
