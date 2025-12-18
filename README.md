# Agentic AI Trading Application

AI-powered trading analysis system with autonomous multi-agent analysis and human-in-the-loop approval workflows.

## Features

- **Multi-Agent Analysis**: Technical, Fundamental, Sentiment, and Risk analysis
- **Human-in-the-Loop**: Trade proposals require human approval before execution
- **Real-time Streaming**: Live reasoning logs via WebSocket
- **Cross-Platform**: Supports Windows (NVIDIA GPU) and macOS (Apple Silicon)

## Architecture

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
│  │              │   HITL Approval     │ ← Interrupt    │   │
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
│         vLLM (Windows/Linux) │ Ollama (All Platforms)       │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Redis (optional, for state persistence)
- NVIDIA GPU (Windows) or Apple Silicon (macOS)

---

## Windows Setup (Windows Terminal + PowerShell)

### 1. Clone and Setup Environment

```powershell
# Clone repository
git clone <repository-url>
cd JonberAITrading

# Create Python virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install backend dependencies
cd backend
pip install -r requirements.txt
cd ..

# Setup environment variables
Copy-Item .env.example .env
# Edit .env with your configuration
```

### 2. Start LLM Server (vLLM)

```powershell
# Install vLLM (requires CUDA)
pip install vllm

# Start vLLM server with AWQ quantization for RTX 3090
python -m vllm.entrypoints.openai.api_server `
    --model deepseek-ai/DeepSeek-R1-Distill-Llama-70B `
    --quantization awq `
    --max-model-len 8192 `
    --gpu-memory-utilization 0.95 `
    --host 0.0.0.0 `
    --port 8080
```

### 3. Start Backend (New Terminal)

```powershell
.\venv\Scripts\Activate.ps1
cd backend
uvicorn app.main:app --reload --port 8000
```

### 4. Start Frontend (New Terminal)

```powershell
cd frontend
npm install
npm run dev
```

### 5. Access Application

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

---

## macOS Setup (iTerm2 + zsh)

### 1. Clone and Setup Environment

```zsh
# Clone repository
git clone <repository-url>
cd JonberAITrading

# Create Python virtual environment
python3 -m venv venv
source venv/bin/activate

# Install backend dependencies
cd backend
pip install -r requirements.txt
cd ..

# Setup environment variables
cp .env.example .env
# Edit .env - change LLM settings for Ollama:
# LLM_PROVIDER=ollama
# LLM_BASE_URL=http://localhost:11434/v1
# LLM_MODEL=deepseek-r1:7b
```

### 2. Install and Start Ollama

```zsh
# Install Ollama
brew install ollama

# Start Ollama server (runs in background)
ollama serve &

# Pull model (choose based on available RAM)
# For 24GB RAM, you can try larger models
ollama pull deepseek-r1:7b      # ~4GB, fast
ollama pull deepseek-r1:14b     # ~8GB, balanced
ollama pull llama3.1:8b         # ~5GB, good alternative

# Verify installation
curl http://localhost:11434/v1/models
```

### 3. Start Backend (New Terminal Tab)

```zsh
source venv/bin/activate
cd backend
uvicorn app.main:app --reload --port 8000
```

### 4. Start Frontend (New Terminal Tab)

```zsh
cd frontend
npm install
npm run dev
```

### 5. Access Application

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

---

## Docker Setup (Both Platforms)

```bash
# Build and start all services
docker-compose up --build

# Or start specific services
docker-compose up backend frontend redis
```

---

## Environment Configuration

Edit `.env` file based on your platform:

### Windows (vLLM + RTX 3090)
```env
LLM_PROVIDER=vllm
LLM_BASE_URL=http://localhost:8080/v1
LLM_MODEL=deepseek-ai/DeepSeek-R1-Distill-Llama-70B
```

### macOS (Ollama + M1 Pro)
```env
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=deepseek-r1:7b
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analysis/start` | POST | Start new analysis |
| `/api/analysis/status/{id}` | GET | Get analysis status |
| `/api/approval/decide` | POST | Submit approval decision |
| `/api/approval/pending` | GET | List pending approvals |
| `/ws/session/{id}` | WS | Real-time updates |
| `/health` | GET | Health check |

---

## Development

### Run Tests
```bash
cd backend
pytest -v
```

### Code Formatting
```bash
# Python
black backend/
isort backend/

# TypeScript
cd frontend
npm run lint
```

---

## Troubleshooting

### vLLM Out of Memory (Windows)
- Reduce `--max-model-len` to 4096
- Increase `--gpu-memory-utilization` to 0.98
- Use smaller quantization or model

### Ollama Slow Response (macOS)
- Ensure Metal acceleration is enabled
- Try smaller model variant
- Check Activity Monitor for memory pressure

### WebSocket Connection Failed
- Verify backend is running on port 8000
- Check CORS settings in backend
- Ensure firewall allows connection

---

## License

MIT License
