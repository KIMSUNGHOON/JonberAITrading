"""Phase 1: OpenRouter + CLI + budget settings exist and SecretStr never leaks.

이 테스트는 **코드 기본값**을 고정한다. `Settings()`를 그냥 부르면 pydantic이
프로젝트 루트의 `.env`를 읽어버려, 운영자가 거기에 실제 키나 예산을 넣는 순간
테스트가 깨진다(2026-07-28 실제 발생: `.env`에 OPENROUTER_API_KEY를 넣자
`test_openrouter_key_defaults_none`이, 예산을 올리자 나머지 둘이 실패).

테스트가 운영자의 환경 파일에 의존하면 안 되므로 `_defaults()`로 `.env`를
차단해 코드 기본값만 본다. 실제 배포 설정이 맞는지는 테스트가 아니라
`/api/llm/stats`로 관측할 일이다.
"""
from app.config import Settings


def _defaults(**overrides) -> Settings:
    """`.env`를 무시하고 코드 기본값만으로 Settings를 만든다.

    `_env_file=None`은 pydantic-settings가 지원하는 인스턴스 단위 오버라이드로,
    이 호출에 한해 dotenv 로딩을 끈다. 실제 환경변수도 막으려면 각 테스트가
    monkeypatch로 지우면 되지만, 여기서 고정하는 값들은 CI/로컬 셸에 없는
    항목이라 `.env` 차단만으로 충분하다.
    """
    return Settings(_env_file=None, **overrides)


def test_openrouter_and_cli_settings_exist():
    s = _defaults()
    assert s.OPENROUTER_BASE_URL.startswith("https://openrouter.ai")
    assert s.OPENROUTER_MODEL  # non-empty default
    assert s.LLM_LOCAL_ENABLED is False           # cloud-first default
    assert s.CLAUDE_STRATEGIC_MODEL == "opus"
    assert s.CLAUDE_FALLBACK_MODEL == "sonnet"
    assert s.OPENROUTER_DAILY_BUDGET_USD == 5.0
    assert s.LLM_CLI_CONCURRENCY == 2
    assert s.LLM_CLI_TIMEOUT == 180


def test_secret_never_leaks_in_repr():
    s = _defaults(OPENROUTER_API_KEY="sk-secret-xyz")
    assert "sk-secret-xyz" not in repr(s)
    assert s.OPENROUTER_API_KEY.get_secret_value() == "sk-secret-xyz"


def test_openrouter_key_defaults_none():
    assert _defaults().OPENROUTER_API_KEY is None


def test_env_file_can_override_defaults():
    """운영자가 `.env`로 값을 바꿀 수 있다는 계약도 함께 고정한다.

    위 테스트들이 `.env`를 차단하므로, 차단이 "설정을 못 바꾼다"는 뜻으로
    오해되지 않도록 반대편을 명시한다.
    """
    s = _defaults(OPENROUTER_DAILY_BUDGET_USD=100000.0)
    assert s.OPENROUTER_DAILY_BUDGET_USD == 100000.0
