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
from app.core.security import generate_refresh_token
from app.core.security import hash_password
from app.core.security import hash_refresh_token
from app.modules.auth.models import RefreshToken
from app.modules.users.models import User

LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/auth/me"
REFRESH_URL = "/api/v1/auth/refresh"
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
    error = refresh_response.json()["error"]

    assert refresh_response.status_code == 401
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
    error = refresh_response.json()["error"]

    assert refresh_response.status_code == 401
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
    reuse_error = reuse_response.json()["error"]

    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE_NAME, new_token, path="/api/v1/auth")
    after_reuse_response = client.post(REFRESH_URL)
    after_reuse_error = after_reuse_response.json()["error"]

    assert reuse_response.status_code == 401
    assert reuse_error["code"] == "AUTHENTICATION_FAILED"
    assert reuse_error["message"] == "Invalid or expired token."
    assert after_reuse_response.status_code == 401
    assert after_reuse_error["code"] == "AUTHENTICATION_FAILED"
    assert after_reuse_error["message"] == "Invalid or expired token."


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
