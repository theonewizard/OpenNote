import { api, settings } from "./common.js";

const $ = (id) => document.getElementById(id);
const status = (text) => ($("status").textContent = text);

async function loadVaults(selected) {
  const page = await api("/api/v1/vaults");
  $("vault").replaceChildren(
    ...page.items.map((v) => new Option(v.name, v.id, false, v.id === selected)),
  );
}

$("connect").addEventListener("click", async () => {
  try {
    const origin = new URL($("server").value).origin;
    // Ask for access to this one server only; the extension holds no other host access.
    if (!(await chrome.permissions.request({ origins: [`${origin}/*`] }))) {
      return status("Access to the server was not granted.");
    }
    await chrome.storage.local.set({ server: origin, token: $("token").value });
    await loadVaults();
    status("Connected. Pick a vault and save.");
  } catch (error) {
    status(error.message);
  }
});

$("save").addEventListener("click", async () => {
  await chrome.storage.local.set({ vaultId: $("vault").value, folder: $("folder").value });
  status("Saved.");
});

const current = await settings();
$("server").value = current.server;
$("token").value = current.token;
$("folder").value = current.folder;
if (current.server && current.token) loadVaults(current.vaultId).catch((e) => status(e.message));
