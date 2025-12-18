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
- **Redis** 7.0+ (for session persistence and caching)
- **NVIDIA GPU** (Windows) or **Apple Silicon** (macOS)
- **CUDA 12.1+** (Windows/Linux with NVIDIA GPU only)

---

## CUDA Installation (Windows - NVIDIA GPU)

vLLM requires CUDA 12.1 or higher. Follow these steps:

### 1. Check GPU Compatibility

```powershell
# Check if NVIDIA driver is installed
nvidia-smi
```

### 2. Install CUDA Toolkit

1. Download CUDA Toolkit 12.1+ from [NVIDIA CUDA Downloads](https://developer.nvidia.com/cuda-downloads)
2. Select: Windows → x86_64 → 11/10 → exe (local)
3. Run installer with default options
4. Verify installation:

```powershell
nvcc --version
# Should show: release 12.1 or higher
```

### 3. Install cuDNN (Optional but Recommended)

1. Download cuDNN from [NVIDIA cuDNN](https://developer.nvidia.com/cudnn) (requires NVIDIA account)
2. Extract and copy files to CUDA installation directory
3. Add to PATH if needed

### 4. Environment Variables

Ensure these are in your system PATH:
```
C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.1\bin
C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.1\libnvvp
```

### 5. Verify CUDA for PyTorch

```powershell
conda activate agentic-trading
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA version: {torch.version.cuda}')"
```

Expected output:
```
CUDA available: True
CUDA version: 12.1
```

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

# Start vLLM server with AWQ quantization for RTX 3090 (24GB)
# Option 1: DeepSeek-R1-Distill-Qwen-32B (Recommended - Best performance)
python -m vllm.entrypoints.openai.api_server `
    --model deepseek-ai/DeepSeek-R1-Distill-Qwen-32B `
    --quantization awq `
    --max-model-len 4096 `
    --gpu-memory-utilization 0.90 `
    --host 0.0.0.0 `
    --port 8080

# Option 2: DeepSeek-R1-Distill-Qwen-14B (More stable, longer context)
# python -m vllm.entrypoints.openai.api_server `
#     --model deepseek-ai/DeepSeek-R1-Distill-Qwen-14B `
#     --quantization awq `
#     --max-model-len 8192 `
#     --gpu-memory-utilization 0.90 `
#     --host 0.0.0.0 `
#     --port 8080
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

## Redis Setup

Redis is used for session persistence and caching. Install and start Redis:

### Windows (WSL2 or Docker)
```powershell
# Option 1: Docker
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Option 2: WSL2
wsl -d Ubuntu
sudo apt update && sudo apt install redis-server
sudo service redis-server start
```

### macOS
```zsh
# Install via Homebrew
brew install redis

# Start Redis service
brew services start redis

# Or run directly
redis-server
```

### Verify Redis Connection
```bash
redis-cli ping
# Should return: PONG
```

---

## Environment Configuration

Edit `.env` file based on your platform:

### Windows (vLLM + RTX 3090 24GB)
```env
LLM_PROVIDER=vllm
LLM_BASE_URL=http://localhost:8080/v1
LLM_MODEL=deepseek-ai/DeepSeek-R1-Distill-Qwen-32B
MARKET_DATA_MODE=live
REDIS_URL=redis://localhost:6379
```

### macOS (Ollama + M1 Pro 24GB)
```env
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=deepseek-r1:14b
MARKET_DATA_MODE=live
REDIS_URL=redis://localhost:6379
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

### Analysis
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analysis/start` | POST | Start new analysis session |
| `/api/analysis/status/{session_id}` | GET | Get session status |
| `/api/analysis/state/{session_id}` | GET | Get full session state |
| `/api/analysis/sessions` | GET | List all active sessions |
| `/api/analysis/cancel/{session_id}` | POST | Cancel a session |

### Approval (HITL)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/approval/pending/{session_id}` | GET | Get pending proposal |
| `/api/approval/decide` | POST | Submit approval decision |

### WebSocket
| Endpoint | Protocol | Description |
|----------|----------|-------------|
| `/ws/session/{session_id}` | WS | Real-time session updates |
| `/ws/broadcast` | WS | System-wide broadcasts |

### Authentication (Not Yet Implemented)
| Endpoint | Method | Description | Status |
|----------|--------|-------------|--------|
| `/api/auth/login` | POST | User login | 501 |
| `/api/auth/register` | POST | User registration | 501 |
| `/api/auth/logout` | POST | User logout | 501 |
| `/api/auth/me` | GET | Current user profile | 501 |
| `/api/auth/refresh` | POST | Refresh access token | 501 |
| `/api/auth/api-keys` | POST/GET | API key management | 501 |

### System
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | API information |
| `/health` | GET | Health check (API, LLM, Redis) |
| `/docs` | GET | Swagger documentation (debug only) |

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

## Project Structure

```
JonberAITrading/
├── backend/
│   ├── app/                    # FastAPI application
│   │   ├── api/
│   │   │   ├── routes/         # API endpoints
│   │   │   │   ├── analysis.py
│   │   │   │   ├── approval.py
│   │   │   │   ├── auth.py     # Auth interface (placeholder)
│   │   │   │   └── websocket.py
│   │   │   └── schemas/        # Pydantic models
│   │   ├── config.py           # Settings
│   │   ├── dependencies.py     # DI providers
│   │   └── main.py             # Entry point
│   ├── agents/
│   │   ├── graph/
│   │   │   ├── nodes.py        # LangGraph nodes
│   │   │   ├── state.py        # State definitions
│   │   │   ├── trading_graph.py
│   │   │   └── redis_checkpointer.py
│   │   ├── tools/              # Agent tools
│   │   └── llm_provider.py     # LLM abstraction
│   ├── services/
│   │   └── redis_service.py    # Redis client
│   └── tests/                  # Pytest tests
├── frontend/
│   ├── src/
│   │   ├── api/                # API & WebSocket clients
│   │   ├── components/
│   │   │   ├── analysis/       # Analysis components
│   │   │   ├── approval/       # HITL approval UI
│   │   │   ├── chart/          # TradingView charts
│   │   │   ├── chat/           # Chat interface
│   │   │   ├── layout/         # Layout components
│   │   │   └── position/       # Position display
│   │   ├── store/              # Zustand state
│   │   └── types/              # TypeScript types
│   ├── tailwind.config.js
│   └── vite.config.ts
├── docker/                     # Docker configurations
├── data/mock/                  # Mock data for testing
├── environment.yml             # Conda environment
└── CLAUDE.md                   # AI assistant instructions
```

---

## Authentication Roadmap

Authentication is currently **not implemented**. The `/api/auth/*` endpoints return `501 Not Implemented`.

### Planned Implementation Phases

#### Phase 1: Basic JWT Authentication
- [ ] User registration with email verification
- [ ] Password hashing with bcrypt
- [ ] JWT token generation (RS256)
- [ ] Token refresh mechanism
- [ ] Session management with Redis

#### Phase 2: OAuth2 Integration
- [ ] Google OAuth2
- [ ] GitHub OAuth2
- [ ] Microsoft OAuth2

#### Phase 3: API Key Management
- [ ] API key generation for programmatic access
- [ ] Key rotation and expiration
- [ ] Rate limiting per key
- [ ] Scoped permissions

#### Phase 4: RBAC (Role-Based Access Control)
- [ ] Role definitions: Admin, Trader, Viewer
- [ ] Permission system
- [ ] Team/Organization support

### Security Considerations (Planned)
- Passwords stored with bcrypt (work factor 12)
- JWT signed with RS256 algorithm
- Refresh tokens stored in Redis with TTL
- Rate limiting on authentication endpoints
- Audit logging for all auth events
- HTTPS required in production

### Temporary Workaround
Until authentication is implemented:
1. Run in development mode (DEBUG=true)
2. API is open without authentication
3. Use network-level security (firewall, VPN)

---

## Tech Stack

### Backend
- Python 3.12
- FastAPI 0.115+
- LangChain 0.3+
- LangGraph 0.2+
- Pydantic 2.10+
- Redis 5.0+ (async client)

### Frontend
- React 18.3
- Vite 6.0
- TypeScript 5.7
- Zustand 5.0
- TailwindCSS 3.4
- Lightweight Charts 4.2 (TradingView)

### LLM
- vLLM (Windows/Linux with NVIDIA GPU)
- Ollama (All platforms)

### Infrastructure
- Redis 7.0+ (session persistence)
- Docker (optional deployment)

---

## Chart Features

The frontend includes TradingView Lightweight Charts with:

### Timeframes
- 1분봉 (1 Minute)
- 5분봉 (5 Minutes)
- 15분봉 (15 Minutes)
- 1시간봉 (1 Hour)
- 일봉 (Daily)
- 주봉 (Weekly)
- 월봉 (Monthly)

### Indicators
- 50일 이동평균선 (SMA 50)
- 200일 이동평균선 (SMA 200)
- 거래량 (Volume)

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
