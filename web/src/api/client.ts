// Fetch helpers for /api/v1. The web app authenticates with its httpOnly session cookie
// (api-contract §1): requests are same-origin with credentials, and every request that
// changes something echoes the readable opennote_csrf cookie as X-CSRF-Token.

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, title: string) {
    super(title);
    this.status = status;
  }
}

function csrfToken(): string | undefined {
  const match = /(?:^|;\s*)opennote_csrf=([^;]*)/.exec(document.cookie);
  return match ? decodeURIComponent(match[1]) : undefined;
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = csrfToken();
  if (init.method && init.method !== "GET" && token) headers.set("X-CSRF-Token", token);
  const response = await fetch(new URL(path, location.origin), {
    ...init,
    credentials: "same-origin",
    headers,
  });
  if (!response.ok) {
    let title = response.statusText;
    if (response.headers.get("content-type")?.startsWith("application/problem+json")) {
      title = ((await response.json()) as { title?: string }).title ?? title;
    }
    throw new ApiError(response.status, title);
  }
  return response;
}

export async function getJson<T>(path: string): Promise<T> {
  return (await (await request(path)).json()) as T;
}

export interface NoteContent {
  bytes: Uint8Array;
  etag: string;
}

export async function getNoteContent(id: string): Promise<NoteContent> {
  const response = await request(`/api/v1/notes/${encodeURIComponent(id)}/content`);
  return {
    bytes: new Uint8Array(await response.arrayBuffer()),
    etag: response.headers.get("etag") ?? "",
  };
}

// Replaces the note's bytes if the server still holds revision `etag` and returns the
// new ETag; a stale etag is a 412 ApiError and nothing is overwritten.
export async function putNoteContent(id: string, bytes: Uint8Array<ArrayBuffer>, etag: string): Promise<string> {
  const response = await request(`/api/v1/notes/${encodeURIComponent(id)}/content`, {
    method: "PUT",
    headers: { "Content-Type": "text/markdown; charset=utf-8", "If-Match": etag },
    body: bytes,
  });
  return response.headers.get("etag") ?? "";
}
