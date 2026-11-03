"""`.opennote/config.json` (storage contract §1.2)."""

import json
import uuid

import pytest

from app.vaults.config import SUPPORTED_SCHEMA_VERSION, VaultConfig, read_config, write_config
from app.vaults.fsio import open_root


@pytest.fixture
def root_fd(tmp_path):
    fd = open_root(tmp_path)
    yield fd
    import os

    os.close(fd)


def write_raw(tmp_path, data: dict) -> None:
    (tmp_path / ".opennote").mkdir()
    (tmp_path / ".opennote" / "config.json").write_text(json.dumps(data))


def test_missing_config_reads_as_none(root_fd):
    assert read_config(root_fd) is None


def test_config_roundtrip(tmp_path, root_fd):
    cfg = VaultConfig(schema_version=1, vault_id=uuid.uuid7(), name="Work")
    write_config(root_fd, cfg)
    assert read_config(root_fd) == cfg
    assert not [p for p in (tmp_path / ".opennote").iterdir() if p.name != "config.json"]


def test_config_unknown_keys_preserved(tmp_path, root_fd):
    vault_id = str(uuid.uuid7())
    extra = {"attachments_folder": "Attachments", "daily_notes": {"folder": "J", "format": "Y"}}
    write_raw(tmp_path, {"schema_version": 1, "vault_id": vault_id, "name": "W"} | extra)
    cfg = read_config(root_fd)
    assert cfg is not None
    write_config(root_fd, VaultConfig(cfg.schema_version, cfg.vault_id, "Renamed", cfg.extra))
    saved = json.loads((tmp_path / ".opennote" / "config.json").read_text())
    assert saved == {"schema_version": 1, "vault_id": vault_id, "name": "Renamed"} | extra


def test_higher_schema_version_opens_read_only(tmp_path, root_fd):
    write_raw(
        tmp_path,
        {
            "schema_version": SUPPORTED_SCHEMA_VERSION + 1,
            "vault_id": str(uuid.uuid7()),
            "name": "W",
        },
    )
    cfg = read_config(root_fd)
    assert cfg is not None and cfg.read_only
    with pytest.raises(PermissionError):
        write_config(root_fd, cfg)


def test_invalid_config_is_refused(tmp_path, root_fd):
    write_raw(tmp_path, {"schema_version": "one"})
    with pytest.raises(ValueError):
        read_config(root_fd)


def test_symlinked_config_dir_is_refused(tmp_path, root_fd):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / ".opennote").symlink_to(outside)
    with pytest.raises(OSError):
        write_config(root_fd, VaultConfig(1, uuid.uuid7(), "W"))
    assert list(outside.iterdir()) == []
