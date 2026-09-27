from contextlib import nullcontext

import pytest
from factories import make_user
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from app import cli
from app.core.permissions import Role
from app.modules.users.repository import get_by_email

ADMIN_EMAIL = "admin@example.com"
ADMIN_FULL_NAME = "super user"


def test_create_admin_creates_an_admin_and_prints_its_email(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid input creates an Admin, prints its email, and saves it.

    Each CLI test replaces ``SessionLocal`` so the command uses the test
    session; without that, it would write to the development database.
    """
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(db_session))

    result = CliRunner().invoke(
        cli.app,
        ["create-admin", "--email", ADMIN_EMAIL, "--full-name", ADMIN_FULL_NAME],
        input="Password@1331\nPassword@1331\n",
    )

    assert result.exit_code == 0
    assert ADMIN_EMAIL in result.output

    admin = get_by_email(db_session, ADMIN_EMAIL)

    assert admin is not None
    assert admin.role is Role.ADMIN


def test_create_admin_rejects_a_short_password_without_showing_it(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An 11-character password is refused with the rule, never echoed, and nothing is saved.

    The test password is a string that can't appear in the output by
    chance, so its absence proves the command didn't print it.
    """
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(db_session))

    result = CliRunner().invoke(
        cli.app,
        ["create-admin", "--email", ADMIN_EMAIL, "--full-name", ADMIN_FULL_NAME],
        input="short-pw-11\nshort-pw-11\n",
    )

    assert result.exit_code == 1
    assert "password: must be 12 to 128 characters." in result.output
    assert "short-pw-11" not in result.output
    assert get_by_email(db_session, ADMIN_EMAIL) is None


def test_create_admin_refuses_when_an_active_admin_exists(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With an active Admin already committed, the command exits with code 1 and says why."""
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(db_session))

    user = make_user()
    db_session.add(user)
    db_session.commit()

    result = CliRunner().invoke(
        cli.app,
        ["create-admin", "--email", ADMIN_EMAIL, "--full-name", ADMIN_FULL_NAME],
        input="Password@1331\nPassword@1331\n",
    )

    assert result.exit_code == 1
    assert "An active Admin already exists" in result.output


def test_create_admin_prompts_for_a_missing_email_and_name(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without options, the command asks for the email and name, then creates the Admin."""
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(db_session))

    result = CliRunner().invoke(
        cli.app,
        ["create-admin"],
        input=f"{ADMIN_EMAIL}\n{ADMIN_FULL_NAME}\nPassword@1331\nPassword@1331\n",
    )

    assert result.exit_code == 0
    assert ADMIN_EMAIL in result.output

    admin = get_by_email(db_session, ADMIN_EMAIL)

    assert admin is not None
    assert admin.role is Role.ADMIN
