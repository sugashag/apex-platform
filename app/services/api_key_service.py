"""API-key creation and validation.

Full keys look like ``apex_live_<32-char-token>``. Only the bcrypt hash of the
full key is persisted; the plaintext is returned exactly once at create time.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.services.auth import hash_password, verify_password

KEY_PREFIX = "apex_live_"
KEY_RANDOM_LENGTH = 32


def _generate_key() -> tuple[str, str]:
    """Return ``(prefix, full_key)``. ``full_key`` is ``prefix + token``."""
    token = secrets.token_urlsafe(KEY_RANDOM_LENGTH)[:KEY_RANDOM_LENGTH]
    return KEY_PREFIX, f"{KEY_PREFIX}{token}"


async def create_api_key(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    created_by_id: UUID,
    name: str,
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
) -> tuple[ApiKey, str]:
    """Create an API key. Returns ``(record, full_key)``.

    The full plaintext key is returned **once** and never persisted in cleartext
    again. Callers must surface it to the user immediately or it is lost.
    """
    prefix, full_key = _generate_key()
    api_key = ApiKey(
        workspace_id=workspace_id,
        created_by_id=created_by_id,
        name=name,
        key_prefix=prefix,
        key_hash=hash_password(full_key),
        scopes=scopes,
        expires_at=expires_at,
    )
    db.add(api_key)
    await db.flush()
    return api_key, full_key


async def validate_api_key(db: AsyncSession, full_key: str) -> ApiKey | None:
    """Look up an API key by its plaintext value.

    On success the key's ``last_used_at`` is bumped and the record is returned.
    Returns ``None`` for unknown / inactive / expired keys.
    """
    if not full_key.startswith(KEY_PREFIX):
        return None

    result = await db.execute(
        select(ApiKey).where(
            ApiKey.key_prefix == KEY_PREFIX,
            ApiKey.is_active.is_(True),
        )
    )
    candidates = list(result.scalars().all())
    now = datetime.now(tz=UTC)
    for candidate in candidates:
        if candidate.expires_at is not None and candidate.expires_at <= now:
            continue
        if verify_password(full_key, candidate.key_hash):
            candidate.last_used_at = now
            await db.flush()
            return candidate
    return None


__all__ = ["KEY_PREFIX", "create_api_key", "validate_api_key"]
