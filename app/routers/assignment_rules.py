"""Assignment-rule CRUD + reorder."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.dependencies import CurrentUser, DbSession
from app.models.assignment_rule import AssignmentRule
from app.models.user import User
from app.schemas.assignment_rule import (
    AssignmentRuleCreate,
    AssignmentRuleReorder,
    AssignmentRuleResponse,
    AssignmentRuleUpdate,
)

router = APIRouter(prefix="/assignment-rules", tags=["assignment-rules"])


async def _load_rule(
    db: DbSession, rule_id: UUID, workspace_id: UUID
) -> AssignmentRule:
    result = await db.execute(
        select(AssignmentRule).where(
            AssignmentRule.id == rule_id,
            AssignmentRule.workspace_id == workspace_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Assignment rule not found"
        )
    return rule


async def _validate_user(
    db: DbSession, user_id: UUID | None, workspace_id: UUID
) -> None:
    if user_id is None:
        return
    result = await db.execute(
        select(User.id).where(
            User.id == user_id, User.workspace_id == workspace_id
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="assign_to_user_id must belong to the same workspace",
        )


@router.get("", response_model=list[AssignmentRuleResponse])
async def list_rules(
    db: DbSession,
    current_user: CurrentUser,
) -> list[AssignmentRuleResponse]:
    result = await db.execute(
        select(AssignmentRule)
        .where(AssignmentRule.workspace_id == current_user.workspace_id)
        .order_by(AssignmentRule.position.asc(), AssignmentRule.created_at.asc())
    )
    return [AssignmentRuleResponse.model_validate(r) for r in result.scalars().all()]


@router.post(
    "",
    response_model=AssignmentRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_rule(
    payload: AssignmentRuleCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> AssignmentRuleResponse:
    await _validate_user(db, payload.assign_to_user_id, current_user.workspace_id)
    rule = AssignmentRule(
        workspace_id=current_user.workspace_id,
        **payload.model_dump(),
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return AssignmentRuleResponse.model_validate(rule)


@router.patch("/{rule_id}", response_model=AssignmentRuleResponse)
async def update_rule(
    rule_id: UUID,
    payload: AssignmentRuleUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> AssignmentRuleResponse:
    rule = await _load_rule(db, rule_id, current_user.workspace_id)
    data = payload.model_dump(exclude_unset=True)
    if "assign_to_user_id" in data:
        await _validate_user(
            db, data["assign_to_user_id"], current_user.workspace_id
        )
    for key, value in data.items():
        setattr(rule, key, value)
    await db.commit()
    await db.refresh(rule)
    return AssignmentRuleResponse.model_validate(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> None:
    rule = await _load_rule(db, rule_id, current_user.workspace_id)
    await db.delete(rule)
    await db.commit()


@router.put("/reorder", response_model=list[AssignmentRuleResponse])
async def reorder_rules(
    payload: AssignmentRuleReorder,
    db: DbSession,
    current_user: CurrentUser,
) -> list[AssignmentRuleResponse]:
    result = await db.execute(
        select(AssignmentRule).where(
            AssignmentRule.workspace_id == current_user.workspace_id
        )
    )
    rules_by_id = {r.id: r for r in result.scalars().all()}

    missing = [rid for rid in payload.ordered_ids if rid not in rules_by_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown rule ids: {missing}",
        )
    for position, rid in enumerate(payload.ordered_ids):
        rules_by_id[rid].position = position

    await db.commit()
    ordered_result = await db.execute(
        select(AssignmentRule)
        .where(AssignmentRule.workspace_id == current_user.workspace_id)
        .order_by(AssignmentRule.position.asc())
    )
    return [
        AssignmentRuleResponse.model_validate(r)
        for r in ordered_result.scalars().all()
    ]
