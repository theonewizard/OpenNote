// Note bytes <-> editor text without changing a single byte (storage contract: bytes are
// sacred). UTF-8 only: a BOM stays in the text as U+FEFF, and the editor splits lines on
// the file's own separator only, so other line-ending characters stay inside lines. Read
// the document back with state.sliceDoc(), which joins lines with that separator;
// doc.toString() always joins with "\n".

export type DecodedNote =
  | { editable: true; text: string; lineSeparator: string }
  | { editable: false; reason: "not-utf8" };

const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
const encoder = new TextEncoder();

export function decodeNote(bytes: Uint8Array): DecodedNote {
  let text: string;
  try {
    text = decoder.decode(bytes);
  } catch {
    return { editable: false, reason: "not-utf8" };
  }
  return { editable: true, text, lineSeparator: firstLineSeparator(text) };
}

export function encodeNote(text: string): Uint8Array<ArrayBuffer> {
  return encoder.encode(text);
}

// The first separator in the file wins; a file without one gets "\n".
export function firstLineSeparator(text: string): string {
  const match = /\r\n|\r|\n/.exec(text);
  return match ? match[0] : "\n";
}
