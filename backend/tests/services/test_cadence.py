"""compute_held_ttl formula (monitoring-cadence-tuning arc).

Root cause: held-position responsiveness was gated by a hardcoded 3.0s
`stock_info` cache TTL in KiwoomClient — RiskMonitor polls every 1s but the
cache deduped fetches to once per 3s regardless of how many positions were
held. Cost scales as N/TTL req/s against Kiwoom's ~1.43 req/s ceiling, so a
fixed TTL either starves responsiveness (N small) or blows the budget
(N large). `compute_held_ttl` derives a TTL from the held-position count N
so cost stays bounded while responsiveness scales down as N grows:
`clamp(ceil(N / 0.8), 2, 20)` seconds.
"""

import pytest

from services.trading.cadence import compute_held_ttl


@pytest.mark.parametrize(
    "n,expected",
    [
        (0, 2.0),
        (1, 2.0),  # ceil(1/0.8) = ceil(1.25) = 2
        (2, 3.0),  # ceil(2/0.8) = ceil(2.5) = 3
        (5, 7.0),  # ceil(5/0.8) = ceil(6.25) = 7
        (16, 20.0),  # ceil(16/0.8) = ceil(20.0) = 20
        (100, 20.0),  # clamped at the 20s ceiling
    ],
)
def test_compute_held_ttl_examples(n, expected):
    assert compute_held_ttl(n) == expected


@pytest.mark.parametrize("n", [0, 1, 2, 5, 16, 100])
def test_compute_held_ttl_returns_float(n):
    assert isinstance(compute_held_ttl(n), float)
