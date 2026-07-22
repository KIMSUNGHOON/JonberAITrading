# 발굴 워치 첫 토론 보장 — 설계 기록

**날짜:** 2026-07-22
**Goal:** 자율 발굴이 승격한 워치가 **갭 여부와 무관하게 최소 한 번은 토론(평가)받도록** 보장. 매수는 강제하지 않음 — 4에이전트 투표가 여전히 결정("문을 열되 검문 불변"). 내일 개장 시 오늘 승격 5종이 실제로 토론→투표에 오르게 함.

## 근본원인 (확정 + 코드 주석이 이미 인지)

`ranker.promote_candidates`가 `add_to_watch_list(signal="discovery", confidence=c.composite, target_entry_price=close_price)`로 승격(ranker.py 주석: *"left them dependent on the (much stricter) high-confidence-only fallback branch"*). `agent_chat/coordinator._detect_opportunity`(coordinator.py:619-668)는:
- (a) 근접: `target_price && current_price`이고 `|cur-target|/target <= proximity_pct`(기본 0.03).
- (b) 확신: `confidence >= min_confidence`(기본 0.75).
- 발굴 워치는 confidence=composite(0.65~0.73 < 0.75)라 **(b) 죽어있음** → 근접만 유효 → **전일종가 ±3% 밖으로 갭 시 영영 토론 안 됨**.

## 설계

**원칙**: 승격 종목은 최소 1회 평가 보장(근접/확신 무관). 투표는 불변(NO_ACTION/BUY는 에이전트 판단).

- `agent_chat/coordinator` `__init__`에 인메모리 `self._discovery_reviewed: set[str] = set()`.
- `_detect_opportunity`: 기존 근접·확신 분기 유지하되, **신규 분기** — `stock.get("signal") == "discovery"` AND `ticker not in self._discovery_reviewed` → `return True`(첫 평가 보장). (구현자: `_get_watch_list`이 dict에 `signal`을 포함하는지 확인 — 없으면 포함시킴. `_detect_opportunity`는 이미 target_entry_price/confidence를 dict에서 읽으므로 signal도 동일 소스.)
- `_check_watch_list` 시작 루프: 토론이 **실제 시작된 경우에만** 마킹 — `_start_discussion` 후 `ticker in self._active_rooms`이면 `signal=="discovery"`일 때 `_discovery_reviewed.add(ticker)`. (감지 시점 아님 → 슬롯부족/실패 미시작분은 다음 tick 재기회. stale로 미시작 시 재시도.)
- 마킹 후엔 기존 근접/확신 로직으로 복귀(재토론은 근접 시에만).

## 효과
내일 개장 시 승격 5종(위닉스·SK이터닉스·가비아·인탑스·새론오토모티브)이 갭 여부와 무관하게 각 1회 토론→투표. 슬롯(max_concurrent)·recently_discussed 스로틀 그대로 → 폭주 없음.

## 스코프 / 비목표
- **변경**: `services/agent_chat/coordinator.py`(set 추가·detect 분기·start 마킹·필요 시 signal을 watch dict에 포함) + 테스트.
- **무접촉**: 0.75 합의 문턱·vote_to_action·투표/confidence 로직(의도된 보수성; 감사의 "NO_ACTION 편향"은 별도 리스크선호 결정). 발굴/승격/워치등록 로직 무변경.
- **인메모리 트레이드오프**: 재시작 시 discovery 워치 1회 재평가(무해 — 재토론일 뿐). 영속 불요.

## 테스트 계획
- 발굴 워치(signal="discovery", confidence 0.7, 근접 밖) → `_detect_opportunity` True(첫 평가). `_discovery_reviewed`에 추가 후 → False(복귀). 근접/확신 충족 시엔 기존대로 True.
- 비-발굴 워치(signal="hold")는 discovery 분기 미적용(기존 로직 불변).
- 슬롯부족/미시작분은 마킹 안 됨(재기회).
- 실 LLM/네트워크 금지(coordinator 유닛, _start_discussion/_active_rooms 모킹).
