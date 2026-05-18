"""FastAPI dependency-injection providers."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User, UserRole
from app.services.auth import JWTError, decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    db: DbSession,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> User:
    """Decode the bearer token, load the user, and inject it.

    Raises 401 on missing/invalid token or inactive user.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if token is None:
        raise credentials_error

    try:
        payload = decode_access_token(token)
        user_id_raw = payload.get("sub")
        if not user_id_raw:
            raise credentials_error
    except JWTError as exc:
        raise credentials_error from exc

    result = await db.execute(select(User).where(User.id == user_id_raw))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_error
    return user


async def get_current_user_or_api_key(
    db: DbSession,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> User:
    """Accept either a Bearer JWT or an ``X-API-Key`` header.

    When the API key is valid the workspace's first active admin user is
    returned so downstream code can treat the request like a normal admin call
    (every domain query is scoped by ``current_user.workspace_id``).
    """
    if x_api_key:
        # Imported here to avoid a circular import — api_key_service depends on
        # the same models the dependency injector imports.
        from app.services.api_key_service import validate_api_key

        api_key = await validate_api_key(db, x_api_key)
        if api_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired API key",
                headers={"WWW-Authenticate": "ApiKey"},
            )
        admin_result = await db.execute(
            select(User)
            .where(
                User.workspace_id == api_key.workspace_id,
                User.is_active.is_(True),
                User.role == UserRole.ADMIN,
            )
            .order_by(User.created_at.asc())
            .limit(1)
        )
        admin = admin_result.scalar_one_or_none()
        if admin is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key workspace has no active admin user",
            )
        return admin

    return await get_current_user(db, token)


CurrentUser = Annotated[User, Depends(get_current_user_or_api_key)]
CurrentUserOrApiKey = CurrentUser
