# 2026-11-14 — Phase 8: disaster recovery (P8-05)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Done in the "Finish Phase 8 production hardening" thread. P8-04, P8-06 and P8-08 belong to the "Harden deployment and releases" thread (rulings R-P8-001 to R-P8-032); this thread's rulings start at R-P8-100 so the two never collide.

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-14 00:53 | Flemming | Start the development phase 5,6 8 using ubi 10 |
| 2026-11-14 00:53 | Coordinator | Phase 8 thread: the remaining Phase 8 items per `docs/ROADMAP.md`, on UBI 10. P8-04, P8-06 and P8-08 are done in the "Harden deployment and releases" thread, which is also moving all four images to `ubi10/ubi-minimal:10.3` (PR #51): build on top of it once it merges. RHEL 10 needs an x86-64-v3 CPU. Phases 5 and 6 have threads of their own. |

## Scope

Remaining Phase 8 items: P8-01 (performance), P8-02 (security testing), P8-03 (accessibility), P8-05 (disaster recovery), P8-07 (documentation), P8-09 (beta). Done here as one pull request each. Not done by this thread, because they need Flemming or Phase 5: the external security review (P8-02), VoiceOver testing on Apple hardware (P8-03), benchmark numbers on the reference hardware of testing-strategy §6 (P8-01), and the beta program (P8-09, after M5 and P8-01 to P8-08).

## Rulings

### P8-05 disaster recovery (branch `feature/disaster-recovery`)

- R-P8-110: the "rebuild procedure in P8" of architecture plan §5.2 is `python -m app.sync.rebuild` (`app/sync/rebuild.py`): per vault in the history root, one transaction writes `vaults`, every `revisions` row from the JSONL log, `vault_seq`, `files` at each file's last logged revision, and the derived index. The index is built from the history bytes of those revisions (`rebuild_index` gained an optional `read`), not from the folder, so the rebuilt rows are exactly the logged state even when the folder has moved on; the folder's newer state then arrives as ordinary commits.
- R-P8-111: `files.written_revision` is set to the revision itself. Recovery and the watcher therefore treat any difference between the folder and the log as an edit made outside OpenNote and commit it (device `server-fs`); nothing in a folder is overwritten with older history. Tested: an edit and a new file made while the database was down become revisions 2 and 1.
- R-P8-112: finding a vault's folder: `--map VAULT_ID=FOLDER`, else the folder whose `.opennote/config.json` names the id, else the direct child of the vault root holding at least 90 % of the log's live files (sampled, at most 200). Vaults created through the API with the default folder are direct children without a config, so the file match covers them; anything else is skipped with a message asking for `--map`. Vaults already in the database are skipped, so the tool can be repeated; `--dry-run` prints the plan.
- R-P8-113: what only the database held is not invented: users, devices, tokens, sessions, memberships, vault settings, `client_ops`, conflicts and the audit log. `--owner USERNAME` makes an existing user the owner of every rebuilt vault, enough for an administrator to add members back. A repeated sequence number in the log is refused (HistoryCorrupt); every history object is checked against its hash while its size is read.
- R-P8-114: verified locally with P8-04's drill helper (from PR #40's branch): seed, fingerprint, drop and re-create the database, rebuild, fingerprint again: identical, and `verify` passed; the API then served the vault, its notes and search. The same drill joins `scripts/backup-drill.sh` in CI after PR #40 is merged (it is not on `main` yet).
