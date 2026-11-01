"""The shared compatibility corpus at the repository root (tests/compatibility/vaults)."""

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

CORPUS = Path(__file__).resolve().parents[3] / "tests" / "compatibility" / "vaults"


@dataclass(frozen=True)
class Case:
    path: Path

    @property
    def name(self) -> str:
        return self.path.name

    def note_bytes(self) -> bytes:
        return (self.path / "note.md").read_bytes()

    @cached_property
    def expected(self) -> dict[str, Any]:
        return json.loads((self.path / "expected.json").read_text(encoding="utf-8"))


def corpus_cases(*, with_valid_frontmatter: bool = False) -> list[Case]:
    cases = [Case(p) for p in sorted(CORPUS.iterdir()) if (p / "note.md").is_file()]
    if with_valid_frontmatter:
        cases = [c for c in cases if c.expected.get("frontmatter")]
    return cases


def case_ids(cases: list[Case]) -> list[str]:
    return [c.name for c in cases]


def vault_cases() -> list[Path]:
    """Corpus cases that hold a whole vault tree (`<case>/vault/`)."""
    return [p for p in sorted(CORPUS.iterdir()) if (p / "vault").is_dir()]
