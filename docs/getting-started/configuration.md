# Configuration Reference

상세 설정 가이드

---

## 환경 변수

### LLM 설정

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `LLM_PROVIDER` | LLM 제공자 (`ollama`, `vllm`) | `ollama` |
| `LLM_BASE_URL` | LLM API 엔드포인트 | `http://localhost:11434/v1` |
| `LLM_MODEL` | 모델 이름 | `deepseek-r1:14b` |
| `LLM_TEMPERATURE` | 생성 온도 (0.0-1.0) | `0.1` |
| `LLM_MAX_TOKENS` | 최대 토큰 수 | `4096` |

### Kiwoom API 설정

| 변수 | 설명 | 필수 |
|------|------|------|
| `KIWOOM_APP_KEY` | 앱 키 | Yes |
| `KIWOOM_SECRET_KEY` | 시크릿 키 | Yes |
| `KIWOOM_ACCOUNT_NO` | 계좌번호 | Yes |
| `KIWOOM_IS_MOCK` | 모의투자 여부 (`true`/`false`) | Yes |

!!! warning "실거래 주의"
    `KIWOOM_IS_MOCK=false` 설정 시 실제 매매가 실행됩니다.
    충분한 테스트 후 전환하세요.

### Upbit API 설정

| 변수 | 설명 | 필수 |
|------|------|------|
| `UPBIT_ACCESS_KEY` | Access Key | Yes |
| `UPBIT_SECRET_KEY` | Secret Key | Yes |

### Telegram 설정

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `TELEGRAM_BOT_TOKEN` | 봇 토큰 | - |
| `TELEGRAM_CHAT_ID` | 채팅 ID | - |
| `TELEGRAM_ENABLED` | 활성화 여부 | `false` |
| `TELEGRAM_NOTIFY_TRADE_ALERTS` | 거래 알림 | `true` |
| `TELEGRAM_NOTIFY_POSITION_UPDATES` | 포지션 알림 | `true` |
| `TELEGRAM_NOTIFY_ANALYSIS_COMPLETE` | 분석 완료 알림 | `true` |
| `TELEGRAM_NOTIFY_SYSTEM_STATUS` | 시스템 상태 알림 | `true` |

### 뉴스 API 설정

| 변수 | 설명 | 필수 |
|------|------|------|
| `NAVER_CLIENT_ID` | 네이버 API Client ID | No |
| `NAVER_CLIENT_SECRET` | 네이버 API Secret | No |

### 시스템 설정

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `MARKET_DATA_MODE` | 데이터 모드 (`live`, `mock`) | `live` |
| `ENVIRONMENT` | 환경 (`development`, `production`) | `development` |
| `DEBUG` | 디버그 모드 | `true` |
| `REDIS_URL` | Redis 연결 URL | - |

---

## 매매 설정

### 리스크 파라미터

```python
# backend/services/trading/models.py

DEFAULT_STOP_LOSS_PCT = 3.0      # 손절 비율 (%)
DEFAULT_TAKE_PROFIT_PCT = 5.0    # 익절 비율 (%)
MAX_POSITION_SIZE_PCT = 10.0     # 최대 포지션 크기 (%)
MAX_DAILY_TRADES = 10            # 일일 최대 거래 수
```

### 분석 설정

```python
# 동시 분석 세션 제한
MAX_CONCURRENT_SESSIONS = 3

# 분석 타임아웃 (초)
ANALYSIS_TIMEOUT = 300
```

---

## 모델 권장 사양

| VRAM/RAM | 모델 | 명령어 |
|----------|------|--------|
| 24GB+ | deepseek-r1:32b | `ollama pull deepseek-r1:32b` |
| 10-16GB | deepseek-r1:14b | `ollama pull deepseek-r1:14b` |
| 8GB | deepseek-r1:7b | `ollama pull deepseek-r1:7b` |

---

## Frontend 설정

### Vite 환경 변수

`frontend/.env`:

```env
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

### 테마 설정

TailwindCSS를 통해 다크/라이트 모드 지원

---

## 프로덕션 설정

### Backend

```bash
# Gunicorn으로 실행
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

### Frontend

```bash
# 프로덕션 빌드
npm run build

# 빌드 결과물 서빙
npm run preview
```

### Docker

```yaml
# docker-compose.yml
version: '3.8'
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    env_file:
      - .env

  frontend:
    build: ./frontend
    ports:
      - "80:80"
    depends_on:
      - backend
```
