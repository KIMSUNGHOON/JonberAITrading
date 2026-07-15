"""Dynamic monitoring-cadence formulas.

Pure functions that derive monitoring parameters (cache TTLs, poll
intervals, ...) from live state such as the number of held/watched
positions, so responsiveness scales with load without blowing a fixed
external rate budget (e.g. Kiwoom's ~1.43 req/s ceiling).

Kept deliberately free of any I/O or class state — every function here is a
pure `int -> float` (or similar) mapping, easy to unit-test and easy to
extend with additional cadence formulas (e.g. a future `compute_watch_ttl`
for watch-list, as opposed to held-position, monitoring).
"""

import math


def compute_held_ttl(n: int) -> float:
    """TTL (seconds) for held-position price cache lookups, given `n` held
    positions.

    Held-position responsiveness is gated by the price cache TTL: RiskMonitor
    polls every 1s, but a fixed cache TTL dedupes fetches to once per TTL
    regardless of `n`. Request cost is `n / ttl` req/s, so a fixed TTL either
    starves responsiveness when `n` is small or blows the request budget when
    `n` is large. This scales TTL with `n` instead: `clamp(ceil(n / 0.8), 2, 20)`
    seconds — roughly one request slot per position at a 0.8 req/s-per-position
    rate, floored at 2s (stay responsive with few positions) and capped at 20s
    (stay cheap with many).
    """
    ttl = math.ceil(n / 0.8)
    return float(min(max(ttl, 2), 20))
