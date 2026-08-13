"""jinja2 → 단일 HTML 문자열.

외부 리소스를 절대 부르지 않는다 — 폰의 인앱 브라우저에서 네트워크가
막히거나 느리면 리포트가 빈 페이지가 된다. CSS는 base.html에 인라인,
폰트는 시스템 폰트(-apple-system)만 쓴다.
"""
from __future__ import annotations

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


_env.filters["krw"] = _krw
_env.filters["pct"] = _pct
_env.filters["num"] = _num

_KINDS = {"premarket", "postmarket", "discovery"}


def render(ctx: ReportContext) -> str:
    if ctx.kind not in _KINDS:
        raise ValueError(f"unknown report kind: {ctx.kind}")
    return _env.get_template(f"{ctx.kind}.html").render(ctx=ctx)
