import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { EditorView } from "@codemirror/view";
import { http, HttpResponse } from "msw";
import { expect, it, vi } from "vitest";

import { Layout } from "@/app/Layout";
import { createHandlers, initialNotes } from "@/mocks/handlers";
import { FakeSyncServer } from "@/mocks/sync-server";
import { server } from "./setup";

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Layout />
    </QueryClientProvider>,
  );
}

// The editor renders into a shadow root (see MarkdownEditor).
const editorDom = () => screen.queryByTestId("note-editor")?.shadowRoot?.querySelector<HTMLElement>(".cm-editor");

function editorView() {
  return EditorView.findFromDOM(editorDom()!)!;
}

it("renders the three panes and says when the server cannot be reached", async () => {
  server.use(http.get("/api/v1/vaults", () => HttpResponse.error()));
  renderApp();
  expect(screen.getByRole("navigation")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Note list" })).toBeInTheDocument();
  expect(screen.getByRole("main")).toHaveTextContent("No note selected");
  expect(await screen.findByText("Not connected")).toBeInTheDocument();
  const button = within(screen.getByRole("navigation")).getByRole("button", { name: "New note" });
  expect(button).toBeDisabled();
});

it("lists folders and filters notes by folder", async () => {
  server.use(...createHandlers());
  renderApp();
  const nav = screen.getByRole("navigation");
  expect(await within(nav).findByRole("button", { name: "Alpha" })).toBeInTheDocument();
  const list = screen.getByRole("region", { name: "Note list" });
  expect(await within(list).findByText("Welcome")).toBeInTheDocument();
  fireEvent.click(within(nav).getByRole("button", { name: "Alpha" }));
  expect(await within(list).findByText("Plan")).toBeInTheDocument();
  expect(within(list).queryByText("Welcome")).not.toBeInTheDocument();
});

it("pages through long note lists", async () => {
  const notes = initialNotes();
  const extra = Array.from({ length: 60 }, (_, i) => ({
    meta: { ...notes[0].meta, id: `extra-${i}`, path: `Note ${String(i).padStart(2, "0")}.md`, title: `Note ${String(i).padStart(2, "0")}` },
    bytes: notes[0].bytes,
  }));
  server.use(...createHandlers([...notes, ...extra]));
  renderApp();
  const list = screen.getByRole("region", { name: "Note list" });
  // Sorted by path like the server: Meetings/Legacy, then Note 00 to Note 48 on page one.
  expect(await within(list).findByText("Note 48")).toBeInTheDocument();
  expect(within(list).queryByText("Note 49")).not.toBeInTheDocument();
  fireEvent.click(within(list).getByRole("button", { name: "Load more" }));
  expect(await within(list).findByText("Note 59")).toBeInTheDocument();
  expect(within(list).queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
});

it("saves edits on the device and syncs them with the CSRF token and the file's own bytes", async () => {
  const notes = initialNotes();
  const sync = new FakeSyncServer();
  const sent: (string | null)[] = [];
  document.cookie = "opennote_csrf=token-1";
  server.use(
    http.post("/api/v1/sync/:vault/push", ({ request }) => {
      sent.push(request.headers.get("x-csrf-token"));
    }),
    ...createHandlers(notes, sync),
  );
  renderApp();
  fireEvent.click(await screen.findByRole("button", { name: /^Plan/ }));
  await waitFor(() => expect(editorDom()).toBeTruthy());

  const view = editorView();
  act(() => {
    view.dispatch({ changes: { from: view.state.doc.length, insert: `${view.state.lineBreak}- [ ] Second` } });
  });
  expect(screen.getByRole("contentinfo")).toHaveTextContent("Unsaved changes");
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.getByRole("contentinfo")).toHaveTextContent("1 change not synced yet"));
  await waitFor(() => expect(screen.getByRole("contentinfo")).toHaveTextContent("Saved"), { timeout: 4000 });

  const id = notes[1].meta.id;
  const saved = new TextDecoder("utf-8", { ignoreBOM: true }).decode(await sync.bytes(id));
  expect(saved).toBe("\ufeff---\r\ntags: [alpha]\r\n---\r\n# Plan\r\n\r\n- [ ] First step\r\n\r\n- [ ] Second");
  expect(sync.files.get(id)!.revision).toBe(2);
  expect(sent).toEqual(["token-1"]);
  document.cookie = "opennote_csrf=; max-age=0";
});

it("autosaves after typing stops", async () => {
  // IndexedDB (fake-indexeddb) schedules with setImmediate, which stays real.
  vi.useFakeTimers({ shouldAdvanceTime: true, toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
  try {
    const notes = initialNotes();
    const sync = new FakeSyncServer();
    server.use(...createHandlers(notes, sync));
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /^Welcome/ }));
    await waitFor(() => expect(editorDom()).toBeTruthy());
    const view = editorView();
    act(() => view.dispatch({ changes: { from: 0, insert: "x" } }));
    await act(() => vi.advanceTimersByTimeAsync(600)); // autosave stores it on the device
    await waitFor(() => expect(screen.getByRole("contentinfo")).toHaveTextContent("1 change not synced yet"));
    await act(() => vi.advanceTimersByTimeAsync(2500)); // then the sync after an edit runs
    await waitFor(() => expect(sync.files.get(notes[0].meta.id)!.revision).toBe(2));
    expect(new TextDecoder().decode(await sync.bytes(notes[0].meta.id)).startsWith("x# Welcome")).toBe(true);
  } finally {
    vi.useRealTimers();
  }
});

it("keeps both versions when the note changed elsewhere", async () => {
  const notes = initialNotes();
  const sync = new FakeSyncServer();
  server.use(...createHandlers(notes, sync));
  renderApp();
  fireEvent.click(await screen.findByRole("button", { name: /^Welcome/ }));
  await waitFor(() => expect(editorDom()).toBeTruthy());
  await sync.edit(notes[0].meta.id, new TextEncoder().encode("theirs\n")); // another client saved

  const view = editorView();
  act(() => view.dispatch({ changes: { from: 0, insert: "mine " } }));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  // The fake server does not merge: the edit is kept as a conflict copy and the editor
  // shows the server's version with a note saying where the edit went.
  expect(await screen.findByRole("status", {}, { timeout: 4000 })).toHaveTextContent("Welcome (conflict web");
  await waitFor(() => expect(editorView().state.sliceDoc()).toBe("theirs\n"));
  const copy = (await sync.liveFiles()).find(([, f]) => f.path.startsWith("Welcome (conflict"))!;
  expect(new TextDecoder().decode(await sync.bytes(copy[0])).startsWith("mine # Welcome")).toBe(true);
});

it("keeps editing offline and says the changes are not synced", async () => {
  const notes = initialNotes();
  const sync = new FakeSyncServer();
  server.use(...createHandlers(notes, sync));
  renderApp();
  fireEvent.click(await screen.findByRole("button", { name: /^Welcome/ }));
  await waitFor(() => expect(editorDom()).toBeTruthy());
  sync.offline = true;
  const view = editorView();
  act(() => view.dispatch({ changes: { from: 0, insert: "offline " } }));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.getByRole("contentinfo")).toHaveTextContent("1 change not synced yet (offline)"), { timeout: 4000 });
  sync.offline = false;
  act(() => void dispatchEvent(new Event("online")));
  await waitFor(() => expect(screen.getByRole("contentinfo")).toHaveTextContent("Saved"));
  expect(new TextDecoder().decode(await sync.bytes(notes[0].meta.id)).startsWith("offline # Welcome")).toBe(true);
});

it("opens a non-UTF-8 note read-only", async () => {
  server.use(...createHandlers());
  renderApp();
  fireEvent.click(await screen.findByRole("button", { name: /^Legacy/ }));
  expect(await screen.findByRole("note")).toHaveTextContent("not UTF-8");
  expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  expect(editorView().state.readOnly).toBe(true);
});
