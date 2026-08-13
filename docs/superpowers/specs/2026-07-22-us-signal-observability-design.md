# US AI 신호 관측성 (API + FE 카드) — 설계 기록

**날짜:** 2026-07-22
**선행:** US AI 크로스마켓 신호 v1 + AI밸류체인 큐레이션 확장 (둘 다 통합·라이브)
**Goal:** 현재 `us_ai_signal`과 AI밸류체인 큐레이션 목록을 **읽기전용 API + FE 상태 카드**로 노출한다. 신호식/큐레이션/소비자 로직은 **무변경** — 순수 관측성.

## 배경 — 관측성 갭

코드 검색 결과 확증: 큐레이션(`AI_VALUECHAIN_TICKERS`)도 US 신호(`us_ai_signal`)도 **API 라우트 0·프론트엔드 참조 0**. 유일한 관측 창구는 agent-chat 토론의 「시장심리 분석가」 텍스트(간접·산발적). 발굴 후보 API는 `composite_score`만 반환하고 `factor_json`(US 보너스 내역)을 노출하지 않는다. → 사용자가 시스템 상태를 직접 볼 수 없는 실제 UX 갭.

## 엔드포인트 (읽기전용)

`GET /api/trading/discovery/us-signal` — `app/api/routes/trading.py`에 인라인 응답모델로 추가(기존 discovery 라우트 관행). `Depends` 불필요.

```jsonc
{
  "enabled": bool,          // get_settings().US_SIGNAL_ENABLED (off/on 구분용)
  "as_of": str|null,        // 신호 날짜; null = 당일 미갱신
  "signal_pct": float|null, // 간밤 가중 %change (헤드라인)
  "signal": float|null,     // 정규화·클램프 [-1,1] (에이전트 소비값)
  "components": [ {"ticker":str,"weight":float,"change_pct":float|null} ],  // US_AI_TICKERS 가중 + get_cached_us_ai_signal().components 병합
  "computed_at": str|null,
  "curation": [ {"ticker":str,"name":str} ]  // AI_VALUECHAIN_TICKERS — enabled 무관 항상 반환
}
```

**데이터 소스**: `await get_cached_us_ai_signal()`(async, off/stale→None, never-raise) — 반환 dict 키 `{signal, signal_pct, components(dict[str,float]), as_of, computed_at}`. `enabled`는 라우트에서 `get_settings().US_SIGNAL_ENABLED` 별도 조회(getter가 None을 주는 "off"와 "on이나 데이터 없음"을 구분하기 위함). `components`는 `US_AI_TICKERS`(ticker→weight) 순회하며 getter의 change_pct를 병합(신호 None이면 change_pct=null). `curation`은 `AI_VALUECHAIN_TICKERS`에서 항상 생성.

**계약 규칙**: getter가 None(off 또는 stale)이면 as_of/signal_pct/signal/computed_at=null, components의 change_pct=null. curation은 항상 채운다.

## FE 카드

다크 터미널 톤, 기존 카드 셸(`bg-card border border-hairline rounded p-4` + `CardHeader` + `StatusDot`) 재사용. `panels/shared.tsx`의 `fmtPct`/`DASH`/`Awaiting` 사용 — **null이면 숫자 조작 없이 `—`**.

표시:
- 헤드라인: `간밤 미 AI 반도체 {signal_pct 서명%} → 신호강도 {signal}(상한 시 표기)`, up/down 색.
- 컴포넌트 행: `SMH 50% +4.52 · MU 25% +12.17 · NVDA 25% +1.97` (각 %는 색).
- 적용 대상: `적용 대상 (7): 삼성전자·SK하이닉스·…·SK스퀘어` (muted).
- 푸터(`text-[11px] text-dim`): `간밤 미 반도체 성과를 밸류체인 토론·발굴에 반영(넛지) · as_of {as_of} · 갱신 {computed_at}`.

상태:
- **enabled+fresh**(as_of=today) → 초록 StatusDot + 전체.
- **enabled+as_of null** → warn dot + "당일 신호 대기 중(개장 전 갱신 예정)" + 컴포넌트 `—`, 큐레이션은 표시.
- **disabled**(enabled=false) → 회색 dot + "US 신호 비활성 (US_SIGNAL_ENABLED off)" + 큐레이션만.
- **error/404** → graceful(카드 유지, "상태 확인 중…"/에러 dim).

폴링: `useEodReport` 훅 형태(aliveRef + setInterval) 30~60s. 신호는 하루 1회 스냅샷이라 저빈도 충분.

**마운트(동일 컴포넌트 2곳)**:
- `/trading` `TradingDashboard.tsx` — 스위치 3카드 그리드 위 전폭 스트립(`max-w-6xl mx-auto space-y-4` 자식). 1차.
- `/discovery` `DiscoveryLedgerPanel.tsx` — 필터 블록 위. 2차(적용 유니버스 맥락).

## 스코프 / 파일

- **BE**: `app/api/routes/trading.py`(엔드포인트 + 인라인 `UsSignalResponse`류 모델), `tests/test_api/`(또는 기존 trading 라우트 테스트 위치)에 계약 테스트.
- **FE**: `src/types/index.ts`(`UsSignalResponse` 등 타입), `src/api/client.ts`(`getUsSignal()` 메서드 + convenience export), 신규 카드 컴포넌트(예: `src/components/terminal/panels/UsSignalCard.tsx` 또는 `trading/` 하위), 2곳 마운트, 경량 vitest.

## 비목표 / 안전

- 신호식·큐레이션·sentiment 넛지·발굴 보너스 로직 **무변경**.
- 순수 읽기. 추가적·역가역 없음(끄면 카드가 "비활성"). 별도 킬스위치 불필요.
- 시크릿 미노출(응답에 API 키·raw Finnhub 없음).

## 테스트 계획

- **BE**: (a) enabled=true·신호 캐시 있음 → signal_pct/components/curation 채워짐; (b) enabled=true·getter None(stale) → 신호필드 null·curation 채워짐; (c) enabled=false → enabled:false·신호 null·curation 채워짐. get_cached_us_ai_signal/get_settings 모킹, 실 네트워크 금지.
- **FE**: 카드 렌더 — fresh/awaiting/disabled 3상태에서 각각 헤드라인·`—`·큐레이션 목록이 규칙대로 표시되는지(vitest + mock).

## v2 백로그(비포함)

발굴 후보 API의 `us_crossmarket_bonus` 배지 노출(현재 factor_json 미노출)·티어드 가중 표시·토큰 로그 하드닝.
