"""Orchestrates APEX → NetSuite synchronization.

Every public method:
1. Creates (or reuses) a ``NetSuiteSyncLog`` row.
2. Loads or builds a ``NetSuiteService`` for the workspace (mock mode when
   no ``NetSuiteConfig`` is on file).
3. Performs the upstream NetSuite call.
4. Stamps ``netsuite_internal_id`` back onto the APEX entity.
5. Updates the sync-log row with success / failure metadata.

Callers commit. Failures are caught and recorded — they never raise.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.company import Company
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.msa_document import MsaDocument
from app.models.netsuite import (
    NetSuiteSyncLog,
    SyncDirection,
    SyncStatus,
)
from app.models.netsuite_config import NetSuiteConfig
from app.models.payment import Payment
from app.services.netsuite_service import NetSuiteService

logger = logging.getLogger(__name__)

# Folder ID we attach MSA PDFs to when none is configured. Real deployments
# can override per-workspace; for now we use a stable default.
DEFAULT_MSA_FOLDER_ID = "0"


async def _load_config(
    db: AsyncSession, workspace_id: UUID
) -> NetSuiteConfig | None:
    result = await db.execute(
        select(NetSuiteConfig).where(
            NetSuiteConfig.workspace_id == workspace_id,
            NetSuiteConfig.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def _build_service(
    db: AsyncSession, workspace_id: UUID
) -> NetSuiteService:
    """Return a NetSuiteService — mock when no live config exists."""
    config = await _load_config(db, workspace_id)
    if config is None:
        logger.info(
            "no NetSuiteConfig for workspace %s — using mock NetSuiteService",
            workspace_id,
        )
        return NetSuiteService(config=None, mock=True)
    # Force mock mode in tests/dev so we never accidentally call NetSuite.
    mock = settings.ENVIRONMENT != "production"
    return NetSuiteService(config=config, mock=mock)


async def _create_sync_log(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    entity_type: str,
    entity_id: UUID,
    record_type: str,
) -> NetSuiteSyncLog:
    log = NetSuiteSyncLog(
        workspace_id=workspace_id,
        apex_entity_type=entity_type,
        apex_entity_id=entity_id,
        netsuite_record_type=record_type,
        sync_direction=SyncDirection.APEX_TO_NETSUITE,
        status=SyncStatus.PENDING,
    )
    db.add(log)
    await db.flush()
    return log


def _mark_success(log: NetSuiteSyncLog, internal_id: str | None) -> None:
    log.status = SyncStatus.SYNCED
    log.last_synced_at = datetime.now(UTC)
    log.netsuite_internal_id = internal_id
    log.error_message = None


def _mark_failure(log: NetSuiteSyncLog, error: Exception | str) -> None:
    log.status = SyncStatus.FAILED
    log.last_synced_at = datetime.now(UTC)
    log.error_message = str(error)[:2000]


# ---------------------------------------------------------------- public API


async def sync_company_as_customer(
    db: AsyncSession,
    workspace_id: UUID,
    company_id: UUID,
) -> NetSuiteSyncLog:
    """Sync a Company to a NetSuite Customer.

    Looks up an existing Customer by primary contact email (when known)
    before creating a new one — this is how we avoid duplicate Customer
    records in NetSuite.
    """
    log = await _create_sync_log(
        db,
        workspace_id=workspace_id,
        entity_type="company",
        entity_id=company_id,
        record_type="customer",
    )

    company = await db.get(Company, company_id)
    if company is None:
        _mark_failure(log, "company not found")
        return log

    # If already linked, refresh the log and return.
    if company.netsuite_internal_id:
        _mark_success(log, company.netsuite_internal_id)
        return log

    service = await _build_service(db, workspace_id)
    primary_contact_result = await db.execute(
        select(Contact)
        .where(
            Contact.workspace_id == workspace_id,
            Contact.company_id == company_id,
            Contact.is_active.is_(True),
        )
        .order_by(Contact.created_at.asc())
        .limit(1)
    )
    contact = primary_contact_result.scalar_one_or_none()

    try:
        existing_id: str | None = None
        if contact is not None and contact.email:
            existing_id = await service.find_customer_by_email(contact.email)
        if existing_id is None:
            existing_id = await service.create_customer(company, contact)
        company.netsuite_internal_id = existing_id
        if contact is not None and not contact.netsuite_internal_id:
            contact.netsuite_internal_id = existing_id
        _mark_success(log, existing_id)
    except Exception as exc:  # noqa: BLE001 — every sync failure is logged
        logger.exception("netsuite customer sync failed for company %s", company_id)
        _mark_failure(log, exc)
    return log


async def sync_deal_as_sales_order(
    db: AsyncSession,
    workspace_id: UUID,
    deal_id: UUID,
) -> NetSuiteSyncLog:
    """Sync a Deal to a NetSuite Sales Order. Requires the Company already synced."""
    log = await _create_sync_log(
        db,
        workspace_id=workspace_id,
        entity_type="deal",
        entity_id=deal_id,
        record_type="salesOrder",
    )

    deal = await db.get(Deal, deal_id)
    if deal is None:
        _mark_failure(log, "deal not found")
        return log

    if deal.company_id is None:
        _mark_failure(log, "deal has no company_id — cannot sync to sales order")
        return log

    company = await db.get(Company, deal.company_id)
    if company is None or not company.netsuite_internal_id:
        # Try to sync the company first so the user doesn't have to do it
        # manually. The inner sync mutates `company.netsuite_internal_id`
        # in-session, so we don't need to refresh — refreshing would in fact
        # roll back the pending change before it's committed.
        if company is not None:
            await sync_company_as_customer(db, workspace_id, company.id)
        if company is None or not company.netsuite_internal_id:
            _mark_failure(log, "company has no NetSuite customer id")
            return log

    service = await _build_service(db, workspace_id)
    try:
        so_id = await service.create_sales_order(deal, company.netsuite_internal_id)
        deal.netsuite_sales_order_id = so_id
        deal.netsuite_customer_id = company.netsuite_internal_id
        if not deal.netsuite_internal_id:
            deal.netsuite_internal_id = so_id
        _mark_success(log, so_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("netsuite sales-order sync failed for deal %s", deal_id)
        _mark_failure(log, exc)
    return log


async def sync_payment_as_invoice(
    db: AsyncSession,
    workspace_id: UUID,
    payment_id: UUID,
) -> NetSuiteSyncLog:
    """Sync a Payment to a NetSuite Invoice."""
    log = await _create_sync_log(
        db,
        workspace_id=workspace_id,
        entity_type="payment",
        entity_id=payment_id,
        record_type="invoice",
    )

    payment = await db.get(Payment, payment_id)
    if payment is None:
        _mark_failure(log, "payment not found")
        return log

    # We need a customer id — pull it from the deal's company.
    customer_id: str | None = None
    if payment.deal_id is not None:
        deal = await db.get(Deal, payment.deal_id)
        if deal is not None and deal.netsuite_customer_id:
            customer_id = deal.netsuite_customer_id
        elif deal is not None and deal.company_id is not None:
            company = await db.get(Company, deal.company_id)
            if company is not None and company.netsuite_internal_id:
                customer_id = company.netsuite_internal_id

    if customer_id is None:
        _mark_failure(log, "no NetSuite customer id reachable from payment")
        return log

    service = await _build_service(db, workspace_id)
    try:
        invoice_id = await service.create_invoice(payment, customer_id)
        payment.netsuite_invoice_id = invoice_id
        payment.netsuite_transaction_id = invoice_id
        _mark_success(log, invoice_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("netsuite invoice sync failed for payment %s", payment_id)
        _mark_failure(log, exc)
    return log


async def sync_msa_document(
    db: AsyncSession,
    workspace_id: UUID,
    msa_id: UUID,
) -> NetSuiteSyncLog:
    """Upload an MSA PDF to File Cabinet and attach it to the Sales Order."""
    log = await _create_sync_log(
        db,
        workspace_id=workspace_id,
        entity_type="msa_document",
        entity_id=msa_id,
        record_type="file",
    )

    msa = await db.get(MsaDocument, msa_id)
    if msa is None:
        _mark_failure(log, "msa document not found")
        return log
    if msa.document_url is None:
        _mark_failure(log, "msa document has no stored file")
        return log

    file_bytes: bytes
    try:
        file_bytes = _read_local_file(msa.document_url)
    except OSError as exc:
        _mark_failure(log, f"could not read MSA file: {exc}")
        return log

    deal = await db.get(Deal, msa.deal_id)
    service = await _build_service(db, workspace_id)
    try:
        filename = msa.document_url.rsplit("/", 1)[-1]
        file_id = await service.upload_file(
            file_bytes, filename, DEFAULT_MSA_FOLDER_ID
        )
        msa.netsuite_file_id = file_id
        if deal is not None and deal.netsuite_sales_order_id:
            await service.attach_file_to_record(
                file_id, "salesOrder", deal.netsuite_sales_order_id
            )
        _mark_success(log, file_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("netsuite msa sync failed for %s", msa_id)
        _mark_failure(log, exc)
    return log


async def get_sync_status(
    db: AsyncSession,
    workspace_id: UUID,
    entity_type: str,
    entity_id: UUID,
) -> NetSuiteSyncLog | None:
    """Return the most recent NetSuiteSyncLog row for an entity."""
    result = await db.execute(
        select(NetSuiteSyncLog)
        .where(
            NetSuiteSyncLog.workspace_id == workspace_id,
            NetSuiteSyncLog.apex_entity_type == entity_type,
            NetSuiteSyncLog.apex_entity_id == entity_id,
        )
        .order_by(NetSuiteSyncLog.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def retry_failed_syncs(
    db: AsyncSession, workspace_id: UUID
) -> int:
    """Re-run every failed sync for the workspace. Returns the count attempted."""
    result = await db.execute(
        select(NetSuiteSyncLog).where(
            NetSuiteSyncLog.workspace_id == workspace_id,
            NetSuiteSyncLog.status == SyncStatus.FAILED,
        )
    )
    rows = list(result.scalars().all())

    retried = 0
    for log in rows:
        retried += 1
        et = log.apex_entity_type
        eid = log.apex_entity_id
        try:
            if et == "company":
                await sync_company_as_customer(db, workspace_id, eid)
            elif et == "deal":
                await sync_deal_as_sales_order(db, workspace_id, eid)
            elif et == "payment":
                await sync_payment_as_invoice(db, workspace_id, eid)
            elif et == "msa_document":
                await sync_msa_document(db, workspace_id, eid)
            else:
                logger.warning("retry: unknown entity_type %s", et)
        except Exception:  # noqa: BLE001 — already recorded into a new log
            logger.exception("retry sync failed for %s/%s", et, eid)
    return retried


def _read_local_file(path: str) -> bytes:
    """Read a local file. Strips a leading ``file://`` if present."""
    if path.startswith("file://"):
        path = path[len("file://") :]
    with open(path, "rb") as fh:
        return fh.read()
