"""장전 브리핑과 조회 명령의 데이터 계약 + 포맷터 (2026-08-06).

설계: docs/superpowers/specs/2026-08-06-telegram-briefing-design.md

이 모듈의 포맷터는 **순수 함수**다 — DB도 API도 모르고, 데이터클래스를 받아
문자열을 돌려줄 뿐이다. I/O는 수집기(`collect_*`)가 전담한다. 그래야 테스트가
목(mock)이 아니라 실제 렌더링을 검증한다.

출력은 **plain text**다. 이 봇은 Markdown 파싱이 실제로 깨져 plain 폴백이
경보를 살린 전력이 있다(2026-08-04) — 여기서 마크다운 특수문자를 쓰지 않는다.

값이 없을 때 표기 규약(기존 `commands.py`와 동일):
- 조회 실패 → `조회 실패`
- 값이 정상적으로 비어 있음 → `없음` 또는 그 섹션 고유의 문구
둘을 섞으면 "고장"과 "해당 없음"이 구별되지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

_NO_DATA = "조회 실패"
_NOT_STARTED = "관측 시작 전"

# `/slots`가 한 번에 보여줄 최대 종목 수. 넘으면 잘랐다고 명시한다 —
# `_truncate`가 3,900자에서 조용히 자르면 "없었다"와 구별되지 않는다.
_SLOT_LIST_LIMIT = 10


@dataclass
class BriefData:
    trade_date: str
    equity: Optional[float] = None
    stock_value: Optional[float] = None
    positions: Optional[list] = None
    max_positions: Optional[int] = None
    max_single_position_pct: Optional[float] = None
    exposure: Optional[dict] = None
    yesterday: Optional[dict] = None
    trading: Optional[dict] = None
    watch_count: Optional[int] = None
    # 2026-08-07: 오늘의 레짐 판정 행(services.storage_service.
    # get_latest_regime_judgment 반환 그대로). 행이 없어도(아직 안 돌았거나
    # 수집 실패) 정상 상태다 -- format_regime(None)이 그렇게 명시적으로 쓴다.
    # 조회 자체가 실패하면 `RegimeUnavailable`이 들어온다(3-상태, I-3).
    regime: Optional[dict] = None


@dataclass
class WhyData:
    ticker: str
    last_decision: Optional[dict] = None
    executed: bool = False
    block_reason: Optional[str] = None
    today_actions: dict = field(default_factory=dict)
    fills_today: int = 0
    sizing_lineage_present: bool = False


@dataclass
class SlotData:
    trade_date: str
    open_positions: Optional[int] = None
    max_positions: Optional[int] = None
    refusals: Optional[list] = None


@dataclass
class ExposureData:
    """2026-08-07: `m_regime`/`m_evidence`는 여기 없다 -- 레짐 배수는 앵커
    테이블(`REGIME_ANCHORS`)로, 증거량 배수는 안전장치로 기능하지 못해
    폐기로 대체됐다. 개념 자체가 없어진 것이지 조회가 실패한 게 아니므로
    `_NO_DATA`("조회 실패")로 렌더링하면 안 된다 -- 그래서 필드째 뺐다.
    """

    ts: str
    target_pct: float
    actual_pct: Optional[float] = None
    binding: Optional[str] = None
    degraded: Optional[str] = None
    m_vol: Optional[float] = None
    m_drawdown: Optional[float] = None
    index_vol_annualized: Optional[float] = None
    index_vol_n: Optional[int] = None
    n_round_trips: Optional[int] = None


def _won(v: Optional[float]) -> str:
    return f"₩{v:,.0f}" if v is not None else _NO_DATA


def _pct(v: Optional[float], digits: int = 1) -> str:
    return f"{v * 100:.{digits}f}%" if v is not None else _NO_DATA


# -------------------------------------------
# 레짐 판정 블록 (2026-08-07) — /brief와 /exposure 양쪽 앞에 붙는다.
# -------------------------------------------


class RegimeUnavailable:
    """레짐 판정 **조회 자체가 실패**했다 -- "아직 행이 없다"(None)와 구별한다.

    둘을 None 하나로 합치면 DB 장애가 영구히 "아직 안 돌았음"으로 읽힌다.
    이 설계의 명시 원칙("오류와 부재를 절대 합치지 않는다")을 어기는 것이고,
    2026-08-06에 사용자가 폰에서 실제로 신고한 사고와 같은 계열이다. 같은
    파일의 `ExposureUnavailable`과 동일한 3-상태 패턴을 따른다.

    배포 다음날 아침 검증이 전적으로 이 화면을 통해 이뤄지므로, 여기서
    오판이 나면 정상/비정상 판별 자체가 불가능해진다.
    """


# 저하 태그 → 사람이 읽을 설명. 폰에서 보는 사람에게 코드 식별자를 그대로
# 던지면 "실패"로 읽힌다 — 대부분은 "판정은 났고 입력 하나가 낡았다"는
# 꼬리표다. 위험 방향(노출도가 열리는지 닫히는지)까지 한 줄에 담는다.
#
# ⚠️ 표에 없는 태그는 **원문 그대로** 보여준다(아래 `_describe_degraded`).
# 표시 계층이 모르는 태그를 삼키면, 새로 생긴 저하 사유가 폰에서 영영 안 보인다.
_DEGRADED_LABELS: dict[str, str] = {
    "index_series_lagging": "지수 시계열이 거래일 기준으로 뒤짐 — 노출도는 보수적으로 계산됨",
    "index_series_stale": "지수 시계열이 7일 이상 낡음 — 노출도는 보수적으로 계산됨",
    "index_series_lag_unknown": "지수 지연 여부를 판정 못 함(달력 조회 실패)",
    "index_vol_insufficient": "지수 변동성 표본 부족 — 변동성 배수를 신뢰할 수 없음",
    "equity_peak_unavailable": "계좌 고점 조회 실패 — 낙폭 방어 배수를 믿을 수 없음",
    "portfolio_state_unavailable": "계좌 조회 실패 — 실제 비중을 못 읽음",
    "target_clamped_defense_unreliable": "방어 배수를 못 믿어 목표를 직전 값 이하로 눌러둠",
    "regime_unparseable": "LLM 응답을 해석 못 함 — 직전 판정을 잇는 중",
    "llm_unavailable": "LLM 호출 실패 — 직전 판정을 잇는 중",
    "regime_unknown": "레짐 라벨 미상",
}


def _describe_degraded(tag: str) -> str:
    """알려진 태그면 `설명 (원문)`, 모르는 태그면 원문 그대로.

    원문을 항상 남기는 이유: 로그(`index_series_lagging` 등)와 대조해야
    원인을 추적할 수 있고, 그 대조가 이 태그를 만든 목적이다.
    """
    label = _DEGRADED_LABELS.get(tag)
    return f"{label} ({tag})" if label else tag


def format_regime(row) -> str:
    """오늘의 레짐 판정 블록. 세 상태를 구별한다 -- 조용히 중립을
    보여주면 '판정 못 함'과 '중립으로 판정함'이 구별되지 않는다.

    - `dict`               : 판정이 있다
    - `None`               : 아직 안 돌았거나 매크로 수집 실패(정상 상태)
    - `RegimeUnavailable`  : 조회 실패(비정상)
    """
    if isinstance(row, RegimeUnavailable) or row is RegimeUnavailable:
        return f"📊 레짐: {_NO_DATA}"
    if not row:
        return "📊 레짐: 판정 없음 (아직 돌지 않았거나 매크로 수집 실패)"
    lines = [
        f"📊 레짐: {row['regime']}"
        + (f" (신뢰 {row['confidence']:.0%})" if row.get("confidence") else ""),
        f"   목표 주식 {row['effective_target_pct'] * 100:.1f}%"
        f" · 앵커 {row['anchor_target_pct'] * 100:.0f}%",
    ]
    for d in (row.get("key_drivers") or [])[:3]:
        lines.append(f"   · {d}")
    for tag in row.get("degraded") or []:
        lines.append(f"   ⚠️ {_describe_degraded(tag)}")
    return "\n".join(lines)


# -------------------------------------------
# /brief
# -------------------------------------------


def _brief_allocation(d: BriefData) -> list[str]:
    lines = ["[자산 배분]"]
    if d.equity is None or d.stock_value is None or d.equity <= 0:
        lines.append(f"  {_NO_DATA}")
        return lines

    cash = d.equity - d.stock_value
    lines.append(f"  총자산   {_won(d.equity)}")
    lines.append(f"  주식     {_won(d.stock_value)}  {_pct(d.stock_value / d.equity)}")
    lines.append(f"  예수금   {_won(cash)}  {_pct(cash / d.equity)}")

    # 구조적 천장 = 슬롯 수 × 종목당 비중. 현금·주식 비중 노브가 아니라
    # 이 곱이 실제로 배분을 결정한다 -- 브리핑의 요점이다.
    if d.max_positions and d.max_single_position_pct:
        ceiling = d.max_positions * d.max_single_position_pct
        lines.append(
            f"  구조적 천장  {_pct(ceiling)}"
            f"  ({d.max_positions}슬롯 x {_pct(d.max_single_position_pct, 0)})"
        )
    return lines


def _brief_exposure(d: BriefData) -> list[str]:
    if not d.exposure:
        # 08:30에는 오늘 행이 없다. 어제 값을 오늘 값인 척 보여주지 않는다.
        return [f"  목표 노출도  {_NOT_STARTED}"]
    e = d.exposure
    ts = str(e.get("ts") or "")[:16]
    line = f"  목표 노출도  {_pct(e.get('target_pct'))}"
    if e.get("binding"):
        line += f"  ({e['binding']}가 묶음)"
    if ts:
        line += f"  [{ts} 기준]"
    return [line]


def _brief_positions(d: BriefData) -> list[str]:
    if d.positions is None:
        return ["[보유]", f"  {_NO_DATA}"]
    if not d.positions:
        return ["[보유]", "  없음"]
    lines = [f"[보유 {len(d.positions)}종]"]
    for p in d.positions:
        lines.append(
            f"  {p.get('ticker','?'):8} {p.get('quantity',0):>6}주"
            f"  {p.get('pnl_pct',0.0):+5.1f}%"
            f"  손절까지 {p.get('stop_gap_pct',0.0):4.1f}%"
        )
    return lines


def _brief_yesterday(d: BriefData) -> list[str]:
    if not d.yesterday:
        return ["[어제]", f"  {_NO_DATA}"]
    y = d.yesterday
    lines = [f"[어제 {y.get('trade_date','')}]"]
    lines.append(
        f"  결정 {y.get('decisions',0)}건 · 체결 {y.get('fills',0)}건"
        f" · 실현손익 {_won(y.get('realized_pnl'))}"
    )
    refusals = y.get("slot_refusals")
    if refusals:
        lines.append(f"  슬롯 거절 {refusals}건 — /slots 로 상세")
    return lines


def _brief_readiness(d: BriefData) -> list[str]:
    lines = ["[오늘 준비]"]
    if not d.trading:
        lines.append(f"  {_NO_DATA}")
    else:
        t = d.trading
        state = "가능" if t.get("is_active") else "정지"
        lines.append(f"  자율 실행  {state} ({t.get('mode','?')})")
        lines.append(
            f"  일일 거래  {t.get('daily_trades',0)}/{t.get('max_daily_trades',0)}"
        )
    if d.watch_count is not None:
        lines.append(f"  워치       {d.watch_count}종")

    held = len(d.positions) if d.positions is not None else None
    if held is not None and d.max_positions:
        mark = "  만석 — 신규 진입 불가" if held >= d.max_positions else ""
        lines.append(f"  슬롯       {held}/{d.max_positions}{mark}")
    return lines


def format_brief(d: BriefData) -> str:
    """장전 브리핑 한 편. 섹션 하나가 죽어도 나머지는 나간다."""
    parts: list[str] = [f"[장전 브리핑] {d.trade_date}", ""]
    parts.append(format_regime(d.regime))
    parts.append("")
    parts += _brief_allocation(d)
    parts += _brief_exposure(d)
    parts.append("")
    parts += _brief_positions(d)
    parts.append("")
    parts += _brief_yesterday(d)
    parts.append("")
    parts += _brief_readiness(d)
    return "\n".join(parts)


# -------------------------------------------
# /why
# -------------------------------------------


def format_why(d: WhyData) -> str:
    """'왜 샀나 / 왜 안 샀나'에 한 화면으로 답한다.

    이 명령이 존재하는 이유: 2026-08-05~06에 316140이 ADD를 7회씩 의결하고
    체결 0건이었는데, 그 사유를 찾는 데 DB 조회·로그 grep·코드 추적·오프라인
    재현까지 필요했다.
    """
    lines = [f"[왜?] {d.ticker}", ""]

    if not d.last_decision:
        lines.append("  최근 결정  없음")
    else:
        x = d.last_decision
        lines.append(
            f"  최근 결정  {x.get('ts','')}  {x.get('action','?')}"
            f"  합의 {x.get('consensus',0.0):.2f}"
        )

    lines.append(f"  실행       {'체결됨' if d.executed else '안 나감'}")

    if d.block_reason:
        lines.append(f"  막은 것    {d.block_reason}")

    if d.today_actions:
        summary = " · ".join(f"{k} {v}회" for k, v in sorted(d.today_actions.items()))
        lines.append(f"  오늘       {summary} / 체결 {d.fills_today}건")

    if not d.sizing_lineage_present and not d.executed:
        # 계보 부재는 지문이다 -- 게이트에서 반환되면 사이징 코드에 도달조차
        # 못 하므로 sizing_lineage가 남지 않는다.
        lines.append("  사이징     계보 없음 — 사이징에 도달하지 못했다")

    return "\n".join(lines)


# -------------------------------------------
# /slots
# -------------------------------------------


def format_slots(d: SlotData) -> str:
    """자리가 없어 거절된 종목. 슬롯 상한을 올릴지 판단하는 근거 데이터."""
    lines = [f"[슬롯 경합] {d.trade_date}", ""]

    if d.open_positions is not None and d.max_positions:
        mark = "  만석" if d.open_positions >= d.max_positions else ""
        lines.append(f"  보유 {d.open_positions}/{d.max_positions}{mark}")
        lines.append("")

    if d.refusals is None:
        lines.append(f"  {_NO_DATA}")
        return "\n".join(lines)
    if not d.refusals:
        lines.append("  거절 없음")
        return "\n".join(lines)

    total = len(d.refusals)
    lines.append(f"  거절 {total}종")
    for r in d.refusals[:_SLOT_LIST_LIMIT]:
        lines.append(
            f"  {r.get('ticker','?'):8} {r.get('count',0):>3}회"
            f"  최고 합의 {r.get('max_consensus',0.0):.3f}"
            f"  {r.get('first','')}~{r.get('last','')}"
        )
    if total > _SLOT_LIST_LIMIT:
        lines.append(f"  …외 {total - _SLOT_LIST_LIMIT}종 (전체 {total}종)")
    return "\n".join(lines)


# -------------------------------------------
# /exposure
# -------------------------------------------


def format_exposure(d) -> str:
    """목표 노출도와 그것을 만든 성분. degraded 사유가 보여야 값이 있다."""
    if isinstance(d, ExposureUnavailable):
        return f"[목표 노출도]\n\n  {_NO_DATA}"
    if d is None:
        return f"[목표 노출도]\n\n  {_NOT_STARTED}"

    lines = ["[목표 노출도]", "", f"  기준 시각  {str(d.ts)[:19]}"]
    lines.append(f"  목표       {_pct(d.target_pct)}")
    if d.actual_pct is not None:
        lines.append(f"  실제       {_pct(d.actual_pct)}")
    if d.binding:
        lines.append(f"  묶은 성분  {d.binding}")
    lines.append("")
    lines.append("  [성분]")
    for name, val in (
        ("m_vol", d.m_vol),
        ("m_drawdown", d.m_drawdown),
    ):
        lines.append(f"    {name:12} {val if val is not None else _NO_DATA}")

    if d.n_round_trips is not None:
        lines.append(f"    왕복 거래    {d.n_round_trips}건")

    if d.degraded:
        lines.append("")
        lines.append(f"  저하  {d.degraded}")
        # 게이트에 막힌 원값을 함께 보여준다 -- 왜 중립인지가 안 보이면
        # degraded를 만든 의미가 없다.
        if d.index_vol_annualized is not None:
            lines.append(
                f"        실측 지수 변동성 {d.index_vol_annualized:.1f}%"
                f" (표본 {d.index_vol_n or 0}일)"
            )
    return "\n".join(lines)


# -------------------------------------------
# 수집기 — I/O는 전부 여기 모은다
# -------------------------------------------
#
# 포맷터와 달리 여기는 DB와 코디네이터를 안다. 각 조회는 호출자(`commands.py`의
# `_safe`)가 감싸므로 여기서는 예외를 삼키지 않는다 -- 삼키면 "실패"와 "값 없음"이
# 구별되지 않는다. 다만 섹션 단위로 나눠 두어 하나가 죽어도 나머지가 산다.


async def _storage():
    from services.storage_service import get_storage_service

    return await get_storage_service()


async def _coordinator():
    from app.dependencies import get_trading_coordinator

    return await get_trading_coordinator()


async def collect_brief(trade_date: str, prev_date: Optional[str] = None) -> BriefData:
    """장전 브리핑 데이터를 모은다. 섹션별로 독립 실패한다."""
    from services.telegram.commands import _safe

    d = BriefData(trade_date=trade_date)

    coord = await _safe("brief_coordinator", _coordinator())
    if coord is not None:
      try:
        account = getattr(coord._state, "account", None)
        d.equity = float(getattr(account, "total_equity", 0) or 0) or None
        positions = list(getattr(coord._state, "positions", []) or [])
        d.stock_value = sum(p.quantity * p.current_price for p in positions)
        d.positions = [
            dict(
                ticker=p.ticker,
                quantity=p.quantity,
                pnl_pct=(
                    (p.current_price - p.avg_price) / p.avg_price * 100
                    if p.avg_price else 0.0
                ),
                stop_gap_pct=(
                    (p.current_price - p.stop_loss) / p.current_price * 100
                    if p.stop_loss and p.current_price else 0.0
                ),
            )
            for p in positions
        ]
        rp = getattr(coord, "risk_params", None)
        d.max_positions = getattr(rp, "max_open_positions", None)
        d.max_single_position_pct = getattr(rp, "max_single_position_pct", None)
        d.watch_count = len(getattr(coord._state, "watch_list", []) or []) or None
        d.trading = dict(
            mode=str(getattr(coord._state, "mode", "?")),
            is_active=bool(getattr(coord, "is_active", False)),
            daily_trades=getattr(coord._state, "daily_trades_count", 0),
            max_daily_trades=getattr(rp, "max_daily_trades", 0),
        )
      except Exception:
        # 코디네이터 파생부가 통째로 죽어도 브리핑 전체를 잃지 않는다 --
        # 이 블록만 비고 어제/노출도 섹션은 그대로 나간다.
        pass

    storage = await _safe("brief_storage", _storage())
    if storage is not None:
        try:
            rows = await storage.get_latest_exposure_shadow()
        except Exception:
            # 브리핑에서는 조회 실패도 "관측 시작 전"으로 접는다 -- 한 줄짜리
            # 요약이라 상태를 셋으로 나눌 지면이 없다. 상세는 /exposure가
            # 구별해 보여준다.
            rows = None
        if rows:
            d.exposure = dict(
                target_pct=rows.get("target_pct"),
                binding=rows.get("binding"),
                degraded=rows.get("degraded"),
                ts=rows.get("created_at"),
            )
        try:
            # 직접 try/except -- `_safe`로 감싸면 이 한 줄의 실패가 바깥
            # `_safe("brief", collect_brief(...))`(commands.py)까지 전파돼
            # 브리핑 전체가 조회 실패로 접힌다("행 없음"과 "조회 실패"가
            # 섹션 하나에서 다시 합쳐지는 대신, 브리핑 전 섹션이 함께
            # 죽는 더 나쁜 형태로 재발한다). exposure_shadow 조회(바로 위)와
            # 동일한 섹션-독립 실패 패턴.
            d.regime = await storage.get_latest_regime_judgment()
        except Exception:
            # `None`(행 없음)으로 접지 않는다 -- 조회 실패가 "아직 안 돌았음"으로
            # 읽히면 배포 다음날 아침 검증이 정상/비정상을 구별하지 못한다(I-3).
            d.regime = RegimeUnavailable()
        if prev_date:
            d.yesterday = await _safe(
                "brief_yesterday", storage.get_day_rollup(prev_date)
            )
    return d


async def collect_slots(trade_date: str) -> SlotData:
    """슬롯 경합 — 자리가 없어 거절된 종목을 종목별로 접는다."""
    from services.telegram.commands import _safe

    d = SlotData(trade_date=trade_date)

    coord = await _safe("slots_coordinator", _coordinator())
    if coord is not None:
        d.open_positions = len(getattr(coord._state, "positions", []) or [])
        d.max_positions = getattr(
            getattr(coord, "risk_params", None), "max_open_positions", None
        )

    storage = await _safe("slots_storage", _storage())
    if storage is not None:
        d.refusals = await _safe(
            "slots_refusals", storage.get_slot_contest_rollup(trade_date)
        )
    return d


async def collect_regime_row():
    """오늘의 레짐 판정 1행. `/exposure`가 `format_regime`으로 앞에 붙일 때
    쓴다(`/brief`는 `collect_brief`가 `BriefData.regime`으로 직접 채운다).

    - `dict`              : 행이 있다
    - `None`              : 아직 안 돌았다(정상)
    - `RegimeUnavailable` : 조회 실패(비정상)

    `get_latest_regime_judgment()`는 행이 없으면 `None`, DB 오류는 raise한다.
    여기서 직접 try/except로 감싸는 이유: `_safe`로 감싸면 "행 없음"과
    "조회 실패"가 다시 하나의 `None`으로 합쳐져 로그에서도 구별이 안 된다
    (commands.py의 바깥 `_safe("exposure_regime", ...)`는 이 함수 자체가
    호출부에서 죽지 않게 하는 별도의 방어층이지, 이 구별을 대신하지 않는다).

    I-3 (2026-08-07): 로그에서만 구별하고 **화면에는 같은 문구**를 내보내던
    것을 봉합했다. 조회 실패는 `RegimeUnavailable`로 올려 보낸다 --
    `collect_exposure`/`ExposureUnavailable`과 같은 패턴.
    """
    try:
        storage = await _storage()
        return await storage.get_latest_regime_judgment()
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(
            "regime_row_fetch_failed: %s", e
        )
        return RegimeUnavailable()


class ExposureUnavailable:
    """조회 자체가 실패했다 -- "아직 행이 없다"(None)와 구별한다.

    둘을 None 하나로 뭉개면 스토리지 장애가 영구히 "관측 시작 전"으로 보고된다.
    """


async def collect_exposure():
    """최근 목표 노출도 1행.

    - `ExposureData` : 행이 있다
    - `None`         : 관측이 아직 안 돌았다(정상)
    - `ExposureUnavailable` : 조회 실패(비정상)
    """
    from services.telegram.commands import _safe

    storage = await _safe("exposure_storage", _storage())
    if storage is None:
        return ExposureUnavailable()
    try:
        # `_safe`를 쓰지 않는 이유: `_safe`는 실패를 None으로 접는데, 이
        # 호출에서는 None이 "행이 아직 없다"는 정상 신호다. 둘을 구별하려면
        # 예외를 직접 받아야 한다.
        row = await storage.get_latest_exposure_shadow()
    except Exception:
        return ExposureUnavailable()
    if not row:
        return None
    return ExposureData(
        ts=str(row.get("created_at") or ""),
        target_pct=row.get("target_pct"),
        actual_pct=row.get("actual_pct"),
        binding=row.get("binding"),
        degraded=row.get("degraded") or None,
        m_vol=row.get("m_vol"),
        m_drawdown=row.get("m_drawdown"),
        index_vol_annualized=row.get("index_vol_annualized"),
        index_vol_n=row.get("index_vol_n"),
        n_round_trips=row.get("n_round_trips"),
    )


async def collect_why(ticker: str, trade_date: str) -> WhyData:
    """'왜 샀나 / 왜 안 샀나'.

    거절 사유는 DB에 남지 않는다(게이트 거절은 로그에만 있다). 그래서 활성
    로그 파일의 **꼬리만** 읽어 이 종목의 차단 이벤트를 찾는다 -- 전체를 읽으면
    30MB짜리 파일을 매번 훑게 된다.
    """
    from services.telegram.commands import _safe

    d = WhyData(ticker=ticker)

    storage = await _safe("why_storage", _storage())
    if storage is not None:
        rows = await _safe("why_decisions", storage.get_ticker_day_decisions(ticker, trade_date))
        if rows:
            last = rows[-1]
            d.last_decision = dict(
                ts=last.get("created_at"),
                action=last.get("action"),
                consensus=last.get("consensus_level") or 0.0,
            )
            counts: dict = {}
            for r in rows:
                a = r.get("action") or "?"
                counts[a] = counts.get(a, 0) + 1
            d.today_actions = counts
            d.sizing_lineage_present = any(r.get("sizing_lineage") for r in rows)
        rollup = await _safe("why_fills", storage.get_ticker_day_fills(ticker, trade_date))
        d.fills_today = rollup or 0
        d.executed = d.fills_today > 0

    d.block_reason = await _scan_block_reason(ticker)
    return d


# `/why`의 차단 사유 스캔 범위. **best-effort다.**
#
# 로그는 파일당 50MB이고 LLM 요청 페이로드가 통째로 한 줄에 담겨 있어, 5개
# 파일(250MB)에 정규식을 돌리면 5초를 넘긴다(실측). 폰 명령이 그만큼 멈춰
# 있으면 안 되므로 최근 2개 파일 / 3초로 묶는다.
#
# 그래서 오래된 차단 사유는 못 찾는다 — 못 찾으면 None을 돌려주고 포맷터는
# 그 줄을 아예 그리지 않는다. **모르는 것을 아는 척하지 않는다.**
# 근본 해결은 게이트 거절을 DB에 기록하는 것이고, 그건 별도 작업이다
# (그때 이 스캐너는 폴백으로 남기거나 지운다).
_LOG_SCAN_FILES = 2
_LOG_SCAN_TIMEOUT_SECONDS = 3.0

_BLOCK_EVENTS = (
    ("add_gate_denied", "게이트"),
    ("add_blocked_by_position_cap", "단일 종목 상한"),
    ("add_blocked_by_liquidity_cap", "유동성 캡"),
    ("add_blocked_by_daily_limit", "일일 거래 상한"),
    ("add_no_coordinator_position", "원장 불일치"),
    ("add_unfilled", "미체결"),
)


def _log_dir():
    """로그 디렉터리. 테스트가 갈아끼울 수 있도록 함수로 분리했다.

    briefing.py는 backend/services/telegram/ 아래이므로 리포 루트는
    parents[3]이다 -- app/logging_config.py(한 단계 얕다)와 인덱스가 다르다.
    """
    from pathlib import Path

    return Path(__file__).resolve().parents[3] / "debug" / "log"


async def _scan_block_reason(ticker: str) -> Optional[str]:
    """최근 로그에서 이 종목의 마지막 차단 사유를 찾는다. never-raise.

    grep에 맡기는 이유는 순전히 규모다 — 로그가 파일당 50MB라 Python으로
    줄 단위 순회를 하면 이벤트 루프를 수 초간 붙든다. 못 찾으면 None을
    돌려주고, 포맷터는 그 줄을 아예 그리지 않는다 — **모르는 것을 아는 척하지
    않는다.**

    한계(의도적): 로그가 회전해 나가면 사유도 사라진다. 근본 해결은 게이트
    거절을 DB에 기록하는 것이고 그건 별도 작업이다.
    """
    import asyncio
    import re
    from pathlib import Path

    try:
        log_dir = _log_dir()
        candidates = list(log_dir.glob("*.log")) + list(log_dir.glob("*.log.[0-9]"))
        newest_first = sorted(
            candidates, key=lambda p: p.stat().st_mtime, reverse=True
        )[:_LOG_SCAN_FILES]
        # 최신 N개를 고르되 grep에는 **오래된 것부터** 넘긴다. grep은 인자
        # 순서대로 출력하므로, 최신 파일을 먼저 주면 아래 "마지막 줄이 이긴다"
        # 규칙이 오래된 사유를 집어 든다(리뷰가 실측으로 잡았다).
        logs = list(reversed(newest_first))
        if not logs:
            return None

        pattern = "|".join(e for e, _ in _BLOCK_EVENTS)
        proc = await asyncio.create_subprocess_exec(
            "grep", "-ahE", pattern, *[str(p) for p in logs],
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(
                proc.communicate(), timeout=_LOG_SCAN_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            proc.kill()
            return None

        ansi = re.compile(r"\x1b\[[0-9;]*m")
        hit = None
        for raw in out.decode("utf-8", errors="replace").splitlines():
            if ticker not in raw:
                continue
            clean = ansi.sub("", raw)
            for event, label in _BLOCK_EVENTS:
                if event in clean:
                    m = re.search(r"gate_reason='([^']*)'", clean)
                    hit = f"{label} · {event}" + (f" — {m.group(1)}" if m else "")
        return hit
    except Exception:
        return None


async def _collect_exposure_trend(days: int = 5) -> list[dict]:
    """최근 N거래일 목표 노출도. 실패하면 빈 리스트 → 섹션이 통째로 빠진다.

    ⚠️ `StorageService`에는 범용 `fetch_all`이 없다 — `get_ticker_day_
    decisions_full` 등 기존 조회기와 같은 `aiosqlite.connect(db_path)`
    패턴을 직접 쓴다.
    """
    try:
        import aiosqlite

        from services.storage_service import get_storage_service

        storage = await get_storage_service()
        async with aiosqlite.connect(str(storage.db_path)) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT trade_date, regime, effective_target_pct FROM regime_judgment "
                "ORDER BY trade_date DESC LIMIT ?",
                (days,),
            )
            rows = [dict(r) for r in await cursor.fetchall()]
        rows = list(reversed(rows))
        if not rows:
            return []
        top = max((r["effective_target_pct"] or 0) for r in rows) or 1
        return [
            {
                "trade_date": r["trade_date"],
                "regime": r["regime"],
                "pct": (r["effective_target_pct"] or 0) * 100,
                "width_pct": (r["effective_target_pct"] or 0) / top * 100,
            }
            for r in rows
        ]
    except Exception:
        return []


# -------------------------------------------
# 08:30 자동 발송
# -------------------------------------------

_BRIEF_HOUR = 8
_BRIEF_MINUTE = 30

_scheduler = None


async def send_morning_brief() -> bool:
    """장전 브리핑을 텔레그램으로 보낸다. never-raise — 실패해도 False만.

    발송 직전 영업일을 확인한다. 주말·공휴일 아침에 "보유 5종, 슬롯 만석"이
    날아오면 그날 장이 열리는 줄 알게 된다.
    """
    import logging

    log = logging.getLogger(__name__)
    try:
        from datetime import date, timedelta

        holiday_svc = None
        try:
            from services.krx_holiday import get_holiday_service

            holiday_svc = await get_holiday_service()
            if not holiday_svc.is_trading_day(date.today()):
                log.info("morning_brief_skipped_non_business_day")
                return False
        except Exception:
            # 영업일 판단이 안 되면 보낸다 -- 브리핑 한 통이 잘못 가는 것이
            # 열린 장에 브리핑이 안 가는 것보다 낫다.
            log.warning("morning_brief_business_day_check_failed")

        today = date.today().isoformat()
        # ⚠️ 달력 -1일이 아니라 **직전 거래일**이어야 한다 -- 월요일 아침에
        # `date.today() - timedelta(days=1)`는 일요일이 된다(2026-08-13
        # 최종 리뷰 Critical 2). `holiday_svc`를 못 구했으면(위 except) 어쩔
        # 수 없이 달력 계산으로 접는다 -- 브리핑 발송 자체를 막을 이유는
        # 아니다.
        if holiday_svc is not None:
            try:
                prev = holiday_svc.get_previous_trading_day(date.today()).isoformat()
            except Exception:
                prev = (date.today() - timedelta(days=1)).isoformat()
        else:
            prev = (date.today() - timedelta(days=1)).isoformat()
        try:
            data = await collect_brief(today, prev)
        except Exception:
            # 수집이 통째로 실패해도 "브리핑을 못 만들었다"는 사실은 보낸다 --
            # 침묵하면 스케줄러가 죽은 것과 구별되지 않는다.
            data = BriefData(trade_date=today)
        text = format_brief(data)

        from services.telegram import get_telegram_notifier

        notifier = await get_telegram_notifier()
        if not notifier.is_ready:
            log.warning("morning_brief_notifier_not_ready")
            return False
        await notifier.send_message(text)

        # 리포트는 텍스트 발송 뒤에 붙는 부가물이다 — 여기서 무엇이
        # 실패해도 위의 send_message는 이미 나갔다.
        try:
            from services.reports import build_and_send_report

            await build_and_send_report(
                "premarket",
                today,
                # 표지 날짜(today)와 분리 -- 토론 조회는 직전 거래일 기준
                # (스펙 §5-1, 2026-08-13 최종 리뷰 Critical 2).
                research_date=prev,
                # `data.regime`은 dict(정상) · None(아직 안 돌았음) ·
                # `RegimeUnavailable()`(조회 실패, 3-상태 중 하나) 이렇게
                # 세 형태일 수 있다. `RegimeUnavailable()`은 `__bool__`을
                # 오버라이드하지 않은 평범한 객체라 truthy라서 `or None`이
                # 걸러내지 못한다 — dict인지 명시로 확인해야 한다
                # (2026-08-13 리뷰 Important, render.py에도 동일 가드 있음).
                regime=(data.regime if isinstance(data.regime, dict) else None),
                actual_exposure_pct=(data.exposure or {}).get("actual_pct"),
                max_positions=data.max_positions,
                max_single_position_pct=data.max_single_position_pct,
                daily_trades=(data.trading or {}).get("daily_trades"),
                max_daily_trades=(data.trading or {}).get("max_daily_trades"),
                exposure_trend=await _collect_exposure_trend(),
            )
        except Exception as e:  # noqa: BLE001
            log.warning("morning_brief_report_failed: %s", e)

        log.info("morning_brief_sent", extra={"chars": len(text)})
        return True
    except Exception as e:  # noqa: BLE001 -- 브리핑이 앱을 죽이면 안 된다
        log.warning("morning_brief_failed: %s", e)
        return False


def start_morning_brief_scheduler(hour: int = _BRIEF_HOUR, minute: int = _BRIEF_MINUTE):
    """평일 hour:minute에 브리핑을 보내는 스케줄러를 띄운다.

    `krx_holiday`의 스케줄러와 같은 형태 -- 앱 기동 시 1회 호출하고, 실패해도
    앱을 죽이지 않는다. 요일 필터(mon-fri)는 1차 거름망이고 공휴일은
    `send_morning_brief`가 발송 직전에 다시 본다.
    """
    global _scheduler
    import logging

    log = logging.getLogger(__name__)
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        if _scheduler is not None:
            return _scheduler
        _scheduler = AsyncIOScheduler()
        _scheduler.add_job(
            send_morning_brief,
            CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute),
            id="morning_brief",
            replace_existing=True,
        )
        _scheduler.start()
        log.info("morning_brief_scheduler_started")
        return _scheduler
    except Exception as e:  # noqa: BLE001
        log.warning("morning_brief_scheduler_failed: %s", e)
        return None
