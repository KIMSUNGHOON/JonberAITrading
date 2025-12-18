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

#### Windows (vLLM + RTX 3090 24GB)
```powershell
# PowerShell - DeepSeek-R1-Distill-Qwen-32B (AWQ ~17GB)
python -m vllm.entrypoints.openai.api_server `
  --model deepseek-ai/DeepSeek-R1-Distill-Qwen-32B `
  --quantization awq `
  --max-model-len 4096 `
  --gpu-memory-utilization 0.90 `
  --port 8080
```

#### macOS (Ollama + M1 Pro 24GB)
```zsh
# zsh
ollama serve &
ollama pull deepseek-r1:14b  # ~8GB RAM, good balance
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
| `LLM_BASE_URL` | OpenAI-compatible endpoint | `http://localhost:8080/v1` |
| `LLM_MODEL` | Model name | `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` |
| `LLM_PROVIDER` | Provider type | `vllm` or `ollama` |
| `MARKET_DATA_MODE` | Data source | `live` or `mock` |
| `REDIS_URL` | Redis connection | `redis://localhost:6379` |

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
