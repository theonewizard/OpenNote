// React access to the sync engine: one engine per signed-in user, kept by the query client.
import { useQuery } from "@tanstack/react-query";
import { useCallback, useSyncExternalStore } from "react";

import { ApiError, getJson } from "@/api/client";
import type { User } from "@/api/types";
import { IDLE, SyncEngine, type SyncStatus } from "@/sync/engine";

// The last signed-in user, so the app can open that user's cache when it starts offline.
const USER_KEY = "opennote:user";

async function openEngine(): Promise<SyncEngine> {
  let userId: string | null;
  try {
    userId = (await getJson<User>("/api/v1/me")).id;
    try {
      localStorage.setItem(USER_KEY, userId);
    } catch {
      // storage blocked: the app still works online
    }
  } catch (error) {
    if (error instanceof ApiError) throw error; // signed out: never open someone's cache
    try {
      userId = localStorage.getItem(USER_KEY);
    } catch {
      userId = null;
    }
    if (!userId) throw error;
  }
  return SyncEngine.open(userId);
}

export function useSyncEngine() {
  return useQuery({ queryKey: ["sync-engine"], queryFn: openEngine, staleTime: Infinity, gcTime: Infinity, retry: false });
}

export function useSyncStatus(engine: SyncEngine | undefined, vaultId: string | undefined): SyncStatus {
  const subscribe = useCallback((notify: () => void) => engine?.subscribe(notify) ?? (() => undefined), [engine]);
  return useSyncExternalStore(subscribe, () => (engine && vaultId ? engine.status(vaultId) : IDLE));
}
