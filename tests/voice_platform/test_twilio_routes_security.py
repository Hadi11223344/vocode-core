"""Security tests for Twilio mutating route credential requirements."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_purchase_number_requires_user_twilio_credentials(client: AsyncClient):
    response = await client.post(
        "/api/twilio/numbers/purchase",
        json={"phone_number": "+12025550123"},
    )

    assert response.status_code == 403
    assert "credentials" in response.json()["detail"].lower()


async def test_outbound_call_requires_user_twilio_credentials(client: AsyncClient):
    response = await client.post(
        "/api/twilio/calls/outbound",
        json={"to_phone": "+12025550123"},
    )

    assert response.status_code == 403
    assert "credentials" in response.json()["detail"].lower()
