"""`python -m app.ai`: switch AI on or off for a vault, embed it now, or ask Claude.

    python -m app.ai enable <vault-id> [--allow-external]
    python -m app.ai disable <vault-id>
    python -m app.ai embed <vault-id>
    python -m app.ai ask <vault-id> "<question>"

Until the API has AI settings, this is how an operator opts a vault in.
"""

import argparse
import asyncio
import difflib
import sys
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.ai.agent import AgentUnavailable, Answer, ask
from app.ai.config import AISettings, load_ai_settings
from app.ai.embeddings import embed_vault, set_vault_ai
from app.ai.providers import AIError
from app.core.config import Settings, SettingsError, load_settings
from app.core.db import engine_from_settings, make_sync_engine
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
    commands.add_parser("ask", help="ask Claude about the vault's notes (read and suggest)")
    for command in commands.choices.values():
        command.add_argument("vault_id", type=uuid.UUID)
    commands.choices["ask"].add_argument("question")
    args = parser.parse_args(argv)
    try:
        settings, ai = load_settings(), load_ai_settings()
    except SettingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    configure_logging(settings.log_level, stream=sys.stderr)
    if args.command == "ask":
        return asyncio.run(_ask(settings, ai, args.vault_id, args.question))
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


async def _ask(settings: Settings, ai: AISettings, vault_id: uuid.UUID, question: str) -> int:
    engine = engine_from_settings(settings)
    try:
        async with AsyncSession(engine) as db:
            answer = await ask(db, vault_id, question, ai)
    except AgentUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except AIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        await engine.dispose()
    print(_render(answer))
    return 0


def _render(answer: Answer) -> str:
    """The answer, its sources and each suggestion as a diff against the note Claude read.
    Nothing is applied: the user edits the note themselves."""
    if answer.refused:
        return answer.text
    lines = [answer.text, ""]
    if answer.uncited:
        lines.append("Note: this answer cites none of your notes; check it before relying on it.")
    lines += [f"Source: {c.path} ({c.note_id})" for c in answer.citations]
    for s in answer.suggestions:
        lines += ["", f"Suggested edit to {s.path} (revision {s.base_revision}): {s.reason}"]
        lines += difflib.unified_diff(
            s.original.splitlines(),
            s.content.splitlines(),
            f"{s.path} (revision {s.base_revision})",
            f"{s.path} (suggested)",
            lineterm="",
        )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
