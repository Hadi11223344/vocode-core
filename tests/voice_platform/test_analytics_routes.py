"""Tests for analytics transcript redaction helpers."""

from voice_platform.api.analytics_routes import _redact_sensitive_text


def test_redact_sensitive_text_redacts_common_pii():
    text = (
        "Customer email is user@example.com and phone is +1 (202) 555-0101. "
        "SSN 123-45-6789 and card 4242 4242 4242 4242 were spoken."
    )

    redacted = _redact_sensitive_text(text)

    assert "user@example.com" not in redacted
    assert "+1 (202) 555-0101" not in redacted
    assert "123-45-6789" not in redacted
    assert "4242 4242 4242 4242" not in redacted

    assert "[REDACTED_EMAIL]" in redacted
    assert "[REDACTED_PHONE]" in redacted
    assert "[REDACTED_SSN]" in redacted
    assert "[REDACTED_CARD]" in redacted
