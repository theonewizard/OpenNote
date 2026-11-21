import { useState } from "react";

import { sendJson } from "@/api/client";
import type { Attachment } from "@/api/types";
import { Button } from "@/components/ui/button";
import { FormDialog } from "@/components/ui/form-dialog";
import { attachmentUrl, ifMatch } from "@/features/actions";

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** An attachment: images shown in place; a PDF opens in a new tab, because the CSP's
 * frame-ancestors 'none' forbids framing it (plan R-P3-005); anything else downloads. */
export function AttachmentView(props: {
  attachment: Attachment;
  canEdit: boolean;
  change: <T>(run: () => Promise<T>) => Promise<T>;
  onDeleted: () => void;
}) {
  const { attachment: a, canEdit } = props;
  const [confirm, setConfirm] = useState(false);
  const name = a.path.split("/").at(-1)!;
  const url = attachmentUrl(a.id);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2">
        <h1 className="min-w-0 flex-1 truncate font-semibold">{name}</h1>
        <span className="text-xs text-muted-foreground">
          {a.media_type}, {size(a.size)}
        </span>
        {a.media_type === "application/pdf" ? (
          <a className="text-sm text-primary underline" href={url} target="_blank" rel="noopener noreferrer">
            Open PDF
          </a>
        ) : (
          <a className="text-sm text-primary underline" href={url} download={name}>
            Download
          </a>
        )}
        {canEdit && (
          <Button size="sm" variant="ghost" onClick={() => setConfirm(true)}>
            Delete
          </Button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">
        {a.media_type.startsWith("image/") ? (
          <img src={url} alt={name} className="max-w-full" />
        ) : (
          <p className="text-sm text-muted-foreground">{a.path}</p>
        )}
      </div>
      <FormDialog
        title={`Delete ${name}?`}
        open={confirm}
        onOpenChange={setConfirm}
        submitLabel="Delete"
        destructive
        onSubmit={async () => {
          await props.change(() => sendJson(`/api/v1/attachments/${a.id}`, "DELETE", undefined, ifMatch(a.revision)));
          props.onDeleted();
        }}
      >
        <p className="text-sm">Notes that embed it will show a broken embed.</p>
      </FormDialog>
    </div>
  );
}
