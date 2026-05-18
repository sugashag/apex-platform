"""VAR partner program — referral tracking."""

import secrets
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.dependencies import DbSession
from app.middleware.rbac import require_admin
from app.models.partner_referral import PartnerReferral
from app.models.user import User
from app.schemas.partner import (
    PartnerReferralCreate,
    PartnerReferralListResponse,
    PartnerReferralResponse,
)

router = APIRouter(prefix="/partners", tags=["partners"])


def _generate_referral_code() -> str:
    """8-character URL-safe referral code."""
    return secrets.token_urlsafe(6)[:8]


@router.post(
    "/referrals",
    response_model=PartnerReferralResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_referral(
    payload: PartnerReferralCreate,
    db: DbSession,
    _admin: User = Depends(require_admin()),
) -> PartnerReferralResponse:
    referral = PartnerReferral(
        partner_name=payload.partner_name,
        partner_email=payload.partner_email,
        referral_code=payload.referral_code or _generate_referral_code(),
        commission_rate=payload.commission_rate
        if payload.commission_rate is not None
        else Decimal("20.00"),
        notes=payload.notes,
    )
    db.add(referral)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Referral code already in use",
        ) from exc
    await db.refresh(referral)
    return PartnerReferralResponse.model_validate(referral)


@router.get("/referrals", response_model=PartnerReferralListResponse)
async def list_referrals(
    db: DbSession,
    _admin: User = Depends(require_admin()),
) -> PartnerReferralListResponse:
    result = await db.execute(
        select(PartnerReferral).order_by(PartnerReferral.created_at.desc())
    )
    return PartnerReferralListResponse(
        items=[
            PartnerReferralResponse.model_validate(r)
            for r in result.scalars().all()
        ]
    )
