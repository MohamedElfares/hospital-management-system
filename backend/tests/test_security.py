"""Tests for the password, token, and cookie helpers in ``app/core/security.py``.

These are unit tests: they call the functions directly, with no database
and no request. Password hashing is checked for its Argon2id format, a
new salt for every hash, an exact comparison, and the warning a stored
value in an unknown format gets; ``verify_login_password`` for its
answers and for the dummy-hash check that makes an unknown email as slow
to reject as a wrong password. ``_make_token`` builds access tokens with
PyJWT that are valid except for the one thing a rejection test changes,
so each rejection comes from the check the test names. Refresh tokens
are checked for their length, their characters, and their SHA-256 hash,
and the cookie helpers for the header each one writes, parsed so that
each attribute is compared whole, and for the two headers agreeing, with
the ``Secure`` flag checked in production through a copy of the settings.
What the API does with these helpers, such as the 401 a bad token gets
and the cookie a sign-in sets, is tested in ``tests/test_auth_api.py``.
"""

# Matches a refresh token and its hash against the characters each may contain.
import re

# A random key of the test's own, to sign a token the application must refuse.
import secrets

# Random user IDs for the tokens; a decoded subject is compared with one.
import uuid

# UTC time zone; the tokens' timestamps are built in UTC, as the application builds them.
from datetime import UTC

# The current time, for a token's iat and exp and for the bounds iat must fall between.
from datetime import datetime

# Token lifetimes: the configured lifetime after iat, or a minute in the past.
from datetime import timedelta

# Type of one parsed cookie, with its value and attributes.
from http.cookies import Morsel

# Parses a Set-Cookie header the way a cookie jar does, so attributes are compared whole.
from http.cookies import SimpleCookie

# Type hint for claim values, which mix strings and datetimes.
from typing import Any

# PyJWT; builds tokens the application never would, and reads a real token's claims.
import jwt

# Test framework: parametrize, raises, and the monkeypatch and caplog types.
import pytest

# A hash in bcrypt's format, the one make_user stores, as an account hashed before
# Argon2 would hold; pwdlib's recommended hasher identifies only Argon2.
from factories import FAKE_PASSWORD_HASH

# The response the cookie helpers write their Set-Cookie header to.
from fastapi import Response

# The module under test, so monkeypatch can replace names where its functions look them up.
from app.core import security

# Cached settings: the signing key and the token lifetime; the cookie tests copy them.
from app.core.config import get_settings

# The error every rejected access token raises, which the API answers with 401.
from app.core.errors import AuthenticationError

# The hash an unknown email's password is checked against.
from app.core.security import _DUMMY_HASH

# Writes the header that deletes the refresh cookie.
from app.core.security import clear_refresh_cookie

# Signs an access token for a user ID.
from app.core.security import create_access_token

# Verifies an access token and returns the user ID it names.
from app.core.security import decode_access_token

# Makes a new random refresh token.
from app.core.security import generate_refresh_token

# Hashes a password with Argon2id.
from app.core.security import hash_password

# Hashes a refresh token with SHA-256, as it is stored.
from app.core.security import hash_refresh_token

# Writes the Set-Cookie header that carries a refresh token.
from app.core.security import set_refresh_cookie

# Checks a sign-in password, against the dummy hash when no user matched.
from app.core.security import verify_login_password

# Checks a password against a stored hash.
from app.core.security import verify_password

# Written out rather than imported from app.core.security, so a change to the
# module's algorithm fails these tests instead of silently passing them.
JWT_ALGORITHM = "HS256"

# The password most tests hash. hash_password applies no rule of its own, so it
# needn't meet the password rule that the request schemas enforce.
PASSWORD: str = "Password@1331"

# One password in Unicode's two forms, written with escapes so the difference shows:
# ä and ö as single characters (composed, NFC), and as a and o, each followed by a
# combining diaeresis (decomposed, NFD).
COMPOSED_PASSWORD = "Pässwörd123!"
DECOMPOSED_PASSWORD = "Pässwörd123!"

# The attributes the header that deletes the refresh cookie must share with the
# header that set it: a browser matches the path, and clear_refresh_cookie keeps
# the flags. The value and Max-Age differ on purpose.
SHARED_COOKIE_ATTRIBUTES = ("path", "domain", "httponly", "samesite", "secure")


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

    # PyJWT raises InvalidKeyError for alg "none" unless the key is None or empty.
    if algorithm == "none":
        signing_key = None
    elif key is not None:
        signing_key = key
    else:
        signing_key = settings.jwt_secret_key.get_secret_value()

    return jwt.encode(claims, signing_key, algorithm=algorithm)


def _refresh_cookie(response: Response) -> Morsel[str]:
    """Parse the refresh cookie out of a response's ``Set-Cookie`` header.

    ``SimpleCookie`` reads the header the way a cookie jar does, so a test
    compares each attribute whole. A check for the text
    ``path=/api/v1/auth`` anywhere in the header would also pass
    ``/api/v1/auth/``, which a browser treats as another cookie's path.

    Args:
        response: A response that one of the cookie helpers has written to.

    Returns:
        The ``refresh_token`` cookie. Its ``value`` is the token, and each
        attribute is read by its lowercase name, such as
        ``cookie["path"]``; ``httponly`` and ``secure`` are True when set
        and an empty string when not.

    Raises:
        KeyError: If the header sets no ``refresh_token`` cookie.
    """
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    return cookie["refresh_token"]


def test_a_hash_is_argon2_and_not_the_password() -> None:
    """Hashing gives an Argon2id string, not the password itself.

    The ``$argon2id$`` prefix names the algorithm, which pwdlib reads back
    when it verifies, so a hasher switched to another algorithm, such as
    bcrypt, fails here. The settings and the salt follow the prefix, and
    ``test_a_hash_uses_the_documented_argon2_settings`` reads them.
    """
    password_hash: str = hash_password(PASSWORD)

    assert password_hash.startswith("$argon2id$")
    assert password_hash != PASSWORD


def test_a_hash_uses_the_documented_argon2_settings() -> None:
    """A hash records the Argon2 settings ``hash_password`` documents.

    The part before the salt names the variant, the version, and the
    costs: ``m=65536`` KiB of memory (64 MiB), ``t=3`` passes over it, and
    ``p=4`` lanes, the second option RFC 9106 recommends, which pwdlib's
    ``recommended()`` gives today. Verifying reads the settings back from
    each hash, so they decide what every guess costs someone who has stolen
    the hashes. No other test reads them: with far cheaper settings the
    rest of the suite passes, and runs faster. The 97 characters are that
    part, a 16-byte salt, and a 32-byte digest, each encoded. A deliberate
    change updates this test and the docstring together, and a pwdlib
    release that changed its defaults fails here first.
    """
    password_hash = hash_password(PASSWORD)

    assert password_hash.rsplit("$", 2)[0] == "$argon2id$v=19$m=65536,t=3,p=4"
    assert len(password_hash) == 97


def test_the_same_password_gets_a_different_hash_each_time() -> None:
    """Two hashes of one password differ, and both still verify.

    Each hash gets a new random salt, so two users with the same password
    get different hashes: a stolen ``users`` table doesn't show which
    accounts share a password, and each hash has to be guessed on its own,
    because no table of hashes computed in advance covers a salt no one
    has seen before.
    """
    first_password_hash: str = hash_password(PASSWORD)
    second_password_hash: str = hash_password(PASSWORD)

    assert first_password_hash != second_password_hash
    assert verify_password(PASSWORD, first_password_hash) is True
    assert verify_password(PASSWORD, second_password_hash) is True


def test_the_right_password_verifies() -> None:
    """The password that was hashed verifies against its own hash."""
    password_hash: str = hash_password(PASSWORD)

    assert verify_password(PASSWORD, password_hash) is True


@pytest.mark.parametrize(
    ("submitted", "stored"),
    [
        pytest.param("password@1331", "Password123", id="totally wrong"),
        pytest.param("S3cret", "s3cret", id="different case"),
        pytest.param("s3cret ", "s3cret", id="trailing space"),
        pytest.param("ﬁle-cabinet-1", "file-cabinet-1", id="ligature"),
    ],
)
def test_a_wrong_password_is_rejected(submitted: str, stored: str) -> None:
    """A submitted password that differs from the stored one fails to verify.

    Apart from the Unicode form, which
    ``test_a_password_verifies_in_either_unicode_form`` covers, passwords
    are compared exactly, so even a small difference, such as a letter's
    case, a trailing space, or the fi ligature (U+FB01) where the stored
    password has the two letters, must be rejected rather than normalized
    away. NFC leaves the ligature as it is; NFKC would fold it into "fi".
    """
    password_hash: str = hash_password(stored)

    assert verify_password(submitted, password_hash) is False


def test_a_unicode_password_round_trips() -> None:
    """A password with non-ASCII characters hashes and then verifies.

    The password is typed in one Unicode form, with each accented letter as
    a single character, and verified in that same form;
    ``test_a_password_verifies_in_either_unicode_form`` covers the other
    form.
    """
    unicode_password = "Pässwörd123!"
    password_hash = hash_password(unicode_password)

    assert verify_password(unicode_password, password_hash) is True


@pytest.mark.parametrize(
    ("set_password", "typed_password"),
    [
        pytest.param(COMPOSED_PASSWORD, DECOMPOSED_PASSWORD, id="set-composed-typed-decomposed"),
        pytest.param(DECOMPOSED_PASSWORD, COMPOSED_PASSWORD, id="set-decomposed-typed-composed"),
    ],
)
def test_a_password_verifies_in_either_unicode_form(set_password: str, typed_password: str) -> None:
    """A password matches its own hash when typed in the other Unicode form.

    The two forms look the same on screen but are different strings, 12
    and 14 code points long. ``hash_password`` and ``verify_password`` both
    put a password in NFC, as NIST SP 800-63B-4 recommends, so the two
    match in either order; each case fails if one of the two functions
    skips that step.
    """
    assert set_password != typed_password

    password_hash = hash_password(set_password)

    assert verify_password(typed_password, password_hash) is True


def test_a_very_long_password_round_trips() -> None:
    """A 3,000-character password hashes and then verifies.

    ``hash_password`` sets no limit of its own: the 128-character maximum
    belongs to the request schemas, and Argon2 takes a password of any
    practical length, where bcrypt uses only its first 72 bytes. The round
    trip shows that a long password is accepted, not that every character
    counts, since a hasher that cut it short would pass too;
    ``test_every_character_of_a_long_password_counts`` checks that.
    """
    long_password = "abc" * 1000
    password_hash = hash_password(long_password)

    assert verify_password(long_password, password_hash) is True


def test_every_character_of_a_long_password_counts() -> None:
    """A 128-character password fails when only its last character differs.

    128 is the longest password the request schemas accept, so it is the
    longest that can reach ``hash_password``. NIST SP 800-63B-4 requires a
    verifier to check the entire password, never a truncated one
    (§3.1.1.2). A hasher that kept only the first 72 characters, as bcrypt
    keeps only the first 72 bytes, would let the last 56 count for nothing,
    and would still pass every round trip.
    """
    password_hash = hash_password("a" * 127 + "b")

    assert verify_password("a" * 128, password_hash) is False


@pytest.mark.parametrize(
    "password_hash",
    [
        pytest.param(FAKE_PASSWORD_HASH, id="bcrypt-hash"),
        pytest.param("not-a-real-hash", id="garbage"),
    ],
)
def test_an_unsupported_hash_fails_and_logs_a_safe_warning(
    password_hash: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stored value pwdlib can't identify fails to verify, with a warning that leaves it out.

    The cases are a hash in bcrypt's format, the one ``make_user`` stores,
    and text that is no hash at all. pwdlib raises ``UnknownHashError`` for both, and
    ``verify_password`` turns that into False, so sign-in answers 401
    rather than 500, and logs a warning so the bad row gets noticed. The
    test captures every logger from WARNING up, and checks that a warning
    was logged and that the stored value appears nowhere in the captured
    text. A damaged value that still looks like an Argon2 hash isn't
    covered: pwdlib reports it as an ordinary mismatch, without a warning.
    """
    with caplog.at_level("WARNING"):
        is_correct = verify_password("some-password", password_hash)

    assert is_correct is False
    assert any(record.levelname == "WARNING" for record in caplog.records)
    assert password_hash not in caplog.text


def test_the_dummy_hash_is_argon2_and_matches_no_password() -> None:
    """The dummy hash is an Argon2id hash that an ordinary password doesn't match.

    ``verify_login_password`` checks an unknown email's password against
    it, so that rejecting the email costs as much as rejecting a wrong
    password. That needs a well-formed hash with the settings real hashes
    have, because Argon2 takes its cost from the settings written into the
    hash. This test checks the prefix and one password;
    ``test_the_dummy_hash_has_the_settings_of_a_real_hash`` checks the
    rest.
    """
    assert verify_password(PASSWORD, _DUMMY_HASH) is False
    assert _DUMMY_HASH.startswith("$argon2id$")


def test_the_dummy_hash_has_the_settings_of_a_real_hash() -> None:
    """The dummy hash has the settings and the length of a hash made now.

    Argon2 takes its cost from the settings written into a hash, so checking
    a password against the dummy costs what a real check does only while
    the dummy has a real hash's settings, and parses. A dummy made with
    cheaper settings, or written out by hand without its digest, which
    argon2-cffi refuses at once, would let an unknown email be answered
    thousands of times faster than a wrong password, and so show which
    emails have accounts. The dummy is compared with a fresh hash rather
    than with fixed values, so it keeps following ``hash_password``;
    ``test_a_hash_uses_the_documented_argon2_settings`` pins the values.
    """
    password_hash = hash_password(PASSWORD)

    assert _DUMMY_HASH.rsplit("$", 2)[0] == password_hash.rsplit("$", 2)[0]
    assert len(_DUMMY_HASH) == len(password_hash)


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


def test_an_access_token_holds_only_sub_iat_and_exp(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token carries exactly ``sub``, ``iat``, and ``exp``, with correct values.

    ``sub`` is the user's ID, ``iat`` is the time of creation, and ``exp``
    is one configured lifetime later. No other claim, such as the role or
    the email, may appear: the token can be read by anyone who holds it, and
    those values would go stale. ``get_settings`` is replaced where
    ``create_access_token`` looks it up, with a copy whose
    ``ACCESS_TOKEN_EXPIRE_MINUTES`` is 9, a value no setting has by
    default, so a lifetime written into the code, or read from another
    setting such as the refresh token's 7 days, fails here, whatever the
    environment configures.
    """
    nine_minute_settings = get_settings().model_copy(update={"access_token_expire_minutes": 9})
    monkeypatch.setattr(security, "get_settings", lambda: nine_minute_settings)
    jwt_secret_key = nine_minute_settings.jwt_secret_key.get_secret_value()

    user_id = uuid.uuid4()

    before = int(datetime.now(UTC).timestamp())
    token = create_access_token(user_id)
    after = int(datetime.now(UTC).timestamp())

    payload = jwt.decode(token, key=jwt_secret_key, algorithms=[JWT_ALGORITHM])

    assert set(payload) == {"sub", "iat", "exp"}
    assert payload["sub"] == str(user_id)
    assert payload["iat"] >= before
    assert payload["iat"] <= after
    assert payload["exp"] - payload["iat"] == 9 * 60


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

    PyJWT refuses each one before it checks a signature: the empty string
    and ``not-a-token`` don't split into a token's three dot-separated
    parts, and ``a.b.c`` does, but its header isn't valid base64url. Each
    must give the generic 401, never a 500.
    """
    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(token)

    assert exc_info.value.message == "Invalid or expired token."


def test_two_refresh_tokens_are_never_the_same() -> None:
    """A hundred generated refresh tokens are all different.

    With 256 random bits a repeat never happens by chance, so one would
    mean the generator had lost its randomness, such as one that returns a
    fixed value or starts from the same seed on every call. A generator
    that is predictable but never repeats, such as a counter, passes: that
    the tokens can't be guessed rests on ``secrets``, which a unit test
    can't measure.
    """
    tokens = set()
    for _ in range(100):
        tokens.add(generate_refresh_token())

    assert len(tokens) == 100


def test_a_refresh_token_is_url_safe_and_long_enough() -> None:
    """A refresh token has at least 43 characters, all safe in a cookie.

    Forty-three is the length of 32 random bytes in URL-safe base64,
    without the ``=`` padding. Only letters, digits, ``-``, and ``_`` may
    appear, so the cookie needs no escaping.
    """
    token = generate_refresh_token()

    assert len(token) >= 43
    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)


def test_a_refresh_token_hash_is_64_hex_characters() -> None:
    """A refresh token's hash has the shape of the ``token_hash`` column.

    Sixty-four lowercase hex characters fit ``String(64)``. A raw token is
    43 characters long, so a function that returned the token instead of
    its hash would fail here.
    """
    token = generate_refresh_token()
    assert re.fullmatch(r"[0-9a-f]{64}", hash_refresh_token(token))


def test_a_refresh_token_hash_is_plain_sha256() -> None:
    """Hashing ``"abc"`` gives the published SHA-256 test vector.

    A fixed expected value pins the exact algorithm and shows that nothing
    else, such as a salt, goes into the hash, so the same token always
    gives the same hash. Adding a salt or switching algorithms would make
    stored tokens unfindable and sign everyone out, and this test would
    fail first.
    """
    sha256_of_abc = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

    assert hash_refresh_token("abc") == sha256_of_abc


def test_different_refresh_tokens_get_different_hashes() -> None:
    """A hundred different refresh tokens give a hundred different hashes.

    Each refresh must find exactly one row, so two tokens may never share
    a hash.
    """
    token_hashes = set()

    for _ in range(100):
        token_hashes.add(hash_refresh_token(generate_refresh_token()))

    assert len(token_hashes) == 100


def test_verify_login_password_accepts_the_right_password() -> None:
    """With an existing user, the right password is accepted."""
    assert verify_login_password(PASSWORD, hash_password(PASSWORD)) is True


def test_verify_login_password_rejects_a_wrong_password() -> None:
    """With an existing user, a password that doesn't match their hash is rejected."""
    assert verify_login_password(PASSWORD, hash_password(PASSWORD + "abc")) is False


def test_verify_login_password_without_a_user_returns_false() -> None:
    """With no matching user, the check fails.

    The dummy check's own answer is False as well, since no one knows the
    password the dummy hash was made from, so this test can't tell the
    explicit False that ``verify_login_password`` returns from that answer;
    ``test_verify_login_password_without_a_user_fails_even_if_the_dummy_matched``
    does.
    """
    assert verify_login_password(PASSWORD, None) is False


def test_verify_login_password_without_a_user_fails_even_if_the_dummy_matched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no matching user, the answer is False even when the dummy check says yes.

    ``verify_login_password`` ignores the dummy check's answer and returns
    False itself, so an email that matches no account can never sign in,
    whatever the dummy hash is. ``verify_password`` is replaced here with
    one that always answers True, as it would if the dummy hash were ever
    made from a password someone could type, so a copy that returned the
    dummy check's answer fails. ``login`` checks for a missing user again,
    but its comment says that check is there for the type checker; the
    rule lives here.
    """

    def always_matches(password: str, password_hash: str) -> bool:
        """Answer as if every password matched every hash.

        Args:
            password: The submitted password, ignored.
            password_hash: The hash it is checked against, ignored.

        Returns:
            Always True.
        """
        return True

    monkeypatch.setattr(security, "verify_password", always_matches)

    assert verify_login_password(PASSWORD, None) is False


def test_verify_login_password_without_a_user_still_checks_the_dummy_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no matching user, the password is still verified against the dummy hash.

    ``verify_password`` must run exactly once, against ``_DUMMY_HASH``, so
    an unknown email costs the same Argon2 work as a wrong password and
    response times can't reveal which emails have accounts. A spy records
    the calls, because measuring time would be too unreliable for a test.
    The answer is False either way, as
    ``test_verify_login_password_without_a_user_returns_false`` checks, so
    only this test fails when the dummy check is removed. How long the
    check takes depends on ``_DUMMY_HASH`` itself, which the spy can't see.
    """
    calls: list[str] = []
    real_verify = verify_password

    def spy(password: str, password_hash: str) -> bool:
        """Record the hash being checked, then run the real verification.

        Args:
            password: The submitted password, passed on unchanged.
            password_hash: The hash ``verify_login_password`` checks
                against.

        Returns:
            The real ``verify_password``'s answer.
        """
        calls.append(password_hash)
        return real_verify(password, password_hash)

    monkeypatch.setattr(security, "verify_password", spy)

    assert verify_login_password(PASSWORD, None) is False
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
    production_settings = get_settings().model_copy(update={"environment": "production"})
    monkeypatch.setattr(security, "get_settings", lambda: production_settings)

    response = Response()
    set_refresh_cookie(response, "token")

    assert "secure" in response.headers["set-cookie"].lower()


def test_clear_refresh_cookie_expires_the_refresh_cookie() -> None:
    """Clearing sends the refresh cookie back empty, with ``Max-Age=0``, on its exact path.

    A browser replaces a cookie only with one of the same name, domain, and
    path, so the deleting header must name ``refresh_token`` and exactly
    ``/api/v1/auth``, as ``set_refresh_cookie`` does, and ``Max-Age=0``
    then deletes it. A longer path, such as ``/api/v1/auth/``, would name
    another cookie and leave the real one in the browser, so the header is
    parsed and each attribute compared whole. ``HttpOnly`` and
    ``SameSite=Strict`` are checked too: deleting doesn't need them, but
    ``clear_refresh_cookie`` keeps the cookie's flags, so the deleting
    header follows the same rules.
    """
    response = Response()
    clear_refresh_cookie(response)
    cleared_cookie = _refresh_cookie(response)

    assert cleared_cookie.value == ""
    assert cleared_cookie["max-age"] == "0"
    assert cleared_cookie["path"] == "/api/v1/auth"
    assert cleared_cookie["httponly"] is True
    assert cleared_cookie["samesite"] == "strict"


@pytest.mark.parametrize(
    "environment",
    [
        pytest.param("test", id="outside-production"),
        pytest.param("production", id="in-production"),
    ],
)
def test_clearing_the_refresh_cookie_repeats_its_path_and_flags(
    environment: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deleting header carries the path and flags of the cookie it deletes.

    ``clear_refresh_cookie`` promises that its attributes match
    ``set_refresh_cookie``'s exactly: with another path, the browser takes
    the deleting header for a different cookie and keeps the real one, and
    the flags match by choice. The two headers are compared with each other
    rather than with fixed values, so a change to either function alone
    fails, in both branches of ``Secure``;
    ``test_clear_refresh_cookie_expires_the_refresh_cookie`` pins the
    values. ``get_settings`` is replaced with a copy for each environment,
    as in the production tests.
    """
    environment_settings = get_settings().model_copy(update={"environment": environment})
    monkeypatch.setattr(security, "get_settings", lambda: environment_settings)
    set_response = Response()
    set_refresh_cookie(set_response, "token")
    clear_response = Response()
    clear_refresh_cookie(clear_response)

    set_cookie = _refresh_cookie(set_response)
    cleared_cookie = _refresh_cookie(clear_response)

    assert {name: cleared_cookie[name] for name in SHARED_COOKIE_ATTRIBUTES} == {
        name: set_cookie[name] for name in SHARED_COOKIE_ATTRIBUTES
    }


def test_the_cleared_cookie_is_secure_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """In production, the header that clears the refresh cookie carries ``Secure``.

    ``clear_refresh_cookie`` gives the deleting header the cookie's flags,
    and in production that includes ``Secure``, as ``set_refresh_cookie``
    sets it. A copy that drops the flag from the deleting header fails
    here; a change to ``set_refresh_cookie`` alone fails
    ``test_the_refresh_cookie_is_secure_in_production`` instead.
    ``get_settings`` is replaced with a production copy, as in that test.
    """
    production_settings = get_settings().model_copy(update={"environment": "production"})
    monkeypatch.setattr(security, "get_settings", lambda: production_settings)

    response = Response()
    clear_refresh_cookie(response)

    assert "secure" in response.headers["set-cookie"].lower()
