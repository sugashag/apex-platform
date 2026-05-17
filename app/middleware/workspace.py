"""Workspace isolation middleware.

Extracts `workspace_id` from the JWT (if present) and stashes it on
`request.state.workspace_id`. Downstream queries should filter by this value
to guarantee tenant isolation, in addition to per-route auth dependencies.

This middleware does NOT reject requests — auth enforcement is handled by
the `get_current_user` dependency. Its job is purely to surface the
workspace context for logging, audit, and query filters.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.services.auth import JWTError, decode_access_token


class WorkspaceContextMiddleware(BaseHTTPMiddleware):
    """Populate `request.state.workspace_id` from the Bearer token, if any."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.workspace_id = None
        request.state.user_id = None

        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            try:
                payload = decode_access_token(token)
                ws_raw = payload.get("workspace_id")
                user_raw = payload.get("sub")
                if ws_raw:
                    request.state.workspace_id = UUID(ws_raw)
                if user_raw:
                    request.state.user_id = UUID(user_raw)
            except (JWTError, ValueError):
                # Bad token — leave context empty; auth dependency will reject.
                pass

        return await call_next(request)
