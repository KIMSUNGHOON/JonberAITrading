"""유동성 인지 아크 배포 전 실측 재현 검증(일회성, Task 8).

설계 문서 §2.2(`docs/superpowers/specs/2026-07-27-liquidity-aware-discovery-
design.md`)의 표를 실제 코드(`services.discovery.ranker._effective_weights`)로
재현한다. 2026-07-23 배치(`discovery_candidates`, promoted=1)의 저장된
`strategy_scores_json`으로 신규 가중 재정규화 폐기 로직을 적용해 composite를
재계산하고, 승격 5종의 운명이 설계 문서와 일치하는지 확인한다.

기대(§2.2):
- 317400 자이에스앤디, 089860 롯데렌탈 (flow_present=True) -> 점수 무변화, 생존(>=0.55)
- 094840 슈프리마HQ, 214260 라파스, 093190 빅솔론 (flow 결측) -> 0.55 미만으로 하락, 탈락

DB 경로: 이 worktree는 tracked 파일만 가져오므로 `backend/data/storage.db`에
2026-07-23 발굴 배치가 없을 수 있다. 그 경우 공유 체크아웃의 DB
(`../../../backend/data/storage.db`, 라이브 서버가 쓰는 파일)를 **읽기 전용
URI**로 연다 — 절대 쓰지 않는다. 실행 시 어느 DB를 쓰는지 항상 stdout에
찍는다.

읽기 전용 보장: `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`만 쓴다.
INSERT/UPDATE/DELETE/DDL 문은 이 파일에 없다.

실행 (backend/ 에서):
    env -u OPENROUTER_API_KEY python scripts/verify_liquidity_arc.py
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.discovery.ranker import _effective_weights  # noqa: E402

TRADE_DATE = "2026-07-23"

BULLISH = {"momentum": 0.40, "pullback": 0.25, "flow": 0.25, "meanrev": 0.10}
EXPECT_SURVIVE = {"317400", "089860"}
EXPECT_DROP = {"094840", "214260", "093190"}
THRESHOLD = 0.55

# 후보 DB 경로: worktree 로컬 -> 공유 체크아웃(라이브 서버 소유, 읽기전용).
_WORKTREE_DB = Path(__file__).resolve().parent.parent / "data" / "storage.db"
_SHARED_CHECKOUT_DB = Path(
    "/Users/sunghoonk/Workspaces/JonberAITrading/backend/data/storage.db"
)


def _fetch_rows(db_path: Path):
    """읽기 전용 URI로 연결해 promoted 후보 행을 가져온다. 절대 쓰지 않는다."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute(
            "SELECT ticker, name, composite_score, strategy_scores_json "
            "FROM discovery_candidates WHERE trade_date=? AND promoted=1",
            (TRADE_DATE,),
        ).fetchall()
    finally:
        conn.close()
    return rows


def _resolve_db_path() -> Path:
    """worktree DB에 대상 배치가 있으면 그것을, 없으면 공유 체크아웃 DB를
    쓴다. 둘 다 없거나 조회에 실패하면 None을 반환(호출자가 종료 처리)."""
    for candidate, label in (
        (_WORKTREE_DB, "worktree local"),
        (_SHARED_CHECKOUT_DB, "shared checkout (READ-ONLY, live server owns this file)"),
    ):
        if not candidate.exists():
            print(f"[skip] {label} DB not found: {candidate}")
            continue
        try:
            rows = _fetch_rows(candidate)
        except sqlite3.Error as e:
            print(f"[skip] {label} DB query failed: {candidate} ({e})")
            continue
        if rows:
            print(f"[using] {label} DB: {candidate}  ({len(rows)} promoted rows for {TRADE_DATE})")
            return candidate, rows
        print(f"[skip] {label} DB has no promoted={TRADE_DATE} rows: {candidate}")
    return None, []


def main() -> int:
    db_path, rows = _resolve_db_path()
    if not rows:
        print(
            f"\n검증 불가: 2026-07-23 promoted discovery_candidates 데이터를 "
            f"worktree DB({_WORKTREE_DB})와 공유 체크아웃 DB({_SHARED_CHECKOUT_DB}) "
            "어디에서도 찾지 못했다."
        )
        return 1

    failures = []
    seen = set()
    for ticker, name, old, sj in rows:
        seen.add(ticker)
        s = json.loads(sj)
        raw = {k: (s.get(k) or 0.0) for k in BULLISH}
        flow_present = (s.get("_weights", {}) or {}).get("flow", 0.0) > 0
        w = _effective_weights(dict(BULLISH), flow_present)
        new = sum(raw[k] * w[k] for k in BULLISH)
        status = "생존" if new >= THRESHOLD else "탈락"
        print(f"{ticker} {name:<12} {old:.4f} -> {new:.4f}  flow={flow_present}  {status}")

        if ticker in EXPECT_SURVIVE:
            if new < THRESHOLD:
                failures.append(f"{ticker} 생존 기대했으나 탈락 (new={new:.4f})")
            elif abs(new - old) > 1e-9:
                failures.append(
                    f"{ticker} flow_present=True인데 점수가 변했다 (old={old:.4f}, new={new:.4f})"
                )
        if ticker in EXPECT_DROP and new >= THRESHOLD:
            failures.append(f"{ticker} 탈락 기대했으나 생존 (new={new:.4f})")

    missing = (EXPECT_SURVIVE | EXPECT_DROP) - seen
    if missing:
        failures.append(f"기대 종목이 배치에 없다: {sorted(missing)}")

    if failures:
        print("\n검증 실패:", *failures, sep="\n  ")
        return 1
    print("\n✅ 실측 재현 일치 — 설계 문서 §2.2와 동일")
    return 0


if __name__ == "__main__":
    sys.exit(main())
