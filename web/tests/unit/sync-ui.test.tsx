// Conflict list and resolution (roadmap P5-05) and note history (P5-06) in the web app.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it } from "vitest";

import { Layout } from "@/app/Layout";
import { createHandlers, createRest, initialNotes } from "@/mocks/handlers";
import { FakeSyncServer } from "@/mocks/sync-server";
import { server } from "./setup";

const enc = (text: string) => new TextEncoder().encode(text);
const dec = (bytes: Uint8Array | undefined) => new TextDecoder().decode(bytes);
const COPY = "018f5a40-2d14-7b9c-8e3a-0000000000c0";

/** The app over the mock notes, with Welcome edited on two devices: the server kept one
 * edit in Welcome and the other in a conflict copy. */
function setup() {
  const notes = initialNotes();
  const sync = new FakeSyncServer();
  const rest = createRest(notes, sync);
  server.use(...createHandlers(notes, sync, rest));
  const welcome = notes[0].meta.id;
  void sync.edit(welcome, enc("# Welcome\n\nEdited on the Mac.\n"));
  sync.seed(COPY, "Welcome (conflict iPhone 2026-11-21).md", enc("# Welcome\n\nEdited on the iPhone.\n"));
  sync.conflicts.push({
    id: "018f5a40-2d14-7b9c-8e3a-0000000000cf",
    vault_id: rest.vaults[0].id,
    file_id: welcome,
    copy_file_id: COPY,
    base_revision: 1,
    their_revision: 2,
    status: "open",
    revision: 1,
    created_at: "2026-11-21T10:00:00.000Z",
    resolved_at: null,
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Layout user={rest.user} />
    </QueryClientProvider>,
  );
  return { sync, welcome };
}

const nav = () => screen.getByRole("navigation");
const list = () => screen.getByRole("region", { name: "Note list" });
const main = () => screen.getByRole("main");

async function openConflict() {
  fireEvent.click(await within(nav()).findByRole("button", { name: /^Conflicts/ }));
  fireEvent.click(await within(list()).findByRole("button", { name: /Welcome\.md.*Copy: Welcome \(conflict iPhone/s }));
  return within(await screen.findByRole("toolbar", { name: "Resolve conflict" }));
}

it("counts open conflicts and shows how the copy differs from the note", async () => {
  setup();
  expect(await within(nav()).findByRole("button", { name: /^Conflicts\s*1$/ })).toBeInTheDocument();
  await openConflict();
  const diff = await within(main()).findByLabelText("Differences between note and copy");
  expect(diff.querySelector('[data-kind="removed"]')).toHaveTextContent("Edited on the Mac.");
  expect(diff.querySelector('[data-kind="added"]')).toHaveTextContent("Edited on the iPhone.");
});

it("keeps the note and deletes the copy, then the conflict is gone", async () => {
  const { sync, welcome } = setup();
  const toolbar = await openConflict();
  fireEvent.click(toolbar.getByRole("button", { name: "Keep note, delete copy" }));
  await waitFor(() => expect(sync.conflicts[0].status).toBe("resolved"));
  expect(sync.files.get(COPY)!.deleted).toBe(true);
  expect(dec(await sync.bytes(welcome))).toContain("Edited on the Mac.");
  await waitFor(() => expect(within(nav()).queryByRole("button", { name: /^Conflicts/ })).not.toBeInTheDocument());
});

it("uses the copy's text in the note", async () => {
  const { sync, welcome } = setup();
  const toolbar = await openConflict();
  fireEvent.click(toolbar.getByRole("button", { name: "Use copy in note" }));
  await waitFor(() => expect(sync.conflicts[0].status).toBe("resolved"));
  expect(dec(await sync.bytes(welcome))).toContain("Edited on the iPhone.");
  expect(sync.files.get(COPY)!.deleted).toBe(true);
});

it("keeps both files when asked", async () => {
  const { sync } = setup();
  const toolbar = await openConflict();
  fireEvent.click(toolbar.getByRole("button", { name: "Keep both" }));
  await waitFor(() => expect(sync.conflicts[0].status).toBe("resolved"));
  expect(sync.files.get(COPY)!.deleted).toBe(false);
});

it("browses a note's history, shows what a revision changed and restores it", async () => {
  const { sync, welcome } = setup();
  fireEvent.click(await within(list()).findByRole("button", { name: /^Welcome\s*Welcome\.md$/ }));
  const toolbar = within(await screen.findByRole("toolbar", { name: "Note actions" }));
  await waitFor(() => expect(toolbar.getByRole("button", { name: "History" })).toBeEnabled());
  fireEvent.click(toolbar.getByRole("button", { name: "History" }));

  const revisions = within(await within(main()).findByRole("list", { name: "Revisions" }));
  expect(await revisions.findByRole("button", { name: /Edited · revision 2 \(current\)/ })).toBeInTheDocument();
  const changes = await within(main()).findByLabelText("Changes in this revision");
  expect(changes.querySelector('[data-kind="added"]')).toHaveTextContent("Edited on the Mac.");

  fireEvent.click(revisions.getByRole("button", { name: /Created · revision 1/ }));
  fireEvent.change(within(main()).getByLabelText("Compare with"), { target: { value: "current" } });
  const against = await within(main()).findByLabelText("Differences from the current note");
  await waitFor(() => expect(against.querySelector('[data-kind="added"]')).toHaveTextContent("This is **OpenNote**."));

  fireEvent.click(within(main()).getByRole("button", { name: "Restore this revision" }));
  await waitFor(async () => expect(dec(await sync.bytes(welcome))).toContain("This is **OpenNote**."));
  expect(sync.files.get(welcome)!.revision).toBe(3);
  // Back in the note after the restore.
  expect(await within(main()).findByRole("heading", { name: "Welcome" })).toBeInTheDocument();
});
