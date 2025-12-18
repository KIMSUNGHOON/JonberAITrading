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

## Prerequisites

- **Anaconda** or Miniconda (recommended)
- **Node.js** 18+
- **Redis** (optional, for state persistence)
- **NVIDIA GPU** (Windows) or **Apple Silicon** (macOS)

---

## Setup Options (Priority Order)

1. **Anaconda** (Recommended) - Best for development
2. **Docker** - Best for deployment

---

# Option 1: Anaconda Setup (Recommended)

## Windows Setup (Windows Terminal + PowerShell)

### 1. Create Conda Environment

```powershell
# Clone repository
git clone <repository-url>
cd JonberAITrading

# Create conda environment from environment.yml
conda env create -f environment.yml

# Activate environment
conda activate agentic-trading

# Setup environment variables
Copy-Item .env.example .env
# Edit .env with your configuration (use notepad, vscode, etc.)
```

### 2. Start LLM Server (vLLM)

```powershell
# Install vLLM (requires CUDA 12.1+)
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
conda activate agentic-trading
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

### 1. Create Conda Environment

```zsh
# Clone repository
git clone <repository-url>
cd JonberAITrading

# Create conda environment from environment.yml
conda env create -f environment.yml

# Activate environment
conda activate agentic-trading

# Setup environment variables
cp .env.example .env

# Edit .env for macOS/Ollama:
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
# For M1 Pro 24GB RAM:
ollama pull deepseek-r1:7b      # ~4GB, fast
ollama pull deepseek-r1:14b     # ~8GB, balanced
ollama pull llama3.1:8b         # ~5GB, good alternative

# Verify installation
curl http://localhost:11434/v1/models
```

### 3. Start Backend (New Terminal Tab)

```zsh
conda activate agentic-trading
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

# Option 2: Docker Setup

```bash
# Start all services (uses Ollama by default)
docker-compose up backend frontend redis

# With NVIDIA GPU support (vLLM)
docker-compose --profile gpu up

# Or start specific services
docker-compose up backend

# Rebuild and start
docker-compose up --build
```

---

## Environment Configuration

Edit `.env` file based on your platform:

### Windows (vLLM + RTX 3090)
```env
LLM_PROVIDER=vllm
LLM_BASE_URL=http://localhost:8080/v1
LLM_MODEL=deepseek-ai/DeepSeek-R1-Distill-Llama-70B
MARKET_DATA_MODE=live
```

### macOS (Ollama + M1 Pro)
```env
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=deepseek-r1:7b
MARKET_DATA_MODE=live
```

---

## Conda Environment Management

```bash
# Create environment
conda env create -f environment.yml

# Activate environment
conda activate agentic-trading

# Update environment (after modifying environment.yml)
conda env update -f environment.yml --prune

# Deactivate environment
conda deactivate

# Remove environment
conda env remove -n agentic-trading

# Export current environment
conda env export > environment.yml
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
conda activate agentic-trading
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
npm run format
```

### Type Checking
```bash
# Python
cd backend
mypy app/

# TypeScript
cd frontend
npx tsc --noEmit
```

---

## Troubleshooting

### Conda Environment Issues
```bash
# If environment creation fails, try:
conda clean --all
conda env create -f environment.yml

# Or create manually:
conda create -n agentic-trading python=3.12
conda activate agentic-trading
pip install -r backend/requirements.txt
```

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

## Tech Stack

### Backend
- Python 3.12
- FastAPI 0.115+
- LangChain 0.3+
- LangGraph 0.2+
- Pydantic 2.10+

### Frontend
- React 18.3
- Vite 6.0
- TypeScript 5.7
- Zustand 5.0
- TailwindCSS 3.4

### LLM
- vLLM (Windows/Linux with NVIDIA GPU)
- Ollama (All platforms)

---

## License

MIT License
