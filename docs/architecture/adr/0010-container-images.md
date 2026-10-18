# ADR-0010: Container images on Red Hat UBI

Status: Proposed  
Date: 2026-10-17  
Deciders: Flemming (pending review)

## Context
Design §11 and `CLAUDE.md` §5 prefer UBI. Free UBI images are on `registry.access.redhat.com` (no login). Red Hat's PostgreSQL and Redis images are on `registry.redhat.io`, which needs a Red Hat account, and none ships pgvector.

## Decision
| Image | Base | Notes |
|---|---|---|
| `opennote-api` (also worker) | `ubi9/ubi-minimal` with `python3.14` from the UBI 9 repositories, in the builder (virtual environment) and the runtime stage; `ubi9/python-314` if that RPM is missing (versions.md, "Python decision") | Multi-stage, non-root UID 1001 group 0, read-only root FS |
| `opennote-web` | Official Node.js image builder (the `.nvmrc` release; only static files leave it) → `ubi9/ubi-minimal` + the `nginx:1.26` module stream runtime | Static files + `/api` reverse proxy |
| `opennote-postgres` | `ubi-minimal` + PGDG PostgreSQL RPMs + `pgvector` RPM | Built in CI; arbitrary-UID safe entrypoint |
| `opennote-valkey` | `ubi-minimal` + Valkey from EPEL/AppStream if available, else built from source in a builder stage | — |
| `opennote-ai` | UBI Python image + Ollama client; model runtime as separate upstream Ollama container | Optional profile |

`compose.dev.yaml` may substitute upstream `pgvector/pgvector` and `valkey/valkey` images for fast local start. All images: explicit version tags plus digest pinning in release builds, SIGTERM-graceful entrypoints, health checks, no secrets.

## Consequences
Production images are UBI-based and OpenShift restricted-SCC compatible, with one exception: the optional AI model runtime (upstream Ollama, Ubuntu-based) is not UBI. It is off by default, runs only when an operator enables the AI profile, and is listed as an exception in the release notes; a UBI-based llama.cpp server image can replace it later. We own patching of the PostgreSQL and Valkey images: CI rebuilds and scans every image on every push and pull request and every Monday from `main`, and a HIGH or CRITICAL finding that has a fix fails the run; nothing rebuilds an image automatically when a scan fails. Operators may instead use a managed PostgreSQL with pgvector.
