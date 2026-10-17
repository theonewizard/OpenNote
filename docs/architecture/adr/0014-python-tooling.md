# ADR-0014: Python tooling: venv, pip, pinned requirements

Status: Proposed  
Date: 2026-10-17  
Deciders: Flemming (pending review)

## Context
`CLAUDE.md` §3 mandates a repository-local `.venv` used through `.venv/bin/python|pip|pytest` and dependencies in `requirements.txt`; §20 discourages new tools without need.

## Decision
- Repository-root `.venv` (as in `CLAUDE.md` §3) created with `python -m venv`; dependency files live in `backend/` (design §15.4): `requirements.txt` (runtime) and `requirements-dev.txt` (`-r requirements.txt` + test/lint tools) with exact `==` pins.
- `pyproject.toml` holds project metadata and tool configuration only.
- Tools: `ruff` (lint + format), `mypy --strict`, `pytest` (+ `pytest-asyncio`, `hypothesis`, `schemathesis`), `pip-audit`, `bandit`.
- Upgrades: a scheduled CI job (Dependabot/Renovate) opens PRs; no broad upgrades inside feature work (`CLAUDE.md` §20).

## Consequences
Matches `CLAUDE.md` exactly. No hash-locked transitive lock file; if reproducibility issues appear, `pip-compile` can be added later with an ADR.
