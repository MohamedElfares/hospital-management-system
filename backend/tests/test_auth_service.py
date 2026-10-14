import uuid
from datetime import UTC
from datetime import datetime
from datetime import timedelta

import pytest
from factories import make_user
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthenticationError
from app.core.security import create_access_token
from app.core.security import decode_access_token
from app.core.security import hash_password
from app.core.security import hash_refresh_token
from app.modules.auth import service
from app.modules.auth.models import RefreshToken
from app.modules.users.models import User

PASSWORD = "Correct-Password-1"
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
