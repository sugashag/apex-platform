"""Role-based access control dependencies.

Used as a FastAPI dependency on routes that require a specific role. The
underlying check is intentionally simple: the caller's role must be one of
the allowed roles. ``UserRole.ADMIN`` is always sufficient.
"""

from collections.abc import Awaitable, Callable, Iterable

from fastapi import Depends, HTTPException, status

from app.dependencies import CurrentUser
from app.models.user import User, UserRole

RoleDependency = Callable[..., Awaitable[User]]


def require_role(*roles: str) -> RoleDependency:
    """Return a FastAPI dependency enforcing that the caller has one of ``roles``.

    The check is case-insensitive on the role *value* (``admin``, ``manager``,
    ``rep``, ``readonly``). ``UserRole.ADMIN`` is always accepted regardless
    of whether it appears in ``roles``.
    """
    allowed: set[str] = {r.lower() for r in roles}
    allowed.add(UserRole.ADMIN.value)

    async def _checker(current_user: CurrentUser) -> User:
        if current_user.role.value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Insufficient role: this action requires "
                    f"{_format_roles(allowed)}"
                ),
            )
        return current_user

    return _checker


def _format_roles(roles: Iterable[str]) -> str:
    sorted_roles = sorted(roles)
    return ", ".join(sorted_roles)


def require_admin() -> RoleDependency:
    return require_role(UserRole.ADMIN.value)


def require_manager_or_above() -> RoleDependency:
    return require_role(UserRole.ADMIN.value, UserRole.MANAGER.value)


AdminUser = Depends(require_admin())
ManagerOrAbove = Depends(require_manager_or_above())
