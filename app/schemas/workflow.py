"""Workflow request/response schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.workflow import WorkflowTriggerType
from app.models.workflow_condition import WorkflowConditionOperator
from app.models.workflow_run import WorkflowRunStatus
from app.models.workflow_step import WorkflowActionType
from app.models.workflow_step_run import WorkflowStepRunStatus
from app.utils.pagination import PaginatedResponse

# --- conditions --------------------------------------------------------------


class WorkflowConditionCreate(BaseModel):
    field: str = Field(min_length=1, max_length=100)
    operator: WorkflowConditionOperator
    value: str | None = Field(default=None, max_length=500)
    position: int = Field(default=0, ge=0)


class WorkflowConditionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_id: UUID
    field: str
    operator: WorkflowConditionOperator
    value: str | None
    position: int


# --- steps -------------------------------------------------------------------


class WorkflowStepCreate(BaseModel):
    position: int = Field(ge=0)
    action_type: WorkflowActionType
    action_config: dict[str, Any] = Field(default_factory=dict)
    delay_minutes: int = Field(default=0, ge=0)
    requires_approval: bool = False


class WorkflowStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_id: UUID
    position: int
    action_type: WorkflowActionType
    action_config: dict[str, Any]
    delay_minutes: int
    requires_approval: bool


# --- workflows ---------------------------------------------------------------


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    is_active: bool = True
    trigger_type: WorkflowTriggerType
    trigger_config: dict[str, Any] | None = None
    conditions: list[WorkflowConditionCreate] = Field(default_factory=list)
    steps: list[WorkflowStepCreate] = Field(default_factory=list)


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    is_active: bool | None = None
    trigger_type: WorkflowTriggerType | None = None
    trigger_config: dict[str, Any] | None = None
    conditions: list[WorkflowConditionCreate] | None = None
    steps: list[WorkflowStepCreate] | None = None


class WorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    description: str | None
    is_active: bool
    trigger_type: WorkflowTriggerType
    trigger_config: dict[str, Any] | None
    run_count: int
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkflowDetailResponse(WorkflowResponse):
    conditions: list[WorkflowConditionResponse]
    steps: list[WorkflowStepResponse]


WorkflowListResponse = PaginatedResponse[WorkflowResponse]


class WorkflowManualTrigger(BaseModel):
    entity_type: str | None = Field(default=None, max_length=50)
    entity_id: UUID | None = None
    context: dict[str, Any] = Field(default_factory=dict)


# --- runs --------------------------------------------------------------------


class WorkflowStepRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_run_id: UUID
    workflow_step_id: UUID
    status: WorkflowStepRunStatus
    approved_by_id: UUID | None
    approved_at: datetime | None
    execute_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    output: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class WorkflowRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    workflow_id: UUID
    trigger_type: str
    trigger_entity_type: str | None
    trigger_entity_id: UUID | None
    contact_id: UUID | None
    deal_id: UUID | None
    status: WorkflowRunStatus
    current_step_position: int
    error_message: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkflowRunDetailResponse(WorkflowRunResponse):
    step_runs: list[WorkflowStepRunResponse]


WorkflowRunListResponse = PaginatedResponse[WorkflowRunResponse]
