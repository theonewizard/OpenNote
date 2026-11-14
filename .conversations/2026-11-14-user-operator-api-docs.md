# 2026-11-14 — User, operator and API documentation (P8-07)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Done in the "Phase 8 on UBI 10" thread; rulings R-P8-140..143.

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-14 | Flemming (via the coordinator) | "Start the development phase 5,6 8 using ubi 10". The coordinator scoped this thread to the Phase 8 items not owned by the deployment thread: P8-01, P8-02, P8-03, P8-05 and P8-07. |

## Rulings

- R-P8-140: three documents, one per reader: `docs/user-guide.md`, `docs/deployment/operator-guide.md` (Compose on one host; Kubernetes stays in `kubernetes.md`) and `docs/api/using-the-api.md` (task-oriented, next to the OpenAPI reference and the API contract, which it links instead of repeating).
- R-P8-141: every `curl` flow in `using-the-api.md` was run against a local API before it was written down: sign-in returns `csrf_token`, `POST /tokens` returns the secret once, a PAT works only in `X-API-Key` (as a Bearer token it gets 401), `PUT /content` with `If-Match` gives 200 or 412 with `current`, and `/docs` is 404.
- R-P8-142: the user guide says plainly that the web app has no sign-in screen yet (P3-01 is not on `main`) and lists what is not there yet, instead of describing planned features (CLAUDE.md §7: document the system that exists).
- R-P8-143: the operator guide describes the UBI 10 images and the x86-64-v3 CPU requirement, so it is meant to merge after PR #51; it links `backup.md` (PR #40) and `disaster-recovery.md` (PR #59), which arrive with those PRs.

## Output

Branch `docs/user-operator-api`: the three documents, README links, ROADMAP P8-07 to TESTING.
