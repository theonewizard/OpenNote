import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { markdown } from "@codemirror/lang-markdown";
import { yamlFrontmatter } from "@codemirror/lang-yaml";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorState, RangeSetBuilder, StateEffect, StateField } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  MatchDecorator,
  ViewPlugin,
  WidgetType,
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
  { tag: tags.propertyName, opacity: "0.7" },
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

const WIKI_LINK = /(!?)\[\[([^\]\r\n]+)\]\]/g;

/** The note or file a wiki-link names: without alias, heading or block reference. */
function linkTarget(inner: string): string {
  return inner.split("|")[0].split("#")[0].trim();
}

const IMAGE = /\.(png|jpe?g|gif|webp|avif|bmp|svg)$/i;

class ImageWidget extends WidgetType {
  readonly url: string;
  readonly alt: string;
  constructor(url: string, alt: string) {
    super();
    this.url = url;
    this.alt = alt;
  }
  eq(other: ImageWidget) {
    return other.url === this.url;
  }
  toDOM() {
    const img = document.createElement("img");
    img.src = this.url;
    img.alt = this.alt;
    img.className = "cm-embed-image";
    const box = document.createElement("div");
    box.append(img);
    return box;
  }
}

const refreshEmbeds = StateEffect.define<null>();
// Image embeds are scanned on every change; a very large note shows none rather than slow
// down typing.
const MAX_EMBED_SCAN = 1 << 20;

/** Shows each resolvable image embed (![[x.png]]) under its line, markup left in place. */
function imageEmbeds(resolve: () => ((target: string) => string | undefined) | undefined) {
  const build = (state: EditorState): DecorationSet => {
    const url = resolve();
    if (!url || state.doc.length > MAX_EMBED_SCAN) return Decoration.none;
    const builder = new RangeSetBuilder<Decoration>();
    for (let n = 1; n <= state.doc.lines; n++) {
      const line = state.doc.line(n);
      for (const match of line.text.matchAll(WIKI_LINK)) {
        const target = linkTarget(match[2]);
        const src = match[1] && IMAGE.test(target) ? url(target) : undefined;
        if (src) builder.add(line.to, line.to, Decoration.widget({ widget: new ImageWidget(src, target), block: true, side: 1 }));
      }
    }
    return builder.finish();
  };
  return StateField.define<DecorationSet>({
    create: build,
    update: (value, tr) => (tr.docChanged || tr.effects.some((e) => e.is(refreshEmbeds)) ? build(tr.state) : value),
    provide: (field) => EditorView.decorations.from(field),
  });
}

/** Ctrl/Cmd-click on a wiki-link calls `open` with its target. */
function linkClicks(open: (target: string, embed: boolean) => void) {
  return EditorView.domEventHandlers({
    mousedown(event, view) {
      if (!(event.metaKey || event.ctrlKey) || event.button !== 0) return false;
      const pos = view.posAtCoords({ x: event.clientX, y: event.clientY });
      if (pos === null) return false;
      const line = view.state.doc.lineAt(pos);
      for (const match of line.text.matchAll(WIKI_LINK)) {
        const from = line.from + match.index;
        if (pos >= from && pos <= from + match[0].length) {
          event.preventDefault();
          open(linkTarget(match[2]), match[1] === "!");
          return true;
        }
      }
      return false;
    },
  });
}

const theme = EditorView.theme({
  "&": { height: "100%" },
  ".cm-scroller": { fontFamily: "inherit", lineHeight: "1.6" },
  ".cm-content": { padding: "1rem 0" },
  ".cm-line": { padding: "0 1rem" },
  ".cm-wikilink": { color: "var(--color-primary)", textDecoration: "underline" },
  ".cm-embed-image": { maxWidth: "100%", maxHeight: "24rem", margin: "0.25rem 0" },
});

export interface MarkdownEditorProps {
  text: string;
  lineSeparator: string;
  readOnly: boolean;
  onChange: (text: string) => void;
  onSave: () => void;
  /** Ctrl/Cmd-click on a wiki-link or embed */
  onOpenLink?: (target: string, embed: boolean) => void;
  /** The URL of an embedded image, when the target resolves to one */
  imageUrl?: (target: string) => string | undefined;
  /** Set to a function that inserts text at the cursor */
  insertRef?: { current?: (text: string) => void };
}

// Mounted once per opened note revision (the caller keys it); later prop changes to
// text and lineSeparator are ignored, callbacks are always the latest; a new imageUrl
// redraws the image embeds.
//
// The editor lives in a shadow root: CodeMirror then installs its styles as constructed
// style sheets, which the web container's CSP (no 'unsafe-inline' styles) allows, instead
// of a <style> element, which it blocks.
export function MarkdownEditor({ text, lineSeparator, readOnly, onChange, onSave, onOpenLink, imageUrl, insertRef }: MarkdownEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView>(undefined);
  const callbacks = useRef({ onChange, onSave, onOpenLink, imageUrl });
  useEffect(() => {
    callbacks.current = { onChange, onSave, onOpenLink, imageUrl };
  });
  useEffect(() => {
    view.current?.dispatch({ effects: refreshEmbeds.of(null) });
  }, [imageUrl]);

  useEffect(() => {
    const shadow = host.current!.shadowRoot ?? host.current!.attachShadow({ mode: "open" });
    const parent = document.createElement("div");
    parent.style.height = "100%";
    shadow.append(parent);
    const editor = new EditorView({
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
          // YAML frontmatter is parsed as YAML; without this, "key: value" above the closing
          // "---" reads as a Markdown setext heading.
          yamlFrontmatter({ content: markdown() }),
          syntaxHighlighting(markdownStyle),
          wikiLinkPlugin,
          imageEmbeds(() => callbacks.current.imageUrl),
          linkClicks((target, embed) => callbacks.current.onOpenLink?.(target, embed)),
          theme,
          EditorView.contentAttributes.of({ "aria-label": "Note text" }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) callbacks.current.onChange(update.state.sliceDoc());
          }),
        ],
      }),
    });
    view.current = editor;
    if (insertRef) {
      insertRef.current = (insert) => {
        editor.dispatch(editor.state.replaceSelection(insert));
        editor.focus();
      };
    }
    return () => {
      if (insertRef) insertRef.current = undefined;
      view.current = undefined;
      editor.destroy();
      parent.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see the comment above
  }, []);

  return <div ref={host} data-testid="note-editor" className="h-full" />;
}
