# 발굴 승격 Telegram 통지 — 설계 기록

**날짜:** 2026-07-22
**Goal:** 자율 발굴이 종목을 승격→워치리스트 배선할 때 **간결·핵심 정보**를 Telegram으로 전달. HITL/버튼 없음(자율매매가 목표) — 일방향 정보 통지. 현재 갭: 수동 트리거(`run_discovery_pipeline`) 경로엔 통지 step이 아예 없고, 15:30 요약의 발굴 블록은 compact(티커/composite만)이라 무엇을·왜·어디 배선됐는지 부족.

## 확정 메시지 형식 (사용자 승인)
```
🔍 자율 발굴 승격 5종 · 07-22
• 위닉스 044340 · 0.73 momentum · 워치 3,850
• SK이터닉스 475150 · 0.67 momentum · 워치 62,000
• 가비아 079940 · 0.66 momentum · 워치 47,500
• 인탑스 049070 · 0.65 momentum · 워치 18,860
• 새론오토모티브 075180 · 0.65 pullback · 워치 2,975
+16종 daily_cap 대기 · 개장 시 토론→투표
```
- 한 종목 = 한 줄: `{이름} {티커} · {composite:.2f} {전략} · 워치 {target}`.
- 헤더: `🔍 자율 발굴 승격 {N}종 · {trade_date}`.
- 푸터: daily_cap 스킵 있으면 `+{K}종 daily_cap 대기 · 개장 시 토론→투표`, 없으면 `개장 시 토론→투표`.
- **핵심만**(주구절절 금지): 왜=composite+전략, 배선=워치 target + 다음단계.
- 종목이 많으면(>N_MAX, 예 10) 상위 composite N_MAX만 + "외 M종".

## 배선

- **위치**: `services/discovery/orchestrator.py::run_discovery_pipeline`의 `promote_candidates` 직후(~line 54-58). **수동 트리거·15:30 EOD 양 경로 모두** 이 함수를 거치므로 한 지점 배선으로 둘 다 커버.
- **데이터**: 랭킹된 `candidates`에서 `promote_summary.promoted`(티커 리스트)에 해당하는 Candidate만 필터 → `name`·`composite`·`top_strategy_tag`·`target`(=`close_price`, promote 시 target_entry_price로 사용된 값) 추출. `promote_summary.skipped`에서 `daily_cap` 개수 카운트.
- **게이트**: 신규 `TELEGRAM_NOTIFY_DISCOVERY: bool = True`(config, 기존 TELEGRAM_NOTIFY_* 카테고리 관행). off면 미발송.
- **승격 0이면 미발송**(매일 "0 승격"은 소음 → 신호만).
- **never-raise**: 통지 실패가 파이프라인/승격에 영향 없음(try/except log-only, 기존 telegram 호출 관행).

## Telegram 서비스

`services/telegram/service.py`에 `send_discovery_promotion(...)` + `_format_discovery_promotion(...)` 추가(기존 `send_X`+`_format_X` 관행). TelegramService 미설정/비활성 시 no-op(기존 패턴). 시그니처(안):
```
async def send_discovery_promotion(
    self, *, trade_date: str, promoted: list[dict], daily_cap_waiting: int
) -> bool
# promoted item: {"ticker","name","composite","strategy","target"}
```

## 스코프 / 태스크
- **T1**(telegram·config): `send_discovery_promotion`+`_format_discovery_promotion`+`TELEGRAM_NOTIFY_DISCOVERY` + 포맷 단위 테스트(형식·0건·overflow).
- **T2**(orchestrator): `run_discovery_pipeline` promote 직후 배선(candidates 필터→상세 구성→gated·never-raise 호출) + 테스트.

## 비목표 / 안전
- HITL/버튼/양방향 없음(일방향 정보). 기존 "장마감 요약" 발굴 블록은 그대로 둠(전일 recap 맥락, 별도).
- 승격/파이프라인 로직 무변경 — 통지만 부가. 실 네트워크/실 Telegram 발송 테스트 금지(TelegramService 모킹, 포맷 검증).

## 후속(비포함)
배선 재감사(workflow wgip2brxv) 결과에 따라 다른 자율 이벤트(BUY 실행·손절 등)의 통지 커버리지 갭이 나오면 별도 arc.
