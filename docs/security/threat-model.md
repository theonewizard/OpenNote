# Threat Model (baseline)

Status: Proposed (2026-10-17). STRIDE-style baseline for Phase 0; updated whenever a phase adds an entry point. Implements design §12 and §15.15.

## 1. Assets

| Asset | Why it matters |
|---|---|
| Note and attachment content (vaults, history) | Private user data; the product's reason to exist |
| Credentials and tokens (passwords, refresh tokens, PATs, signing keys, OIDC client secrets) | Full account takeover |
| ACLs and audit log | Integrity of who can see what, and evidence |
| Server host / volumes | Lateral movement, data destruction |

## 2. Trust boundaries

1. Internet/LAN → reverse proxy/ingress → `opennote-api` (TLS terminates at ingress or API).
2. `opennote-api`/`worker` → PostgreSQL, Valkey, vault and history volumes (trusted network, credentials from secrets).
3. `opennote-worker` → AI runtime (optional) and any external AI provider (opt-in only).
4. Vault content → parsers, renderers, AI prompts (content is untrusted input even though users own it: shared vaults, clipped web pages, emailed notes).
5. Native client device ↔ local vault folder shared with other apps (Obsidian, Files).

## 3. Threats and controls

| STRIDE | Threat | Control | Verified by |
|---|---|---|---|
| S | Stolen access/refresh token | Short-lived access tokens; rotating, device-bound, hashed refresh tokens; revocation per device; Keychain on Apple, httpOnly cookies on web | Integration tests for rotation/revocation |
| S | Credential stuffing on local login | Argon2id, rate limits per IP/user, lockout backoff, optional OIDC-only mode | Rate-limit tests |
| T | Path traversal / symlink escape via note paths, uploads, folder moves | Storage contract §3 validation, `dir_fd` + `O_NOFOLLOW`, realpath containment check | Fuzz tests with traversal corpus |
| T | Stale write overwrites newer content | Revision preconditions, server-side merge, conflict copies | Sync simulation |
| T | Malicious Markdown/HTML/SVG executing script in web client (stored XSS) | Rendered Markdown sanitized (DOMPurify allow-list), raw HTML rendered sandboxed or as text, SVG attachments served with `Content-Disposition: attachment` and CSP; strict CSP on app | Playwright XSS cases |
| T | Malicious upload (zip bombs, polyglots, huge files) | Size limits, server-side type sniffing, no archive extraction in v1, optional ClamAV scan hook | Upload tests |
| R | User denies deleting or sharing | Append-only audit log for auth, ACL, delete, restore, conflict resolution | Audit tests |
| I | Cross-vault data leak through search, AI or IDs | Authorization resolved via vault on every query; search and AI retrieval filtered by vault before ranking; 404 for unauthorized | Authorization matrix tests per endpoint |
| I | Secrets in logs, errors or images | RFC 9457 generic errors, log redaction filter for auth headers/tokens, gitleaks and Trivy secret scan, `.env` git-ignored | CI scans |
| I | Note content sent to external AI | External providers disabled by default; per-vault explicit opt-in; outbound allow-list | Config tests (Phase 7) |
| I | Prompt injection from note content | Retrieved content delimited as data, fixed system prompt, no tool execution or write actions from model output without user approval | AI red-team cases (Phase 7) |
| D | Request floods, expensive searches, giant sync batches | Rate limits, query timeouts, pagination caps, batch size limits, upload size limits | Load tests |
| E | Unauthenticated route added by mistake | `assert_routes_authenticated()` fails startup; `KEYLESS_ROUTES` reviewed | Startup unit test |
| E | Container breakout / privilege | Non-root arbitrary UID, no capabilities, read-only root FS, no privileged mode, restricted SCC on OpenShift, `seccompProfile: RuntimeDefault` | Container CI job |
| E | Supply-chain compromise | Pinned dependencies, pip-audit/npm audit, Trivy, base image digests in releases, signed images (cosign) from Phase 8 | CI |

## 4. Explicit non-claims

- OpenNote does **not** provide end-to-end encryption. The server can read note content (needed for search, OCR and AI). Encryption at rest is the operator's volume/database encryption; backups are encrypted with a key the operator holds (Phase 8).
- Security of the local vault on a device is the device's security (FileVault, iOS data protection with `NSFileProtectionComplete` for the app container).
