"""The worker's broker and entrypoint, without any service: building the broker opens no
connection, and invalid settings stop the worker before it starts one."""

import os
import subprocess
import sys
from pathlib import Path

from app.workers.broker import broker_from_settings
from tests.conftest import placeholder_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_broker_keeps_its_keys_under_the_opennote_namespace():
    assert broker_from_settings(placeholder_settings()).namespace == "opennote"


def test_invalid_settings_stop_the_worker_with_one_line_on_stderr():
    env = {k: v for k, v in os.environ.items() if k != "OPENNOTE_VALKEY_URL"}
    result = subprocess.run(
        [sys.executable, "-m", "app.workers"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    assert result.stderr == (
        "OpenNote worker cannot start: invalid or missing settings: valkey_url\n"
    )
    assert result.stdout == ""
