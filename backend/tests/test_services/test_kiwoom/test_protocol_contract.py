"""공통 프로토콜 계약 테스트 (Paper-Proof Phase A1-t1).

계약 감사(2026-07-12)가 확정한 전송 계층 결함을 공식 스펙 기준으로 고정:
- C9: cont-yn/next-key는 응답 HTTP **헤더**로 온다 (body 아님) — 참조 구현
  Kiwoom-REST-API/kiwoom/core/client.py:232-238
- M5: 토큰만료(8005 등)/401 시 재발급-재시도 1회; expires_dt는 KST;
  revoke body는 appkey/secretkey/token 3필드
- M6: 실서버 에러코드는 양수(1700 레이트리밋, 8001-8031 인증/모드)
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.kiwoom.auth import KiwoomAuth
from services.kiwoom.client import KiwoomClient
from services.kiwoom.errors import KiwoomError
from services.kiwoom.models import KiwoomToken

KST = timezone(timedelta(hours=9))


@pytest.fixture
def client():
    c = KiwoomClient(
        app_key="k", secret_key="s", is_mock=True,
        enable_rate_limit=False, enable_cache=False,
    )
    c.auth.get_token = AsyncMock(return_value="T")
    return c


def _http_response(body, headers=None, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    if isinstance(body, Exception):
        resp.json.side_effect = body
    else:
        resp.json.return_value = body
    return resp


def _patch_post(client, responses):
    http = MagicMock()
    http.post = AsyncMock(side_effect=list(responses))
    client._client = http
    return http


class TestContinuationFromHeaders:
    """C9 — 연속조회 값은 응답 헤더에서 읽는다."""

    @pytest.mark.asyncio
    async def test_request_exposes_continuation_from_response_headers(self, client):
        _patch_post(client, [
            _http_response({"return_code": 0}, headers={"cont-yn": "Y", "next-key": "NK1"}),
        ])
        result, cont = await client._request(
            "ka10099", "/api/dostk/stkinfo", {}, with_continuation=True
        )
        assert result == {"return_code": 0}
        assert cont == {"cont_yn": "Y", "next_key": "NK1"}

    @pytest.mark.asyncio
    async def test_get_stock_list_follows_header_pagination(self, client):
        page1 = {"return_code": 0, "list": [
            {"code": "005930", "name": "삼성전자", "listCount": "1", "marketName": "코스피"}]}
        page2 = {"return_code": 0, "list": [
            {"code": "000660", "name": "SK하이닉스", "listCount": "1", "marketName": "코스피"}]}
        http = _patch_post(client, [
            _http_response(page1, headers={"cont-yn": "Y", "next-key": "NK1"}),
            _http_response(page2, headers={"cont-yn": "N", "next-key": ""}),
        ])
        stocks = await client.get_stock_list()
        assert [s.code for s in stocks] == ["005930", "000660"]
        # 2번째 요청이 next-key를 요청 헤더로 되돌려보냈는지
        second_headers = http.post.call_args_list[1].kwargs["headers"]
        assert second_headers.get("cont-yn") == "Y"
        assert second_headers.get("next-key") == "NK1"


class TestAuthRetry:
    """M5 — 토큰만료 응답이면 재발급 후 1회 재시도."""

    @pytest.mark.asyncio
    async def test_token_expired_code_triggers_reissue_and_retry(self, client):
        _patch_post(client, [
            _http_response({"return_code": 8005, "return_msg": "토큰이 만료되었습니다"}),
            _http_response({"return_code": 0, "ok": True}),
        ])
        client.auth.invalidate_token = MagicMock()
        result = await client._request("ka10001", "/api/dostk/stkinfo", {})
        assert result["ok"] is True
        client.auth.invalidate_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_http_401_triggers_reissue_and_retry(self, client):
        _patch_post(client, [
            _http_response({}, status_code=401),
            _http_response({"return_code": 0, "ok": True}),
        ])
        client.auth.invalidate_token = MagicMock()
        result = await client._request("ka10001", "/api/dostk/stkinfo", {})
        assert result["ok"] is True
        client.auth.invalidate_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_persistent_token_expiry_raises_after_one_retry(self, client):
        _patch_post(client, [
            _http_response({"return_code": 8005, "return_msg": "만료"}),
            _http_response({"return_code": 8005, "return_msg": "만료"}),
        ])
        client.auth.invalidate_token = MagicMock()
        with pytest.raises(KiwoomError):
            await client._request("ka10001", "/api/dostk/stkinfo", {})


class TestNonJsonDefense:
    """M5 — 비-JSON 오류 응답이 미처리 예외로 새지 않는다."""

    @pytest.mark.asyncio
    async def test_non_json_error_page_raises_kiwoom_error(self, client):
        _patch_post(client, [
            _http_response(ValueError("not json"), status_code=502),
        ])
        with pytest.raises(KiwoomError):
            await client._request("ka10001", "/api/dostk/stkinfo", {})


class TestRealErrorCodes:
    """M6 — 실서버 양수 에러코드 분류."""

    def test_rate_limit_1700(self):
        e = KiwoomError(code=1700, message="허용된 요청 개수를 초과하였습니다")
        assert e.is_rate_limit is True
        assert e.is_retryable is True

    def test_token_codes_are_auth_errors(self):
        for code in (8003, 8005, 8006, 8009, 8015, 8016):
            e = KiwoomError(code=code)
            assert e.is_token_expired is True, code
            assert e.is_auth_error is True, code

    def test_credential_codes_are_auth_but_not_token_expired(self):
        for code in (8001, 8002, 8011, 8012):
            e = KiwoomError(code=code)
            assert e.is_auth_error is True, code
            assert e.is_token_expired is False, code

    def test_rate_limit_not_matched_by_substring(self):
        # 가격 121700이 메시지에 있어도 레이트리밋으로 오탐하지 않는다
        e = KiwoomError(code=907, message="가격 121700원은 호가단위 위반")
        assert e.is_rate_limit is False


class TestTokenKst:
    """M5 — expires_dt는 KST로 해석하고 tz-aware로 비교."""

    def test_expires_dt_parsed_as_kst(self):
        auth = KiwoomAuth(base_url="https://mockapi.kiwoom.com", app_key="k", secret_key="s")
        parsed = auth._parse_expires_dt("20260713124346")
        assert parsed.tzinfo is not None
        assert parsed == datetime(2026, 7, 13, 12, 43, 46, tzinfo=KST)

    def test_token_expiry_check_is_tz_aware(self):
        token = KiwoomToken(
            token="T",
            expires_dt=datetime.now(KST) + timedelta(hours=1),
        )
        assert token.is_expired is False
        expired = KiwoomToken(
            token="T",
            expires_dt=datetime.now(KST) - timedelta(seconds=1),
        )
        assert expired.is_expired is True


class TestRevokeBody:
    """M5 — revoke body는 appkey/secretkey/token 3필드 (참조 구현 auth.py:180-189)."""

    @pytest.mark.asyncio
    async def test_revoke_sends_credentials_in_body(self):
        auth = KiwoomAuth(base_url="https://mockapi.kiwoom.com", app_key="AK", secret_key="SK")
        auth._token = KiwoomToken(
            token="T", expires_dt=datetime.now(KST) + timedelta(hours=1)
        )
        http = MagicMock()
        http.post = AsyncMock(return_value=_http_response({"return_code": 0}))
        auth._client = http

        await auth.revoke_token()

        body = http.post.call_args.kwargs["json"]
        assert body == {"appkey": "AK", "secretkey": "SK", "token": "T"}
