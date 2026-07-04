"""Phase 1: OpenRouter + CLI + budget settings exist and SecretStr never leaks."""
from app.config import Settings


def test_openrouter_and_cli_settings_exist():
    s = Settings()
    assert s.OPENROUTER_BASE_URL.startswith("https://openrouter.ai")
    assert s.OPENROUTER_MODEL  # non-empty default
    assert s.LLM_LOCAL_ENABLED is False           # cloud-first default
    assert s.CLAUDE_STRATEGIC_MODEL == "opus"
    assert s.CLAUDE_FALLBACK_MODEL == "sonnet"
    assert s.OPENROUTER_DAILY_BUDGET_USD == 5.0
    assert s.LLM_CLI_CONCURRENCY == 2
    assert s.LLM_CLI_TIMEOUT == 180


def test_secret_never_leaks_in_repr():
    s = Settings(OPENROUTER_API_KEY="sk-secret-xyz")
    assert "sk-secret-xyz" not in repr(s)
    assert s.OPENROUTER_API_KEY.get_secret_value() == "sk-secret-xyz"


def test_openrouter_key_defaults_none():
    assert Settings().OPENROUTER_API_KEY is None
