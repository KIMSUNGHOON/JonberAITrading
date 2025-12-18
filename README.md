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

## Step 1: Install Required Software

### 1.1 Install Git

```powershell
# Option 1: Download from https://git-scm.com/download/win
# Option 2: Using winget
winget install Git.Git

# Verify installation (restart terminal after install)
git --version
```

### 1.2 Install Node.js (includes npm)

```powershell
# Option 1: Download LTS from https://nodejs.org/
# Option 2: Using winget
winget install OpenJS.NodeJS.LTS

# Verify installation (restart terminal after install)
node --version   # Should show v18.x or higher
npm --version    # Should show 9.x or higher
```

### 1.3 Install Anaconda (Python)

```powershell
# Option 1: Download from https://www.anaconda.com/download
# Option 2: Using winget
winget install Anaconda.Anaconda3

# After installation, open "Anaconda Prompt" from Start Menu
# Verify installation
conda --version
python --version  # Should show 3.12.x
```

### 1.4 Install Docker Desktop (for Redis)

```powershell
# Option 1: Download from https://www.docker.com/products/docker-desktop
# Option 2: Using winget
winget install Docker.DockerDesktop

# After installation, restart Windows and start Docker Desktop
# Verify installation
docker --version
```

### 1.5 Install NVIDIA CUDA Toolkit (for GPU)

```powershell
# 1. Update NVIDIA Driver first
#    Download from: https://www.nvidia.com/drivers

# 2. Install CUDA Toolkit 12.1+
#    Download from: https://developer.nvidia.com/cuda-downloads
#    Select: Windows > x86_64 > 11/10 > exe (network)

# 3. Verify installation (restart terminal)
nvidia-smi          # Check GPU and driver version
nvcc --version      # Check CUDA version
```

## Step 2: Install Ollama (LLM Server)

```powershell
# Option 1: Download from https://ollama.ai
# Option 2: Using winget
winget install Ollama.Ollama

# Verify installation
ollama --version
```

## Step 3: Configure and Start Ollama

```powershell
# Set environment variables (optional but recommended)
# Run these BEFORE starting ollama serve

# Allow connections from backend (CORS)
$env:OLLAMA_ORIGINS="http://localhost:5173,http://localhost:8000"

# Enable flash attention for better performance (RTX 3090)
$env:OLLAMA_FLASH_ATTENTION="1"

# Set context length (default 4096)
$env:OLLAMA_CONTEXT_LENGTH="8192"

# Keep model loaded longer (default 5m)
$env:OLLAMA_KEEP_ALIVE="30m"

# Start Ollama server
ollama serve
```

> **Tip**: To make these permanent, add them to System Environment Variables via Control Panel.

## Step 4: Download LLM Model

```powershell
# Open a NEW terminal while ollama serve is running
# Download model (choose one based on your VRAM)

# RTX 3090 24GB - Best quality
ollama pull deepseek-r1:32b

# RTX 3080 10GB or less VRAM
ollama pull deepseek-r1:14b

# Verify model downloaded
ollama list
```

## Step 5: Start Redis

```powershell
# Using Docker (requires Docker Desktop running)
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Verify Redis is running
docker ps  # Should show redis container running

# If redis already exists but stopped:
docker start redis
```

## Step 6: Clone and Setup Project

```powershell
# Clone repository
git clone <repository-url>
cd JonberAITrading

# Create conda environment (run in Anaconda Prompt)
conda env create -f environment.yml
conda activate agentic-trading

# Setup environment variables
Copy-Item .env.example .env

# Edit .env file with notepad:
notepad .env

# Set these values in .env:
# LLM_PROVIDER=ollama
# LLM_BASE_URL=http://localhost:11434/v1
# LLM_MODEL=deepseek-r1:32b
```

## Step 7: Install Frontend Dependencies

```powershell
# Navigate to frontend directory
cd frontend

# Install npm packages
npm install

# Go back to project root
cd ..
```

## Step 8: Start Application

Open 3 separate terminals (PowerShell or Anaconda Prompt):

```powershell
# Terminal 1: Ollama (should already be running from Step 3)
# If not running, start with environment variables:
$env:OLLAMA_ORIGINS="http://localhost:5173,http://localhost:8000"
$env:OLLAMA_FLASH_ATTENTION="1"
ollama serve

# Terminal 2: Backend
conda activate agentic-trading
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 3: Frontend
cd frontend
npm run dev
```

## Step 9: Access Application

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

---

# Linux Setup

> **Recommended**: Use vLLM for best performance with NVIDIA GPUs.

## Prerequisites

- Ubuntu 20.04+ or similar Linux distribution
- NVIDIA GPU with CUDA support (RTX 3090 recommended)

## Step 1: Install Required Software

### 1.1 Install Git

```bash
sudo apt update
sudo apt install -y git

# Verify installation
git --version
```

### 1.2 Install Node.js (includes npm)

```bash
# Using NodeSource repository (recommended for latest LTS)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Verify installation
node --version   # Should show v20.x or higher
npm --version    # Should show 10.x or higher
```

### 1.3 Install Anaconda (Python)

```bash
# Download Anaconda installer
wget https://repo.anaconda.com/archive/Anaconda3-2024.10-1-Linux-x86_64.sh

# Run installer
bash Anaconda3-2024.10-1-Linux-x86_64.sh

# Follow prompts, accept license, use default location
# Restart terminal or run:
source ~/.bashrc

# Verify installation
conda --version
python --version  # Should show 3.12.x
```

## Step 2: Install CUDA Toolkit

```bash
# Check if GPU is recognized
nvidia-smi

# Install CUDA 12.1+ (Ubuntu 22.04 example)
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
sudo apt install -y cuda-toolkit-12-1

# Add CUDA to PATH (add to ~/.bashrc for persistence)
export PATH=/usr/local/cuda-12.1/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda-12.1/lib64:$LD_LIBRARY_PATH

# Verify
nvcc --version
```

## Step 3: Install Redis

```bash
sudo apt update
sudo apt install -y redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Verify
redis-cli ping
# Should return: PONG
```

## Step 4: Clone and Setup Project

```bash
# Clone repository
git clone <repository-url>
cd JonberAITrading

# Create conda environment
conda env create -f environment.yml
conda activate agentic-trading

# Setup environment variables
cp .env.example .env

# Edit .env file for Linux vLLM:
nano .env

# Change these values in .env:
# LLM_PROVIDER=vllm
# LLM_BASE_URL=http://localhost:8080/v1
# LLM_MODEL=deepseek-ai/DeepSeek-R1-Distill-Qwen-32B
```

## Step 5: Install Frontend Dependencies

```bash
# Navigate to frontend directory
cd frontend

# Install npm packages
npm install

# Go back to project root
cd ..
```

## Step 6: Install and Start vLLM

```bash
# Install vLLM (in conda environment)
conda activate agentic-trading
pip install vllm

# Start vLLM server (RTX 3090 24GB)
# This will download the model on first run (~17GB)
python -m vllm.entrypoints.openai.api_server \
    --model deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
    --quantization awq \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.90 \
    --host 0.0.0.0 \
    --port 8080

# Alternative: Smaller model for less VRAM (10-16GB)
# python -m vllm.entrypoints.openai.api_server \
#     --model deepseek-ai/DeepSeek-R1-Distill-Qwen-14B \
#     --quantization awq \
#     --max-model-len 8192 \
#     --gpu-memory-utilization 0.90 \
#     --port 8080
```

## Step 7: Start Application

Open 3 separate terminals:

```bash
# Terminal 1: vLLM (keep running from Step 6)
# Already running

# Terminal 2: Backend
conda activate agentic-trading
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 3: Frontend
cd frontend
npm run dev
```

## Step 8: Access Application

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

---

# macOS Setup

> **Note**: Use Ollama with Metal acceleration for Apple Silicon.

## Prerequisites

- macOS 12+ (Monterey or later)
- Apple Silicon (M1/M2/M3) or Intel Mac

## Step 1: Install Required Software

### 1.1 Install Homebrew (Package Manager)

```zsh
# Install Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Follow the instructions to add Homebrew to your PATH
# For Apple Silicon, run:
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"

# Verify installation
brew --version
```

### 1.2 Install Git

```zsh
# Git is usually pre-installed on macOS, if not:
brew install git

# Verify installation
git --version
```

### 1.3 Install Node.js (includes npm)

```zsh
brew install node

# Verify installation
node --version   # Should show v20.x or higher
npm --version    # Should show 10.x or higher
```

### 1.4 Install Anaconda (Python)

```zsh
brew install --cask anaconda

# Add Anaconda to PATH (add to ~/.zshrc for persistence)
export PATH="/opt/homebrew/anaconda3/bin:$PATH"

# Initialize conda
conda init zsh

# Restart terminal or run:
source ~/.zshrc

# Verify installation
conda --version
python --version  # Should show 3.12.x
```

### 1.5 Install Redis

```zsh
brew install redis
brew services start redis

# Verify Redis is running
redis-cli ping
# Should return: PONG
```

### 1.6 Install Ollama

```zsh
brew install ollama

# Verify installation
ollama --version
```

## Step 2: Configure and Start Ollama

```zsh
# Set environment variables (optional but recommended)
# Add to ~/.zshrc for persistence

# Allow connections from backend (CORS)
export OLLAMA_ORIGINS="http://localhost:5173,http://localhost:8000"

# Enable flash attention for better performance (Apple Silicon)
export OLLAMA_FLASH_ATTENTION="1"

# Set context length (default 4096)
export OLLAMA_CONTEXT_LENGTH="8192"

# Keep model loaded longer (default 5m)
export OLLAMA_KEEP_ALIVE="30m"

# Start Ollama server
ollama serve &
```

> **Tip**: Add these exports to `~/.zshrc` to make them permanent.

## Step 3: Download LLM Model

```zsh
# Download model (choose based on RAM)
# M1 Pro/Max 24GB+ - Best quality
ollama pull deepseek-r1:14b

# M1 8GB - Lighter model
ollama pull deepseek-r1:7b

# Verify model downloaded
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
nano .env

# Default values work for macOS:
# LLM_PROVIDER=ollama
# LLM_BASE_URL=http://localhost:11434/v1
# LLM_MODEL=deepseek-r1:14b
```

## Step 5: Install Frontend Dependencies

```zsh
# Navigate to frontend directory
cd frontend

# Install npm packages
npm install

# Go back to project root
cd ..
```

## Step 6: Start Application

Open 3 separate terminal windows:

```zsh
# Terminal 1: Ollama (should already be running from Step 2)
# If not running, start with environment variables:
export OLLAMA_ORIGINS="http://localhost:5173,http://localhost:8000"
export OLLAMA_FLASH_ATTENTION="1"
ollama serve

# Terminal 2: Backend
conda activate agentic-trading
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 3: Frontend
cd frontend
npm run dev
```

## Step 7: Access Application

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
