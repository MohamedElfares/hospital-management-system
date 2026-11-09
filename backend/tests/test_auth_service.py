"""Tests for the auth service: sign-in, sessions, sign-out, and password changes.

The tests call the service's functions directly with ``db_session``, the
test's own session, so every use case runs against PostgreSQL inside the
test's transaction. A use case's ``commit()`` releases only a savepoint of
that transaction, so the rollback at the end of the test removes what it
saved, and what it flushed without committing stays visible to the test:
a test that must see a commit rolls the session back itself first, as a
request's session is rolled back when the request ends. The tests hold
and present raw refresh tokens, as a browser would; the helpers save only
a token's hash, as the service does, and read a row back by its raw value.

Sign-in returns an access token that names the user and stores only the
hash of a new refresh token, which expires after the configured number of
days; each sign-in adds a session of its own and leaves the user's others
working. It records the sign-in time, accepts the email in any case and
with spaces around it, and lets a user with a pending password change in.
Every failed sign-in raises the very same ``AuthenticationError`` and
writes nothing, and an unknown email and a deactivated account still run
the password check. No sign-in logs or prints a password, the stored
hash, a token, or an email.

A valid access token is turned back into the active user it names, looked
up once by the ID inside it, even while a password change is pending;
every other token gets the very same error, and one that doesn't decode
gets it before any lookup. Refresh rotates the token, keeps its expiry,
leaves the user's other sessions and the sign-in time alone, and stays
open while a password change is pending. A rotated token presented again
revokes every token of its user, commits that, and logs one warning
without the token, however old it is and even when its owner is
deactivated, while every other unusable token, one revoked without
rotation included, is refused with the very same error and ends no
session.

Sign-out revokes the presented token, without linking a replacement,
and commits that, leaving the user's other sessions alone; presented
after a refresh rotated it, the token's replacement is revoked instead,
with no alarm, and the token keeps the time and the link of its
rotation. A missing, empty, or unknown cookie and another user's token
change nothing, a revoked token raises no alarm and ends no other
session, and a second sign-out keeps the first revocation time, the
replacement's when the token was rotated. A password change stores a
hash only the new password matches, clears the forced-change flag,
revokes every session the user had, and starts a new one with a fresh
window, all in one commit, so a change whose commit fails saves
nothing, and leaves the sign-in time and every other account alone; a
wrong current password or an unchanged new one gets a 400 with a
message of its own and writes nothing, and a wrong current password is
refused as wrong even when the new one is the real password. No
sign-out logs or prints a token, the stored hash, or the user's email
or name, and no password change logs a password, a hash, or a token.
The password-change gate refuses a user with a pending
change with a 403 and a code of its own, and lets every other user
through.

The row locks that keep concurrent requests apart can only be seen from a
second connection, so ``tests/test_auth_concurrency.py`` tests them. The
routes, the cookie, and the response bodies are tested in
``tests/test_auth_api.py``, the token and password functions in
``tests/test_security.py``, and the queries in
``tests/test_auth_repository.py``.
"""

# Log level numbers; the no-alarm checks refuse every record from WARNING up.
import logging

# Random UUIDs: an ID no user has; also the type of the IDs the lookup spy records.
import uuid

# Type of the functions that build an access token case when its test runs.
from collections.abc import Callable

# UTC time zone; every time a test builds is timezone-aware UTC, as the service's are.
from datetime import UTC

# The current time: bounds for a sign-in time or an expiry, and a saved token's own times.
from datetime import datetime

# Moves a time: a lifetime ahead, or an expiry, a revocation, or a sign-in in the past.
from datetime import timedelta

# Test framework: fixtures, marks, raises, and the monkeypatch and caplog types.
import pytest

# Builds an unsaved refresh token for a saved user; the helpers give it a real token's hash.
from factories import make_refresh_token

# Builds an unsaved User: the user fixture's account, and the other accounts some tests save.
from factories import make_user

# Builds the queries that read token rows back after a use case.
from sqlalchemy import select

# What a commit that breaks a unique constraint raises; the failed password change expects it.
from sqlalchemy.exc import IntegrityError

# Type of the db_session fixture, the session every use case here runs in.
from sqlalchemy.orm import Session

# Cached settings; three_day_refresh_tokens copies them with a refresh lifetime of its own.
from app.core.config import get_settings

# What a failed sign-in or a rejected token raises, which the API answers with 401.
from app.core.errors import AuthenticationError

# What a refused password change raises, which the API answers with 400.
from app.core.errors import BadRequestError

# Machine-readable error codes; sign-in, token, password change, and gate errors are checked.
from app.core.errors import ErrorCode

# What the password-change gate raises, which the API answers with 403.
from app.core.errors import PermissionDeniedError

# Signs an access token for a user ID, for the tests that start from one.
from app.core.security import create_access_token

# Verifies an access token and returns the user ID it names; checks what a use case returns.
from app.core.security import decode_access_token

# Makes a random refresh token: the raw value a saved hash comes from, or one never saved.
from app.core.security import generate_refresh_token

# Hashes a password with Argon2id, so the user fixture's account can sign in.
from app.core.security import hash_password

# Hashes a refresh token as the service stores it; saves a token and finds its row.
from app.core.security import hash_refresh_token

# Checks a password against a stored hash; tells which password a changed hash belongs to.
from app.core.security import verify_password

# The auth service, under test, as a module, so monkeypatch can replace names it looks up.
from app.modules.auth import service

# The refresh_tokens table's ORM model; the read-back queries load its rows.
from app.modules.auth.models import RefreshToken

# Validated password change input; _password_change builds one, as the route receives it.
from app.modules.auth.schemas import PasswordChange

# The users table's ORM model; the type of the user fixture and of what a lookup returns.
from app.modules.users.models import User

# The user fixture's password, and a valid new one that differs from it.
PASSWORD = "Correct-Password-1"
NEW_PASSWORD = "New-Password-123"

# The messages a user sees, written out rather than imported from the service, so a
# changed text fails here. INVALID_TOKEN is decode_access_token's message too.
INVALID_CREDENTIALS = "Incorrect email or password."
INVALID_TOKEN = "Invalid or expired token."
PASSWORD_CHANGE_REQUIRED = "You must change your password before continuing."

# The ways a sign-in can fail while no other request changes the account, as
# the email and password typed and whether the saved account is active. The
# only saved user is test@example.com with PASSWORD, so ghost@example.com is
# truly unknown, and the inactive-user case passes the password check and
# reaches the is_active check. The last case shows that a wrong password on a
# deactivated account gets the very same error. An account that changes
# during the check is tested in tests/test_auth_concurrency.py.
FAILED_LOGINS = [
    pytest.param("test@example.com", "Wrong-Password-1", True, id="wrong-password"),
    pytest.param("ghost@example.com", PASSWORD, True, id="unknown-email"),
    pytest.param("test@example.com", PASSWORD, False, id="inactive-user"),
    pytest.param("test@example.com", "Wrong-Password-1", False, id="inactive-wrong-password"),
]

# Each way a refresh can fail without a revoked token, by name; _present_token
# turns a name into the value to present, because some cases need a saved
# token, which a plain list of values can't build. Revoked tokens have tests
# of their own: a rotated one presented again is reuse, the one failure that
# writes, and one revoked without rotation must raise no alarm. An owner
# deleted while refresh waits is tested in tests/test_auth_concurrency.py.
UNUSABLE_REFRESH_TOKENS = [
    pytest.param("missing", id="missing"),
    pytest.param("empty", id="empty"),
    pytest.param("unknown", id="unknown"),
    pytest.param("expired", id="expired"),
    pytest.param("inactive-user", id="inactive-user"),
]

# Both ways the service refuses a password change with a 400, each as the
# fields it replaces in the otherwise valid input and the message the user
# sees. The wrong current password passes the schema, which limits only its
# length, so the refusal comes from the service's check against the stored
# hash. The last case fails both checks, a wrong current password with the
# real one as the new password, and must get the first check's message: if
# the new password were compared first, a caller holding only an access
# token could send guesses of the password as the new one and learn from
# the second message which guess is right. An account deactivated or
# deleted since the request's authentication gets a 401 instead, tested in
# tests/test_auth_concurrency.py.
REJECTED_PASSWORD_CHANGES = [
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


@pytest.fixture
def user(db_session: Session) -> User:
    """Save an active user, test@example.com, whose password is ``PASSWORD``.

    The hash is real, unlike ``make_user``'s default, which can never sign
    in. The database supplies both flags, as for any new account: the user
    is active and must still change their password. Flushing sends the
    ``INSERT`` and gives the user its ID, which the tokens and access
    tokens name. A use case's commit only releases a savepoint of the
    test's transaction, so the rollback at the end of the test removes the
    user with everything else.

    Args:
        db_session: The test's session.

    Returns:
        The saved user.
    """
    user = make_user(password_hash=hash_password(PASSWORD))
    db_session.add(user)
    db_session.flush()

    return user


@pytest.fixture
def lookup_calls(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Spy on the auth service's user lookup and return the IDs it receives.

    The auth service imported ``get_user_by_id`` by name, which gave it a
    name of its own for the users service's function, and it calls the
    function through that name. So the spy replaces it there: patching the
    users service instead would rebind only the users service's name, the
    auth service would still call the real function, and the list would
    stay empty whatever happened. The spy records each ID, then runs the
    real lookup and returns its result, so the code under test behaves
    exactly as usual. ``monkeypatch`` puts the real function back after the
    test.

    The list is returned before any lookup happens and filled in as the
    test runs, so the test reads it after acting: ``[]`` means no lookup,
    ``[user.id]`` means exactly one, for that ID.

    Args:
        monkeypatch: pytest's patching fixture; undoes the patch afterwards.

    Returns:
        The list the spy appends each looked-up ID to, in call order.
    """
    calls: list[uuid.UUID] = []
    real_get_user_by_id = service.get_user_by_id

    def spy(session: Session, user_id: uuid.UUID) -> User | None:
        """Record the ID being looked up, then run the real lookup.

        Args:
            session: The session the auth service passes, handed on unchanged.
            user_id: The ID the auth service looks up.

        Returns:
            The real ``get_user_by_id``'s answer: the user, or None.
        """
        calls.append(user_id)
        return real_get_user_by_id(session, user_id)

    monkeypatch.setattr(service, "get_user_by_id", spy)
    return calls


@pytest.fixture
def password_check_calls(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """Spy on the auth service's password check and return the hashes it receives.

    ``verify_login_password`` is replaced where the auth service looks it
    up, for the reason ``lookup_calls`` gives. The spy records the stored
    hash each check is given, or None when no account has the email, then
    runs the real check and returns its answer, so a sign-in behaves
    exactly as usual. A sign-in that skips the check, or runs it twice,
    shows in the list. ``monkeypatch`` puts the real check back after the
    test.

    Args:
        monkeypatch: pytest's patching fixture; undoes the patch afterwards.

    Returns:
        The list the spy appends each checked hash to, in call order:
        ``[None]`` means one check against the dummy hash, and
        ``[user.password_hash]`` one check against that account's hash.
    """
    calls: list[str | None] = []
    real_verify_login_password = service.verify_login_password

    def spy(password: str, password_hash: str | None) -> bool:
        """Record the hash being checked, then run the real check.

        Args:
            password: The typed password, handed on unchanged.
            password_hash: The stored hash the service passes, or None
                when no account has the email.

        Returns:
            The real ``verify_login_password``'s answer.
        """
        calls.append(password_hash)
        return real_verify_login_password(password, password_hash)

    monkeypatch.setattr(service, "verify_login_password", spy)
    return calls


@pytest.fixture
def three_day_refresh_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the auth service give each new session's refresh token three days to live.

    ``get_settings`` is replaced where the auth service looks it up, with a
    copy of the settings whose ``REFRESH_TOKEN_EXPIRE_DAYS`` is 3, a value
    no setting has by default. A test that expects three days then fails if
    the service writes a lifetime into the code or reads another setting,
    whatever the environment configures. Sign-in and a password change read
    the lifetime, while refresh keeps the old token's expiry. The access
    token is untouched, because ``create_access_token`` reads the settings
    in ``app.core.security``.

    Args:
        monkeypatch: pytest's patching fixture; undoes the patch afterwards.
    """
    three_day_settings = get_settings().model_copy(update={"refresh_token_expire_days": 3})
    monkeypatch.setattr(service, "get_settings", lambda: three_day_settings)


def _save_refresh_token(db_session: Session, user: User, **overrides: object) -> str:
    """Save a refresh token for a user and return its raw value.

    The row stores only the hash, as the service does, and the raw value
    is returned because that is what a client presents from its cookie.
    Without overrides the token is as the factory builds it: unrevoked,
    never rotated, and expiring seven days from now. Overrides let a test
    save a token that is already expired, revoked, or rotated.

    Args:
        db_session: The test's session; the row is flushed, not committed.
        user: The saved user who owns the token.
        **overrides: Columns to set, such as ``expires_at``, ``revoked_at``,
            or ``replaced_by_id``.

    Returns:
        The raw refresh token whose hash was saved.
    """
    raw_refresh_token = generate_refresh_token()
    refresh_token_row = make_refresh_token(
        user.id,
        token_hash=hash_refresh_token(raw_refresh_token),
        **overrides,
    )

    db_session.add(refresh_token_row)
    db_session.flush()

    return raw_refresh_token


def _save_rotated_token(db_session: Session, user: User) -> str:
    """Save a refresh token that was already rotated and return its raw value.

    Rotation revokes a token and links it to the token that replaced it, so
    this saves the replacement first, unrevoked, then the old token with
    both ``revoked_at`` and ``replaced_by_id`` set; both expire seven days
    from now. Presenting the old token again is reuse: only a rotated token
    coming back proves a copy exists. A token revoked any other way, by
    sign-out or a password change, has no replacement, so it can't stand in
    for reuse.

    Args:
        db_session: The test's session; the rows are flushed, not committed.
        user: The saved user who owns both tokens.

    Returns:
        The raw value of the old, rotated token.
    """
    replacement_row = _token_row(db_session, _save_refresh_token(db_session, user))

    return _save_refresh_token(
        db_session,
        user,
        revoked_at=datetime.now(UTC),
        replaced_by_id=replacement_row.id,
    )


def _present_token(db_session: Session, user: User, case: str) -> str | None:
    """Build the refresh token value a test presents for one failure case.

    ``missing`` and ``empty`` are what arrives without a usable cookie: no
    cookie at all, or one with an empty value. ``unknown`` is a well-formed
    token that was never saved. ``expired`` saves a token that ran out a
    second ago, and ``inactive-user`` saves a valid token, then deactivates
    its owner, so the failure comes from the expiry or the account and not
    from the lookup. An unrecognized name raises instead of returning None,
    so a typo can't quietly turn a case into ``missing``.

    Args:
        db_session: The test's session.
        user: The saved user who owns any token created here.
        case: One of the IDs in ``UNUSABLE_REFRESH_TOKENS``.

    Returns:
        The raw token to pass to ``refresh``, or None for a missing cookie.

    Raises:
        ValueError: If ``case`` isn't a known case name.
    """
    if case == "missing":
        return None
    if case == "empty":
        return ""
    if case == "unknown":
        return generate_refresh_token()  # never saved, so no row has its hash
    if case == "expired":
        expires_at = datetime.now(UTC) - timedelta(seconds=1)
        return _save_refresh_token(db_session, user, expires_at=expires_at)
    if case == "inactive-user":
        raw_refresh_token = _save_refresh_token(db_session, user)
        user.is_active = False
        db_session.flush()
        return raw_refresh_token
    raise ValueError(f"Unknown case: {case}")


def _token_row(db_session: Session, raw_token: str) -> RefreshToken:
    """Load the refresh token row for a raw token, as the database holds it now.

    Tests hold raw tokens, the values a browser would send, but the table
    stores only their hashes. This hashes the token the same way the service
    does and reads the row back, so callers only ever pass raw tokens and
    can't mix up a raw token with a hash.

    ``populate_existing`` makes the query overwrite whatever the session
    already holds for the row, so the test reads the stored values even
    where the session's copy is out of date. In these tests every change
    goes through the session, which keeps its copies up to date: the bulk
    ``UPDATE`` of ``revoke_all_refresh_tokens_for_user`` updates the values
    the session has loaded, and a query fills in those it hasn't. Only a
    row changed behind the session's back, such as by raw SQL, would leave
    a plain query showing old values.

    Args:
        db_session: The test's database session.
        raw_token: The raw refresh token, as ``_save_refresh_token`` or a
            use case such as ``service.refresh`` returns it.

    Returns:
        The token's row.

    Raises:
        NoResultFound: If no row has this token's hash, which means the test
            set up the wrong token.
    """
    return db_session.execute(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(raw_token))
        .execution_options(populate_existing=True)
    ).scalar_one()


def _password_change(
    current_password: str = PASSWORD,
    new_password: str = NEW_PASSWORD,
) -> PasswordChange:
    """Build a validated password change for the ``user`` fixture.

    By default it holds the fixture's real password and a different, valid
    new one, so ``change_password`` succeeds. A test that checks a rejection
    replaces only the value it is about, so a failure points at that value.
    ``PasswordChange`` validates both, as it does the route's input, so a
    new password must follow the password rule.

    Args:
        current_password: The password the user claims to sign in with now.
            Defaults to ``PASSWORD``, the fixture's real password.
        new_password: The password to replace it. Defaults to
            ``NEW_PASSWORD``, which differs from ``PASSWORD``.

    Returns:
        The validated input to pass to ``service.change_password``.
    """
    return PasswordChange(current_password=current_password, new_password=new_password)


def _assert_generic_token_error(error: AuthenticationError) -> None:
    """Check that an error is the very one every rejected token gets.

    ``get_authenticated_user`` and ``refresh`` refuse every unusable token
    the same way, so its holder can't tell an expired, unknown, or revoked
    token from a deactivated or missing account. The API sends the error's
    status, code, message, and details in the response, so all four are
    compared: an error that gave one case a status, a code, or details of
    its own would tell that case apart, even with the same message. The
    message is compared with ``INVALID_TOKEN``, written out, so the
    decoder's text and the service's copy of it can't drift apart.

    Args:
        error: The error the use case raised.

    Raises:
        AssertionError: If any of the four differs from the generic error's.
    """
    assert error.status_code == 401
    assert error.code == ErrorCode.AUTHENTICATION_FAILED
    assert error.message == INVALID_TOKEN
    assert error.details == []


def test_login_returns_an_access_token_for_the_user(db_session: Session, user: User) -> None:
    """A successful sign-in returns a valid access token that names the user.

    Decoding proves the token is signed with the right key, hasn't expired,
    and carries the user's ID as a UUID.
    """
    issued_tokens = service.login(db_session, user.email, PASSWORD)

    assert decode_access_token(issued_tokens.access_token) == user.id


def test_login_stores_only_the_hash_of_the_refresh_token(db_session: Session, user: User) -> None:
    """Sign-in saves exactly one token row, holding the token's hash, not the token.

    The stored hash must equal the hash of the token the client receives,
    because refreshing looks the row up that way, and the stored value must
    not be the raw token. The table is read without a filter and the row's
    owner is checked, so a token saved for the wrong user fails the test.
    """
    issued_tokens = service.login(db_session, user.email, PASSWORD)

    token_rows = db_session.scalars(select(RefreshToken)).all()

    assert len(token_rows) == 1
    token_row = token_rows[0]

    assert token_row.token_hash == hash_refresh_token(issued_tokens.refresh_token)
    assert token_row.token_hash != issued_tokens.refresh_token
    assert token_row.user_id == user.id


def test_the_repr_of_issued_tokens_shows_neither_token() -> None:
    """The ``repr`` of the tokens a use case returns shows neither of them.

    ``IssuedTokens`` is what sign-in, refresh, and a password change return.
    It defines no ``__str__``, so ``str()``, f-strings, and a log call's
    ``%s`` all fall back to this ``repr``, and a stray print or log line
    would otherwise write both credentials out in full; a refresh token
    works for days. The instance holds a real access token and a real
    refresh token, long random strings, so finding either in the text can
    only mean it leaked.
    """
    issued_tokens = service.IssuedTokens(
        access_token=create_access_token(uuid.uuid4()),
        refresh_token=generate_refresh_token(),
    )

    shown = repr(issued_tokens)

    assert issued_tokens.access_token not in shown
    assert issued_tokens.refresh_token not in shown


@pytest.mark.usefixtures("three_day_refresh_tokens")
def test_login_sets_the_refresh_token_to_expire_after_the_configured_days(
    db_session: Session,
    user: User,
) -> None:
    """The refresh token expires the configured number of days after sign-in.

    The service's settings say three days here, so a lifetime written into
    the code, or read from another setting, fails, whatever the environment
    configures. The expiry must fall between three days after the moments
    just before and just after the sign-in, so a longer or a shorter
    lifetime fails too.
    """
    before = datetime.now(UTC) + timedelta(days=3)
    service.login(db_session, user.email, PASSWORD)
    after = datetime.now(UTC) + timedelta(days=3)

    token_row = db_session.scalar(select(RefreshToken).where(RefreshToken.user_id == user.id))

    assert before <= token_row.expires_at <= after


def test_login_records_the_sign_in_time(db_session: Session, user: User) -> None:
    """A successful sign-in sets ``last_login_at`` to the current time.

    The time must fall between the moments just before and just after the
    sign-in. The user is read back from the database first, so the time
    checked is the one saved, not only the one set on the object.
    """
    before = datetime.now(UTC)
    service.login(db_session, user.email, PASSWORD)
    db_session.refresh(user)
    after = datetime.now(UTC)

    assert user.last_login_at is not None
    assert before <= user.last_login_at <= after


def test_login_ignores_email_case_and_surrounding_spaces(db_session: Session, user: User) -> None:
    """An email typed in mixed case with spaces around it still signs the user in.

    The account was saved as ``test@example.com``. Sign-in looks the typed
    text up in the form account creation stores, so the access token names
    that account.
    """
    issued_tokens = service.login(db_session, "   Test@Example.COM   ", PASSWORD)

    assert decode_access_token(issued_tokens.access_token) == user.id


def test_login_succeeds_while_a_password_change_is_pending(db_session: Session) -> None:
    """A user who must still change their password can sign in.

    They need a session to choose a new password; the API, not sign-in,
    blocks their other requests until they do. The flag is set explicitly,
    so the test doesn't depend on the database default that the ``user``
    fixture's account gets.
    """
    user = make_user(password_hash=hash_password(PASSWORD), must_change_password=True)
    db_session.add(user)
    db_session.flush()

    issued_tokens = service.login(db_session, user.email, PASSWORD)

    assert decode_access_token(issued_tokens.access_token) == user.id


def test_each_login_issues_a_new_refresh_token_and_keeps_the_earlier_ones(
    db_session: Session,
    user: User,
) -> None:
    """Two sign-ins save two rows, return two different tokens, and revoke neither.

    A new sign-in never reuses, overwrites, or ends an earlier session, so
    each device a user signs in on keeps a session of its own. Both rows
    are read back after the second sign-in and must still be unrevoked, so
    a sign-in that ended the user's other sessions fails. The revocation
    times are compared as a list, so a failure shows which row was revoked.
    """
    first_login = service.login(db_session, user.email, PASSWORD)
    second_login = service.login(db_session, user.email, PASSWORD)
    token_rows = db_session.scalars(select(RefreshToken)).all()

    assert len(token_rows) == 2
    assert first_login.refresh_token != second_login.refresh_token
    assert [token_row.revoked_at for token_row in token_rows] == [None, None]


@pytest.mark.parametrize(("email", "password", "is_active"), FAILED_LOGINS)
def test_a_failed_login_raises_the_generic_error(
    db_session: Session,
    email: str,
    password: str,
    is_active: bool,
) -> None:
    """Every kind of failed sign-in raises the very same error.

    A wrong password, an unknown email, and a deactivated account must look
    the same, so a caller can't discover which emails have accounts or
    which accounts are deactivated. The status, the code, the message, and
    the details are all compared, because the API sends each of them in
    the 401, so an error that carried a code or details of its own for one
    kind fails.
    """
    user = make_user(password_hash=hash_password(PASSWORD), is_active=is_active)
    db_session.add(user)
    db_session.flush()

    with pytest.raises(AuthenticationError) as exc_info:
        service.login(db_session, email, password)

    error = exc_info.value

    assert error.status_code == 401
    assert error.code == ErrorCode.AUTHENTICATION_FAILED
    assert error.message == INVALID_CREDENTIALS
    assert error.details == []


@pytest.mark.parametrize(("email", "password", "is_active"), FAILED_LOGINS)
def test_a_failed_login_writes_nothing(
    db_session: Session,
    email: str,
    password: str,
    is_active: bool,
) -> None:
    """A failed sign-in saves no refresh token and leaves ``last_login_at`` unset.

    Each case is set up as in the generic-error test. Afterwards the user is
    read back from the database and the tokens are counted in the same
    session, so a sign-in time the service saved before it failed would
    show, and so would a token it only added to the session.
    """
    user = make_user(password_hash=hash_password(PASSWORD), is_active=is_active)
    db_session.add(user)
    db_session.flush()

    with pytest.raises(AuthenticationError):
        service.login(db_session, email, password)

    db_session.refresh(user)
    token_rows = db_session.scalars(select(RefreshToken)).all()

    assert len(token_rows) == 0
    assert user.last_login_at is None


def test_an_unknown_email_still_runs_the_password_check(
    db_session: Session,
    password_check_calls: list[str | None],
) -> None:
    """An unknown email still goes through the password check, with no hash.

    The ``password_check_calls`` spy records exactly one check, with None:
    the path that checks the password against the dummy hash, so an unknown
    email takes as long as a wrong password. The cost of that path is
    tested in ``tests/test_security.py``.
    """
    with pytest.raises(AuthenticationError) as exc_info:
        service.login(db_session, "ghost@example.com", PASSWORD)

    assert password_check_calls == [None]
    assert exc_info.value.message == INVALID_CREDENTIALS


@pytest.mark.parametrize(
    "password",
    [
        pytest.param(PASSWORD, id="right-password"),
        pytest.param("Wrong-Password-1", id="wrong-password"),
    ],
)
def test_a_deactivated_account_still_runs_the_password_check(
    db_session: Session,
    password_check_calls: list[str | None],
    password: str,
) -> None:
    """A deactivated account's password is checked once, against its own hash.

    The password is checked before the account's ``is_active`` flag, so a
    deactivated account takes as long to refuse as a wrong password on an
    active one, and the response time can't reveal which emails belong to
    deactivated accounts. A sign-in that refused the account before the
    check would answer without that cost, and the spy would record nothing.
    The right password is tried as well as a wrong one, because only the
    right one passes the check and reaches the ``is_active`` check.
    """
    user = make_user(password_hash=hash_password(PASSWORD), is_active=False)
    db_session.add(user)
    db_session.flush()

    with pytest.raises(AuthenticationError) as exc_info:
        service.login(db_session, user.email, password)

    assert password_check_calls == [user.password_hash]
    assert exc_info.value.message == INVALID_CREDENTIALS


def test_login_logs_and_prints_neither_the_secrets_nor_the_emails(
    db_session: Session,
    user: User,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No sign-in, successful or failed, logs or prints a password, hash, token, or email.

    Plan §12 says passwords are never logged and keeps personal data out
    of logs, and ``CLAUDE.md`` says passwords, password hashes, and tokens
    are never logged. A successful sign-in, one with a wrong password, and
    one for an unknown email run while every record down to DEBUG is
    captured, and so is everything printed to stdout and stderr, where the
    application's log records go too, so a stray log line at any level or
    a stray ``print`` shows. Neither password typed, the account's stored
    hash, either token the successful sign-in issued, nor either email,
    the account's or the unknown one, may appear in the records or in
    either stream; a failure names each value found and where, never the
    value itself. The test of the same name in ``tests/test_auth_api.py``
    checks the route too.
    """
    unknown_email = "ghost@example.com"

    with caplog.at_level("DEBUG"):
        issued_tokens = service.login(db_session, user.email, PASSWORD)

        with pytest.raises(AuthenticationError):
            service.login(db_session, user.email, "Wrong-Password-1")

        with pytest.raises(AuthenticationError):
            service.login(db_session, unknown_email, PASSWORD)

    printed = capsys.readouterr()
    sensitive_values = {
        "password": PASSWORD,
        "wrong password": "Wrong-Password-1",
        "stored hash": user.password_hash,
        "access token": issued_tokens.access_token,
        "refresh token": issued_tokens.refresh_token,
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


def test_a_valid_token_returns_its_user(db_session: Session, user: User) -> None:
    """A freshly signed access token for an active user returns that user.

    The token is signed directly, as a sign-in signs it, so the test needs
    nothing but the ``user`` fixture's account. The user returned must
    have the ID the token names.
    """
    access_token = create_access_token(user.id)
    authenticated_user = service.get_authenticated_user(db_session, access_token)

    assert authenticated_user.id == user.id


@pytest.mark.parametrize(
    "make_access_token",
    (
        pytest.param(lambda: "not-a-token", id="garbage"),
        pytest.param(lambda: "", id="empty"),
        pytest.param(lambda: create_access_token(uuid.uuid4()), id="unknown-user"),
    ),
)
def test_an_unusable_token_raises_the_generic_error(
    db_session: Session,
    user: User,
    make_access_token: Callable[[], str],
) -> None:
    """A token that doesn't decode, or that names no account, gets the generic error.

    A garbage string fails to decode, and so does an empty one, which is
    what a bare ``Bearer`` header produces. The unknown-user token is
    correctly signed but names an ID no account has. The ``user`` fixture
    is a decoy: with an active account in the table, a lookup that ignored
    the ID would find it, and the test would fail. The first two errors
    come from ``decode_access_token`` and the third from the service, and
    each is compared whole, because the API sends every part of it in the
    401: an error with a code or details of its own would tell a holder
    which check failed.

    Each case is a function the test calls, so the unknown-user token is
    signed when the test runs. A token signed when the module is imported
    would have expired by the time a slow run reached the test, more than
    the access token's lifetime later, and would then fail to decode like
    the other two without ever reaching the lookup. Expired, tampered, and
    wrong-key tokens are tested in ``tests/test_security.py``.
    """
    with pytest.raises(AuthenticationError) as exc_info:
        service.get_authenticated_user(db_session, make_access_token())

    _assert_generic_token_error(exc_info.value)


def test_a_token_stops_working_once_its_user_is_deactivated(
    db_session: Session,
    user: User,
) -> None:
    """A token signed before deactivation is refused once the account is inactive.

    The token is still correctly signed and unexpired, so only the check of
    the account can turn it away: deactivation applies to the next request,
    not when the token runs out. The error is the generic one, compared
    whole, so the holder can't tell the account was deactivated.

    The flag is set on the session's copy of the account and flushed, and
    ``get_user_by_id`` finds that copy without a query, so the test sees
    the check but not a read from the database.
    ``test_me_rejects_a_deactivated_user`` in ``tests/test_auth_api.py``
    goes through a request, whose session reads the account from the
    database.
    """
    access_token = create_access_token(user.id)
    user.is_active = False

    db_session.flush()

    with pytest.raises(AuthenticationError) as exc_info:
        service.get_authenticated_user(db_session, access_token)

    _assert_generic_token_error(exc_info.value)


def test_a_user_who_must_change_their_password_is_still_authenticated(
    db_session: Session,
    user: User,
) -> None:
    """A pending password change doesn't stop the token identifying the user.

    ``GET /auth/me`` must keep working in this state, so the web app can
    read the flag and show the change-password screen. The password-change
    gate belongs to the routes it covers, not to this function, and this
    test fails if it is moved here. The flag is set explicitly, so the test
    doesn't depend on the database default that the ``user`` fixture's
    account gets.
    """
    access_token = create_access_token(user.id)
    user.must_change_password = True
    db_session.flush()

    authenticated_user = service.get_authenticated_user(db_session, access_token)
    assert authenticated_user.id == user.id


def test_a_bad_token_never_reaches_the_database(
    db_session: Session,
    lookup_calls: list[uuid.UUID],
) -> None:
    """A token that fails to decode is refused before any user lookup.

    Decoding needs no database, so it runs first, and a junk token never
    costs the user lookup, the only query this function makes. The error
    alone can't show this: code that swallowed the decode error and then
    looked up a made-up ID would end in the same generic error, so the
    unusable-token test would still pass. Only the ``lookup_calls`` spy
    sees the difference, and it must record nothing here. The next test is
    its positive control.
    """
    with pytest.raises(AuthenticationError) as exc_info:
        service.get_authenticated_user(db_session, "not-a-token")

    assert lookup_calls == []
    _assert_generic_token_error(exc_info.value)


def test_a_valid_token_looks_up_the_user_it_names(
    db_session: Session,
    user: User,
    lookup_calls: list[uuid.UUID],
) -> None:
    """A valid token leads to exactly one lookup, by the ID inside it.

    This is the positive control for the test above. An empty call list
    there would also appear if the spy were patched in the wrong place and
    never called, so this test shows that the same spy records a lookup
    when one happens. It also shows that the account is looked up by the
    ID the token carries, and only once.
    """
    authenticated_user = service.get_authenticated_user(db_session, create_access_token(user.id))

    assert lookup_calls == [user.id]
    assert authenticated_user.id == user.id


def test_refresh_returns_an_access_token_for_the_user(db_session: Session, user: User) -> None:
    """A valid refresh token gets a new access token that names its owner.

    Decoding proves the token is signed with the right key, hasn't expired,
    and carries the owner's ID as a UUID, as the first sign-in test checks
    for sign-in.
    """
    raw_refresh_token = _save_refresh_token(db_session, user)
    issued_tokens = service.refresh(db_session, raw_refresh_token)

    assert decode_access_token(issued_tokens.access_token) == user.id


def test_refresh_issues_a_new_refresh_token(db_session: Session, user: User) -> None:
    """Refresh returns a different refresh token, whose row is saved and unrevoked.

    Finding the row matters more than the inequality: a refresh that
    returned a random string without storing it would hand the client a
    token its next refresh could never use. ``_token_row`` finds the row by
    the new token's hash and fails if there is none. The row's expiry is
    checked by ``test_refresh_keeps_the_old_expiry``.
    """
    raw_refresh_token = _save_refresh_token(db_session, user)
    issued_tokens = service.refresh(db_session, raw_refresh_token)
    new_token_row = _token_row(db_session, issued_tokens.refresh_token)

    assert issued_tokens.refresh_token != raw_refresh_token
    assert new_token_row.revoked_at is None


def test_refresh_revokes_the_old_token_and_links_it_to_the_new_one(
    db_session: Session,
    user: User,
) -> None:
    """The presented token is revoked and points to the token that replaced it.

    Each row is found by the hash of its own raw value: the presented token
    for the old row, the returned token for the new one. The link is what
    marks the old token as rotated, so presenting it again raises the reuse
    alarm rather than a quiet refusal, and it lets an investigation follow
    a chain of rotations. The next test checks that the user's other
    tokens are left alone.
    """
    raw_refresh_token = _save_refresh_token(db_session, user)
    issued_tokens = service.refresh(db_session, raw_refresh_token)
    old_token_row = _token_row(db_session, raw_refresh_token)
    new_token_row = _token_row(db_session, issued_tokens.refresh_token)

    assert old_token_row.revoked_at is not None
    assert old_token_row.replaced_by_id == new_token_row.id


def test_refresh_leaves_the_users_other_sessions_alone(db_session: Session, user: User) -> None:
    """Refreshing on one device keeps the user signed in on the others.

    The user holds two tokens, as on a laptop and a phone, and the laptop
    refreshes. Only the presented token may be revoked: each device
    refreshes whenever its access token expires, so a refresh that revoked
    every token of the user, as reuse does, would sign the user out on
    every other device again and again. The phone's row is read back after
    the refresh and must still be unrevoked.
    """
    raw_refresh_token = _save_refresh_token(db_session, user)
    raw_other_device_token = _save_refresh_token(db_session, user)

    service.refresh(db_session, raw_refresh_token)

    other_device_row = _token_row(db_session, raw_other_device_token)

    assert other_device_row.revoked_at is None


def test_refresh_leaves_the_sign_in_time_alone(db_session: Session, user: User) -> None:
    """A refresh keeps ``last_login_at`` at the time of the last sign-in.

    The user signed in a day ago. A refresh is not a sign-in, and the web
    app makes one whenever an access token expires, so a refresh that set
    the column would leave it showing the latest refresh instead of the
    latest sign-in. The user is read back from the database after the
    refresh, so the time checked is the one saved.
    """
    signed_in_at = datetime.now(UTC) - timedelta(days=1)
    user.last_login_at = signed_in_at
    db_session.flush()
    raw_refresh_token = _save_refresh_token(db_session, user)

    service.refresh(db_session, raw_refresh_token)
    db_session.refresh(user)

    assert user.last_login_at == signed_in_at


def test_refresh_keeps_the_old_expiry(db_session: Session, user: User) -> None:
    """The replacement token expires exactly when the presented one did.

    The presented token expires in three days, not the default seven, and
    the two expiries are compared exactly, so a refresh that started a
    fresh window of any length fails. Keeping the expiry ends a session a
    fixed time after it started, however often it is refreshed, so everyone
    signs in again at least once a window.
    """
    original_expires_at = datetime.now(UTC) + timedelta(days=3)
    raw_refresh_token = _save_refresh_token(db_session, user, expires_at=original_expires_at)
    issued_tokens = service.refresh(db_session, raw_refresh_token)
    new_token_row = _token_row(db_session, issued_tokens.refresh_token)

    assert new_token_row.expires_at == original_expires_at


def test_refresh_works_while_a_password_change_is_pending(db_session: Session, user: User) -> None:
    """A user who must change their password can still refresh.

    The web app refreshes after a reload and then shows the change-password
    screen, so refresh must stay open in this state (plan §8.1). The flag
    is set explicitly, so the test doesn't depend on the database default,
    and the new access token must name the user.
    """
    raw_refresh_token = _save_refresh_token(db_session, user)
    user.must_change_password = True

    db_session.flush()

    issued_tokens = service.refresh(db_session, raw_refresh_token)

    assert decode_access_token(issued_tokens.access_token) == user.id


def test_a_refresh_token_works_only_once(db_session: Session, user: User) -> None:
    """Presenting the same refresh token a second time gets the generic error.

    This is rotation seen from the client: the first refresh replaces the
    token, so the second use is reuse. The test sees only the refusal;
    what reuse does besides, revoking the user's tokens and logging a
    warning, is checked by the reuse tests below.
    """
    raw_refresh_token = _save_refresh_token(db_session, user)
    service.refresh(db_session, raw_refresh_token)

    with pytest.raises(AuthenticationError) as exc_info:
        service.refresh(db_session, raw_refresh_token)

    _assert_generic_token_error(exc_info.value)


@pytest.mark.parametrize("case", UNUSABLE_REFRESH_TOKENS)
def test_an_unusable_refresh_token_raises_the_generic_error(
    db_session: Session,
    user: User,
    case: str,
) -> None:
    """Every unusable refresh token gets the very same error.

    A missing cookie, an empty one, an unknown token, an expired one, and a
    deactivated owner must look the same from outside, so the reply never
    says which check failed. ``_present_token`` builds each case's value.
    The whole error is compared, because the API sends every part of it in
    the 401: an expired token with a code or details of its own, say,
    would tell its holder why it failed.
    """
    raw_refresh_token = _present_token(db_session, user, case)

    with pytest.raises(AuthenticationError) as exc_info:
        service.refresh(db_session, raw_refresh_token)

    _assert_generic_token_error(exc_info.value)


@pytest.mark.parametrize("case", UNUSABLE_REFRESH_TOKENS)
def test_an_unusable_refresh_token_writes_nothing(
    db_session: Session,
    user: User,
    case: str,
) -> None:
    """A failed refresh adds no token and revokes none.

    A valid token is saved first, so there is something a faulty refresh
    could wrongly change, and the rows are counted after each case's own
    setup, which saves a second token for the expired and deactivated-owner
    cases. The rows are read in the test's session, so a token the refresh
    only added would show too. Reuse is the only failure that writes, and
    it has tests of its own.
    """
    _save_refresh_token(db_session, user)
    raw_refresh_token = _present_token(db_session, user, case)
    token_count_before = len(db_session.scalars(select(RefreshToken)).all())

    with pytest.raises(AuthenticationError):
        service.refresh(db_session, raw_refresh_token)

    token_rows = db_session.scalars(select(RefreshToken)).all()

    assert len(token_rows) == token_count_before
    assert all(token_row.revoked_at is None for token_row in token_rows)


def test_reusing_a_rotated_token_revokes_every_token_of_the_user(
    db_session: Session,
    user: User,
) -> None:
    """Presenting a rotated token again ends the user's other sessions too.

    The user also holds an unrevoked token, as on a second device. A token
    that was already replaced coming back means a copy exists, and the
    server can't tell the real user from a thief, so every token of the
    user is revoked, the other device's included, which the test reads
    back. The error is the generic one. The owner is active here;
    ``test_a_rotated_token_of_a_deactivated_user_still_raises_the_alarm``
    presents one whose owner is deactivated.
    """
    raw_rotated_token = _save_rotated_token(db_session, user)
    raw_other_device_token = _save_refresh_token(db_session, user)

    with pytest.raises(AuthenticationError) as exc_info:
        service.refresh(db_session, raw_rotated_token)

    other_device_row = _token_row(db_session, raw_other_device_token)

    _assert_generic_token_error(exc_info.value)
    assert other_device_row.revoked_at is not None


def test_the_reuse_revocation_survives_the_failed_request(
    db_session: Session,
    user: User,
) -> None:
    """The revocation that reuse triggers is committed before the error.

    The session is rolled back after the error, as a failed request's is,
    and the other device's token is still revoked. Without the commit the
    rollback would undo the revocation, and the stolen copy would keep
    working; the previous test can't see that, because the change is still
    in the session there.
    """
    raw_rotated_token = _save_rotated_token(db_session, user)
    raw_other_device_token = _save_refresh_token(db_session, user)

    with pytest.raises(AuthenticationError) as exc_info:
        service.refresh(db_session, raw_rotated_token)

    # A failed request's session is rolled back; only committed work remains.
    db_session.rollback()

    other_device_row = _token_row(db_session, raw_other_device_token)

    _assert_generic_token_error(exc_info.value)
    assert other_device_row.revoked_at is not None


def test_reuse_is_logged_without_the_token(
    db_session: Session,
    user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reuse logs exactly one warning naming the user, and never the token.

    The warning lets someone find the incident later. Records are captured
    from WARNING up and only WARNING records are counted, so a line at
    another level fails. The raw token must not appear anywhere in the
    captured text, because anyone who can read the logs could otherwise
    use it. The service runs outside a request here, so the line's request
    ID is None; ``test_reuse_is_logged_with_the_request_id`` in
    ``tests/test_auth_api.py`` compares the whole line through a request.
    """
    raw_rotated_token = _save_rotated_token(db_session, user)

    with caplog.at_level("WARNING"), pytest.raises(AuthenticationError):
        service.refresh(db_session, raw_rotated_token)

    warnings = [record for record in caplog.records if record.levelname == "WARNING"]

    assert len(warnings) == 1
    assert str(user.id) in warnings[0].getMessage()
    assert raw_rotated_token not in caplog.text


def test_an_expired_token_does_not_revoke_the_others(db_session: Session, user: User) -> None:
    """An expired token is only refused; the user's other session survives.

    The token ran out a second ago and was never revoked or rotated, as a
    session that simply ended leaves it. Tokens expire whenever someone
    stays away for a while, so treating expiry like reuse would sign
    ordinary users out on every device.
    """
    raw_expired_token = _save_refresh_token(
        db_session,
        user,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    raw_other_device_token = _save_refresh_token(db_session, user)

    with pytest.raises(AuthenticationError):
        service.refresh(db_session, raw_expired_token)

    other_device_row = _token_row(db_session, raw_other_device_token)

    assert other_device_row.revoked_at is None


def test_an_expired_rotated_token_still_raises_the_alarm(
    db_session: Session,
    user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A rotated token presented after it expired still ends every session of its user.

    Reuse is checked before expiry, so a stolen copy that comes back after
    its session ran out raises the alarm like any other, as ADR-0004 says:
    a rotated token raises one every time it comes back. The rotated token
    and its replacement share an expiry a day in the past, as a refresh
    copies it, and the other device's token is unexpired. A refresh that
    checked expiry first, or a token lookup that skipped expired tokens,
    would raise the same error with no warning and no revocation.
    """
    expires_at = datetime.now(UTC) - timedelta(days=1)
    replacement_row = _token_row(
        db_session, _save_refresh_token(db_session, user, expires_at=expires_at)
    )
    raw_rotated_token = _save_refresh_token(
        db_session,
        user,
        expires_at=expires_at,
        revoked_at=expires_at - timedelta(days=1),
        replaced_by_id=replacement_row.id,
    )
    raw_other_device_token = _save_refresh_token(db_session, user)

    with caplog.at_level("WARNING"), pytest.raises(AuthenticationError) as exc_info:
        service.refresh(db_session, raw_rotated_token)

    other_device_row = _token_row(db_session, raw_other_device_token)
    warnings = [record for record in caplog.records if record.levelname == "WARNING"]

    _assert_generic_token_error(exc_info.value)
    assert other_device_row.revoked_at is not None
    assert len(warnings) == 1
    assert str(user.id) in warnings[0].getMessage()
    assert raw_rotated_token not in caplog.text


def test_a_rotated_token_of_a_deactivated_user_still_raises_the_alarm(
    db_session: Session,
    user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A rotated token presented again ends every session even when its owner is deactivated.

    Reuse is checked before the account, so a stolen copy that comes back
    after the owner was deactivated raises the alarm like any other, as
    plan §8.1 says of every rotated token presented again. The user also
    holds another device's token, as a thief who refreshed first would
    hold the replacement. A refresh that checked the account first would
    refuse the rotated token quietly, with no warning, and leave that
    token unrevoked, so it would work again once the account was
    reactivated.
    """
    raw_rotated_token = _save_rotated_token(db_session, user)
    raw_other_device_token = _save_refresh_token(db_session, user)
    user.is_active = False
    db_session.flush()

    with caplog.at_level("WARNING"), pytest.raises(AuthenticationError) as exc_info:
        service.refresh(db_session, raw_rotated_token)

    other_device_row = _token_row(db_session, raw_other_device_token)
    warnings = [record for record in caplog.records if record.levelname == "WARNING"]

    _assert_generic_token_error(exc_info.value)
    assert other_device_row.revoked_at is not None
    assert len(warnings) == 1
    assert str(user.id) in warnings[0].getMessage()
    assert raw_rotated_token not in caplog.text


def test_reuse_leaves_other_users_tokens_alone(db_session: Session, user: User) -> None:
    """Reuse ends the sessions of the token's owner and nobody else.

    Another user is saved with an unrevoked token of their own. The
    repository tests prove the revocation query filters by user; this
    proves the service passes the owner of the presented token, so a
    stolen token can never sign out the rest of the hospital.
    """
    other_user = make_user(email="other-user@example.com")

    db_session.add(other_user)
    db_session.flush()

    raw_other_user_token = _save_refresh_token(db_session, other_user)
    raw_rotated_token = _save_rotated_token(db_session, user)

    with pytest.raises(AuthenticationError):
        service.refresh(db_session, raw_rotated_token)

    other_user_row = _token_row(db_session, raw_other_user_token)

    assert other_user_row.revoked_at is None


def test_logout_revokes_the_presented_token(db_session: Session, user: User) -> None:
    """Logout revokes the token from the cookie, without linking a replacement.

    The token's row is read back after the sign-out: it is revoked, and its
    ``replaced_by_id`` is still empty. That link is what marks a token as
    rotated, so a sign-out that set it would make the token's next refresh
    raise the reuse alarm and end every session of the user, where a token
    ended on purpose is refused quietly. The next test checks the commit.
    """
    raw_token = _save_refresh_token(db_session, user)

    service.logout(db_session, user, raw_token)

    refresh_token_row = _token_row(db_session, raw_token)

    assert refresh_token_row.revoked_at is not None
    assert refresh_token_row.replaced_by_id is None


def test_the_logout_revocation_is_committed(db_session: Session, user: User) -> None:
    """The revocation is committed, so it survives a rollback.

    The session is rolled back after logout, as a request's session is when
    it closes, and the token's row, read back from the database, is still
    revoked and still unlinked. Without the commit, the rollback would undo
    the revocation; ``test_logout_revokes_the_presented_token`` can't see
    that, because the change is still in the session there.
    """
    raw_token = _save_refresh_token(db_session, user)

    service.logout(db_session, user, raw_token)
    db_session.rollback()

    refresh_token_row = _token_row(db_session, raw_token)

    assert refresh_token_row.revoked_at is not None
    assert refresh_token_row.replaced_by_id is None


def test_logout_leaves_the_users_other_sessions_alone(db_session: Session, user: User) -> None:
    """Signing out on one device leaves the user's other sessions alone.

    The user holds two tokens, as on a laptop and a phone, and the laptop
    signs out. Its token is revoked without a link, and the phone's row,
    read back after the sign-out, must still be unrevoked: logout must
    never revoke every token the way reuse detection does.
    """
    raw_refresh_token = _save_refresh_token(db_session, user)
    raw_other_device_token = _save_refresh_token(db_session, user)

    service.logout(db_session, user, raw_refresh_token)

    refresh_token_row = _token_row(db_session, raw_refresh_token)
    other_device_row = _token_row(db_session, raw_other_device_token)

    assert refresh_token_row.revoked_at is not None
    assert refresh_token_row.replaced_by_id is None
    assert other_device_row.revoked_at is None


@pytest.mark.parametrize(
    "unusable_token",
    [
        pytest.param(None, id="None"),
        pytest.param("", id="empty"),
        pytest.param("unknown-token", id="unknown"),
    ],
)
def test_logout_with_an_unusable_token_does_nothing(
    db_session: Session,
    user: User,
    unusable_token: str | None,
) -> None:
    """A missing, empty, or unknown cookie changes nothing and raises nothing.

    A real token is saved first, so there is something a faulty logout
    could wrongly revoke, and it must still be unrevoked afterwards. Its
    row is the copy loaded before the sign-out, which the session keeps in
    step with every change made through it, the bulk revocation included.
    Logout never fails, so signing out without a usable cookie is not an
    error.
    """
    raw_token = _save_refresh_token(db_session, user)
    refresh_token_row = _token_row(db_session, raw_token)

    assert refresh_token_row.revoked_at is None

    service.logout(db_session, user, unusable_token)

    assert refresh_token_row.revoked_at is None


def test_logout_with_a_revoked_token_raises_no_alarm(
    db_session: Session,
    user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An already revoked token is ignored: no alarm, and no mass revocation.

    The token was revoked five minutes ago, without a replacement, as a
    sign-out leaves it. In refresh, a rotated token presented again means a
    copy exists and ends every session. At logout a revoked token usually
    means a double click or a second tab signing out too, so the user's
    other device must keep its token, and nothing may be logged as a
    security warning. Every record from WARNING up counts, so an alarm
    logged at ERROR fails as well as one logged at WARNING.
    """
    five_minutes_ago = datetime.now(UTC) - timedelta(minutes=5)
    raw_other_device_token = _save_refresh_token(db_session, user)
    raw_revoked_token = _save_refresh_token(db_session, user, revoked_at=five_minutes_ago)

    with caplog.at_level("WARNING"):
        service.logout(db_session, user, raw_revoked_token)

    assert [record for record in caplog.records if record.levelno >= logging.WARNING] == []

    other_device_row = _token_row(db_session, raw_other_device_token)

    assert other_device_row.revoked_at is None


def test_signing_out_twice_keeps_the_first_revocation(db_session: Session, user: User) -> None:
    """A second sign-out with the same cookie changes nothing.

    A double click can send the cookie twice. The first sign-out revokes
    the token; the second finds it revoked and must leave its revocation
    time alone, so the record of when the session ended never moves. The
    time is read back from the database after each sign-out. The token was
    never rotated;
    ``test_a_second_logout_with_a_rotated_token_keeps_the_replacements_revocation``
    signs out twice with one that was.
    """
    raw_token = _save_refresh_token(db_session, user)

    service.logout(db_session, user, raw_token)
    first_revoked_at = _token_row(db_session, raw_token).revoked_at

    service.logout(db_session, user, raw_token)

    assert first_revoked_at is not None
    assert _token_row(db_session, raw_token).revoked_at == first_revoked_at


def test_logout_with_a_rotated_token_revokes_its_replacement(
    db_session: Session,
    user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Signing out with a token that a refresh has rotated ends the replacement too.

    A refresh of the same cookie can rotate the token just before the
    sign-out reads it, and send the browser the replacement. The sign-out
    must revoke that replacement, without linking it to another token, and
    commit, so the session can't come back: the session is rolled back
    before the rows are read, as a request's is when it ends. The rotated
    token keeps its own revocation time, the time of the rotation, and its
    link to the replacement, so the record of when the session was rotated
    never moves. The sign-out raises no reuse alarm, at WARNING or at any
    level above it, and the user's token on another device stays
    unrevoked. The next test signs out a second time with the same cookie.
    """
    raw_rotated_token = _save_rotated_token(db_session, user)
    raw_other_device_token = _save_refresh_token(db_session, user)
    rotated_row = _token_row(db_session, raw_rotated_token)
    rotated_at = rotated_row.revoked_at
    replacement_id = rotated_row.replaced_by_id

    assert replacement_id is not None

    with caplog.at_level("WARNING"):
        service.logout(db_session, user, raw_rotated_token)

    # A request's session is rolled back when it closes; only committed work remains.
    db_session.rollback()

    rotated_row = _token_row(db_session, raw_rotated_token)
    replacement_row = db_session.get(RefreshToken, replacement_id, populate_existing=True)
    other_device_row = _token_row(db_session, raw_other_device_token)

    assert rotated_row.revoked_at == rotated_at
    assert rotated_row.replaced_by_id == replacement_id
    assert replacement_row is not None
    assert replacement_row.revoked_at is not None
    assert replacement_row.replaced_by_id is None
    assert other_device_row.revoked_at is None
    assert [record for record in caplog.records if record.levelno >= logging.WARNING] == []


def test_a_second_logout_with_a_rotated_token_keeps_the_replacements_revocation(
    db_session: Session,
    user: User,
) -> None:
    """A second sign-out with a rotated cookie leaves the replacement's revocation time alone.

    This is the rotated counterpart of
    ``test_signing_out_twice_keeps_the_first_revocation``. The first
    sign-out with the rotated token revokes its replacement, as the test
    above checks. A double click sends the same cookie again, and the
    second sign-out finds the replacement revoked and must leave its
    revocation time alone, so the record of when the session ended never
    moves. The replacement is read back from the database after each
    sign-out.
    """
    raw_rotated_token = _save_rotated_token(db_session, user)
    replacement_id = _token_row(db_session, raw_rotated_token).replaced_by_id

    service.logout(db_session, user, raw_rotated_token)
    replacement_row = db_session.get(RefreshToken, replacement_id, populate_existing=True)
    first_revoked_at = replacement_row.revoked_at

    service.logout(db_session, user, raw_rotated_token)
    db_session.refresh(replacement_row)

    assert first_revoked_at is not None
    assert replacement_row.revoked_at == first_revoked_at


def test_logout_ignores_another_users_token(db_session: Session, user: User) -> None:
    """A user can't sign out someone else by presenting their token.

    The cookie holds another user's token while the access token names
    ``user``. Logout revokes only a token of the signed-in user, so neither
    token is revoked: a stolen cookie can't be used with another account to
    end its owner's session, and the caller's own token, which wasn't
    presented, stays as it was.
    """
    other_user = make_user(email="other-user@example.com")

    db_session.add(other_user)
    db_session.flush()

    raw_user_token = _save_refresh_token(db_session, user)
    raw_other_user_token = _save_refresh_token(db_session, other_user)

    service.logout(db_session, user, raw_other_user_token)

    user_refresh_token_row = _token_row(db_session, raw_user_token)
    other_user_refresh_token_row = _token_row(db_session, raw_other_user_token)

    assert user_refresh_token_row.revoked_at is None
    assert other_user_refresh_token_row.revoked_at is None


def test_logout_logs_and_prints_neither_the_secrets_nor_the_users_details(
    db_session: Session,
    user: User,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No sign-out logs or prints a token, the stored hash, or the user's email or name.

    ``logout``'s docstring says the cookie's token is never logged, and
    ``CLAUDE.md`` says no token ever is: anyone who can read the logs
    could use one that still works. ``logout`` is also handed the
    signed-in account, with its stored hash, its email, and its full
    name, and plan §12 keeps personal data out of logs. A valid token, a
    rotated one, whose replacement is revoked instead, and an unknown
    one, which changes nothing, are signed out while every record down to
    DEBUG is captured, and so is everything printed to stdout and stderr,
    where the application's log records go too, so a stray log line at
    any level or a stray ``print`` shows. None of the three tokens, the
    stored hash, the email, nor the full name may appear in the records
    or in either stream; a failure names each value found and where,
    never the value itself. The test of the same name in
    ``tests/test_auth_api.py`` checks the route and the bearer-token
    dependency too.
    """
    raw_refresh_token = _save_refresh_token(db_session, user)
    raw_rotated_token = _save_rotated_token(db_session, user)
    raw_unknown_token = generate_refresh_token()

    with caplog.at_level("DEBUG"):
        service.logout(db_session, user, raw_refresh_token)
        service.logout(db_session, user, raw_rotated_token)
        service.logout(db_session, user, raw_unknown_token)

    printed = capsys.readouterr()
    sensitive_values = {
        "refresh token": raw_refresh_token,
        "rotated token": raw_rotated_token,
        "unknown token": raw_unknown_token,
        "stored hash": user.password_hash,
        "email": user.email,
        "full name": user.full_name,
    }
    captured_texts = {"logs": caplog.text, "stdout": printed.out, "stderr": printed.err}

    assert [
        (name, channel)
        for name, value in sensitive_values.items()
        for channel, text in captured_texts.items()
        if value in text
    ] == []


def test_change_password_stores_a_hash_of_the_new_password(db_session: Session, user: User) -> None:
    """Changing the password stores a hash that only the new password matches.

    The account's hash isn't the plain new password, the old password no
    longer verifies against it, and the new one does. ``user`` is the very
    object the service changes: its locked lookup returns the session's own
    copy of the account, refreshed from the locked row. The hash being
    saved is checked by ``test_the_password_change_is_committed``.
    """
    service.change_password(db_session, user, _password_change())

    assert user.password_hash != NEW_PASSWORD
    assert not verify_password(PASSWORD, user.password_hash)
    assert verify_password(NEW_PASSWORD, user.password_hash)


def test_change_password_clears_the_forced_change_flag(db_session: Session, user: User) -> None:
    """A successful change clears ``must_change_password``.

    The flag is set explicitly first, so the test sees it go from true to
    false whatever the database default. Clearing it lifts the
    forced-change gate, so the user can reach the rest of the API.
    """
    user.must_change_password = True
    db_session.flush()

    service.change_password(db_session, user, _password_change())

    assert user.must_change_password is False


def test_change_password_revokes_every_existing_session(db_session: Session, user: User) -> None:
    """Changing the password revokes every refresh token the user holds.

    The two tokens stand for two signed-in devices, the one making the
    change and another. Both rows, read back after the change, are revoked,
    so anyone still holding an old token, such as someone who knew the old
    password, can no longer refresh. The next test checks the session the
    change starts.
    """
    raw_refresh_token = _save_refresh_token(db_session, user)
    raw_other_device_token = _save_refresh_token(db_session, user)

    service.change_password(db_session, user, _password_change())

    refresh_token_row = _token_row(db_session, raw_refresh_token)
    other_device_row = _token_row(db_session, raw_other_device_token)

    assert refresh_token_row.revoked_at is not None
    assert other_device_row.revoked_at is not None


@pytest.mark.usefixtures("three_day_refresh_tokens")
def test_change_password_returns_a_working_session(db_session: Session, user: User) -> None:
    """The change returns a new session for the device that made it.

    The new refresh token's row belongs to the user and is unrevoked, so it
    escaped the revocation that ends the old sessions, and it expires the
    configured number of days after the change, three here: a fresh window,
    checked from both sides so a shorter or longer lifetime fails, and a
    lifetime written into the code fails as well. The access token names
    the user. That the new cookie refreshes is checked through the API.
    """
    before = datetime.now(UTC) + timedelta(days=3)
    issued_tokens = service.change_password(db_session, user, _password_change())
    after = datetime.now(UTC) + timedelta(days=3)

    token_row = _token_row(db_session, issued_tokens.refresh_token)

    assert token_row.user_id == user.id
    assert token_row.revoked_at is None
    assert before <= token_row.expires_at <= after
    assert decode_access_token(issued_tokens.access_token) == user.id


def test_change_password_leaves_the_sign_in_time_alone(db_session: Session, user: User) -> None:
    """A password change keeps ``last_login_at`` at the time of the last sign-in.

    The user signed in a day ago. A password change is not a sign-in,
    although it starts a new session, so a change that set the column
    would leave it showing the latest password change instead of the
    latest sign-in. The user is read back from the database after the
    change, so the time checked is the one saved.
    ``test_refresh_leaves_the_sign_in_time_alone`` checks the same for
    refresh.
    """
    signed_in_at = datetime.now(UTC) - timedelta(days=1)
    user.last_login_at = signed_in_at
    db_session.flush()

    service.change_password(db_session, user, _password_change())
    db_session.refresh(user)

    assert user.last_login_at == signed_in_at


def test_the_password_change_is_committed(db_session: Session, user: User) -> None:
    """The password change is committed, so it survives a rollback.

    The session is rolled back after the change, as a request's session is
    when it closes, and the new password, the cleared flag, and the new
    session are all still saved. The flag starts set, as the database
    default leaves it. Had the change left anything uncommitted, the
    rollback would undo it and expire ``user``, which would then show the
    stored values; after a commit it has nothing to undo, so ``user`` keeps
    the values the commit saved. The earlier tests can't see a missing
    commit, because the changes are still in the session there. Nor can
    this one see how many commits the change made;
    ``test_a_password_change_that_fails_at_its_commit_saves_nothing`` does.
    """
    issued_tokens = service.change_password(db_session, user, _password_change())

    db_session.rollback()

    new_token_row = _token_row(db_session, issued_tokens.refresh_token)

    assert verify_password(NEW_PASSWORD, user.password_hash)
    assert user.must_change_password is False
    assert new_token_row.revoked_at is None


def test_a_password_change_that_fails_at_its_commit_saves_nothing(
    db_session: Session,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A change whose commit fails leaves the password, the flag, and the sessions as they were.

    The change is committed once, at the end, so a failure at any point,
    the commit included, saves nothing, and the user can simply try again.
    A change that committed the new password first and then failed would
    leave it saved while every old session, a thief's included, kept
    working, and would release the user's row lock before the sessions
    were revoked. To make the commit fail, the new refresh token repeats
    the value of a token the user already holds: ``generate_refresh_token``
    is replaced where the auth service looks it up, so the new row's
    ``INSERT`` breaks the unique token hash, which the error must name.

    The flag is set and the setup committed first, as a request finds
    them, so the rollback after the error, as a failed request's session
    is rolled back, undoes only the change. The user, read back from the
    database, still has the old hash and the flag, and the token is still
    unrevoked.
    """
    user.must_change_password = True
    raw_refresh_token = _save_refresh_token(db_session, user)
    original_hash = user.password_hash
    db_session.commit()
    monkeypatch.setattr(service, "generate_refresh_token", lambda: raw_refresh_token)

    with pytest.raises(IntegrityError, match="uq_refresh_tokens_token_hash"):
        service.change_password(db_session, user, _password_change())

    # A failed request's session is rolled back; only committed work remains.
    db_session.rollback()
    db_session.refresh(user)

    assert user.password_hash == original_hash
    assert user.must_change_password is True
    assert _token_row(db_session, raw_refresh_token).revoked_at is None


@pytest.mark.parametrize(("overrides", "message"), REJECTED_PASSWORD_CHANGES)
def test_a_rejected_change_raises_and_writes_nothing(
    db_session: Session,
    user: User,
    overrides: dict[str, str],
    message: str,
) -> None:
    """A refused change raises a 400 with its own message and changes nothing.

    The user has one signed-in device and the forced-change flag set, as
    the fixture's database default leaves it. After the refusal, the stored
    hash is exactly the one from before, the flag is still set, the
    device's token is not revoked, and no new token was issued: none of the
    four things a successful change writes. The hash is compared directly,
    because in the reuse case a hash rewritten from the same password would
    still verify. There is no rollback, so even changes the service made
    without committing would show. The last case fails both checks and
    must get the first one's message, so the current password is checked
    before the new one is compared with it.
    """
    _save_refresh_token(db_session, user)
    original_hash = user.password_hash

    with pytest.raises(BadRequestError) as exc_info:
        service.change_password(db_session, user, _password_change(**overrides))

    error = exc_info.value
    token_rows = (
        db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
        .scalars()
        .all()
    )

    assert error.status_code == 400
    assert error.code == ErrorCode.BAD_REQUEST
    assert error.message == message
    assert user.password_hash == original_hash
    assert user.must_change_password is True
    assert len(token_rows) == 1
    assert token_rows[0].revoked_at is None


def test_change_password_leaves_other_users_alone(db_session: Session, user: User) -> None:
    """Changing one user's password leaves every other account as it was.

    Another user is signed in on a device. After ``user`` changes their
    password, that user's token row, read back from the database, is not
    revoked, and their password hash is unchanged. The hash is the
    session's copy of ``other_user``, which the commit leaves as it was,
    since the session doesn't expire objects on commit: a change made
    through the session, such as an ORM update of every account, would
    show in it, but one made in raw SQL would not.
    """
    other_user = make_user(email="other-user@example.com")
    other_user_original_hash = other_user.password_hash

    db_session.add(other_user)
    db_session.flush()

    raw_other_user_token = _save_refresh_token(db_session, other_user)

    service.change_password(db_session, user, _password_change())

    other_user_token_row = _token_row(db_session, raw_other_user_token)

    assert other_user_token_row.revoked_at is None
    assert other_user.password_hash == other_user_original_hash


def test_change_password_logs_neither_the_passwords_nor_the_tokens(
    db_session: Session,
    user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No password change, refused or made, logs a password, a hash, or a token.

    Plan §12 says passwords are never logged, ``CLAUDE.md`` says the same
    of password hashes and tokens, and ``change_password``'s docstring
    says neither password is logged. A change refused for a wrong current
    password, one refused because the new password is the current one,
    and a successful one run while every record down to DEBUG is
    captured, so a stray log line at any level shows. None of the three
    passwords typed, the hash from before the change, the new hash, which
    ``user`` holds once the change is made, nor either token the
    successful change issued may appear in the captured text. The test of
    the same name in ``tests/test_auth_api.py`` checks the route's logs.
    """
    original_hash = user.password_hash

    with caplog.at_level("DEBUG"):
        with pytest.raises(BadRequestError):
            service.change_password(
                db_session, user, _password_change(current_password="Wrong-Password-1")
            )

        with pytest.raises(BadRequestError):
            service.change_password(db_session, user, _password_change(new_password=PASSWORD))

        issued_tokens = service.change_password(db_session, user, _password_change())

    assert PASSWORD not in caplog.text
    assert NEW_PASSWORD not in caplog.text
    assert "Wrong-Password-1" not in caplog.text
    assert original_hash not in caplog.text
    assert user.password_hash not in caplog.text
    assert issued_tokens.access_token not in caplog.text
    assert issued_tokens.refresh_token not in caplog.text


def test_a_token_revoked_without_rotation_is_refused_quietly(
    db_session: Session,
    user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A token revoked on purpose gets the generic error and raises no alarm.

    The token was revoked five minutes ago and has no ``replaced_by_id``,
    as a sign-out or a password change leaves it. The server ended it on
    purpose, so it is not a stolen copy: the user's other device keeps its
    session, and nothing is logged from WARNING up, so an alarm logged at
    ERROR fails as well as one logged at WARNING. Without this, another
    device refreshing after a password change would sign out the device
    that made the change.
    """
    five_minutes_ago = datetime.now(UTC) - timedelta(minutes=5)
    raw_revoked_token = _save_refresh_token(db_session, user, revoked_at=five_minutes_ago)
    raw_other_device_token = _save_refresh_token(db_session, user)

    with caplog.at_level("WARNING"), pytest.raises(AuthenticationError) as exc_info:
        service.refresh(db_session, raw_revoked_token)

    other_device_row = _token_row(db_session, raw_other_device_token)

    _assert_generic_token_error(exc_info.value)
    assert other_device_row.revoked_at is None
    assert [record for record in caplog.records if record.levelno >= logging.WARNING] == []


def test_a_pending_password_change_is_refused(user: User) -> None:
    """A user who must change their password is refused with its own 403 code.

    The flag is set explicitly, so the test doesn't depend on the database
    default. The status, the code, and the message are compared: the code,
    not the generic ``PERMISSION_DENIED``, is what tells the web app to
    show the change-password screen instead of an error.
    """
    user.must_change_password = True

    with pytest.raises(PermissionDeniedError) as exc_info:
        service.ensure_password_change_not_pending(user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.PASSWORD_CHANGE_REQUIRED
    assert exc_info.value.message == PASSWORD_CHANGE_REQUIRED


def test_a_user_without_a_pending_change_passes_the_gate(user: User) -> None:
    """A user with no pending password change passes the gate without an error.

    The flag is cleared explicitly, because the fixture's user starts with
    the database default, which is set.
    """
    user.must_change_password = False

    assert service.ensure_password_change_not_pending(user) is None
