"""Tests for the request ID and the request log line in ``app/core/logging.py``.

``_resolve_request_id`` chooses each request's ID: a UUID the client sends
is reused in one normalized form, and anything else is replaced by a new
one. ``request_context_middleware`` writes one ``key=value`` line per
request with the fields plan §12 asks for: the request ID, the signed-in
user's ID, the method, the path, the status, and the duration. The unit
tests call ``_resolve_request_id`` directly. The line tests send requests
through the whole application and read the middleware's records with
``caplog``: they check what each field holds, what must stay out of the
line (the query string, raw control characters, and a user from another
request), and which requests name a user. The ``X-Request-ID`` header is
tested in ``tests/test_errors.py``.
"""

# Log levels, for capturing the middleware's INFO records whatever LOG_LEVEL is.
import logging

# Matches the whole request log line against the plan's fields, and each generated ID
# against the one form every request ID takes.
import re

# Test framework: fixtures, parametrize, the usefixtures mark, and caplog's type.
import pytest

# Builds a valid user, so the fixture sets nothing the tests don't need.
from factories import make_user

# Type of the app fixture, which the gated route is added to.
from fastapi import FastAPI

# Sends requests through the whole application, middleware included.
from fastapi.testclient import TestClient

# Type of the db_session fixture, which saves the user and its pending password change.
from sqlalchemy.orm import Session

# The gated dependency: the signed-in user, refused while a password change is pending.
from app.api.deps import CurrentUser

# Chooses each request's ID; the unit tests call it directly.
from app.core.logging import _resolve_request_id

# Signs an access token for the user, as sign-in does, so no test needs a password.
from app.core.security import create_access_token

# Type of the user fixture.
from app.modules.users.models import User

# Exists only on a test's own application, added by the gated_route fixture.
GATED_URL = "/api/v1/test/gated"

# The plainest route that needs a signed-in user, and it lets one through whose password
# change is pending, as every new account's is.
ME_URL = "/api/v1/auth/me"

# Already in the normalized form, so the line carries it unchanged.
REQUEST_ID = "3f2c8a1e-9b4d-4c6e-8f00-123456789abc"

# The one form every request ID takes, a lowercase UUID with dashes, as _resolve_request_id
# promises. It is written out rather than built with uuid, so the test doesn't share the
# logic of the code it checks.
REQUEST_ID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


@pytest.fixture
def user(db_session: Session) -> User:
    """Save an active user for the signed-in requests.

    The tests sign the user's access token directly, so the password never
    matters and ``make_user``'s default hash is enough. Like every new
    account, the user must change their password, which is the database's
    default; ``/auth/me`` lets such a user through, so only the gated route
    refuses them. The user is flushed so that it has its ID, which the
    token names;
    ``get_test_db`` commits it before each request, and the rollback at the
    end of the test removes it.

    Args:
        db_session: The test's session.

    Returns:
        The saved user.
    """
    user = make_user()
    db_session.add(user)
    db_session.flush()

    return user


@pytest.fixture
def gated_route(app: FastAPI) -> None:
    """Add a route at ``GATED_URL`` that uses the ordinary ``CurrentUser``.

    No route that exists today applies the password-change gate: the three
    that need a signed-in user ask for ``CurrentUserAllowingPasswordChange``.
    The test of a user the gate refuses therefore needs a route of its own
    that applies it. The route is added to this test's own application
    only, so it never leaks into another test.

    Args:
        app: The application built for this test.
    """

    def gated(user: CurrentUser) -> dict[str, str]:
        """Return the caller's ID, proving the route ran for that user.

        Args:
            user: The signed-in user, past the password-change gate.

        Returns:
            The user's ID as text, under ``user_id``.
        """
        return {"user_id": str(user.id)}

    app.add_api_route(GATED_URL, gated, methods=["GET"])


def _auth_header(user: User) -> dict[str, str]:
    """Build an Authorization header with a fresh access token for the user.

    The token is signed here as sign-in signs one, with
    ``create_access_token``, so the tests need neither a password nor a
    sign-in request.

    Args:
        user: The saved user the token should name.

    Returns:
        The headers to pass to the test client.
    """
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _request_log_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the lines the request middleware logged during the test.

    Only records from ``app.core.logging`` count. httpx2, the HTTP client
    ``TestClient`` is built on, logs every request at INFO with its full
    URL, query string included, so when ``LOG_LEVEL`` lets INFO through,
    its records are captured too and must never be mistaken for the
    application's. Tests make the request inside
    ``caplog.at_level(logging.INFO, logger="app.core.logging")``, so the
    middleware's lines are recorded even when ``LOG_LEVEL`` is set higher.

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
def test_a_valid_uuid_is_reused_in_its_normalized_form(header_value: str, expected: str) -> None:
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
def test_a_missing_or_invalid_header_gets_a_new_id_every_time(header_value: str | None) -> None:
    """A missing header, or one that isn't a valid UUID, gets a newly generated ID each time.

    Covers a missing header, an empty value, one containing a line break,
    an oversized one, and a malformed string. The value reaches the logs,
    so a line break could otherwise forge a second log entry and a huge
    value would bloat every line. Each value is resolved twice. Both IDs
    must take the normalized form, so the log spells every ID one way, and
    they must differ: an ID shared by every request that sent no header, or
    by every one that sent a malformed one, would match all their log
    lines, so none could be found. A missing header and an invalid one get
    their IDs in two separate places, so the cases cover both.
    """
    first_request_id = _resolve_request_id(header_value)
    second_request_id = _resolve_request_id(header_value)

    assert re.fullmatch(REQUEST_ID_PATTERN, first_request_id)
    assert re.fullmatch(REQUEST_ID_PATTERN, second_request_id)
    assert first_request_id != second_request_id


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


@pytest.mark.parametrize(
    ("requested_path", "logged_path"),
    [
        pytest.param("/health/x%1B%5B2K", "/health/x%1B%5B2K", id="terminal-escape-code"),
        pytest.param("/health/x%0By", "/health/x%0By", id="vertical-tab"),
        pytest.param("/health/x%C2%85y", "/health/x%C2%85y", id="next-line-character"),
        pytest.param("/health/x%20status=200", "/health/x%20status%3D200", id="faked-field"),
    ],
)
def test_request_log_line_escapes_the_path(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
    requested_path: str,
    logged_path: str,
) -> None:
    """The path is logged percent-encoded, so a client can't write raw control characters.

    The server decodes the path before the application sees it, and so does
    the test client, so ``%1B`` arrives as a real escape character, which
    can rewrite the screen of whoever reads the log in a terminal, and
    ``%20`` as a space, which can fake a ``key=value`` field of its own.
    Tabs, carriage returns, and line feeds never reach the line: Starlette
    parses ``request.url`` with Python's ``urlsplit``, which removes them,
    so the cases are control characters it keeps. No route has these
    paths, so each request answers 404, which is logged like any other.
    Each line must stay printable, with the path in its encoded form.
    """
    with caplog.at_level(logging.INFO, logger="app.core.logging"):
        response = client.get(requested_path)

    lines = _request_log_lines(caplog)

    assert response.status_code == 404
    assert len(lines) == 1
    assert f" path={logged_path} status=404 " in lines[0]
    assert lines[0].isprintable()


def test_request_log_line_names_the_signed_in_user(
    user: User,
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A request with a valid access token is logged with that user's ID.

    Plan §12 asks for the user ID, so a problem someone reports can be
    traced to the requests they made. ``/auth/me`` is the plainest route
    that needs a signed-in user, and it lets this one through although
    their password change is pending.
    """
    with caplog.at_level(logging.INFO, logger="app.core.logging"):
        response = client.get(ME_URL, headers=_auth_header(user))

    lines = _request_log_lines(caplog)

    assert response.status_code == 200
    assert len(lines) == 1
    assert f" user_id={user.id} " in lines[0]


def test_request_log_line_has_no_user_for_a_rejected_token(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A request whose access token is refused is logged with no user ID.

    The 401 means nobody was signed in, so the line must not name anyone.
    The authentication dependency stores the ID only once the auth service
    has accepted both the token and the account, and here the token can't
    even be decoded.
    """
    with caplog.at_level(logging.INFO, logger="app.core.logging"):
        response = client.get(ME_URL, headers={"Authorization": "Bearer not-a-token"})

    lines = _request_log_lines(caplog)

    assert response.status_code == 401
    assert len(lines) == 1
    assert " user_id=None " in lines[0]


@pytest.mark.usefixtures("gated_route")
def test_request_log_line_names_a_user_the_password_change_gate_refuses(
    db_session: Session,
    user: User,
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A signed-in user refused with a 403 is still named in the log line.

    The token and the account are checked before the password-change gate,
    so the caller is known even though the route turns them away, and the
    log shows who was refused. The test sets ``must_change_password``
    itself, although every new account starts with it, so the condition it
    depends on is written in the test.
    """
    user.must_change_password = True
    db_session.flush()

    with caplog.at_level(logging.INFO, logger="app.core.logging"):
        response = client.get(GATED_URL, headers=_auth_header(user))

    lines = _request_log_lines(caplog)

    assert response.status_code == 403
    assert len(lines) == 1
    assert f" user_id={user.id} " in lines[0]


def test_request_log_line_does_not_carry_a_user_into_the_next_request(
    user: User,
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """After a signed-in request, an anonymous one on the same client names nobody.

    The user ID belongs to one request. Kept anywhere that outlives it, such
    as a module variable, it would label the next caller's line with
    someone else's ID.
    """
    with caplog.at_level(logging.INFO, logger="app.core.logging"):
        signed_in_response = client.get(ME_URL, headers=_auth_header(user))
        anonymous_response = client.get("/health/live")

    lines = _request_log_lines(caplog)

    assert signed_in_response.status_code == 200
    assert anonymous_response.status_code == 200
    assert len(lines) == 2
    assert f" user_id={user.id} " in lines[0]
    assert " user_id=None " in lines[1]
