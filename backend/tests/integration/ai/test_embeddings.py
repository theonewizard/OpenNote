"""The embedding pipeline against the real database: off until the vault opts in,
incremental per chunk, cleaned up on delete and disable, one run per vault at a time."""

import hashlib
import subprocess
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.ai import embeddings, jobs
from app.ai.config import AISettings
from app.ai.embeddings import embed_vault, set_vault_ai
from app.ai.models import AIChunk, AINoteState
from app.notes.index import rebuild_index
from app.notes.models import File
from app.vaults.registry import open_vault
from tests.integration.test_index_rebuild import add_files

BACKEND_DIR = Path(__file__).resolve().parents[3]
LOCAL = AISettings(provider="ollama", base_url="http://127.0.0.1:11434", embed_model="m1")
EXTERNAL = AISettings(provider="openai", base_url="https://api.example.com/v1", embed_model="m1")


class FakeProvider:
    """Deterministic 3-dimensional vectors; records every text it was asked to embed."""

    name = "fake"

    def __init__(self, external: bool) -> None:
        self.external = external
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str], model: str) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(t)), float(len(model)), 1.0] for t in texts]

    def generate(self, prompt: str, *, system: str, model: str) -> str:
        raise NotImplementedError

    @property
    def embedded(self) -> list[str]:
        return [t for call in self.calls for t in call]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    provider = FakeProvider(external=False)

    def from_settings(settings: AISettings) -> FakeProvider | None:
        if settings.provider == "none":
            return None
        provider.external = settings.external
        return provider

    monkeypatch.setattr(embeddings, "provider_from_settings", from_settings)
    return provider


@pytest.fixture
def vault(obsidian_vault: Path, session: Session) -> uuid.UUID:
    (obsidian_vault / "Long.md").write_text(
        "---\ntitle: Long note\n---\nintro\n\n# One\nfirst\n\n# Two\nsecond\n"
    )
    vault_id = open_vault(session, obsidian_vault)
    add_files(session, vault_id, obsidian_vault)
    rebuild_index(session, vault_id, obsidian_vault)
    session.commit()
    return vault_id


def chunks(session: Session, path: str) -> list[tuple[int, str, list[float]]]:
    session.rollback()  # see the pipeline's commits
    rows = session.execute(
        select(AIChunk.ordinal, AIChunk.text, AIChunk.embedding)
        .join(File, File.file_id == AIChunk.file_id)
        .where(File.path == path)
        .order_by(AIChunk.ordinal)
    )
    return [tuple(r) for r in rows]


def edit(session: Session, root: Path, path: str, content: str) -> None:
    """Change a note on disk and in `files`, as a commit would."""
    (root / path).write_text(content)
    file = session.scalars(select(File).where(File.path == path)).one()
    file.content_hash = "sha256:" + hashlib.sha256(content.encode()).hexdigest()
    session.commit()


def enable(session: Session, vault_id: uuid.UUID, **kw: bool) -> None:
    set_vault_ai(session, vault_id, enabled=True, **kw)
    session.commit()


def test_nothing_is_embedded_unless_server_and_vault_opt_in(engine, session, vault, fake):
    assert embed_vault(engine, vault, LOCAL) == 0  # vault not enabled
    enable(session, vault)
    assert embed_vault(engine, vault, AISettings()) == 0  # server has no provider
    assert embed_vault(engine, vault, LOCAL.model_copy(update={"embed_model": None})) == 0
    assert fake.calls == []
    assert session.scalar(select(func.count()).select_from(AIChunk)) == 0


def test_an_external_provider_needs_the_vaults_allow_external(engine, session, vault, fake):
    enable(session, vault)
    assert embed_vault(engine, vault, EXTERNAL) == 0
    assert fake.calls == []
    enable(session, vault, allow_external=True)
    assert embed_vault(engine, vault, EXTERNAL) == 4


def test_notes_are_chunked_and_stored_as_vectors(engine, session, vault, fake):
    enable(session, vault)
    assert embed_vault(engine, vault, LOCAL) == 4  # Long, Plan, Welcome, #hashtag note
    rows = chunks(session, "Long.md")
    assert [(o, t) for o, t, _ in rows] == [(0, "intro"), (1, "# One\nfirst"), (2, "# Two\nsecond")]
    assert rows[1][2] == [float(len("Long note\n\n# One\nfirst")), 2.0, 1.0]
    assert "Long note\n\nintro" in fake.embedded  # the title goes in front of each chunk
    assert session.scalar(text("SELECT vector_dims(embedding) FROM ai_chunks LIMIT 1")) == 3


def test_a_second_run_embeds_nothing_and_an_edit_only_its_chunk(
    engine, session, vault, fake, obsidian_vault
):
    enable(session, vault)
    embed_vault(engine, vault, LOCAL)
    fake.calls.clear()
    assert embed_vault(engine, vault, LOCAL) == 0
    assert fake.calls == []

    edit(
        session,
        obsidian_vault,
        "Long.md",
        "---\ntitle: Long note\n---\nintro\n\n# One\nNEW\n\n# Two\nsecond\n",
    )
    assert embed_vault(engine, vault, LOCAL) == 1
    assert fake.embedded == ["Long note\n\n# One\nNEW"]
    assert [t for _, t, _ in chunks(session, "Long.md")] == ["intro", "# One\nNEW", "# Two\nsecond"]


def test_a_new_model_re_embeds_everything(engine, session, vault, fake):
    enable(session, vault)
    embed_vault(engine, vault, LOCAL)
    fake.calls.clear()
    assert embed_vault(engine, vault, LOCAL.model_copy(update={"embed_model": "model-2"})) == 4
    assert len(fake.embedded) == 6
    assert set(session.scalars(select(AINoteState.model))) == {"model-2"}


def test_deleted_notes_lose_their_chunks_and_disable_drops_all(engine, session, vault, fake):
    enable(session, vault)
    embed_vault(engine, vault, LOCAL)
    session.scalars(select(File).where(File.path == "Long.md")).one().deleted = True
    session.commit()
    embed_vault(engine, vault, LOCAL)
    assert chunks(session, "Long.md") == []
    assert session.scalar(select(func.count()).select_from(AIChunk)) > 0

    set_vault_ai(session, vault, enabled=False, allow_external=True)
    session.commit()
    assert session.scalar(select(func.count()).select_from(AIChunk)) == 0
    assert session.scalar(select(func.count()).select_from(AINoteState)) == 0
    assert session.execute(text("SELECT enabled, allow_external FROM ai_vault_settings")).one() == (
        False,
        False,
    )


def test_a_note_missing_on_disk_is_skipped(engine, session, vault, fake, obsidian_vault):
    enable(session, vault)
    (obsidian_vault / "Long.md").unlink()
    assert embed_vault(engine, vault, LOCAL) == 3
    assert chunks(session, "Long.md") == []


def test_only_one_run_per_vault(engine: Engine, session, vault, fake):
    enable(session, vault)
    key = int.from_bytes(vault.bytes[:8], signed=True)
    with engine.connect() as other:
        other.execute(select(func.pg_advisory_lock(key)))
        assert embed_vault(engine, vault, LOCAL) is None
        other.execute(select(func.pg_advisory_unlock(key)))
    assert embed_vault(engine, vault, LOCAL) == 4


def test_the_job_retries_later_when_the_vault_is_busy(monkeypatch, vault):
    sent = []
    monkeypatch.setattr(jobs, "embed_vault", lambda *args: None)
    monkeypatch.setattr(jobs, "_engine", lambda: None)
    monkeypatch.setattr(jobs, "get_ai_settings", lambda: LOCAL)
    monkeypatch.setattr(jobs.embed_vault_job, "send_with_options", lambda **kw: sent.append(kw))
    jobs.embed_vault_job(str(vault))
    assert sent == [{"args": (str(vault),), "delay": jobs.BUSY_DELAY_MS}]


def run_cli(pg_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - arguments come from the tests below
        [sys.executable, "-m", "app.ai", *args],
        cwd=BACKEND_DIR,
        env={"PATH": "/usr/bin:/bin", **_settings_env(pg_url)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _settings_env(pg_url: str) -> dict[str, str]:
    from tests.conftest import PLACEHOLDER_ENV

    return PLACEHOLDER_ENV | {"OPENNOTE_DATABASE_URL": pg_url}


def test_cli_enables_and_disables_a_vault(pg_url, session, vault):
    result = run_cli(pg_url, "enable", str(vault), "--allow-external")
    assert result.returncode == 0, result.stderr
    assert session.execute(text("SELECT enabled, allow_external FROM ai_vault_settings")).one() == (
        True,
        True,
    )
    assert run_cli(pg_url, "embed", str(vault)).stdout == "embedded 0 notes\n"  # AI off on server
    assert run_cli(pg_url, "disable", str(vault)).returncode == 0
    session.rollback()
    assert session.execute(text("SELECT enabled FROM ai_vault_settings")).scalar() is False


def test_cli_refuses_an_unknown_vault(pg_url, engine):
    result = run_cli(pg_url, "enable", str(uuid.uuid4()))
    assert result.returncode == 1
    assert result.stderr.startswith("error: no vault")
