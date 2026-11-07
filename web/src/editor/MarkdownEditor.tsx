import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { markdown } from "@codemirror/lang-markdown";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  MatchDecorator,
  ViewPlugin,
  type DecorationSet,
  type ViewUpdate,
  keymap,
} from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { useEffect, useRef } from "react";

// Styled Markdown source: headings, emphasis, code and links are styled in place, the
// markup stays visible and the text is never re-rendered (storage contract).
const markdownStyle = HighlightStyle.define([
  { tag: tags.heading1, fontSize: "1.6em", fontWeight: "700" },
  { tag: tags.heading2, fontSize: "1.35em", fontWeight: "700" },
  { tag: tags.heading3, fontSize: "1.15em", fontWeight: "700" },
  { tag: [tags.heading4, tags.heading5, tags.heading6], fontWeight: "700" },
  { tag: tags.strong, fontWeight: "700" },
  { tag: tags.emphasis, fontStyle: "italic" },
  { tag: tags.strikethrough, textDecoration: "line-through" },
  { tag: tags.monospace, fontFamily: "ui-monospace, monospace" },
  { tag: [tags.link, tags.url], color: "var(--color-primary)" },
  { tag: [tags.processingInstruction, tags.meta], opacity: "0.55" },
]);

// [[target]], [[target|alias]] and ![[embed]] (Obsidian wiki-links).
const wikiLinks = new MatchDecorator({
  regexp: /!?\[\[[^\]\r\n]+\]\]/g,
  decoration: Decoration.mark({ class: "cm-wikilink" }),
});

const wikiLinkPlugin = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet;
    constructor(view: EditorView) {
      this.decorations = wikiLinks.createDeco(view);
    }
    update(update: ViewUpdate) {
      this.decorations = wikiLinks.updateDeco(update, this.decorations);
    }
  },
  { decorations: (plugin) => plugin.decorations },
);

const theme = EditorView.theme({
  "&": { height: "100%" },
  ".cm-scroller": { fontFamily: "inherit", lineHeight: "1.6" },
  ".cm-content": { padding: "1rem 0" },
  ".cm-line": { padding: "0 1rem" },
  ".cm-wikilink": { color: "var(--color-primary)", textDecoration: "underline" },
});

export interface MarkdownEditorProps {
  text: string;
  lineSeparator: string;
  readOnly: boolean;
  onChange: (text: string) => void;
  onSave: () => void;
}

// Mounted once per opened note revision (the caller keys it); later prop changes to
// text and lineSeparator are ignored, callbacks are always the latest.
//
// The editor lives in a shadow root: CodeMirror then installs its styles as constructed
// style sheets, which the web container's CSP (no 'unsafe-inline' styles) allows, instead
// of a <style> element, which it blocks.
export function MarkdownEditor({ text, lineSeparator, readOnly, onChange, onSave }: MarkdownEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const callbacks = useRef({ onChange, onSave });
  useEffect(() => {
    callbacks.current = { onChange, onSave };
  });

  useEffect(() => {
    const shadow = host.current!.shadowRoot ?? host.current!.attachShadow({ mode: "open" });
    const parent = document.createElement("div");
    parent.style.height = "100%";
    shadow.append(parent);
    const view = new EditorView({
      root: shadow,
      parent,
      state: EditorState.create({
        doc: text,
        extensions: [
          EditorState.lineSeparator.of(lineSeparator),
          EditorState.readOnly.of(readOnly),
          EditorView.lineWrapping,
          history(),
          keymap.of([
            { key: "Mod-s", preventDefault: true, run: () => (callbacks.current.onSave(), true) },
            ...defaultKeymap,
            ...historyKeymap,
          ]),
          markdown(),
          syntaxHighlighting(markdownStyle),
          wikiLinkPlugin,
          theme,
          EditorView.contentAttributes.of({ "aria-label": "Note text" }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) callbacks.current.onChange(update.state.sliceDoc());
          }),
        ],
      }),
    });
    return () => {
      view.destroy();
      parent.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see the comment above
  }, []);

  return <div ref={host} data-testid="note-editor" className="h-full" />;
}
