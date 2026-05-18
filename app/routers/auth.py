"""Authentication routes: register, login, me."""

import logging
import secrets

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.dependencies import CurrentUser, DbSession
from app.models.user import User, UserRole
from app.models.workspace import Workspace
from app.schemas.user import TokenResponse, UserLogin, UserRead, UserRegister
from app.services import billing_service, onboarding_service
from app.services.auth import create_access_token, hash_password, verify_password
from app.services.pipeline_stages import seed_default_pipeline_stages

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister, db: DbSession) -> TokenResponse:
    """Create a workspace and its first user (admin) in a single transaction."""
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    workspace = Workspace(
        name=payload.workspace_name,
        slug=payload.workspace_slug,
        tracking_token=secrets.token_urlsafe(32),
    )
    db.add(workspace)
    await db.flush()

    await seed_default_pipeline_stages(db, workspace.id)

    user = User(
        workspace_id=workspace.id,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=UserRole.ADMIN,
    )
    db.add(user)
    await db.flush()

    # Phase 8: every new workspace starts with an onboarding checklist and a
    # 14-day trial of the Starter plan. If the Starter plan row is missing
    # (e.g. a test fixture that didn't run the seed migration) we log and
    # continue — the trial gate falls back to "unlimited" without a plan.
    await onboarding_service.get_or_create_checklist(db, workspace.id)
    starter_plan = await billing_service.get_plan_by_slug(
        db, billing_service.STARTER_PLAN_SLUG
    )
    if starter_plan is not None:
        await billing_service.start_trial_subscription(
            db,
            workspace_id=workspace.id,
            plan=starter_plan,
            billing_email=payload.email,
            billing_name=(
                f"{payload.first_name} {payload.last_name}".strip()
                if payload.first_name or payload.last_name
                else None
            ),
        )
    else:
        logger.warning(
            "Starter plan not found during registration of workspace %s; "
            "skipping trial subscription creation.",
            workspace.id,
        )

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workspace slug already in use",
        ) from exc

    await db.refresh(user)

    token, expires_in = create_access_token(
        user_id=user.id,
        workspace_id=workspace.id,
    )
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: DbSession) -> TokenResponse:
    """Exchange email + password for a JWT access token."""
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive",
        )

    token, expires_in = create_access_token(
        user_id=user.id,
        workspace_id=user.workspace_id,
    )
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserRead)
async def me(current_user: CurrentUser) -> User:
    """Return the currently authenticated user."""
    return current_user
