// Every corpus note must come back byte for byte after a trip through the editor's
// document model (roadmap P3-04, testing strategy §3).
import { readdirSync, readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { EditorState } from "@codemirror/state";
import { describe, expect, it } from "vitest";

import { decodeNote, encodeNote } from "@/editor/bytes";

const corpus = path.resolve(import.meta.dirname, "../../../tests/compatibility/vaults");
const cases = readdirSync(corpus).filter((name) => existsSync(path.join(corpus, name, "note.md")));

const hex = (bytes: Uint8Array) => Buffer.from(bytes).toString("hex");

function load(text: string, lineSeparator: string) {
  return EditorState.create({ doc: text, extensions: EditorState.lineSeparator.of(lineSeparator) });
}

describe("corpus round trip through the editor document", () => {
  it.each(cases)("%s", (name) => {
    const bytes = new Uint8Array(readFileSync(path.join(corpus, name, "note.md")));
    const decoded = decodeNote(bytes);
    if (!decoded.editable) {
      // Only non-UTF-8 files are refused; they open read-only and are never re-encoded.
      expect(name).toMatch(/^enc-/);
      return;
    }
    const state = load(decoded.text, decoded.lineSeparator);
    expect(hex(encodeNote(state.sliceDoc()))).toBe(hex(bytes));
  });
});

describe("edits keep the file's conventions", () => {
  it("a new line in a CRLF file is CRLF and the BOM survives", () => {
    const bytes = encodeNote("﻿# Title\r\nbody\r\n");
    const decoded = decodeNote(bytes);
    if (!decoded.editable) throw new Error("expected UTF-8");
    const state = load(decoded.text, decoded.lineSeparator);
    const end = state.doc.length;
    const edited = state.update({ changes: { from: end, insert: state.lineBreak + "more" } }).state;
    expect(edited.sliceDoc()).toBe("﻿# Title\r\nbody\r\n\r\nmore");
  });

  it("refuses Windows-1252 bytes instead of re-encoding them", () => {
    expect(decodeNote(new Uint8Array([0x63, 0x61, 0x66, 0xe9]))).toEqual({
      editable: false,
      reason: "not-utf8",
    });
  });
});
