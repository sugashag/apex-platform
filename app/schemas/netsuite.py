"""NetSuite config and sync-log schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.netsuite import SyncDirection, SyncStatus
from app.models.netsuite_config import NetSuiteTestStatus
from app.utils.pagination import PaginatedResponse


class NetSuiteConfigCreate(BaseModel):
    account_id: str = Field(..., min_length=1, max_length=50)
    consumer_key: str = Field(..., min_length=1)
    consumer_secret: str = Field(..., min_length=1)
    token_id: str = Field(..., min_length=1)
    token_secret: str = Field(..., min_length=1)
    subsidiary_id: str | None = Field(default=None, max_length=50)
    default_ar_account_id: str | None = Field(default=None, max_length=50)
    default_revenue_account_id: str | None = Field(default=None, max_length=50)
    is_active: bool = True


class NetSuiteConfigResponse(BaseModel):
    """Config with sensitive fields masked."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    account_id: str
    consumer_key: str  # masked at the router layer
    consumer_secret: str
    token_id: str
    token_secret: str
    subsidiary_id: str | None
    default_ar_account_id: str | None
    default_revenue_account_id: str | None
    is_active: bool
    last_tested_at: datetime | None
    last_test_status: NetSuiteTestStatus | None
    last_test_error: str | None
    created_at: datetime
    updated_at: datetime


class NetSuiteTestResponse(BaseModel):
    success: bool
    tested_at: datetime
    error: str | None = None


class NetSuiteSyncLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    apex_entity_type: str
    apex_entity_id: UUID
    netsuite_record_type: str
    netsuite_internal_id: str | None
    netsuite_external_id: str | None
    sync_direction: SyncDirection
    status: SyncStatus
    last_synced_at: datetime | None
    error_message: str | None
    apex_checksum: str | None
    created_at: datetime
    updated_at: datetime


NetSuiteSyncLogListResponse = PaginatedResponse[NetSuiteSyncLogResponse]


class NetSuiteSyncTriggerResponse(BaseModel):
    """Returned after manually triggering a sync."""

    sync_log_id: UUID
    status: SyncStatus
    entity_type: str
    entity_id: UUID
    netsuite_internal_id: str | None
    error_message: str | None
