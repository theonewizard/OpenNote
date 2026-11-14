export type SaveState = "saved" | "unsaved" | "saving" | "failed" | "conflict" | "read-only";

export const saveStateText: Record<SaveState, string> = {
  saved: "Saved",
  unsaved: "Unsaved changes",
  saving: "Saving…",
  failed: "Save failed, retrying on the next edit",
  conflict: "Changed elsewhere, not saved",
  "read-only": "Read-only",
};
