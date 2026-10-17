# ADR-0012: Authentication: OpenNote as OAuth 2.0 authorization server, OIDC upstream

Status: Proposed  
Date: 2026-10-17  
Deciders: Flemming (pending review)

## Context
Design §12: local accounts, OIDC, OAuth 2.0, MFA via IdP, sessions, device registration. `claude.md` §12: deny-by-default, `assert_routes_authenticated` at startup, `KEYLESS_ROUTES` allow-list.

## Decision
- The backend issues its own tokens: OAuth 2.0 authorization code + PKCE for all clients (native via `ASWebAuthenticationSession`, web via a backend-for-frontend cookie session).
- Login methods behind that: local password (Argon2id) or upstream OIDC providers (Keycloak, Entra ID, Authentik…). MFA is delegated to the IdP; local MFA (TOTP) is a later item.
- Access tokens: short-lived (15 min) signed JWT (EdDSA). Refresh tokens: opaque, hashed in PostgreSQL, rotating, bound to `device_id`.
- Web: tokens never reach JavaScript; httpOnly, `Secure`, `SameSite=Strict` cookies plus CSRF token for mutating requests.
- Automation (design §10.5): personal access tokens scoped per vault, checked by `get_api_key`.
- Every route depends on `get_current_principal` or `get_api_key`; `assert_routes_authenticated()` fails startup otherwise.

## Consequences
One token model for all clients and integrations. We own token security (key rotation, revocation), covered in the threat model.
