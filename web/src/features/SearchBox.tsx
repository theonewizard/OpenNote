import { useRef, useState, type FormEvent } from "react";

// The filters of the search grammar (docs/api/api-contract.md §5).
const HINTS: [string, string][] = [
  ["tag:", "has a tag or a child tag"],
  ["notebook:", "under a top-level folder"],
  ["path:", "under any folder"],
  ["title:", "word or phrase in the title"],
  ["type:", "attachment type: pdf, image, audio"],
  ["has:", "attachment, task, link, unresolved"],
  ["created:", "date YYYY-MM-DD or range a..b"],
  ["modified:", "date YYYY-MM-DD or range a..b"],
  ["before:", "modified before a date"],
  ["after:", "modified after a date"],
  ["is:", "favorite, archived, conflict"],
];

/** The header search field; shows the grammar's filters while it has focus. */
export function SearchBox({ onSearch }: { onSearch: (q: string) => void }) {
  const [text, setText] = useState("");
  const [hints, setHints] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;
    setHints(false);
    onSearch(text.trim());
  }

  return (
    <form
      role="search"
      className="relative min-w-0 flex-1"
      onSubmit={submit}
      onFocus={() => setHints(true)}
      onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setHints(false)}
    >
      <input
        ref={input}
        type="search"
        aria-label="Search notes"
        placeholder="Search"
        className="w-full rounded border bg-background px-2 py-1"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && setHints(false)}
      />
      {hints && (
        <div
          aria-label="Search syntax"
          role="group"
          className="absolute top-full right-0 left-0 z-10 mt-1 max-h-80 overflow-auto rounded border bg-background p-2 text-sm shadow"
        >
          <p className="px-1 pb-1 text-xs text-muted-foreground">Words match title, text and tags. Quote phrases. Filters:</p>
          {HINTS.map(([key, meaning]) => (
            <button
              key={key}
              type="button"
              tabIndex={-1} // a typing aid: Tab moves on to the rest of the app
              className="flex w-full gap-2 rounded px-1 py-0.5 text-left hover:bg-muted"
              onClick={() => {
                setText((t) => (t && !t.endsWith(" ") ? `${t} ${key}` : `${t}${key}`));
                input.current?.focus();
              }}
            >
              <code className="font-mono">{key}</code>
              <span className="text-muted-foreground">{meaning}</span>
            </button>
          ))}
        </div>
      )}
    </form>
  );
}
