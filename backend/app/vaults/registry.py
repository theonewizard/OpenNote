"""Opening and registering vaults (storage contract §1, §1.2).

Opening never writes to the vault: a plain Obsidian vault's id lives in `vaults` only.
Registering is the one call that creates `.opennote/config.json`.
"""

import os
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.vaults.config import SUPPORTED_SCHEMA_VERSION, VaultConfig, read_config, write_config
from app.vaults.fsio import open_root
from app.vaults.models import Vault


class VaultIdMismatch(Exception):
    """The vault's config names a different id than the one recorded for its folder."""


def open_vault(session: Session, root: Path) -> uuid.UUID:
    """The vault's id, recording the vault in `vaults` if needed. Writes nothing to disk."""
    root_fd = open_root(root)
    try:
        cfg = read_config(root_fd)
    finally:
        os.close(root_fd)
    return _upsert(session, root, cfg.vault_id if cfg else None, cfg.name if cfg else root.name)


def register_vault(session: Session, root: Path, name: str) -> uuid.UUID:
    """Register the vault with OpenNote: write its config (keeping unknown keys and an
    existing id) and record it. PermissionError when a newer client owns the config."""
    root_fd = open_root(root)
    try:
        cfg = read_config(root_fd)
        if cfg is not None and cfg.read_only:
            raise PermissionError("vault config has a newer schema_version; vault is read-only")
        vault_id = _upsert(session, root, cfg.vault_id if cfg else None, name)
        extra = cfg.extra if cfg else {}
        write_config(root_fd, VaultConfig(SUPPORTED_SCHEMA_VERSION, vault_id, name, extra))
    finally:
        os.close(root_fd)
    return vault_id


def _upsert(session: Session, root: Path, vault_id: uuid.UUID | None, name: str) -> uuid.UUID:
    row = session.scalar(select(Vault).where(Vault.root_path == str(root)))
    if row is None:
        row = Vault(id=vault_id or uuid.uuid7(), name=name, root_path=str(root))
        session.add(row)
    elif vault_id is not None and vault_id != row.id:
        raise VaultIdMismatch("the vault config's id differs from the recorded one")
    row.name = name
    session.flush()
    return row.id
