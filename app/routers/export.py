"""Workspace data export — CSV per entity plus a full ZIP bundle."""

from fastapi import APIRouter
from fastapi.responses import Response

from app.dependencies import CurrentUser, DbSession
from app.services import data_export_service

router = APIRouter(prefix="/export", tags=["export"])


def _csv_response(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/contacts")
async def export_contacts(
    db: DbSession, current_user: CurrentUser
) -> Response:
    csv = await data_export_service.export_contacts_csv(
        db, current_user.workspace_id
    )
    return _csv_response(csv, "contacts.csv")


@router.get("/deals")
async def export_deals(
    db: DbSession, current_user: CurrentUser
) -> Response:
    csv = await data_export_service.export_deals_csv(
        db, current_user.workspace_id
    )
    return _csv_response(csv, "deals.csv")


@router.get("/activities")
async def export_activities(
    db: DbSession, current_user: CurrentUser
) -> Response:
    csv = await data_export_service.export_activities_csv(
        db, current_user.workspace_id
    )
    return _csv_response(csv, "activities.csv")


@router.get("/full")
async def export_full(
    db: DbSession, current_user: CurrentUser
) -> Response:
    """Return a ZIP archive containing every CSV export for the workspace."""
    files = await data_export_service.generate_full_export(
        db, current_user.workspace_id
    )
    archive = data_export_service.bundle_zip(files)
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="apex-export.zip"'
        },
    )
