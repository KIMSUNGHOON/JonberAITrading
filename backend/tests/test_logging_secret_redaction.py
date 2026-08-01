"""로그 비밀 마스킹 회귀 테스트.

절대 실제 비밀 값을 쓰지 않는다 — 합성 토큰만 사용한다.

핵심 함정 2가지를 코드로 못 박는다:
1) 필터를 로거(특히 root)에 붙이면 자식 로거(httpx)에서 전파된 레코드를
   마스킹하지 못한다 — 반드시 핸들러에 붙여야 한다.
2) httpx는 URL을 record.msg가 아니라 record.args에 담는다(args[1]이
   httpx.URL 객체). record.msg만 치환하는 필터는 조용히 무력하고,
   args를 순회해 re.sub을 돌리면 TypeError로 로깅 자체가 깨진다.
"""

from __future__ import annotations

import io
import logging

import httpx
import pytest

from app.logging_config import (
    RequestLoggingMiddleware,
    SecretRedactingFilter,
    configure_logging,
    mask_secrets,
)

# 합성 값만 사용한다 — 실제 토큰/키가 아니다.
FAKE_TG = "123456789:AAFakeTokenForTest_xyz-0000000000"
FAKE_FH = "fakefinnhubkey0000"


@pytest.fixture(autouse=True)
def _restore_logging_state():
    """configure_logging()이 root 로거를 오염시키므로 전후로 저장·복원한다."""
    root = logging.getLogger()
    saved_level = root.level
    saved_handlers = list(root.handlers)

    saved_child_levels = {
        name: logging.getLogger(name).level
        for name in ("httpx", "httpcore", "telegram.Bot")
    }

    yield

    root.handlers.clear()
    root.setLevel(saved_level)
    for h in saved_handlers:
        root.addHandler(h)
    for name, level in saved_child_levels.items():
        logging.getLogger(name).setLevel(level)


# ---------------------------------------------------------------------------
# mask_secrets() 단위 테스트
# ---------------------------------------------------------------------------


def test_mask_secrets_telegram_path_variants():
    """세 가지 텔레그램 토큰 변종 모두 마스킹되고, /file/ 접두는 보존된다."""
    path_form = f"https://api.telegram.org/bot{FAKE_TG}/sendMessage"
    no_trailing_slash = f"Set Bot API URL: https://api.telegram.org/bot{FAKE_TG}"
    file_form = f"https://api.telegram.org/file/bot{FAKE_TG}/x"

    masked_path = mask_secrets(path_form)
    masked_no_slash = mask_secrets(no_trailing_slash)
    masked_file = mask_secrets(file_form)

    assert FAKE_TG not in masked_path
    assert "/bot<REDACTED>" in masked_path

    assert FAKE_TG not in masked_no_slash
    assert "/bot<REDACTED>" in masked_no_slash

    assert FAKE_TG not in masked_file
    assert "/file/bot<REDACTED>" in masked_file


def test_mask_secrets_query_secrets():
    """쿼리스트링 토큰(Finnhub 등)은 지워지고 symbol 같은 무해한 파라미터는 남는다."""
    url = f"https://finnhub.io/api/v1/quote?symbol=SMH&token={FAKE_FH}"
    masked = mask_secrets(url)

    assert FAKE_FH not in masked
    assert "symbol=SMH" in masked
    assert "token=<REDACTED>" in masked


def test_mask_secrets_no_over_masking():
    """정상 로그 내용은 손대지 않는다 — 과잉 마스킹 방지 회귀 테스트."""
    samples = [
        "max_tokens=4096",
        "?symbol=SMH&resolution=D",
        "token_count=12",
        "삼성전자 094840 1,315주 @13,060 손절 12,492",
    ]
    for s in samples:
        assert mask_secrets(s) == s


# ---------------------------------------------------------------------------
# 핸들러 필터 동작 — 핵심 함정 재현
# ---------------------------------------------------------------------------


def test_handler_filter_masks_child_logger_args_form():
    """httpx와 동일한 args 형태(URL 객체가 args[1])로 로깅해도 마스킹되고 예외가 나지 않는다.

    args를 순진하게 re.sub 하는 구현이면 httpx.URL 객체에 TypeError가 난다.
    msg만 치환하는 구현이면 args의 토큰이 그대로 남는다.
    """
    logger = logging.getLogger("test_httpx_args_form")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecretRedactingFilter())
    logger.addHandler(handler)

    # httpx._client가 실제로 쓰는 호출 형태: URL이 record.args[1]에 httpx.URL 객체로 들어간다.
    logger.info(
        'HTTP Request: %s %s "%s %d %s"',
        "POST",
        httpx.URL(f"https://api.telegram.org/bot{FAKE_TG}/sendMessage"),
        "HTTP/1.1",
        200,
        "OK",
    )

    output = stream.getvalue()
    assert FAKE_TG not in output
    assert "<REDACTED>" in output


def test_root_logger_filter_does_not_cover_children():
    """필터를 '로거'에 붙이면(오답) 자식 로거의 전파 레코드가 마스킹되지 않는다.

    이 테스트는 오답 구현으로의 회귀를 코드로 막기 위한 것이다 — 통과 조건은
    '마스킹되지 않음'(즉 함정이 재현됨)이다.
    """
    parent = logging.getLogger("test_root_filter_parent")
    parent.handlers.clear()
    parent.propagate = False
    parent.setLevel(logging.DEBUG)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    parent.addHandler(handler)
    # 오답: 로거에 붙인다 (핸들러가 아니라)
    parent.addFilter(SecretRedactingFilter())

    child = logging.getLogger("test_root_filter_parent.httpx")
    child.setLevel(logging.DEBUG)
    child.propagate = True

    child.info(f"HTTP Request: bot url https://api.telegram.org/bot{FAKE_TG}/sendMessage")

    output = stream.getvalue()
    # 함정 재현: 로거-레벨 필터는 자식 전파 레코드를 보지 못하므로 토큰이 그대로 남는다.
    assert FAKE_TG in output


def test_two_handlers_idempotent():
    """필터가 붙은 핸들러 2개를 거쳐도 동일하게 마스킹되고, 비밀 없는 args 로그는 온전히 포맷된다."""
    logger = logging.getLogger("test_idempotent")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)

    stream_a = io.StringIO()
    stream_b = io.StringIO()
    handler_a = logging.StreamHandler(stream_a)
    handler_b = logging.StreamHandler(stream_b)
    handler_a.addFilter(SecretRedactingFilter())
    handler_b.addFilter(SecretRedactingFilter())
    logger.addHandler(handler_a)
    logger.addHandler(handler_b)

    logger.info(f"https://api.telegram.org/bot{FAKE_TG}/sendMessage")

    out_a = stream_a.getvalue()
    out_b = stream_b.getvalue()
    assert FAKE_TG not in out_a
    assert FAKE_TG not in out_b
    assert out_a == out_b

    stream_a.truncate(0)
    stream_a.seek(0)
    stream_b.truncate(0)
    stream_b.seek(0)

    logger.info("no secret here %d", 42)
    assert "no secret here 42" in stream_a.getvalue()
    assert "no secret here 42" in stream_b.getvalue()


def test_exc_text_masked():
    """트레이스백(exc_info)에 실린 토큰도 마스킹된다."""
    logger = logging.getLogger("test_exc_text")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    # exc_text는 기본 Formatter.format()이 알아서 traceback을 붙이므로 별도 포맷 불필요
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(SecretRedactingFilter())
    logger.addHandler(handler)

    try:
        raise RuntimeError(
            f"connect failed for url 'https://api.telegram.org/bot{FAKE_TG}/sendMessage'"
        )
    except RuntimeError:
        logger.exception("boom")

    output = stream.getvalue()
    assert FAKE_TG not in output


# ---------------------------------------------------------------------------
# configure_logging() 배선 확인
# ---------------------------------------------------------------------------


def test_configure_logging_attaches_filter_to_every_handler():
    """configure_logging() 후 root의 모든 핸들러가 SecretRedactingFilter를 보유한다."""
    configure_logging(debug_to_file=False)

    root = logging.getLogger()
    assert root.handlers, "root logger에 핸들러가 없다"
    for handler in root.handlers:
        assert any(
            isinstance(f, SecretRedactingFilter) for f in handler.filters
        ), f"{handler}에 SecretRedactingFilter가 붙어있지 않다"


def test_configure_logging_suppresses_leaky_loggers():
    """httpx/httpcore는 WARNING으로, telegram.Bot은 INFO로 억제된다."""
    configure_logging(debug_to_file=False)

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
    assert logging.getLogger("telegram.Bot").level == logging.INFO


# ---------------------------------------------------------------------------
# 민감 경로 바디 로깅 스킵
# ---------------------------------------------------------------------------


def test_sensitive_path_skips_body_logging():
    """설정(비밀) 경로는 바디 로깅 대상에서 제외되고, 일반 경로는 유지된다.

    (2026-08-01 Upbit 제거: 이 룰은 "/settings" 하나를 접두사로 잡는 범용
    매칭이라 특정 하위 경로에 의존하지 않는다 — /api/settings/upbit는
    Task 6에서 사라졌으므로 예시를 현재 살아있는 /settings/kiwoom 계열
    경로로 정정했다. `_SENSITIVE_BODY_PATHS` 자체는 손대지 않는다.)
    """
    middleware = RequestLoggingMiddleware(app=None)

    assert middleware._is_sensitive_path("/api/settings/kiwoom") is True
    assert middleware._is_sensitive_path("/api/v1/settings/kiwoom/validate") is True
    assert middleware._is_sensitive_path("/api/trading/watch-list") is False
