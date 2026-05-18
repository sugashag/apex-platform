"""Tiny template renderer for workflow/sequence string substitution.

Supports `{{var}}` and dotted lookups like `{{contact.first_name}}`. The
renderer is intentionally minimal — no expressions, conditionals, or loops —
because action_config templates run on potentially-untrusted JSON data and
the surface area of a real template engine isn't worth the risk.

Unknown variables render as the empty string, never raise.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

_TEMPLATE_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def resolve_path(path: str, context: Mapping[str, Any]) -> Any:
    """Walk `a.b.c` against nested dicts/objects. Returns None on miss."""
    current: Any = context
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, Mapping):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def render_template(template: str | None, context: Mapping[str, Any]) -> str:
    """Substitute `{{var}}` references in `template` using `context`.

    Returns the empty string when ``template`` is None so callers don't have
    to special-case empty templates.
    """
    if template is None:
        return ""

    def _replace(match: re.Match[str]) -> str:
        path = match.group(1)
        try:
            value = resolve_path(path, context)
        except Exception:  # noqa: BLE001 — defensive: rendering must never raise
            logger.exception("template lookup failed for %s", path)
            return ""
        if value is None:
            return ""
        return str(value)

    return _TEMPLATE_VAR_RE.sub(_replace, template)
