"""Pipeline stage helpers — including default-stage seeding for new workspaces."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_stage import PipelineStage

DEFAULT_STAGES: list[dict[str, object]] = [
    {
        "name": "New Lead", "position": 1,
        "probability_default": 10, "is_won": False, "is_lost": False,
    },
    {
        "name": "Qualified", "position": 2,
        "probability_default": 30, "is_won": False, "is_lost": False,
    },
    {
        "name": "Proposal Sent", "position": 3,
        "probability_default": 50, "is_won": False, "is_lost": False,
    },
    {
        "name": "Negotiation", "position": 4,
        "probability_default": 70, "is_won": False, "is_lost": False,
    },
    {
        "name": "Closed Won", "position": 5,
        "probability_default": 100, "is_won": True, "is_lost": False,
    },
    {
        "name": "Closed Lost", "position": 6,
        "probability_default": 0, "is_won": False, "is_lost": True,
    },
]


async def seed_default_pipeline_stages(
    db: AsyncSession,
    workspace_id: UUID,
) -> list[PipelineStage]:
    """Insert the default six-stage pipeline for a freshly created workspace.

    Caller is responsible for committing the surrounding transaction.
    """
    stages = [
        PipelineStage(workspace_id=workspace_id, **stage)
        for stage in DEFAULT_STAGES
    ]
    db.add_all(stages)
    return stages
