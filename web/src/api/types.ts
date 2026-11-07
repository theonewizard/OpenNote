// The fields of the v1 schemas (docs/api/openapi.json) that the web app reads. Temporary:
// replaced by aliases of the generated src/api/schema.d.ts once the Phase 2 contract
// (pull request #34) is on main.

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface Vault {
  id: string;
  name: string;
  role: "viewer" | "editor" | "owner";
  revision: number;
}

// GET /api/v1/folders: every folder, flat, sorted by path, not paginated.
export interface Folder {
  path: string;
  name: string;
  parent: string | null;
}

export interface NoteMeta {
  id: string;
  vault_id: string;
  path: string;
  title: string;
  revision: number;
  modified_at: string;
  tags: string[];
  read_only: boolean;
}
