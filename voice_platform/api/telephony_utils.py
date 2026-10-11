"""Shared helpers for Twilio callback URL handling."""

from typing import Optional

from fastapi import HTTPException, status


def normalize_public_base_url(base_url: str) -> str:
    """Strip a URL down to the host portion expected by Twilio callback builders."""
    return base_url.replace("https://", "").replace("http://", "").rstrip("/")


def resolve_public_base_url(*candidates: Optional[str]) -> str:
    """Return the first non-localhost base URL candidate or raise a service error."""
    for candidate in candidates:
        if not candidate:
            continue

        clean = normalize_public_base_url(candidate.strip())
        hostname = clean.split("/", 1)[0].split(":", 1)[0].lower().strip("[]")

        if not hostname:
            continue
        if hostname == "localhost" or hostname == "0.0.0.0" or hostname == "::1":
            continue
        if hostname.startswith("127."):
            continue

        return clean

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "Twilio webhook base URL is not configured or publicly reachable. "
            "Set BASE_URL or use ngrok."
        ),
    )