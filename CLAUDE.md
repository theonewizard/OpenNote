# Project Guidance for Claude

**Status: Production

These rules apply to every Claude session, agent, subagent, worktree, and development task in this repository unless the user explicitly overrides them.

The objective is to maintain a professional, reproducible, secure development environment while allowing Claude to work autonomously during normal development.

---

## 1. Operating Principles

Follow these principles in order:

1. Protect production and secrets.
2. Preserve correctness and existing behaviour unless change is requested.
3. Make the smallest change necessary.
4. Verify changes with automated tests and appropriate runtime testing.
5. Keep development reproducible.
6. Prefer simple solutions over clever or over-engineered ones.
7. Leave the repository cleaner only where your own changes require cleanup.
8. Always use the Latest stable version of software used

Do not trade safety or correctness for speed.

---

## 2. Autonomy and Approval

Claude is authorized to work autonomously in **development and pre-production/prepped environments**.

Claude may without asking:

- create and modify source files
- create branches and worktrees
- create or update tests
- run tests, linters, formatters, type checkers, and builds
- install project dependencies inside approved project environments
- create development containers
- modify development configuration
- start, stop, and restart development services
- deploy to development/prepped environments
- inspect logs
- debug failures
- retry failed implementations
- commit development changes after verification
- squash-merge completed development work according to this workflow

Do not repeatedly request approval for normal development actions.

### Approval is required before:

- modifying production
- deploying to production
- committing directly in a production environment
- deleting or modifying production data
- changing production secrets or credentials
- destructive infrastructure operations
- irreversible external actions
- force-pushing shared branches
- rewriting published Git history
- bypassing security controls
- weakening authentication or authorization
- disabling tests or security checks merely to make a change pass

When uncertain whether a target is production, **treat it as production**.

---

## 3. Python Environment

All Python work for this repository runs inside the repository's `.venv`.

Never install project Python packages into:

- system Python
- global Python environments
- Homebrew Python environments
- user-site packages

Use:

```bash
.venv/bin/python
.venv/bin/pytest
.venv/bin/pip
```

or activate the virtual environment first.

### Creating the environment

If a new worktree does not contain `.venv`, create it before running backend code or tests:

```bash
python -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r backend/requirements-dev.txt   # includes backend/requirements.txt
```

### Dependencies

New runtime dependencies must be:

1. justified by the requested feature
2. added to `backend/requirements.txt` (development-only tools go in `backend/requirements-dev.txt`)
3. installed inside `.venv`
4. compatible with the project's supported Python version

Do not add a dependency when the Python standard library or an existing dependency adequately solves the problem.

Never install a dependency merely to avoid writing a small amount of straightforward code.

---

## 4. Node / Frontend Environment

Use the package manager already established by the repository.

Do not switch package managers or regenerate lockfiles unnecessarily.

When adding frontend dependencies:

- use the existing package manager
- update the appropriate manifest
- update the existing lockfile
- avoid unnecessary dependencies
- verify the production build

Do not globally install project-specific Node packages.

Prefer repository-local binaries and scripts.

---

## 5. Containers

The application must remain suitable for Linux container deployment.

Prefer **Red Hat Universal Base Images (UBI)** where practical and compatible with the application.

Container builds should:

- be reproducible
- use explicit base image versions where practical
- minimize unnecessary packages
- run as a non-root user where possible
- avoid embedding secrets
- use multi-stage builds when beneficial
- keep runtime images smaller than build environments
- provide appropriate health checks
- handle SIGTERM and graceful shutdown correctly

Never place credentials, `.env` files, API keys, certificates, or private keys into container images.

---

## 6. Git and Worktree Workflow

Feature work happens on a dedicated branch in a worktree under:

```text
.worktrees/<subsystem>/
```

Do not perform feature development directly on `main`.

Use descriptive branch names appropriate to the repository conventions.

Examples:

```text
feature/battery-metadata
fix/transcoding-timeout
security/api-auth
```

Completed feature work is squash-merged to `main`.

Before merging:

- tests must pass
- required builds must succeed
- relevant runtime behaviour must be verified
- security requirements must be satisfied
- the diff must be reviewed
- temporary/debug artifacts must be removed

Never force-push `main`.

Never rewrite published/shared history without explicit approval.

---

## 7. Specifications and Plans

Design specifications live in:

```text
docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md
```

Implementation plans live in:

```text
docs/superpowers/plans/
```

For substantial features, architectural changes, or cross-component changes:

1. understand the existing implementation
2. create or update the design/spec
3. create an implementation plan when useful
4. implement incrementally
5. test each meaningful stage
6. verify the deployed result

Do not create unnecessary specifications for trivial fixes.

Documentation should describe the system that actually exists, not an aspirational implementation.

---

## 8. Development Loop

Use the following development loop:

```text
Understand
    ↓
Plan
    ↓
Implement
    ↓
Test
    ↓
Review
    ↓
Deploy to development/prepped
    ↓
Verify actual behaviour
    ↓
Fix and repeat if necessary
    ↓
Commit
```

A successful build or test suite alone does **not** prove that a feature works.

After deployment, test the actual feature whenever practical.

If verification fails:

1. inspect logs and observable behaviour
2. determine the root cause
3. correct the implementation
4. rerun relevant tests
5. redeploy
6. verify again

Do not declare work complete while known verification failures remain.

---

## 9. Testing Requirements

Every change must receive testing proportional to its risk.

Where applicable, run:

- unit tests
- integration tests
- API tests
- frontend tests
- type checking
- linting
- production builds
- container builds
- runtime/deployment verification

Bug fixes should normally include a regression test demonstrating the failure and preventing recurrence.

New functionality should include tests covering its important behaviour.

Do not:

- delete tests simply because they fail
- weaken assertions to make tests pass
- skip relevant tests without explaining why
- modify unrelated tests
- mock away the behaviour being tested

If a required test cannot be run, state that explicitly when reporting completion.

---

## 10. Commit Rules

Development commits are authorized when:

- relevant tests pass
- the change has been reviewed
- no secrets or junk files are staged
- the change matches the requested scope

Production commits or production changes require explicit approval.

Before committing, inspect:

```bash
git status
git diff
git diff --cached
```

The staged diff must be understood before committing.

Use concise commit messages describing the actual change.

Do not include unrelated changes in the same commit.

---

## 11. Security and Hygiene Guardrails

These controls are mandatory.

### Secrets

**Secrets never enter the repository.**

`.env` remains gitignored.

Never:

- commit secrets
- print secret values
- paste secret values into logs
- expose credentials in test output
- place credentials into documentation
- include secrets in container images

When checking whether a secret exists, redact the value:

```text
AWS_ACCESS_KEY=<present>
DATABASE_PASSWORD=<present>
```

Any host, cluster, or namespace running OpenNote with real user vaults (Compose host, Kubernetes or OpenShift namespace) holds live credentials: database passwords, OIDC client secrets, token signing keys, and any opted-in AI provider keys.

Treat access to such a host as **production access**. When uncertain whether a target is production, treat it as production.

---

## 12. Backend Authentication

Every new backend route requires an authentication dependency by default.

Authentication is enforced at startup by:

```text
assert_routes_authenticated
```

in:

```text
backend/app/api/main.py
```

Intentionally unauthenticated routes must be explicitly included in:

```text
KEYLESS_ROUTES
```

New routes must use one of:

```python
Depends(get_current_principal)   # OAuth 2.0 bearer token (users and devices)
Depends(get_api_key)             # automation tokens
```

or a stricter authorization mechanism.

A route without authentication or an explicit approved keyless exemption **does not ship**.

Default policy:

```text
DENY unless explicitly authorized.
```

---

## 13. API Error Handling

API errors follow **RFC 9457 Problem Details**.

Never expose raw exceptions to clients.

Do not:

```python
return str(exc)
```

or otherwise leak:

- stack traces
- filesystem paths
- credentials
- database internals
- implementation details

Instead:

1. log the exception server-side with appropriate context
2. return a generic client-safe error
3. use:

```text
Content-Type: application/problem+json
```

Error responses should contain appropriate Problem Details fields such as:

```json
{
  "type": "...",
  "title": "...",
  "status": 500,
  "detail": "...",
  "instance": "..."
}
```

Do not expose sensitive diagnostic information in `detail`.

---

## 14. Frontend API Contract

The web app talks to the backend through a TypeScript client generated from the committed OpenAPI document (`docs/api/openapi.json`). Query parameters are validated with Zod schemas in `web/src/api/`.

Adding or modifying a backend endpoint, query parameter, or payload requires, in the **same change**:

- regenerating the OpenAPI document and the TypeScript and Swift clients
- updating the corresponding Zod schemas

CI fails when the committed OpenAPI document or generated clients drift from the backend.

Backend and client contract changes must remain synchronized.

---

## 15. Input Validation

Treat all external input as untrusted.

Validate:

- API payloads
- query parameters
- path parameters
- uploaded files
- filenames
- URLs
- external API responses where appropriate
- configuration values

Use established schemas and validation mechanisms rather than duplicating validation logic.

Do not rely solely on frontend validation.

---

## 16. Filesystem Safety

Never construct unsafe filesystem paths directly from user-controlled input.

Protect against:

- path traversal
- unsafe temporary files
- symlink attacks where relevant
- overwriting arbitrary files
- uncontrolled file sizes
- untrusted archive extraction

Uploaded or generated filenames must be sanitized before filesystem use.

---

## 17. Database Changes

Database schema changes must be deliberate and reviewable.

When modifying schemas:

- use the project's migration mechanism
- preserve existing data unless deletion is explicitly required
- consider backward compatibility
- test migrations
- consider rollback behaviour

Never manually alter the production database without explicit approval.

Avoid destructive migrations when a safe staged migration is practical.

---

## 18. Logging

Logs should provide enough context for diagnosis without leaking sensitive information.

Never log:

- passwords
- API keys
- authorization headers
- session tokens
- private keys
- complete sensitive request payloads

Use appropriate log levels.

Do not leave temporary debug logging in completed work unless it provides ongoing operational value.

---

## 19. External Services

Calls to external services must:

- have reasonable timeouts
- handle errors
- avoid infinite retries
- use bounded retry/backoff where appropriate
- validate unexpected responses
- avoid leaking credentials in logs

Do not assume an external API is always available.

---

## 20. Dependency and Supply-Chain Hygiene

Before introducing a new dependency, determine whether it is actually necessary.

Prefer:

1. standard library
2. existing project dependency
3. well-maintained established dependency
4. new specialized dependency only when justified

Avoid:

- abandoned packages
- unnecessary wrappers
- packages with unclear provenance
- dependencies added solely for trivial functionality

Do not perform broad dependency upgrades as part of unrelated feature work.

Security upgrades may be handled separately when discovered.

---

## 21. Repository Hygiene

Before every commit, ensure junk does not enter Git.

Examples that must not be committed unless explicitly required:

```text
*.pyc
__pycache__/
.DS_Store
.claude/worktrees/
.vite/
.understand-anything/
.env
coverage artifacts
temporary logs
large scrape dumps
temporary downloads
IDE state
```

If `git status` shows generated junk:

1. determine its origin
2. remove it if safe
3. update `.gitignore` where appropriate
4. verify `git status` again

Do not blindly run destructive cleanup commands against unknown files.

---

## 22. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- do not improve unrelated code
- do not reformat unrelated sections
- do not rewrite comments unnecessarily
- do not rename unrelated variables
- do not refactor unrelated components
- do not update unrelated dependencies
- match the existing style and architecture

If unrelated problems are discovered, mention them separately rather than fixing them unless they block the requested work.

### Orphans created by your changes

Remove:

- imports your changes made unused
- variables your changes made unused
- functions made obsolete by your changes
- temporary compatibility code introduced during development
- debugging artifacts introduced during development

Do not remove pre-existing dead code unless requested.

### Scope test

Every changed line should have a clear relationship to:

- the user's request
- a required test
- a required security correction caused by the change
- cleanup made necessary by the change

If that relationship cannot be explained, reconsider the change.

---

## 23. Architecture and Over-Engineering

Prefer the simplest implementation that correctly satisfies current requirements.

Do not introduce:

- unnecessary abstraction layers
- speculative extensibility
- unnecessary interfaces
- premature plugin systems
- generic frameworks for single-use functionality
- distributed components when a local component is sufficient
- complex caching without demonstrated need
- additional services without operational justification

Reuse existing architecture and patterns when they are adequate.

Avoid both extremes:

```text
under-engineered ← appropriate solution → over-engineered
```

The goal is maintainable production-quality code, not maximum abstraction.

---

## 24. Performance

Do not prematurely optimize.

However, avoid obvious scalability problems such as:

- unbounded memory growth
- unbounded queues
- loading arbitrarily large files into memory
- N+1 database queries
- blocking operations in async request paths
- uncontrolled concurrency
- infinite retries
- missing network timeouts

Measure before making significant performance optimizations.

---

## 25. Compatibility

Preserve existing APIs, configuration, stored data, and user behaviour unless the requested change requires otherwise.

Breaking changes must be identified explicitly.

When practical, use migrations or compatibility transitions instead of immediate breakage.

Do not silently change public API semantics.

---

## 26. Documentation

Update documentation when a change affects:

- installation
- configuration
- deployment
- API behaviour
- architecture
- operational procedures
- security requirements
- user-visible behaviour

Do not update documentation unrelated to the requested change.

Examples and commands must match the current implementation.

---

## 27. Code Review Before Completion

Before considering work complete, review the complete diff.

Check specifically for:

- correctness
- security regressions
- missing authentication
- leaked secrets
- inadequate validation
- exception leakage
- unnecessary complexity
- duplicated logic
- accidental formatting changes
- dead code created by the change
- missing tests
- missing documentation
- backwards compatibility issues
- debugging artifacts

Ask:

> Could this change be smaller while still completely solving the problem?

If yes, simplify it.

---

## 28. Ponytail Audit

Always review implementation work for unnecessary complexity and over-engineering using the `ponytail-audit` skill.

Use the audit as a **review step**, not as permission to perform unrelated refactoring.

Apply recommendations only when they are directly relevant to the current change.

If the audit identifies unrelated technical debt:

- report it
- do not fix it unless requested

The surgical-change rule remains authoritative.

---

## 29. Definition of Done

Work is complete only when all applicable conditions are satisfied:

- requested behaviour is implemented
- relevant tests pass
- new behaviour has appropriate test coverage
- frontend/backend contracts remain synchronized
- authentication and authorization requirements are satisfied
- error handling follows project standards
- no secrets are exposed
- development deployment succeeds where applicable
- deployed behaviour has been verified where practical
- failed verification has been corrected and retested
- documentation is updated where necessary
- repository hygiene has been checked
- the final diff contains only relevant changes
- over-engineering review has been performed
- development changes have been committed when appropriate

A task is **not done** merely because the code compiles.

---

## 30. Completion Report

When completing a development task, provide a concise report containing:

- what changed
- important implementation decisions
- tests performed and their results
- deployment/verification performed
- files or components materially affected
- any known limitations or follow-up work
- anything that could not be verified

Do not claim tests, deployment, or verification succeeded unless they were actually performed.

---

## Final Rule

When choosing between a broad change and a surgical change that both satisfy the requirement:

**choose the surgical change.**

When choosing between a clever solution and a simple solution that both satisfy the requirement:

**choose the simple solution.**

When choosing between assuming something works and verifying it:

**verify it.**

When an action could affect production:

**require explicit approval.**

Document every prompt
*** add conversations to .conversations ***
