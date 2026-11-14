# ADR-0010: Container images on Red Hat UBI

Status: Accepted (2026-11-01)  
Date: 2026-10-17  
Deciders: Flemming  
Amended: 2026-11-14 (Flemming): the base moved from UBI 9 minimal to UBI 10 minimal (10.3)

## Context
Design §11 and `CLAUDE.md` §5 prefer UBI. Free UBI images are on `registry.access.redhat.com` (no login). Red Hat's PostgreSQL and Redis images are on `registry.redhat.io`, which needs a Red Hat account, and none ships pgvector.

## Decision
| Image | Base | Notes |
|---|---|---|
| `opennote-api` (also worker) | `ubi10/ubi-minimal` with `python3.14` from the UBI 10 repositories and the virtual environment built in the same image; `ubi9/python-314` if that RPM is missing (versions.md, "Python decision") | One stage (installing wheels needs nothing the runtime lacks), non-root UID 1001 group 0, read-only root FS |
| `opennote-web` | Official Node.js image builder (the `.nvmrc` release; only static files leave it) → `ubi10/ubi-minimal` + `nginx-core` 1.26 runtime | Static files + `/api` reverse proxy |
| `opennote-postgres` | `ubi-minimal` + PGDG PostgreSQL RPMs + `pgvector` RPM (PGDG's RHEL 10 repository) | Built in CI; arbitrary-UID safe entrypoint |
| `opennote-valkey` | `ubi-minimal` + Valkey 9.1.2 built from source in a builder stage (the UBI repositories carry no Valkey 9) | — |
| `opennote-ai` | UBI Python image + Ollama client; model runtime as separate upstream Ollama container | Optional profile; not built in Phase 0 |

`compose.dev.yaml` uses the same images as `compose.yaml`; the upstream `pgvector/pgvector` and `valkey/valkey` images serve only as the backend CI job's service containers. All images: explicit version tags plus digest pinning on every build, SIGTERM-graceful entrypoints, health checks, no secrets.

## Consequences
Production images are UBI-based and OpenShift restricted-SCC compatible, with one exception: the optional AI model runtime (upstream Ollama, Ubuntu-based) is not UBI. It is off by default, runs only when an operator enables the AI profile, and is listed as an exception in the release notes; a UBI-based llama.cpp server image can replace it later. We own patching of the PostgreSQL and Valkey images: CI rebuilds and scans every image on every push and pull request and every Monday from `main`, and a HIGH or CRITICAL finding that has a fix fails the run; nothing rebuilds an image automatically when a scan fails. Operators may instead use a managed PostgreSQL with pgvector.

Amendment of 2026-11-14: all images moved from `ubi9/ubi-minimal` to `ubi10/ubi-minimal:10.3`, because the newest UBI 9 base (9.9) carried 14 fixable HIGH findings in `krb5-libs` whose fix the UBI 9 repositories did not yet ship, while UBI 10.3 had none (`.conversations/2026-11-14-postgres-18-7.md`). RHEL 10 runs only on x86-64-v3 CPUs (Intel Haswell, AMD Excavator or newer) on x86_64, so the images no longer start on older x86_64 hosts.
