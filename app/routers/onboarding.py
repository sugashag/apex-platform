"""Onboarding checklist routes."""

from fastapi import APIRouter, HTTPException, status

from app.dependencies import CurrentUser, DbSession
from app.models.onboarding_checklist import CHECKLIST_STEPS
from app.schemas.onboarding import OnboardingChecklistResponse
from app.services import onboarding_service

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("", response_model=OnboardingChecklistResponse)
async def get_checklist(
    db: DbSession, current_user: CurrentUser
) -> OnboardingChecklistResponse:
    """Return the workspace's checklist, auto-evaluating steps against real data."""
    checklist = await onboarding_service.evaluate_checklist(
        db, current_user.workspace_id
    )
    await db.commit()
    await db.refresh(checklist)
    return OnboardingChecklistResponse.model_validate(checklist)


@router.post("/{step}/complete", response_model=OnboardingChecklistResponse)
async def mark_step(
    step: str, db: DbSession, current_user: CurrentUser
) -> OnboardingChecklistResponse:
    """Manually mark a checklist step as complete."""
    if step not in CHECKLIST_STEPS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown onboarding step: {step}",
        )
    checklist = await onboarding_service.mark_step_complete(
        db, current_user.workspace_id, step
    )
    await db.commit()
    await db.refresh(checklist)
    return OnboardingChecklistResponse.model_validate(checklist)
