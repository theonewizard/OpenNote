// A line diff for history and conflicts (roadmap P5-05, P5-06): the server leaves diffs to
// the client (sync server plan R-P5-007). Longest common subsequence over the lines that
// differ after the common start and end are taken off.

export interface DiffLine {
  kind: "same" | "added" | "removed";
  text: string;
}

/** Above this many cells (changed lines before × after) the table is too big to build. */
const MAX_CELLS = 4_000_000;

/** The lines of `after` against `before`, or null when the changed part is too large. */
export function lineDiff(before: string, after: string): DiffLine[] | null {
  const a = before.split(/\r?\n/);
  const b = after.split(/\r?\n/);
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let end = 0;
  while (end < a.length - start && end < b.length - start && a[a.length - 1 - end] === b[b.length - 1 - end]) end++;
  const x = a.slice(start, a.length - end);
  const y = b.slice(start, b.length - end);
  if (x.length * y.length > MAX_CELLS) return null;

  // lcs[i][j]: common lines of x[i..] and y[j..], in one flat array.
  const width = y.length + 1;
  const lcs = new Uint32Array((x.length + 1) * width);
  for (let i = x.length - 1; i >= 0; i--) {
    for (let j = y.length - 1; j >= 0; j--) {
      lcs[i * width + j] = x[i] === y[j] ? lcs[(i + 1) * width + j + 1] + 1 : Math.max(lcs[(i + 1) * width + j], lcs[i * width + j + 1]);
    }
  }
  const middle: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < x.length || j < y.length) {
    if (i < x.length && j < y.length && x[i] === y[j]) {
      middle.push({ kind: "same", text: x[i++] });
      j++;
    } else if (i < x.length && (j === y.length || lcs[(i + 1) * width + j] >= lcs[i * width + j + 1])) {
      middle.push({ kind: "removed", text: x[i++] });
    } else {
      middle.push({ kind: "added", text: y[j++] });
    }
  }
  const same = (lines: string[]) => lines.map((text): DiffLine => ({ kind: "same", text }));
  return [...same(a.slice(0, start)), ...middle, ...same(a.slice(a.length - end))];
}
