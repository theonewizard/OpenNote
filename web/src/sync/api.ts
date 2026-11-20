// The sync endpoints (sync protocol §§3-5) over the session-cookie client.
import { ApiError, request } from "@/api/client";
import type { PushOperation, SyncChanges, SyncPushResult, SyncSnapshot } from "@/api/types";
import { sha256 } from "@/sync/hash";

export const CHUNK_BYTES = 8 * 1024 * 1024; // sync protocol §3
const JSON_TIMEOUT_MS = 30_000;
const CHUNK_TIMEOUT_MS = 120_000;

const enc = encodeURIComponent;
const hex = (hash: string) => hash.replace(/^sha256:/, "");
const vaultQuery = (vaultId: string) => `vault_id=${enc(vaultId)}`;

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await request(path, { signal: AbortSignal.timeout(JSON_TIMEOUT_MS), ...init });
  return (await response.json()) as T;
}

export function getChanges(vaultId: string, cursor: string): Promise<SyncChanges> {
  return json(`/api/v1/sync/${enc(vaultId)}/changes?cursor=${enc(cursor)}&limit=500`);
}

export function getSnapshot(vaultId: string, page: string | null): Promise<SyncSnapshot> {
  return json(`/api/v1/sync/${enc(vaultId)}/snapshot${page ? `?page=${enc(page)}` : ""}`);
}

export function push(vaultId: string, operations: PushOperation[]): Promise<SyncPushResult> {
  return json(`/api/v1/sync/${enc(vaultId)}/push`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ operations }),
  });
}

/** Downloads a blob and checks it against its hash. */
export async function getBlob(vaultId: string, hash: string): Promise<Uint8Array<ArrayBuffer>> {
  const response = await request(`/api/v1/blobs/${hex(hash)}?${vaultQuery(vaultId)}`, {
    signal: AbortSignal.timeout(CHUNK_TIMEOUT_MS),
  });
  const bytes = new Uint8Array(await response.arrayBuffer());
  if ((await sha256(bytes)) !== hash) throw new Error("Downloaded blob does not match its hash");
  return bytes;
}

/** Bytes of an unfinished upload the server holds, or null when it has the whole blob. */
async function uploadOffset(url: string): Promise<number | null> {
  try {
    await request(url, { method: "HEAD", signal: AbortSignal.timeout(JSON_TIMEOUT_MS) });
    return null;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return Number(error.headers.get("Upload-Offset") ?? 0);
    throw error;
  }
}

/** HEAD first and upload only what is missing; large blobs go in 8 MiB chunks and resume
 * from the server's Upload-Offset after an interruption. */
export async function putBlob(vaultId: string, hash: string, bytes: Uint8Array<ArrayBuffer>): Promise<void> {
  const url = `/api/v1/blobs/${hex(hash)}?${vaultQuery(vaultId)}`;
  let offset = await uploadOffset(url);
  if (offset === null) return;
  if (offset === 0 && bytes.length <= CHUNK_BYTES) {
    await request(url, {
      method: "PUT",
      headers: { "Content-Type": "application/octet-stream" },
      body: bytes,
      signal: AbortSignal.timeout(CHUNK_TIMEOUT_MS),
    });
    return;
  }
  let mismatches = 0;
  while (offset < bytes.length) {
    const end = Math.min(offset + CHUNK_BYTES, bytes.length);
    try {
      const response = await request(url, {
        method: "PUT",
        headers: {
          "Content-Type": "application/octet-stream",
          "Content-Range": `bytes ${offset}-${end - 1}/${bytes.length}`,
        },
        body: bytes.subarray(offset, end),
        signal: AbortSignal.timeout(CHUNK_TIMEOUT_MS),
      });
      if (response.status === 204) return;
      offset = Number(response.headers.get("Upload-Offset") ?? end);
    } catch (error) {
      // The server holds a different offset (an earlier chunk did arrive): continue there.
      const at = error instanceof ApiError && error.status === 409 ? error.headers.get("Upload-Offset") : null;
      if (at === null || ++mismatches > 3) throw error;
      offset = Number(at);
    }
  }
}
