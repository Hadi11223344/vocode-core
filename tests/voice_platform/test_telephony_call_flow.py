"""Regression tests for inbound/outbound telephony call flow."""

import json
import sys
import types
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import vocode.streaming.telephony.client.twilio_client as twilio_client_module
from vocode.streaming.models.telephony import TwilioConfig
from vocode.streaming.telephony.client.twilio_client import TwilioClient
from voice_platform.api import campaign_routes, twilio_routes
from voice_platform.api.campaign_routes import Campaign, CampaignContact, _execute_campaign
from voice_platform.api.telephony_utils import resolve_public_base_url
from voice_platform.database import UserApiKey
from voice_platform.telephony import inbound_handler

pytestmark = pytest.mark.asyncio


class _FakeResponse:
    ok = True
    status = 200
    reason = "OK"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return {"sid": "CA1234567890abcdef1234567890abcd"}


class _FakeSession:
    def __init__(self, captured):
        self.captured = captured

    def post(self, url, auth=None, data=None):
        self.captured["url"] = url
        self.captured["data"] = data
        return _FakeResponse()


class _FakeRequestor:
    def __init__(self, captured):
        self.captured = captured

    def get_session(self):
        return _FakeSession(self.captured)


class _FakeCallUpdater:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeCallResource:
    def __init__(self, captured):
        self.captured = captured

    def update(self, **kwargs):
        self.captured["update_kwargs"] = kwargs
        return _FakeCallUpdater()


class _FakeClient:
    def __init__(self, captured):
        self.captured = captured

    def calls(self, sid):
        self.captured["sid"] = sid
        return _FakeCallResource(self.captured)


class _FakeCalls:
    def __init__(self, captured):
        self.captured = captured

    def create(self, **kwargs):
        self.captured["create_kwargs"] = kwargs
        return SimpleNamespace(sid="CA1234567890abcdef1234567890abcd", status="queued")

    def __call__(self, sid):
        self.captured["fetch_sid"] = sid
        return SimpleNamespace(fetch=self.fetch)

    def fetch(self):
        raise RuntimeError("poll exploded")


class _FakeIncomingPhoneNumbers:
    def list(self, limit=1):
        return [SimpleNamespace(phone_number="+18313188656")]


class _FakeTwilioClient:
    def __init__(self, captured):
        self.calls = _FakeCalls(captured)
        self.incoming_phone_numbers = _FakeIncomingPhoneNumbers()


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_resolve_public_base_url_prefers_public_candidate():
    result = resolve_public_base_url("https://example.ngrok-free.app", "http://localhost:3000")

    assert result == "example.ngrok-free.app"


def test_resolve_public_base_url_rejects_localhost_only():
    with pytest.raises(HTTPException) as exc:
        resolve_public_base_url("http://localhost:3000")

    assert exc.value.status_code == 503


async def test_twilio_client_create_call_preserves_e164_numbers(monkeypatch):
    captured = {}
    monkeypatch.setattr(twilio_client_module, "AsyncRequestor", lambda: _FakeRequestor(captured))

    client = TwilioClient(
        base_url="example.ngrok-free.app",
        maybe_twilio_config=TwilioConfig(
            account_sid="AC1234567890abcdef1234567890abcd",
            auth_token="auth-token",
        ),
    )

    await client.create_call(
        conversation_id="conv-123",
        to_phone="+12025550123",
        from_phone="+18313188656",
    )

    assert captured["data"]["To"] == "+12025550123"
    assert captured["data"]["From"] == "+18313188656"


async def test_transfer_call_uses_runtime_public_base_url(monkeypatch):
    captured = {}

    async def _fake_get_twilio_client(*args, **kwargs):
        return _FakeClient(captured), "AC1234567890abcdef1234567890abcd", "token", "+18313188656"

    monkeypatch.setattr(twilio_routes, "_get_twilio_client", _fake_get_twilio_client)
    monkeypatch.setattr(twilio_routes.settings, "base_url", "http://localhost:3000")

    result = await twilio_routes.transfer_call(
        request=twilio_routes.TransferCallRequest(
            call_sid="CA1234567890abcdef1234567890abcd",
            destination="+12025550123",
        ),
        req=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(base_url="https://example.ngrok-free.app"))),
        user=SimpleNamespace(id=1),
        db=SimpleNamespace(),
    )

    assert result["success"] is True
    expected_url = (
        "https://example.ngrok-free.app/api/twilio/transfer/dial"
        "?To=%2B12025550123&conversation_id=CA1234567890abcdef1234567890abcd"
    )
    assert captured["update_kwargs"]["url"] == expected_url
    assert captured["update_kwargs"]["fallback_url"] == expected_url


async def test_campaign_poll_failure_marks_contact_failed(monkeypatch, db_session, test_user, test_agent):
    campaign = Campaign(
        user_id=test_user.id,
        name="Follow-up campaign",
        description="Campaign used to verify poll failures are not treated as success.",
        agent_id=test_agent.id,
        from_phone="+18313188656",
        max_concurrent_calls=1,
        call_interval_secs=0,
        max_retries=1,
        max_call_duration_secs=35,
        total_contacts=1,
    )
    db_session.add(campaign)
    await db_session.flush()

    contact = CampaignContact(
        campaign_id=campaign.id,
        phone_number="+12025550123",
        name="Example Lead",
        status="pending",
    )
    db_session.add(contact)
    await db_session.commit()

    captured = {}

    async def _fake_get_user_twilio_credentials(session, user_id):
        return "AC1234567890abcdef1234567890abcd", "auth-token"

    async def _fake_sleep(delay):
        return None

    def _fake_twilio_client_factory(account_sid, auth_token):
        return _FakeTwilioClient(captured)

    monkeypatch.setattr(campaign_routes, "_get_user_twilio_credentials", _fake_get_user_twilio_credentials)
    monkeypatch.setattr(campaign_routes.asyncio, "sleep", _fake_sleep)

    import twilio.rest as twilio_rest

    monkeypatch.setattr(twilio_rest, "Client", _fake_twilio_client_factory)
    monkeypatch.setattr(campaign_routes, "async_session", lambda: _AsyncSessionContext(db_session))

    await _execute_campaign(campaign.id, test_user.id, "example.ngrok-free.app")

    updated_contact = (await db_session.execute(select(CampaignContact).where(CampaignContact.id == contact.id))).scalar_one()
    updated_campaign = (await db_session.execute(select(Campaign).where(Campaign.id == campaign.id))).scalar_one()

    assert captured["create_kwargs"]["url"] == "https://example.ngrok-free.app/inbound_call"
    assert captured["create_kwargs"]["status_callback"] == "https://example.ngrok-free.app/call_status"
    assert updated_contact.status == "failed"
    assert updated_contact.call_outcome == "poll_error"
    assert "Could not poll call status" in (updated_contact.last_error or "")
    assert updated_campaign.failed_contacts == 1
    assert updated_campaign.completed_contacts == 0


async def test_inbound_routing_uses_twilio_key_metadata(db_session, test_user, test_agent):
    twilio_key = UserApiKey(
        user_id=test_user.id,
        service="twilio",
        api_key="AC1234567890abcdef1234567890abcd",
        api_secret="auth-token",
        metadata_json=json.dumps({
            "phone_number": "+15551234567",
            "account_sid": "AC1234567890abcdef1234567890abcd",
        }),
        label="Primary Twilio",
        is_active=True,
    )
    db_session.add(twilio_key)
    await db_session.commit()

    user_id, agent_id, greeting_override, routing_source, phone_number_id = await inbound_handler._resolve_inbound_routing_context(
        db_session,
        "+15551234567",
    )

    assert user_id == test_user.id
    assert agent_id == test_agent.id
    assert greeting_override is None
    assert routing_source == "twilio_key"
    assert phone_number_id is None
