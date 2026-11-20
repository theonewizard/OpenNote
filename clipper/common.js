// Settings live in the browser's extension storage: the server URL, a personal access
// token with write scope for one vault, and that vault's id.
export async function settings() {
  return chrome.storage.local.get({ server: "", token: "", vaultId: "", folder: "Clippings" });
}

export async function api(path, { method = "GET", body } = {}) {
  const { server, token } = await settings();
  if (!server || !token) throw new Error("Set the server and token in the extension options.");
  const response = await fetch(new URL(path, server), {
    method,
    headers: { "X-API-Key": token, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = response.headers.get("content-type")?.includes("json") ? await response.json() : {};
  if (!response.ok) throw new Error(data.title || `HTTP ${response.status}`);
  return data;
}
