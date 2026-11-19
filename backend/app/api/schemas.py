"""Request and response bodies of the v1 API (docs/api/api-contract.md §3).

One module so the generated clients see one consistent set of names. Timestamps are
RFC 3339 UTC; identifiers are UUIDv7; every mutable resource carries `revision`, which
the `ETag` header repeats as `"<revision>"`.
"""

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

Role = Literal["viewer", "editor", "owner"]
NoteSort = Literal[
    "path", "-path", "title", "-title", "created_at", "-created_at", "modified_at", "-modified_at"
]


class _Body(BaseModel):
    """Request bodies reject unknown fields, and booleans are `StrictBool` (no `"0"` for
    `false`), so a mistake is a 422, not a silent no-op or a coerced value."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def _no_nul(cls, value: Any) -> Any:
        """PostgreSQL text and file names cannot hold NUL."""
        texts = value if isinstance(value, list) else [value]
        if any(isinstance(text, str) and "\x00" in text for text in texts):
            raise ValueError("must not contain NUL characters")
        return value


# Pagination -------------------------------------------------------------------------------


class _Page(BaseModel):
    next_cursor: str | None = Field(
        description="Pass as `cursor` for the next page; null on the last page"
    )


# Auth -------------------------------------------------------------------------------------


class LoginRequest(_Body):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)
    auth_request: str | None = Field(
        default=None,
        description="The `auth_request` id `GET /api/v1/auth/authorize` put in the login URL; "
        "when given, the response's `redirect_to` carries the authorization code",
    )


class TokenResponse(BaseModel):
    """RFC 6749 §5.1 access token response."""

    access_token: str
    token_type: Literal["Bearer"]
    expires_in: int = Field(description="Seconds until the access token expires")
    refresh_token: str = Field(description="Opaque, single use: each refresh returns a new one")
    device_id: uuid.UUID


# Users and devices -----------------------------------------------------------------------


class User(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    is_admin: bool
    created_at: dt.datetime


class LoginResult(BaseModel):
    user: User
    csrf_token: str = Field(
        description="Send as `X-CSRF-Token` on mutating requests made with the session cookie; "
        "also readable from the `opennote_csrf` cookie"
    )
    redirect_to: str | None = Field(
        description="Where to send the browser next: the OAuth client's redirect URI with "
        "`code` and `state` when `auth_request` was given, else null"
    )


class UserCreate(_Body):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=12, max_length=1024)
    display_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    is_admin: StrictBool = False


class UserPage(_Page):
    items: list[User]


class Device(BaseModel):
    id: uuid.UUID
    name: str
    platform: str | None
    created_at: dt.datetime
    last_seen_at: dt.datetime | None
    current: bool = Field(description="True for the device the request is authenticated as")


class DevicePage(_Page):
    items: list[Device]


class PersonalAccessToken(BaseModel):
    id: uuid.UUID
    name: str
    vault_ids: list[uuid.UUID] = Field(description="The only vaults the token can reach")
    scope: Literal["read", "write"]
    created_at: dt.datetime
    expires_at: dt.datetime | None
    last_used_at: dt.datetime | None


class PersonalAccessTokenCreate(_Body):
    name: str = Field(min_length=1, max_length=255)
    vault_ids: list[uuid.UUID] = Field(min_length=1)
    scope: Literal["read", "write"] = "read"
    expires_at: dt.datetime | None = None


class PersonalAccessTokenCreated(BaseModel):
    token: PersonalAccessToken
    secret: str = Field(description="Send as `X-API-Key`; shown once and never again")


class PersonalAccessTokenPage(_Page):
    items: list[PersonalAccessToken]


# Vaults -----------------------------------------------------------------------------------


class VaultSettings(BaseModel):
    sync_obsidian_config: bool = False
    ai_enabled: bool = False


class VaultSettingsPatch(_Body):
    sync_obsidian_config: StrictBool | None = None
    ai_enabled: StrictBool | None = None


class Vault(BaseModel):
    id: uuid.UUID
    name: str
    role: Role = Field(description="The caller's role in this vault")
    revision: int
    created_at: dt.datetime
    settings: VaultSettings


class VaultCreate(_Body):
    name: str = Field(min_length=1, max_length=255)
    directory: str | None = Field(
        default=None,
        description="An existing directory under the server's vault root to register, "
        "relative to that root; omitted, an empty vault directory is created",
    )


class VaultPatch(_Body):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    settings: VaultSettingsPatch | None = None


class VaultPage(_Page):
    items: list[Vault]


class VaultMember(BaseModel):
    user_id: uuid.UUID
    username: str
    display_name: str
    role: Role


class VaultMemberPage(_Page):
    items: list[VaultMember]


class VaultMemberPut(_Body):
    role: Role


# Notes ------------------------------------------------------------------------------------


class Note(BaseModel):
    id: uuid.UUID
    vault_id: uuid.UUID
    path: str
    title: str
    revision: int
    content_hash: str = Field(description="`sha256:` and the lowercase hex digest of the bytes")
    size: int
    created_at: dt.datetime
    modified_at: dt.datetime
    modified_by_device: str
    tags: list[str]
    aliases: list[str]
    properties: dict[str, Any] | None = Field(
        description="The frontmatter as JSON; null when there is none or it does not parse"
    )
    frontmatter_error: bool
    read_only: bool = Field(description="True for a note too large to edit (opaque)")
    path_warning: str | None = Field(
        description="A path rule the existing file name breaks, or null"
    )
    has_id_in_file: bool


class NotePage(_Page):
    items: list[Note]


class NoteCreate(_Body):
    vault_id: uuid.UUID
    path: str = Field(min_length=1, max_length=1024, description="Vault-relative, ends in `.md`")
    content: str | None = Field(
        default=None,
        description="The note's Markdown; omitted, the note starts with an `id` frontmatter only",
    )
    template_id: uuid.UUID | None = Field(
        default=None,
        description="A note in the same vault to start from instead of `content`: its "
        "`{{title}}`, `{{date}}`, `{{time}}`, `{{date:FORMAT}}` and `{{time:FORMAT}}` are "
        "filled in (Obsidian Templates syntax) and its `id` is replaced by the new note's",
    )
    local_time: dt.datetime | None = Field(
        default=None,
        description="The creator's local time with its UTC offset, for the template's dates; "
        "omitted, the server's time in UTC",
    )

    @field_validator("local_time")
    @classmethod
    def _aware(cls, value: dt.datetime | None) -> dt.datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("must carry a UTC offset")
        return value


class NotePatch(_Body):
    """Either a move (`path`) or a metadata edit (the other fields), not both."""

    path: str | None = Field(default=None, min_length=1, max_length=1024)
    tags: list[str] | None = None
    aliases: list[str] | None = None
    opennote: dict[str, Any] | None = Field(
        default=None, description="Replaces the `opennote:` frontmatter namespace"
    )


class NoteRef(BaseModel):
    id: uuid.UUID
    path: str
    title: str


class OutgoingLink(BaseModel):
    target: str = Field(description="The link text as written, without alias or heading")
    resolved: NoteRef | None = Field(description="The note it points at; null if unresolved")
    embed: bool
    heading: str | None
    block: str | None
    alias: str | None


class NoteLinks(BaseModel):
    outgoing: list[OutgoingLink]
    incoming: list[NoteRef] = Field(description="Notes that link here (backlinks)")
    unresolved: list[str] = Field(description="Targets of outgoing links that resolve nowhere")


# Folders ----------------------------------------------------------------------------------


class Folder(BaseModel):
    path: str = Field(description="Vault-relative, no trailing slash")
    name: str
    parent: str | None = Field(description="The parent folder's path; null at the vault root")
    note_count: int = Field(description="Notes directly in this folder")
    attachment_count: int = Field(description="Attachments directly in this folder")


class FolderList(BaseModel):
    """Every folder of the vault, sorted by path; the client builds the tree from `parent`."""

    items: list[Folder]


class FolderCreate(_Body):
    vault_id: uuid.UUID
    path: str = Field(min_length=1, max_length=1024)


class FolderMove(_Body):
    vault_id: uuid.UUID
    path: str = Field(min_length=1, max_length=1024)
    new_path: str = Field(min_length=1, max_length=1024)


class FolderMoveResult(BaseModel):
    folder: Folder
    moved_files: int = Field(description="Files moved, each as one revision")


# Attachments ------------------------------------------------------------------------------


class Attachment(BaseModel):
    id: uuid.UUID
    vault_id: uuid.UUID
    path: str
    revision: int
    content_hash: str
    size: int
    media_type: str = Field(description="Sniffed from the bytes by the server")
    created_at: dt.datetime
    modified_at: dt.datetime


class AttachmentPage(_Page):
    items: list[Attachment]


# Tags and search --------------------------------------------------------------------------


class Tag(BaseModel):
    name: str = Field(description="As written in the most common spelling, without `#`")
    count: int = Field(description="Notes that carry the tag")


class TagPage(_Page):
    items: list[Tag]


class SearchHit(BaseModel):
    note: Note
    snippet: str | None = Field(description="Plain-text excerpt around the match, or null")
    score: float


class SearchPage(_Page):
    items: list[SearchHit]


# Tasks and the link graph -----------------------------------------------------------------

TaskStatusFilter = Literal["open", "done", "any"]


class Task(BaseModel):
    note: NoteRef
    ordinal: int = Field(description="The task's position among the note's tasks, from 0")
    revision: int = Field(description="The note's revision; send it as `If-Match` to toggle")
    line: int = Field(description="0-based line in the note, frontmatter included")
    status: str = Field(description="The character between the brackets")
    done: bool = Field(description="Any status but a space")
    text: str = Field(description="The task's first line after `[c] `, as written")
    parent: int | None = Field(description="`ordinal` of the enclosing task, for subtasks")
    due: dt.date | None = Field(description="Due date (Tasks plugin)")
    scheduled: dt.date | None = Field(description="Scheduled date (Tasks plugin)")
    start: dt.date | None = Field(description="Start date (Tasks plugin)")
    done_on: dt.date | None = Field(description="Done date (Tasks plugin)")
    priority: Literal["highest", "high", "medium", "low", "lowest"] | None
    recurrence: str | None = Field(description="Recurrence rule as written (Tasks plugin)")
    remind_at: dt.datetime | None = Field(
        description="Reminder plugin `(@date time)`: local wall-clock time, no UTC offset"
    )


class TaskPage(_Page):
    items: list[Task]


class TaskPatch(_Body):
    done: StrictBool
    today: dt.date | None = Field(
        default=None,
        description="The caller's local date, for the done date and the next occurrence of a "
        "recurring task; omitted, the server's date in UTC",
    )


class GraphNode(BaseModel):
    id: str = Field(description="The note or attachment id, or `unresolved:` + the target")
    kind: Literal["note", "attachment", "unresolved"]
    label: str
    path: str | None


class GraphEdge(BaseModel):
    source: str
    target: str
    count: int = Field(description="Links and embeds from source to target")


class Graph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
