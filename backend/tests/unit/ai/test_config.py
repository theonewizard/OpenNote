"""AI settings: off by default, a provider needs a URL, the key stays secret, and anything
not plainly on a private network counts as external."""

import pytest

from app.ai.config import AISettings, is_local_host, load_ai_settings
from app.ai.providers import OllamaProvider, OpenAICompatibleProvider, provider_from_settings
from app.core.config import SettingsError


def test_ai_is_off_by_default():
    settings = load_ai_settings()
    assert settings.provider == "none"
    assert provider_from_settings(settings) is None


def test_a_provider_without_a_url_is_refused_by_name(monkeypatch):
    monkeypatch.setenv("OPENNOTE_AI_PROVIDER", "ollama")
    with pytest.raises(SettingsError, match="ai_base_url"):
        load_ai_settings()


def test_an_invalid_setting_names_the_field_never_the_value(monkeypatch):
    monkeypatch.setenv("OPENNOTE_AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENNOTE_AI_BASE_URL", "not-a-url-secret-marker")
    with pytest.raises(SettingsError) as info:
        load_ai_settings()
    assert "ai_base_url" in str(info.value)
    assert "secret-marker" not in str(info.value)


def test_the_api_key_comes_from_its_file_and_stays_out_of_repr(monkeypatch, tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text("sk-test-marker\n")
    monkeypatch.setenv("OPENNOTE_AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENNOTE_AI_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("OPENNOTE_AI_API_KEY_FILE", str(key_file))
    settings = load_ai_settings()
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "sk-test-marker"
    assert "sk-test-marker" not in repr(settings) + str(settings)
    assert isinstance(provider_from_settings(settings), OpenAICompatibleProvider)


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "127.0.0.1",
        "[::1]",
        "10.1.2.3",
        "192.168.1.20",
        "172.16.0.5",
        "fd00::1",
        "169.254.10.1",
        "ollama",  # a Compose service name
        "ollama.ai.svc.cluster.local",
        "ollama.ai.svc",
        "gpu-box.local",
        "gpu-box.lan",
    ],
)
def test_local_hosts(host):
    assert is_local_host(host)


@pytest.mark.parametrize(
    "host", ["api.openai.com", "8.8.8.8", "example.com", "100.64.0.1", "ollama.example.org"]
)
def test_everything_else_is_external(host):
    assert not is_local_host(host)


def test_external_follows_the_base_url():
    local = AISettings(provider="ollama", base_url="http://ollama:11434")
    remote = AISettings(provider="openai", base_url="https://api.openai.com/v1")
    assert isinstance(provider_from_settings(local), OllamaProvider)
    assert not local.external
    assert remote.external


def test_the_claude_key_comes_from_its_file_and_stays_out_of_repr(monkeypatch, tmp_path):
    key_file = tmp_path / "claude"
    key_file.write_text("sk-ant-marker\n")
    monkeypatch.setenv("OPENNOTE_AI_CLAUDE_API_KEY_FILE", str(key_file))
    settings = load_ai_settings()
    assert settings.claude_api_key is not None
    assert settings.claude_api_key.get_secret_value() == "sk-ant-marker"
    assert "sk-ant-marker" not in repr(settings) + str(settings)
    assert (settings.claude_model, settings.claude_effort) == ("claude-opus-5-5", "medium")
    assert settings.provider == "none"  # Claude never becomes the embedding provider
