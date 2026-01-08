# macOS Setup Guide

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

### 1.5 Install Ollama

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

Open 2 separate terminal windows:

```zsh
# Terminal 1: Backend
conda activate agentic-trading
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend
npm run dev
```

> **Note**: Ollama should already be running from Step 2. State is stored locally in SQLite (no Redis required).

## Step 7: Access Application

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

---

## Model Recommendations for Apple Silicon

| RAM | Model | Command |
|-----|-------|---------|
| 24GB+ (M1 Pro/Max/Ultra) | deepseek-r1:14b | `ollama pull deepseek-r1:14b` |
| 16GB (M1 Pro) | deepseek-r1:7b | `ollama pull deepseek-r1:7b` |
| 8GB (M1) | deepseek-r1:1.5b | `ollama pull deepseek-r1:1.5b` |

---

## Troubleshooting

### LLM Connection Failed

```zsh
# Check if Ollama is running
ollama list

# Restart Ollama
killall ollama
ollama serve &
```

### Slow Model Response

```zsh
# Check if using Metal acceleration
# Ollama should automatically use Metal on Apple Silicon
# If slow, try restarting Ollama
```

### Frontend Build Errors

```zsh
# Clear node_modules and reinstall
cd frontend
rm -rf node_modules package-lock.json
npm install
```

---

[Back to Main README](../../README.md)
