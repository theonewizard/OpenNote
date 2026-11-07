# 2026-11-07 — Apple core packages (P4-01, P4-02, P4-04)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Several threads work in parallel since 2026-11-07, so this record numbers its rulings W1-1, W1-2, … (workstream 1) instead of continuing the shared R sequence, which would collide.

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-07 15:01 | Flemming (project chat) | "Run most of the phases in parallel so it is developed quickly." |
| 2026-11-07 15:03 | Coordinator (thread "Build Apple core packages") | Workstream 1 of the parallel plan: P4-01 parser parity, P4-02 Storage, P4-04 TextKit editor in `apple/Packages`; depends only on Phase 1; Core and Storage build on Linux, the editor needs the macOS runners |

## Rulings

- W1-1: the Python parsers are the reference. Beyond the corpus, `backend/tests/compatibility/parity.py` generates `tests/compatibility/parity/{frontmatter,paths,extraction}.json` from the Python code and a backend test fails when they drift; the Swift tests read the same files. Cost if wrong: one generator and three JSON files to delete.
- W1-2: frontmatter YAML is parsed with Yams 6.2.2 (already in the graph through swift-openapi-generator) and plain scalars are resolved in Swift by ruamel.yaml's YAML 1.2 rules rather than Yams's own resolver, whose YAML 1.1 rules (`yes`, `on`) and `Date` values differ from Python. Cost if wrong: one file.
- W1-3: code and HTML blocks are masked using swift-cmark 0.9.0 (plain CommonMark, no GFM extensions) rather than a hand-written block scanner; indented code and HTML block rules depend on paragraph and list context that a scanner would get wrong. swift-markdown was not used: it adds the swift-docc-plugin dependency and GFM extensions by default. Cost if wrong: one function.
- W1-4: `renameat2`, `renamex_np` and `F_FULLFSYNC` are reached through a small C target (`CFileSwap`) because Swift's Glibc overlay does not declare `renameat2`; the system SQLite through a `systemLibrary` target (`libsqlite3-dev` installed in the Linux CI job). Cost if wrong: two tiny targets.
- W1-5: Swift metadata editing (the YAML splice) and the sync state (bases, outbox, cursor) are left out: the first is not in P4-01's acceptance and no UI calls it yet, the second belongs to P5-03. Cost if wrong: they are added when first needed.
- W1-6: where Python raises instead of answering (impossible dates, explicit YAML tags), Swift answers safely (`frontmatter_error`, the scalar's text) and the parity fixture leaves those inputs out; the Python behaviour is reported to the Phase 2 thread rather than changed here, to keep this workstream out of `backend/app`.

## Output

Branch `feature/apple-core` in `.worktrees/apple-core/`: one pull request to `main`. Plan and limits: [docs/superpowers/plans/2026-11-07-apple-core-packages-plan.md](../docs/superpowers/plans/2026-11-07-apple-core-packages-plan.md).
