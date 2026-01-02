# Quick Start Guide

5분 안에 JonberAI Trading 시작하기

---

## 1. 서버 실행

### LLM 서버

```bash
# Ollama (Windows/macOS)
ollama serve

# vLLM (Linux)
python -m vllm.entrypoints.openai.api_server \
  --model deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
  --port 8080
```

### Backend 서버

```bash
conda activate agentic-trading
cd backend
uvicorn app.main:app --reload --port 8000
```

### Frontend 서버

```bash
cd frontend
npm run dev
```

---

## 2. 분석 실행

### Web UI 사용

1. `http://localhost:5173` 접속
2. 좌측 사이드바에서 **Analysis** 선택
3. 종목 코드 입력 (예: `005930` - 삼성전자)
4. **Analyze** 버튼 클릭
5. 실시간 분석 로그 확인
6. 분석 완료 시 **Approve/Reject** 결정

### API 사용

```bash
# 분석 시작
curl -X POST http://localhost:8000/api/kr-stocks/analyze \
  -H "Content-Type: application/json" \
  -d '{"stk_cd": "005930"}'

# 세션 상태 확인
curl http://localhost:8000/api/kr-stocks/sessions
```

---

## 3. 자동매매 설정

### Trading Dashboard

1. 좌측 사이드바에서 **Auto Trading** 선택
2. **Start Trading** 버튼으로 시스템 활성화
3. 분석 결과 승인 시 자동으로 Trade Queue에 추가
4. Trade Queue에서 실행 대기 중인 주문 확인

### 주문 흐름

```
분석 완료 → HITL 승인 → Trade Queue → 장 시작 시 실행
```

---

## 4. 알림 설정

### Telegram 알림

1. [@BotFather](https://t.me/BotFather)에서 봇 생성
2. Bot Token 획득
3. 봇과 대화 시작 후 Chat ID 확인
4. `.env` 파일에 설정:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TELEGRAM_ENABLED=true
```

### WebSocket 알림

Frontend에서 자동으로 WebSocket 연결되어 실시간 알림 표시

---

## 5. 주요 화면

### Analysis Dashboard

- 종목 분석 시작
- 실시간 분석 로그
- Sub-Agent 분석 결과
- 매매 제안 승인/거부

### Trading Dashboard

- 시스템 상태 (Active/Paused/Stopped)
- Trade Queue (대기 중인 주문)
- 포지션 현황
- 손절/익절 설정

### Agent Chat

- Agent 간 토론 세션
- 실시간 메시지
- 투표 결과
- 합의 기반 의사결정

---

## 다음 단계

- [Configuration](configuration.md): 상세 설정
- [Analysis Guide](../user-guide/analysis.md): 분석 기능 상세
- [Trading Guide](../user-guide/trading.md): 자동매매 상세
