import { Dialog } from "@base-ui/react/dialog";
import { useState, type FormEvent, type ReactNode } from "react";

import { errorText } from "@/api/client";
import { Button } from "@/components/ui/button";

interface Props {
  title: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  submitLabel: string;
  destructive?: boolean;
  /** Runs on submit; the dialog closes when it resolves and shows the error when it throws. */
  onSubmit: () => Promise<unknown>;
  children?: ReactNode;
}

/** A modal form: fields as children, one submit button, Cancel, and the server's error. */
export function FormDialog({ title, open, onOpenChange, submitLabel, destructive, onSubmit, children }: Props) {
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      await onSubmit();
      onOpenChange(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) setError(undefined);
        onOpenChange(next);
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 bg-black/30" />
        <Dialog.Popup className="fixed top-1/2 left-1/2 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-lg border bg-background p-4 shadow-lg">
          <form className="flex flex-col gap-3" onSubmit={(e) => void submit(e)}>
            <Dialog.Title className="font-semibold">{title}</Dialog.Title>
            {children}
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Dialog.Close render={<Button type="button" variant="ghost" />}>Cancel</Dialog.Close>
              <Button type="submit" variant={destructive ? "destructive" : "default"} disabled={busy}>
                {submitLabel}
              </Button>
            </div>
          </form>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** A labelled text field for a FormDialog. */
export function TextField(props: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      {props.label}
      <input
        className="rounded border bg-background px-2 py-1 text-base"
        required
        autoFocus
        value={props.value}
        placeholder={props.placeholder}
        onChange={(e) => props.onChange(e.target.value)}
      />
    </label>
  );
}
