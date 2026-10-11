#!/usr/bin/env python3
"""Validate VOIA local setup for Tier 0 (playground) and Tier 1 (live call).

Usage (repo root):
  python scripts/check_setup.py
  python scripts/check_setup.py --env voice_platform/.env
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse


def _load_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            values[key] = value
    return values


def _get(env_file: Dict[str, str], key: str, default: str = "") -> str:
    return (os.environ.get(key) or env_file.get(key) or default).strip()


def _tcp_ok(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _parse_redis(url: str) -> Tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    return host, port


def _parse_db(url: str) -> Optional[Tuple[str, int]]:
    if not url or url.startswith("sqlite"):
        return None
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if not parsed.hostname:
        return None
    return parsed.hostname, parsed.port or 5432


def main() -> int:
    parser = argparse.ArgumentParser(description="Check VOIA Tier 0/1 setup")
    parser.add_argument(
        "--env",
        default="voice_platform/.env",
        help="Path to .env (default: voice_platform/.env)",
    )
    args = parser.parse_args()
    env_path = Path(args.env)
    file_vals = _load_env_file(env_path)

    print("VOIA setup check")
    print(f"  env file: {env_path} ({'found' if env_path.is_file() else 'MISSING — copy .env.example'})")
    print()

    errors: List[str] = []
    warnings: List[str] = []

    if not env_path.is_file():
        errors.append("Create voice_platform/.env from voice_platform/.env.example")

    allow_dev = _get(file_vals, "ALLOW_DEV_LOGIN", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if allow_dev:
        print("  [ok] ALLOW_DEV_LOGIN=true (Dev Login enabled)")
    else:
        google = _get(file_vals, "GOOGLE_CLIENT_ID")
        if google:
            print("  [ok] Google OAuth configured (Dev Login off)")
        else:
            errors.append(
                "Set ALLOW_DEV_LOGIN=true for local Tier 0, or configure GOOGLE_CLIENT_ID"
            )

    llm_keys = [
        "OPENROUTER_API_KEY",
        "GROQ_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "COMMANDCODE_API_KEY",
    ]
    if any(_get(file_vals, k) for k in llm_keys):
        print("  [ok] At least one LLM API key present")
    else:
        openai_base = _get(file_vals, "OPENAI_API_BASE")
        if openai_base:
            print(f"  [ok] OPENAI_API_BASE set ({openai_base}) — ensure a local/compatible LLM is running")
        else:
            errors.append(
                "Tier 0 needs an LLM key (OPENROUTER_API_KEY, GROQ_API_KEY, OPENAI_API_KEY, …) "
                "or OPENAI_API_BASE for Ollama"
            )

    jwt = _get(file_vals, "JWT_SECRET", "voia-fyp-secret-change-in-production")
    weak = {"", "change-me-to-a-random-secret", "voia-fyp-secret-change-in-production"}
    if jwt in weak or len(jwt) < 32:
        warnings.append(
            "JWT_SECRET is weak/default — fine for local Tier 0; change before production"
        )
    else:
        print("  [ok] JWT_SECRET looks non-default")

    redis_url = _get(file_vals, "REDIS_URL", "redis://localhost:6380")
    r_host, r_port = _parse_redis(redis_url)
    if _tcp_ok(r_host, r_port):
        print(f"  [ok] Redis reachable at {r_host}:{r_port}")
    else:
        errors.append(
            f"Redis not reachable at {r_host}:{r_port} — "
            "run: docker compose up -d redis  (host port 6380)"
        )
        if r_port == 6379:
            warnings.append(
                "Compose maps Redis to host port 6380; .env may need REDIS_URL=redis://localhost:6380"
            )

    db_url = _get(file_vals, "DATABASE_URL")
    db_ep = _parse_db(db_url)
    if db_ep:
        d_host, d_port = db_ep
        if _tcp_ok(d_host, d_port):
            print(f"  [ok] Postgres reachable at {d_host}:{d_port}")
        else:
            warnings.append(
                f"DATABASE_URL set but Postgres not reachable at {d_host}:{d_port} "
                "(Compose host port is 5433)"
            )
    else:
        print("  [ok] DATABASE_URL unset — SQLite fallback for local app process")

    # Tier 1 signals
    twilio = all(
        _get(file_vals, k)
        for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER")
    )
    deepgram = bool(_get(file_vals, "DEEPGRAM_API_KEY"))
    if twilio and deepgram:
        print("  [ok] Tier 1 keys present (Twilio + Deepgram)")
    else:
        missing = []
        if not twilio:
            missing.append("Twilio")
        if not deepgram:
            missing.append("Deepgram")
        print(f"  [--] Tier 1 not ready yet (optional): missing {', '.join(missing)}")

    print()
    for w in warnings:
        print(f"  WARN: {w}")
    for e in errors:
        print(f"  FAIL: {e}")

    if errors:
        print("\nResult: not ready for Tier 0 playground")
        return 1

    print("\nResult: ready for Tier 0 playground")
    print("  → docker compose --profile playground up -d")
    print("  → http://localhost:3001  (Dev Login)")
    if twilio and deepgram:
        print("  → Tier 1 live call keys look set; configure BASE_URL/ngrok for webhooks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
