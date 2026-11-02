import re
import secrets
import uuid
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Any

import jwt
import pytest
from fastapi import Response

from app.core import security
from app.core.config import get_settings
from app.core.errors import AuthenticationError
from app.core.security import _DUMMY_HASH
from app.core.security import check_password
from app.core.security import clear_refresh_cookie
from app.core.security import create_access_token
from app.core.security import decode_access_token
from app.core.security import generate_refresh_token
from app.core.security import hash_password
from app.core.security import hash_refresh_token
from app.core.security import set_refresh_cookie
from app.core.security import verify_password

# Written out rather than imported from app.core.security, so a change to the
# module's algorithm fails these tests instead of silently passing them.
JWT_ALGORITHM = "HS256"
PASSWORD: str = "Password@1331"
OLD_BCRYPT_HASH = "$2a$12$xmwWaOMD74tVfixmTpxpWe7oZiybi9crvSu0lbrbe9NXCx8CS1nq"


def _make_token(
    *,
    key: str | None = None,
    algorithm: str = JWT_ALGORITHM,
    omit: tuple[str, ...] = (),
    **overrides: Any,
) -> str:
    """Build an access token that is valid except for what the caller changes.

    Starts from the claims ``create_access_token`` would produce (a new
    random ``sub``, ``iat`` now, ``exp`` one token lifetime later), applies
    ``overrides``, removes the claims named in ``omit``, and signs the result
    with the application's key. Each negative test then changes exactly one
    thing, so it fails at the check its name describes.

    Args:
        key: Signing key. Defaults to the application's ``JWT_SECRET_KEY``.
            Ignored when ``algorithm`` is ``"none"``.
        algorithm: Signing algorithm. ``"none"`` produces an unsigned token.
        omit: Claim names to leave out of the token, such as ``("exp",)``.
        **overrides: Claim values that replace the defaults, such as
            ``exp=...`` or ``sub="admin"``.

    Returns:
        The encoded token.

    Raises:
        KeyError: If ``omit`` names a claim that isn't present, so a typo
            fails the test instead of silently building a valid token.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    claims.update(overrides)
    for name in omit:
        del claims[name]

    # PyJWT refuses any key for alg "none"; it must be None.
    if algorithm == "none":
        signing_key = None
    elif key is not None:
        signing_key = key
    else:
        signing_key = settings.jwt_secret_key.get_secret_value()

    return jwt.encode(claims, signing_key, algorithm=algorithm)


def test_a_hash_is_argon2_and_not_the_password() -> None:
    """Hashing gives an Argon2id string that doesn't contain the password as is."""
    hashed_password: str = hash_password(PASSWORD)

    assert hashed_password.startswith("$argon2id$")
    assert hashed_password != PASSWORD


def test_the_same_password_gets_a_different_hash_each_time() -> None:
    """Two hashes of one password differ, and both still verify.

    Each hash gets its own random salt, so users who share a password don't
    share a hash, and one cracked hash doesn't unlock the others.
    """
    first_hashed_password: str = hash_password(PASSWORD)
    second_hashed_password: str = hash_password(PASSWORD)

    assert first_hashed_password != second_hashed_password
    assert verify_password(PASSWORD, first_hashed_password) is True
    assert verify_password(PASSWORD, second_hashed_password) is True


def test_the_right_password_verifies() -> None:
    """The password that was hashed verifies against its own hash."""
    hashed_password: str = hash_password(PASSWORD)

    assert verify_password(PASSWORD, hashed_password) is True


@pytest.mark.parametrize(
    ("submitted", "stored"),
    [
        pytest.param("password@1331", "Password123", id="totally wrong"),
        pytest.param("S3cret", "s3cret", id="different case"),
        pytest.param("s3cret ", "s3cret", id="trailing space"),
    ],
)
def test_a_wrong_password_is_rejected(submitted: str, stored: str) -> None:
    """A submitted password that differs from the stored one fails to verify.

    Passwords are compared exactly, so even a small difference must be
    rejected rather than normalized away.
    """
    hashed_password: str = hash_password(stored)

    assert verify_password(submitted, hashed_password) is False


def test_a_unicode_password_round_trips() -> None:
    """A password with non-ASCII characters hashes and then verifies."""
    unicode_password = "Pässwörd123!"
    hashed_password = hash_password(unicode_password)

    assert verify_password(unicode_password, hashed_password) is True


def test_a_very_long_password_round_trips() -> None:
    """A 3,000-character password hashes and then verifies.

    Argon2 has no input limit, unlike bcrypt, which silently ignores
    everything after 72 bytes.
    """
    long_password = "abc" * 1000
    hashed_password = hash_password(long_password)

    assert verify_password(long_password, hashed_password) is True


@pytest.mark.parametrize(
    "hashed_password",
    [
        pytest.param(OLD_BCRYPT_HASH, id="bcrypt-hash"),
        pytest.param("not-a-real-hash", id="garbage"),
    ],
)
def test_an_unsupported_hash_fails_and_logs_a_safe_warning(
    hashed_password: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A bcrypt or corrupted stored hash fails to verify, with a safe warning.

    pwdlib raises for hashes it doesn't recognize; ``verify_password``
    turns that into False so sign-in answers 401, not 500. The warning must
    be logged, and it must not contain the hash.
    """
    with caplog.at_level("WARNING"):
        result = verify_password("some-password", hashed_password)

    assert result is False
    assert any(record.levelname == "WARNING" for record in caplog.records)
    assert hashed_password not in caplog.text


def test_the_dummy_hash_is_argon2_and_matches_no_password() -> None:
    """The dummy hash is a real Argon2id hash that an ordinary password doesn't match.

    Being Argon2id with the normal settings is what makes verifying against
    it take as long as a real sign-in.
    """
    assert verify_password(PASSWORD, _DUMMY_HASH) is False
    assert _DUMMY_HASH.startswith("$argon2id$")


def test_the_token_helper_builds_a_valid_token() -> None:
    """A token from ``_make_token`` with no changes is accepted.

    This is the control for the rejection tests below: each one changes a
    single thing in this token, so when it is rejected, that change is the
    reason and not a broken helper.
    """
    user_id = uuid.uuid4()
    assert decode_access_token(_make_token(sub=str(user_id))) == user_id


def test_an_access_token_round_trips_to_the_user_id() -> None:
    """Decoding a newly created token gives back the same user ID, as a UUID.

    The result is compared without converting it, so a decoder that
    returned the raw ``sub`` string would fail: a ``str`` never equals a
    ``UUID``.
    """
    user_id = uuid.uuid4()
    token = create_access_token(user_id)

    assert decode_access_token(token) == user_id


def test_an_access_token_holds_only_sub_iat_and_exp() -> None:
    """A token carries exactly ``sub``, ``iat``, and ``exp``, with correct values.

    ``sub`` is the user's ID, ``iat`` is the time of creation, and ``exp``
    is one configured lifetime later. No other claim, such as the role or
    the email, may appear: the token can be read by anyone who holds it, and
    those values would go stale. The lifetime is read from the settings, so
    the test doesn't depend on the environment's value.
    """
    settings = get_settings()
    jwt_secret_key = settings.jwt_secret_key.get_secret_value()
    access_token_expire_minutes = settings.access_token_expire_minutes

    user_id = uuid.uuid4()

    before = int(datetime.now(UTC).timestamp())
    token = create_access_token(user_id)
    after = int(datetime.now(UTC).timestamp())

    payload = jwt.decode(token, key=jwt_secret_key, algorithms=[JWT_ALGORITHM])

    assert set(payload) == {"sub", "iat", "exp"}
    assert payload["sub"] == str(user_id)
    assert payload["iat"] >= before
    assert payload["iat"] <= after
    assert payload["exp"] - payload["iat"] == access_token_expire_minutes * 60


def test_an_expired_access_token_is_rejected() -> None:
    """A correctly signed token whose expiry has passed fails with a 401 error.

    Expired tokens are routine, so they must give the generic 401 that tells
    the client to refresh, never a 500.
    """
    now = datetime.now(UTC)
    token = _make_token(exp=now - timedelta(minutes=1))

    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(token)

    assert exc_info.value.message == "Invalid or expired token."


def test_an_access_token_signed_with_another_key_is_rejected() -> None:
    """A token with valid claims but signed with a different key is rejected.

    Only tokens signed with the application's ``JWT_SECRET_KEY`` are
    trusted; anyone can sign a token with a key of their own.
    """
    token = _make_token(key=secrets.token_urlsafe(32))

    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(token)

    assert exc_info.value.message == "Invalid or expired token."


def test_a_tampered_access_token_is_rejected() -> None:
    """A real token whose claims were swapped for another user's is rejected.

    The header and signature come from a genuine token and the payload
    from a different one, which is how an attacker would try to take over
    another account. The signature no longer matches the claims, so the
    signature check rejects it.
    """
    token = create_access_token(uuid.uuid4())
    header, _, signature = token.split(".")
    _, forged_payload, _ = _make_token().split(".")  # another user's sub
    tampered_token = f"{header}.{forged_payload}.{signature}"

    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(tampered_token)

    assert exc_info.value.message == "Invalid or expired token."


def test_an_unsigned_access_token_is_rejected() -> None:
    """A token with valid claims but ``alg`` set to ``"none"`` is rejected.

    An unsigned token would let anyone write their own claims. Decoding
    accepts only HS256, so the algorithm named in the token is never
    trusted.
    """
    token = _make_token(algorithm="none")

    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(token)

    assert exc_info.value.message == "Invalid or expired token."


def test_an_access_token_without_an_expiry_is_rejected() -> None:
    """A correctly signed token with no ``exp`` claim is rejected.

    PyJWT checks ``exp`` only when it's present, so without the explicit
    requirement such a token would be valid forever.
    """
    token = _make_token(omit=("exp",))

    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(token)

    assert exc_info.value.message == "Invalid or expired token."


def test_an_access_token_whose_subject_is_not_a_uuid_is_rejected() -> None:
    """A correctly signed token whose ``sub`` isn't a UUID fails with a 401 error.

    The signature is valid, so this is the case where parsing ``sub`` raises
    ``ValueError``; it must still give the generic 401, not a 500.
    """
    token = _make_token(sub="admin")

    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(token)

    assert exc_info.value.message == "Invalid or expired token."


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("not-a-token", id="no-dots"),
        pytest.param("", id="empty"),
        pytest.param("a.b.c", id="not-base64-json"),
    ],
)
def test_a_malformed_access_token_is_rejected(token: str) -> None:
    """Input that isn't a JWT at all fails with the same 401 error.

    The cases fail at different stages of parsing: no dots, an empty
    string, and three segments that aren't base64-encoded JSON. Each must
    give the generic 401, never a 500.
    """
    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(token)

    assert exc_info.value.message == "Invalid or expired token."


def test_two_refresh_tokens_are_never_the_same() -> None:
    """A hundred generated refresh tokens are all different.

    With 256 random bits a repeat never happens, so a duplicate would mean
    the generator had become predictable, such as a counter or a clock.
    """
    tokens = set()
    for _ in range(100):
        tokens.add(generate_refresh_token())

    assert len(tokens) == 100


def test_a_refresh_token_is_url_safe_and_long_enough() -> None:
    """A refresh token has at least 43 characters, all safe in a cookie.

    Forty-three is the base64 length of 32 random bytes. Only letters,
    digits, ``-``, and ``_`` may appear, so the cookie needs no escaping.
    """
    token = generate_refresh_token()

    assert len(token) >= 43
    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)


def test_a_refresh_token_hash_is_64_hex_characters() -> None:
    """A refresh token's hash has the shape of the ``token_hash`` column.

    Sixty-four lowercase hex characters fit ``String(64)``, and the raw
    token, with its mixed case, could never match, so the function can't
    be returning the token itself.
    """
    token = generate_refresh_token()
    assert re.fullmatch(r"[0-9a-f]{64}", hash_refresh_token(token))


def test_a_refresh_token_hash_is_plain_sha256() -> None:
    """Hashing ``"abc"`` gives the published SHA-256 test vector.

    This pins the exact algorithm and shows the hash is the same every
    time. Adding a salt or switching algorithms would make stored tokens
    unfindable and sign everyone out, and this test would fail first.
    """
    value = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

    assert hash_refresh_token("abc") == value


def test_different_refresh_tokens_get_different_hashes() -> None:
    """A hundred different refresh tokens give a hundred different hashes.

    Each refresh must find exactly one row, so two tokens may never share
    a hash.
    """
    hash_tokens = set()

    for _ in range(100):
        hash_tokens.add(hash_refresh_token(generate_refresh_token()))

    assert len(hash_tokens) == 100


def test_check_password_accepts_the_right_password() -> None:
    """With an existing user, the right password is accepted."""
    assert check_password(PASSWORD, hash_password(PASSWORD)) is True


def test_check_password_rejects_a_wrong_password() -> None:
    """With an existing user, a password that doesn't match their hash is rejected."""
    assert check_password(PASSWORD, hash_password(PASSWORD + "abc")) is False


def test_check_password_without_a_user_returns_false() -> None:
    """With no matching user, the check always fails."""
    assert check_password(PASSWORD, None) is False


def test_check_password_without_a_user_still_checks_the_dummy_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no matching user, the password is still verified against the dummy hash.

    The slow Argon2 check runs exactly once, against ``_DUMMY_HASH``, so an
    unknown email takes as long as a wrong password. A spy records the
    calls: measuring time would be too unreliable for a test. The previous
    test checks the answer; this one checks the cost, so removing the dummy
    check would fail here even though the answer stays False.
    """
    calls: list[str] = []
    real_verify = verify_password

    def spy(password: str, password_hash: str) -> bool:
        """Record the hash being checked, then run the real verification."""
        calls.append(password_hash)
        return real_verify(password, password_hash)

    monkeypatch.setattr(security, "verify_password", spy)

    assert check_password(PASSWORD, None) is False
    assert calls == [_DUMMY_HASH]


def test_the_refresh_cookie_is_secure_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """In production, the refresh cookie carries the ``Secure`` flag.

    ``Secure`` stops the browser from sending the cookie over plain HTTP,
    where anyone on the network could read it. Tests run outside
    production, so the API tests only ever see the cookie without
    ``Secure``; this test covers the branch that protects real users. Here
    ``get_settings`` is replaced where ``set_refresh_cookie`` looks it up,
    with a copy of the real settings whose environment is production. The
    cached settings themselves are untouched, so no other test is affected.
    """
    production = get_settings().model_copy(update={"environment": "production"})
    monkeypatch.setattr(security, "get_settings", lambda: production)

    response = Response()
    set_refresh_cookie(response, "token")

    assert "secure" in response.headers["set-cookie"].lower()


def test_clear_refresh_cookie_expires_the_refresh_cookie() -> None:
    """Clearing sends the refresh cookie back with ``Max-Age=0``.

    The browser deletes a cookie only when the deleting header names the
    same cookie and path as the one that set it, so the name and
    ``Path=/api/v1/auth`` are checked along with ``Max-Age=0``. The
    ``HttpOnly`` and ``SameSite=Strict`` flags must match the original
    cookie too.
    """
    response = Response()
    clear_refresh_cookie(response)
    cleared_cookie_header = response.headers["set-cookie"].lower()

    assert "httponly" in cleared_cookie_header
    assert "max-age=0" in cleared_cookie_header
    assert "samesite=strict" in cleared_cookie_header
    assert "path=/api/v1/auth" in cleared_cookie_header
    assert cleared_cookie_header.startswith("refresh_token=")


def test_the_cleared_cookie_is_secure_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """In production, the header that clears the refresh cookie carries ``Secure``.

    The deleting header must keep the flags of the cookie it deletes, so a
    change to one cookie function and not the other fails here.
    ``get_settings`` is replaced with a production copy, as in the test
    for setting the cookie.
    """
    production = get_settings().model_copy(update={"environment": "production"})
    monkeypatch.setattr(security, "get_settings", lambda: production)

    response = Response()
    clear_refresh_cookie(response)

    assert "secure" in response.headers["set-cookie"].lower()
