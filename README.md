# Agentic AI Trading Application

AI-powered trading analysis system with autonomous multi-agent analysis and human-in-the-loop approval workflows.

---

## Features

- **Multi-Agent Analysis**: Technical, Fundamental, Sentiment, and Risk analysis by specialized AI agents
- **Human-in-the-Loop (HITL)**: Trade proposals require human approval before execution
- **Re-Analysis Workflow**: Reject proposals with feedback for agents to reconsider
- **Real-time Streaming**: Live reasoning logs and analysis updates via WebSocket
- **Cross-Platform**: Supports Windows, Linux, and macOS

---

## Quick Start

Choose your platform for detailed setup instructions:

| Platform | LLM Server | GPU Support | Guide |
|----------|------------|-------------|-------|
| **Windows** | Ollama (recommended) | NVIDIA CUDA | [Setup Guide](docs/setup/README_WIN.md) |
| **Linux** | vLLM (recommended) | NVIDIA CUDA | [Setup Guide](docs/setup/README_LINUX.md) |
| **macOS** | Ollama | Apple Metal | [Setup Guide](docs/setup/README_MAC.md) |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (React)                        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐│
│  │TickerInput  │ │ApprovalDlg  │ │  LiveReasoningLog       ││
│  └─────────────┘ └─────────────┘ └─────────────────────────┘│
└────────────────────────┬────────────────────────────────────┘
                         │ WebSocket / REST
┌────────────────────────▼────────────────────────────────────┐
│                    Backend (FastAPI)                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                  LangGraph Workflow                   │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │   │
│  │  │Technical │ │Fundament.│ │Sentiment │ │  Risk   │ │   │
│  │  │ Analyst  │ │ Analyst  │ │ Analyst  │ │Assessor │ │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬────┘ │   │
│  │       └────────────┴────────────┴────────────┘      │   │
│  │                         ▼                            │   │
│  │              ┌─────────────────────┐                │   │
│  │              │ Strategic Decision  │                │   │
│  │              └──────────┬──────────┘                │   │
│  │                         ▼                            │   │
│  │              ┌─────────────────────┐                │   │
│  │              │   HITL Approval     │ ← Human Review │   │
│  │              └──────────┬──────────┘                │   │
│  │                         ▼                            │   │
│  │              ┌─────────────────────┐                │   │
│  │              │  Trade Execution    │                │   │
│  │              └─────────────────────┘                │   │
│  └──────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│                    LLM Server                                │
│    vLLM (Linux) │ Ollama (Windows/macOS/Linux)              │
└─────────────────────────────────────────────────────────────┘
```

---

## Model Recommendations

| VRAM/RAM | Platform | Model | Command |
|----------|----------|-------|---------|
| 24GB+ | Linux | DeepSeek-R1-Distill-Qwen-32B | vLLM (AWQ) |
| 24GB+ | Windows/macOS | deepseek-r1:32b | `ollama pull deepseek-r1:32b` |
| 10-16GB | All | deepseek-r1:14b | `ollama pull deepseek-r1:14b` |
| 8GB | All | deepseek-r1:7b | `ollama pull deepseek-r1:7b` |

---

## Project Structure

```
JonberAITrading/
├── backend/
│   ├── app/                    # FastAPI application
│   │   ├── api/routes/         # API endpoints
│   │   ├── config.py           # Settings
│   │   └── main.py             # Entry point
│   ├── agents/                 # LangGraph agents
│   │   ├── graph/              # Workflow definition
│   │   └── llm_provider.py     # LLM abstraction
│   ├── services/               # Business logic
│   └── tests/                  # Pytest tests
├── frontend/
│   ├── src/
│   │   ├── components/         # React components
│   │   ├── store/              # Zustand state
│   │   └── api/                # API clients
│   └── vite.config.ts
├── docs/
│   ├── setup/                  # OS-specific setup guides
│   └── FEATURE_SPEC_*.md       # Feature specifications
├── environment.yml             # Conda environment
└── README.md
```

---

## Tech Stack

| Layer | Technologies |
|-------|--------------|
| **Backend** | Python 3.12, FastAPI, LangGraph, Pydantic |
| **Frontend** | React 18, Vite, TypeScript, Zustand, TailwindCSS |
| **Charts** | TradingView Lightweight Charts |
| **LLM** | vLLM (Linux), Ollama (All platforms) |
| **Storage** | SQLite (embedded, no server required) |

---

## API Reference

### Analysis Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analysis/start` | POST | Start new analysis |
| `/api/analysis/status/{id}` | GET | Get session status |
| `/api/analysis/sessions` | GET | List all sessions |
| `/api/analysis/cancel/{id}` | POST | Cancel session |

### Approval Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/approval/pending/{id}` | GET | Get pending proposal |
| `/api/approval/decide` | POST | Submit decision (approve/reject/re-analyze) |

### WebSocket

| Endpoint | Description |
|----------|-------------|
| `/ws/session/{id}` | Real-time session updates |

### System

| Endpoint | Description |
|----------|-------------|
| `/health` | Health check (API, LLM, Storage) |
| `/docs` | Swagger documentation |

---

## Environment Configuration

```env
# === LLM Configuration ===
# Windows/macOS: ollama, Linux: vllm
LLM_PROVIDER=ollama

# Ollama: http://localhost:11434/v1
# vLLM: http://localhost:8080/v1
LLM_BASE_URL=http://localhost:11434/v1

# Model name
LLM_MODEL=deepseek-r1:14b

# === Other Settings ===
MARKET_DATA_MODE=live
STORAGE_DB_PATH=data/storage.db
ENVIRONMENT=development
DEBUG=true
```

---

## Testing

```bash
conda activate agentic-trading
cd backend
pytest -v
```

---

## Documentation

- [Windows Setup Guide](docs/setup/README_WIN.md)
- [Linux Setup Guide](docs/setup/README_LINUX.md)
- [macOS Setup Guide](docs/setup/README_MAC.md)
- [Real-Time Agent Trading Feature Spec](docs/FEATURE_SPEC_REALTIME_AGENT_TRADING.md)
- [Project Instructions (CLAUDE.md)](CLAUDE.md)

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `pytest -v`
5. Submit a pull request

---

## License

MIT License
