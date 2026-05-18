"""AssignmentRule request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.assignment_rule import AssignmentConditionOperator


class AssignmentRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    condition_field: str = Field(min_length=1, max_length=100)
    condition_operator: AssignmentConditionOperator
    condition_value: str = Field(min_length=1, max_length=500)
    assign_to_user_id: UUID | None = None
    position: int = Field(default=0, ge=0)
    is_active: bool = True


class AssignmentRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    condition_field: str | None = Field(default=None, min_length=1, max_length=100)
    condition_operator: AssignmentConditionOperator | None = None
    condition_value: str | None = Field(default=None, min_length=1, max_length=500)
    assign_to_user_id: UUID | None = None
    position: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class AssignmentRuleReorder(BaseModel):
    """`{rule_id: new_position}` mapping for bulk reordering."""

    ordered_ids: list[UUID] = Field(min_length=1)


class AssignmentRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    condition_field: str
    condition_operator: AssignmentConditionOperator
    condition_value: str
    assign_to_user_id: UUID | None
    position: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
