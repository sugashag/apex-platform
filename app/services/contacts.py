"""Contact services — upsert and search helpers."""

from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact


async def get_or_create_by_email(
    db: AsyncSession,
    workspace_id: UUID,
    email: str,
    **fields: Any,
) -> tuple[Contact, bool]:
    """Find a contact by (workspace_id, email) or insert a new one.

    Returns `(contact, created)`. Caller commits the transaction.
    """
    result = await db.execute(
        select(Contact).where(
            Contact.workspace_id == workspace_id,
            Contact.email == email,
        )
    )
    contact = result.scalar_one_or_none()
    if contact is not None:
        return contact, False

    contact = Contact(workspace_id=workspace_id, email=email, **fields)
    db.add(contact)
    await db.flush()
    return contact, True


async def search_contacts(
    db: AsyncSession,
    workspace_id: UUID,
    *,
    query: str | None = None,
    company_id: UUID | None = None,
    owner_id: UUID | None = None,
    source: str | None = None,
    email_status: str | None = None,
    lead_score_min: int | None = None,
    lead_score_max: int | None = None,
    include_inactive: bool = False,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[Contact], int]:
    """Search/filter contacts within a workspace. Returns `(rows, total)`."""
    stmt = select(Contact).where(Contact.workspace_id == workspace_id)

    if not include_inactive:
        stmt = stmt.where(Contact.is_active.is_(True))
    if company_id is not None:
        stmt = stmt.where(Contact.company_id == company_id)
    if owner_id is not None:
        stmt = stmt.where(Contact.owner_id == owner_id)
    if source is not None:
        stmt = stmt.where(Contact.source == source)
    if email_status is not None:
        stmt = stmt.where(Contact.email_status == email_status)
    if lead_score_min is not None:
        stmt = stmt.where(Contact.lead_score >= lead_score_min)
    if lead_score_max is not None:
        stmt = stmt.where(Contact.lead_score <= lead_score_max)
    if query:
        like = f"%{query.lower()}%"
        stmt = stmt.where(
            or_(
                Contact.email.ilike(like),
                Contact.first_name.ilike(like),
                Contact.last_name.ilike(like),
            )
        )

    count_stmt = select(Contact.id).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = len(total_result.all())

    stmt = stmt.order_by(Contact.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all()), total
