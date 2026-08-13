"""The collapsed mount must expose the exact same route set as before.

Every API router is mounted under both /api/v1/* and legacy /api/*; the frontend
uses /api/*. The dual-mount was collapsed into one table + loop, which must be
behavior-preserving.
"""
from app.main import app


def test_both_prefixes_present():
    paths = {r.path for r in app.routes}
    assert any(p.startswith("/api/v1/") for p in paths)
    assert any(p.startswith("/api/") and not p.startswith("/api/v1/") for p in paths)


def test_v1_and_legacy_counts_match():
    paths = [r.path for r in app.routes]
    v1 = sum(p.startswith("/api/v1") for p in paths)
    legacy = sum(p.startswith("/api/") and not p.startswith("/api/v1") for p in paths)
    assert v1 == legacy and v1 > 0
