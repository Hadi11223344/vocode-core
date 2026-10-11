"""Startup security helpers (JWT hardening, etc.)."""

from __future__ import annotations

import os
import secrets
import sys
from typing import Any

from loguru import logger

WEAK_JWT_DEFAULTS = frozenset(
    {
        "",
        "voia-fyp-secret-change-in-production",
        "voia-fyp-secret-2026-change-in-production",
        "change-me-to-a-random-secret",
        "secret",
        "changeme",
        "super_secret_string_for_local_dev",
    }
)


def ensure_jwt_secret(settings: Any, auth_module: Any, *, exit_fn=sys.exit) -> str:
    """Ensure a usable JWT secret.

    - Production / non-dev-login: refuse weak or short secrets.
    - ALLOW_DEV_LOGIN: mint an ephemeral secret for this process when unset/weak.
    """
    jwt_value = (getattr(settings, "jwt_secret", None) or "").strip()
    if jwt_value not in WEAK_JWT_DEFAULTS and len(jwt_value) >= 32:
        auth_module.JWT_SECRET = jwt_value
        if not os.environ.get("REFRESH_TOKEN_SECRET"):
            auth_module.REFRESH_TOKEN_SECRET = jwt_value + "-refresh"
        return jwt_value

    if not getattr(settings, "allow_dev_login", False):
        logger.error(
            "❌ JWT_SECRET is missing, weak, or shorter than 32 characters. "
            "Refusing to start. Generate one with: "
            'python -c "import secrets; print(secrets.token_hex(32))"'
        )
        exit_fn(1)
        return jwt_value  # pragma: no cover

    jwt_value = secrets.token_hex(32)
    settings.jwt_secret = jwt_value
    auth_module.JWT_SECRET = jwt_value
    if not os.environ.get("REFRESH_TOKEN_SECRET"):
        auth_module.REFRESH_TOKEN_SECRET = jwt_value + "-refresh"
    logger.warning(
        "⚠️  Generated ephemeral JWT_SECRET for this process "
        "(ALLOW_DEV_LOGIN=true). Tokens reset on restart. "
        "Set JWT_SECRET in .env for stable local tokens / any shared host."
    )
    return jwt_value
