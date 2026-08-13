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


def compute_watch_ttl(w: int) -> float:
    """TTL (seconds) for watch-list price cache lookups, given `w` ACTIVE
    watch-list entries.

    Root cause (monitoring-cadence-tuning arc, MAIN BODY): `WatchedStock.
    current_price` for ACTIVE watch entries was only ever refreshed at
    coordinator `start()` and on each trade approval (via
    `_refresh_account_info` -> `_reprice_positions`) — there was no periodic
    loop, so entry-candidate prices went stale for an entire session. A
    periodic `_watch_refresh_loop` (see `ExecutionCoordinator`) fixes that,
    but its sleep/TTL must scale with `w` for the same reason `compute_held_ttl`
    scales with held-position count: request cost is `w / ttl` req/s against
    Kiwoom's ~1.43 req/s ceiling, so a fixed interval either starves
    responsiveness (few watched stocks) or blows the request budget (many).
    `clamp(ceil(w / 0.3), 10, 60)` seconds — roughly one request slot per
    watched stock at a 0.3 req/s-per-entry rate, floored at 10s and capped at
    60s.
    """
    ttl = math.ceil(w / 0.3)
    return float(min(max(ttl, 10), 60))
