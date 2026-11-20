# ADR-0010: Container images on Red Hat UBI

Status: Accepted (2026-11-01)  
Date: 2026-10-17  
Deciders: Flemming  
Amended: 2026-11-14 (Flemming): the base moved from UBI 9 minimal to UBI 10 minimal (10.3); Tesseract for OCR; 2026-11-19 (Flemming): Tesseract built from source instead of EPEL 10

## Context
Design §11 and `CLAUDE.md` §5 prefer UBI. Free UBI images are on `registry.access.redhat.com` (no login). Red Hat's PostgreSQL and Redis images are on `registry.redhat.io`, which needs a Red Hat account, and none ships pgvector.

## Decision
| Image | Base | Notes |
|---|---|---|
| `opennote-api` (also worker) | `ubi10/ubi-minimal` with `python3.14` from the UBI 10 repositories and the virtual environment built in the same image; `ubi9/python-314` if that RPM is missing (versions.md, "Python decision") | One stage (installing wheels needs nothing the runtime lacks), non-root UID 1001 group 0, read-only root FS; Leptonica and Tesseract built from source in a builder stage for OCR (amendments below) |
| `opennote-web` | Official Node.js image builder (the `.nvmrc` release; only static files leave it) → `ubi10/ubi-minimal` + `nginx-core` 1.26 runtime | Static files + `/api` reverse proxy |
| `opennote-postgres` | `ubi-minimal` + PGDG PostgreSQL RPMs + `pgvector` RPM (PGDG's RHEL 10 repository) | Built in CI; arbitrary-UID safe entrypoint |
| `opennote-valkey` | `ubi-minimal` + Valkey 9.1.2 built from source in a builder stage (the UBI repositories carry no Valkey 9) | — |
| `opennote-ai` | UBI Python image + Ollama client; model runtime as separate upstream Ollama container | Optional profile; not built in Phase 0 |

`compose.dev.yaml` uses the same images as `compose.yaml`; the upstream `pgvector/pgvector` and `valkey/valkey` images serve only as the backend CI job's service containers. All images: explicit version tags plus digest pinning on every build, SIGTERM-graceful entrypoints, health checks, no secrets.

## Consequences
Production images are UBI-based and OpenShift restricted-SCC compatible, with one exception: the optional AI model runtime (upstream Ollama, Ubuntu-based) is not UBI. It is off by default, runs only when an operator enables the AI profile, and is listed as an exception in the release notes; a UBI-based llama.cpp server image can replace it later. We own patching of the PostgreSQL and Valkey images: CI rebuilds and scans every image on every push and pull request and every Monday from `main`, and a HIGH or CRITICAL finding that has a fix fails the run; nothing rebuilds an image automatically when a scan fails. Operators may instead use a managed PostgreSQL with pgvector.

Amendment of 2026-11-14: all images moved from `ubi9/ubi-minimal` to `ubi10/ubi-minimal:10.3`, because the newest UBI 9 base (9.9) carried 14 fixable HIGH findings in `krb5-libs` whose fix the UBI 9 repositories did not yet ship, while UBI 10.3 had none (`.conversations/2026-11-14-postgres-18-7.md`). RHEL 10 runs only on x86-64-v3 CPUs (Intel Haswell, AMD Excavator or newer) on x86_64, so the images no longer start on older x86_64 hosts.

Amendment of 2026-11-14 (Flemming, OCR decision; replaced by the amendment of 2026-11-19, because EPEL 10 has no Tesseract): the `opennote-api` image, which also runs the worker, installs `tesseract` and `tesseract-langpack-eng` from EPEL 10, the one package repository outside Red Hat's. Its signing key is committed next to the Containerfile (fingerprint `7D8D15CBFC4E62688591FB2633D98517E37ED158`), `epel-release` is installed only after its signature checks out, and microdnf checks every EPEL package's signature. EPEL packages are rebuilt by Fedora volunteers, not Red Hat, and carry no Red Hat support; the Trivy scan covers them like every other package. The worker and the API share the image, so the API carries Tesseract too, unused; a separate worker image would also mean a second image in releases, Helm and the Kubernetes manifests.

Amendment of 2026-11-19 (Flemming): EPEL 10 does not ship Tesseract, because RHEL 10 carries it in AppStream and EPEL does not duplicate RHEL packages; the free UBI repositories do not include it either, so the first build failed with `No package matches 'tesseract'`. Of building from source, AlmaLinux 10 AppStream, CentOS Stream 10 AppStream, or no image OCR, Flemming chose building from source, as for Valkey. A builder stage of `opennote-api` compiles Leptonica 1.87.0 and Tesseract 5.5.4 from their upstream source releases and fetches the `tessdata_fast` English model; each download is checked against the SHA-256 Homebrew pins (docs/development/versions.md). The result lives under `/opt/tesseract`, linked by RPATH, with the image libraries it reads installed from the UBI 10 repositories. The image keeps Red Hat's repositories only; the EPEL key and the EPEL repository are gone. We own Tesseract's patching like Valkey's: a new release means a new version and checksum in the Containerfile.
