# Agentic AI Trading Application

AI-powered trading analysis system with autonomous multi-agent analysis and human-in-the-loop approval workflows.

## Features

- **Multi-Agent Analysis**: Technical, Fundamental, Sentiment, and Risk analysis
- **Human-in-the-Loop**: Trade proposals require human approval before execution
- **Real-time Streaming**: Live reasoning logs via WebSocket
- **Cross-Platform**: Supports Windows, Linux, and macOS

---

## Quick Start (Choose Your Platform)

| Platform | LLM Server | GPU Support |
|----------|------------|-------------|
| [Windows](#windows-setup) | Ollama (recommended) | NVIDIA CUDA |
| [Linux](#linux-setup) | vLLM (recommended) | NVIDIA CUDA |
| [macOS](#macos-setup) | Ollama | Apple Metal |

---

# Windows Setup

> **Note**: vLLM does not support Windows natively. Use **Ollama** (recommended) or **WSL2 + vLLM**.

## Prerequisites

- Windows 10/11
- NVIDIA GPU with CUDA support (RTX 3090 recommended)
- [Anaconda](https://www.anaconda.com/download) or Miniconda
- [Node.js 18+](https://nodejs.org/)
- [Git](https://git-scm.com/)

## Step 1: Install Ollama

```powershell
# Option 1: Download from https://ollama.ai
# Option 2: Using winget
winget install Ollama.Ollama
```

## Step 2: Download Model

```powershell
# Start Ollama (runs automatically after install)
ollama serve

# Download model (choose one based on your VRAM)
# RTX 3090 24GB - Best quality
ollama pull deepseek-r1:32b

# RTX 3080 10GB or less VRAM
ollama pull deepseek-r1:14b

# Verify model
ollama list
```

## Step 3: Install Redis (Choose One)

```powershell
# Option 1: Docker (Recommended)
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Option 2: WSL2
wsl --install -d Ubuntu
wsl -d Ubuntu -e bash -c "sudo apt update && sudo apt install -y redis-server && sudo service redis-server start"
```

## Step 4: Clone and Setup Project

```powershell
# Clone repository
git clone <repository-url>
cd JonberAITrading

# Create conda environment
conda env create -f environment.yml
conda activate agentic-trading

# Setup environment variables
Copy-Item .env.example .env

# Edit .env file - set these values:
# LLM_PROVIDER=ollama
# LLM_BASE_URL=http://localhost:11434/v1
# LLM_MODEL=deepseek-r1:32b
```

## Step 5: Start Application

```powershell
# Terminal 1: Backend
conda activate agentic-trading
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend
npm install
npm run dev
```

## Step 6: Access Application

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

---

# Linux Setup

> **Recommended**: Use vLLM for best performance with NVIDIA GPUs.

## Prerequisites

- Ubuntu 20.04+ or similar Linux distribution
- NVIDIA GPU with CUDA 12.1+ support
- Anaconda or Miniconda
- Node.js 18+
- Git

## Step 1: Install CUDA Toolkit

```bash
# Check GPU
nvidia-smi

# Install CUDA 12.1+ (Ubuntu example)
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
sudo apt install cuda-toolkit-12-1

# Verify
nvcc --version
```

## Step 2: Install Redis

```bash
sudo apt update
sudo apt install redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Verify
redis-cli ping
# Should return: PONG
```

## Step 3: Clone and Setup Project

```bash
# Clone repository
git clone <repository-url>
cd JonberAITrading

# Create conda environment
conda env create -f environment.yml
conda activate agentic-trading

# Setup environment variables
cp .env.example .env

# Edit .env file - default values work for Linux:
# LLM_PROVIDER=vllm
# LLM_BASE_URL=http://localhost:8080/v1
# LLM_MODEL=deepseek-ai/DeepSeek-R1-Distill-Qwen-32B
```

## Step 4: Install and Start vLLM

```bash
# Install vLLM
pip install vllm

# Start vLLM server (RTX 3090 24GB)
python -m vllm.entrypoints.openai.api_server \
    --model deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
    --quantization awq \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.90 \
    --host 0.0.0.0 \
    --port 8080

# Alternative: Smaller model for less VRAM
# python -m vllm.entrypoints.openai.api_server \
#     --model deepseek-ai/DeepSeek-R1-Distill-Qwen-14B \
#     --quantization awq \
#     --max-model-len 8192 \
#     --gpu-memory-utilization 0.90 \
#     --port 8080
```

## Step 5: Start Application

```bash
# Terminal 1: Backend (new terminal)
conda activate agentic-trading
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2: Frontend (new terminal)
cd frontend
npm install
npm run dev
```

## Step 6: Access Application

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

---

# macOS Setup

> **Note**: Use Ollama with Metal acceleration for Apple Silicon.

## Prerequisites

- macOS 12+ (Monterey or later)
- Apple Silicon (M1/M2/M3) or Intel Mac
- [Homebrew](https://brew.sh/)
- Node.js 18+

## Step 1: Install Homebrew (if not installed)

```zsh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

## Step 2: Install Dependencies

```zsh
# Install Anaconda
brew install --cask anaconda

# Install Node.js
brew install node

# Install Redis
brew install redis
brew services start redis

# Install Ollama
brew install ollama
```

## Step 3: Download Model

```zsh
# Start Ollama service
ollama serve &

# Download model (choose based on RAM)
# M1 Pro/Max 24GB+ - Best quality
ollama pull deepseek-r1:14b

# M1 8GB - Lighter model
ollama pull deepseek-r1:7b

# Verify
ollama list
```

## Step 4: Clone and Setup Project

```zsh
# Clone repository
git clone <repository-url>
cd JonberAITrading

# Create conda environment
conda env create -f environment.yml
conda activate agentic-trading

# Setup environment variables
cp .env.example .env

# Edit .env file:
# LLM_PROVIDER=ollama
# LLM_BASE_URL=http://localhost:11434/v1
# LLM_MODEL=deepseek-r1:14b
```

## Step 5: Start Application

```zsh
# Terminal 1: Backend
conda activate agentic-trading
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend
npm install
npm run dev
```

## Step 6: Access Application

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

---

# Architecture

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

# Model Recommendations

## By VRAM/RAM

| VRAM/RAM | Platform | Model | Command |
|----------|----------|-------|---------|
| 24GB+ | Linux | DeepSeek-R1-Distill-Qwen-32B | vLLM (AWQ) |
| 24GB+ | Windows/macOS | deepseek-r1:32b | `ollama pull deepseek-r1:32b` |
| 10-16GB | All | deepseek-r1:14b | `ollama pull deepseek-r1:14b` |
| 8GB | All | deepseek-r1:7b | `ollama pull deepseek-r1:7b` |

## Performance Benchmarks

| Model | AIME 2024 | MATH-500 | VRAM (4-bit) |
|-------|-----------|----------|--------------|
| Qwen-32B | 72.6% | 94.3% | ~17GB |
| Qwen-14B | 69.7% | 93.9% | ~8GB |
| Qwen-7B | 55.5% | 92.8% | ~4GB |

---

# Environment Configuration

## .env File Settings

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
REDIS_URL=redis://localhost:6379
ENVIRONMENT=development
DEBUG=true
```

---

# API Reference

## Analysis Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analysis/start` | POST | Start new analysis |
| `/api/analysis/status/{id}` | GET | Get session status |
| `/api/analysis/sessions` | GET | List all sessions |
| `/api/analysis/cancel/{id}` | POST | Cancel session |

## Approval Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/approval/pending/{id}` | GET | Get pending proposal |
| `/api/approval/decide` | POST | Submit decision |

## WebSocket

| Endpoint | Description |
|----------|-------------|
| `/ws/session/{id}` | Real-time session updates |

## System

| Endpoint | Description |
|----------|-------------|
| `/health` | Health check (API, LLM, Redis) |
| `/docs` | Swagger documentation |

---

# Testing

## Run Backend Tests

```bash
conda activate agentic-trading
cd backend
pytest -v
```

## Health Check

```bash
# Check all services
curl http://localhost:8000/health

# Expected response
{
  "status": "healthy",
  "services": {
    "api": "healthy",
    "llm": {"status": "healthy"},
    "redis": {"status": "healthy"}
  }
}
```

---

# Troubleshooting

## Common Issues

### LLM Connection Failed

```bash
# Check if Ollama is running
ollama list

# Restart Ollama
ollama serve
```

### Redis Connection Failed

```bash
# Check Redis status
redis-cli ping

# Windows (Docker)
docker start redis

# macOS
brew services restart redis

# Linux
sudo systemctl restart redis-server
```

### CUDA Not Available (Linux)

```bash
# Verify CUDA installation
nvcc --version
nvidia-smi

# Check PyTorch CUDA
python -c "import torch; print(torch.cuda.is_available())"
```

### Frontend Build Errors

```bash
# Clear node_modules and reinstall
cd frontend
rm -rf node_modules package-lock.json
npm install
```

---

# Project Structure

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
├── environment.yml             # Conda environment
└── README.md
```

---

# Tech Stack

| Layer | Technologies |
|-------|--------------|
| **Backend** | Python 3.12, FastAPI, LangGraph, Pydantic |
| **Frontend** | React 18, Vite, TypeScript, Zustand, TailwindCSS |
| **Charts** | TradingView Lightweight Charts |
| **LLM** | vLLM (Linux), Ollama (All platforms) |
| **Database** | Redis (session persistence) |

---

# Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `pytest -v`
5. Submit a pull request

---

# License

MIT License
