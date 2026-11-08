"""Tests for the ``create-admin`` command, run the way a person runs it.

Typer's ``CliRunner`` runs the command in this process with the options
and typed input each test gives it, and collects its exit code and what it
printed; ``result.output`` holds both streams together, as the screen
would show them. Every test but the crash test puts
``contextmanager(get_test_db)`` in place of the module's ``SessionLocal``,
so the command gets the test's session and ends it as it ends its own:
what the test set up is committed first, and whatever the command didn't
commit is rolled back. Without that replacement, the command's first query
would go to the development database, which the suite refuses.

The tests cover a successful run, with the email and name given as options
or typed at the prompts; a short password and a name holding NUL, each
refused by field without showing what was typed, with nothing saved; the
refusal while an active Admin exists; and a crash, whose traceback must
not show the typed password. The rules underneath are tested where they
live: the service's in ``tests/test_user_service.py``, and the schema's in
``tests/test_user_schemas.py``.
"""

# Python's hidden-input prompt, which Click calls; the crash test answers it.
import getpass

# The command line and the exception hook, which the crash test sets and calls.
import sys

# Type of the get_test_db fixture: a function that returns the session's generator.
from collections.abc import Callable

# Return type of that generator.
from collections.abc import Iterator

# Turns get_test_db's generator into the context manager that SessionLocal() must return.
from contextlib import contextmanager

# A context manager that hands out None; the crash test's command never reaches a database.
from contextlib import nullcontext

# Test framework: monkeypatch, raises, and capsys, which captures what Typer prints.
import pytest

# Builds the active Admin whose presence makes the command refuse.
from factories import make_user

# The database error the crash test's stand-in service raises.
from sqlalchemy.exc import SQLAlchemyError

# Type of the db_session fixture.
from sqlalchemy.orm import Session

# Runs a Typer command in this process with given arguments and typed input.
from typer.testing import CliRunner

# The module under test: its Typer app, and the names the tests replace in it.
from app import cli

# The role enum; the saved account must be an Admin.
from app.core.permissions import Role

# The repository's exact-email lookup; reads back what the command saved.
from app.modules.users.repository import get_user_by_email

# The README's example address: example.com is reserved for examples, so email-validator takes it.
ADMIN_EMAIL = "admin@example.com"
ADMIN_FULL_NAME = "super user"


def test_create_admin_creates_an_admin_and_prints_its_email(
    db_session: Session,
    get_test_db: Callable[[], Iterator[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid input creates an Admin, prints its email, and saves it.

    The Admin is found afterwards only because the command committed it:
    ``get_test_db`` rolls back whatever the command left uncommitted when
    its ``with`` block ends, as closing a real session would.
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
    """An 11-character password is refused with the rule, never shown, and nothing is saved.

    The command prints the rule rather than Pydantic's message, which would
    give the typed password's length, and prints only each error's field
    and message, because Pydantic's whole error holds the rejected input.
    The test password is a string that can't appear in the output by
    chance, so its absence shows that neither the prompt nor the error
    printed it.
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
    database error. A real command line can't carry NUL in an option, so
    the name comes through the prompt.
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
    """With an active Admin already committed, the command exits with code 1 and says why.

    ``make_user``'s default account is an Admin, active by the column's
    default, committed as an earlier run of the command would have left
    it. The message is the service's ``ConflictError``, printed as it is.
    """
    monkeypatch.setattr(cli, "SessionLocal", contextmanager(get_test_db))

    existing_admin = make_user()
    db_session.add(existing_admin)
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
    """Without options, the command asks for the email and name, then creates the Admin.

    The typed lines answer the prompts in order: the email, the name, and
    the password twice.
    """
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
        """Fail as the service does when the database can't be reached.

        Args:
            *args: The session and the validated input, ignored.

        Raises:
            SQLAlchemyError: Always, with a message like the driver's.
        """
        raise SQLAlchemyError("connection to server failed: Connection refused")

    monkeypatch.setattr(cli, "create_first_admin", fail_like_an_unreachable_database)
    monkeypatch.setattr(
        sys,
        "argv",
        ["app.cli", "create-admin", "--email", ADMIN_EMAIL, "--full-name", ADMIN_FULL_NAME],
    )
    # Typer replaces sys.excepthook when it runs; monkeypatch puts the original back afterward.
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)

    with pytest.raises(SQLAlchemyError) as exc_info:
        cli.app()
    sys.excepthook(exc_info.type, exc_info.value, exc_info.tb)

    output = capsys.readouterr()
    assert "Connection refused" in output.err
    assert typed_password not in output.out + output.err
