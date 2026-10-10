import pytest
from factories import make_user
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ErrorCode
from app.core.security import REFRESH_COOKIE_NAME
from app.core.security import decode_access_token
from app.core.security import hash_password
from app.core.security import hash_refresh_token
from app.modules.auth.models import RefreshToken
from app.modules.users.models import User

LOGIN_URL = "/api/v1/auth/login"
PASSWORD = "Correct-Password-1"


@pytest.fixture
def user(db_session: Session) -> User:
    """Save an active user, test@example.com, whose password is ``PASSWORD``.

    The hash is real, unlike ``make_user``'s default, which can never sign
    in. The user is flushed, not committed, so the test's rollback removes
    it.

    Args:
        db_session: The test's session.

    Returns:
        The saved user.
    """
    user = make_user(password_hash=hash_password(PASSWORD))
    db_session.add(user)
    db_session.flush()

    return user


def test_login_returns_a_bearer_access_token(user: User, client: TestClient) -> None:
    """A successful sign-in answers 200 with a bearer token that names the user.

    The body has exactly two keys, so any extra field, such as the refresh
    token, would fail the test. Decoding proves the token is genuine.
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
) -> None:
    """Sign-in sets the refresh cookie with every security flag.

    The flags are read from the raw ``Set-Cookie`` header, because the
    client's cookie jar keeps only names and values. ``Max-Age`` comes from
    the settings, and ``Secure`` is absent because tests don't run in
    production; ``test_security.py`` covers the production case.
    """
    response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})

    set_cookie = response.headers["set-cookie"].lower()

    assert f"{REFRESH_COOKIE_NAME}=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie
    assert "path=/api/v1/auth" in set_cookie

    expected_max_age = get_settings().refresh_token_expire_days * 24 * 60 * 60

    assert f"max-age={expected_max_age}" in set_cookie
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
    refresh_token = response.cookies[REFRESH_COOKIE_NAME]
    tokens = db_session.scalars(select(RefreshToken)).all()

    assert len(tokens) == 1
    assert hash_refresh_token(refresh_token) == tokens[0].token_hash


def test_the_refresh_token_never_appears_in_the_body(user: User, client: TestClient) -> None:
    """The refresh token's value appears nowhere in the response body.

    The body is searched as text, so the token can't hide in any field. It
    must stay in the ``HttpOnly`` cookie, out of reach of page scripts.
    """
    response = client.post(LOGIN_URL, data={"username": user.email, "password": PASSWORD})
    refresh_token = response.cookies[REFRESH_COOKIE_NAME]

    assert refresh_token not in response.text


def test_wrong_credentials_return_the_standard_401(user: User, client: TestClient) -> None:
    """A wrong password gets a 401 in the standard error format and no cookie.

    The status and code are written out, not read from
    ``AuthenticationError``, so a change to the API's contract fails the
    test. The service tests cover every other kind of failed sign-in.
    """
    response = client.post(LOGIN_URL, data={"username": user.email, "password": "Wrong Password"})
    error = response.json()["error"]

    assert response.status_code == 401
    assert error["code"] == ErrorCode.AUTHENTICATION_FAILED
    assert error["message"] == "Incorrect email or password."
    assert "set-cookie" not in response.headers


def test_login_without_a_username_is_a_validation_error(client: TestClient) -> None:
    """A form without a username gets a 422 that names the missing field.

    The only detail is ``body.username``, so the request failed for this
    reason alone. No user is needed: validation rejects the request before
    the service runs.
    """
    response = client.post(LOGIN_URL, data={"password": PASSWORD})
    error = response.json()["error"]

    assert response.status_code == 422
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

    The endpoint accepts only the documented form. The credentials are
    real, so the 422 can only come from the format, and the empty token
    table proves the service never ran.
    """
    response = client.post(LOGIN_URL, json={"username": user.email, "password": PASSWORD})
    error = response.json()["error"]

    assert response.status_code == 422
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["message"] == "The request contains invalid data."
    assert "set-cookie" not in response.headers
    assert db_session.scalars(select(RefreshToken)).all() == []
