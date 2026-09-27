"""Maintenance commands, run with ``python -m app.cli <command>``.

The CLI is an entry point, like a router: it collects input, opens a
database session, calls a service, and prints the outcome. It holds no
business rules. It connects with the same ``DATABASE_URL`` as the API, so
running it requires the database credentials, which is what makes
``create-admin`` safe without a sign-in. ``seed-demo`` and
``export-openapi`` join it in Milestone 1.7.

Example:
    ``uv run python -m app.cli create-admin --email admin@hospital.test --full-name "Ada Admin"``
"""

# Attaches Typer option settings to a parameter's type.
from typing import Annotated

# Builds the command-line interface from typed functions; also prompts and exits.
import typer

# Raised when UserCreate rejects the input.
from pydantic import ValidationError

# Parent of every domain error; each one's message is safe to print.
from app.core.errors import AppError

# The role given to the new account.
from app.core.permissions import Role

# Opens a database session from the configured DATABASE_URL.
from app.db.session import SessionLocal

# Validates the email, name, and password before anything is saved.
from app.modules.users.schemas import UserCreate

# The service that checks the rules and creates the first Admin.
from app.modules.users.service import create_first_admin

app = typer.Typer(help="Hospital Management System maintenance commands.")

# Replaces Pydantic's SecretStr wording ("at least 12 items ..., not 5"),
# which is confusing and echoes the length of what was typed.
_PASSWORD_RULE = "must be 12 to 128 characters."


@app.callback()
def main() -> None:
    """Group the maintenance commands under one program.

    Typer runs a lone command directly, which would make ``create-admin``
    an unexpected extra argument. A callback turns the app into a group of
    named commands, so ``python -m app.cli create-admin`` works and later
    commands can be added beside it.
    """


@app.command(help="Create the first Admin. The password is asked for twice and never shown.")
def create_admin(
    email: Annotated[str, typer.Option(prompt=True)],
    full_name: Annotated[str, typer.Option(prompt=True)],
) -> None:
    """Create the first Admin account from the terminal.

    There is no public sign-up, so on a new database nobody can sign in to
    create accounts; this command creates the first Admin directly. The
    email and full name may be given as options or typed when prompted.
    The password is only ever read from a hidden prompt, entered twice,
    and is deliberately not an option: a value passed on the command line
    would be saved in the shell's history.

    Validation errors are printed as field and message only, because
    Pydantic's full error includes the rejected input, which could be the
    password. The service refuses when an active Admin already exists.
    Every failure prints to stderr and exits with code 1 without saving
    anything.

    Args:
        email: Sign-in email for the new Admin.
        full_name: The Admin's display name.

    Raises:
        typer.Exit: With code 1 when the input is invalid or the service
            refuses.
    """
    password = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    try:
        data = UserCreate(
            email=email,
            full_name=full_name,
            password=password,
            role=Role.ADMIN,
        )
    except ValidationError as exc:
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"])
            message = _PASSWORD_RULE if field == "password" else error["msg"]
            typer.echo(f"{field}: {message}", err=True)
        raise typer.Exit(code=1)

    with SessionLocal() as session:
        try:
            admin = create_first_admin(session, data)
        except AppError as exc:
            typer.echo(exc.message, err=True)
            raise typer.Exit(code=1)

    typer.echo(f"Created Admin {admin.email} (id {admin.id})")


if __name__ == "__main__":
    app()
