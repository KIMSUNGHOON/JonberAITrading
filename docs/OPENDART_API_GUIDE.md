# OpenDART API 개발 가이드

> 금융감독원 전자공시시스템 (DART) API를 활용한 재무정보 연동 가이드

## 개요

- **Base URL**: `https://opendart.fss.or.kr/api`
- **인코딩**: UTF-8
- **응답 포맷**: JSON, XML
- **일일 요청 제한**: 약 20,000건

---

## 1. API 목록

### 1.1 공시정보 (DS001)

| API | 엔드포인트 | 설명 |
|-----|----------|------|
| 고유번호 다운로드 | `/corpCode.xml` | 종목코드 → 기업코드 매핑 (ZIP) |
| 기업개황 | `/company.json` | 기업 기본정보 조회 |

### 1.2 정기보고서 재무정보 (DS003)

| API | 엔드포인트 | 설명 |
|-----|----------|------|
| 단일회사 주요계정 | `/fnlttSinglAcnt.json` | 매출, 영업이익 등 핵심 계정 |
| 다중회사 주요계정 | `/fnlttMultiAcnt.json` | 여러 회사 비교 분석 |
| 단일회사 전체 재무제표 | `/fnlttSinglAcntAll.json` | BS, IS 전체 항목 (XBRL) |
| 단일회사 주요 재무지표 | `/fnlttSinglIndx.json` | PER, ROE 등 재무비율 |
| 다중회사 주요 재무지표 | `/fnlttMultiIndx.json` | 여러 회사 재무비율 비교 |

---

## 2. 공통 요청 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|:----:|------|
| `crtfc_key` | STRING(40) | Y | API 인증키 (40자리) |
| `corp_code` | STRING(8) | Y | 기업 고유번호 (8자리) |
| `bsns_year` | STRING(4) | Y | 사업연도 (2015년 이후) |
| `reprt_code` | STRING(5) | Y | 보고서 코드 |

### 보고서 코드 (reprt_code)

| 코드 | 보고서 유형 |
|------|-----------|
| 11011 | 사업보고서 (연간) |
| 11012 | 반기보고서 |
| 11013 | 1분기보고서 |
| 11014 | 3분기보고서 |

### 재무제표 구분 (fs_div)

| 코드 | 설명 |
|------|------|
| CFS | 연결재무제표 |
| OFS | 개별재무제표 |

---

## 3. API 상세

### 3.1 고유번호 다운로드

종목코드(stock_code)와 기업고유번호(corp_code) 매핑 테이블 다운로드.

```
GET /api/corpCode.xml?crtfc_key={API_KEY}
```

**응답**: ZIP 파일 (XML 포함)

**XML 필드**:
| 필드 | 설명 |
|------|------|
| `corp_code` | 기업 고유번호 (8자리) |
| `corp_name` | 회사명 |
| `stock_code` | 종목코드 (6자리, 상장사만) |
| `modify_date` | 최종수정일 (YYYYMMDD) |

---

### 3.2 단일회사 전체 재무제표

XBRL 기반 전체 재무제표 항목 조회.

```
GET /api/fnlttSinglAcntAll.json
```

**요청 파라미터**:
| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|:----:|------|
| `crtfc_key` | STRING(40) | Y | API 인증키 |
| `corp_code` | STRING(8) | Y | 기업 고유번호 |
| `bsns_year` | STRING(4) | Y | 사업연도 |
| `reprt_code` | STRING(5) | Y | 보고서 코드 |
| `fs_div` | STRING(3) | Y | CFS(연결) / OFS(개별) |

**응답 필드**:
| 필드 | 설명 |
|------|------|
| `sj_div` | 재무제표구분 (BS/IS/CIS/CF/SCE) |
| `sj_nm` | 재무제표명 |
| `account_nm` | 계정명 |
| `thstrm_nm` | 당기명 |
| `thstrm_amount` | 당기금액 |
| `frmtrm_nm` | 전기명 |
| `frmtrm_amount` | 전기금액 |
| `bfefrmtrm_nm` | 전전기명 |
| `bfefrmtrm_amount` | 전전기금액 |
| `ord` | 계정과목 정렬순서 |

**재무제표구분 코드 (sj_div)**:
| 코드 | 재무제표 |
|------|---------|
| BS | 재무상태표 |
| IS | 손익계산서 |
| CIS | 포괄손익계산서 |
| CF | 현금흐름표 |
| SCE | 자본변동표 |

---

### 3.3 단일회사 주요 재무지표

재무비율 및 주요 지표 조회. (2023년 3분기부터 제공)

```
GET /api/fnlttSinglIndx.json
```

**요청 파라미터**:
| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|:----:|------|
| `crtfc_key` | STRING(40) | Y | API 인증키 |
| `corp_code` | STRING(8) | Y | 기업 고유번호 |
| `bsns_year` | STRING(4) | Y | 사업연도 |
| `reprt_code` | STRING(5) | Y | 보고서 코드 |
| `idx_cl_code` | STRING(7) | Y | 지표분류코드 |

**지표분류코드 (idx_cl_code)**:
| 코드 | 분류 | 포함 지표 |
|------|------|----------|
| M210000 | 수익성 | 영업이익률, ROE, ROA, 순이익률 |
| M220000 | 안정성 | 부채비율, 유동비율, 당좌비율 |
| M230000 | 성장성 | 매출성장률, 영업이익성장률, 순이익성장률 |
| M240000 | 활동성 | 총자산회전율, 재고자산회전율 |

**응답 필드**:
| 필드 | 설명 |
|------|------|
| `idx_cl_nm` | 지표분류명 |
| `idx_nm` | 지표명 |
| `idx_val` | 지표값 |

---

## 4. 에러 코드

| 코드 | 메시지 | 설명 |
|------|--------|------|
| 000 | 정상 | 정상 처리 |
| 010 | 등록되지 않은 키 | API 키 미등록 |
| 011 | 사용할 수 없는 키 | API 키 비활성화 |
| 013 | 조회된 데이터가 없습니다 | 해당 조건 데이터 없음 |
| 020 | 요청 제한 초과 | 일일 20,000건 초과 |
| 021 | 최대 100건 초과 | 다중회사 조회 시 100건 초과 |
| 100 | 필드의 부적절한 값 | 파라미터 값 오류 |
| 800 | 원인을 알 수 없는 에러 | 서버 내부 오류 |

---

## 5. 구현 전략

### 5.1 기업코드 매핑 테이블

```python
# 1. corpCode.xml 다운로드 (ZIP)
# 2. XML 파싱하여 stock_code → corp_code 매핑
# 3. SQLite 또는 Redis에 캐싱
# 4. 주기적 갱신 (일/주 단위)

corp_code_mapping = {
    "005930": "00126380",  # 삼성전자
    "000660": "00164779",  # SK하이닉스
    # ...
}
```

### 5.2 캐싱 전략

| 데이터 | 캐시 TTL | 갱신 주기 |
|--------|---------|----------|
| 기업코드 매핑 | 1주일 | 매일 체크 |
| 재무제표 | 1개월 | 분기별 |
| 재무지표 | 1개월 | 분기별 |

### 5.3 Fundamental Analyst 연동

```python
# agents/subagents/fundamental_analyst.py

async def analyze_fundamentals(stock_code: str) -> dict:
    # 1. 기업코드 조회
    corp_code = await get_corp_code(stock_code)

    # 2. 재무제표 조회
    financials = await opendart.get_financial_statements(
        corp_code=corp_code,
        bsns_year=current_year - 1,
        reprt_code="11011",  # 사업보고서
        fs_div="CFS"  # 연결재무제표
    )

    # 3. 재무지표 조회
    ratios = await opendart.get_financial_ratios(
        corp_code=corp_code,
        idx_cl_code="M210000"  # 수익성
    )

    # 4. 분석 결과 반환
    return {
        "revenue": financials.get("매출액"),
        "operating_profit": financials.get("영업이익"),
        "net_income": financials.get("당기순이익"),
        "roe": ratios.get("자기자본이익률"),
        "debt_ratio": ratios.get("부채비율"),
    }
```

---

## 6. 환경 설정

```env
# .env
OPENDART_API_KEY=your_40_character_api_key_here
```

---

## 7. 참고 링크

- [OpenDART 개발가이드](https://opendart.fss.or.kr/guide/main.do)
- [API 키 발급](https://opendart.fss.or.kr/uat/uia/egovLoginUsr.do)
- [정기보고서 재무정보 API](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS003)
