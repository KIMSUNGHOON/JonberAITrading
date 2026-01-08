# JonberAI Trading

AI 기반 자율 주식/코인 매매 시스템

---

## 개요

JonberAI Trading은 다중 AI 에이전트를 활용한 자동매매 시스템입니다. 기술적 분석, 펀더멘털 분석, 감성 분석, 리스크 평가를 병렬로 수행하고, Human-in-the-Loop (HITL) 워크플로우를 통해 안전한 매매를 지원합니다.

### 핵심 기능

| 기능 | 설명 |
|------|------|
| **다중 에이전트 분석** | Technical, Fundamental, Sentiment, Risk 4개 전문 에이전트 병렬 분석 |
| **Human-in-the-Loop** | 모든 매매 결정은 사용자 승인 후 실행 |
| **Agent Group Chat** | 에이전트 간 토론 및 합의 기반 의사결정 |
| **실시간 알림** | Telegram + WebSocket 실시간 체결/포지션 알림 |
| **자동 손절/익절** | Stop-Loss, Take-Profit 자동 실행 |
| **크로스 플랫폼** | Windows, Linux, macOS 지원 |

---

## 지원 시장

| 시장 | 거래소/API | 상태 |
|------|-----------|------|
| **한국 주식** | Kiwoom OpenAPI+ | 지원 (모의투자/실거래) |
| **암호화폐** | Upbit | 지원 |
| ~~미국 주식~~ | - | 미지원 |

---

## 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (React)                        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐│
│  │ Analysis    │ │ Trading     │ │  Agent Chat             ││
│  │ Dashboard   │ │ Dashboard   │ │  Dashboard              ││
│  └─────────────┘ └─────────────┘ └─────────────────────────┘│
└────────────────────────┬────────────────────────────────────┘
                         │ WebSocket / REST API
┌────────────────────────▼────────────────────────────────────┐
│                    Backend (FastAPI)                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              LangGraph Agent Workflow                 │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │   │
│  │  │Technical │ │Fundament.│ │Sentiment │ │  Risk   │ │   │
│  │  │ Analyst  │ │ Analyst  │ │ Analyst  │ │Assessor │ │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬────┘ │   │
│  │       └────────────┴────────────┴────────────┘      │   │
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
│    Ollama (Windows/macOS) │ vLLM (Linux/CUDA)               │
└─────────────────────────────────────────────────────────────┘
```

---

## 빠른 시작

### 1. 환경 설정

=== "Windows"

    ```powershell
    # Anaconda 환경 생성
    conda env create -f environment.yml
    conda activate agentic-trading

    # Ollama 설치 및 모델 다운로드
    winget install Ollama.Ollama
    ollama serve
    ollama pull deepseek-r1:14b
    ```

=== "macOS"

    ```zsh
    # Anaconda 환경 생성
    conda env create -f environment.yml
    conda activate agentic-trading

    # Ollama 설치 및 모델 다운로드
    brew install ollama
    ollama serve
    ollama pull deepseek-r1:14b
    ```

=== "Linux"

    ```bash
    # Anaconda 환경 생성
    conda env create -f environment.yml
    conda activate agentic-trading

    # vLLM 설치 (CUDA 필요)
    pip install vllm
    ```

### 2. 서버 실행

```bash
# Backend
cd backend
uvicorn app.main:app --reload --port 8000

# Frontend (새 터미널)
cd frontend
npm install
npm run dev
```

### 3. 접속

브라우저에서 `http://localhost:5173` 접속

---

## 문서 구조

- **[Getting Started](getting-started/installation.md)**: 설치 및 설정 가이드
- **[Architecture](architecture/overview.md)**: 시스템 아키텍처 상세
- **[User Guide](user-guide/analysis.md)**: 사용자 가이드
- **[API Reference](api/overview.md)**: API 문서
- **[Development](development/contributing.md)**: 개발 가이드

---

## 기술 스택

| Layer | Technologies |
|-------|--------------|
| **Backend** | Python 3.12, FastAPI, LangGraph, Pydantic |
| **Frontend** | React 18, Vite, TypeScript, Zustand, TailwindCSS |
| **Charts** | TradingView Lightweight Charts |
| **LLM** | vLLM (Linux), Ollama (All platforms) |
| **Database** | SQLite (embedded) |
| **Messaging** | WebSocket, Telegram Bot API |

---

## 라이선스

MIT License
