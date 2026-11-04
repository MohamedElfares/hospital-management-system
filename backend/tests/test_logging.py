import logging
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.logging import _resolve_request_id

REQUEST_ID = "3f2c8a1e-9b4d-4c6e-8f00-123456789abc"


def _request_log_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the lines the request middleware logged during the test.

    Only records from ``app.core.logging`` count: the test client logs every
    request too, with its full URL, so its lines must never be mistaken for
    the application's. Tests make the request inside
    ``caplog.at_level(logging.INFO, logger="app.core.logging")``, so the
    lines are recorded even when ``LOG_LEVEL`` is set higher.

    Args:
        caplog: pytest's log capture for the running test.

    Returns:
        The middleware's messages, in the order they were logged.
    """
    return [record.getMessage() for record in caplog.records if record.name == "app.core.logging"]


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
def test_reuses_a_valid_uuid_in_lowercase(header_value: str, expected: str) -> None:
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
def test_generates_an_id_when_clients_sends_fake_uuid_value(header_value: str | None) -> None:
    """Anything that is not a valid UUID is replaced by a freshly generated one.

    Covers a missing header, an empty value, one containing a line break, an
    oversized one, and a malformed string. The value reaches the logs, so a
    line break could otherwise forge a second log entry and a huge value
    would bloat every line. Parsing the result checks that the replacement
    is itself a real UUID, not merely different from what was sent.
    """
    resolved = _resolve_request_id(header_value)
    assert uuid.UUID(resolved)


def test_request_log_line_has_the_plan_fields_and_no_query_string(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A request is logged as one line with the plan's fields, without its query string.

    Plan §12 asks for the request ID, user ID, method, path, status, and
    duration, so a request a user reports can be found, and the query
    string stays out because it can carry patient names or phone numbers.
    The whole line must match, so a missing field and a leaked parameter
    both fail. No token is sent, so the user ID is ``None``.
    """
    with caplog.at_level(logging.INFO, logger="app.core.logging"):
        response = client.get(
            "/health/live?name=Jane&phone=0501234567",
            headers={"X-Request-ID": REQUEST_ID},
        )

    lines = _request_log_lines(caplog)

    assert response.status_code == 200
    assert len(lines) == 1
    assert re.fullmatch(
        rf"request_id={REQUEST_ID} user_id=None method=GET path=/health/live "
        r"status=200 duration_ms=\d+\.\d",
        lines[0],
    )
