# Archived TodoList - Stock Trading Features

> Archived: 2025-12-19
> Status: Deferred for Coin Trading Feature Implementation

---

## Quick Reference Summary

### High Priority Pending Items

| Feature | Priority | Est. Duration | Key Tasks |
|---------|----------|---------------|-----------|
| Multi-Ticker Analysis | P1 | 1-2 weeks | Backend parallel processing, Frontend multi-session UI |
| Real-Time Agent Trading | P0 | 12-14 weeks | Agent messaging, voting, position management |
| Security (Auth) | P1 | 1 week | JWT, API keys, audit logs |

### Real-Time Agent Trading Phases
1. **Foundation** (2-3w): AgentMessageBus, data models, WebSocket streaming
2. **Decision Protocol** (2w): Voting, Risk Agent veto, orchestrator
3. **Market Monitoring** (2w): Price alerts, news feed, event triggers
4. **Position Management** (2w): Stop-loss, take-profit, P&L tracking
5. **Frontend UI** (2-3w): Chat panel, dashboard, notifications
6. **Testing** (1-2w): Integration, load testing, security audit

### UI/UX Completed ✅
- Responsive layout, ReasoningLog auto-collapse, Cancel option
- Ticker History, Markdown rendering, Re-analyze workflow

### UI/UX Pending
- Theme toggle, chart indicators, keyboard shortcuts, progress bar

### Backend Pending
- GraphQL, rate limiting, API versioning, caching, parallel nodes

### Infrastructure Pending
- Docker GPU, CI/CD, monitoring (Prometheus/Grafana), ELK logging

---

## Restore Instructions

To resume these tasks:
1. Copy relevant sections back to `docs/TODO.md`
2. Update priorities based on current project state
3. Reference `docs/FEATURE_SPEC_REALTIME_AGENT_TRADING.md` for agent trading details

---

## Related Documents
- [Real-Time Agent Trading Spec](FEATURE_SPEC_REALTIME_AGENT_TRADING.md)
- [Windows Setup](setup/README_WIN.md)
- [Linux Setup](setup/README_LINUX.md)
- [macOS Setup](setup/README_MAC.md)
