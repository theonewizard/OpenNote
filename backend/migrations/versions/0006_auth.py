"""Credential store, vault membership and metadata, idempotency keys, audit log
(Phase 2 Task 3).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None

NOW = sa.text("now()")


def _ts(name: str, *, nullable: bool = True, now: bool = False) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), nullable=nullable, server_default=NOW if now else None
    )


def _user_fk(name: str = "user_id") -> sa.Column:
    return sa.Column(name, sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("username_key", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("oidc_issuer", sa.Text(), nullable=True),
        sa.Column("oidc_subject", sa.Text(), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        _ts("created_at", nullable=False, now=True),
        sa.UniqueConstraint("oidc_issuer", "oidc_subject"),
    )
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _user_fk(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=True),
        _ts("created_at", nullable=False, now=True),
        _ts("last_seen_at"),
        _ts("revoked_at"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "device_id",
            sa.Uuid(),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        _ts("created_at", nullable=False, now=True),
        _ts("expires_at", nullable=False),
        _ts("used_at"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _user_fk(),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        _ts("created_at", nullable=False, now=True),
        _ts("expires_at", nullable=False),
        _ts("revoked_at"),
    )
    op.create_table(
        "personal_access_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _user_fk(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("vault_ids", ARRAY(sa.Uuid()), nullable=False),
        _ts("created_at", nullable=False, now=True),
        _ts("expires_at"),
        _ts("last_used_at"),
        _ts("revoked_at"),
        sa.CheckConstraint("scope IN ('read', 'write')", name="pat_scope"),
    )
    op.create_table(
        "signing_keys",
        sa.Column("kid", sa.Text(), primary_key=True),
        sa.Column("private_pem", sa.Text(), nullable=False),
        _ts("created_at", nullable=False, now=True),
        _ts("retired_at"),
    )
    op.create_table(
        "auth_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("oidc_state", sa.Text(), nullable=True, unique=True),
        sa.Column("oidc_nonce", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("code_hash", sa.Text(), nullable=True, unique=True),
        _ts("created_at", nullable=False, now=True),
        _ts("expires_at", nullable=False),
        _ts("used_at"),
    )
    op.add_column("vaults", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("vaults", _ts("created_at", nullable=False, now=True))
    op.add_column(
        "vaults",
        sa.Column("settings", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column("vaults", _ts("deleted_at"))
    op.create_table(
        "vault_members",
        sa.Column(
            "vault_id", sa.Uuid(), sa.ForeignKey("vaults.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.CheckConstraint("role IN ('viewer', 'editor', 'owner')", name="vault_member_role"),
    )
    op.create_index("vault_members_user", "vault_members", ["user_id"])
    op.create_table(
        "idempotency_keys",
        sa.Column("principal", sa.Text(), primary_key=True),
        sa.Column("key", sa.Uuid(), primary_key=True),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("headers", JSONB(), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        _ts("created_at", nullable=False, now=True),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _ts("at", nullable=False, now=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),  # no FK: outlives the user
        sa.Column("actor_device", sa.Text(), nullable=True),
        sa.Column("vault_id", sa.Uuid(), nullable=True),
        sa.Column("target", sa.Text(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("details", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("audit_events_at", "audit_events", ["at"])
    # Append-only (design §8): rows can be added, never changed or removed.
    op.execute(
        """
        CREATE FUNCTION audit_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only';
        END $$;
        CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION audit_events_append_only()")
    op.drop_table("audit_events")
    op.drop_table("idempotency_keys")
    op.drop_index("vault_members_user", table_name="vault_members")
    op.drop_table("vault_members")
    for column in ("deleted_at", "settings", "created_at", "revision"):
        op.drop_column("vaults", column)
    for table in (
        "auth_requests",
        "signing_keys",
        "personal_access_tokens",
        "sessions",
        "refresh_tokens",
        "devices",
        "users",
    ):
        op.drop_table(table)
