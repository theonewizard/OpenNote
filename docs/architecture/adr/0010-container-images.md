# ADR-0010: Container images on Red Hat UBI

Status: Proposed  
Date: 2026-10-17  
Deciders: Flemming (pending review)

## Context
Design §11 and `claude.md` §5 prefer UBI. Free UBI images are on `registry.access.redhat.com` (no login). Red Hat's PostgreSQL and Redis images are on `registry.redhat.io`, which needs a Red Hat account, and none ships pgvector.

## Decision
| Image | Base | Notes |
|---|---|---|
| `opennote-api` (also worker) | `ubi9/python-3xx` or `ubi10` Python image (newest Python available, see versions.md) builder → `ubi-minimal` runtime | Multi-stage, non-root UID 1001 group 0, read-only root FS |
| `opennote-web` | Node UBI image builder → `ubi9/nginx-1xx` runtime | Static files + `/api` reverse proxy |
| `opennote-postgres` | `ubi-minimal` + PGDG PostgreSQL RPMs + `pgvector` RPM | Built in CI; arbitrary-UID safe entrypoint |
| `opennote-valkey` | `ubi-minimal` + Valkey from EPEL/AppStream if available, else built from source in a builder stage | — |
| `opennote-ai` | UBI Python image + Ollama client; model runtime as separate upstream Ollama container | Optional profile |

`compose.dev.yaml` may substitute upstream `pgvector/pgvector` and `valkey/valkey` images for fast local start. All images: explicit version tags plus digest pinning in release builds, SIGTERM-graceful entrypoints, health checks, no secrets.

## Consequences
Production images are fully UBI-based and OpenShift restricted-SCC compatible. We own patching of the PostgreSQL and Valkey images (CI rebuilds weekly and on CVE scan failures). Operators may instead use a managed PostgreSQL with pgvector.
