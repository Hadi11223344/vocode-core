"""Tests for voice_platform.auth — JWT creation and verification."""

from datetime import datetime, timedelta, timezone

import pytest

from voice_platform.auth import (
    JWT_ALGORITHM,
    JWT_SECRET,
    TOKEN_EXPIRY_HOURS,
    create_access_token,
    decode_access_token,
)


class TestCreateAccessToken:
    def test_creates_valid_token(self):
        token = create_access_token(user_id=1, email="a@b.com", role="user")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_expected_claims(self):
        token = create_access_token(user_id=42, email="admin@test.com", role="admin")
        payload = decode_access_token(token)
        assert payload["sub"] == "42"
        assert payload["email"] == "admin@test.com"
        assert payload["role"] == "admin"
        assert "exp" in payload
        assert "iat" in payload

    def test_different_users_get_different_tokens(self):
        t1 = create_access_token(user_id=1, email="a@b.com", role="user")
        t2 = create_access_token(user_id=2, email="c@d.com", role="user")
        assert t1 != t2


class TestDecodeAccessToken:
    def test_roundtrip(self):
        token = create_access_token(user_id=7, email="test@x.com", role="user")
        payload = decode_access_token(token)
        assert payload["sub"] == "7"

    def test_invalid_token_raises(self):
        with pytest.raises(ValueError, match="Invalid token"):
            decode_access_token("not.a.valid.jwt")

    def test_tampered_token_raises(self):
        token = create_access_token(user_id=1, email="a@b.com", role="user")
        # Split into header.payload.signature and corrupt the signature
        parts = token.split(".")
        assert len(parts) == 3, "JWT must have 3 parts"
        # Replace signature with a clearly different one
        parts[2] = "AAAA" + parts[2][4:]
        tampered = ".".join(parts)
        with pytest.raises(ValueError, match="Invalid token"):
            decode_access_token(tampered)

    def test_expired_token_raises(self):
        from jose import jwt as jose_jwt

        payload = {
            "sub": "1",
            "email": "a@b.com",
            "role": "user",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        expired_token = jose_jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        with pytest.raises(ValueError, match="Invalid token"):
            decode_access_token(expired_token)
