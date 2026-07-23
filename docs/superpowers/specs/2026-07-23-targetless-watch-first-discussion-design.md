# 진입가 없는 워치 첫 토론 보장 — 설계 기록

**날짜:** 2026-07-23
**Goal:** 진입타겟(`target_entry_price=None`)이 없는 수동 워치도 **최소 1회는 토론(평가)받도록** 보장. 현재 이런 워치는 `_detect_opportunity`의 근접 브랜치(target 필요)와 확신 브랜치(confidence<0.75)가 둘 다 죽어 **영영 감시 밖**(예: 사용자 수동 등록 000660 SK하이닉스 target=None → 오늘 토론 0회). 어제 배포한 발굴 워치 첫토론 보장(`_discovery_reviewed`)의 일반화.

## 근본원인 (라이브 확인)
`_detect_opportunity`(agent_chat/coordinator.py): (a)근접 `target && |cur-target|/target<=3%` OR (b)`confidence>=0.75`. 수동 워치는 confidence=0.5(hold)라 (b) 죽고, **target=None이면 (a)도 죽음** → 절대 발화 안 함. 라이브 확인: 000660 cur=1,911,000·target=None·오늘 토론 **0회**. (반면 target 있는 수동 워치 삼성전자/삼성전기/SK스퀘어는 오늘 9~17회 토론 — 정상.)

## 설계 (어제 arc 일반화)

어제 `_discovery_reviewed`(signal=="discovery"만) → **`_first_reviewed`로 일반화**: 첫 토론 보장을 **①발굴 승격(signal="discovery") ②진입타겟 없는 워치(target_entry_price is None)** 둘 다에 적용.

- `__init__`: `self._discovery_reviewed` → `self._first_reviewed: set[str] = set()` (rename, 의미 일반화).
- `_detect_opportunity`(근접·확신 분기 뒤, `return False` 직전):
```
if (stock.get("signal") == "discovery" or stock.get("target_entry_price") is None) \
        and ticker not in self._first_reviewed:
    return True
```
  (근접/확신이 먼저 검사되므로, target=None이라도 confidence>=0.75면 확신분기가 먼저 발화 — guarantee 분기는 "달리 절대 안 뜨는" 워치만 도달.)
- `_check_watch_list` 시작 루프 마킹: `if (signal=="discovery" or target_entry_price is None) and ticker in _active_rooms: _first_reviewed.add(ticker)` (실제 시작 시만).

## 효과
- **000660 SK하이닉스**: 세션당 1회 토론 보장 → 에이전트 평가(매수 여부) 표면화. (target 없으니 이후 재발화는 없음 — 지속 감시엔 여전히 target 설정이 정공법이나, "최소 1회 평가" 요구는 충족.)
- **발굴 워치**: 어제와 동일(변화 없음).
- **target 있는 정상 수동 워치**: guarantee 미해당(target 있어 근접으로 발화) → 거동 불변.

## 스코프 / 비목표
- **변경**: `services/agent_chat/coordinator.py`(rename + detect 조건 확장 + 마킹 조건 확장) + 테스트.
- **무접촉**: 근접/확신 문턱·투표/confidence 로직·발굴/승격/워치등록. 000660에 target 자동설정 안 함(사용자 선택).
- 인메모리(세션당 1회, 재시작 재평가 — 배포 재시작이 곧 일 단위 재평가). 지속 감시는 target 설정이 정공법(별도 안내).

## 테스트 계획
- target=None·confidence 0.5·signal="hold" 워치 → `_detect_opportunity` True(첫평가), 마킹 후 → False(target 없어 이후 영영 False).
- target=None·confidence 0.8 → 확신분기가 먼저 True(guarantee 무관 — 기존).
- 발굴(signal="discovery") → 여전히 True(회귀).
- target 있는 정상 수동 워치(근접 밖·저확신) → False(거동 불변).
- 실 LLM/네트워크 금지.

## 배포 타이밍
장중 재시작은 진행중 발굴 토론(오늘 라이브 관측)을 끊으므로 **장 마감(16:35) 후 배포 권장**(000660은 내일 개장 시 평가). 사용자가 즉시 원하면 재시작.
