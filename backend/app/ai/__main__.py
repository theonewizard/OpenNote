"""`python -m app.ai`: switch AI on or off for a vault, or embed it now.

    python -m app.ai enable <vault-id> [--allow-external]
    python -m app.ai disable <vault-id>
    python -m app.ai embed <vault-id>

Until the API has AI settings, this is how an operator opts a vault in.
"""

import argparse
import sys
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.config import load_ai_settings
from app.ai.embeddings import embed_vault, set_vault_ai
from app.core.config import SettingsError, load_settings
from app.core.db import make_sync_engine
from app.core.logging import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai")
    commands = parser.add_subparsers(dest="command", required=True)
    enable = commands.add_parser("enable", help="switch AI on for a vault")
    enable.add_argument(
        "--allow-external",
        action="store_true",
        help="also allow a provider outside the local network to receive this vault's notes",
    )
    commands.add_parser("disable", help="switch AI off for a vault and drop its embeddings")
    commands.add_parser("embed", help="bring the vault's embeddings up to date now")
    for command in commands.choices.values():
        command.add_argument("vault_id", type=uuid.UUID)
    args = parser.parse_args(argv)
    try:
        settings, ai = load_settings(), load_ai_settings()
    except SettingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    configure_logging(settings.log_level, stream=sys.stderr)
    engine = make_sync_engine(settings)
    try:
        if args.command == "embed":
            done = embed_vault(engine, args.vault_id, ai)
            print(
                "busy: another run holds this vault" if done is None else f"embedded {done} notes"
            )
            return 0 if done is not None else 2
        with Session(engine) as session:
            try:
                set_vault_ai(
                    session,
                    args.vault_id,
                    enabled=args.command == "enable",
                    allow_external=getattr(args, "allow_external", False),
                )
                session.commit()
            except IntegrityError:  # the vault_id foreign key
                print(f"error: no vault {args.vault_id}", file=sys.stderr)
                return 1
        print(f"AI {args.command}d for vault {args.vault_id}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
