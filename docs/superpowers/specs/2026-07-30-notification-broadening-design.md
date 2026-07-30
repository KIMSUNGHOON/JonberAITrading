# 통지 광역화 설계 — 체결 통지(push) + 대화형 명령어(pull)

**작성일**: 2026-07-30
**상태**: 승인됨 (설계 확정, 구현 대기)

## 문제

폰이 트레이딩 시스템의 유일한 창인데, 그 창이 세 방향으로 고장 나 있다.

**1. 필요한 것을 보내지 않는다.** 자율 BUY·SELL 체결에 Telegram 통지가 없다. 07-24
자율 손절 청산과 07-27 익절(+₩350,033, +9.62%) 둘 다 폰 통지가 없었다. 발송 메서드는
이미 존재하는데 호출하는 곳이 없다 — `send_stop_loss_triggered`, `send_take_profit_triggered`,
`send_position_update`, `send_error_alert` 모두 **호출처 0건**이고
`send_trade_executed`는 `approval.py:715`의 HITL 승인 경로에서만 불린다.

**2. 잘못된 것을 보낸다.** `_notify_event`(`position_manager.py:1145`)가
`TELEGRAM_NOTIFY_*` 게이트를 전혀 거치지 않아 저가치 알림이 스팸으로 나간다. 07-30
2시간 동안 13건, 그중 `trailing_stop` 7건이고 11:35~11:37에만 4건이 스탑 이동폭 ₩124로
발화했다.

**3. 보내려던 것이 조용히 실패한다.** 이 레포는 Markdown 파싱 실패로 라이브 통지를 두 번
잃었고(`51227ca`의 `daily_cap` 밑줄), **세 번째가 지금 진행 중이다** — `_notify_decision`이
`NO_ACTION`의 밑줄 때문에 07-30 하루에 18건 이상 400으로 실패했다. `_send_message`가 그
400을 삼키고 `False`를 반환하는데 그 반환값을 아무도 보지 않는다.

**4. 물어볼 수 없다.** `/help`는 등록된 명령어 **이름만** 나열한다(`_handle_help` docstring:
"lists every currently-registered command name"). `/positions`는 종목·수량·평단·현재가·손익만
보여주고 손절가·익절가·**손절까지 여유**·총평가·관리 엔진이 없다. 워치리스트 조회 명령은
아예 없다. 그래서 운영자가 지난 2주간 직접 물어야 했던 것들이 전부 폰에서 답이 안 나온다:
"손절까지 여유 얼마나?", "워치 진입 상황", "EOD 결과", "OpenRouter 실제로 쓰이나".

이 넷이 합쳐진 결과가 07-30에 실증됐다. `AUTONOMY_ENABLED`가 재시작으로 꺼져
**롯데렌탈 자율 BUY가 4에이전트 만장일치 후 거부됐는데**, 아무 통지도 없었고 폰에서
확인할 명령어도 없어 로그를 파헤치기 전까지 아무도 몰랐다.

## 범위

**파트 A — 체결 통지(push)**: 자율·HITL·방어청산 체결과 집행 실패를 폰으로 보낸다.
**파트 B — 대화형 명령어(pull)**: 16개 명령어 세트와 출력 형식을 재정비한다.

두 파트는 코드 경로가 다르지만(`service.py` 발송부 / `commands.py` 수신부) 손익·손절여유·
금액 포맷을 공유하므로 하나의 스펙으로 묶고 공유 기반(B0)을 먼저 만든다.

---

# 파트 A — 체결 통지

## A1. 부착점: `_record_fill_ledger`

체결 통지를 `ExecutionCoordinator._record_fill_ledger()`에 붙인다. docstring이 명시하듯
이 함수는 **BUY·SELL 양쪽 체결 초크포인트가 공유하는 지점**이다("Shared ledger-write half
of both fill choke points (BUY in `_execute_order`, SELL in `_apply_sell_fill`)").

```
자율 BUY      → _execute_order ──────┐
자율 SELL     → _apply_sell_fill ────┼→ _record_fill_ledger → [통지]
PM 방어청산   → coordinator._close_position ─┘
HITL 승인     → (동일 경로)
```

PM의 자율 청산도 `trading_coord._close_position()`을 거치므로 이 한 곳이면 현재 경로가 다
덮이고, 새 경로가 생겨도 자동으로 커버된다.

**동기 함수 문제**: `_record_fill_ledger`는 `def`라 `await`가 안 된다. `asyncio.create_task`
+ 강참조로 던진다(레포 기존 패턴: `coordinator.py:1973`의
`loop.create_task(self._persist_state())`). 강참조를 보관하지 않으면 GC가 태스크를 수거해
통지가 조용히 사라진다.

**게이트 위치**: 현재 첫 줄이 `if not self._persistence_active: return`이다. 통지를 이 게이트
**앞**에 둔다 — 체결됐으면 원장 기록 여부와 무관하게 알려야 한다. 유닛 테스트에서 실제
발송이 나가지 않도록 통지 자체에 킬스위치를 둔다.

**부분 체결**: `_poll_tracked_fills`가 30초 폴링으로 델타마다 `_apply_sell_fill`을 부르므로
이론상 여러 번 통지된다. 자율 매매는 시장가를 쓰니 빈도는 낮고, `부분 (n/N주)`로 명시해
정직하게 보낸다. 별도 집계는 넣지 않는다(YAGNI).

## A2. 통지 내용

`send_trade_executed`가 이미 있고 `TELEGRAM_NOTIFY_TRADE_ALERTS` 게이트를 갖는다
(`services/telegram/config.py:39`). 다만 **손익을 받지 않는다** — 청산 통지에 그게 없으면
"437주 9,126원에 매도됨"만 알려주고 얼마 벌었는지는 모른다.

| 필드 | 진입(BUY) | 청산(SELL) |
|---|---|---|
| 종목·수량·체결가·총액 | ✓ | ✓ |
| 실현손익(원·%) | — | ✓ |
| 소스 (`자율`/`승인`/`방어청산`) | ✓ | ✓ |
| 부분 체결 표시 | ✓ | ✓ |

진입가는 포지션 감소 **전에** 읽어야 하므로 `_apply_sell_fill`이 그 값을 넘긴다.

## A3. 실패 통지 — 체결보다 급하다

손절 집행이 실패하면 포지션이 무방비로 남는다. 현재 넷 중 하나만 통지한다.

| 경로 | 현재 | 조치 |
|---|---|---|
| `_execute_close_position` 예외 | `auto_execute_failed` **로그만** | 🔴 통지 추가 |
| 유동성 캡 거부 (`ORDER_STATUS_REJECTED_LIQUIDITY_CAP`) | 없음 | 통지 추가 |
| 주문 API 실패 (`success=False`) | 없음 | 통지 추가 |
| autonomy 게이트 거부 | ✅ `_notify_close_gate_denied` | 그대로 |

실패 통지는 **무엇을 하라는 지시를 담는다** — "손절 집행 실패, 094840 무방비. 수동 확인
필요". 재시작 안전 아크에서 배운 것이다: 알림이 상태만 알려주고 조치를 안 알려주면
운영자가 잘못된 복구를 한다.

## A4. 지금 진행 중인 Markdown 실패 봉합

`_notify_decision`이 `NO_ACTION`의 밑줄로 07-30 하루 18건+ 400 실패 중이다. 발송부
(`service.py`의 `send_*` 16종) 전체에 세 겹을 적용한다.

1. 모든 자유텍스트·식별자에 `_md_escape`(`service.py:733`) 적용
2. Markdown 실패 시 `parse_mode` 없이 **1회 재발송**하는 폴백
3. 실패 시 `parse_mode`·본문 앞 120자·실패 종류를 로그에 남긴다 (**토큰은 절대 로그 금지**)

현재는 `can't find end of the entity` 로그 한 줄만 남고 무엇이 유실됐는지 알 수 없다.

## A5. 이벤트 스팸 억제

`_notify_event`가 `TELEGRAM_NOTIFY_*` 게이트를 거치지 않는 것을 고친다. `trailing_stop`
갱신처럼 스탑이 ₩124 움직인 것은 폰에 갈 일이 아니다. 게이트를 거치게 하고, 이벤트 종류별
발송 여부를 설정으로 통제한다. 사용자 결정(2026-07-30)에 따라 **체결·실패만** 보내므로
근접 경고·트레일링 갱신은 기본 off다.

## A6. HITL 중복 제거

`approval.py:715`의 기존 `send_trade_executed` 호출을 **제거**한다. 승인 경로도 같은
초크포인트를 지나므로 통지가 사라지지 않고 형식이 통일된다.

## A7. 실패 처리

- **킬스위치** `TELEGRAM_NOTIFY_FILL_ENABLED`(기본 `True`) — 기존
  `TELEGRAM_NOTIFY_TRADE_ALERTS`와 별도로 체결 통지만 끌 수 있게 한다.
- **never-raise**: 통지 실패가 체결 처리·원장 쓰기를 깨뜨려선 안 된다. `create_task`로
  던지는 코루틴 내부에서 전부 잡고 로그만 남긴다.

---

# 파트 B — 대화형 명령어

## B-형식. 출력 규칙 (전 명령어 공통)

**`parse_mode`를 지정하지 않는다 — 전 응답 평문.** 근거는 실측이다. 스캐너가 훑은 4,292개
고유 종목명 중 legacy Markdown 위험문자(`_ * ` [`)를 가진 이름은 **0개**인데, MarkdownV2로
바꾸면 `(`/`)` 311개(KODEX 골드선물(H), CJ4우(전환))와 `-` 70개(S-Oil)가, HTML로 바꾸면
`&` 든 143종목이 깨진다. 평문이 가장 안전하다.

평문이므로 기존 발송부 formatter의 `*` 마커를 재사용하지 않는다(현재 `/report`에 별표
12개가 그대로 노출된다). 강조는 서식이 아니라 **대괄호 섹션 라벨**(`[보유] 1종`), **줄 맨 앞
상태 이모지**, **2칸 들여쓰기**, **`──` 구분선**으로 한다.

**이모지 어휘 고정**: 🟢보유/신규매수 · 워치는 `·` · 🎯사거리 내 · ⚠️주의·불일치 ·
⛔차단·정지 · ✅정상. 한 줄에 최대 1개, 줄 맨 앞에만. 문장 중간 장식 금지.

**한 줄 표시폭 44 이하**(한글·이모지=2, ASCII=1). 넘으면 폰에서 접히고 접힘에 들여쓰기가
없어 다음 항목과 섞인다(현재 `/positions` 한 줄은 폭 80). 정보가 많으면 줄을 늘리지 말고
**헤더 1줄 + 2칸 들여쓴 상세 1~3줄 카드**로 쪼갠다.

**표·공백 정렬·고정폭 컬럼·코드블록 금지.** 폰 클라이언트는 비례폭이라 정렬이 무너지고
코드블록은 좌우 스크롤을 만든다. 정렬 대신 라벨(평단/손절/익절)로 필드를 식별시킨다.

**금액 3분류**:
- 주문 가능한 가격 레벨(진입가·손절가·익절가·평단·현재가) → 부호 없는 완전 천단위
  `13,060`. **축약 절대 금지.**
- 집계 금액(총평가·예수금) → 축약 허용 `4.97억`, `1,782만`
- 손익만 부호 표기 `+644,350`, `-3,432,361`. **비손익 값에 부호 금지**(현재 `_fmt_krw`가
  예수금에 `+`를 붙이는 동작을 재사용하지 말 것).

**백분율**: 손익률·갭·여유는 소수 1~2자리, 확신도·합의·승률은 정수 퍼센트(승률만 소수 1자리),
composite은 기존 `_fmt_composite` 재사용.

**시각**: 상대표기 우선, 절대시각은 괄호 보조(`1분 전`, `2시간 23분 전`). 마이크로초 ISO
원본을 그대로 찍지 않는다. `market-hours`의 `next_close`는 타임존이 `+08:28`로 깨져 있으므로
서버 `message`나 `countdown_seconds`만 가공해 쓴다.

**종목 표기**: `종목명 티커`(괄호 없음). 폴백은 `name → stock_name → 종목 094840`.
현재 EOD 렌더에 `094840(094840)` 중복이 실재한다.

**시스템 식별자는 한글 매핑**(이스케이프 아님): `below_threshold`→문턱 미달,
`market_cap_low`→시총 미달, `liquidity_low`→유동성 부족, `price_too_low`→주가 과소,
`insufficient_history`→이력 부족, `zero_volume_day`→거래 없음,
`liquidity_inconsistent`→유동성 모순, `llm_not_suitable`→LLM 반려, `daily_cap`→일일한도,
`not_reviewed`→미검토.

**LLM 자유텍스트는 `*`/`_`/백틱을 strip**한다. 평문 경로라도 원문의 짝 안 맞는 `**`가
노출된다(워치 402340 `key_factors`에 `차 지지선**: 1,194,000원`이 실재). 절단은 문장
경계에서 하고 `…(전문은 웹)`을 붙인다 — 현재 300자 하드컷이 `...breadth br`처럼 단어
중간을 자른다.

**4096자 대응은 절단 + 항목 상한**, 분할은 하지 않는다. 폰에서 3연속 메시지는 읽히지 않고
연속 발송은 초당 1건 권고를 넘겨 429를 유발하며 그 429는 `_send_message`가 조용히 삼킨다.
상한: 워치 12종 · 발굴 승격 8종 · 결정 8건 · 이벤트 8건 · 일별 손익 7행 · 보유는 전량(한도 5종).
그럼에도 `_reply`(`commands.py:110`)에 **3,900자 하드 절단**(문장 경계 + `…이하 생략`)을
넣는다. 방어 없이 4,096자를 넘기면 데이터가 통째로 사라지고 `오류: Message is too long`
한 줄만 온다. **절단 방식이면 기존 `assert_awaited_once` 테스트 계약이 유지된다**(분할은
20곳 가까운 테스트를 깬다).

**빈 상태 / 실패 / 미설정 3분류 강제.** `데이터 없음` 단일 문자열 금지 — 현재
`_format_positions(None)`(API 예외)과 `holding=null`(정상 빈값)이 **바이트 동일**하다.
`0건` / `조회 실패(타임아웃)` / `미설정`으로 구분하고, `/operations`가 이미 실어 보내는
`errors` dict를 읽는다(현재 어떤 명령어도 읽지 않는다).

**이중엔진 값이 어긋나면 양쪽 병기 + '실제 발동' 라벨.** 실효 손절 =
`max(포지션매니저, 코디네이터 원장)`, 여유는 실효값 기준. 라이브에서 13,224 vs 12,492로
5.9% 벌어져 여유가 2.41% vs 8.42%로 갈린다 — 라벨 없는 단일 숫자는 거짓 안심이다.

**한 명령 안에서는 한 소스의 금액만 쓴다.** 같은 포지션의 손익이 소스마다 3개
(operations 596,370 / PM 644,350 / portfolio 644,422), 평가액도 2개다.
`/positions`·`/status`는 PM+operations, `/pnl`은 Kiwoom performance로 고정한다.

**폰 응답 목표 2초.** 수신 Application이 `max_concurrent_updates=1`로 순차 처리하므로 느린
조회가 승인 버튼 탭과 `/halt`를 굶긴다. 소스는 `asyncio.gather`로 병렬화하고 소스별
타임아웃을 건다(특히 `/pnl`은 Kiwoom REST 2회).

## B-help. `/help` 재설계

**단일 출처 — `register_command` 확장.** 현재 `register_command(name, handler)`
(`receiver.py:96`)에는 설명을 담을 자리가 없다. 별도 설명 dict를 두면 "등록됐지만 /help에
없는 명령"이 반드시 생긴다. 시그니처를 확장한다:

```python
register_command(
    "positions", handle_positions,
    summary="보유 종목·실효 손절 여유",   # 32자 이내. setMyCommands description 겸용
    group="지금 상태",                     # /help 섹션
    risk="read",                           # read | mutate
    usage="/positions",
    detail="…",                            # /help positions 본문
    caution="손절이 엔진마다 다르면 둘 다 표시",
)
```

키워드 인자는 전부 optional 기본값을 주어 기존 6개 호출부가 깨지지 않게 하되, 신규 명령은
`summary`/`group`/`risk`를 필수로 취급한다(누락 시 기동 로그 warning — 예외를 던지지
않는다, receiver의 never-raise 계약).

**2단 구조**: `/help`는 `group`으로 묶어 1행 요약만, 그룹 순서 고정(지금 상태 → 종목 판단 →
성과 → 승인 대기 → ⚠️ 상태를 바꿈). `risk="mutate"`는 항상 맨 아래 별도 섹션 — 현행
`sorted()` 나열이라 `/auto`(자율 재개)가 첫 줄에 조회 명령과 나란히 뜨는 문제가 해소된다.
`/help <명령>`은 detail 본문(목적·읽는 데이터·보여줄 것·인자·위험도·언제·주의)을 주고,
미등록 이름이면 유사 후보 3개를 제시한다.

**`setMyCommands`를 쓴다.** 코드베이스 전체에 `set_my_commands`/`BotCommand`가 **0건**이라
폰에서 `/`를 쳤을 때 자동완성이 비어 있고 `/help`가 그 역할을 100% 혼자 진다. 등록하면
"이름 + 한줄설명"은 봇 API가 UI로 렌더하므로 `/help`는 그룹 맥락과 상세에 집중할 수 있다.
`await application.initialize()` 직후 `BotCommandScopeChat`으로 호출하고 실패는 로그만 남긴다.

## B-set. 명령어 세트 (16개)

`must` 10 / `should` 5 / `nice` 1.

| 명령어 | 등급 | 한 줄 설명 |
|---|---|---|
| `/help`, `/help <명령>` | must | 명령어 목록과 사용법 (2단) |
| `/status` | must | 자율 실행 가능 여부와 계좌·한도 여유 |
| `/positions` | must | 보유 종목과 실효 손절·익절까지 남은 여유 |
| `/watch`, `/watch <티커>` | must | 워치 진입가 갭과 문턱까지 남은 거리 |
| `/discovery` | must | 최근 EOD 발굴 퍼널과 승격 병목 |
| `/pnl [일수]` | must | 실현손익·승률·일별 추이 |
| `/health` | must | 조용히 꺼진 플래그·LLM 백엔드·감시 루프 |
| `/halt` | must | ⚠️ 자율 정지 (**자동 손절도 수동 전환**) |
| `/why <티커>` | should | 손절·익절이 왜 그 값인지 — 변경 이력과 결정 |
| `/decisions` | should | 최근 결정 8건과 실제 집행 결과 |
| `/pending` | should | 승인 대기 제안 + 버튼 (판단 근거 포함) |
| `/report [날짜]` | should | 장마감 요약 |
| `/auto` | should | ⚠️ 자율 재개 (버튼 확인 5분, 1회용) |
| `/risk` | nice | 리스크 한도와 현재 위치 |

**핵심 두 개의 출력 예시** (실제 라이브 값):

```
[상태] 07-30 13:10 · KRX 개장
자율 실행: 차단
  마스터 게이트 OFF (AUTONOMY_ENABLED)
  → 자동 손절도 집행 불가 (수동 승인)
모드: 키움 자율 / 코인 수동
계좌: 4.97억 · 현금 96.5%
포지션: 1/5종 · 평가 1,782만 (3.6%)
  094840 슈프리마에이치큐
  실효 손절 13,224 (여유 2.41%)
일일 거래: 0/10 · 당일 실현 0원
워치: 8종 · 사거리 3% 내 0종
  최근접 롯데렌탈 갭 -6.1%
가동: 10:47 기동 (2시간 23분 전, 복원됨)
```

```
[보유] 1종 · 평가 1,782만 (계좌 3.6%)
총 미실현 +644,350 (+3.75%)

🟢 슈프리마에이치큐 094840
  1,315주 · 평단 13,060 · 현재 13,550
  손익 +644,350 (+3.75%)
  실효 손절 13,224 (여유 2.41%)
  ⚠️ 엔진 불일치
     감시 13,224 / 원장 12,492
     실제 발동은 높은 쪽 13,224
  익절 14,384 (여유 6.15%)
  트레일링 5% · 최고 13,920 · 보유 0일
  오늘 토론 4회 · 12:51 HOLD

오늘 체결 0건 · 미체결 주문 0건
```

`/discovery`는 **병목을 한 줄로 단정**하는 것이 존재 이유다 — `병목: 점수 문턱 (LLM 아님)`.
퍼널을 후보 → 게이트 통과 → 문턱 미달 → LLM 도달/반려 → 승격으로 보여주고, 게이트 탈락
사유를 한글 라벨로 분포시킨다. 원시 `discovery/candidates`(2,648행·62KB)는 쓰지 않고
`eod-report`의 `digest.discovery` 집계만 읽는다.

`/health`는 **조용히 꺼진 것들**을 보여준다. 07-30에 `master_enabled=false` ·
`DISCOVERY_ENABLED=false` · `codex_cli healthy=false` 3중 무성 실패가 실재했다. 각 OFF
항목에 복구 방법 1행(`.env` 키 + 재시작 필요)을 붙인다.

## B-safety. 안전

**발신자 검증은 이미 있고 fail-closed다.** `receiver.py:117 _authorized`가 모든 핸들러 앞에서
`effective_chat.id == TELEGRAM_CHAT_ID`를 검사하고, CHAT_ID 미설정 시 무조건 거부, 불일치 시
답장 없이 `telegram_unauthorized_chat`만 로깅한다(정보 누출 없음). 신규 핸들러에서 이 검문을
재구현하지 않는다.

**잔여 갭 — per-user 검증 부재**: 기준이 `effective_chat.id`뿐이라 `TELEGRAM_CHAT_ID`를
그룹(음수)으로 바꾸는 순간 그룹원 전원이 `/halt`를 칠 수 있다. `risk="mutate"` 명령에
`effective_user.id` 화이트리스트 검증(`TELEGRAM_ADMIN_USER_ID`, 미설정 시 현행 동작 유지)과
감사 로그·10초 쿨다운을 추가한다.

🔴 **`/halt`의 최대 위험을 문구로 해소한다.** `/halt`는 "신규 매수 차단"이 아니라 **자동 손절
무장해제**다. 게이트 2단계가 `mode != autonomous`면 거부하는데(`gate.py:279`) PM의
전량청산·부분축소가 바로 그 게이트를 통과해야 주문을 낸다(`position_manager.py:1255, 1630`).
HITL 폴백(`:1352`)이 완전 무방비는 막지만 사람이 승인해야 한다. 명령어 설명과 실행 응답
양쪽에 이 사실을 명시한다.

**신설 명령은 전부 읽기 전용(GET).** POST/PUT을 늘리지 않는다. 상태 변경은 기존
`/halt`(무확인, fail-safe 방향)·`/auto`(단발 nonce + TTL 300초 + 1회용 + `/halt` 시 무효화)로만
한정하고 `/help`에서 mutate 섹션을 시각적으로 분리한다.

**조회 명령에 쓰기 인라인 버튼을 붙이지 않는다.** 조회는 반복 호출되므로 채팅 히스토리에
서로 다른 시점 가격을 전제한 버튼이 무한 누적된다(하루 10번 `/positions` → 버튼 10개).
이 레포는 이미 그 사고를 겪었다 — 고정 `callback_data` 확인 버튼의 늦은 탭이 `/halt`
긴급정지를 되돌려서 nonce+TTL이 도입됐다(`commands.py:73-76`).

**`callback_data` 접두사는 3자 이상 + `:`로 끝나게 한다.** `_dispatch_callback`
(`receiver.py:199`)이 최장 접두 일치로 고르므로 `a`/`r`로 시작하는 짧은 문자열은 승인·거부
버튼을 가로챈다. `callback_data`는 64바이트 이내.

**항목별 연속 발송에 0.4초 지연.** `/pending`은 현재 지연 없이 항목마다 별도 메시지를
보내는데(`commands.py:300`) Telegram은 동일 채팅 초당 1건을 권고하고 초과 시 429를 내며
그 429는 `_send_message`가 조용히 삼킨다 — 뒷항목이 통째로 유실된다.

**비밀 값 금지.** `/health`는 boolean과 마스킹만 담는다. 토큰·API 키·계좌번호·chat_id 원본은
어떤 응답에도 넣지 않는다. 소스로 `/api/settings`·`/debug/config`를 쓰지 않는다.

---

# 공유 기반과 구현 순서

이 스펙은 하나지만 **구현 계획은 층 단위로 나눈다** — 아래 9개 층을 한 계획에 담으면
리뷰 단위가 너무 커진다. `B0 → B1 → B2 → A` 를 첫 계획으로, `B3~B7`을 두 번째 계획으로
쪼갠다. 첫 계획만으로도 배포 가치가 있다: 진행 중인 Markdown 실패가 멎고, 체결 통지가
살아나고, `/help`가 쓸모 있어진다.

**B0 (선행, 파트 A와 공유)** — `services/telegram/formatting.py` 신설.
`fmt_price`(부호 없는 천단위, 축약 금지) / `fmt_money_short`(4.97억·1,782만) /
`fmt_pnl`(부호 강제) / `fmt_pct` / `fmt_rel_time` / `effective_stop`(양 엔진 max + 불일치 플래그) /
`stock_label`(종목명 티커, 폴백) / `strip_markers`(LLM 텍스트) / `display_width`(한글 2폭) /
`ko_label`(시스템 식별자 한글 매핑). 파트 A의 체결 통지와 파트 B의 `/positions`가 같은
함수를 쓴다.

**B1 (안전 기반)** — 수신부 하드닝. `_reply` 3,900자 절단 · `_safe` 결과 3분류 표기 +
`errors` dict 소비 · mutate 등급에 `effective_user.id` 검증 + 감사 로그 + 10초 쿨다운 ·
항목별 발송 0.4초 지연. **이 층이 없으면 뒤의 모든 명령이 같은 결함을 반복한다.**

**B2 (레지스트리 + `/help`)** — `register_command` 시그니처 확장(기존 6개 호출부 메타 백필) →
`/help` 2단 재작성 → `setMyCommands` 호출. **명령어를 추가하기 전에** 끝내야 이후 신설분이
자동으로 도움말·자동완성에 실린다. 순서를 뒤집으면 백필을 두 번 한다.

**A (통지)** — B0 완료 후 파트 A 전체. 진행 중인 Markdown 실패(A4)가 포함되므로 우선순위가
높다.

**B3** — `/positions` 강화 + `/watch` 신설. 둘 다 **새 데이터 소스가 0개**다 —
`stop_loss`/`take_profit`은 이미 operations 응답에 실려 오는데 포매터가 버리고 있고
(`trading.py:1830` vs `commands.py:212`), 워치 8종도 필드가 완비돼 있다.

**B4** — `/health` 신설 + `/status` 개선. "이미 나 있는 불"을 보이게 한다.

**B5** — `/pnl` + `/discovery`. `/pnl`은 Kiwoom REST 2회라 B1의 3분류 강등·타임아웃이
먼저 있어야 한다.

**B6** — `/why` + `/decisions`. B5까지 오면 "무엇이 일어났나"는 보이는데 "왜"가 없다.
`/decisions`는 결정↔집행 갭(09:28 롯데렌탈 만장일치 BUY → 미집행)을 드러낸다.

**B7 (다듬기)** — `/pending` 근거 보강 + `/report` 6결함 수정 + `/halt` 고지·에코·멱등 +
`/auto` 문구 + `/risk`. `/risk`는 nice — 시간이 없으면 잘라도 `/status`가 대체한다.

# 테스트

**단위 테스트로는 이 결함군을 못 잡는다는 것이 이미 증명됐다** — `51227ca` 커밋 메시지가
"`_send_message` 모킹이라 미검출"이라고 기록한다. 그래서 각 층 공통 게이트를 둔다:

1. **라이브 캡처 데이터로 렌더**한 문자열에 `*`/`_`/백틱/`[` 잔존 **0** · 길이 **≤3,900** ·
   최대 표시폭 **≤44**를 단정하는 테스트
2. **장 마감 후 실물 1회 발송** 확인

파트 A 추가: BUY/SELL 체결 각 1회 통지 · SELL에 실현손익 포함 · `_persistence_active=False`
여도 통지 발송 · 부분 체결 표시 · 킬스위치 off → 미발송 · 통지가 raise해도 원장 쓰기 정상 ·
HITL 경로 체결이 **1회만** 통지 · 실패 4경로 각각 통지 + 조치 문구.

# 배포 창 제약

라이브 프로세스가 모의투자 포지션(094840 1,315주)을 감시 중이다. 수신부 변경은 장 마감 후
배포하고 **15:30~16:35 EOD 발굴 창은 피한다**. 조사·검증은 GET만 쓰고
`backend/data/storage.db`에 쓰지 않는다.

# 제외 범위

검토했으나 넣지 않은 것과 이유:

- **`/brief`**(개장 종합 브리핑) → 내용이 `/status`+`/positions`+`/watch` 헤더의 합집합.
  같은 숫자를 두 곳에서 렌더해 어긋날 표면이 늘고 `max_concurrent_updates=1`에서 느려진다.
- **`/events`** → `/why`에 흡수. "이벤트 발생을 아는 것"은 pull이 아니라 push의 일이다(파트 A).
- **`/llm`, `/account`, `/orders`, `/alerts`, `/agents`** → 각각 `/health`, `/status`+`/pnl`,
  `/positions` 푸터, `/status`, `/decisions`에 흡수. 독립 명령을 소비할 정보량이 아니다.
- **`/scan`** → 장중 대부분 idle이고 세션 액션 카운트가 유령 숫자다(session 20260729153028이
  `buy_count 212`를 보고하나 같은 session_id 조회 결과와 불일치).
- **`/candidates`, `/session <id>`, 토론·rationale 전문** → 각각 62KB, 23.9KB, 2,000자+.
  한 메시지를 다 먹고도 넘친다.
- **`/stop`, `/sell`, `/buy`, `/close`, `/setstop`, `/strategy set`** → 위험이 비대칭이고
  되돌릴 수 없다. 폰 오타 한 번이 1,315주 시장가 청산이 된다.
- **POST 유발 명령(`/discovery run`, `/scan start`)** → 발굴 스캔은 4,276종목 × 2콜 ×
  0.7s로 이론 100분+이고, 장중에 돌리면 감시 루프의 Kiwoom 유량을 굶겨 손절 감시를
  위험하게 한다.
- **`/chart`, `/candles`, `/orderbook`, `/tickers`** → 폰 텍스트로 무의미. FE 전용 GET군.
- **코인 전용 명령** → 표시할 것이 없다(`coin/positions` 빈 배열, 모드 hitl). KR과 공용으로
  처리하고 0건일 때 `0건`을 명시한다.
- **`/settings`, `/config`** → 마스킹돼 있어도 폰 노출 가치가 0. 운영 플래그는 `/health`가
  boolean으로만 보여준다.
- **MarkdownV2 / HTML `parse_mode`** → 위 B-형식의 실측 근거대로 평문보다 위험하다.
- **`_reply` 멀티 메시지 분할** → 절단을 택했다. 429 유실과 기존 테스트 20곳 파괴를 피한다.
- **조회 결과의 인라인 새로고침·드릴다운 버튼** → 안전하게 만들려면 nonce + TTL +
  발행시점 상태 핀 + 동기 키보드 제거 + detached task를 전부 복제해야 한다. 재조회는
  명령어를 다시 치면 되고 그쪽이 stale 표면이 0이다.
- **`/mute <종류> [분]`**(저가치 알림 억제) → 문제는 실재하나(07-30 2시간에 13건, trailing 7건)
  해법은 명령어가 아니라 `_notify_event`를 게이트 아래로 넣는 것이다(A5).
