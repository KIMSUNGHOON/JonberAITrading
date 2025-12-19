# Development TodoList - Agentic AI Trading Application

> Last Updated: 2025-12-19

---

## Priority Legend
- **P0**: Critical - Must have for MVP
- **P1**: High - Important for user experience
- **P2**: Medium - Nice to have
- **P3**: Low - Future enhancement

---

## 1. Multi-Ticker Simultaneous Analysis [P1]

현재 한 번에 하나의 티커만 분석 가능. 여러 티커를 동시에 분석할 수 있도록 개선 필요.

### Backend Tasks
- [ ] `POST /api/analysis/start` 엔드포인트 수정 - 여러 티커 배열 지원
- [ ] 세션 매니저 병렬 처리 지원
- [ ] 여러 WebSocket 연결 동시 관리

### Frontend Tasks
- [ ] TickerInput 컴포넌트 수정 - 콤마 구분 다중 입력 지원
- [ ] 사이드바에 활성 세션 목록 표시
- [ ] 세션 간 전환 UI
- [ ] 각 세션별 상태 표시 (running, awaiting_approval 등)

### Store Changes
- [ ] `activeSessions: Map<sessionId, SessionState>` 형태로 변경
- [ ] 현재 선택된 세션 추적: `selectedSessionId`
- [ ] 각 세션별 독립적인 WebSocket 연결 관리

---

## 2. Real-Time Agent Trading System [P0]

AI에게 트레이딩을 위임할 때 에이전트들이 실시간으로 대화하고 포지션을 관리하는 기능.

> 상세 명세: [FEATURE_SPEC_REALTIME_AGENT_TRADING.md](docs/FEATURE_SPEC_REALTIME_AGENT_TRADING.md)

### Phase 1: Foundation (2-3 weeks)
- [ ] Redis PubSub 기반 AgentMessageBus 구현
- [ ] AgentMessage 데이터 모델 정의
- [ ] TradingState에 agent_messages 필드 추가
- [ ] 노드 간 기본 메시지 전송 구현
- [ ] WebSocket을 통한 에이전트 메시지 스트리밍

### Phase 2: Decision Protocol (2 weeks)
- [ ] Proposal 생성 로직 구현
- [ ] 투표 메커니즘 구현 (approve/reject/abstain)
- [ ] Risk Agent 거부권 구현
- [ ] AgentOrchestrator 서비스 생성
- [ ] 결정 타임아웃 처리

### Phase 3: Market Monitoring (2 weeks)
- [ ] MarketMonitor 서비스 구현
- [ ] 가격 알림 트리거 추가
- [ ] 뉴스 피드 모니터링 연동
- [ ] 이벤트 기반 에이전트 활성화

### Phase 4: Position Management (2 weeks)
- [ ] PositionManager 서비스 구현
- [ ] Stop-loss/Take-profit 자동 실행
- [ ] 포지션 추적 데이터베이스 생성
- [ ] P&L 계산 로직

### Phase 5: Frontend UI (2-3 weeks)
- [ ] AgentChatPanel 컴포넌트 개발
- [ ] AutoTradingControl 패널 생성
- [ ] PositionsDashboard 구현
- [ ] 알림 시스템 추가
- [ ] 모바일 반응형 디자인

### Phase 6: Testing & Polish (1-2 weeks)
- [ ] 통합 테스트
- [ ] 실시간 업데이트 로드 테스트
- [ ] 보안 감사
- [ ] 문서화
- [ ] 사용자 수용 테스트

---

## 3. UI/UX Improvements [P1]

### Completed ✅
- [x] 반응형 레이아웃 (뷰포트 맞춤)
- [x] ReasoningLog 자동 접기
- [x] Approval Dialog Cancel 옵션
- [x] Ticker History 사이드바
- [x] Markdown 렌더링 (Rationale)
- [x] Re-analyze 버튼 (Reject → Re-analyze)

### Pending
- [ ] 다크/라이트 테마 전환
- [ ] 차트 인디케이터 커스터마이징
- [ ] 키보드 단축키 지원
- [ ] 분석 진행률 표시 개선 (WorkflowProgress)
- [ ] 에러 토스트 알림
- [ ] 로딩 스켈레톤 UI

---

## 4. Backend Enhancements [P2]

### API Improvements
- [ ] GraphQL 엔드포인트 추가 (선택적)
- [ ] Rate limiting 구현
- [ ] API 버전 관리 (/v1/, /v2/)
- [ ] 배치 분석 엔드포인트

### Data & Storage
- [ ] 분석 히스토리 영구 저장
- [ ] 사용자 설정 저장
- [ ] 분석 결과 캐싱 (Redis)
- [ ] 데이터 내보내기 (CSV, JSON)

### Performance
- [ ] 분석 노드 병렬 실행 (현재 순차)
- [ ] LLM 응답 캐싱
- [ ] Connection pooling 최적화
- [ ] 벤치마킹 및 프로파일링

---

## 5. Security & Compliance [P1]

- [ ] 사용자 인증 시스템 (JWT)
- [ ] API 키 관리
- [ ] 거래 감사 로그
- [ ] 위험 공시 동의 플로우
- [ ] HTTPS 강제
- [ ] 입력 검증 강화

---

## 6. Testing [P2]

### Backend Tests
- [ ] 단위 테스트 커버리지 80% 이상
- [ ] 통합 테스트 (API 엔드포인트)
- [ ] LLM 응답 모킹
- [ ] WebSocket 테스트

### Frontend Tests
- [ ] Vitest 설정
- [ ] 컴포넌트 단위 테스트
- [ ] E2E 테스트 (Playwright)
- [ ] 시각적 회귀 테스트

---

## 7. DevOps & Deployment [P2]

- [ ] Docker Compose 개선 (GPU 지원)
- [ ] CI/CD 파이프라인 (GitHub Actions)
- [ ] 환경별 설정 분리 (dev/staging/prod)
- [ ] 헬스체크 대시보드
- [ ] 로그 수집 (ELK Stack)
- [ ] 모니터링 (Prometheus + Grafana)

---

## 8. Documentation [P2]

### Completed ✅
- [x] README.md 개선 (overview)
- [x] OS별 설치 가이드 분리
- [x] 실시간 에이전트 트레이딩 기능 명세

### Pending
- [ ] API 문서 자동 생성 (OpenAPI → Postman)
- [ ] 개발자 가이드
- [ ] 아키텍처 다이어그램
- [ ] 기여 가이드라인
- [ ] 변경 로그 (CHANGELOG.md)

---

## 9. Future Enhancements [P3]

- [ ] 다중 자산 포트폴리오 관리
- [ ] 커스텀 트레이딩 전략 (모멘텀, 평균회귀)
- [ ] 백테스팅 기능
- [ ] 소셜 트레이딩 (성공적인 설정 팔로우)
- [ ] 고급 리스크 모델 (VaR, 스트레스 테스트)
- [ ] 다중 브로커 연동
- [ ] 모바일 앱 (React Native)

---

## Immediate Next Steps (권장 순서)

1. **Multi-Ticker Analysis** - 사용자 편의성 즉시 개선
2. **Real-Time Agent Trading Phase 1** - 핵심 기능 기반 구축
3. **Security (인증)** - 프로덕션 준비
4. **Testing** - 안정성 확보
5. **Real-Time Agent Trading Phase 2-6** - 전체 기능 완성

---

## Notes

- 각 작업 완료 시 체크박스 업데이트
- 새로운 요구사항 발생 시 해당 섹션에 추가
- 우선순위 변경 시 문서 업데이트
