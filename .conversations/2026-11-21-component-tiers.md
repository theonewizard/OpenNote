# Component map by tier and split actions (2026-11-21)

Thread: Map components into frontend, middleware, backend. Requested by Flemming.

## Prompts

- Flemming: "Create a diagram in drawio of the components and split them into Frontend middleware and backend compoents. If they are not split today make a list of actions to be planned for splitting them up"

## Output

- `docs/architecture/opennote-components.drawio`: components of main 2f14f9a grouped into Frontend, Middleware and Backend, with runtime connections and the boundary violations drawn in red (V2 to V5).
- `docs/architecture/tier-split-actions.md`: verdict (split at deployment level and between clients and server; not split inside `backend/app`), findings V1 to V9 with evidence, target layering and planned actions A0 to A8.
- No code changed. One finding is a functional gap, not only structure: AI and OCR jobs are enqueued only on REST writes, never on sync pushes or watcher ingests (V5, action A1).
