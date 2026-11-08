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
hash of a new refresh token, one per sign-in, which expires after the
configured number of days. It records the sign-in time, accepts the email
in any case and with spaces around it, and lets a user with a pending
password change in. Every failed sign-in raises ``AuthenticationError``
with the same message and writes nothing, and an unknown email still runs
the password check. A valid access token is turned back into the active
user it names, looked up once by the ID inside it; every other token gets
the same error, and one that doesn't decode gets it before any lookup.
Refresh rotates the token and keeps its expiry. A rotated token presented again revokes every
token of its user, commits that, and logs one warning without the token,
however old it is, while every other unusable token is refused with the
same error and no alarm. Sign-out revokes only the presented token, or
the replacement of one a refresh has rotated, and ignores a token it
can't use. A password change refuses a wrong current password or an
unchanged new one with a 400; otherwise it replaces the hash, clears the
forced-change flag, ends every session, and starts a new one, all
committed. The password-change gate refuses a user with a pending change
with a 403 and a code of its own.

The row locks that keep concurrent requests apart can only be seen from a
second connection, so ``tests/test_auth_concurrency.py`` tests them. The
routes, the cookie, and the response bodies are tested in
``tests/test_auth_api.py``, the token and password functions in
``tests/test_security.py``, and the queries in
``tests/test_auth_repository.py``.
"""

# Random UUIDs: an ID no user has; also the type of the IDs the lookup spy records.
import uuid

# UTC time zone; every time a test builds is timezone-aware UTC, as the service's are.
from datetime import UTC

# The current time: bounds for a sign-in time or an expiry, and a saved token's own times.
from datetime import datetime

# Moves a time by days, minutes, or seconds: a lifetime ahead, or an expiry in the past.
from datetime import timedelta

# Test framework: fixtures, marks, raises, and the monkeypatch and caplog types.
import pytest

# Builds an unsaved refresh token for a saved user; the helpers give it a real token's hash.
from factories import make_refresh_token

# Builds an unsaved User: the user fixture's account, and the other accounts some tests save.
from factories import make_user

# Builds the queries that read token rows back after a use case.
from sqlalchemy import select

# Type of the db_session fixture, the session every use case here runs in.
from sqlalchemy.orm import Session

# Cached settings; three_day_refresh_tokens copies them with a refresh lifetime of its own.
from app.core.config import get_settings

# What a failed sign-in or a rejected token raises, which the API answers with 401.
from app.core.errors import AuthenticationError

# What a refused password change raises, which the API answers with 400.
from app.core.errors import BadRequestError

# Machine-readable error codes; a refused change's and a pending change's codes are checked.
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

# The refresh_tokens table's ORM model; the read-back queries select it.
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
# deactivated account gets the same error and message. An account that
# changes during the check is tested in tests/test_auth_concurrency.py.
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
# field it replaces in the otherwise valid input and the message the user
# sees. The wrong current password passes the schema, which limits only its
# length, so the refusal comes from the service's check against the stored
# hash. An account deactivated or deleted since the request's authentication
# gets a 401 instead, tested in tests/test_auth_concurrency.py.
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


def test_each_login_issues_a_new_refresh_token(db_session: Session, user: User) -> None:
    """Two sign-ins save two rows and return two different refresh tokens.

    A new sign-in never reuses or overwrites an earlier token's row, so
    each device a user signs in on gets a session of its own. The test
    can't see whether the first token still works afterwards: a sign-in
    that revoked the user's other tokens before issuing its own would pass
    it.
    """
    first_login = service.login(db_session, user.email, PASSWORD)
    second_login = service.login(db_session, user.email, PASSWORD)
    token_rows = db_session.scalars(select(RefreshToken)).all()

    assert len(token_rows) == 2
    assert first_login.refresh_token != second_login.refresh_token


@pytest.mark.parametrize(("email", "password", "is_active"), FAILED_LOGINS)
def test_a_failed_login_raises_the_generic_error(
    db_session: Session,
    email: str,
    password: str,
    is_active: bool,
) -> None:
    """Every kind of failed sign-in raises ``AuthenticationError`` with the same message.

    A wrong password, an unknown email, and a deactivated account must look
    the same, so a caller can't discover which emails have accounts or
    which accounts are deactivated. Only the class and the message are
    compared: an error that carried a code or details of its own for one
    kind, which the API would send in the 401's body, would pass.
    """
    user = make_user(password_hash=hash_password(PASSWORD), is_active=is_active)
    db_session.add(user)
    db_session.flush()

    with pytest.raises(AuthenticationError) as exc_info:
        service.login(db_session, email, password)

    assert exc_info.value.message == INVALID_CREDENTIALS


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown email still goes through the password check, with no hash.

    ``verify_login_password`` is replaced where the service looks it up, and
    the spy records exactly one call, with None: the path that checks the
    password against the dummy hash, so an unknown email takes as long as a
    wrong password. The cost of that path is tested in
    ``tests/test_security.py``. Only the unknown email is spied on, so a
    sign-in that refused a deactivated account before checking its password
    would pass every test here.
    """
    calls: list[str | None] = []
    real_check = service.verify_login_password

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
        return real_check(password, password_hash)

    monkeypatch.setattr(service, "verify_login_password", spy)

    with pytest.raises(AuthenticationError) as exc_info:
        service.login(db_session, "ghost@example.com", PASSWORD)

    assert calls == [None]
    assert exc_info.value.message == INVALID_CREDENTIALS


def test_a_valid_token_returns_its_user(db_session: Session, user: User) -> None:
    """A freshly issued token for an active user returns that user."""
    access_token = create_access_token(user.id)
    result = service.get_authenticated_user(db_session, access_token)

    assert result.id == user.id


@pytest.mark.parametrize(
    "access_token",
    (
        pytest.param("not-a-token", id="garbage"),
        pytest.param("", id="empty"),
        pytest.param(create_access_token(uuid.uuid4()), id="unknown-user"),
    ),
)
def test_an_unusable_token_raises_the_generic_error(
    db_session: Session,
    user: User,
    access_token: str,
) -> None:
    """Every token that can't identify an active user gets the same 401 error.

    A garbage string and an empty one, which is what a bare ``Bearer``
    header produces, fail to decode. The unknown-user token is correctly
    signed but names an id nobody has. The ``user`` fixture is there as a
    decoy: with a real active user in the table, a lookup that ignored the
    id would find that user, and the test would fail. Expired, tampered,
    and wrong-key tokens are covered in ``test_security.py``. The message
    is compared with a literal, so it can't drift from the decoder's.
    """
    with pytest.raises(AuthenticationError) as exc_info:
        service.get_authenticated_user(db_session, access_token)

    assert exc_info.value.message == INVALID_TOKEN


def test_a_token_stops_working_once_its_user_is_deactivated(
    db_session: Session,
    user: User,
) -> None:
    """A token issued before deactivation is refused once the user is inactive.

    The token is still correctly signed and unexpired, so only the database
    read can catch this: deactivation applies to the next request, not
    when the token runs out. The error is the generic one, so the holder
    can't tell the account was deactivated.
    """
    access_token = create_access_token(user.id)
    user.is_active = False

    db_session.flush()

    with pytest.raises(AuthenticationError) as exc_info:
        service.get_authenticated_user(db_session, access_token)

    assert exc_info.value.message == INVALID_TOKEN


def test_a_user_who_must_change_their_password_is_still_authenticated(
    db_session: Session,
    user: User,
) -> None:
    """A pending password change doesn't stop the token identifying the user.

    The current-user endpoint must keep working in this state, so the web
    app can show the change-password screen. The password-change gate
    belongs to the routes it covers, not to this function, and this test
    fails if it is moved here.
    """
    access_token = create_access_token(user.id)
    user.must_change_password = True
    db_session.flush()

    result = service.get_authenticated_user(db_session, access_token)
    assert result.id == user.id


def test_a_bad_token_never_reaches_the_database(
    db_session: Session,
    lookup_calls: list[uuid.UUID],
) -> None:
    """A token that fails to decode is rejected before any user lookup.

    Decoding needs no database, so it runs first and junk tokens never cost
    a query. The error alone can't show this: code that swallowed the
    decode error and then looked up a made-up id would also end in the
    generic 401, so the unusable-token test would still pass. Only the
    ``lookup_calls`` spy sees the difference, and it must record nothing
    here. The next test is its positive control.
    """
    with pytest.raises(AuthenticationError) as exc_info:
        service.get_authenticated_user(db_session, "not-a-token")

    assert lookup_calls == []
    assert exc_info.value.message == INVALID_TOKEN


def test_a_valid_token_looks_up_the_user_it_names(
    db_session: Session,
    user: User,
    lookup_calls: list[uuid.UUID],
) -> None:
    """A valid token leads to exactly one lookup, by the id inside it.

    This is the positive control for the test above. An empty call list
    there would also appear if the spy were patched in the wrong place and
    never called, so this test shows the same spy does record a lookup
    when one happens. It also shows the user is loaded by the id the token
    carries, and only once.
    """
    result = service.get_authenticated_user(db_session, create_access_token(user.id))

    assert lookup_calls == [user.id]
    assert result.id == user.id


def test_refresh_returns_an_access_token_for_the_user(db_session: Session, user: User) -> None:
    """A valid refresh token gets a new access token that names its owner."""
    raw_refresh_token = _save_refresh_token(db_session, user)
    issued_tokens = service.refresh(db_session, raw_refresh_token)

    assert decode_access_token(issued_tokens.access_token) == user.id


def test_refresh_issues_a_new_refresh_token(db_session: Session, user: User) -> None:
    """Refresh returns a different refresh token, saved and still usable.

    Checking the saved row matters more than the inequality: a refresh that
    returned a random string without storing it would hand the client a
    token its next refresh could never use.
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
    lets a later investigation follow a chain of rotations.
    """
    raw_refresh_token = _save_refresh_token(db_session, user)
    issued_tokens = service.refresh(db_session, raw_refresh_token)
    old_token_row = _token_row(db_session, raw_refresh_token)
    new_token_row = _token_row(db_session, issued_tokens.refresh_token)

    assert old_token_row.revoked_at is not None
    assert old_token_row.replaced_by_id == new_token_row.id


def test_the_new_token_keeps_the_old_expiry(db_session: Session, user: User) -> None:
    """The replacement token expires exactly when the original one did.

    The original expiry is three days away, not the configured seven, so a
    refresh that started a fresh window would give a visibly different
    value. Keeping it means everyone signs in again at least once a window.
    """
    original_expires_at = datetime.now(UTC) + timedelta(days=3)
    raw_refresh_token = _save_refresh_token(db_session, user, expires_at=original_expires_at)
    issued_tokens = service.refresh(db_session, raw_refresh_token)
    new_token_row = _token_row(db_session, issued_tokens.refresh_token)

    assert new_token_row.expires_at == original_expires_at


def test_refresh_works_while_a_password_change_is_pending(db_session: Session, user: User) -> None:
    """A user who must change their password still gets a working session.

    The web app refreshes after a reload and then shows the change-password
    screen, so refresh must stay open in this state.
    """
    raw_refresh_token = _save_refresh_token(db_session, user)
    user.must_change_password = True

    db_session.flush()

    issued_tokens = service.refresh(db_session, raw_refresh_token)

    assert decode_access_token(issued_tokens.access_token) == user.id


def test_a_refresh_token_works_only_once(db_session: Session, user: User) -> None:
    """Presenting the same refresh token a second time gets the generic error.

    This is rotation seen from the client: the first refresh replaces the
    token, so the second use is treated as reuse.
    """
    raw_refresh_token = _save_refresh_token(db_session, user)
    service.refresh(db_session, raw_refresh_token)

    with pytest.raises(AuthenticationError) as exc_info:
        service.refresh(db_session, raw_refresh_token)

    assert exc_info.value.message == INVALID_TOKEN


@pytest.mark.parametrize("case", UNUSABLE_REFRESH_TOKENS)
def test_an_unusable_refresh_token_raises_the_generic_error(
    db_session: Session,
    user: User,
    case: str,
) -> None:
    """Every unusable refresh token gets the same error and message.

    A missing cookie, an empty one, an unknown token, an expired one, and a
    deactivated owner are indistinguishable from outside, so the reply
    never says which check failed.
    """
    raw_refresh_token = _present_token(db_session, user, case)

    with pytest.raises(AuthenticationError) as exc_info:
        service.refresh(db_session, raw_refresh_token)

    assert exc_info.value.message == INVALID_TOKEN


@pytest.mark.parametrize("case", UNUSABLE_REFRESH_TOKENS)
def test_an_unusable_refresh_token_writes_nothing(
    db_session: Session,
    user: User,
    case: str,
) -> None:
    """A failed refresh adds no token and revokes none.

    A valid token is saved first, so there is something a faulty refresh
    could wrongly change, and rows are counted after each case's own setup.
    Reuse is the only failure that writes, and it has its own tests.
    """
    _save_refresh_token(db_session, user)
    raw_refresh_token = _present_token(db_session, user, case)
    token_count_before = len(db_session.scalars(select(RefreshToken)).all())

    with pytest.raises(AuthenticationError):
        service.refresh(db_session, raw_refresh_token)

    token_rows = db_session.scalars(select(RefreshToken)).all()

    assert len(token_rows) == token_count_before
    assert all(row.revoked_at is None for row in token_rows)


def test_reusing_a_rotated_token_revokes_every_token_of_the_user(
    db_session: Session,
    user: User,
) -> None:
    """Presenting a rotated token again ends the user's other sessions too.

    The user also holds an active token, as on a second device. A token
    that was already replaced coming back means a copy exists, and the
    server can't tell the real user from a thief, so the active token is
    revoked as well.
    """
    raw_rotated_token = _save_rotated_token(db_session, user)
    raw_other_device_token = _save_refresh_token(db_session, user)

    with pytest.raises(AuthenticationError) as exc_info:
        service.refresh(db_session, raw_rotated_token)

    other_device_row = _token_row(db_session, raw_other_device_token)

    assert exc_info.value.message == INVALID_TOKEN
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

    assert exc_info.value.message == INVALID_TOKEN
    assert other_device_row.revoked_at is not None


def test_reuse_is_logged_without_the_token(
    db_session: Session,
    user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reuse logs exactly one warning naming the user, and never the token.

    The warning lets someone find the incident later. The raw token must
    not appear anywhere in the captured logs, because anyone who can read
    the logs could otherwise use it.
    """
    raw_rotated_token = _save_rotated_token(db_session, user)

    with caplog.at_level("WARNING"), pytest.raises(AuthenticationError):
        service.refresh(db_session, raw_rotated_token)

    warnings = [record for record in caplog.records if record.levelname == "WARNING"]

    assert len(warnings) == 1
    assert str(user.id) in warnings[0].getMessage()
    assert raw_rotated_token not in caplog.text


def test_an_expired_token_does_not_revoke_the_others(db_session: Session, user: User) -> None:
    """An expired token is only rejected; the user's other session survives.

    Tokens expire whenever someone stays away for a while, so treating
    expiry like reuse would sign ordinary users out on every device.
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
    would answer the same 401 with no warning and no revocation.
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

    assert exc_info.value.message == INVALID_TOKEN
    assert other_device_row.revoked_at is not None
    assert len(warnings) == 1
    assert str(user.id) in warnings[0].getMessage()
    assert raw_rotated_token not in caplog.text


def test_reuse_leaves_other_users_tokens_alone(db_session: Session, user: User) -> None:
    """Reuse ends the sessions of the token's owner and nobody else.

    The repository tests prove the revocation query filters by user; this
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

    The device can never refresh with that token again. ``replaced_by_id``
    stays empty, which tells a sign-out apart from a rotation when the
    table is investigated later.
    """
    raw_token = _save_refresh_token(db_session, user)

    service.logout(db_session, user, raw_token)

    refresh_token_row = _token_row(db_session, raw_token)

    assert refresh_token_row.revoked_at is not None
    assert refresh_token_row.replaced_by_id is None


def test_the_logout_revocation_is_committed(db_session: Session, user: User) -> None:
    """The revocation is committed, so it survives a rollback.

    The session is rolled back after logout, as the request's session is
    when it closes, and the token is still revoked. The previous test can't
    see a missing commit, because the change is still in the session there.
    """
    raw_token = _save_refresh_token(db_session, user)

    service.logout(db_session, user, raw_token)
    db_session.rollback()

    refresh_token_row = _token_row(db_session, raw_token)

    assert refresh_token_row.revoked_at is not None
    assert refresh_token_row.replaced_by_id is None


def test_logout_leaves_the_users_other_sessions_alone(db_session: Session, user: User) -> None:
    """Signing out on one device keeps the user signed in on the others.

    The user holds two tokens, as on a laptop and a phone. Only the one
    presented is revoked, so logout must never revoke every token the way
    reuse detection does.
    """
    first_raw_token = _save_refresh_token(db_session, user)
    second_raw_token = _save_refresh_token(db_session, user)

    service.logout(db_session, user, first_raw_token)

    first_refresh_token_row = _token_row(db_session, first_raw_token)
    second_refresh_token_row = _token_row(db_session, second_raw_token)

    assert first_refresh_token_row.revoked_at is not None
    assert first_refresh_token_row.replaced_by_id is None
    assert second_refresh_token_row.revoked_at is None


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
    could wrongly revoke, and it must still be unrevoked afterwards.
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
    """An already revoked token is ignored: no warning, and no mass revocation.

    In refresh, a rotated token presented again means a copy exists and
    ends every session. At logout a revoked token usually means a double
    click or a second tab signing out too, so the user's other token must
    stay active and nothing is logged as a security warning.
    """
    five_minutes_ago = datetime.now(UTC) - timedelta(minutes=5)
    unrevoked_raw_token = _save_refresh_token(db_session, user)
    revoked_raw_token = _save_refresh_token(db_session, user, revoked_at=five_minutes_ago)

    with caplog.at_level("WARNING"):
        service.logout(db_session, user, revoked_raw_token)

    warnings = [record for record in caplog.records if record.levelname == "WARNING"]

    assert warnings == []

    unrevoked_token_row = _token_row(db_session, unrevoked_raw_token)

    assert unrevoked_token_row.revoked_at is None


def test_signing_out_twice_keeps_the_first_revocation(db_session: Session, user: User) -> None:
    """A second sign-out with the same cookie changes nothing.

    A double click can send the cookie twice. The first sign-out revokes
    the token; the second finds it revoked and must leave its revocation
    time alone, so the record of when the session ended never moves.
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
    commit, so the session can't come back. It raises no reuse alarm, and
    the user's token on another device stays active.
    """
    raw_rotated_token = _save_rotated_token(db_session, user)
    raw_other_device_token = _save_refresh_token(db_session, user)
    replacement_id = _token_row(db_session, raw_rotated_token).replaced_by_id

    assert replacement_id is not None

    with caplog.at_level("WARNING"):
        service.logout(db_session, user, raw_rotated_token)

    # A request's session is rolled back when it closes; only committed work remains.
    db_session.rollback()

    replacement_row = db_session.get(RefreshToken, replacement_id, populate_existing=True)
    other_device_row = _token_row(db_session, raw_other_device_token)
    warnings = [record for record in caplog.records if record.levelname == "WARNING"]

    assert replacement_row is not None
    assert replacement_row.revoked_at is not None
    assert replacement_row.replaced_by_id is None
    assert other_device_row.revoked_at is None
    assert warnings == []


def test_logout_ignores_another_users_token(db_session: Session, user: User) -> None:
    """A user can't sign out someone else by presenting their token.

    The cookie holds another user's token while the access token names
    ``user``. Logout ends only the caller's own session, so neither
    token is revoked: a stolen cookie can't be used with another account
    to end its owner's session.
    """
    other_user = make_user(email="other-user@example.com")

    db_session.add(other_user)
    db_session.flush()

    user_raw_token = _save_refresh_token(db_session, user)
    other_user_raw_token = _save_refresh_token(db_session, other_user)

    service.logout(db_session, user, other_user_raw_token)

    user_refresh_token_row = _token_row(db_session, user_raw_token)
    other_user_refresh_token_row = _token_row(db_session, other_user_raw_token)

    assert user_refresh_token_row.revoked_at is None
    assert other_user_refresh_token_row.revoked_at is None


def test_change_password_stores_a_hash_of_the_new_password(db_session: Session, user: User) -> None:
    """Changing the password stores a hash that only the new password matches.

    The stored value isn't the plain new password, the old password no
    longer verifies, and the new one does.
    """
    service.change_password(db_session, user, _password_change())

    assert user.password_hash != NEW_PASSWORD
    assert not verify_password(PASSWORD, user.password_hash)
    assert verify_password(NEW_PASSWORD, user.password_hash)


def test_change_password_clears_the_forced_change_flag(db_session: Session, user: User) -> None:
    """A successful change clears ``must_change_password``.

    The flag is set first, so the test sees it go from true to false.
    Clearing it lifts the forced-change gate, so the user can reach the
    rest of the API.
    """
    user.must_change_password = True
    db_session.flush()

    service.change_password(db_session, user, _password_change())

    assert user.must_change_password is False


def test_change_password_revokes_every_existing_session(db_session: Session, user: User) -> None:
    """Changing the password revokes every refresh token the user holds.

    The two tokens stand for two signed-in devices. Both are revoked, so
    anyone still holding an old token, such as someone who knew the old
    password, is signed out everywhere.
    """
    first_token = _save_refresh_token(db_session, user)
    second_token = _save_refresh_token(db_session, user)

    service.change_password(db_session, user, _password_change())

    first_token_row = _token_row(db_session, first_token)
    second_token_row = _token_row(db_session, second_token)

    assert first_token_row.revoked_at is not None
    assert second_token_row.revoked_at is not None


@pytest.mark.usefixtures("three_day_refresh_tokens")
def test_change_password_returns_a_working_session(db_session: Session, user: User) -> None:
    """The change returns a new session for the device that made it.

    The new refresh token belongs to the user, escapes the revocation of
    the old tokens, and expires the configured number of days after the
    change, three here: a fresh window, checked from both sides so a
    longer lifetime fails too, and a lifetime written into the code fails
    as well. The access token names the user.
    """
    before = datetime.now(UTC) + timedelta(days=3)
    issued_tokens = service.change_password(db_session, user, _password_change())
    after = datetime.now(UTC) + timedelta(days=3)

    token_row = _token_row(db_session, issued_tokens.refresh_token)

    assert token_row.user_id == user.id
    assert token_row.revoked_at is None
    assert before <= token_row.expires_at <= after
    assert decode_access_token(issued_tokens.access_token) == user.id


def test_the_password_change_is_committed(db_session: Session, user: User) -> None:
    """The password change is committed, so it survives a rollback.

    The session is rolled back after the change, as the request's session
    is when it closes, and the new password, the cleared flag, and the new
    session are all still saved. The rollback also makes ``user`` reload
    from the database. The earlier tests can't see a missing commit,
    because the changes are still in the session there.
    """
    issued_tokens = service.change_password(db_session, user, _password_change())

    db_session.rollback()

    new_token_row = _token_row(db_session, issued_tokens.refresh_token)

    assert verify_password(NEW_PASSWORD, user.password_hash)
    assert user.must_change_password is False
    assert new_token_row.revoked_at is None


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
    without committing would show.
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
    password, that user's token is not revoked and their password hash is
    unchanged. The service commits, so ``other_user`` reloads from the
    database and the hash read afterwards is the saved one.
    """
    other_user = make_user(email="other-user@example.com")
    other_user_original_hash = other_user.password_hash

    db_session.add(other_user)
    db_session.flush()

    other_user_raw_token = _save_refresh_token(db_session, other_user)

    service.change_password(db_session, user, _password_change())

    other_user_token_row = _token_row(db_session, other_user_raw_token)

    assert other_user_token_row.revoked_at is None
    assert other_user.password_hash == other_user_original_hash


def test_a_token_revoked_without_rotation_is_refused_quietly(
    db_session: Session,
    user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A token revoked on purpose gets the generic error and raises no alarm.

    The token has ``revoked_at`` but no ``replaced_by_id``, as a sign-out
    or a password change leaves it. The server ended it on purpose, so it
    is not a stolen copy: the user's other device keeps its session, and
    nothing is logged as a warning. Without this, another device
    refreshing after a password change would sign out the device that
    made the change.
    """
    five_minutes_ago = datetime.now(UTC) - timedelta(minutes=5)
    raw_revoked_token = _save_refresh_token(db_session, user, revoked_at=five_minutes_ago)
    raw_other_device_token = _save_refresh_token(db_session, user)

    with caplog.at_level("WARNING"), pytest.raises(AuthenticationError) as exc_info:
        service.refresh(db_session, raw_revoked_token)

    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    other_device_row = _token_row(db_session, raw_other_device_token)

    assert exc_info.value.message == INVALID_TOKEN
    assert other_device_row.revoked_at is None
    assert warnings == []


def test_a_pending_password_change_is_refused(user: User) -> None:
    """A user who must change their password is refused with its own 403 code.

    The code, not the generic ``PERMISSION_DENIED``, is what tells the web
    app to show the change-password screen instead of an error.
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
