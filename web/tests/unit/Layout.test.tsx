import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { EditorView } from "@codemirror/view";
import { http, HttpResponse } from "msw";
import { expect, it, vi } from "vitest";

import { Layout } from "@/app/Layout";
import { createHandlers, initialNotes } from "@/mocks/handlers";
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
  expect(await within(list).findByText("Note 46")).toBeInTheDocument();
  expect(within(list).queryByText("Note 47")).not.toBeInTheDocument();
  fireEvent.click(within(list).getByRole("button", { name: "Load more" }));
  expect(await within(list).findByText("Note 59")).toBeInTheDocument();
  expect(within(list).queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
});

it("saves edits with If-Match, the CSRF token and the file's own bytes", async () => {
  const notes = initialNotes();
  const sent: (string | null)[] = [];
  document.cookie = "opennote_csrf=token-1";
  server.use(
    http.put("/api/v1/notes/:id/content", ({ request }) => {
      sent.push(request.headers.get("x-csrf-token"));
    }),
    ...createHandlers(notes),
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
  await waitFor(() => expect(screen.getByRole("contentinfo")).toHaveTextContent("Saved"));

  const saved = new TextDecoder("utf-8", { ignoreBOM: true }).decode(notes[1].bytes);
  expect(saved).toBe("﻿---\r\ntags: [alpha]\r\n---\r\n# Plan\r\n\r\n- [ ] First step\r\n\r\n- [ ] Second");
  expect(notes[1].meta.revision).toBe(2);
  expect(sent).toEqual(["token-1"]);
  document.cookie = "opennote_csrf=; max-age=0";
});

it("autosaves after typing stops", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    const notes = initialNotes();
    server.use(...createHandlers(notes));
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /^Welcome/ }));
    await waitFor(() => expect(editorDom()).toBeTruthy());
    const view = editorView();
    act(() => view.dispatch({ changes: { from: 0, insert: "x" } }));
    await act(() => vi.advanceTimersByTimeAsync(2000));
    await waitFor(() => expect(notes[0].meta.revision).toBe(2));
    expect(new TextDecoder().decode(notes[0].bytes).startsWith("x# Welcome")).toBe(true);
  } finally {
    vi.useRealTimers();
  }
});

it("keeps edits and does not overwrite when the note changed elsewhere", async () => {
  const notes = initialNotes();
  server.use(...createHandlers(notes));
  renderApp();
  fireEvent.click(await screen.findByRole("button", { name: /^Welcome/ }));
  await waitFor(() => expect(editorDom()).toBeTruthy());
  notes[0].meta.revision = 5; // another client saved
  const before = notes[0].bytes;

  const view = editorView();
  act(() => view.dispatch({ changes: { from: 0, insert: "mine " } }));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("changed elsewhere");
  expect(notes[0].bytes).toBe(before);
  expect(view.state.sliceDoc().startsWith("mine ")).toBe(true);
});

it("opens a non-UTF-8 note read-only", async () => {
  server.use(...createHandlers());
  renderApp();
  fireEvent.click(await screen.findByRole("button", { name: /^Legacy/ }));
  expect(await screen.findByRole("note")).toHaveTextContent("not UTF-8");
  expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  expect(editorView().state.readOnly).toBe(true);
});
