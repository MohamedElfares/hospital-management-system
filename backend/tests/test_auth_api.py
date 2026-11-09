"""Tests for the auth routes: sign-in, the signed-in user, sessions, sign-out, and password changes.

Every test sends real requests through ``client``, so each one runs the
whole stack: the request-context middleware, FastAPI's validation, the
route and its dependencies, the auth service, and the exception handlers,
against PostgreSQL inside the test's transaction. Before each request,
``get_test_db`` commits what the test set up, as it would already be saved
before a real request, and afterwards it rolls back what the request
didn't commit, so a test reads back only what a request committed, and
the rollback at the end of the test removes everything. Most tests act
as the ``user`` fixture's account, and most that need an access token
sign one directly with ``_auth_header``; the refresh token travels in the
client's cookie jar, which sends it back to the auth paths by itself, as
a browser would.

Sign-in answers with a bearer access token that names the user, in a body
that holds nothing else, and puts the refresh token in its cookie alone,
with its security flags and a lifetime that follows the setting; the
cookie holds the token whose hash was saved. Nothing a sign-in logs, at
any level, or prints holds a password typed, the stored hash, either
token, or an email, the account's or an unknown one, even when the form
is refused with a 422. A wrong password and an email holding a NUL get
the standard 401, its body compared whole, with no details, and no
cookie. A form without a username, a JSON body, and a field over its
limit get a 422 and no cookie; the last two also save no session, and
the 422 for a field over its limit never repeats its value.
A password as long as the rule allows and one with a space at each end
sign in as typed, and an email as long as the limit reaches the service
and gets the same 401 an unknown email gets.

The current-user route returns exactly the user's public fields, for a
signed token and for the one sign-in returns, and still answers while a
password change is pending; a missing or unusable token and a deactivated
user's token get the standard 401, and each kind of 401 carries
``WWW-Authenticate: Bearer``. Refresh answers with a new access token and
a new cookie with the same flags, never puts the refresh token in the
body, and gives a missing or unknown cookie the standard 401; a cookie
that was already exchanged, sent again, fails, ends every session of its
user, and logs one warning with the request ID. Sign-out answers 204,
clears the cookie, revokes the token behind it, and logs no token; it
needs an access token, and it works without a cookie and while a password
change is pending.

A password change answers with a new access token and a new cookie, ends
the session from before the change, and lets only the new password sign
in, both passwords used as typed; the new refresh token never appears in
the body, and no password, hash, or token is logged. A refused change
gets the standard 400 with its message and no cookie, an invalid or form
body gets a 422, and a missing access token or a deactivated user gets a
401. The route stays open while a password change is pending, and another
device's old cookie is refused without signing out the device that made
the change. A route that applies the password-change gate, which
``gated_route`` adds, refuses a user with a pending change with a 403 and
a code of its own, lets a user without one through, answers 401 rather
than 403 without an access token or for a deactivated user, and lets the
user in once the password is changed.

The service's rules are tested on their own in
``tests/test_auth_service.py``, the token and cookie helpers in
``tests/test_security.py``, and the row locks that keep concurrent
requests apart in ``tests/test_auth_concurrency.py``.
"""

# Random UUIDs: the X-Request-ID a test sends, to find it again in a log line.
import uuid

# UTC time zone; the expired token's times are timezone-aware UTC.
from datetime import UTC

# The current time, from which the expired token's issue and expiry times are set.
from datetime import datetime

# Moves those times into the past: issued an hour ago, expired a minute ago.
from datetime import timedelta

# Parses a Set-Cookie header, so an attribute such as Max-Age is compared whole.
from http.cookies import SimpleCookie

# PyJWT; signs the expired access token with the application's key and algorithm.
import jwt

# Test framework: fixtures, parametrize, monkeypatch, and caplog.
import pytest

# Builds a valid unsaved user; the tests give it a real password hash so it can sign in.
from factories import make_user

# Type of the application the gated_route fixture adds its route to.
from fastapi import FastAPI

# Type of the client fixture, which sends requests through the whole application.
from fastapi.testclient import TestClient

# Builds the queries that read refresh token rows back.
from sqlalchemy import select

# Type of the test's session, which saves users and reads rows back.
from sqlalchemy.orm import Session

# The signed-in user past the password-change gate; the gated route asks for it.
from app.api.deps import CurrentUser

# The module whose get_settings set_refresh_cookie reads, so a test can replace it there.
from app.core import security

# The settings: the JWT key for the expired token, and a copy with another refresh lifetime.
from app.core.config import get_settings

# Machine-readable error codes; the code each error body must carry.
from app.core.errors import ErrorCode

# The refresh cookie's name; reads the cookie from a response and sets it in the client.
from app.core.security import REFRESH_COOKIE_NAME

# Signs an access token directly, so tests of the routes that need one skip sign-in.
from app.core.security import create_access_token

# Checks a returned access token's signature and gives back the user ID it names.
from app.core.security import decode_access_token

# Makes a well-formed refresh token that the server never issued.
from app.core.security import generate_refresh_token

# Hashes a password, so a saved user can sign in with it.
from app.core.security import hash_password

# Hashes a raw refresh token, to find the row that stores it.
from app.core.security import hash_refresh_token

# The refresh_tokens table's ORM model; the tests read its rows back.
from app.modules.auth.models import RefreshToken

# The users table's ORM model; the type of the saved user.
from app.modules.users.models import User

# Longest email the sign-in form accepts; the overlong and longest-email cases follow it.
from app.modules.users.schemas import EMAIL_MAX_LENGTH

# Longest password the rule allows; the sign-in and change-password limits follow it.
from app.modules.users.schemas import PASSWORD_MAX_LENGTH

# Shortest password the rule allows; the too-short new password follows it.
from app.modules.users.schemas import PASSWORD_MIN_LENGTH

CHANGE_PASSWORD_URL = "/api/v1/auth/change-password"
GATED_URL = "/api/v1/test/gated"
LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/auth/me"
REFRESH_URL = "/api/v1/auth/refresh"
NEW_PASSWORD = "New-Password-123"
PASSWORD = "Correct-Password-1"

# Each sign-in field one character over its limit, as the form field and the
# value that replaces it in an otherwise valid form. Lengths come from the
# shared constants, so they follow them.
OVERLONG_LOGIN_FIELDS = [
    pytest.param("username", "a" * (EMAIL_MAX_LENGTH + 1), id="email-too-long"),
    pytest.param("password", "p" * (PASSWORD_MAX_LENGTH + 1), id="password-too-long"),
]

# Both ways the service refuses a change with a 400, each as the body fields
# that differ from a valid change and the message the user sees; every body
# passes validation. The last case fails both checks, a wrong current
# password with the real one as the new password, and gets the first check's
# message, so a caller holding only an access token can't learn from the
# reply whether a guess of the password, sent as the new one, is right. An
# account deactivated or deleted since the request's authentication gets a
# 401 instead, tested in tests/test_auth_concurrency.py.
REFUSED_PASSWORD_CHANGES = [
    pytest.param(
        {"current_password": "Wrong-Password-1"},
        "Current password is incorrect.",
        id="wrong-current-password",
    ),
    pytest.param(
        {"new_password": PASSWORD},
        "The new password must be different from the current one.",
        id="new-password-same-as-current",
    ),
    pytest.param(
        {"current_password": "Wrong-Password-1", "new_password": PASSWORD},
        "Current password is incorrect.",
        id="wrong-current-password-with-the-real-one-as-new",
    ),
]

# Bodies the schema rejects before the service runs, with the field the
# 422 names. Lengths come from the shared rule, so they follow it.
INVALID_PASSWORD_CHANGE_BODIES = [
    pytest.param(
        {"current_password": PASSWORD, "new_password": "a" * (PASSWORD_MIN_LENGTH - 1)},
        "body.new_password",
        id="new-password-too-short",
    ),
    pytest.param(
        {"current_password": "a" * (PASSWORD_MAX_LENGTH + 1), "new_password": NEW_PASSWORD},
        "body.current_password",
        id="current-password-too-long",
    ),
    pytest.param(
        {"current_password": PASSWORD},
        "body.new_password",
        id="new-password-missing",
    ),
]


@pytest.fixture
def user(db_session: Session) -> User:
    """Save an active user, test@example.com, whose password is ``PASSWORD``.

    The hash is real, unlike ``make_user``'s default, which can never sign
    in. Like every account ``make_user`` builds, the user must change their
    password, the database's default, so each sign-in of this user also
    shows that a pending change doesn't stop one; a test of the
    password-change gate sets the flag itself. The user is flushed, so its
    ID and the database's defaults are filled in before the test reads
    them, as ``_auth_header`` reads the ID. ``get_test_db`` commits it
    before each request, as the account would already be saved, and the
    rollback at the end of the test removes it.

    Args:
        db_session: The test's session.

    Returns:
        The saved user.
    """
    user = make_user(password_hash=hash_password(PASSWORD))
    db_session.add(user)
    db_session.flush()

    return user


def _auth_header(user: User) -> dict[str, str]:
    """Build an Authorization header with a fresh access token for the user.

    The token is signed directly, so the tests of the routes that need an
    access token don't depend on the sign-in route or pay for its password
    check. ``test_me_accepts_the_access_token_from_login`` goes through
    sign-in on purpose, to prove the two routes work together.

    Args:
        user: The saved user the token should name.

    Returns:
        The headers to pass to the test client.
    """
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _expired_access_token(user: User) -> str:
    """Sign an access token for the user that expired a minute ago.

    It is signed with the application's key and algorithm and names a real
    user, so its expiry is the only thing wrong with it.

    Args:
        user: The saved user the token should name.

    Returns:
        The encoded token.
    """
    now = datetime.now(UTC)
    claims = {
        "sub": str(user.id),
        "iat": now - timedelta(hours=1),
        "exp": now - timedelta(minutes=1),
    }

    return jwt.encode(claims, get_settings().jwt_secret_key.get_secret_value(), algorithm="HS256")


def _password_change_body(**overrides: str) -> dict[str, str]:
    """Build a valid change-password body for the ``user`` fixture.

    By default it holds the fixture's real password and a different, valid
    new one, so the change succeeds. A test replaces only the field it is
    about.

    Args:
        **overrides: Fields that replace the defaults.

    Returns:
        The JSON body to send.
    """
    return {"current_password": PASSWORD, "new_password": NEW_PASSWORD, **overrides}


@pytest.fixture
def gated_route(app: FastAPI) -> None:
    """Add a route at ``GATED_URL`` that uses the ordinary ``CurrentUser``.

    No route that exists today applies the password-change gate: the three
    that need a signed-in user, sign-out, the current-user route, and the
    password change, ask for ``CurrentUserAllowingPasswordChange``, which
    skips it. The gate tests therefore need a route of their own that
    applies it. It is added to this test's own application, which the
    ``client`` fixture is bound to, so it goes through the real middleware
    and exception handlers, never exists outside the test, and can't leak
    into other tests.

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


def test_login_returns_a_bearer_access_token(user: User, client: TestClient) -> None:
    """A successful sign-in answers 200 with a bearer token that names the user.

    The body has exactly two keys, so any extra field, such as the refresh
    token, would fail the test. Decoding the token with the application's
    key proves it is genuine and names that user.
    """
    response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})
    body = response.json()

    assert response.status_code == 200
    assert set(body) == {"access_token", "token_type"}
    assert body["token_type"] == "bearer"
    assert decode_access_token(body["access_token"]) == user.id


def test_login_sets_the_refresh_cookie_with_its_security_flags(
    user: User,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sign-in sets the refresh cookie with every security flag.

    The flags are read from the raw ``Set-Cookie`` header, the text the
    browser receives, rather than from the client's cookie jar, which turns
    ``Max-Age`` into an expiry time and keeps ``HttpOnly`` and ``SameSite``
    only as nonstandard attributes. ``get_settings`` is replaced where
    ``set_refresh_cookie`` looks it up, with a copy whose
    ``REFRESH_TOKEN_EXPIRE_DAYS`` is 3, a value no setting has by default,
    so ``Max-Age`` must be 259,200 seconds, whatever the environment
    configures. It is read from the parsed header, because text such as
    ``max-age=259200`` is also found in a header that says 2592000.
    ``Secure`` is absent because tests don't run in production;
    ``test_security.py`` covers the production case.
    """
    three_day_settings = get_settings().model_copy(update={"refresh_token_expire_days": 3})
    monkeypatch.setattr(security, "get_settings", lambda: three_day_settings)

    response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    assert response.status_code == 200

    set_cookie = response.headers["set-cookie"].lower()
    parsed_cookie = SimpleCookie()
    parsed_cookie.load(response.headers["set-cookie"])

    assert f"{REFRESH_COOKIE_NAME}=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie
    assert "path=/api/v1/auth" in set_cookie
    assert parsed_cookie[REFRESH_COOKIE_NAME]["max-age"] == "259200"
    assert "secure" not in set_cookie


def test_the_refresh_cookie_holds_the_stored_token(
    db_session: Session,
    user: User,
    client: TestClient,
) -> None:
    """The token in the cookie is the one whose hash was saved.

    Exactly one row exists, and its hash matches the cookie's value, so a
    later refresh with this cookie will find the row.
    """
    response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    assert response.status_code == 200

    raw_refresh_token = response.cookies[REFRESH_COOKIE_NAME]
    token_rows = db_session.scalars(select(RefreshToken)).all()

    assert len(token_rows) == 1
    assert hash_refresh_token(raw_refresh_token) == token_rows[0].token_hash


def test_the_refresh_token_never_appears_in_the_body(user: User, client: TestClient) -> None:
    """The refresh token's value appears nowhere in the response body.

    The body is searched as text, so the token can't hide in any field. It
    must stay in the ``HttpOnly`` cookie, out of reach of page scripts.
    """
    response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    assert response.status_code == 200

    refresh_token = response.cookies[REFRESH_COOKIE_NAME]

    assert refresh_token not in response.text


def test_login_logs_and_prints_neither_the_secrets_nor_the_emails(
    user: User,
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A sign-in through the API logs and prints no password, hash, token, or email.

    The service test of the same name sees only the service. Here the
    route, the middleware, and the error handlers run too. Every record
    down to DEBUG is captured, the test client's own included, and so is
    everything printed to stdout and stderr: the application writes its
    log records to stderr, so a ``print`` ends up in the same log. Five
    sign-ins are sent: a successful one, one with a wrong password, one
    for an unknown email, and two forms the route refuses with a 422,
    whose handler must log none of what was typed either. One has a
    password over the limit, which FastAPI's validation error holds whole,
    as Pydantic's ``input``; the other lacks only its username and holds
    the real password, which only the request's body holds. No password
    typed, the account's stored hash, nor either token the successful
    sign-in returned may appear in the records or in either stream: the
    access token from the body, and the refresh token from the cookie.
    Nor may an email, the account's or the unknown one, since plan §12
    keeps personal data out of logs. A failure names each value found and
    where, never the value itself.
    """
    overlong_password = "p" * (PASSWORD_MAX_LENGTH + 1)
    unknown_email = "ghost@example.com"

    with caplog.at_level("DEBUG"):
        response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})
        failed_response = client.post(
            LOGIN_URL, data={"username": user.email, "password": "Wrong-Password-1"}
        )
        unknown_email_response = client.post(
            LOGIN_URL, data={"username": unknown_email, "password": PASSWORD}
        )
        overlong_response = client.post(
            LOGIN_URL, data={"username": user.email, "password": overlong_password}
        )
        no_username_response = client.post(LOGIN_URL, data={"password": PASSWORD})

    printed = capsys.readouterr()

    assert response.status_code == 200
    assert failed_response.status_code == 401
    assert unknown_email_response.status_code == 401
    assert overlong_response.status_code == 422
    assert no_username_response.status_code == 422

    sensitive_values = {
        "password": PASSWORD,
        "wrong password": "Wrong-Password-1",
        "overlong password": overlong_password,
        "stored hash": user.password_hash,
        "access token": response.json()["access_token"],
        "refresh token": response.cookies[REFRESH_COOKIE_NAME],
        "email": user.email,
        "unknown email": unknown_email,
    }
    captured_texts = {"logs": caplog.text, "stdout": printed.out, "stderr": printed.err}

    assert [
        (name, channel)
        for name, value in sensitive_values.items()
        for channel, text in captured_texts.items()
        if value in text
    ] == []


def test_login_with_a_wrong_password_returns_the_standard_401(
    user: User,
    client: TestClient,
) -> None:
    """A wrong password gets the standard 401, its body compared whole, and no cookie.

    The status and the body are written out, not read from
    ``AuthenticationError``, so a change to the API's contract fails the
    test, and so does a 401 with details of its own, which could tell the
    caller which check failed. The request ID is the one the response's
    ``X-Request-ID`` header carries. The service tests compare the whole
    error of every kind of failed sign-in; this test compares what reaches
    the client.
    """
    response = client.post(LOGIN_URL, data={"username": user.email, "password": "Wrong Password"})

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "AUTHENTICATION_FAILED",
            "message": "Incorrect email or password.",
            "details": [],
            "request_id": response.headers["x-request-id"],
        }
    }
    assert "set-cookie" not in response.headers


def test_login_with_a_nul_in_the_email_returns_the_standard_401(
    user: User,
    client: TestClient,
) -> None:
    """An email holding a NUL character gets the same 401 an unknown email gets.

    PostgreSQL refuses that character, so the text must be turned away
    before any query; otherwise the request ends in a 500. The rest of the
    email and the password are the real user's, so the NUL alone decides
    the outcome. The whole body is compared, so a refusal with details of
    its own, which would tell the caller that the text isn't an address,
    fails.
    """
    response = client.post(
        LOGIN_URL,
        data={"username": f"\x00{user.email}", "password": PASSWORD},
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "AUTHENTICATION_FAILED",
            "message": "Incorrect email or password.",
            "details": [],
            "request_id": response.headers["x-request-id"],
        }
    }
    assert "set-cookie" not in response.headers


def test_login_without_a_username_is_a_validation_error(client: TestClient) -> None:
    """A form without a username gets a 422 that names the missing field.

    The only detail is ``body.username``, so the request failed for this
    reason alone. No user is needed: validation rejects the request before
    the service runs.
    """
    response = client.post(LOGIN_URL, data={"password": PASSWORD})

    assert response.status_code == 422

    error = response.json()["error"]

    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["message"] == "The request contains invalid data."
    assert [detail["field"] for detail in error["details"]] == ["body.username"]
    assert "set-cookie" not in response.headers


def test_login_with_a_json_body_is_a_validation_error(
    db_session: Session,
    user: User,
    client: TestClient,
) -> None:
    """Correct credentials sent as JSON get a 422, and nothing is saved.

    The endpoint reads only the documented form, so a JSON body leaves both
    of its fields missing. The credentials are real, so the 422 can only
    come from the format, and the empty token table shows that no session
    was issued.
    """
    response = client.post(LOGIN_URL, json={"username": user.email, "password": PASSWORD})

    assert response.status_code == 422

    error = response.json()["error"]

    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["message"] == "The request contains invalid data."
    assert "set-cookie" not in response.headers
    assert db_session.scalars(select(RefreshToken)).all() == []


@pytest.mark.parametrize(("field", "value"), OVERLONG_LOGIN_FIELDS)
def test_login_with_an_overlong_field_is_a_validation_error(
    db_session: Session,
    user: User,
    client: TestClient,
    field: str,
    value: str,
) -> None:
    """A sign-in field longer than any account's gets a 422, and nothing is saved.

    No account's email is longer than its column, and no password can be
    set longer than the password rule allows, so such a value can never
    sign in; the form refuses it before the route runs, so no lookup or
    password check happens. The other field holds the user's real
    credentials, so the length alone decides the outcome. The 422 names
    the field and the reason, and never repeats the value, so a rejected
    password can't reach the browser's network panel or anything else that
    keeps responses. That the 422 logs and prints none of it either is
    checked by ``test_login_logs_and_prints_neither_the_secrets_nor_the_emails``.
    """
    form = {"username": user.email, "password": PASSWORD, field: value}

    response = client.post(LOGIN_URL, data=form)

    assert response.status_code == 422

    error = response.json()["error"]

    assert [(detail["field"], detail["type"]) for detail in error["details"]] == [
        (f"body.{field}", "string_too_long")
    ]
    assert value not in response.text
    assert "set-cookie" not in response.headers
    assert db_session.scalars(select(RefreshToken)).all() == []


def test_login_with_a_password_of_the_longest_allowed_length_succeeds(
    db_session: Session,
    client: TestClient,
) -> None:
    """An account whose password is as long as the rule allows can sign in.

    The form's limit must match the password rule exactly: one character
    less would lock such an account out, and this test would fail.
    """
    longest_password = "p" * PASSWORD_MAX_LENGTH
    user = make_user(email="longest@example.com", password_hash=hash_password(longest_password))
    db_session.add(user)
    db_session.flush()

    response = client.post(LOGIN_URL, data={"username": user.email, "password": longest_password})

    assert response.status_code == 200


def test_login_with_spaces_around_the_password_succeeds(
    db_session: Session,
    client: TestClient,
) -> None:
    """An account whose password has a space at each end signs in with it as typed.

    ``UserCreate`` keeps such a password, so its hash includes the spaces,
    and the form and the service must hand the password to the check as it
    arrived: either one stripping it would lock the account out.
    """
    spaced_password = " Correct-Password-1 "
    user = make_user(password_hash=hash_password(spaced_password))
    db_session.add(user)
    db_session.flush()

    response = client.post(LOGIN_URL, data={"username": user.email, "password": spaced_password})

    assert response.status_code == 200


def test_login_with_an_email_of_the_longest_allowed_length_reaches_the_service(
    client: TestClient,
) -> None:
    """An email exactly as long as the limit is checked like any other.

    It gets the same 401 an unknown email gets, its body compared whole,
    not a 422: the form refuses only longer ones. No address that long is
    valid, so no account is needed for the check to fail.
    """
    response = client.post(
        LOGIN_URL, data={"username": "a" * EMAIL_MAX_LENGTH, "password": PASSWORD}
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "AUTHENTICATION_FAILED",
            "message": "Incorrect email or password.",
            "details": [],
            "request_id": response.headers["x-request-id"],
        }
    }


def test_me_returns_exactly_the_public_fields_of_the_user(
    user: User,
    client: TestClient,
) -> None:
    """A valid token returns 200 with exactly the user's public fields.

    The whole body is compared with one dict, so the test fails if a value
    is wrong or if any extra field, such as the password hash, appears.
    """
    response = client.get(ME_URL, headers=_auth_header(user))

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "must_change_password": user.must_change_password,
    }


def test_me_accepts_the_access_token_from_login(user: User, client: TestClient) -> None:
    """The token returned by sign-in opens the current-user route for that user.

    This is the one test that chains the two routes, proving login issues a
    token the protected routes accept, with the same key and claims.
    """
    login = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    assert login.status_code == 200

    access_token = login.json()["access_token"]
    response = client.get(ME_URL, headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)


def test_me_without_a_token_is_the_standard_401(
    client: TestClient,
) -> None:
    """A request without an Authorization header gets the standard 401.

    FastAPI's bearer scheme rejects it before the route runs, and the error
    handler still returns the standard error body, keeping the
    ``WWW-Authenticate: Bearer`` header that tells clients how to sign in.
    """
    response = client.get(ME_URL)

    assert response.status_code == 401

    body = response.json()["error"]

    assert body["code"] == "AUTHENTICATION_FAILED"
    assert body["message"] == "Not authenticated"
    assert response.headers["www-authenticate"] == "Bearer"


def test_every_kind_of_401_names_the_bearer_scheme(user: User, client: TestClient) -> None:
    """Every refusal from the auth service carries ``WWW-Authenticate: Bearer`` too.

    HTTP requires every 401 to name a way to authenticate (RFC 9110), as
    FastAPI's own 401 above does. An expired access token, a failed
    sign-in, and a refused refresh are each refused by a different part of
    the auth service, so the test sends all three and compares them in one
    assertion, which names every request that lacks the header.
    """
    expired_header = {"Authorization": f"Bearer {_expired_access_token(user)}"}
    wrong_password = {"username": user.email, "password": "Wrong Password"}

    responses = {
        "expired access token": client.get(ME_URL, headers=expired_header),
        "failed sign-in": client.post(LOGIN_URL, data=wrong_password),
        "refused refresh": client.post(REFRESH_URL),
    }

    assert {
        kind: (response.status_code, response.headers.get("www-authenticate"))
        for kind, response in responses.items()
    } == {kind: (401, "Bearer") for kind in responses}


@pytest.mark.parametrize(
    ("authorization", "message"),
    [
        pytest.param(
            "Basic abc",
            "Not authenticated",
            id="wrong-scheme",
        ),
        pytest.param(
            "Bearer not-a-token",
            "Invalid or expired token.",
            id="bad-token",
        ),
        pytest.param(
            "Bearer ",
            "Invalid or expired token.",
            id="empty-token",
        ),
    ],
)
def test_me_rejects_an_unusable_authorization_header(
    client: TestClient,
    authorization: str,
    message: str,
) -> None:
    """Every unusable Authorization header gets a 401 in the standard format.

    A non-bearer scheme is stopped by FastAPI's bearer scheme, which says
    "Not authenticated". A bearer header with a bad or empty token reaches
    the auth service, which says "Invalid or expired token.". No user is
    saved, because none of these requests gets as far as a database lookup.
    """
    response = client.get(
        ME_URL,
        headers={"Authorization": authorization},
    )

    assert response.status_code == 401

    body = response.json()["error"]

    assert body["code"] == "AUTHENTICATION_FAILED"
    assert body["message"] == message


def test_me_rejects_a_deactivated_user(db_session: Session, user: User, client: TestClient) -> None:
    """A token issued before deactivation gets the generic 401 afterwards.

    The header is built while the user is active, as when someone signs in
    and is then deactivated. The token is still signed and unexpired, so
    only the database read on every request turns it away, with the same
    message as an expired token.
    """
    headers = _auth_header(user)
    user.is_active = False
    db_session.flush()

    response = client.get(ME_URL, headers=headers)

    assert response.status_code == 401

    body = response.json()["error"]

    assert body["code"] == "AUTHENTICATION_FAILED"
    assert body["message"] == "Invalid or expired token."


def test_me_still_works_while_a_password_change_is_pending(
    db_session: Session,
    user: User,
    client: TestClient,
) -> None:
    """A user with a pending password change still gets 200 and sees the flag.

    The web app relies on this route to discover that the change-password
    screen is due, so the password-change gate added later must not cover
    it; this test fails if it does.
    """
    user.must_change_password = True
    db_session.flush()

    response = client.get(ME_URL, headers=_auth_header(user))

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "must_change_password": True,
    }


def test_refresh_returns_a_new_bearer_access_token(
    user: User,
    client: TestClient,
) -> None:
    """After sign-in, a refresh answers 200 with a bearer token for the user.

    The client keeps the sign-in cookie and sends it back by itself, as a
    browser does, so the request carries no Authorization header at all.
    """
    login_response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    assert login_response.status_code == 200

    refresh_response = client.post(REFRESH_URL)
    body = refresh_response.json()

    assert refresh_response.status_code == 200
    assert body["token_type"] == "bearer"
    assert decode_access_token(body["access_token"]) == user.id


def test_refresh_sets_a_new_refresh_cookie_with_its_security_flags(
    user: User,
    client: TestClient,
) -> None:
    """A refresh replaces the cookie with a different token and the same flags.

    A cookie that kept the sign-in value would mean the token was not
    rotated. Max-Age isn't pinned here, since the cookie's lifetime and the
    token's fixed expiry may still be aligned later.
    """
    login_response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    assert login_response.status_code == 200

    refresh_response = client.post(REFRESH_URL)

    assert refresh_response.status_code == 200

    set_cookie = refresh_response.headers["set-cookie"].lower()
    login_cookie = login_response.cookies[REFRESH_COOKIE_NAME]
    refresh_cookie = refresh_response.cookies[REFRESH_COOKIE_NAME]

    assert f"{REFRESH_COOKIE_NAME}=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie
    assert "path=/api/v1/auth" in set_cookie
    assert refresh_cookie != login_cookie


def test_the_refreshed_token_never_appears_in_the_body(user: User, client: TestClient) -> None:
    """The body holds only the access token and its type, never the refresh token.

    The key set catches any extra field, and the text search catches the
    token hidden in any value. It must stay in the HttpOnly cookie.
    """
    login_response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    assert login_response.status_code == 200

    refresh_response = client.post(REFRESH_URL)

    assert refresh_response.status_code == 200

    body = refresh_response.json()
    refresh_cookie = refresh_response.cookies[REFRESH_COOKIE_NAME]

    assert set(body) == {"access_token", "token_type"}
    assert refresh_cookie not in refresh_response.text


def test_refresh_without_a_cookie_is_the_standard_401(client: TestClient) -> None:
    """A refresh without the cookie gets the standard 401 and no cookie.

    Not a 422: the route's cookie parameter defaults to None, so the
    request reaches the service, which reports it as unauthenticated.
    """
    refresh_response = client.post(REFRESH_URL)

    assert refresh_response.status_code == 401

    error = refresh_response.json()["error"]

    assert error["code"] == "AUTHENTICATION_FAILED"
    assert error["message"] == "Invalid or expired token."
    assert "set-cookie" not in refresh_response.headers


def test_refresh_with_an_unknown_cookie_is_the_standard_401(client: TestClient) -> None:
    """A well-formed token the server never issued gets the standard 401.

    The cookie is set with the same path the server uses, so the client
    really sends it; with any other path it would be left out and this
    would only repeat the missing-cookie test.
    """
    client.cookies.set(REFRESH_COOKIE_NAME, generate_refresh_token(), path="/api/v1/auth")
    refresh_response = client.post(REFRESH_URL)

    assert refresh_response.status_code == 401

    error = refresh_response.json()["error"]

    assert error["code"] == "AUTHENTICATION_FAILED"
    assert error["message"] == "Invalid or expired token."
    assert "set-cookie" not in refresh_response.headers


def test_reusing_an_old_cookie_signs_out_every_session(user: User, client: TestClient) -> None:
    """Replaying a replaced cookie fails and kills the newer cookie as well.

    After one refresh the sign-in token is spent. Sending it again looks
    like a stolen copy, so every token of the user is revoked: the new
    cookie, which was valid a moment earlier, now gets a 401 too. This is
    the protection rotation exists for, seen from outside.
    """
    login_response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    assert login_response.status_code == 200

    old_token = login_response.cookies[REFRESH_COOKIE_NAME]
    refresh_response = client.post(REFRESH_URL)

    assert refresh_response.status_code == 200

    new_token = refresh_response.cookies[REFRESH_COOKIE_NAME]

    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE_NAME, old_token, path="/api/v1/auth")
    reuse_response = client.post(REFRESH_URL)

    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE_NAME, new_token, path="/api/v1/auth")
    after_reuse_response = client.post(REFRESH_URL)

    assert reuse_response.status_code == 401
    assert after_reuse_response.status_code == 401

    reuse_error = reuse_response.json()["error"]
    after_reuse_error = after_reuse_response.json()["error"]

    assert reuse_error["code"] == "AUTHENTICATION_FAILED"
    assert reuse_error["message"] == "Invalid or expired token."
    assert after_reuse_error["code"] == "AUTHENTICATION_FAILED"
    assert after_reuse_error["message"] == "Invalid or expired token."


def test_reuse_is_logged_with_the_request_id(
    db_session: Session,
    user: User,
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A replayed cookie logs one warning naming the request, the user, and the token.

    The replay sends its own ``X-Request-ID``, which the middleware hands
    on to the service, so the warning can be matched with the request
    whose 401 the client got; the request's own log line names no user,
    because refresh takes no access token. The whole message is compared,
    so a line without the request ID, the user's ID, or the replayed
    token's ID fails, and only WARNING records from the auth service's
    logger count, so a warning logged at another level or under another
    name fails too. Neither cookie may appear anywhere in the captured
    text.
    """
    login_response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    assert login_response.status_code == 200

    old_cookie = login_response.cookies[REFRESH_COOKIE_NAME]
    refresh_response = client.post(REFRESH_URL)

    assert refresh_response.status_code == 200

    new_cookie = refresh_response.cookies[REFRESH_COOKIE_NAME]
    old_token_id = db_session.scalar(
        select(RefreshToken.id).where(RefreshToken.token_hash == hash_refresh_token(old_cookie))
    )
    request_id = str(uuid.uuid4())

    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE_NAME, old_cookie, path="/api/v1/auth")
    with caplog.at_level("WARNING", logger="app.modules.auth.service"):
        reuse_response = client.post(REFRESH_URL, headers={"X-Request-ID": request_id})

    alarm_records = [
        (record.levelname, record.getMessage())
        for record in caplog.records
        if record.name == "app.modules.auth.service"
    ]
    expected_message = (
        f"Refresh token reuse detected (request_id={request_id}, user_id={user.id}, "
        f"token_id={old_token_id})"
    )

    assert reuse_response.status_code == 401
    assert alarm_records == [("WARNING", expected_message)]
    assert old_cookie not in caplog.text
    assert new_cookie not in caplog.text


def test_logout_clears_the_cookie_and_ends_the_session(user: User, client: TestClient) -> None:
    """Logout answers 204, clears the cookie, and revokes the token behind it.

    The cookie's value is saved before logout and put back afterwards,
    because the client deletes the cookie once logout clears it: a refresh
    without it would get 401 whether or not the token was revoked. Only a
    refresh with the old value proves the session really ended.
    """
    login_response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    assert login_response.status_code == 200

    access_token = login_response.json()["access_token"]
    raw_refresh_token = login_response.cookies[REFRESH_COOKIE_NAME]

    logout_response = client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {access_token}"})

    assert logout_response.status_code == 204
    assert logout_response.content == b""

    cleared_cookie_header = logout_response.headers["set-cookie"].lower()

    assert cleared_cookie_header.startswith(f"{REFRESH_COOKIE_NAME}=")
    assert "max-age=0" in cleared_cookie_header
    assert "path=/api/v1/auth" in cleared_cookie_header

    client.cookies.set(REFRESH_COOKIE_NAME, raw_refresh_token, path="/api/v1/auth")
    refresh_response = client.post(REFRESH_URL)

    assert refresh_response.status_code == 401


def test_logout_never_logs_the_refresh_token(
    db_session: Session,
    user: User,
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A sign-out through the API logs the refresh cookie at no level.

    The service test of the same name sees only the service. Here the
    route, its dependencies, and the middleware run too, and every record
    down to DEBUG is captured, the test client's own included. The user
    signs in and signs out with the cookie sign-in set, whose value may
    not appear in the captured text. Signing out answers 204 even without
    a cookie, so the token's row must be revoked afterwards, which shows
    the cookie reached the route and the check isn't empty.
    """
    login_response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    assert login_response.status_code == 200

    headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}
    raw_refresh_token = login_response.cookies[REFRESH_COOKIE_NAME]

    with caplog.at_level("DEBUG"):
        logout_response = client.post(LOGOUT_URL, headers=headers)

    token_row = db_session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_refresh_token))
    )

    assert logout_response.status_code == 204
    assert token_row.revoked_at is not None
    assert raw_refresh_token not in caplog.text


def test_logout_without_an_access_token_is_the_standard_401(user: User, client: TestClient) -> None:
    """Logout without an access token gets the standard 401 and ends nothing.

    The client holds a valid refresh cookie from signing in but sends no
    ``Authorization`` header. The bearer scheme rejects the request before
    the route runs, and the refresh that follows still works, which proves
    the cookie alone can't be used to revoke a session.
    """
    client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})
    logout_response = client.post(LOGOUT_URL)

    assert logout_response.status_code == 401

    error = logout_response.json()["error"]
    refresh_response = client.post(REFRESH_URL)

    assert refresh_response.status_code == 200
    assert error["code"] == "AUTHENTICATION_FAILED"
    assert error["message"] == "Not authenticated"


def test_logout_without_a_cookie_still_succeeds(user: User, client: TestClient) -> None:
    """Logout with a valid access token but no cookie still answers 204.

    The test never signs in, so the client has no cookie to send. Signing
    out never fails, so a second tab or a cookie that is already gone is
    not an error, and the cookie is cleared anyway.
    """
    headers = _auth_header(user)
    logout_response = client.post(LOGOUT_URL, headers=headers)
    cleared_cookie_header = logout_response.headers["set-cookie"].lower()

    assert logout_response.status_code == 204
    assert "max-age=0" in cleared_cookie_header


def test_logout_works_while_a_password_change_is_pending(
    db_session: Session,
    user: User,
    client: TestClient,
) -> None:
    """A user who must change their password can still sign out.

    Logout is one of the routes the forced-password-change gate leaves open
    (plan §8.1), so a user is never trapped in a session they can't end.
    This test guards that exemption once the gate exists.
    """
    user.must_change_password = True

    db_session.flush()

    headers = _auth_header(user)
    logout_response = client.post(LOGOUT_URL, headers=headers)

    assert logout_response.status_code == 204


def test_change_password_returns_a_new_access_token(user: User, client: TestClient) -> None:
    """A successful change returns a bearer access token that works on /auth/me."""
    response = client.post(
        CHANGE_PASSWORD_URL, json=_password_change_body(), headers=_auth_header(user)
    )

    assert response.status_code == 200

    body = response.json()
    me_response = client.get(ME_URL, headers={"Authorization": f"Bearer {body['access_token']}"})

    assert body["token_type"] == "bearer"
    assert decode_access_token(body["access_token"]) == user.id
    assert me_response.status_code == 200


def test_change_password_sets_a_new_refresh_cookie(user: User, client: TestClient) -> None:
    """Changing the password replaces the refresh cookie with a new one that works.

    The user signs in first, so the browser holds a cookie. Changing the
    password revokes that token, so the response must send exactly one new
    cookie with the same security flags. Without it, the device would be
    signed out when its access token expires. The new cookie differs from
    the old one, and ``/auth/refresh`` accepts it.
    """
    login_response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    assert login_response.status_code == 200

    old_cookie = login_response.cookies[REFRESH_COOKIE_NAME]
    response = client.post(
        CHANGE_PASSWORD_URL,
        json=_password_change_body(),
        headers={"Authorization": f"Bearer {login_response.json()['access_token']}"},
    )

    assert response.status_code == 200

    set_cookie_headers = response.headers.get_list("set-cookie")

    assert len(set_cookie_headers) == 1

    new_cookie = response.cookies[REFRESH_COOKIE_NAME]
    cookie_attributes = set_cookie_headers[0].lower()
    refresh_response = client.post(REFRESH_URL)

    assert new_cookie != old_cookie
    assert "httponly" in cookie_attributes
    assert "samesite=strict" in cookie_attributes
    assert "path=/api/v1/auth" in cookie_attributes
    assert refresh_response.status_code == 200


def test_change_password_ends_the_old_session(user: User, client: TestClient) -> None:
    """The refresh cookie from before the change no longer works.

    The old cookie is put back after the change, as a second device or a
    thief would still hold it, and ``/auth/refresh`` refuses it.
    """
    login_response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    assert login_response.status_code == 200

    old_cookie = login_response.cookies[REFRESH_COOKIE_NAME]
    change_response = client.post(
        CHANGE_PASSWORD_URL,
        json=_password_change_body(),
        headers={"Authorization": f"Bearer {login_response.json()['access_token']}"},
    )

    assert change_response.status_code == 200

    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE_NAME, old_cookie, path="/api/v1/auth")
    refresh_response = client.post(REFRESH_URL)

    assert refresh_response.status_code == 401


def test_only_the_new_password_signs_in(user: User, client: TestClient) -> None:
    """After the change, the new password signs in and the old one is refused."""
    client.post(CHANGE_PASSWORD_URL, json=_password_change_body(), headers=_auth_header(user))

    old_login = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})
    new_login = client.post(LOGIN_URL, data={"username": user.email, "password": NEW_PASSWORD})

    assert old_login.status_code == 401
    assert new_login.status_code == 200


def test_change_password_keeps_the_spaces_around_both_passwords(
    db_session: Session,
    client: TestClient,
) -> None:
    """A current and a new password with a space at each end are both used as typed.

    The current password, saved with its spaces, is accepted as typed, and
    the new one is saved with its spaces, so it then signs in as typed.
    Stripping either password anywhere between the request and the hash,
    in the schema or in the service, fails here: a stripped current
    password is refused as wrong, and a stripped new one no longer matches
    what the user signs in with.
    """
    user = make_user(password_hash=hash_password(" Correct-Password-1 "))
    db_session.add(user)
    db_session.flush()

    response = client.post(
        CHANGE_PASSWORD_URL,
        json={"current_password": " Correct-Password-1 ", "new_password": " New-Password-123 "},
        headers=_auth_header(user),
    )
    new_login = client.post(
        LOGIN_URL, data={"username": user.email, "password": " New-Password-123 "}
    )

    assert response.status_code == 200
    assert new_login.status_code == 200


def test_the_new_refresh_token_never_appears_in_the_body(user: User, client: TestClient) -> None:
    """The new refresh token travels only in its HttpOnly cookie, never in the body."""
    response = client.post(
        CHANGE_PASSWORD_URL, json=_password_change_body(), headers=_auth_header(user)
    )

    assert response.status_code == 200

    new_cookie = response.cookies[REFRESH_COOKIE_NAME]

    assert new_cookie not in response.text


def test_change_password_logs_neither_the_passwords_nor_the_tokens(
    db_session: Session,
    user: User,
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A password change through the API logs no password, hash, or token at any level.

    The service test of the same name sees only the service. Here the
    route, its dependencies, the middleware, and the error handler run
    too, and every record down to DEBUG is captured, the test client's
    own included. A change refused for a wrong current password and a
    successful one are sent. None of the passwords typed, the hash from
    before the change, the new hash, read back from the database, nor
    either token the successful change returned may appear in the
    captured text: the access token from the body, and the refresh token
    from the cookie.
    """
    headers = _auth_header(user)
    original_hash = user.password_hash

    with caplog.at_level("DEBUG"):
        refused_response = client.post(
            CHANGE_PASSWORD_URL,
            json=_password_change_body(current_password="Wrong-Password-1"),
            headers=headers,
        )
        response = client.post(CHANGE_PASSWORD_URL, json=_password_change_body(), headers=headers)

    assert refused_response.status_code == 400
    assert response.status_code == 200

    db_session.refresh(user)
    access_token = response.json()["access_token"]
    refresh_token = response.cookies[REFRESH_COOKIE_NAME]

    assert PASSWORD not in caplog.text
    assert NEW_PASSWORD not in caplog.text
    assert "Wrong-Password-1" not in caplog.text
    assert original_hash not in caplog.text
    assert user.password_hash not in caplog.text
    assert access_token not in caplog.text
    assert refresh_token not in caplog.text


@pytest.mark.parametrize(("overrides", "message"), REFUSED_PASSWORD_CHANGES)
def test_a_refused_change_is_a_400_without_a_cookie(
    user: User,
    client: TestClient,
    overrides: dict[str, str],
    message: str,
) -> None:
    """A refused change returns the standard 400 with its message and sets no cookie.

    Nothing changed, so the browser keeps its current cookie: sending a new
    one would replace a working session for no reason.
    """
    response = client.post(
        CHANGE_PASSWORD_URL,
        json=_password_change_body(**overrides),
        headers=_auth_header(user),
    )

    assert response.status_code == 400

    error = response.json()["error"]

    assert error["code"] == ErrorCode.BAD_REQUEST
    assert error["message"] == message
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(("body", "field"), INVALID_PASSWORD_CHANGE_BODIES)
def test_an_invalid_body_is_a_validation_error(
    user: User,
    client: TestClient,
    body: dict[str, str],
    field: str,
) -> None:
    """A body that breaks the password rule is a 422 naming the field.

    The error body never contains a password that was sent, so a rejected
    password can't end up in logs or in the browser's network panel.
    """
    response = client.post(CHANGE_PASSWORD_URL, json=body, headers=_auth_header(user))

    assert response.status_code == 422

    fields = [detail["field"] for detail in response.json()["error"]["details"]]

    assert field in fields
    for password in body.values():
        assert password not in response.text


def test_a_form_body_is_a_validation_error(user: User, client: TestClient) -> None:
    """The route reads JSON only; a form body like login's is a 422."""
    response = client.post(
        CHANGE_PASSWORD_URL, data=_password_change_body(), headers=_auth_header(user)
    )

    assert response.status_code == 422


def test_change_password_without_an_access_token_is_the_standard_401(
    user: User,
    client: TestClient,
) -> None:
    """Without an access token the change is refused with the standard 401 body."""
    response = client.post(CHANGE_PASSWORD_URL, json=_password_change_body())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == ErrorCode.AUTHENTICATION_FAILED


def test_change_password_rejects_a_deactivated_user(
    db_session: Session,
    user: User,
    client: TestClient,
) -> None:
    """A deactivated user's still-valid access token can't change the password."""
    headers = _auth_header(user)
    user.is_active = False
    db_session.flush()

    response = client.post(CHANGE_PASSWORD_URL, json=_password_change_body(), headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == ErrorCode.AUTHENTICATION_FAILED


def test_change_password_works_while_a_password_change_is_pending(
    db_session: Session,
    user: User,
    client: TestClient,
) -> None:
    """A user who must change their password can still reach this route.

    This route is how the forced change gets done, so the 7d gate must
    exempt it. The test passes today and keeps that exemption in place once
    the gate is added.
    """
    user.must_change_password = True
    db_session.flush()

    response = client.post(
        CHANGE_PASSWORD_URL, json=_password_change_body(), headers=_auth_header(user)
    )

    assert response.status_code == 200


def test_another_device_refreshing_after_a_change_keeps_this_session(
    user: User,
    client: TestClient,
) -> None:
    """Another device's old cookie is refused without signing out the device that changed.

    The user is signed in on a phone and a laptop, and changes the password
    on the laptop. The phone still holds its old cookie, which the change
    revoked, and refreshes first: it gets a 401. That token was ended on
    purpose and never rotated, so it is not reuse, and the laptop's new
    session survives. Its refresh still gets a 200. The order matters:
    only the phone refreshing first can show a false alarm.
    """
    phone_login = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    assert phone_login.status_code == 200

    phone_cookie = phone_login.cookies[REFRESH_COOKIE_NAME]

    client.cookies.clear()
    laptop_login = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    assert laptop_login.status_code == 200

    change_response = client.post(
        CHANGE_PASSWORD_URL,
        json=_password_change_body(),
        headers={"Authorization": f"Bearer {laptop_login.json()['access_token']}"},
    )

    assert change_response.status_code == 200

    laptop_new_cookie = change_response.cookies[REFRESH_COOKIE_NAME]

    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE_NAME, phone_cookie, path="/api/v1/auth")
    phone_refresh = client.post(REFRESH_URL)

    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE_NAME, laptop_new_cookie, path="/api/v1/auth")
    laptop_refresh = client.post(REFRESH_URL)

    assert phone_refresh.status_code == 401
    assert laptop_refresh.status_code == 200


@pytest.mark.usefixtures("gated_route")
def test_a_pending_password_change_blocks_other_routes(
    db_session: Session,
    user: User,
    client: TestClient,
) -> None:
    """A user who must change their password gets the standard 403 elsewhere.

    The route uses the ordinary ``CurrentUser``, as every route outside the
    exempt three does. The body has the ``PASSWORD_CHANGE_REQUIRED`` code
    the web app reads to show the change-password screen.
    """
    user.must_change_password = True
    db_session.flush()

    response = client.get(GATED_URL, headers=_auth_header(user))

    assert response.status_code == 403

    error = response.json()["error"]

    assert error["code"] == ErrorCode.PASSWORD_CHANGE_REQUIRED
    assert error["message"] == "You must change your password before continuing."


@pytest.mark.usefixtures("gated_route")
def test_a_user_without_a_pending_change_reaches_other_routes(
    db_session: Session,
    user: User,
    client: TestClient,
) -> None:
    """Without a pending change the same route answers 200 for that user.

    This is the positive control: it proves the test route works, so the
    403 in the previous test comes from the gate and nothing else.
    """
    user.must_change_password = False
    db_session.flush()

    response = client.get(GATED_URL, headers=_auth_header(user))

    assert response.status_code == 200
    assert response.json() == {"user_id": str(user.id)}


@pytest.mark.usefixtures("gated_route")
def test_a_gated_route_without_an_access_token_is_the_standard_401(client: TestClient) -> None:
    """Without an access token the caller isn't signed in, so it's a 401, never a 403."""
    response = client.get(GATED_URL)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == ErrorCode.AUTHENTICATION_FAILED


@pytest.mark.usefixtures("gated_route")
def test_a_deactivated_user_with_a_pending_change_gets_401_not_403(
    db_session: Session,
    user: User,
    client: TestClient,
) -> None:
    """The account check runs before the gate, so a deactivated user gets 401.

    A 403 would tell the holder of an old token that the account still
    exists and only needs a new password; a deactivated account must look
    like any other rejected token.
    """
    headers = _auth_header(user)
    user.must_change_password = True
    user.is_active = False
    db_session.flush()

    response = client.get(GATED_URL, headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == ErrorCode.AUTHENTICATION_FAILED


@pytest.mark.usefixtures("gated_route")
def test_changing_the_password_opens_the_other_routes(
    db_session: Session,
    user: User,
    client: TestClient,
) -> None:
    """The whole forced-change flow: blocked, change the password, then let in.

    The user is refused first, changes the password through the exempt
    route, and with the access token that change returns reaches the route
    that refused them a moment earlier.
    """
    user.must_change_password = True
    db_session.flush()
    headers = _auth_header(user)

    blocked_response = client.get(GATED_URL, headers=headers)
    change_response = client.post(
        CHANGE_PASSWORD_URL, json=_password_change_body(), headers=headers
    )

    assert blocked_response.status_code == 403
    assert change_response.status_code == 200

    new_headers = {"Authorization": f"Bearer {change_response.json()['access_token']}"}
    allowed_response = client.get(GATED_URL, headers=new_headers)

    assert allowed_response.status_code == 200
