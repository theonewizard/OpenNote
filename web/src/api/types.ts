// Short names for the generated v1 schemas (src/api/schema.d.ts, from docs/api/openapi.json).
import type { components } from "@/api/schema";

type Schemas = components["schemas"];

export type Vault = Schemas["Vault"];
export type VaultPage = Schemas["VaultPage"];
export type Folder = Schemas["Folder"];
export type FolderList = Schemas["FolderList"];
export type NoteMeta = Schemas["Note"];
export type NotePage = Schemas["NotePage"];
