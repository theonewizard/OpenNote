"""`.opennote/config.json`: portable vault settings (storage contract §1.2).

Read on open; written only by an explicit register or settings call, never on open.
"""

import contextlib
import json
import os
import secrets
import uuid
from dataclasses import dataclass, field
from typing import Any

CONFIG_DIR, CONFIG_NAME = ".opennote", "config.json"
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
SUPPORTED_SCHEMA_VERSION = 1
_KNOWN = ("schema_version", "vault_id", "name")


@dataclass(frozen=True)
class VaultConfig:
    schema_version: int
    vault_id: uuid.UUID
    name: str
    extra: dict[str, Any] = field(default_factory=dict)  # unknown keys, kept verbatim

    @property
    def read_only(self) -> bool:
        """A newer client wrote this vault: open it read-only and ask the user to update."""
        return self.schema_version > SUPPORTED_SCHEMA_VERSION


def read_config(root_fd: int) -> VaultConfig | None:
    """The vault's config, or None when it has none. ValueError when it is malformed."""
    try:
        dir_fd = os.open(CONFIG_DIR, _DIR_FLAGS, dir_fd=root_fd)
    except FileNotFoundError:
        return None
    try:
        fd = os.open(CONFIG_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    finally:
        os.close(dir_fd)
    with os.fdopen(fd, "rb") as fh:
        data = json.loads(fh.read())
    if not isinstance(data, dict):
        raise ValueError("vault config is not a JSON object")
    version, vault_id, vault_name = (data.get(k) for k in _KNOWN)
    if type(version) is not int or not isinstance(vault_name, str):
        raise ValueError("vault config has an invalid schema_version or name")
    return VaultConfig(
        version,
        uuid.UUID(str(vault_id)),
        vault_name,
        {k: v for k, v in data.items() if k not in _KNOWN},
    )


def write_config(root_fd: int, cfg: VaultConfig) -> None:
    """Write the config atomically (temp file, fsync, rename, fsync directory)."""
    if cfg.read_only:
        raise PermissionError("vault config has a newer schema_version; vault is read-only")
    data = {"schema_version": cfg.schema_version, "vault_id": str(cfg.vault_id)}
    data |= {"name": cfg.name} | cfg.extra
    payload = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()
    with contextlib.suppress(FileExistsError):
        os.mkdir(CONFIG_DIR, 0o755, dir_fd=root_fd)
    dir_fd = os.open(CONFIG_DIR, _DIR_FLAGS, dir_fd=root_fd)  # ELOOP on a symlink
    try:
        tmp = f".{CONFIG_NAME}.{secrets.token_hex(4)}.opennote-tmp"
        fd = os.open(
            tmp,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o644,
            dir_fd=dir_fd,
        )
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.rename(tmp, CONFIG_NAME, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except BaseException:
            os.unlink(tmp, dir_fd=dir_fd)
            raise
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
