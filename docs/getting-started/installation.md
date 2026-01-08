# Installation Guide

JonberAI Trading 설치 가이드

---

## 시스템 요구사항

### 최소 사양

| 구성요소 | 최소 사양 |
|----------|-----------|
| **CPU** | 4 cores |
| **RAM** | 16GB |
| **GPU VRAM** | 8GB (선택) |
| **Storage** | 20GB |
| **Python** | 3.12+ |
| **Node.js** | 18+ |

### 권장 사양

| 구성요소 | 권장 사양 |
|----------|-----------|
| **CPU** | 8+ cores |
| **RAM** | 24GB+ |
| **GPU VRAM** | 24GB (RTX 3090/4090) |
| **Storage** | 50GB SSD |

---

## 플랫폼별 설치

=== "Windows"

    ### 1. 사전 요구사항

    - [Anaconda](https://www.anaconda.com/download) 설치
    - [Node.js 18+](https://nodejs.org/) 설치
    - [Git](https://git-scm.com/downloads) 설치

    ### 2. 저장소 클론

    ```powershell
    git clone https://github.com/KIMSUNGHOON/JonberAITrading.git
    cd JonberAITrading
    ```

    ### 3. Python 환경 설정

    ```powershell
    # Conda 환경 생성
    conda env create -f environment.yml
    conda activate agentic-trading

    # 또는 pip 사용
    python -m venv venv
    .\venv\Scripts\activate
    pip install -r requirements.txt
    ```

    ### 4. LLM 서버 설치 (Ollama)

    ```powershell
    # Ollama 설치
    winget install Ollama.Ollama

    # 모델 다운로드
    ollama serve  # 새 터미널에서 실행
    ollama pull deepseek-r1:14b  # 10-16GB VRAM
    # 또는
    ollama pull deepseek-r1:32b  # 24GB+ VRAM
    ```

    ### 5. Frontend 설정

    ```powershell
    cd frontend
    npm install
    ```

=== "macOS"

    ### 1. 사전 요구사항

    - [Homebrew](https://brew.sh/) 설치
    - Anaconda 설치: `brew install --cask anaconda`
    - Node.js 설치: `brew install node`

    ### 2. 저장소 클론

    ```zsh
    git clone https://github.com/KIMSUNGHOON/JonberAITrading.git
    cd JonberAITrading
    ```

    ### 3. Python 환경 설정

    ```zsh
    conda env create -f environment.yml
    conda activate agentic-trading
    ```

    ### 4. LLM 서버 설치 (Ollama)

    ```zsh
    brew install ollama
    ollama serve &
    ollama pull deepseek-r1:14b
    ```

    ### 5. Frontend 설정

    ```zsh
    cd frontend
    npm install
    ```

=== "Linux"

    ### 1. 사전 요구사항

    - Anaconda 설치
    - Node.js 18+ 설치
    - NVIDIA Driver + CUDA (GPU 사용 시)

    ### 2. 저장소 클론

    ```bash
    git clone https://github.com/KIMSUNGHOON/JonberAITrading.git
    cd JonberAITrading
    ```

    ### 3. Python 환경 설정

    ```bash
    conda env create -f environment.yml
    conda activate agentic-trading
    ```

    ### 4. LLM 서버 설치 (vLLM - 권장)

    ```bash
    pip install vllm

    # 서버 실행 (RTX 3090 24GB 기준)
    python -m vllm.entrypoints.openai.api_server \
      --model deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
      --quantization awq \
      --max-model-len 4096 \
      --gpu-memory-utilization 0.90 \
      --port 8080
    ```

    ### 5. Frontend 설정

    ```bash
    cd frontend
    npm install
    ```

---

## 환경 변수 설정

`.env` 파일을 프로젝트 루트에 생성:

```env
# === LLM Configuration ===
LLM_PROVIDER=ollama          # ollama 또는 vllm
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=deepseek-r1:14b

# === Kiwoom API (한국 주식) ===
KIWOOM_APP_KEY=your_app_key
KIWOOM_SECRET_KEY=your_secret_key
KIWOOM_ACCOUNT_NO=your_account_number
KIWOOM_IS_MOCK=true          # true: 모의투자, false: 실거래

# === Upbit API (암호화폐) ===
UPBIT_ACCESS_KEY=your_access_key
UPBIT_SECRET_KEY=your_secret_key

# === Telegram 알림 ===
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TELEGRAM_ENABLED=true

# === News API ===
NAVER_CLIENT_ID=your_client_id
NAVER_CLIENT_SECRET=your_client_secret

# === Other Settings ===
MARKET_DATA_MODE=live        # live 또는 mock
ENVIRONMENT=development
DEBUG=true
```

---

## 설치 확인

### Backend 테스트

```bash
cd backend
pytest -v
```

### 서버 실행

```bash
# Backend (터미널 1)
cd backend
uvicorn app.main:app --reload --port 8000

# Frontend (터미널 2)
cd frontend
npm run dev
```

### 접속 확인

- Frontend: `http://localhost:5173`
- API Docs: `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/health`

---

## 문제 해결

### LLM 연결 실패

```bash
# Ollama 상태 확인
curl http://localhost:11434/api/version

# 모델 목록 확인
ollama list
```

### CUDA 오류 (Linux)

```bash
# CUDA 버전 확인
nvidia-smi

# PyTorch CUDA 확인
python -c "import torch; print(torch.cuda.is_available())"
```

### 포트 충돌

```bash
# 포트 사용 확인
lsof -i :8000
lsof -i :5173

# 프로세스 종료
kill -9 <PID>
```

---

## 다음 단계

- [Quick Start](quick-start.md): 빠른 시작 가이드
- [Configuration](configuration.md): 상세 설정 가이드
