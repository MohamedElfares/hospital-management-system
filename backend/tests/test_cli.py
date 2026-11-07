import getpass
import sys
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from contextlib import nullcontext

import pytest
from factories import make_user
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from app import cli
from app.core.permissions import Role
from app.modules.users.repository import get_user_by_email

ADMIN_EMAIL = "admin@example.com"
ADMIN_FULL_NAME = "super user"


def test_create_admin_creates_an_admin_and_prints_its_email(
    db_session: Session,
    get_test_db: Callable[[], Iterator[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid input creates an Admin, prints its email, and saves it.

    Each CLI test puts ``contextmanager(get_test_db)`` in place of
    ``SessionLocal``, so the command gets the test's session and ends it as
    it would end a real one: what the test set up is committed first, and
    whatever the command didn't commit is rolled back when its ``with``
    block ends. The Admin is still found afterwards only because the
    command committed it. Without the replacement, the command would try
    to connect to the development database, which the suite refuses.
    """
    monkeypatch.setattr(cli, "SessionLocal", contextmanager(get_test_db))

    result = CliRunner().invoke(
        cli.app,
        ["create-admin", "--email", ADMIN_EMAIL, "--full-name", ADMIN_FULL_NAME],
        input="Correct-Password-1\nCorrect-Password-1\n",
    )

    assert result.exit_code == 0
    assert ADMIN_EMAIL in result.output

    admin = get_user_by_email(db_session, ADMIN_EMAIL)

    assert admin is not None
    assert admin.role is Role.ADMIN


def test_create_admin_rejects_a_short_password_without_showing_it(
    db_session: Session,
    get_test_db: Callable[[], Iterator[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An 11-character password is refused with the rule, never echoed, and nothing is saved.

    The test password is a string that can't appear in the output by
    chance, so its absence proves the command didn't print it.
    """
    monkeypatch.setattr(cli, "SessionLocal", contextmanager(get_test_db))

    result = CliRunner().invoke(
        cli.app,
        ["create-admin", "--email", ADMIN_EMAIL, "--full-name", ADMIN_FULL_NAME],
        input="short-pw-11\nshort-pw-11\n",
    )

    assert result.exit_code == 1
    assert "password: must be 15 to 128 characters." in result.output
    assert "short-pw-11" not in result.output
    assert get_user_by_email(db_session, ADMIN_EMAIL) is None


def test_create_admin_rejects_a_control_character_in_the_name(
    db_session: Session,
    get_test_db: Callable[[], Iterator[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A NUL typed at the name prompt is refused as invalid input, and nothing is saved.

    PostgreSQL can't store NUL, so a name holding one must be refused by
    validation, with the field named, rather than end the command with a
    database error. A command-line option can't carry NUL, so the name
    comes through the prompt.
    """
    monkeypatch.setattr(cli, "SessionLocal", contextmanager(get_test_db))

    result = CliRunner().invoke(
        cli.app,
        ["create-admin", "--email", ADMIN_EMAIL],
        input="Ana\x00Smith\nCorrect-Password-1\nCorrect-Password-1\n",
    )

    assert result.exit_code == 1
    assert "full_name: Value error, must not contain control characters" in result.output
    assert get_user_by_email(db_session, ADMIN_EMAIL) is None


def test_create_admin_refuses_when_an_active_admin_exists(
    db_session: Session,
    get_test_db: Callable[[], Iterator[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With an active Admin already committed, the command exits with code 1 and says why."""
    monkeypatch.setattr(cli, "SessionLocal", contextmanager(get_test_db))

    user = make_user()
    db_session.add(user)
    db_session.commit()

    result = CliRunner().invoke(
        cli.app,
        ["create-admin", "--email", ADMIN_EMAIL, "--full-name", ADMIN_FULL_NAME],
        input="Correct-Password-1\nCorrect-Password-1\n",
    )

    assert result.exit_code == 1
    assert "An active Admin already exists" in result.output


def test_create_admin_prompts_for_a_missing_email_and_name(
    db_session: Session,
    get_test_db: Callable[[], Iterator[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without options, the command asks for the email and name, then creates the Admin."""
    monkeypatch.setattr(cli, "SessionLocal", contextmanager(get_test_db))

    result = CliRunner().invoke(
        cli.app,
        ["create-admin"],
        input=f"{ADMIN_EMAIL}\n{ADMIN_FULL_NAME}\nCorrect-Password-1\nCorrect-Password-1\n",
    )

    assert result.exit_code == 0
    assert ADMIN_EMAIL in result.output

    admin = get_user_by_email(db_session, ADMIN_EMAIL)

    assert admin is not None
    assert admin.role is Role.ADMIN


def test_create_admin_crash_output_never_shows_the_typed_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A database failure after the prompt prints a traceback without the typed password.

    The command runs through ``cli.app()``, the entry point that
    ``python -m app.cli`` uses, because ``CliRunner`` skips Typer's own
    error handling. The service fails the way an unreachable database does,
    and the uncaught error goes to the hook Typer installs, as Python would
    send it there. The password is still a local variable of the command at
    that moment, so a traceback that showed local variables would print it.
    """
    typed_password = "TypedSecretPassword"
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": typed_password)
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(None))

    def fail_like_an_unreachable_database(*args: object) -> None:
        """Raise a database error, as SQLAlchemy does when the database can't be reached."""
        raise SQLAlchemyError("connection to server failed: Connection refused")

    monkeypatch.setattr(cli, "create_first_admin", fail_like_an_unreachable_database)
    monkeypatch.setattr(
        sys,
        "argv",
        ["app.cli", "create-admin", "--email", ADMIN_EMAIL, "--full-name", ADMIN_FULL_NAME],
    )
    # Typer replaces sys.excepthook when it runs; monkeypatch puts the original back afterward.
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)

    with pytest.raises(SQLAlchemyError) as crash:
        cli.app()
    sys.excepthook(crash.type, crash.value, crash.tb)

    output = capsys.readouterr()
    assert "Connection refused" in output.err
    assert typed_password not in output.out + output.err
