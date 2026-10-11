"""Tests for websocket auth token extraction behavior."""

from types import SimpleNamespace
from typing import Any, cast

from voice_platform.middleware.auth_middleware import _extract_ws_token, _wants_bearer_subprotocol


def _ws(headers: dict[str, str] | None = None, query: dict[str, str] | None = None):
    return SimpleNamespace(headers=headers or {}, query_params=query or {})


def test_extract_ws_token_prefers_authorization_header():
    websocket = _ws(
        headers={"authorization": "Bearer header-token", "sec-websocket-protocol": "bearer,proto-token"},
        query={"token": "query-token"},
    )

    assert _extract_ws_token(cast(Any, websocket)) == "header-token"


def test_extract_ws_token_uses_subprotocol_when_header_absent():
    websocket = _ws(headers={"sec-websocket-protocol": "bearer,proto-token"})

    assert _extract_ws_token(cast(Any, websocket)) == "proto-token"


def test_extract_ws_token_does_not_use_query_param_by_default():
    websocket = _ws(query={"token": "query-token"})

    assert _extract_ws_token(cast(Any, websocket)) is None


def test_extract_ws_token_can_use_query_param_when_enabled():
    websocket = _ws(query={"token": "query-token"})

    assert _extract_ws_token(cast(Any, websocket), allow_query_fallback=True) == "query-token"


def test_extract_ws_token_returns_none_when_missing():
    websocket = _ws()

    assert _extract_ws_token(cast(Any, websocket)) is None


def test_wants_bearer_subprotocol_true_when_offered_first():
    websocket = _ws(headers={"sec-websocket-protocol": "bearer,abc.def.ghi"})

    assert _wants_bearer_subprotocol(cast(Any, websocket)) is True


def test_wants_bearer_subprotocol_false_when_not_offered():
    websocket = _ws(headers={"sec-websocket-protocol": "json,chat"})

    assert _wants_bearer_subprotocol(cast(Any, websocket)) is False
