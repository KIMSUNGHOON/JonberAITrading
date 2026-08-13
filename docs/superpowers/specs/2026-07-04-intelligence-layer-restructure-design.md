# 설계: 멀티 백엔드 지능 레이어 재편성 (Phase 1)

- **날짜**: 2026-07-04
- **상태**: 설계 승인 대기 (브레인스토밍 산출물)
- **범위**: Phase 1 — LLM 지능 레이어 재편 + 태스크 라우터 + 신뢰성 + 방지 전용 시크릿
- **근거 자료**: 3-에이전트 설계 패널 + 심사·합성 워크플로우(`design-intelligence-layer`, 2026-07-04), 실제 코드·CLI 검증

---

## 1. 배경과 목표

현재 `backend/agents/llm_provider.py`는 **로컬 GPU 모델 전용**(vLLM/Ollama, OpenAI 호환) 파사드다. `langchain_openai.ChatOpenAI`를 얇게 감싼 싱글턴이며, 거의 모든 LLM 호출이 단일 메서드 `await get_llm_provider().generate(messages, ...)`를 통과한다(검증된 초크포인트).

6개월 유휴 후 사용자는 다음 리소스를 확보했다:

| 백엔드 | 인증/과금 | 성격 |
|--------|-----------|------|
| **OpenRouter → `deepseek-v4-flash`** | API 키, per-token | HTTP, 스트리밍, 고빈도·저비용 |
| **Claude Code CLI** (`claude -p`) v2.1.201 | Max x20 구독, **키리스 OAuth** | subprocess, 최강 추론, 정액 |
| **Codex CLI** (`codex exec`) v0.142.4 | ChatGPT Plus 구독, **키리스 OAuth** | subprocess, 코딩·구조화, 정액 |

**목표**: 로컬 GPU 중심 → 이 3종 백엔드를 **태스크별 스마트 라우팅**으로 활용하는 지능 레이어로 재편. 기존 호출부를 깨지 않고, 시크릿을 upstream에 노출하지 않으며, 단일 개발자 규모에 맞게.

---

## 2. 확정 결정 (재론 금지)

1. **범위 = Phase 1만**: 멀티 백엔드 지능 레이어 + 태스크 라우터 + 동시성 제어 + 방지 전용 시크릿. **비범위**: 규칙기반 매매 시그널의 실제 LLM 의사결정화, 3중 마켓 스택 통합, 데드코드 삭제.
2. **라우팅 = 태스크별 스마트 라우팅**: 태스크 목적으로 백엔드 선택 + 백엔드별 폴백 체인.
3. **시크릿 = 방지 전용**: 유일 시크릿 = OpenRouter 키 → gitignore된 `.env`로만 주입, 절대 미커밋. CLI는 키리스. **로테이션/히스토리 재작성 없음**(사용자 확인: 현재 누출 키 없음).
4. **호출부 무파손**: `await get_llm_provider().generate(messages)`는 그대로 동작. `task=` 힌트는 키워드 전용 추가.
5. **subprocess 안전**: 프롬프트에 임의 시장/뉴스 텍스트 포함 → argv 배열/stdin 전달, `shell=True` 절대 금지.
6. **단일 개발자 규모**: 엔터프라이즈 과설계 금지(k8s/외부 볼트/메시지 브로커 없음).

### 2.1 라우팅 실무 결정 (2026-07-04 확정)

| 항목 | 결정 | 함의 |
|------|------|------|
| **기본/폴백 티어** | **클라우드 우선 — Ollama 은퇴** | `local` 백엔드 클래스는 유지하되 기본 체인서 제외(Windows용 env-gate 옵션). 기본/최종 폴백 = OpenRouter |
| **Claude 모델** | strategic_decision·risk = **opus**; 기타 폴백용 Claude = **sonnet** | 최고 스테이크에 최강 추론(정액이라 비용 무관, Max 레이트리밋만 고려) |
| **분석 태스크 롤아웃** | **보수적 — 파서 검증 게이트** | Ollama 은퇴로 `local` 부재 → 파서 검증이 Phase 1 필수 단계가 됨(§10) |
| **예산 가드** | `OPENROUTER_DAILY_BUDGET_USD` **on** (기본 제안 $5, env 조정) | 초과시 OpenRouter 당일 제외 → 스캐너는 rule-based 폴백, 고스테이크는 Claude(정액) |
| **스트리밍** | **HTTP 전용** | CLI는 스트림 체인서 자동 제외(stream-json 파싱 취약·저가치) |
| **Codex 모델** | 계정 기본값(`-m` 미지정, env 조정 가능) | 저볼륨 구조화 태스크에만 사용 |

---

## 3. 아키텍처

`agents/llm_provider.py`는 **공개 표면을 그대로 유지**(모든 이름·시그니처 동결)하고 내부만 라우터로 위임한다. 새 패키지 `agents/llm/`(9개 파일):

```
backend/agents/
  llm_provider.py          # 공개 파사드 (유지) — 내부만 router 위임
  llm/
    __init__.py
    tasks.py               # TaskType/BackendName enum, ROUTING_POLICY, DECISION_SCHEMA
    messages.py            # flatten_messages(): LangChain↔CLI 유일 이음새
    subprocess_runner.py   # run_cli(): 유일한 subprocess 초크포인트
    router.py              # Router: 세마포어·서킷브레이커·타임아웃·헬스·폴백·structlog·예산가드
    backends/
      __init__.py
      base.py              # LLMBackend ABC + 예외 계층
      openai_compat.py     # OpenAICompatBackend → openrouter (+ 옵션 local)
      claude_cli.py        # ClaudeCLIBackend
      codex_cli.py         # CodexCLIBackend
```

**의존 방향**: `llm_provider.py → agents/llm/*`, 그리고 `agents/llm/*`는 `app.config`만 의존. **어떤 호출부도 새 import 불필요.**

### 3.1 각 유닛 책임

- **`tasks.py`**: `TaskType(str, Enum)`(strategic_decision, risk, task_decomposition, technical_analysis, fundamental_analysis, sentiment_analysis, group_chat, scanner, translation, chat, utility, general), `BackendName(str, Enum)`(OPENROUTER, CLAUDE_CLI, CODEX_CLI, LOCAL), `ROUTING_POLICY: dict[TaskType, list[BackendName]]`, `DECISION_SCHEMA`(구조화 매매결정 JSON Schema).
- **`messages.py`**: `flatten_messages(messages) -> tuple[str, str]` → `(system_str, user_str)`. `SystemMessage` 연결 + Human/AI 히스토리를 트랜스크립트로 렌더. **LangChain과 CLI 백엔드 사이 유일한 이음새**(HTTP 백엔드는 미사용, `list[BaseMessage]` 네이티브 소비).
- **`subprocess_runner.py`**: `async def run_cli(argv, *, stdin=None, timeout, cwd) -> tuple[int, str, str]`. 유일한 `asyncio.create_subprocess_exec` 지점(argv 배열, `shell=True` 절대 금지). `communicate(input=...)`, `asyncio.wait_for` + 타임아웃시 `proc.kill()`/`await proc.wait()`, `finally`에서 임시파일 정리.
- **`backends/base.py`**: `class LLMBackend(ABC)` — 속성 `name`, `supports_stream`, `supports_schema`; 메서드 `async generate(req)`, `async stream(req)`, `async health()`. 예외: `BackendError → BackendTransientError | BackendTimeoutError | BackendAuthError`; 최상위 `LLMAllBackendsFailed`.
- **`backends/openai_compat.py`**: 현 `ChatOpenAI` 코드 이식. openrouter 인스턴스(기본) + local 인스턴스(env-gate 옵션). 네이티브 스트리밍 + `response_format`. httpx connect/429/5xx에만 좁은 `tenacity(stop_after_attempt(2))`.
- **`backends/claude_cli.py`**: `ClaudeCLIBackend`. `supports_stream=False`, `supports_schema=True`(`--json-schema`). §7.
- **`backends/codex_cli.py`**: `CodexCLIBackend`. `supports_stream=False`, `supports_schema=True`(`--output-schema`). §7.
- **`router.py`**: `class Router` — 레지스트리 `{BackendName: LLMBackend}`, 백엔드별 `asyncio.Semaphore`, 백엔드별 `CircuitBreaker`, 타임아웃, 헬스 캐시, 예산 가드, structlog. 메서드 `resolve(task, streaming) -> list[LLMBackend]`, `generate(req)`, `stream(req)`, `startup()`, `aclose()`, `snapshot()`. 모듈 싱글턴 `get_router()`.

---

## 4. 인터페이스 진화 (하위호환)

```python
async def generate(self, messages, temperature=None, max_tokens=None, *,
                   task: str | TaskType | None = None,     # NEW; None → GENERAL
                   response_schema: dict | None = None) -> str: ...

def stream(self, messages, temperature=None, max_tokens=None, *,
           task: str | TaskType | None = None) -> AsyncIterator[str]: ...

async def generate_structured(self, messages, schema: dict, *,
                              task="strategic_decision") -> dict: ...   # 파싱+검증된 dict
```

- 위치 인자 **바이트 동일**. `task`/`response_schema`는 **키워드 전용** → 기존 25개 호출부 전부 그대로 컴파일·동작(`task=None → GENERAL`).
- 문자열 task는 `TaskType(task)`로 강제 변환; 미지 문자열은 `GENERAL`로 폴백(1회 로깅, 예외 없음).
- `generate()`는 **여전히 `str` 반환**(원문 텍스트 또는 원문 JSON) → 규칙기반 파서(`_extract_bull_case`/정규식 추출기) 무파손. `generate_structured()`는 다음 페이즈용 opt-in.
- `stream()`은 체인을 `supports_stream=True` 백엔드로 자동 필터 → CLI 백엔드가 스트리밍 챗을 막지 않음.
- **블랭킷 `@retry(stop_after_attempt(3))` 제거**(백엔드별 이중 재시도 유발). 좁은 재시도는 HTTP 백엔드 내부로만 이동.
- (참고: 기존 `reset_llm_provider()`의 `asyncio.create_task(...)`는 실행 루프 미보장 잠재버그 — 범위상 그대로 두되 라우터에 패턴 복사 금지.)

### 4.1 DECISION_SCHEMA (구조화 매매결정)

```
action ∈ [BUY, SELL, HOLD, ADD, REDUCE, WATCH, AVOID]
confidence: number
summary: string
bull_case: string[]
bear_case: string[]
rationale: string
required: [action, confidence, rationale]
```

OpenRouter → `response_format={type: json_schema, ...}`; Claude → `--json-schema`; Codex → `--output-schema`. 라우터가 파싱된 객체를 검증하고, **검증/파싱 실패 = 백엔드 실패**로 취급(다음 백엔드로 폴백). HTTP는 백엔드 내 1회 재요청 옵션.

---

## 5. 라우팅 정책 (클라우드 우선 반영, 확정)

`tasks.py`의 순수 `dict[TaskType, list[BackendName]]`(코드, 설정파일 아님). `LLM_DEFAULT_CHAIN` env 한 줄로만 오버라이드.

| TaskType | Primary | Fallback 체인 | 근거 |
|----------|---------|--------------|------|
| **strategic_decision** | claude_cli **(opus)** | → openrouter | 최고 스테이크, 최강 모델, 정액, `--json-schema` |
| **risk** | claude_cli **(opus)** | → openrouter | 고스테이크 저볼륨 |
| task_decomposition | codex_cli | → openrouter → claude_cli(sonnet) | 구조화 JSON, 저볼륨 |
| utility (write_todos) | codex_cli | → openrouter | 코딩/구조화 |
| technical_analysis | openrouter | → claude_cli(sonnet) | 중볼륨, 저비용 우선 · **파서 검증 게이트(§10)** |
| fundamental_analysis | openrouter | → claude_cli(sonnet) | 동상 |
| sentiment_analysis | openrouter | → claude_cli(sonnet) | 뉴스 스파이크 |
| group_chat | openrouter | → claude_cli(sonnet) | 다수 토론턴, 병렬 |
| **scanner** | openrouter | (없음 → rule-based 폴백) | **고볼륨, CLI 절대 금지**(~5s/호출), 예산가드 대상 |
| translation | openrouter | → claude_cli(sonnet) | 저비용 유틸 |
| chat (스트리밍) | openrouter | (스트림 가능 폴백 없음) | HTTP 전용 스트리밍 |
| **GENERAL (태그 없음)** | openrouter | → claude_cli(sonnet) | Ollama 은퇴로 기본=OpenRouter · **파서 검증 게이트(§10)** |

`resolve()`는 다음 백엔드를 체인서 드롭한다: (a) 미생성(OpenRouter 키 없음), (b) 서킷 오픈, (c) 언헬시, (d) 스트리밍 호출인데 비스트림, (e) 당일 예산 초과(openrouter). 체인이 비면 `LLMAllBackendsFailed`(기존 `try/except` 폴백이 받음).

---

## 6. 신뢰성

- **백엔드별 세마포어**(전역 게이트, 스캐너 자체 외부 세마포어와 조합): `openrouter=8`(HTTP), `claude_cli=2`, `codex_cli=2`(subprocess+구독 한도), `local=3`.
- **타임아웃**: HTTP 120–300s(현행 재사용), CLI **180s**(~5s 콜드스타트 + 긴 시장 컨텍스트 여유).
- **폴백 루프**: 체인 순회, 예외시 실패 기록 + `llm_fallback{from,to,reason}` 로깅 후 다음 백엔드.
- **재시도**: HTTP 백엔드 내부 좁은 `tenacity(2)`(httpx/429/5xx만). CLI는 인플레이스 재시도 없음(바로 다음 백엔드).
- **서킷브레이커**(프로세스 내 인메모리, 백엔드별): 3연속 실패→60s open(rate-limit 분류시 120s), half-open 1프로브, `record_success`시 리셋. `BackendAuthError`→해당 백엔드 프로세스 동안 unavailable(로그아웃 CLI가 매 요청 타임아웃 물리지 않게).
- **예산 가드**: `OPENROUTER_DAILY_BUDGET_USD`(on, 기본 $5). 추정 지출 초과시 openrouter를 당일 unavailable로 → 스캐너 degrade, 고스테이크는 Claude(정액).
- **관측성**: 기존 structlog — `llm_request/attempt/success/fallback/backend_failed/circuit_open`. `snapshot()`을 `GET /api/llm/stats`로, 확장 `health_check()`.

---

## 7. CLI 계약 (설치 버전 검증됨)

둘 다 **버려지는 tempdir을 `cwd`로**(프로젝트 `CLAUDE.md`/`.mcp.json`/git 누출 차단). 신뢰된 시스템 프롬프트만 argv, **임의 시장/뉴스 텍스트는 stdin 또는 단일 argv 요소로만 — 셸 보간 절대 금지.**

### Claude (`ClaudeCLIBackend`) — 스모크 테스트 통과(`.result=="OK"`, `subtype=="success"`, ~5s)
```
claude -p --output-format json --tools "" --strict-mcp-config \
  --system-prompt "<system_str>" --model <opus|sonnet> \
  [--json-schema '<schema>'] "<user_str>"
```
- `--tools ""` = 전 툴 비활성(권한 프롬프트 없음, `permission_denials:[]`) → `--permission-mode`/`--dangerously-skip-permissions` 불필요. `--strict-mcp-config`로 MCP 서버 무시.
- **`--bare` 절대 미사용**(키리스 Max OAuth를 깨고 `ANTHROPIC_API_KEY`를 요구함).
- 파싱: `json.loads(stdout)`, 성공 = `subtype=="success"` and not `is_error`, 텍스트 = `["result"]`. `total_cost_usd`/`usage`는 **notional**(정액)로만 로깅. 비정상 종료/파싱불가/`is_error` → `BackendError`; stderr `rate limit|overloaded|429` → `BackendTransientError`(긴 CB 쿨다운).

### Codex (`CodexCLIBackend`)
```
codex exec -s read-only --skip-git-repo-check -C <tempdir> --color never \
  -o <tmp_out> [--output-schema <tmp_schema>] [-m <model>] -
# stdin = "<system_str>\n\n---\nRESPOND WITH TEXT ONLY, DO NOT USE TOOLS.\n\n<user_str>"
```
- `exec`에 시스템 프롬프트 플래그 없음 → system은 stdin 프리앰블로(여전히 stdin, 셸 아님). 최종 메시지는 `-o` 파일에서 읽음(`--json` JSONL 스크래핑보다 견고). 구조화 = `--output-schema` + `json.loads` + 검증. `read-only` 샌드박스 = 쓰기 불가. `-o`/스키마 임시파일 `finally` 정리.

---

## 8. 시크릿 (방지 전용)

유일 시크릿 = OpenRouter 키. `Settings`에 `OPENROUTER_API_KEY: SecretStr | None = None`, `OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"`, `OPENROUTER_MODEL="deepseek-v4-flash"`. `../.env`에서 로드(pydantic-settings 기존 동작; **`.gitignore`가 이미 `.env`/`*.env` 제외 — 검증됨**). `SecretStr`로 repr/트레이스백 차단, `get_secret_value()`는 OpenRouter 백엔드 생성 시점에만, 로그 필드/argv에 절대 미포함(키리스 CLI만 subprocess 사용). 키가 비면 openrouter 백엔드 **미생성** → 체인서 자동 제외(크래시 없음). `.env.example`(+ 루트)에 문서화된 빈 `OPENROUTER_API_KEY=` 줄 추가(CLI는 키 불필요 명시). **로테이션/히스토리 재작성 없음.** CLI는 머신 OAuth(`~/.claude`/`~/.codex`) — 토큰 파일 미열람/미복사/미로깅. `startup()`에서 제약 프로브(`claude -p --tools "" -m haiku "ok"` / `codex exec -s read-only ... "ok"`, ~300s 캐시)로 만료 OAuth를 깨끗한 폴백으로 전환.

---

## 9. 호출부 마이그레이션 (필수 변경 0, opt-in 태그)

기존 `get_llm_provider().generate(messages[, temperature, max_tokens])`는 전부 무변경 동작. 태그는 한 kwarg씩:

- `services/background_scanner/scanner.py:931, 1009` → `task="scanner"` (**최대 비용 절감, 먼저 태그**)
- `agents/graph/kr_stock_nodes/decision_nodes.py:181` → `task="strategic_decision"`; `:69` → `task="risk"`
- `agents/graph/nodes.py:365/:437`(US risk/strategic), `agents/graph/coin_nodes.py:383/:453` → 동일 태그
- `services/agent_chat/agents/base_agent.py:97` → `task="group_chat"`
- `app/api/routes/chat.py:217` → `task="chat"`; `app/api/routes/analysis.py:399` → `task="translation"`
- `agents/tools/write_todos.py:73` → `task="utility"`; `services/trading/strategy_engine.py:287` → `task="strategic_decision"`
- `services/news/sentiment.py:142` → `task="sentiment_analysis"`; `agents/graph/kr_stock_nodes/helpers.py:533/607/744` → 분석 태스크
- `app/dependencies.py:48` → GENERAL 유지 또는 적절 태그(3개 소스 설계가 모두 놓친 지점)

---

## 10. 파서 검증 게이트 (클라우드 우선 + 보수적 조정)

Ollama 은퇴로 `local` 티어가 사라져 분석/GENERAL 트래픽이 **필연적으로 `deepseek-v4-flash`로 이동**한다. 프롬프트와 ~25개 정규식 파서가 로컬 `deepseek-r1` 기준으로 튜닝됐으므로, 이관 전 **파서 검증·수정이 Phase 1 필수 게이트**다.

- 각 분석/의사결정 노드를 `deepseek-v4-flash` 실출력으로 **구동**(`_parse_llm_response`/`_parse_vote`/`_extract_bull_case` 등 확인).
- 깨지는 파서는 수정(모델 출력 형식에 맞춤) 후에만 해당 태스크를 "라이브"로 플립.
- 스테이징: 인프라 세움 → 안전·고가치 먼저(scanner→DeepSeek, strategic/risk→Claude opus) → 파서 검증·수정 → 분석/GENERAL 마지막 플립. **빅뱅 금지.**

---

## 11. 생성/수정 파일

**생성**: `agents/llm/__init__.py`, `tasks.py`, `messages.py`, `subprocess_runner.py`, `router.py`, `backends/__init__.py`, `backends/base.py`, `backends/openai_compat.py`, `backends/claude_cli.py`, `backends/codex_cli.py`; `tests/llm/test_router.py`, `tests/llm/test_cli_backends.py`, `tests/llm/test_facade_compat.py`.

**수정**: `agents/llm_provider.py`, `app/config.py`, `app/main.py`(lifespan `startup()`/`aclose()`), `.env.example`(+ 루트), 그리고 §9의 opt-in 호출부(Phase 1은 scanner + strategic/risk 우선).

---

## 12. 테스트 전략 (3개 집중 파일)

- **`test_router.py`**(순수, I/O 없음): 태스크별 체인 해석(`resolve(SCANNER)==[openrouter]`), 스트리밍 필터가 CLI 드롭, 서킷브레이커 open/half-open/close 전이, 키 부재시 openrouter 드롭, 예산 초과시 드롭, 체인 소진시 `LLMAllBackendsFailed`.
- **`test_cli_backends.py`**: `flatten_messages` 분리; `run_cli` argv 안전성(셸 없음, 프롬프트 stdin/argv 확인) + 타임아웃→kill; Claude 파싱(스모크에서 캡처한 실 엔벨로프 + malformed/`is_error`→`BackendError`); Codex `-o` 파일 파싱; 둘 다 목킹(라이브 subprocess 없음).
- **`test_facade_compat.py`**: `generate(messages)` / `generate(messages, temperature=0.3)`가 router 목킹 하에 여전히 str 반환; 미지 task 문자열→GENERAL; `generate_structured`가 `DECISION_SCHEMA` 검증.
- opt-in `-m integration` 스모크(실 `claude`/`codex`, CI 스킵): 검증된 `.result` 왕복 재현.

---

## 13. 페이징 (클라우드 우선 반영)

- **1a — 스캐폴드, 파사드 계약 동일**: `agents/llm/` 스켈레톤 + `tasks.py`(GENERAL→[openrouter, claude_cli(sonnet)]). `app/config.py`에 OpenRouter + 동시성/타임아웃/예산 설정. `.env.example`에 빈 `OPENROUTER_API_KEY=`. `LLMProvider.generate/stream`을 라우터 위임으로. **주의**: Ollama 은퇴로 "바이트 동일 출력"은 목표가 아님 — **파사드 계약**(str 반환·위치인자·kwargs 불변, 미지 task→GENERAL)만 동일하며 실제 응답 모델은 openrouter다. 스캐폴드 단계에서 실 백엔드 호출은 OpenRouter 키(또는 Windows용 env-gate local)가 있어야 성립. **검증**: `test_facade_compat.py`(router 목킹) green + 기존 `pytest` 통과.
- **1b — HTTP 백엔드 + 라우터 신뢰성**: `OpenAICompatBackend`(openrouter [+옵션 local]), 세마포어·서킷브레이커·좁은 재시도·structlog·키부재 degrade·예산가드. **검증**: `test_router.py`, `health_check()` 리포트, 총실패시 `LLMAllBackendsFailed`.
- **1c — CLI 백엔드 + 라이프사이클**: `subprocess_runner.py`, `claude_cli.py`, `codex_cli.py`, `flatten_messages`, `app/main.py` lifespan 프로브. **검증**: `test_cli_backends.py`, 라이브 스모크 1회씩 `.result` 왕복.
- **1d — 스캐너 태그(최고가치·최저위험)**: `scanner.py:931,1009`에 `task="scanner"`. **검증**: 스캐너가 OpenRouter 사용, 강제 실패시 `_run_quick_analysis` degrade.
- **1e — 파서 검증 게이트(§10) + strategic/risk→Claude opus**: KR/US/coin 의사결정·리스크 노드 + `strategy_engine.py`에 태그(Claude 헬스 green 후). 분석 파서 검증·수정 후 분석 태스크 플립. 선택적으로 `generate_structured(..., DECISION_SCHEMA)`를 `--json-schema`로. **검증**: 의사결정 노드가 Claude 출력 수신, 구조화 파싱 검증, 실패시 OpenRouter 폴백.
- **1f — 기회주의적 태그**: group_chat, chat, translation, GENERAL 등 각각 독립 되돌림 가능한 한 kwarg diff.

---

## 14. 리스크와 완화

1. **CLI 지연/구독 한도**: 실측 ~5s(추정보다 김), 실전 프롬프트는 더 김. 고볼륨 오태깅시 직렬화 참사 → **라우팅 표가 핵심 방어선**(CLI를 scanner/분석 primary서 배제), 낮은 세마포어(2), 서킷브레이커.
2. **파서 품질 시프트**: ~25개 파서가 `deepseek-r1` 튜닝 → `deepseek-v4-flash` 이관시 추출 미묘 파손 → **§10 파서 검증 게이트**로 완화.
3. **CLI 출력/플래그 드리프트**: 버전업시 파싱 깨질 수 있음 → 파싱 실패=폴백 + 계약 테스트 + **CLI 버전 고정·명기**.
4. **구조화 출력 3종 편차**(`--json-schema`/`--output-schema`/`response_format`): 동일 태스크가 백엔드별 다른 JSON → 단일 `DECISION_SCHEMA` + 라우터 검증 + 검증실패=폴백.
5. **전면 아웃티지 하드 raise**: 클라우드 우선이라 로컬 오프라인 폴백 없음. CLI 로그아웃 + OpenRouter 다운/예산초과시 `LLMAllBackendsFailed` → `try/except` 호출부는 degrade, 미래핑 호출부는 에러 표면. 헬스 프로브 + 키부재 degrade로 축소하나 제거 불가.
6. **인메모리 상태 리셋**: 서킷브레이커/헬스/예산이 `uvicorn --reload`마다 리셋, 프로세스별. 단일 개발자 단일 프로세스엔 충분, 멀티워커는 이중 프로브.
7. **subprocess 인젝션 표면**: 안전은 argv/stdin(셸 없음) + `--tools ""`/`read-only` 샌드박스 + 버려지는 cwd에 의존. 미래 편집이 툴 허용/샌드박스 해제/`--bare`/`--dangerously-skip-permissions` 추가시 임의 텍스트가 에이전트 지시 표면이 됨 → **리뷰·테스트에서 이 플래그 가드**.

---

## 15. 미해결 → 해결됨 (2026-07-04)

- Claude 모델: **opus**(strategic/risk), sonnet(폴백).
- GENERAL 기본 티어: **OpenRouter**(Ollama 은퇴).
- 분석 태스크 롤아웃: **보수적 — 파서 검증 게이트**(§10).
- 스트리밍: **HTTP 전용**.
- 예산 가드: **on**($5 기본 제안).
- Codex 모델: 계정 기본값(env 조정).
