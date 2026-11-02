import uuid
from datetime import UTC
from datetime import datetime
from datetime import timedelta

import pytest
from factories import make_refresh_token
from factories import make_user
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthenticationError
from app.core.errors import BadRequestError
from app.core.errors import ErrorCode
from app.core.security import create_access_token
from app.core.security import decode_access_token
from app.core.security import generate_refresh_token
from app.core.security import hash_password
from app.core.security import hash_refresh_token
from app.core.security import verify_password
from app.modules.auth import service
from app.modules.auth.models import RefreshToken
from app.modules.auth.schemas import PasswordChange
from app.modules.users.models import User

PASSWORD = "Correct-Password-1"
NEW_PASSWORD = "New-Password-123"
INVALID_CREDENTIALS = "Incorrect email or password."
INVALID_TOKEN = "Invalid or expired token."
REFRESH_TOKEN_EXPIRE_DAYS = get_settings().refresh_token_expire_days

# Every way a sign-in can fail. The only saved user is test@example.com with
# PASSWORD, so ghost@example.com is truly unknown and the inactive-user case
# reaches the is_active check with the right password. The last case shows a
# wrong password on a deactivated account gets the very same answer.
FAILED_LOGINS = [
    pytest.param("test@example.com", "Wrong-Password-1", True, id="wrong-password"),
    pytest.param("ghost@example.com", PASSWORD, True, id="unknown-email"),
    pytest.param("test@example.com", PASSWORD, False, id="inactive-user"),
    pytest.param("test@example.com", "Wrong-Password-1", False, id="inactive-wrong-password"),
]

# Every way a refresh can fail without being reuse. Each name is turned into
# the value to present by _present_token, because some cases need a saved
# token and a plain list of values can't build one. Reuse is tested apart,
# since it is the one failure that writes.
UNUSABLE_REFRESH_TOKENS = [
    pytest.param("missing", id="missing"),
    pytest.param("empty", id="empty"),
    pytest.param("unknown", id="unknown"),
    pytest.param("expired", id="expired"),
    pytest.param("inactive-user", id="inactive-user"),
]

# Every way a password change is refused, each with the field it replaces in
# the otherwise valid input and the message the user sees. The wrong current
# password is valid as a password, so the refusal comes from the service's
# check against the stored hash, not from the schema.
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


@pytest.fixture
def lookup_calls(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Spy on the auth service's user lookup and return the ids it receives.

    The auth service imported ``get_user_by_id`` by name, which copied it
    into its own namespace, and that copy is what it calls. So the spy
    replaces it there: patching the users service instead would leave the
    auth service calling the real function, and the list would stay empty
    whatever happened. The spy records each id, then runs the real lookup
    and returns its result, so the code under test behaves exactly as
    usual. ``monkeypatch`` puts the real function back after the test.

    The list is returned before any lookup happens and filled in as the
    test runs, so the test reads it after acting: ``[]`` means no lookup,
    ``[user.id]`` means exactly one, for that id.

    Args:
        monkeypatch: pytest's patching fixture; undoes the patch afterwards.

    Returns:
        The list the spy appends each looked-up id to, in call order.
    """
    calls: list[uuid.UUID] = []
    real_get_user_by_id = service.get_user_by_id

    def spy(session: Session, user_id: uuid.UUID) -> User | None:
        """Record the id being looked up, then run the real lookup."""
        calls.append(user_id)
        return real_get_user_by_id(session, user_id)

    monkeypatch.setattr(service, "get_user_by_id", spy)
    return calls


def _save_refresh_token(db_session: Session, user: User, **overrides: object) -> str:
    """Save a refresh token for a user and return its raw value.

    The row stores only the hash, as the service does, and the raw value
    is returned because that is what a client presents from its cookie.
    Overrides let a test save a token that is already revoked or expired.

    Args:
        db_session: The test's session; the row is flushed, not committed.
        user: The saved user who owns the token.
        **overrides: Columns to set, such as ``expires_at`` or ``revoked_at``.

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
    this saves the replacement first, then the old token with both
    ``revoked_at`` and ``replaced_by_id`` set. Presenting the old token again
    is reuse: only a rotated token coming back proves a copy exists. A token
    revoked any other way, by sign-out or a password change, has no
    replacement, so it can't stand in for reuse.

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

    ``missing`` and ``empty`` are what arrives without a usable cookie, and
    ``unknown`` is a well-formed token that was never saved. ``expired``
    and ``inactive-user`` save a real token, so the failure comes from the
    expiry or the account and not from the lookup. An unrecognized name
    raises instead of returning None, so a typo can't quietly turn a case
    into ``missing``.

    Args:
        db_session: The test's session.
        user: The saved user who owns any token created here.
        case: One of the ids in ``UNUSABLE_REFRESH_TOKENS``.

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

    ``populate_existing`` makes the query overwrite any copy of the row the
    session already holds, so the test sees the values in the database
    rather than a stale object. Without it, a bulk UPDATE such as
    ``revoke_all_for_user`` could leave an earlier copy showing old values.

    Args:
        db_session: The test's database session.
        raw_token: The raw refresh token, as returned by
            ``_save_refresh_token`` or ``service.refresh``.

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
    result = service.login(db_session, user.email, PASSWORD)

    assert decode_access_token(result.access_token) == user.id


def test_login_stores_only_the_hash_of_the_refresh_token(db_session: Session, user: User) -> None:
    """Sign-in saves exactly one token row, holding the hash, not the token.

    The stored hash must equal the hash of the token the client receives,
    because refreshing will look the row up that way. The table is read
    without a filter, so a token saved for the wrong user would be caught.
    """
    result = service.login(db_session, user.email, PASSWORD)

    tokens = db_session.scalars(select(RefreshToken)).all()

    assert len(tokens) == 1
    token = tokens[0]

    assert token.token_hash == hash_refresh_token(result.refresh_token)
    assert token.token_hash != result.refresh_token
    assert token.user_id == user.id


def test_login_sets_the_refresh_token_to_expire_after_the_configured_days(
    db_session: Session,
    user: User,
) -> None:
    """The refresh token expires the configured number of days after sign-in.

    The lifetime comes from the settings, so the test holds whatever value
    the environment configures.
    """
    before = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    service.login(db_session, user.email, PASSWORD)
    after = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    token = db_session.scalar(select(RefreshToken).where(RefreshToken.user_id == user.id))

    assert before <= token.expires_at <= after


def test_login_records_the_sign_in_time(db_session: Session, user: User) -> None:
    """A successful sign-in sets ``last_login_at`` to the current time.

    The user is refreshed, so the value checked is the one in the database.
    """
    before = datetime.now(UTC)
    service.login(db_session, user.email, PASSWORD)
    db_session.refresh(user)
    after = datetime.now(UTC)

    assert user.last_login_at is not None
    assert before <= user.last_login_at <= after


def test_login_ignores_email_case_and_surrounding_spaces(db_session: Session, user: User) -> None:
    """An email typed in mixed case with spaces around it still signs the user in."""
    result = service.login(db_session, "   Test@Example.COM   ", PASSWORD)

    assert decode_access_token(result.access_token) == user.id


def test_a_user_who_must_change_their_password_can_still_log_in(db_session: Session) -> None:
    """A user with a temporary password can sign in.

    They need a session to choose a new password; the API, not sign-in,
    blocks their other requests until they do. The flag is set explicitly
    so the test doesn't depend on the column's default.
    """
    user = make_user(password_hash=hash_password(PASSWORD), must_change_password=True)
    db_session.add(user)
    db_session.flush()

    result = service.login(db_session, user.email, PASSWORD)

    assert decode_access_token(result.access_token) == user.id


def test_each_login_issues_a_new_refresh_token(db_session: Session, user: User) -> None:
    """Two sign-ins create two rows with two different refresh tokens.

    A new sign-in never reuses or replaces an earlier token, so a user can
    stay signed in on several devices.
    """
    first_login = service.login(db_session, user.email, PASSWORD)
    second_login = service.login(db_session, user.email, PASSWORD)
    tokens = db_session.scalars(select(RefreshToken)).all()

    assert len(tokens) == 2
    assert first_login.refresh_token != second_login.refresh_token


@pytest.mark.parametrize(("email", "password", "is_active"), FAILED_LOGINS)
def test_a_failed_login_raises_the_generic_error(
    db_session: Session,
    email: str,
    password: str,
    is_active: bool,
) -> None:
    """Every kind of failed sign-in raises the same error with the same message.

    Wrong password, unknown email, and deactivated account must be
    indistinguishable, so a caller can't discover accounts or their state.
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

    The error is raised before anything is added, so nothing is written
    even though the service would otherwise commit.
    """
    user = make_user(password_hash=hash_password(PASSWORD), is_active=is_active)
    db_session.add(user)
    db_session.flush()

    with pytest.raises(AuthenticationError):
        service.login(db_session, email, password)

    db_session.refresh(user)
    tokens = db_session.scalars(select(RefreshToken)).all()

    assert len(tokens) == 0
    assert user.last_login_at is None


def test_an_unknown_email_still_runs_the_password_check(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown email still goes through the password check, with no hash.

    ``check_password`` is replaced where the service looks it up, and the
    spy records one call with None: the path that verifies against the
    dummy hash, so an unknown email takes as long as a wrong password. The
    cost of that path is tested in ``test_security.py``.
    """
    calls: list[str | None] = []
    real_check = service.check_password

    def spy(password: str, password_hash: str | None) -> bool:
        """Record the hash being checked, then run the real check."""
        calls.append(password_hash)
        return real_check(password, password_hash)

    monkeypatch.setattr(service, "check_password", spy)

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


def test_change_password_returns_a_working_session(db_session: Session, user: User) -> None:
    """The change returns a new session for the device that made it.

    The new refresh token belongs to the user, escapes the revocation of
    the old tokens, and expires the configured number of days after the
    change: a fresh window, checked from both sides so a longer lifetime
    fails too. The access token names the user.
    """
    before = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    issued_tokens = service.change_password(db_session, user, _password_change())
    after = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

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
