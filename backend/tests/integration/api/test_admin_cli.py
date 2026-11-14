"""`python -m app.auth.admin create-user` (R-P2-007)."""

import os
import subprocess
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.crypto import verify_password
from app.auth.models import User
from tests.integration.conftest import BACKEND_DIR


def run_admin(pg_url, tmp_path, *args, password="a long enough password"):
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPENNOTE_")} | {
        "OPENNOTE_DATABASE_URL": pg_url,
        "OPENNOTE_VALKEY_URL": "redis://127.0.0.1:6379/1",
        "OPENNOTE_VAULT_ROOT": str(tmp_path),
        "OPENNOTE_HISTORY_ROOT": str(tmp_path),
    }
    return subprocess.run(  # noqa: S603 (fixed argv, test input)
        [sys.executable, "-m", "app.auth.admin", *args],
        input=password + "\n",
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_create_admin_from_stdin(engine, pg_url, tmp_path):
    result = run_admin(pg_url, tmp_path, "create-user", "--admin", "root")
    assert result.returncode == 0, result.stderr
    assert "a long enough password" not in result.stdout + result.stderr
    with Session(engine) as s:
        user = s.scalars(select(User).where(User.username == "root")).one()
        assert user.is_admin
        assert verify_password(user.password_hash, "a long enough password")
    again = run_admin(pg_url, tmp_path, "create-user", "ROOT")
    assert again.returncode == 1
    assert "exists" in again.stderr


def test_short_password_is_refused(engine, pg_url, tmp_path):
    result = run_admin(pg_url, tmp_path, "create-user", "x", password="short")
    assert result.returncode == 1
    assert "at least 12" in result.stderr
