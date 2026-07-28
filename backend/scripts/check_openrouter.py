"""OpenRouter 키·모델 ID가 실제로 동작하는지 확인하는 일회성 점검 스크립트.

배경(2026-07-28): 라우터가 OpenRouter를 1순위로 두는 태스크(SCANNER/DISCOVERY)가
있는데도 spend가 $0이었다. 원인은 두 가지가 겹친 것:
  1. restart-backend.sh의 `env -u OPENROUTER_API_KEY`가 키를 지워 백엔드가
     구성조차 되지 않음 (constructed=false) — 스크립트 수정으로 해결
  2. 키가 401 'User not found'로 거절되고, 모델 ID에 provider 접두사가 빠짐
     ("deepseek-v4-flash" -> "deepseek/deepseek-v4-flash")

라이브 라우터는 401을 만나면 해당 백엔드를 `_unavailable`에 넣고 **프로세스가
끝날 때까지 다시 시도하지 않는다.** 그래서 키를 고친 뒤에는 반드시 재시작해야
하고, 재시작 전에 이 스크립트로 먼저 검증하는 편이 낫다.

사용:
    cd backend && python scripts/check_openrouter.py

키 값은 절대 출력하지 않는다(길이와 접두사만).
"""

import asyncio
import sys
from pathlib import Path

import httpx

# scripts/ 하위에서 직접 실행해도 backend 패키지를 찾게 한다
# (verify_liquidity_arc.py와 동일 관용구).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402


async def main() -> int:
    s = get_settings()

    print("■ 설정")
    key = s.OPENROUTER_API_KEY
    if not key:
        print("  OPENROUTER_API_KEY : ❌ 없음 (.env 확인)")
        return 1
    raw = key.get_secret_value()
    print(f"  OPENROUTER_API_KEY : 설정됨 (len={len(raw)}, prefix={raw[:7]}…)")
    print(f"  OPENROUTER_MODEL   : {s.OPENROUTER_MODEL}")
    print(f"  OPENROUTER_BASE_URL: {s.OPENROUTER_BASE_URL}")
    print()

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1) 모델 ID가 실재하는가 (키 불필요)
        print("■ 모델 ID 확인")
        try:
            r = await client.get(f"{s.OPENROUTER_BASE_URL}/models")
            ids = [m.get("id", "") for m in r.json().get("data", [])]
            if s.OPENROUTER_MODEL in ids:
                print(f"  ✅ '{s.OPENROUTER_MODEL}' 실재 ({len(ids)}개 중)")
            else:
                print(f"  ❌ '{s.OPENROUTER_MODEL}' 없음 ({len(ids)}개 중)")
                near = [i for i in ids if s.OPENROUTER_MODEL.split("/")[-1] in i]
                if near:
                    print("     비슷한 ID:", ", ".join(near[:5]))
                return 1
        except Exception as e:
            print(f"  ⚠️ 모델 목록 조회 실패: {e}")
        print()

        # 2) 키가 유효한가 (최소 토큰으로 실제 호출)
        print("■ 인증 확인 (최소 호출 1회)")
        try:
            r = await client.post(
                f"{s.OPENROUTER_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {raw}"},
                json={
                    "model": s.OPENROUTER_MODEL,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
            )
        except Exception as e:
            print(f"  ⚠️ 요청 실패: {e}")
            return 1

        if r.status_code == 200:
            print("  ✅ 200 OK — 키·모델 모두 정상. 재시작하면 라우터가 사용한다.")
            return 0

        # 실패 원인을 구분해서 알려준다 — 401과 404는 조치가 다르다.
        try:
            msg = r.json().get("error", {}).get("message", r.text[:200])
        except Exception:
            msg = r.text[:200]
        print(f"  ❌ {r.status_code} — {msg}")
        if r.status_code == 401:
            print("     → 키가 무효하다. OpenRouter 대시보드에서 새로 발급해")
            print("        .env의 OPENROUTER_API_KEY를 교체할 것.")
        elif r.status_code == 404:
            print("     → 모델 ID가 잘못됐다. provider 접두사(deepseek/...)를 확인할 것.")
        elif r.status_code == 402:
            print("     → 크레딧 부족. OpenRouter 계정에 잔액을 충전할 것.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
