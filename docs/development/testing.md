# Testing Guide

테스트 가이드

---

## 개요

JonberAI Trading은 pytest를 사용하여 Backend를 테스트합니다.

---

## Backend 테스트

### 테스트 실행

```bash
cd backend

# 전체 테스트
pytest -v

# 특정 디렉토리
pytest tests/test_api/ -v
pytest tests/test_services/ -v

# 특정 파일
pytest tests/test_api/test_trading.py -v

# 특정 테스트
pytest tests/test_api/test_trading.py::test_start_trading -v

# 키워드로 필터
pytest -k "trading" -v
```

### 커버리지

```bash
# 커버리지 리포트
pytest --cov=app --cov=services --cov-report=html

# HTML 리포트 확인
open htmlcov/index.html
```

### 테스트 구조

```
backend/tests/
├── conftest.py              # 공통 fixtures
├── test_api/
│   ├── test_analysis.py     # 분석 API
│   ├── test_trading.py      # 트레이딩 API
│   ├── test_approval.py     # 승인 API
│   └── test_websocket.py    # WebSocket
├── test_services/
│   ├── test_trading/
│   │   ├── test_coordinator.py
│   │   ├── test_portfolio.py
│   │   └── test_risk_monitor.py
│   └── test_agent_chat/
│       ├── test_chat_room.py
│       └── test_coordinator.py
└── test_agents/
    ├── test_technical.py
    └── test_fundamental.py
```

---

## Fixtures

### 공통 Fixtures

```python
# conftest.py

import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    """FastAPI 테스트 클라이언트"""
    return TestClient(app)

@pytest.fixture
def mock_kiwoom():
    """Kiwoom API 모킹"""
    with patch('services.kiwoom.KiwoomClient') as mock:
        yield mock

@pytest.fixture
def sample_stock_data():
    """샘플 주식 데이터"""
    return {
        "ticker": "005930",
        "name": "삼성전자",
        "price": 72000,
        "volume": 1000000
    }
```

### 사용 예시

```python
def test_analyze_stock(client, sample_stock_data):
    response = client.post(
        "/api/kr-stocks/analyze",
        json={"stk_cd": sample_stock_data["ticker"]}
    )
    assert response.status_code == 200
```

---

## API 테스트

### REST API 테스트

```python
def test_trading_status(client):
    """트레이딩 상태 조회 테스트"""
    response = client.get("/api/trading/status")
    assert response.status_code == 200
    data = response.json()
    assert "mode" in data
    assert data["mode"] in ["active", "paused", "stopped"]

def test_start_trading(client):
    """트레이딩 시작 테스트"""
    response = client.post("/api/trading/start")
    assert response.status_code == 200
    assert response.json()["mode"] == "active"
```

### WebSocket 테스트

```python
from fastapi.testclient import TestClient

def test_websocket_connection(client):
    """WebSocket 연결 테스트"""
    with client.websocket_connect("/ws/trade-notifications") as ws:
        # 연결 메시지 확인
        data = ws.receive_json()
        assert data["type"] == "connected"

        # 핑-퐁 테스트
        ws.send_text("ping")
        response = ws.receive_text()
        assert response == "pong"
```

---

## 서비스 테스트

### Mocking

```python
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_execute_order():
    """주문 실행 테스트"""
    with patch('services.kiwoom.KiwoomClient') as mock_client:
        mock_client.return_value.execute_order = AsyncMock(
            return_value={"order_id": "12345", "status": "filled"}
        )

        result = await order_agent.execute(
            ticker="005930",
            action="BUY",
            quantity=10
        )

        assert result["status"] == "filled"
```

### 비동기 테스트

```python
import pytest

@pytest.mark.asyncio
async def test_risk_monitor():
    """리스크 모니터 테스트"""
    monitor = RiskMonitor()
    position = Position(
        ticker="005930",
        quantity=10,
        entry_price=72000,
        stop_loss=69000,
        take_profit=78000
    )

    # 손절 트리거 테스트
    result = await monitor.check_position(position, current_price=68000)
    assert result.triggered == True
    assert result.trigger_type == "stop_loss"
```

---

## 에이전트 테스트

### LLM 모킹

```python
@pytest.fixture
def mock_llm():
    """LLM 응답 모킹"""
    with patch('agents.llm_provider.get_llm') as mock:
        mock.return_value.ainvoke = AsyncMock(
            return_value=AIMessage(content=json.dumps({
                "signal": "BUY",
                "confidence": 0.75,
                "summary": "테스트 분석"
            }))
        )
        yield mock

def test_technical_analyst(mock_llm):
    """기술적 분석 에이전트 테스트"""
    result = technical_analyst.analyze({
        "ticker": "005930",
        "ohlcv": [...],
        "indicators": {...}
    })

    assert result["signal"] in ["BUY", "SELL", "HOLD"]
    assert 0 <= result["confidence"] <= 1
```

---

## 통합 테스트

### 전체 워크플로우 테스트

```python
@pytest.mark.integration
async def test_full_analysis_workflow(client, mock_kiwoom, mock_llm):
    """전체 분석 워크플로우 테스트"""
    # 1. 분석 시작
    response = client.post(
        "/api/kr-stocks/analyze",
        json={"stk_cd": "005930"}
    )
    session_id = response.json()["session_id"]

    # 2. 분석 완료 대기
    for _ in range(60):
        response = client.get(f"/api/kr-stocks/sessions/{session_id}")
        if response.json()["status"] == "awaiting_approval":
            break
        await asyncio.sleep(1)

    # 3. 승인
    response = client.post(
        "/api/approval/decide",
        json={"session_id": session_id, "decision": "approved"}
    )
    assert response.status_code == 200
```

---

## Frontend 테스트

### 타입 체크

```bash
cd frontend
npx tsc --noEmit
```

### 린트

```bash
npm run lint
npm run lint:fix  # 자동 수정
```

### 빌드 테스트

```bash
npm run build
```

---

## CI/CD

### GitHub Actions (예시)

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov pytest-asyncio

      - name: Run tests
        run: |
          cd backend
          pytest -v --cov=app --cov=services
```

---

## 베스트 프랙티스

1. **독립적인 테스트**: 각 테스트는 독립적으로 실행 가능해야 함
2. **Mocking**: 외부 API는 항상 모킹
3. **Fixtures 활용**: 공통 설정은 fixtures로 분리
4. **명확한 이름**: 테스트 이름으로 목적 파악 가능하도록
5. **커버리지 유지**: 최소 80% 커버리지 목표
