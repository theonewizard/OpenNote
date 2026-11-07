"""Server-side account administration (R-P2-007): how the first administrator is made.

    python -m app.auth.admin create-user [--admin] [--display-name NAME] USERNAME

The password is read from standard input (prompted without echo on a terminal), never
from the command line, where other users could see it.
"""

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.crypto import hash_password, username_key
from app.auth.models import User
from app.core.config import SettingsError, get_settings
from app.core.db import make_sync_engine

MIN_PASSWORD_LENGTH = 12


def create_user(
    session: Session, username: str, password: str, *, admin: bool, display_name: str | None
) -> User:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must have at least {MIN_PASSWORD_LENGTH} characters")
    key = username_key(username)
    if session.scalar(select(User).where(User.username_key == key)) is not None:
        raise ValueError("a user with this name exists")
    user = User(
        username=username,
        username_key=key,
        display_name=display_name or username,
        password_hash=hash_password(password),
        is_admin=admin,
    )
    session.add(user)
    session.flush()
    return user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.auth.admin")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="create a local account")
    create.add_argument("username")
    create.add_argument("--admin", action="store_true")
    create.add_argument("--display-name")
    args = parser.parse_args(argv)
    if sys.stdin.isatty():
        password = getpass.getpass("Password: ")
    else:
        password = sys.stdin.readline().removesuffix("\n")
    try:
        engine = make_sync_engine(get_settings())
    except SettingsError as exc:
        print(f"OpenNote cannot start: {exc}", file=sys.stderr)
        return 1
    try:
        with Session(engine) as session, session.begin():
            user = create_user(
                session, args.username, password, admin=args.admin, display_name=args.display_name
            )
            print(f"created user {user.username} ({user.id})")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
