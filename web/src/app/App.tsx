import { MutationCache, QueryCache, QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, getJson } from "@/api/client";
import type { User } from "@/api/types";
import { Layout } from "@/app/Layout";
import { SESSION_KEY } from "@/app/session";
import { Button } from "@/components/ui/button";
import { Login } from "@/features/Login";
import { rememberedUser } from "@/sync/useSync";

/** The signed-in user; "offline" when the server cannot be reached but this device has a
 * signed-in user's cache; null when nobody is signed in. */
async function loadSession(): Promise<User | "offline" | null> {
  try {
    return await getJson<User>("/api/v1/me");
  } catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 401) return null;
      throw error;
    }
    if (rememberedUser()) return "offline";
    throw error;
  }
}

function Session() {
  const client = useQueryClient();
  const session = useQuery({ queryKey: SESSION_KEY, queryFn: loadSession, retry: false, staleTime: Infinity });
  if (session.isPending) return <main className="p-4">Loading…</main>;
  if (session.isError) {
    return (
      <main className="flex flex-col items-start gap-2 p-4">
        <p>The server cannot be reached.</p>
        <Button variant="outline" size="sm" onClick={() => void session.refetch()}>
          Try again
        </Button>
      </main>
    );
  }
  if (session.data === null) return <Login onLoggedIn={() => void client.resetQueries()} />;
  return <Layout user={session.data === "offline" ? undefined : session.data} />;
}

export function App() {
  const [client] = useState(() => {
    // A 401 anywhere means the session ended: ask again, which shows the login screen.
    const signedOut = (error: unknown) => {
      if (error instanceof ApiError && error.status === 401) void client.invalidateQueries({ queryKey: SESSION_KEY });
    };
    const client: QueryClient = new QueryClient({
      defaultOptions: { queries: { retry: (count, error) => count < 1 && !(error instanceof ApiError && error.status === 401) } },
      queryCache: new QueryCache({ onError: signedOut }),
      mutationCache: new MutationCache({ onError: signedOut }),
    });
    return client;
  });
  return (
    <QueryClientProvider client={client}>
      <Session />
    </QueryClientProvider>
  );
}
