"""Company CRUD routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.dependencies import CurrentUser, DbSession
from app.models.company import Company
from app.models.contact import Contact
from app.schemas.company import (
    CompanyCreate,
    CompanyDetailResponse,
    CompanyListResponse,
    CompanyResponse,
    CompanyUpdate,
)
from app.utils.pagination import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/companies", tags=["companies"])


def _to_response(company: Company) -> CompanyResponse:
    return CompanyResponse.model_validate(company)


@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create_company(
    payload: CompanyCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> CompanyResponse:
    company = Company(
        workspace_id=current_user.workspace_id,
        name=payload.name,
        domain=payload.domain,
        industry=payload.industry,
        employee_count=payload.employee_count,
        annual_revenue_cents=payload.annual_revenue_cents,
        website=str(payload.website) if payload.website else None,
        linkedin_url=str(payload.linkedin_url) if payload.linkedin_url else None,
        netsuite_internal_id=payload.netsuite_internal_id,
        netsuite_external_id=payload.netsuite_external_id,
    )
    db.add(company)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A company with this domain already exists in your workspace",
        ) from exc
    await db.refresh(company)
    return _to_response(company)


@router.get("", response_model=CompanyListResponse)
async def list_companies(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    name: Annotated[str | None, Query(description="Exact name match.")] = None,
    domain: Annotated[str | None, Query(description="Exact domain match.")] = None,
    industry: Annotated[str | None, Query(description="Exact industry match.")] = None,
    search: Annotated[
        str | None,
        Query(description="Substring search across name and domain."),
    ] = None,
    include_inactive: bool = False,
) -> PaginatedResponse[CompanyResponse]:
    stmt = select(Company).where(Company.workspace_id == current_user.workspace_id)

    if not include_inactive:
        stmt = stmt.where(Company.is_active.is_(True))
    if name is not None:
        stmt = stmt.where(Company.name == name)
    if domain is not None:
        stmt = stmt.where(Company.domain == domain)
    if industry is not None:
        stmt = stmt.where(Company.industry == industry)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Company.name.ilike(like), Company.domain.ilike(like)))

    count_result = await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )
    total = int(count_result.scalar_one())

    stmt = (
        stmt.order_by(Company.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    result = await db.execute(stmt)
    rows = [_to_response(c) for c in result.scalars().all()]
    return PaginatedResponse.build(items=rows, total=total, params=pagination)


@router.get("/{company_id}", response_model=CompanyDetailResponse)
async def get_company(
    company_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> CompanyDetailResponse:
    result = await db.execute(
        select(Company).where(
            Company.id == company_id,
            Company.workspace_id == current_user.workspace_id,
        )
    )
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    count_result = await db.execute(
        select(func.count(Contact.id)).where(
            Contact.workspace_id == current_user.workspace_id,
            Contact.company_id == company_id,
            Contact.is_active.is_(True),
        )
    )
    return CompanyDetailResponse(
        **CompanyResponse.model_validate(company).model_dump(),
        contact_count=int(count_result.scalar_one()),
    )


@router.patch("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: UUID,
    payload: CompanyUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> CompanyResponse:
    result = await db.execute(
        select(Company).where(
            Company.id == company_id,
            Company.workspace_id == current_user.workspace_id,
        )
    )
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    data = payload.model_dump(exclude_unset=True)
    for field in ("website", "linkedin_url"):
        if field in data and data[field] is not None:
            data[field] = str(data[field])
    for key, value in data.items():
        setattr(company, key, value)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A company with this domain already exists in your workspace",
        ) from exc
    await db.refresh(company)
    return _to_response(company)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(
    company_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> None:
    result = await db.execute(
        select(Company).where(
            Company.id == company_id,
            Company.workspace_id == current_user.workspace_id,
        )
    )
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    company.is_active = False
    await db.commit()
