"""Settings come from OPENNOTE_* variables or *_FILE secrets; errors never echo values."""

import os
import subprocess
import sys
import traceback
from pathlib import Path

import pytest

from app.core.config import Settings, SettingsError, get_settings, load_settings
from tests.conftest import PLACEHOLDER_ENV

BACKEND_DIR = Path(__file__).resolve().parents[2]


def full_traceback(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc))


def test_settings_are_read_from_the_environment(monkeypatch):
    monkeypatch.delenv("OPENNOTE_LOG_LEVEL")
    settings = load_settings()
    assert str(settings.database_url) == PLACEHOLDER_ENV["OPENNOTE_DATABASE_URL"]
    assert str(settings.valkey_url) == PLACEHOLDER_ENV["OPENNOTE_VALKEY_URL"]
    assert settings.vault_root == Path("/nonexistent/opennote/vaults")
    assert settings.history_root == Path("/nonexistent/opennote/history")
    assert settings.log_level == "INFO"
    assert settings.environment == "test"


def test_get_settings_is_cached():
    assert get_settings() is get_settings()


def test_invalid_database_url_message_does_not_leak_password(monkeypatch):
    monkeypatch.setenv("OPENNOTE_DATABASE_URL", "postgresql://u:hunter2@/")  # malformed host
    with pytest.raises(SettingsError) as e:
        load_settings()
    assert "hunter2" not in str(e.value)


def test_settings_error_names_only_the_invalid_field_and_chains_nothing(monkeypatch):
    monkeypatch.setenv("OPENNOTE_DATABASE_URL", "postgresql://u:hunter2@/")
    with pytest.raises(SettingsError) as e:
        load_settings()
    assert "database_url" in str(e.value)
    assert "valkey_url" not in str(e.value)
    assert "hunter2" not in full_traceback(e.value)


def test_missing_setting_is_named(monkeypatch):
    monkeypatch.delenv("OPENNOTE_VALKEY_URL")
    with pytest.raises(SettingsError, match="valkey_url"):
        load_settings()


def test_secret_is_read_from_file_when_the_variable_is_unset(monkeypatch, tmp_path):
    url = "postgresql+psycopg://opennote:from-file@db.internal:5432/opennote"
    secret = tmp_path / "database_url"
    secret.write_text(url + "\n")
    monkeypatch.delenv("OPENNOTE_DATABASE_URL")
    monkeypatch.setenv("OPENNOTE_DATABASE_URL_FILE", str(secret))
    assert str(load_settings().database_url) == url


def test_variable_wins_over_file(monkeypatch, tmp_path):
    secret = tmp_path / "valkey_url"
    secret.write_text("redis://from-file:6379/0\n")
    monkeypatch.setenv("OPENNOTE_VALKEY_URL_FILE", str(secret))
    assert str(load_settings().valkey_url) == PLACEHOLDER_ENV["OPENNOTE_VALKEY_URL"]


def test_unreadable_secret_file_names_the_field_not_the_path(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENNOTE_DATABASE_URL")
    monkeypatch.setenv("OPENNOTE_DATABASE_URL_FILE", str(tmp_path / "hunter2-missing"))
    with pytest.raises(SettingsError) as e:
        load_settings()
    assert "database_url" in str(e.value)
    assert "hunter2" not in full_traceback(e.value)


def test_empty_variable_counts_as_unset_so_the_file_is_read(monkeypatch, tmp_path):
    url = "redis://from-file:6379/0"
    secret = tmp_path / "valkey_url"
    secret.write_text(url + "\n")
    monkeypatch.setenv("OPENNOTE_VALKEY_URL", "")
    monkeypatch.setenv("OPENNOTE_VALKEY_URL_FILE", str(secret))
    assert str(load_settings().valkey_url) == url


def test_oversized_secret_file_names_the_field_not_the_content(monkeypatch, tmp_path):
    secret = tmp_path / "database_url"
    secret.write_text("postgresql+psycopg://u:hunter2@h:5432/db" + "x" * 65536)
    monkeypatch.delenv("OPENNOTE_DATABASE_URL")
    monkeypatch.setenv("OPENNOTE_DATABASE_URL_FILE", str(secret))
    with pytest.raises(SettingsError, match="database_url") as e:
        load_settings()
    assert "hunter2" not in full_traceback(e.value)
    assert str(secret) not in full_traceback(e.value)


@pytest.mark.parametrize("make_path", [lambda d: d, lambda d: d / "not-utf8"])
def test_secret_file_that_is_a_directory_or_not_utf8_is_invalid(monkeypatch, tmp_path, make_path):
    (tmp_path / "not-utf8").write_bytes(b"postgresql+psycopg://u:\xff@h/db")
    path = make_path(tmp_path)
    monkeypatch.delenv("OPENNOTE_DATABASE_URL")
    monkeypatch.setenv("OPENNOTE_DATABASE_URL_FILE", str(path))
    with pytest.raises(SettingsError, match="database_url") as e:
        load_settings()
    assert str(path) not in full_traceback(e.value)


def test_settings_repr_and_str_hide_the_connection_urls():
    settings = Settings(
        database_url="postgresql+psycopg://u:pg-LEAK@db:5432/opennote",
        valkey_url="redis://:vk-LEAK@valkey:6379/0",
        vault_root="/srv/vaults",
        history_root="/srv/history",
        environment="test",
    )
    assert "LEAK" not in repr(settings)
    assert "LEAK" not in str(settings)
    assert "/srv/vaults" in repr(settings)


def test_log_level_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("OPENNOTE_LOG_LEVEL", "debug")
    assert load_settings().log_level == "DEBUG"


def test_unknown_log_level_is_rejected(monkeypatch):
    monkeypatch.setenv("OPENNOTE_LOG_LEVEL", "LOUD")
    with pytest.raises(SettingsError, match="log_level"):
        load_settings()


def test_invalid_settings_stop_the_server_with_one_line_and_no_secret():
    env = {**PLACEHOLDER_ENV, "PATH": os.environ["PATH"]}
    env["OPENNOTE_DATABASE_URL"] = "postgresql://u:hunter2@/"
    result = subprocess.run(
        [sys.executable, "-c", "import app.api.main"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 1
    assert result.stderr.strip().splitlines() == [
        "OpenNote cannot start: invalid or missing settings: database_url"
    ]
    assert "hunter2" not in result.stdout + result.stderr
