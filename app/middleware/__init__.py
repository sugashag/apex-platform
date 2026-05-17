"""HTTP middleware."""

from app.middleware.workspace import WorkspaceContextMiddleware

__all__ = ["WorkspaceContextMiddleware"]
