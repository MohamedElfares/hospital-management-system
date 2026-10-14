import pytest
from factories import make_user
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ErrorCode
from app.core.security import REFRESH_COOKIE_NAME
from app.core.security import create_access_token
from app.core.security import decode_access_token
from app.core.security import hash_password
from app.core.security import hash_refresh_token
from app.modules.auth.models import RefreshToken
from app.modules.users.models import User

LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"
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


def _auth_header(user: User) -> dict[str, str]:
    """Build an Authorization header with a fresh access token for the user.

    The token is signed directly, so tests of the current-user route don't
    depend on the login route or pay for its password check. One test goes
    through login on purpose, to prove the two routes work together.

    Args:
        user: The saved user the token should name.

    Returns:
        The headers to pass to the test client.
    """
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


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
    body = response.json()["error"]

    assert response.status_code == 401
    assert body["code"] == "AUTHENTICATION_FAILED"
    assert body["message"] == "Not authenticated"
    assert response.headers["www-authenticate"] == "Bearer"


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

    body = response.json()["error"]

    assert response.status_code == 401
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
    body = response.json()["error"]

    assert response.status_code == 401
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
