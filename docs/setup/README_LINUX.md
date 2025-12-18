# Linux Setup Guide

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

# Edit .env file for Linux vLLM:
nano .env

# Change these values in .env:
# LLM_PROVIDER=vllm
# LLM_BASE_URL=http://localhost:8080/v1
# LLM_MODEL=deepseek-ai/DeepSeek-R1-Distill-Qwen-32B
```

## Step 4: Install Frontend Dependencies

```bash
# Navigate to frontend directory
cd frontend

# Install npm packages
npm install

# Go back to project root
cd ..
```

## Step 5: Install and Start vLLM

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

## Step 6: Start Application

Open 3 separate terminals:

```bash
# Terminal 1: vLLM (keep running from Step 5)
# Already running

# Terminal 2: Backend
conda activate agentic-trading
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 3: Frontend
cd frontend
npm run dev
```

> **Note**: State is stored locally in SQLite (no Redis required).

## Step 7: Access Application

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

---

## Alternative: Using Ollama on Linux

If you prefer Ollama over vLLM:

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama
ollama serve &

# Pull model
ollama pull deepseek-r1:32b

# Update .env
# LLM_PROVIDER=ollama
# LLM_BASE_URL=http://localhost:11434/v1
# LLM_MODEL=deepseek-r1:32b
```

---

## Troubleshooting

### CUDA Not Available

```bash
# Verify CUDA installation
nvcc --version
nvidia-smi

# Check PyTorch CUDA
python -c "import torch; print(torch.cuda.is_available())"
```

### vLLM Out of Memory

```bash
# Try smaller model or reduce memory utilization
python -m vllm.entrypoints.openai.api_server \
    --model deepseek-ai/DeepSeek-R1-Distill-Qwen-14B \
    --quantization awq \
    --max-model-len 2048 \
    --gpu-memory-utilization 0.85 \
    --port 8080
```

### Frontend Build Errors

```bash
# Clear node_modules and reinstall
cd frontend
rm -rf node_modules package-lock.json
npm install
```

---

[Back to Main README](../../README.md)
