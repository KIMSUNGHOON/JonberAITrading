# Windows Setup Guide

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

### 1.4 Install NVIDIA CUDA Toolkit (for GPU)

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

## Step 5: Clone and Setup Project

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

## Step 6: Install Frontend Dependencies

```powershell
# Navigate to frontend directory
cd frontend

# Install npm packages
npm install

# Go back to project root
cd ..
```

## Step 7: Start Application

Open 2 separate terminals (PowerShell or Anaconda Prompt):

```powershell
# Terminal 1: Backend
conda activate agentic-trading
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend
npm run dev
```

> **Note**: Ollama should already be running from Step 3. State is stored locally in SQLite (no Redis required).

## Step 8: Access Application

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

---

## Troubleshooting

### LLM Connection Failed

```bash
# Check if Ollama is running
ollama list

# Restart Ollama
ollama serve
```

### Frontend Build Errors

```powershell
# Clear node_modules and reinstall
cd frontend
Remove-Item -Recurse -Force node_modules
Remove-Item package-lock.json
npm install
```

---

[Back to Main README](../../README.md)
