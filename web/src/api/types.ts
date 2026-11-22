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
export type SearchPage = Schemas["SearchPage"];
export type TagPage = Schemas["TagPage"];
export type Attachment = Schemas["Attachment"];
export type AttachmentPage = Schemas["AttachmentPage"];
export type DeletedNotePage = Schemas["DeletedNotePage"];
export type NoteLinks = Schemas["NoteLinks"];
export type RenameResult = Schemas["RenameResult"];
export type ServerMeta = Schemas["ServerMeta"];
export type LoginResult = Schemas["LoginResult"];
export type VaultMemberPage = Schemas["VaultMemberPage"];
export type DevicePage = Schemas["DevicePage"];
export type UserPage = Schemas["UserPage"];
export type Conflict = Schemas["Conflict"];
export type ConflictPage = Schemas["ConflictPage"];
export type NoteRevision = Schemas["NoteRevision"];
export type NoteRevisionPage = Schemas["NoteRevisionPage"];
