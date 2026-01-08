# Contributing Guide

JonberAI Trading 기여 가이드

---

## 개요

JonberAI Trading 프로젝트에 기여해 주셔서 감사합니다. 이 문서는 기여 방법을 안내합니다.

---

## 개발 환경 설정

### 1. Fork & Clone

```bash
# Fork 후 클론
git clone https://github.com/YOUR_USERNAME/JonberAITrading.git
cd JonberAITrading
```

### 2. 환경 설정

```bash
# Conda 환경
conda env create -f environment.yml
conda activate agentic-trading

# Frontend
cd frontend
npm install
```

### 3. 브랜치 생성

```bash
git checkout -b feature/your-feature-name
```

---

## 코드 스타일

### Python

- **Type Hints**: 모든 함수에 타입 힌트 사용
- **Pydantic**: 데이터 모델에 Pydantic 사용
- **Async/Await**: 비동기 함수 사용
- **Docstrings**: 모든 public 함수에 docstring

```python
async def analyze_stock(
    ticker: str,
    include_news: bool = True
) -> AnalysisResult:
    """
    주식 분석을 수행합니다.

    Args:
        ticker: 종목 코드
        include_news: 뉴스 분석 포함 여부

    Returns:
        AnalysisResult: 분석 결과
    """
    ...
```

### TypeScript

- **Strict Mode**: TypeScript strict 모드 사용
- **Functional Components**: 함수형 컴포넌트 + Hooks
- **Named Exports**: 기본적으로 named export 사용

```typescript
interface AnalysisProps {
  ticker: string;
  onComplete?: (result: AnalysisResult) => void;
}

export function AnalysisWidget({ ticker, onComplete }: AnalysisProps) {
  // ...
}
```

---

## 커밋 규칙

### 커밋 메시지 형식

```
<type>: <subject>

<body>

<footer>
```

### Type 종류

| Type | 설명 |
|------|------|
| `feat` | 새로운 기능 |
| `fix` | 버그 수정 |
| `docs` | 문서 변경 |
| `style` | 코드 포맷팅 |
| `refactor` | 리팩토링 |
| `test` | 테스트 추가/수정 |
| `chore` | 빌드/설정 변경 |

### 예시

```
feat: Add WebSocket trade notification system

- Add TradeNotificationManager for subscriber management
- Add /ws/trade-notifications endpoint
- Add useTradeNotifications React hook
- Add TradeNotificationToast component

Closes #123
```

---

## Pull Request

### PR 생성 전 체크리스트

- [ ] 테스트 통과 (`pytest -v`)
- [ ] 타입 체크 통과 (`npx tsc --noEmit`)
- [ ] 린트 통과 (`npm run lint`)
- [ ] 문서 업데이트 (필요시)
- [ ] WORK_STATUS.md 업데이트

### PR 템플릿

```markdown
## Summary
<!-- 변경 사항 요약 (1-3줄) -->

## Changes
<!-- 상세 변경 내용 -->
-
-

## Test Plan
<!-- 테스트 방법 -->
- [ ] Unit tests pass
- [ ] Manual testing completed

## Screenshots
<!-- UI 변경 시 스크린샷 -->
```

---

## 테스트

### Backend 테스트

```bash
cd backend
pytest -v                    # 전체 테스트
pytest tests/test_api/ -v    # API 테스트만
pytest --cov=app --cov=services  # 커버리지
```

### Frontend 테스트

```bash
cd frontend
npm run lint      # 린트
npx tsc --noEmit  # 타입 체크
npm run build     # 빌드 테스트
```

---

## 이슈 보고

### 버그 리포트

```markdown
## Bug Description
<!-- 버그 설명 -->

## Steps to Reproduce
1.
2.
3.

## Expected Behavior
<!-- 예상 동작 -->

## Actual Behavior
<!-- 실제 동작 -->

## Environment
- OS:
- Python:
- Node:
```

### 기능 요청

```markdown
## Feature Description
<!-- 기능 설명 -->

## Use Case
<!-- 사용 사례 -->

## Proposed Solution
<!-- 제안 솔루션 -->
```

---

## 프로젝트 구조

```
JonberAITrading/
├── backend/
│   ├── app/              # FastAPI 앱
│   ├── agents/           # LangGraph 에이전트
│   ├── services/         # 비즈니스 로직
│   └── tests/            # 테스트
├── frontend/
│   ├── src/
│   │   ├── components/   # React 컴포넌트
│   │   ├── hooks/        # Custom hooks
│   │   ├── store/        # Zustand store
│   │   └── api/          # API 클라이언트
│   └── ...
├── docs/                 # 문서
└── ...
```

---

## 문의

- GitHub Issues: 버그 리포트, 기능 요청
- Discussions: 일반 질문, 아이디어

---

감사합니다!
