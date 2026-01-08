# CLAUDE.md - Project Instructions for Claude Code

## Project Context
This is an **Agentic AI Trading Application** using DeepAgents, LangGraph, FastAPI, and React.
The system provides autonomous market analysis with human-in-the-loop (HITL) approval workflows.

## Target Environments

### Windows (Primary - GPU)
- **GPU**: NVIDIA RTX 3090 (24GB VRAM)
- **LLM Server**: vLLM (recommended) or Ollama
- **Terminal**: Windows Terminal (PowerShell)
- **Python**: 3.12 (Anaconda)

### macOS (Secondary - Apple Silicon)
- **Hardware**: M1 Pro MacBook Pro (24GB RAM)
- **LLM Server**: Ollama with Metal acceleration
- **Terminal**: iTerm2 (zsh)
- **Python**: 3.12 (Anaconda)

## Key Architecture Decisions

- **LLM Abstraction**: All LLM calls go through `backend/agents/llm_provider.py` which supports:
  - vLLM (OpenAI-compatible API) - Windows/Linux with NVIDIA GPU
  - Ollama (OpenAI-compatible API) - All platforms including macOS Metal

- **State Management**: LangGraph manages agent state with checkpointing for HITL interrupts

- **Real-time Updates**: WebSocket connections stream reasoning logs and position updates

- **Data Fallback**: Always use yfinance with graceful fallback to mock data in `data/mock/`

## Development Commands

### Setup (Anaconda - Recommended)
```bash
# Create and activate conda environment
conda env create -f environment.yml
conda activate agentic-trading
```

### Backend
```bash
conda activate agentic-trading
cd backend
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### LLM Server

#### Windows (Ollama - Recommended)
```powershell
# Install: winget install Ollama.Ollama
ollama serve
ollama pull deepseek-r1:32b  # RTX 3090 24GB
# or: ollama pull deepseek-r1:14b  # Less VRAM
```

#### Linux (vLLM + RTX 3090 24GB)
```bash
pip install vllm
python -m vllm.entrypoints.openai.api_server \
  --model deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
  --quantization awq \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.90 \
  --port 8080
```

#### macOS (Ollama + M1 Pro 24GB)
```zsh
brew install ollama
ollama serve &
ollama pull deepseek-r1:14b  # ~8GB RAM
```

### Tests
```bash
cd backend && pytest -v
```

## Code Style

- **Python**: Use type hints, Pydantic models, async/await patterns
- **TypeScript**: Strict mode, functional components with hooks
- **Error Handling**: Always handle errors gracefully with user-friendly messages

## Environment Variables (from .env)

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_PROVIDER` | Provider type | `ollama` (Win/macOS) or `vllm` (Linux) |
| `LLM_BASE_URL` | OpenAI-compatible endpoint | `http://localhost:11434/v1` |
| `LLM_MODEL` | Model name | `deepseek-r1:14b` |
| `MARKET_DATA_MODE` | Data source | `live` or `mock` |
| `REDIS_URL` | Redis connection | `redis://localhost:6379` |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | (required for notifications) |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | (required for notifications) |
| `TELEGRAM_ENABLED` | Enable Telegram | `false` |

## Project Structure

```
.
├── backend/
│   ├── app/                 # FastAPI application
│   │   ├── api/routes/      # API endpoints
│   │   └── api/schemas/     # Pydantic schemas
│   ├── agents/              # LangGraph agents
│   │   ├── graph/           # Graph state & nodes
│   │   ├── subagents/       # Specialist agents
│   │   └── tools/           # Agent tools
│   ├── services/            # Business logic
│   │   ├── trading/         # Auto-trading system
│   │   ├── telegram/        # Telegram notifications
│   │   ├── background_scanner/  # KOSPI/KOSDAQ scanner
│   │   └── kiwoom/          # Kiwoom API client
│   └── models/              # Data models
├── frontend/                # React application
│   └── src/
│       ├── components/      # UI components
│       ├── store/           # Zustand state
│       └── api/             # API clients
├── docker/                  # Docker configurations
├── scripts/                 # Setup scripts
└── data/mock/               # Mock data for testing
```

## Subagent Architecture

1. **Technical Analyst**: Price patterns, indicators, chart analysis
2. **Fundamental Analyst**: Financials, valuations, business metrics
3. **Sentiment Analyst**: News sentiment, social media, analyst opinions
4. **Risk Assessor**: Risk evaluation, position sizing, stop-loss levels
5. **Execution Agent**: Trade execution and monitoring

## Workflow

```
[User Input] → [Task Decomposition] → [Parallel Analysis]
                                            ↓
                                    [Risk Assessment]
                                            ↓
                                   [Strategic Decision]
                                            ↓
                                   [HITL Approval] ← Human Review
                                            ↓
                                   [Trade Execution]
```

## Planned Features (2026-01-01)

### Agent Group Chat (계획됨)
- **목적**: 사용자 관심 종목 기반 자율 자동매매
- **계획 문서**: `docs/AGENT_GROUP_CHAT_PLAN.md`
- **주요 컴포넌트**:
  - Agent Group Chat: Sub-Agent 간 토론/협의/투표
  - Watch Monitor: 관심 종목 5분 주기 모니터링
  - Position Manager: 실시간 손절/익절 관리
  - Decision Engine: 합의 기반 매매 결정
- **핵심 원칙**:
  - 사용자 통제: 관심 종목, 리스크 설정, 자동매매 ON/OFF
  - 시스템 자율: 매수/매도 타이밍, Agent 토론, 포지션 관리

## New Features (2025-12-31)

### Telegram Notifications
- **Service**: `services/telegram/`
- **Setup**: Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_ENABLED=true`
- **Features**: Trade proposals, executions, sub-agent decisions, system status

### Watch List
- **Endpoints**: `/api/trading/watch-list/*`
- **Features**: Monitor WATCH recommendations, convert to trade queue
- **Actions**: GET list, POST add, DELETE remove, POST convert

### Background Scanner
- **Endpoints**: `/api/scanner/*`
- **Features**: Scan all KOSPI/KOSDAQ stocks in background
- **Actions**: POST start/pause/resume/stop, GET progress, GET results

### TradeAction Types
- `BUY`: New buy (no position)
- `SELL`: Full sell (has position)
- `HOLD`: Hold position
- `ADD`: Add to position
- `REDUCE`: Partial sell
- `WATCH`: Monitor for entry (no position + HOLD signal)
- `AVOID`: Avoid buying (no position + STRONG_SELL signal)

## Documentation

| Document | Description |
|----------|-------------|
| `CLAUDE.md` | Claude Code 개발 지침 (이 파일) |
| `WORK_STATUS.md` | 작업 현황 및 완료된 태스크 |
| `docs/AGENT_GROUP_CHAT_PLAN.md` | Agent Group Chat 구현 계획 |
| `docs/PROJECT_ROADMAP.md` | 프로젝트 로드맵, 진행 상황 |
| `docs/UI_ARCHITECTURE.md` | UI 구조 및 컴포넌트 |
| `docs/OPENDART_API_GUIDE.md` | OpenDART API 가이드 (미구현) |
| `docs/archive/` | 완료된 기능 문서 아카이브 |
