// Short names for the generated v1 schemas (src/api/schema.d.ts, from docs/api/openapi.json).
import type { components } from "@/api/schema";

type Schemas = components["schemas"];

export type Vault = Schemas["Vault"];
export type VaultPage = Schemas["VaultPage"];
export type Folder = Schemas["Folder"];
export type FolderList = Schemas["FolderList"];
export type NoteMeta = Schemas["Note"];
export type NotePage = Schemas["NotePage"];
export type User = Schemas["User"];
export type SyncEntry = Schemas["SyncEntry"];
export type SyncChanges = Schemas["SyncChanges"];
export type SyncSnapshot = Schemas["SyncSnapshot"];
export type PushOperation = Schemas["SyncPush"]["operations"][number];
export type PushResult = Schemas["PushResult"];
export type SyncPushResult = Schemas["SyncPushResult"];
