import { expect, it } from "vitest";

import { lineDiff } from "@/lib/diff";

const kinds = (before: string, after: string) => lineDiff(before, after)!.map((l) => `${l.kind[0]} ${l.text}`);

it("marks added and removed lines and keeps the rest", () => {
  expect(kinds("a\nb\nc\nd", "a\nc\nx\nd")).toEqual(["s a", "r b", "s c", "a x", "s d"]);
});

it("treats CRLF and LF line ends alike", () => {
  expect(kinds("a\r\nb", "a\nb")).toEqual(["s a", "s b"]);
});

it("handles an empty side", () => {
  expect(kinds("", "a")).toEqual(["r ", "a a"]);
});

it("gives up on a changed part too large to compare", () => {
  const many = (p: string) => Array.from({ length: 3000 }, (_, i) => `${p}${i}`).join("\n");
  expect(lineDiff(many("a"), many("b"))).toBeNull();
  // A large note with a small change is fine: the common start and end are left out.
  expect(lineDiff(many("a"), `${many("a")}\nend`)!.filter((l) => l.kind !== "same")).toEqual([{ kind: "added", text: "end" }]);
});
