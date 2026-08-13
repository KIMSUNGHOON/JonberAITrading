"""jinja2 → 단일 HTML 문자열.

외부 리소스를 절대 부르지 않는다 — 폰의 인앱 브라우저에서 네트워크가
막히거나 느리면 리포트가 빈 페이지가 된다. CSS는 base.html에 인라인,
폰트는 시스템 폰트(-apple-system)만 쓴다.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from services.reports.models import ReportContext

_TEMPLATES = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES)),
    autoescape=select_autoescape(["html"]),   # 종목명·뉴스 제목은 자유 텍스트다
    trim_blocks=True,
    lstrip_blocks=True,
)


def _krw(v) -> str:
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _pct(v, digits: int = 2) -> str:
    try:
        return f"{float(v):+.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _num(v, digits: int = 2) -> str:
    try:
        return f"{float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _dash(v, placeholder="—"):
    """`None`만 자리표시자로 접는다 -- `0`은 유효한 값이라 그대로 둔다.

    ⚠️ `{{ ctx.extra.get(key, default) }}` 패턴은 **키가 없을 때만**
    default를 쓴다. `daily_trades`처럼 항상 키가 넘어오는 값이 수집
    실패로 `None`이 되면(그 키 자체는 여전히 존재) `.get`의 default가
    적용되지 않아 화면에 문자 그대로 "None"이 찍힌다(2026-08-13 최종
    리뷰 Important 3). Jinja 내장 `default` 필터는 `Undefined`만 잡고
    실제 파이썬 `None`은 그대로 통과시키므로 못 쓴다. `x or placeholder`도
    `0`(예: "오늘 아직 거래 없음")을 `None`과 똑같이 접어버려 못 쓴다 --
    그래서 `None` 여부만 명시적으로 검사한다.
    """
    return placeholder if v is None else v


_env.filters["krw"] = _krw
_env.filters["pct"] = _pct
_env.filters["num"] = _num
_env.filters["dash"] = _dash

_KINDS = {"premarket", "postmarket", "discovery"}


def render(ctx: ReportContext) -> str:
    if ctx.kind not in _KINDS:
        raise ValueError(f"unknown report kind: {ctx.kind}")
    # ⚠️ 2026-08-13 리뷰(Important): `ctx.regime`이 `None`도 `dict`도 아닌
    # truthy 객체(예: 조회 실패 센티널 `services.telegram.briefing.
    # RegimeUnavailable`)로 들어오면, 템플릿의 `{% if ctx.regime %}`가
    # "dict가 있다"로 오판해 `.confidence`/`.effective_target_pct` 같은
    # 속성 접근을 시도한다. jinja2는 없는 속성을 `Undefined`로 접지만
    # `Undefined * 100` 같은 산술에서 `UndefinedError`를 raise하므로,
    # 그 레짐 조회가 실패한 바로 그날 리포트 전체가 죽는다. 호출자
    # (`services.reports.build_and_send_report`)가 걸러주는 것에 기대지
    # 않고 여기서 한 번 더 막는다 — premarket/postmarket/discovery
    # 세 종류 템플릿이 전부 이 보장을 공유한다.
    if ctx.regime is not None and not isinstance(ctx.regime, dict):
        ctx = replace(ctx, regime=None)
    return _env.get_template(f"{ctx.kind}.html").render(ctx=ctx)
