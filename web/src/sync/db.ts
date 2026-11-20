// The web client's sync state in IndexedDB (sync protocol §2.2 and §10), one database per
// user so a shared browser never shows one user's cached notes to another.
import type { PushOperation } from "@/api/types";

export interface FileRecord {
  vault_id: string;
  file_id: string;
  path: string;
  kind: string;
  /** 0 while the server has never committed the file */
  base_revision: number;
  /** The server's bytes at base_revision; null for a tombstone */
  base_hash: string | null;
  /** The bytes on this device; null when deleted. Dirty when it differs from base_hash */
  local_hash: string | null;
  deleted: boolean;
  /** The newest revision pulled while the file was dirty (the push will merge with it) */
  remote_revision?: number;
  remote_hash?: string | null;
  /** What the device held before sync replaced it, so an edit typed on top of those bytes
   * is still pushed against the revision it was made on (see SyncEngine.edit) */
  prev?: { hash: string | null; base_revision: number; base_hash: string | null };
  /** Set when the server rejected the edit: never pushed again until edited or discarded */
  rejected?: { title: string; detail?: string };
  /** Something the user should be told about this file (conflict copy, restored file) */
  notice?: string;
}

export interface OutboxEntry {
  id?: number;
  vault_id: string;
  file_id: string;
  /** base_revision is filled in when the entry is first sent, then never changes */
  op: PushOperation;
  created_at: number;
  sent: boolean;
}

export interface RecoveryEntry {
  id?: number;
  vault_id: string;
  file_id: string;
  path: string;
  hash: string;
  removed_at: number;
}

export type Store = "files" | "outbox" | "contents" | "meta" | "recovery";

export function openDatabase(name: string): Promise<IDBDatabase> {
  const open = indexedDB.open(name, 1);
  open.onupgradeneeded = () => {
    const db = open.result;
    db.createObjectStore("files", { keyPath: ["vault_id", "file_id"] }).createIndex("vault", "vault_id");
    // The outbox is its own store, ordered by its auto-increment key.
    db.createObjectStore("outbox", { keyPath: "id", autoIncrement: true }).createIndex("vault", "vault_id");
    db.createObjectStore("contents"); // sha256:<hex> -> Uint8Array
    db.createObjectStore("meta"); // key -> value (cursor:<vault>, vaults)
    db.createObjectStore("recovery", { keyPath: "id", autoIncrement: true });
  };
  return request(open);
}

export function request<T>(r: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

/** Runs `fn` in one transaction and resolves once it has committed. Only await IndexedDB
 * requests inside `fn`: any other await lets the transaction commit early. */
export async function transact<T>(
  db: IDBDatabase,
  stores: Store[],
  mode: IDBTransactionMode,
  fn: (t: IDBTransaction) => Promise<T>,
): Promise<T> {
  const t = db.transaction(stores, mode);
  const done = new Promise<void>((resolve, reject) => {
    t.oncomplete = () => resolve();
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error ?? new DOMException("Transaction aborted", "AbortError"));
  });
  try {
    const result = await fn(t);
    await done;
    return result;
  } catch (error) {
    done.catch(() => undefined); // the abort below rejects it; `error` is what counts
    try {
      t.abort();
    } catch {
      // already finished
    }
    throw error;
  }
}

export function byVault<T>(t: IDBTransaction, store: "files" | "outbox", vaultId: string): Promise<T[]> {
  return request(t.objectStore(store).index("vault").getAll(vaultId)) as Promise<T[]>;
}
