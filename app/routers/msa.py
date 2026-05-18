"""MSA generation + signing routes."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.dependencies import CurrentUser, DbSession
from app.models.deal import Deal
from app.models.msa_document import MsaDocument
from app.schemas.msa import (
    MsaConfirmSignedRequest,
    MsaGenerateRequest,
    MsaResponse,
    MsaSendRequest,
)
from app.services import msa_service

router = APIRouter(prefix="/msa", tags=["msa"])


@router.post(
    "/generate", response_model=MsaResponse, status_code=status.HTTP_201_CREATED
)
async def generate_msa(
    payload: MsaGenerateRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> MsaResponse:
    try:
        msa = await msa_service.generate_msa(
            db,
            deal_id=payload.deal_id,
            workspace_id=current_user.workspace_id,
            generated_by_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    await db.commit()
    await db.refresh(msa)
    return MsaResponse.model_validate(msa)


@router.get("/{msa_id}", response_model=MsaResponse)
async def get_msa(
    msa_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> MsaResponse:
    result = await db.execute(
        select(MsaDocument).where(
            MsaDocument.id == msa_id,
            MsaDocument.workspace_id == current_user.workspace_id,
        )
    )
    msa = result.scalar_one_or_none()
    if msa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MSA not found"
        )
    return MsaResponse.model_validate(msa)


@router.post("/{msa_id}/send", response_model=MsaResponse)
async def send_msa(
    msa_id: UUID,
    payload: MsaSendRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> MsaResponse:
    try:
        msa = await msa_service.send_for_signing(
            db,
            msa_id=msa_id,
            workspace_id=current_user.workspace_id,
            signer_email=payload.signer_email,
            signer_name=payload.signer_name,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    await db.commit()
    await db.refresh(msa)
    return MsaResponse.model_validate(msa)


@router.post("/{msa_id}/confirm-signed", response_model=MsaResponse)
async def confirm_signed(
    msa_id: UUID,
    payload: MsaConfirmSignedRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> MsaResponse:
    try:
        msa = await msa_service.process_signed(
            db,
            msa_id=msa_id,
            workspace_id=current_user.workspace_id,
            signed_at=payload.signed_at,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    await db.commit()
    await db.refresh(msa)
    return MsaResponse.model_validate(msa)


# Deal-scoped lookup so the UI can fetch the latest MSA for a deal.
deals_router = APIRouter(prefix="/deals", tags=["msa"])


@deals_router.get("/{deal_id}/msa", response_model=MsaResponse | None)
async def get_msa_for_deal(
    deal_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> MsaResponse | None:
    deal_result = await db.execute(
        select(Deal.id).where(
            Deal.id == deal_id,
            Deal.workspace_id == current_user.workspace_id,
        )
    )
    if deal_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found"
        )

    result = await db.execute(
        select(MsaDocument)
        .where(
            MsaDocument.deal_id == deal_id,
            MsaDocument.workspace_id == current_user.workspace_id,
        )
        .order_by(MsaDocument.created_at.desc())
        .limit(1)
    )
    msa = result.scalar_one_or_none()
    if msa is None:
        return None
    return MsaResponse.model_validate(msa)
