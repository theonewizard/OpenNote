
## Follow-up: OpenAPI drift after #82 and #53 (2026-11-20)

- Flemming merged #82 (Swift nullable fix in the OpenAPI export) and #53 (rename endpoint) within seconds of each other. Each was green alone, but #82's export rewrites the nullable `If-Match` header that #53 added, so main's committed contract drifted. Branch `fix/openapi-drift-after-53` is the output of `make openapi` on main (be71a26); no backend change.
