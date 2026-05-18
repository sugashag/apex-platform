"""API key management routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.dependencies import DbSession
from app.middleware.rbac import require_admin
from app.models.api_key import ApiKey
from app.models.user import User
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyListResponse,
    ApiKeyResponse,
)
from app.services import api_key_service

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_key(
    payload: ApiKeyCreate,
    db: DbSession,
    admin: User = Depends(require_admin()),
) -> ApiKeyCreateResponse:
    api_key, full_key = await api_key_service.create_api_key(
        db,
        workspace_id=admin.workspace_id,
        created_by_id=admin.id,
        name=payload.name,
        scopes=payload.scopes,
        expires_at=payload.expires_at,
    )
    await db.commit()
    await db.refresh(api_key)
    base = ApiKeyResponse.model_validate(api_key)
    return ApiKeyCreateResponse(**base.model_dump(), full_key=full_key)


@router.get("", response_model=ApiKeyListResponse)
async def list_keys(
    db: DbSession,
    admin: User = Depends(require_admin()),
) -> ApiKeyListResponse:
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.workspace_id == admin.workspace_id)
        .order_by(ApiKey.created_at.desc())
    )
    keys = [ApiKeyResponse.model_validate(k) for k in result.scalars().all()]
    return ApiKeyListResponse(items=keys)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: UUID,
    db: DbSession,
    admin: User = Depends(require_admin()),
) -> None:
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.workspace_id == admin.workspace_id,
        )
    )
    key = result.scalar_one_or_none()
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        )
    key.is_active = False
    await db.commit()
