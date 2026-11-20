import { api, settings } from "./common.js";

const $ = (id) => document.getElementById(id);
const status = (text) => ($("status").textContent = text);
const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
$("title").value = tab?.title ?? "";

// Runs in the page: the selection's HTML, or the main content (article, main, body).
function grab(selectionOnly) {
  const selection = window.getSelection();
  if (selectionOnly) {
    if (!selection || selection.isCollapsed) return null;
    const box = document.createElement("div");
    for (let i = 0; i < selection.rangeCount; i++) {
      box.append(selection.getRangeAt(i).cloneContents());
    }
    return box.innerHTML;
  }
  return (document.querySelector("article") || document.querySelector("main") || document.body)
    .innerHTML;
}

async function clip(selectionOnly) {
  try {
    const { vaultId, folder } = await settings();
    if (!vaultId) throw new Error("Pick a vault in the extension options first.");
    const [{ result: html }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: grab,
      args: [selectionOnly],
    });
    if (html == null) throw new Error("Select some text on the page first.");
    status("Saving…");
    const note = await api("/api/v1/clips", {
      method: "POST",
      body: {
        vault_id: vaultId,
        url: tab.url,
        title: $("title").value,
        html,
        folder: folder || "Clippings",
        tags: $("tags").value.split(",").map((t) => t.trim()).filter(Boolean),
      },
    });
    status(`Saved as ${note.path}`);
  } catch (error) {
    status(error.message);
  }
}

$("selection").addEventListener("click", () => clip(true));
$("page").addEventListener("click", () => clip(false));
