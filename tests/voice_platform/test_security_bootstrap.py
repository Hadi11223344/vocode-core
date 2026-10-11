"""Tests for startup JWT hardening."""

from types import SimpleNamespace

import voice_platform.auth as auth
from voice_platform.security_bootstrap import ensure_jwt_secret


def test_ensure_jwt_secret_rejects_weak_without_dev_login():
    settings = SimpleNamespace(jwt_secret="changeme", allow_dev_login=False)
    exited = []

    ensure_jwt_secret(settings, auth, exit_fn=lambda code: exited.append(code))

    assert exited == [1]


def test_ensure_jwt_secret_mints_ephemeral_with_dev_login():
    settings = SimpleNamespace(jwt_secret="", allow_dev_login=True)
    secret = ensure_jwt_secret(settings, auth, exit_fn=lambda code: None)

    assert len(secret) >= 32
    assert settings.jwt_secret == secret
    assert auth.JWT_SECRET == secret


def test_ensure_jwt_secret_keeps_strong_secret():
    strong = "a" * 32
    settings = SimpleNamespace(jwt_secret=strong, allow_dev_login=False)
    secret = ensure_jwt_secret(settings, auth, exit_fn=lambda code: (_ for _ in ()).throw(AssertionError("exit")))

    assert secret == strong
    assert auth.JWT_SECRET == strong
