"""Startup utility tests for voice_platform.main."""

import socket
import sys
import types

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from voice_platform.main import _can_bind_port
from voice_platform.telephony.inbound_handler import _validate_twilio_webhook_signature


def test_can_bind_port_when_free():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()

    assert _can_bind_port("127.0.0.1", free_port) is True


def test_can_bind_port_when_in_use():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    in_use_port = sock.getsockname()[1]

    try:
        assert _can_bind_port("127.0.0.1", in_use_port) is False
    finally:
        sock.close()


def _build_request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/inbound_call",
        "query_string": b"",
        "headers": headers or [],
        "scheme": "https",
        "server": ("example.com", 443),
        "client": ("127.0.0.1", 12345),
    }

    async def _receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, _receive)


@pytest.mark.asyncio
async def test_validate_twilio_signature_missing_header_rejected_when_required(monkeypatch):
    from voice_platform import main

    monkeypatch.setattr(main.settings, "twilio_auth_token", "token")
    monkeypatch.setattr(main.settings, "require_twilio_webhook_signature", True)
    monkeypatch.setattr(main.settings, "validate_twilio_webhook_if_present", True)

    req = _build_request()
    with pytest.raises(HTTPException) as exc:
        await _validate_twilio_webhook_signature(req, {"CallSid": "CA123"})

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_validate_twilio_signature_invalid_header_rejected(monkeypatch):
    from voice_platform import main

    fake_module = types.ModuleType("twilio.request_validator")

    class _FakeValidator:
        def __init__(self, token: str):
            self.token = token

        def validate(self, url: str, fields: dict[str, str], signature: str) -> bool:
            return False

    fake_module.RequestValidator = _FakeValidator
    monkeypatch.setitem(sys.modules, "twilio.request_validator", fake_module)

    monkeypatch.setattr(main.settings, "twilio_auth_token", "token")
    monkeypatch.setattr(main.settings, "require_twilio_webhook_signature", False)
    monkeypatch.setattr(main.settings, "validate_twilio_webhook_if_present", True)

    req = _build_request(headers=[(b"x-twilio-signature", b"bad")])
    with pytest.raises(HTTPException) as exc:
        await _validate_twilio_webhook_signature(req, {"CallSid": "CA123"})

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_validate_twilio_signature_valid_header_allowed(monkeypatch):
    from voice_platform import main

    fake_module = types.ModuleType("twilio.request_validator")

    class _FakeValidator:
        def __init__(self, token: str):
            self.token = token

        def validate(self, url: str, fields: dict[str, str], signature: str) -> bool:
            return signature == "good" and fields.get("CallSid") == "CA123"

    fake_module.RequestValidator = _FakeValidator
    monkeypatch.setitem(sys.modules, "twilio.request_validator", fake_module)

    monkeypatch.setattr(main.settings, "twilio_auth_token", "token")
    monkeypatch.setattr(main.settings, "require_twilio_webhook_signature", False)
    monkeypatch.setattr(main.settings, "validate_twilio_webhook_if_present", True)

    req = _build_request(headers=[(b"x-twilio-signature", b"good")])
    await _validate_twilio_webhook_signature(req, {"CallSid": "CA123"})
