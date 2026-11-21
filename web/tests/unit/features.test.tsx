import { EditorView } from "@codemirror/view";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { File as NodeFile } from "node:buffer";
import { expect, it, onTestFinished, vi } from "vitest";

import { Layout } from "@/app/Layout";
import { createHandlers, createRest, initialNotes } from "@/mocks/handlers";
import { FakeSyncServer } from "@/mocks/sync-server";
import { server } from "./setup";

function setup() {
  const notes = initialNotes();
  const sync = new FakeSyncServer();
  const rest = createRest(notes, sync);
  server.use(...createHandlers(notes, sync, rest));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Layout user={rest.user} />
    </QueryClientProvider>,
  );
  return { notes, sync, rest };
}

const nav = () => screen.getByRole("navigation");
const list = () => screen.getByRole("region", { name: "Note list" });
const toolbar = () => screen.getByRole("toolbar", { name: "Note actions" });
const dialog = () => screen.getByRole("dialog");
const editorDom = () => screen.queryByTestId("note-editor")?.shadowRoot?.querySelector<HTMLElement>(".cm-editor");

async function openNote(name: RegExp) {
  fireEvent.click(await within(list()).findByRole("button", { name }));
  await waitFor(() => expect(editorDom()).toBeTruthy());
  // The actions need the note's metadata from the server.
  await waitFor(() => expect(within(toolbar()).getByRole("button", { name: "Rename" })).toBeEnabled());
}

async function submitDialog(label: string, value: string, button: string) {
  fireEvent.change(within(dialog()).getByLabelText(label), { target: { value } });
  fireEvent.click(within(dialog()).getByRole("button", { name: button }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}

it("creates a note in the open folder and opens it", async () => {
  const { sync } = setup();
  fireEvent.click(await within(nav()).findByRole("button", { name: "Meetings" }));
  fireEvent.click(within(nav()).getByRole("button", { name: "New note" }));
  expect(dialog()).toHaveTextContent("New note in Meetings");
  await submitDialog("Name", "Standup", "Create");
  expect(await within(list()).findByRole("button", { name: /^Standup/ })).toBeInTheDocument();
  expect((await sync.liveFiles()).some(([, f]) => f.path === "Meetings/Standup.md")).toBe(true);
  await waitFor(() => expect(screen.getByRole("main")).toHaveTextContent("Standup"));
});

it("shows the server's reason when a note cannot be created", async () => {
  setup();
  await within(list()).findByRole("button", { name: /^Welcome/ });
  fireEvent.click(within(nav()).getByRole("button", { name: "New note" }));
  fireEvent.change(within(dialog()).getByLabelText("Name"), { target: { value: "Welcome" } });
  fireEvent.click(within(dialog()).getByRole("button", { name: "Create" }));
  expect(await within(dialog()).findByRole("alert")).toHaveTextContent("A file with this path exists");
});

it("renames a note with link updates and keeps it open", async () => {
  const { sync, notes } = setup();
  await openNote(/^Welcome/);
  fireEvent.click(within(toolbar()).getByRole("button", { name: "Rename" }));
  expect(within(dialog()).getByLabelText("Update links in other notes")).toBeChecked();
  await submitDialog("Path in the vault", "Meetings/Hello", "Rename");
  await waitFor(() => expect(sync.files.get(notes[0].meta.id)!.path).toBe("Meetings/Hello.md"));
  expect(await within(screen.getByRole("main")).findByRole("heading", { name: "Hello" })).toBeInTheDocument();
});

it("deletes a note to the Trash and restores it", async () => {
  const { sync, notes } = setup();
  await openNote(/^Welcome/);
  fireEvent.click(within(toolbar()).getByRole("button", { name: "Delete" }));
  fireEvent.click(within(dialog()).getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(sync.files.get(notes[0].meta.id)!.deleted).toBe(true));
  await waitFor(() => expect(screen.getByRole("main")).toHaveTextContent("No note selected"));
  await waitFor(() => expect(within(list()).queryByRole("button", { name: /^Welcome/ })).not.toBeInTheDocument());

  fireEvent.click(within(nav()).getByRole("button", { name: "Trash" }));
  fireEvent.click(await within(list()).findByRole("button", { name: "Restore" }));
  await waitFor(() => expect(sync.files.get(notes[0].meta.id)!.deleted).toBe(false));
  expect(await within(list()).findByText("Trash is empty")).toBeInTheDocument();
});

it("marks a favorite, lists it under Favorites and keeps other opennote keys", async () => {
  const { rest, notes } = setup();
  rest.properties.set(notes[0].meta.id, { opennote: { status: "draft" } });
  await openNote(/^Welcome/);
  fireEvent.click(within(toolbar()).getByRole("button", { name: "☆ Favorite" }));
  expect(await within(toolbar()).findByRole("button", { name: "★ Favorite", pressed: true })).toBeInTheDocument();
  expect(rest.properties.get(notes[0].meta.id)).toEqual({ opennote: { status: "draft", favorite: true } });
  fireEvent.click(within(nav()).getByRole("button", { name: "Favorites" }));
  expect(await within(list()).findByRole("button", { name: /^Welcome/ })).toBeInTheDocument();
  expect(within(list()).queryByRole("button", { name: /^Plan/ })).not.toBeInTheDocument();
});

it("archives a note: it leaves the folder lists and shows under Archive", async () => {
  setup();
  await openNote(/^Welcome/);
  fireEvent.click(within(toolbar()).getByRole("button", { name: "Archive" }));
  await waitFor(() => expect(within(list()).queryByRole("button", { name: /^Welcome/ })).not.toBeInTheDocument());
  fireEvent.click(within(nav()).getByRole("button", { name: "Archive" }));
  expect(await within(list()).findByRole("button", { name: /^Welcome/ })).toBeInTheDocument();
});

it("sorts the note list", async () => {
  setup();
  const titles = () => within(list()).getAllByRole("button").map((b) => b.querySelector("span")?.textContent);
  await within(list()).findByRole("button", { name: /^Welcome/ });
  expect(titles()).toEqual(["Legacy", "Plan", "Welcome"]);
  fireEvent.change(within(list()).getByLabelText("Sort"), { target: { value: "title" } });
  await waitFor(() => expect(titles()).toEqual(["Legacy", "Plan", "Welcome"]));
  fireEvent.change(within(list()).getByLabelText("Sort"), { target: { value: "-modified_at" } });
  await waitFor(() => expect(within(list()).getByLabelText("Sort")).toHaveValue("-modified_at"));
});

it("lists tags with counts, filters by tag and edits a note's tags", async () => {
  const { rest, notes } = setup();
  const tags = await within(nav()).findByRole("list", { name: "Tags" });
  fireEvent.click(within(tags).getByRole("button", { name: /^#alpha\s*1$/ }));
  expect(await within(list()).findByRole("button", { name: /^Plan/ })).toBeInTheDocument();
  expect(within(list()).queryByRole("button", { name: /^Welcome/ })).not.toBeInTheDocument();

  fireEvent.click(within(nav()).getByRole("button", { name: "All notes" }));
  await openNote(/^Welcome/);
  fireEvent.click(within(toolbar()).getByRole("button", { name: "Tags" }));
  await submitDialog("Tags, separated by commas or spaces", "#alpha, beta", "Save tags");
  await waitFor(() => expect(rest.tags.get(notes[0].meta.id)).toEqual(["alpha", "beta"]));
  expect(await within(nav()).findByRole("button", { name: /^#alpha\s*2$/ })).toBeInTheDocument();
  expect(within(toolbar()).getByRole("list", { name: "Tags" })).toHaveTextContent("#alpha#beta");
});

it("searches with grammar hints and shows snippets with the matches marked", async () => {
  setup();
  const box = await screen.findByRole("searchbox", { name: "Search notes" });
  fireEvent.focus(box);
  const hints = screen.getByRole("group", { name: "Search syntax" });
  fireEvent.click(within(hints).getByRole("button", { name: /^tag:/ }));
  expect(box).toHaveValue("tag:");
  fireEvent.change(box, { target: { value: "OpenNote" } });
  fireEvent.submit(box);
  expect(await within(list()).findByRole("heading", { name: "Search: OpenNote" })).toBeInTheDocument();
  const hit = await within(list()).findByRole("button", { name: /^Welcome/ });
  expect(hit.querySelector("mark")).toHaveTextContent("OpenNote");
});

it("uploads an attachment next to the note and embeds it at the cursor", async () => {
  const { sync, rest } = setup();
  // Node's fetch cannot send jsdom's FormData and File, so this upload uses Node's, and the
  // handler reads the fields from the raw body (Playwright tests a real browser upload).
  const nodeForm = await new Response("a=1", { headers: { "Content-Type": "application/x-www-form-urlencoded" } }).formData();
  vi.stubGlobal("FormData", nodeForm.constructor);
  onTestFinished(() => void vi.unstubAllGlobals());
  // Focusing the editor after the insert reads the shadow-root selection through
  // execCommand (CodeMirror's Safari path), which jsdom lacks.
  document.execCommand = () => false;
  let fields: Record<string, string> = {};
  server.use(
    http.post("/api/v1/attachments", async ({ request }) => {
      const raw = await request.text();
      fields = Object.fromEntries([...raw.matchAll(/name="(\w+)"(?:; filename="[^"]*")?\r\n(?:Content-Type: [^\r]*\r\n)?\r\n([^\r]*)/g)].map((m) => [m[1], m[2]]));
      const id = "018f5a40-2d14-7b9c-8e3a-0000000000b1";
      sync.seed(id, fields.path, new Uint8Array([1]), "attachment");
      rest.mediaTypes.set(id, "image/png");
      return HttpResponse.json({ id, path: fields.path, media_type: "image/png" }, { status: 201 });
    }),
  );
  await openNote(/^Welcome/);
  const file = new NodeFile([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "my/photo.png", { type: "image/png" });
  fireEvent.change(screen.getByLabelText("Attachment file"), { target: { files: [file] } });
  await waitFor(() => expect(fields.path).toBe("my_photo.png"));
  expect(fields.vault_id).toBe(rest.vaults[0].id);
  const view = EditorView.findFromDOM(editorDom()!)!;
  await waitFor(() => expect(view.state.sliceDoc()).toContain("![[my_photo.png]]"));
  // The image shows under its line once the vault's attachments are loaded again.
  await waitFor(() => expect(editorDom()?.querySelector("img.cm-embed-image")).toBeTruthy());
  expect(editorDom()!.querySelector("img")!.getAttribute("src")).toBe("/api/v1/attachments/018f5a40-2d14-7b9c-8e3a-0000000000b1/content");
});

it("lists a folder's attachments and previews an image", async () => {
  const { sync, rest } = setup();
  sync.seed("018f5a40-2d14-7b9c-8e3a-0000000000a1", "Meetings/board.png", new Uint8Array([1, 2, 3]), "attachment");
  rest.mediaTypes.set("018f5a40-2d14-7b9c-8e3a-0000000000a1", "image/png");
  fireEvent.click(await within(nav()).findByRole("button", { name: "Meetings" }));
  const attachments = await within(list()).findByRole("list", { name: "Attachments" });
  fireEvent.click(within(attachments).getByRole("button", { name: "board.png" }));
  const img = await within(screen.getByRole("main")).findByRole("img", { name: "board.png" });
  expect(img).toHaveAttribute("src", "/api/v1/attachments/018f5a40-2d14-7b9c-8e3a-0000000000a1/content");
});

it("opens a wiki-link target with Ctrl-click", async () => {
  setup();
  await openNote(/^Welcome/);
  const link = await waitFor(() => {
    const found = editorDom()!.querySelector(".cm-wikilink");
    expect(found).toBeTruthy();
    return found!;
  });
  // jsdom has no layout, so posAtCoords cannot place a click: point it at the link.
  const view = EditorView.findFromDOM(editorDom()!)!;
  const at = view.state.sliceDoc().indexOf("[[Projects");
  view.posAtCoords = () => at + 3;
  fireEvent.mouseDown(link, { ctrlKey: true, button: 0 });
  expect(await within(screen.getByRole("main")).findByRole("heading", { name: "Plan" })).toBeInTheDocument();
});

it("creates, renames and deletes a folder", async () => {
  setup();
  await within(list()).findByRole("button", { name: /^Welcome/ });
  fireEvent.click(within(nav()).getByRole("button", { name: "New folder" }));
  await submitDialog("Name", "Ideas", "Create");
  expect(await within(list()).findByRole("heading", { name: "Ideas" })).toBeInTheDocument();
  fireEvent.click(within(list()).getByRole("button", { name: "Rename" }));
  await submitDialog("Path in the vault", "Thoughts", "Rename");
  expect(await within(nav()).findByRole("button", { name: "Thoughts" })).toBeInTheDocument();
  fireEvent.click(within(list()).getByRole("button", { name: "Delete" }));
  fireEvent.click(within(dialog()).getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(within(nav()).queryByRole("button", { name: "Thoughts" })).not.toBeInTheDocument());

  fireEvent.click(within(nav()).getByRole("button", { name: "Meetings" }));
  fireEvent.click(await within(list()).findByRole("button", { name: "Delete" }));
  fireEvent.click(within(dialog()).getByRole("button", { name: "Delete" }));
  expect(await within(dialog()).findByRole("alert")).toHaveTextContent("Folder not empty");
});

it("manages the vault, its members and devices in Settings", async () => {
  const { rest } = setup();
  await within(list()).findByRole("button", { name: /^Welcome/ });
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  const main = screen.getByRole("main");
  expect(await within(main).findByText("Dana (dana), administrator")).toBeInTheDocument();

  fireEvent.click(within(main).getByLabelText(/AI features/));
  await waitFor(() => expect(rest.vaults[0].settings.ai_enabled).toBe(true));
  await waitFor(() => expect(within(main).getByLabelText(/AI features/)).toBeChecked());

  fireEvent.click(within(main).getByRole("button", { name: "Rename vault" }));
  await submitDialog("Name", "Personal", "Rename");
  expect(await within(nav()).findByRole("heading", { name: "Personal" })).toBeInTheDocument();

  fireEvent.change(await within(main).findByLabelText("Add member"), { target: { value: rest.users[1].id } });
  expect(await within(main).findByLabelText("Role of bob")).toHaveValue("editor");
  fireEvent.change(within(main).getByLabelText("Role of bob"), { target: { value: "viewer" } });
  await waitFor(() => expect(rest.members.find((m) => m.username === "bob")?.role).toBe("viewer"));

  const devices = within(main).getByRole("region", { name: "Devices" });
  fireEvent.click(await within(devices).findByRole("button", { name: "Revoke" }));
  await waitFor(() => expect(within(devices).queryByText(/MacBook/)).not.toBeInTheDocument());
  expect(within(devices).getByText(/this device/)).toBeInTheDocument();

  fireEvent.click(within(main).getByRole("button", { name: "Delete vault" }));
  fireEvent.change(within(dialog()).getByLabelText("Type the vault's name to confirm"), { target: { value: "nope" } });
  fireEvent.click(within(dialog()).getByRole("button", { name: "Delete vault" }));
  expect(await within(dialog()).findByRole("alert")).toHaveTextContent("Type the vault's name to confirm.");
  expect(rest.vaults).toHaveLength(1);
});

it("disables note actions for a viewer", async () => {
  const notes = initialNotes();
  const sync = new FakeSyncServer();
  const rest = createRest(notes, sync);
  rest.vaults[0].role = "viewer";
  server.use(...createHandlers(notes, sync, rest));
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Layout user={rest.user} />
    </QueryClientProvider>,
  );
  fireEvent.click(await within(list()).findByRole("button", { name: /^Welcome/ }));
  await waitFor(() => expect(editorDom()).toBeTruthy());
  expect(within(nav()).getByRole("button", { name: "New note" })).toBeDisabled();
  expect(within(toolbar()).getByRole("button", { name: "Delete" })).toBeDisabled();
});
