import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ApiError, getJson, sendJson } from "@/api/client";
import type { LoginResult, ServerMeta } from "@/api/types";
import { Button } from "@/components/ui/button";

function randomToken(bytes = 32): string {
  const raw = crypto.getRandomValues(new Uint8Array(bytes));
  return btoa(String.fromCharCode(...raw)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// The web client never exchanges a code: the OIDC callback sets the session cookie and
// lands on "/" (backend auth.oidc_callback), so the PKCE challenge is only a required
// random value here.
function oidcUrl(provider: string): string {
  const params = new URLSearchParams({
    response_type: "code",
    client_id: "opennote-web",
    redirect_uri: "/",
    code_challenge: randomToken(),
    code_challenge_method: "S256",
    state: randomToken(16),
    provider,
  });
  return `/api/v1/auth/authorize?${params}`;
}

function loginError(error: unknown): string {
  if (!(error instanceof ApiError)) return "The server cannot be reached.";
  if (error.status === 401) return "Wrong username or password.";
  if (error.status === 429) {
    const wait = error.headers.get("retry-after");
    return `Too many attempts. Try again${wait ? ` in ${wait} seconds` : " later"}.`;
  }
  return error.message;
}

/** Password and OIDC login. `onLoggedIn` runs after the session cookie is set. */
export function Login({ onLoggedIn }: { onLoggedIn: () => void }) {
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => getJson<ServerMeta>("/api/v1/meta") });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  // Set when a native client (Apple app, CLI) sent the browser here to sign in.
  const authRequest = new URLSearchParams(location.search).get("auth_request");
  const providers = meta.data?.login_methods.filter((m) => m !== "password") ?? [];
  const passwordLogin = !meta.data || meta.data.login_methods.includes("password");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const result = await sendJson<LoginResult>("/api/v1/auth/login", "POST", {
        username,
        password,
        ...(authRequest ? { auth_request: authRequest } : {}),
      });
      if (result.redirect_to) {
        location.assign(result.redirect_to);
        return;
      }
      if (location.pathname === "/login") history.replaceState(null, "", "/");
      onLoggedIn();
    } catch (e) {
      setError(loginError(e));
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-svh items-center justify-center p-4">
      <div className="flex w-full max-w-sm flex-col gap-4">
        <h1 className="text-2xl font-semibold">Sign in to OpenNote</h1>
        {passwordLogin && (
          <form className="flex flex-col gap-3" onSubmit={(e) => void submit(e)}>
            <label className="flex flex-col gap-1 text-sm">
              Username
              <input
                className="rounded border bg-background px-2 py-1 text-base"
                autoComplete="username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Password
              <input
                className="rounded border bg-background px-2 py-1 text-base"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <Button type="submit" disabled={busy}>
              Sign in
            </Button>
          </form>
        )}
        {providers.map((p) => (
          <Button key={p} variant="outline" onClick={() => location.assign(oidcUrl(p))}>
            Sign in with {p}
          </Button>
        ))}
      </div>
    </main>
  );
}
