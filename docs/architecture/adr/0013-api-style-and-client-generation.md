# ADR-0013: REST + WebSocket hints, OpenAPI-first clients

Status: Accepted (2026-11-01)  
Date: 2026-10-17  
Deciders: Flemming

## Context
Design §15.2.6: versioned documented API, OpenAPI, typed clients, no duplicated rules.

## Decision
REST/JSON under `/api/v1`, conventions in the [API contract](../../api/api-contract.md). WebSocket only for change hints. FastAPI generates OpenAPI 3.1; `scripts/gen-openapi.sh` exports it to `docs/api/openapi.json`, which is committed. CI fails if the export differs from the committed file. Clients: TypeScript via `openapi-typescript` + `openapi-fetch`; Swift via `swift-openapi-generator`.

## Consequences
Contract drift shows up as a CI diff and as compile errors in clients. GraphQL and gRPC are not used.
