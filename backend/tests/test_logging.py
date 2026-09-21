import uuid

import pytest

from app.core.logging import _resolve_request_id


@pytest.mark.parametrize(
    ("header_value", "expected"),
    [
        pytest.param(
            "3F2C8A1E-9B4D-4C6E-8F00-123456789ABC",
            "3f2c8a1e-9b4d-4c6e-8f00-123456789abc",
            id="uppercase",
        ),
        pytest.param(
            "{3f2c8a1e-9b4d-4c6e-8f00-123456789abc}",
            "3f2c8a1e-9b4d-4c6e-8f00-123456789abc",
            id="braces",
        ),
        pytest.param(
            "3f2c8a1e9b4d4c6e8f00123456789abc",
            "3f2c8a1e-9b4d-4c6e-8f00-123456789abc",
            id="no-dashes",
        ),
        pytest.param(
            "urn:uuid:3f2c8a1e-9b4d-4c6e-8f00-123456789abc",
            "3f2c8a1e-9b4d-4c6e-8f00-123456789abc",
            id="urn-prefix",
        ),
        pytest.param(
            "3f2c8a1e-9b4d-4c6e-8f00-123456789abc",
            "3f2c8a1e-9b4d-4c6e-8f00-123456789abc",
            id="already-normalized",
        ),
    ],
)
def test_reuses_a_valid_uuid_in_lowercase(header_value: str, expected: str):
    """Every spelling of a valid UUID comes back in one normalized form.

    Uppercase, braces, missing dashes and a ``urn:uuid:`` prefix are all
    accepted and returned as the same lowercase, 36-character ID; an already
    normalized value passes through unchanged. Reusing a client's ID lets
    one request be followed across systems, and normalizing it means every
    log line and response spells it the same way, so one search finds them all.
    """
    resolved = _resolve_request_id(header_value)

    assert resolved == expected


@pytest.mark.parametrize(
    "header_value",
    [
        None,
        "",
        "abc\nError fake line",
        pytest.param("x" * 100_000, id="oversized"),
        "not-a-uuid",
    ],
)
def test_generates_an_id_when_clients_sends_fake_uuid_value(header_value: str | None):
    """Anything that is not a valid UUID is replaced by a freshly generated one.

    Covers a missing header, an empty value, one containing a line break, an
    oversized one, and a malformed string. The value reaches the logs, so a
    line break could otherwise forge a second log entry and a huge value
    would bloat every line. Parsing the result checks that the replacement
    is itself a real UUID, not merely different from what was sent.
    """
    resolved = _resolve_request_id(header_value)
    assert uuid.UUID(resolved)
