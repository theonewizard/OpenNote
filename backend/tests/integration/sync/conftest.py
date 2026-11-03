"""Shared fixtures for the sync tests: a fresh vault, history store and Committer."""

import hashlib
import os
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.sync.commit import Committer, Create
from app.sync.history import HistoryStore
from app.vaults.fsio import open_root
from app.vaults.registry import open_vault

BASE = b"one\ntwo\nthree\nfour\nfive\n"


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class SimulatedCrash(Exception):
    pass


@pytest.fixture
def world(tmp_path, engine):
    root = tmp_path / "vault"
    root.mkdir()
    factory = sessionmaker(engine)
    with factory.begin() as s:
        vault_id = open_vault(s, root)
    history = HistoryStore(tmp_path / "history", vault_id)
    root_fd = open_root(root)

    def make(**kwargs):
        return Committer(factory, history, root_fd, vault_id, **kwargs)

    yield root, factory, history, vault_id, make
    os.close(root_fd)


def create(path="n.md", data=BASE, file_id=None):
    op = Create(uuid.uuid7(), file_id or uuid.uuid7(), path, "note", sha(data))
    return op, data
