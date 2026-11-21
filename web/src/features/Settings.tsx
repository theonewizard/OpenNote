import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { errorText, getJson, sendJson } from "@/api/client";
import type { DevicePage, User, UserPage, Vault, VaultMemberPage } from "@/api/types";
import { Button } from "@/components/ui/button";
import { FormDialog, TextField } from "@/components/ui/form-dialog";
import { ifMatch } from "@/features/actions";

type Role = "viewer" | "editor" | "owner";
const ROLES: Role[] = ["viewer", "editor", "owner"];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="flex flex-col gap-2 border-b p-4">
      <h2 className="font-semibold">{title}</h2>
      {children}
    </section>
  );
}

/** Account, vault management (plan R-P3-007) and devices. */
export function Settings({ user, vault, onVaultCreated }: { user: User | undefined; vault: Vault | undefined; onVaultCreated: (vault: Vault) => void }) {
  const client = useQueryClient();
  const [dialog, setDialog] = useState<"new" | "rename" | "delete">();
  const [name, setName] = useState("");
  const [error, setError] = useState<string>();
  const owner = vault?.role === "owner";

  const members = useQuery({
    queryKey: ["members", vault?.id],
    queryFn: () => getJson<VaultMemberPage>(`/api/v1/vaults/${vault!.id}/members`),
    enabled: owner,
  });
  const users = useQuery({
    queryKey: ["users"],
    queryFn: () => getJson<UserPage>("/api/v1/users"),
    enabled: owner && !!user?.is_admin,
  });
  const devices = useQuery({ queryKey: ["devices"], queryFn: () => getJson<DevicePage>("/api/v1/devices") });

  async function act(run: () => Promise<unknown>, keys: string[][]) {
    setError(undefined);
    try {
      await run();
    } catch (e) {
      setError(errorText(e));
    } finally {
      await Promise.all(keys.map((queryKey) => client.invalidateQueries({ queryKey })));
    }
  }

  const patchVault = (body: object) => sendJson<Vault>(`/api/v1/vaults/${vault!.id}`, "PATCH", body, ifMatch(vault!.revision));
  const memberIds = new Set(members.data?.items.map((m) => m.user_id));
  const candidates = users.data?.items.filter((u) => !memberIds.has(u.id)) ?? [];

  return (
    <div className="h-full overflow-auto">
      <h1 className="border-b px-4 py-2 font-semibold">Settings</h1>
      {error && (
        <p role="alert" className="border-b bg-muted px-4 py-2 text-sm">
          {error}
        </p>
      )}
      <Section title="Account">
        {user ? (
          <p>
            {user.display_name} ({user.username}){user.is_admin && ", administrator"}
          </p>
        ) : (
          <p className="text-muted-foreground">Offline: account details need the server.</p>
        )}
      </Section>

      <Section title="Vaults">
        <Button
          size="sm"
          variant="outline"
          className="self-start"
          onClick={() => {
            setName("");
            setDialog("new");
          }}
        >
          New vault
        </Button>
        {vault && (
          <div className="flex flex-col gap-2">
            <h3 className="font-medium">
              {vault.name} <span className="text-sm text-muted-foreground">({vault.role})</span>
            </h3>
            {owner && (
              <>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={vault.settings.ai_enabled}
                    onChange={(e) => void act(() => patchVault({ settings: { ai_enabled: e.target.checked } }), [["vaults"]])}
                  />
                  AI features (off by default; nothing leaves the server unless a provider is configured)
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={vault.settings.sync_obsidian_config}
                    onChange={(e) => void act(() => patchVault({ settings: { sync_obsidian_config: e.target.checked } }), [["vaults"]])}
                  />
                  Sync the .obsidian settings folder
                </label>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setName(vault.name);
                      setDialog("rename");
                    }}
                  >
                    Rename vault
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => {
                      setName("");
                      setDialog("delete");
                    }}
                  >
                    Delete vault
                  </Button>
                </div>
                <h4 className="pt-2 text-sm font-medium">Members</h4>
                <ul className="flex flex-col gap-1">
                  {members.data?.items.map((m) => (
                    <li key={m.user_id} className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="min-w-0 flex-1 truncate">
                        {m.display_name} ({m.username})
                      </span>
                      <select
                        aria-label={`Role of ${m.username}`}
                        className="rounded border bg-background px-1"
                        value={m.role}
                        onChange={(e) =>
                          void act(
                            () => sendJson(`/api/v1/vaults/${vault.id}/members/${m.user_id}`, "PUT", { role: e.target.value }),
                            [["members", vault.id]],
                          )
                        }
                      >
                        {ROLES.map((r) => (
                          <option key={r}>{r}</option>
                        ))}
                      </select>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          void act(() => sendJson(`/api/v1/vaults/${vault.id}/members/${m.user_id}`, "DELETE"), [["members", vault.id]])
                        }
                      >
                        Remove
                      </Button>
                    </li>
                  ))}
                </ul>
                {candidates.length > 0 && (
                  <select
                    aria-label="Add member"
                    className="self-start rounded border bg-background px-1 text-sm"
                    value=""
                    onChange={(e) =>
                      void act(
                        () => sendJson(`/api/v1/vaults/${vault.id}/members/${e.target.value}`, "PUT", { role: "editor" }),
                        [["members", vault.id]],
                      )
                    }
                  >
                    <option value="">Add member as editor…</option>
                    {candidates.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.display_name} ({u.username})
                      </option>
                    ))}
                  </select>
                )}
              </>
            )}
          </div>
        )}
      </Section>

      <Section title="Devices">
        <ul className="flex flex-col gap-1">
          {devices.data?.items.map((d) => (
            <li key={d.id} className="flex items-center gap-2 text-sm">
              <span className="min-w-0 flex-1 truncate">
                {d.name}
                {d.platform && ` (${d.platform})`}
                {d.current && ", this device"}
              </span>
              {!d.current && (
                <Button size="sm" variant="ghost" onClick={() => void act(() => sendJson(`/api/v1/devices/${d.id}`, "DELETE"), [["devices"]])}>
                  Revoke
                </Button>
              )}
            </li>
          ))}
        </ul>
        {devices.data?.items.length === 0 && <p className="text-sm text-muted-foreground">No signed-in apps.</p>}
      </Section>

      <FormDialog
        title="New vault"
        open={dialog === "new"}
        onOpenChange={(open) => setDialog(open ? "new" : undefined)}
        submitLabel="Create"
        onSubmit={async () => {
          const created = await sendJson<Vault>("/api/v1/vaults", "POST", { name });
          await client.invalidateQueries({ queryKey: ["vaults"] });
          onVaultCreated(created);
        }}
      >
        <TextField label="Name" value={name} onChange={setName} />
      </FormDialog>
      <FormDialog
        title="Rename vault"
        open={dialog === "rename"}
        onOpenChange={(open) => setDialog(open ? "rename" : undefined)}
        submitLabel="Rename"
        onSubmit={async () => {
          await patchVault({ name });
          await client.invalidateQueries({ queryKey: ["vaults"] });
        }}
      >
        <TextField label="Name" value={name} onChange={setName} />
      </FormDialog>
      <FormDialog
        title={`Delete ${vault?.name}?`}
        open={dialog === "delete"}
        onOpenChange={(open) => setDialog(open ? "delete" : undefined)}
        submitLabel="Delete vault"
        destructive
        onSubmit={async () => {
          if (name !== vault!.name) throw new Error("Type the vault's name to confirm.");
          await sendJson(`/api/v1/vaults/${vault!.id}`, "DELETE", undefined, ifMatch(vault!.revision));
          await client.invalidateQueries({ queryKey: ["vaults"] });
        }}
      >
        <p className="text-sm">The vault disappears from OpenNote for every member. Its files stay on the server's disk.</p>
        <TextField label="Type the vault's name to confirm" value={name} onChange={setName} />
      </FormDialog>
    </div>
  );
}
