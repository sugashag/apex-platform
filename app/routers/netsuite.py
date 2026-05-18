"""NetSuite configuration, connection testing, and manual sync routes."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.dependencies import CurrentUser, DbSession
from app.models.netsuite import NetSuiteSyncLog, SyncStatus
from app.models.netsuite_config import NetSuiteConfig
from app.schemas.netsuite import (
    NetSuiteConfigCreate,
    NetSuiteConfigResponse,
    NetSuiteSyncLogListResponse,
    NetSuiteSyncLogResponse,
    NetSuiteSyncTriggerResponse,
    NetSuiteTestResponse,
)
from app.services import netsuite_sync_service
from app.services.netsuite_service import NetSuiteService
from app.utils.pagination import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/netsuite", tags=["netsuite"])


SECRET_MASK = "********"  # noqa: S105 — display mask, not a password


def _masked(value: str | None) -> str:
    """Replace secret values with the standard mask string."""
    return SECRET_MASK if value else ""


def _serialize_config(config: NetSuiteConfig) -> NetSuiteConfigResponse:
    """Mask sensitive fields before returning a config to the client."""
    return NetSuiteConfigResponse(
        id=config.id,
        workspace_id=config.workspace_id,
        account_id=config.account_id,
        consumer_key=_masked(config.consumer_key),
        consumer_secret=_masked(config.consumer_secret),
        token_id=_masked(config.token_id),
        token_secret=_masked(config.token_secret),
        subsidiary_id=config.subsidiary_id,
        default_ar_account_id=config.default_ar_account_id,
        default_revenue_account_id=config.default_revenue_account_id,
        is_active=config.is_active,
        last_tested_at=config.last_tested_at,
        last_test_status=config.last_test_status,
        last_test_error=config.last_test_error,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


async def _load_config_for_workspace(
    db: DbSession, workspace_id: UUID
) -> NetSuiteConfig | None:
    result = await db.execute(
        select(NetSuiteConfig).where(NetSuiteConfig.workspace_id == workspace_id)
    )
    return result.scalar_one_or_none()


@router.post(
    "/config",
    response_model=NetSuiteConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_config(
    payload: NetSuiteConfigCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> NetSuiteConfigResponse:
    existing = await _load_config_for_workspace(db, current_user.workspace_id)
    if existing is None:
        config = NetSuiteConfig(
            workspace_id=current_user.workspace_id,
            account_id=payload.account_id,
            consumer_key=payload.consumer_key,
            consumer_secret=payload.consumer_secret,
            token_id=payload.token_id,
            token_secret=payload.token_secret,
            subsidiary_id=payload.subsidiary_id,
            default_ar_account_id=payload.default_ar_account_id,
            default_revenue_account_id=payload.default_revenue_account_id,
            is_active=payload.is_active,
        )
        db.add(config)
    else:
        config = existing
        config.account_id = payload.account_id
        config.consumer_key = payload.consumer_key
        config.consumer_secret = payload.consumer_secret
        config.token_id = payload.token_id
        config.token_secret = payload.token_secret
        config.subsidiary_id = payload.subsidiary_id
        config.default_ar_account_id = payload.default_ar_account_id
        config.default_revenue_account_id = payload.default_revenue_account_id
        config.is_active = payload.is_active

    await db.commit()
    await db.refresh(config)
    return _serialize_config(config)


@router.get("/config", response_model=NetSuiteConfigResponse)
async def get_config(
    db: DbSession,
    current_user: CurrentUser,
) -> NetSuiteConfigResponse:
    config = await _load_config_for_workspace(db, current_user.workspace_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No NetSuite config for this workspace",
        )
    return _serialize_config(config)


@router.post("/test", response_model=NetSuiteTestResponse)
async def test_connection(
    db: DbSession,
    current_user: CurrentUser,
) -> NetSuiteTestResponse:
    config = await _load_config_for_workspace(db, current_user.workspace_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No NetSuite config for this workspace",
        )

    # Connection tests always use mock mode in non-production environments.
    from app.config import settings as cfg
    service = NetSuiteService(
        config=config, mock=cfg.ENVIRONMENT != "production"
    )
    success = await service.test_connection()
    await service.aclose()
    await db.commit()
    return NetSuiteTestResponse(
        success=success,
        tested_at=config.last_tested_at or datetime.now(UTC),
        error=config.last_test_error,
    )


@router.get("/sync-log", response_model=NetSuiteSyncLogListResponse)
async def list_sync_log(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    sync_status: Annotated[
        SyncStatus | None, Query(alias="status")
    ] = None,
    entity_type: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> PaginatedResponse[NetSuiteSyncLogResponse]:
    stmt = select(NetSuiteSyncLog).where(
        NetSuiteSyncLog.workspace_id == current_user.workspace_id
    )
    if sync_status is not None:
        stmt = stmt.where(NetSuiteSyncLog.status == sync_status)
    if entity_type is not None:
        stmt = stmt.where(NetSuiteSyncLog.apex_entity_type == entity_type)
    if created_from is not None:
        stmt = stmt.where(NetSuiteSyncLog.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(NetSuiteSyncLog.created_at <= created_to)

    count_result = await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )
    total = int(count_result.scalar_one())

    stmt = (
        stmt.order_by(NetSuiteSyncLog.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    result = await db.execute(stmt)
    rows = [
        NetSuiteSyncLogResponse.model_validate(log)
        for log in result.scalars().all()
    ]
    return PaginatedResponse.build(items=rows, total=total, params=pagination)


@router.post(
    "/sync/company/{company_id}",
    response_model=NetSuiteSyncTriggerResponse,
)
async def sync_company(
    company_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> NetSuiteSyncTriggerResponse:
    log = await netsuite_sync_service.sync_company_as_customer(
        db, current_user.workspace_id, company_id
    )
    await db.commit()
    await db.refresh(log)
    return NetSuiteSyncTriggerResponse(
        sync_log_id=log.id,
        status=log.status,
        entity_type=log.apex_entity_type,
        entity_id=log.apex_entity_id,
        netsuite_internal_id=log.netsuite_internal_id,
        error_message=log.error_message,
    )


@router.post(
    "/sync/deal/{deal_id}",
    response_model=NetSuiteSyncTriggerResponse,
)
async def sync_deal(
    deal_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> NetSuiteSyncTriggerResponse:
    log = await netsuite_sync_service.sync_deal_as_sales_order(
        db, current_user.workspace_id, deal_id
    )
    await db.commit()
    await db.refresh(log)
    return NetSuiteSyncTriggerResponse(
        sync_log_id=log.id,
        status=log.status,
        entity_type=log.apex_entity_type,
        entity_id=log.apex_entity_id,
        netsuite_internal_id=log.netsuite_internal_id,
        error_message=log.error_message,
    )


@router.post("/sync/retry-failed", response_model=dict[str, int])
async def retry_failed(
    db: DbSession,
    current_user: CurrentUser,
) -> dict[str, int]:
    count = await netsuite_sync_service.retry_failed_syncs(
        db, current_user.workspace_id
    )
    await db.commit()
    return {"retried": count}
