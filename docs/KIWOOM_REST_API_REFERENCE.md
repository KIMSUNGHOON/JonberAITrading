# 키움 REST API Reference

> 자동 생성된 문서입니다. 원본: docs/KiwoomRESTAPI.xlsx
> 생성일: 2025-12-31

---

## 목차

- [API 리스트](#api-리스트)
- [OAuth 인증](#oauth-인증)
- [국내주식 시세](#국내주식-시세)
- [계좌 조회](#계좌-조회)
- [주문](#주문)
- [차트](#차트)

---

## API 리스트

| No | API ID | API 명 | 대분류 | 중분류 | URL |
|-----|--------|--------|--------|--------|-----|
| 2 | au10002 | 접근토큰폐기 | OAuth 인증 | 접근토큰폐기 | /oauth2/revoke |
| 3 | ka00198 | 실시간종목조회순위 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 4 | ka01690 | 일별잔고수익률 | 국내주식 | 계좌 | /api/dostk/acnt |
| 5 | ka10001 | 주식기본정보요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 6 | ka10002 | 주식거래원요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 7 | ka10003 | 체결정보요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 8 | ka10004 | 주식호가요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 9 | ka10005 | 주식일주월시분요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 10 | ka10006 | 주식시분요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 11 | ka10007 | 시세표성정보요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 12 | ka10008 | 주식외국인종목별매매동향 | 국내주식 | 기관/외국인 | /api/dostk/frgnistt |
| 13 | ka10009 | 주식기관요청 | 국내주식 | 기관/외국인 | /api/dostk/frgnistt |
| 14 | ka10010 | 업종프로그램요청 | 국내주식 | 업종 | /api/dostk/sect |
| 15 | ka10011 | 신주인수권전체시세요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 16 | ka10013 | 신용매매동향요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 17 | ka10014 | 공매도추이요청 | 국내주식 | 공매도 | /api/dostk/shsa |
| 18 | ka10015 | 일별거래상세요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 19 | ka10016 | 신고저가요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 20 | ka10017 | 상하한가요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 21 | ka10018 | 고저가근접요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 22 | ka10019 | 가격급등락요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 23 | ka10020 | 호가잔량상위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 24 | ka10021 | 호가잔량급증요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 25 | ka10022 | 잔량율급증요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 26 | ka10023 | 거래량급증요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 27 | ka10024 | 거래량갱신요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 28 | ka10025 | 매물대집중요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 29 | ka10026 | 고저PER요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 30 | ka10027 | 전일대비등락률상위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 31 | ka10028 | 시가대비등락률요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 32 | ka10029 | 예상체결등락률상위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 33 | ka10030 | 당일거래량상위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 34 | ka10031 | 전일거래량상위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 35 | ka10032 | 거래대금상위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 36 | ka10033 | 신용비율상위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 37 | ka10034 | 외인기간별매매상위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 38 | ka10035 | 외인연속순매매상위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 39 | ka10036 | 외인한도소진율증가상위 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 40 | ka10037 | 외국계창구매매상위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 41 | ka10038 | 종목별증권사순위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 42 | ka10039 | 증권사별매매상위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 43 | ka10040 | 당일주요거래원요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 44 | ka10042 | 순매수거래원순위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 45 | ka10043 | 거래원매물대분석요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 46 | ka10044 | 일별기관매매종목요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 47 | ka10045 | 종목별기관매매추이요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 48 | ka10046 | 체결강도추이시간별요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 49 | ka10047 | 체결강도추이일별요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 50 | ka10048 | ELW일별민감도지표요청 | 국내주식 | ELW | /api/dostk/elw |
| 51 | ka10050 | ELW민감도지표요청 | 국내주식 | ELW | /api/dostk/elw |
| 52 | ka10051 | 업종별투자자순매수요청 | 국내주식 | 업종 | /api/dostk/sect |
| 53 | ka10052 | 거래원순간거래량요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 54 | ka10053 | 당일상위이탈원요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 55 | ka10054 | 변동성완화장치발동종목요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 56 | ka10055 | 당일전일체결량요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 57 | ka10058 | 투자자별일별매매종목요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 58 | ka10059 | 종목별투자자기관별요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 59 | ka10060 | 종목별투자자기관별차트요청 | 국내주식 | 차트 | /api/dostk/chart |
| 60 | ka10061 | 종목별투자자기관별합계요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 61 | ka10062 | 동일순매매순위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 62 | ka10063 | 장중투자자별매매요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 63 | ka10064 | 장중투자자별매매차트요청 | 국내주식 | 차트 | /api/dostk/chart |
| 64 | ka10065 | 장중투자자별매매상위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 65 | ka10066 | 장마감후투자자별매매요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 66 | ka10068 | 대차거래추이요청 | 국내주식 | 대차거래 | /api/dostk/slb |
| 67 | ka10069 | 대차거래상위10종목요청 | 국내주식 | 대차거래 | /api/dostk/slb |
| 68 | ka10072 | 일자별종목별실현손익요청_일자 | 국내주식 | 계좌 | /api/dostk/acnt |
| 69 | ka10073 | 일자별종목별실현손익요청_기간 | 국내주식 | 계좌 | /api/dostk/acnt |
| 70 | ka10074 | 일자별실현손익요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 71 | ka10075 | 미체결요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 72 | ka10076 | 체결요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 73 | ka10077 | 당일실현손익상세요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 74 | ka10078 | 증권사별종목매매동향요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 75 | ka10079 | 주식틱차트조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 76 | ka10080 | 주식분봉차트조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 77 | ka10081 | 주식일봉차트조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 78 | ka10082 | 주식주봉차트조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 79 | ka10083 | 주식월봉차트조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 80 | ka10084 | 당일전일체결요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 81 | ka10085 | 계좌수익률요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 82 | ka10086 | 일별주가요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 83 | ka10087 | 시간외단일가요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 84 | ka10088 | 미체결 분할주문 상세 | 국내주식 | 계좌 | /api/dostk/acnt |
| 85 | ka10094 | 주식년봉차트조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 86 | ka10095 | 관심종목정보요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 87 | ka10098 | 시간외단일가등락율순위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 88 | ka10099 | 종목정보 리스트 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 89 | ka10100 | 종목정보 조회 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 90 | ka10101 | 업종코드 리스트 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 91 | ka10102 | 회원사 리스트 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 92 | ka10131 | 기관외국인연속매매현황요청 | 국내주식 | 기관/외국인 | /api/dostk/frgnistt |
| 93 | ka10170 | 당일매매일지요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 94 | ka10171 | 조건검색 목록조회 | 국내주식 | 조건검색 | /api/dostk/websocket |
| 95 | ka10172 | 조건검색 요청 일반 | 국내주식 | 조건검색 | /api/dostk/websocket |
| 96 | ka10173 | 조건검색 요청 실시간 | 국내주식 | 조건검색 | /api/dostk/websocket |
| 97 | ka10174 | 조건검색 실시간 해제 | 국내주식 | 조건검색 | /api/dostk/websocket |
| 98 | ka20001 | 업종현재가요청 | 국내주식 | 업종 | /api/dostk/sect |
| 99 | ka20002 | 업종별주가요청 | 국내주식 | 업종 | /api/dostk/sect |
| 100 | ka20003 | 전업종지수요청 | 국내주식 | 업종 | /api/dostk/sect |
| 101 | ka20004 | 업종틱차트조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 102 | ka20005 | 업종분봉조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 103 | ka20006 | 업종일봉조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 104 | ka20007 | 업종주봉조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 105 | ka20008 | 업종월봉조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 106 | ka20009 | 업종현재가일별요청 | 국내주식 | 업종 | /api/dostk/sect |
| 107 | ka20019 | 업종년봉조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 108 | ka20068 | 대차거래추이요청(종목별) | 국내주식 | 대차거래 | /api/dostk/slb |
| 109 | ka30001 | ELW가격급등락요청 | 국내주식 | ELW | /api/dostk/elw |
| 110 | ka30002 | 거래원별ELW순매매상위요청 | 국내주식 | ELW | /api/dostk/elw |
| 111 | ka30003 | ELWLP보유일별추이요청 | 국내주식 | ELW | /api/dostk/elw |
| 112 | ka30004 | ELW괴리율요청 | 국내주식 | ELW | /api/dostk/elw |
| 113 | ka30005 | ELW조건검색요청 | 국내주식 | ELW | /api/dostk/elw |
| 114 | ka30009 | ELW등락율순위요청 | 국내주식 | ELW | /api/dostk/elw |
| 115 | ka30010 | ELW잔량순위요청 | 국내주식 | ELW | /api/dostk/elw |
| 116 | ka30011 | ELW근접율요청 | 국내주식 | ELW | /api/dostk/elw |
| 117 | ka30012 | ELW종목상세정보요청 | 국내주식 | ELW | /api/dostk/elw |
| 118 | ka40001 | ETF수익율요청 | 국내주식 | ETF | /api/dostk/etf |
| 119 | ka40002 | ETF종목정보요청 | 국내주식 | ETF | /api/dostk/etf |
| 120 | ka40003 | ETF일별추이요청 | 국내주식 | ETF | /api/dostk/etf |
| 121 | ka40004 | ETF전체시세요청 | 국내주식 | ETF | /api/dostk/etf |
| 122 | ka40006 | ETF시간대별추이요청 | 국내주식 | ETF | /api/dostk/etf |
| 123 | ka40007 | ETF시간대별체결요청 | 국내주식 | ETF | /api/dostk/etf |
| 124 | ka40008 | ETF일자별체결요청 | 국내주식 | ETF | /api/dostk/etf |
| 125 | ka40009 | ETF시간대별체결요청 | 국내주식 | ETF | /api/dostk/etf |
| 126 | ka40010 | ETF시간대별추이요청 | 국내주식 | ETF | /api/dostk/etf |
| 127 | ka50010 | 금현물체결추이 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 128 | ka50012 | 금현물일별추이 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 129 | ka50079 | 금현물틱차트조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 130 | ka50080 | 금현물분봉차트조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 131 | ka50081 | 금현물일봉차트조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 132 | ka50082 | 금현물주봉차트조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 133 | ka50083 | 금현물월봉차트조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 134 | ka50087 | 금현물예상체결 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 135 | ka50091 | 금현물당일틱차트조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 136 | ka50092 | 금현물당일분봉차트조회요청 | 국내주식 | 차트 | /api/dostk/chart |
| 137 | ka50100 | 금현물 시세정보 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 138 | ka50101 | 금현물 호가 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 139 | ka52301 | 금현물투자자현황 | 국내주식 | 기관/외국인 | /api/dostk/frgnistt |
| 140 | ka90001 | 테마그룹별요청 | 국내주식 | 테마 | /api/dostk/thme |
| 141 | ka90002 | 테마구성종목요청 | 국내주식 | 테마 | /api/dostk/thme |
| 142 | ka90003 | 프로그램순매수상위50요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 143 | ka90004 | 종목별프로그램매매현황요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 144 | ka90005 | 프로그램매매추이요청 시간대별 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 145 | ka90006 | 프로그램매매차익잔고추이요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 146 | ka90007 | 프로그램매매누적추이요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 147 | ka90008 | 종목시간별프로그램매매추이요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 148 | ka90009 | 외국인기관매매상위요청 | 국내주식 | 순위정보 | /api/dostk/rkinfo |
| 149 | ka90010 | 프로그램매매추이요청 일자별 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 150 | ka90012 | 대차거래내역요청 | 국내주식 | 대차거래 | /api/dostk/slb |
| 151 | ka90013 | 종목일별프로그램매매추이요청 | 국내주식 | 시세 | /api/dostk/mrkcond |
| 152 | kt00001 | 예수금상세현황요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 153 | kt00002 | 일별추정예탁자산현황요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 154 | kt00003 | 추정자산조회요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 155 | kt00004 | 계좌평가현황요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 156 | kt00005 | 체결잔고요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 157 | kt00007 | 계좌별주문체결내역상세요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 158 | kt00008 | 계좌별익일결제예정내역요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 159 | kt00009 | 계좌별주문체결현황요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 160 | kt00010 | 주문인출가능금액요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 161 | kt00011 | 증거금율별주문가능수량조회요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 162 | kt00012 | 신용보증금율별주문가능수량조회요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 163 | kt00013 | 증거금세부내역조회요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 164 | kt00015 | 위탁종합거래내역요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 165 | kt00016 | 일별계좌수익률상세현황요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 166 | kt00017 | 계좌별당일현황요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 167 | kt00018 | 계좌평가잔고내역요청 | 국내주식 | 계좌 | /api/dostk/acnt |
| 168 | kt10000 | 주식 매수주문 | 국내주식 | 주문 | /api/dostk/ordr |
| 169 | kt10001 | 주식 매도주문 | 국내주식 | 주문 | /api/dostk/ordr |
| 170 | kt10002 | 주식 정정주문 | 국내주식 | 주문 | /api/dostk/ordr |
| 171 | kt10003 | 주식 취소주문 | 국내주식 | 주문 | /api/dostk/ordr |
| 172 | kt10006 | 신용 매수주문 | 국내주식 | 신용주문 | /api/dostk/crdordr |
| 173 | kt10007 | 신용 매도주문 | 국내주식 | 신용주문 | /api/dostk/crdordr |
| 174 | kt10008 | 신용 정정주문 | 국내주식 | 신용주문 | /api/dostk/crdordr |
| 175 | kt10009 | 신용 취소주문 | 국내주식 | 신용주문 | /api/dostk/crdordr |
| 176 | kt20016 | 신용융자 가능종목요청 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 177 | kt20017 | 신용융자 가능문의 | 국내주식 | 종목정보 | /api/dostk/stkinfo |
| 178 | kt50000 | 금현물 매수주문 | 국내주식 | 주문 | /api/dostk/ordr |
| 179 | kt50001 | 금현물 매도주문 | 국내주식 | 주문 | /api/dostk/ordr |
| 180 | kt50002 | 금현물 정정주문 | 국내주식 | 주문 | /api/dostk/ordr |
| 181 | kt50003 | 금현물 취소주문 | 국내주식 | 주문 | /api/dostk/ordr |
| 182 | kt50020 | 금현물 잔고확인 | 국내주식 | 계좌 | /api/dostk/acnt |
| 183 | kt50021 | 금현물 예수금 | 국내주식 | 계좌 | /api/dostk/acnt |
| 184 | kt50030 | 금현물 주문체결전체조회 | 국내주식 | 계좌 | /api/dostk/acnt |
| 185 | kt50031 | 금현물 주문체결조회 | 국내주식 | 계좌 | /api/dostk/acnt |
| 186 | kt50032 | 금현물 거래내역조회 | 국내주식 | 계좌 | /api/dostk/acnt |
| 187 | kt50075 | 금현물 미체결조회 | 국내주식 | 계좌 | /api/dostk/acnt |
| 188 | 00 | 주문체결 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 189 | 04 | 잔고 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 190 | 0A | 주식기세 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 191 | 0B | 주식체결 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 192 | 0C | 주식우선호가 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 193 | 0D | 주식호가잔량 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 194 | 0E | 주식시간외호가 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 195 | 0F | 주식당일거래원 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 196 | 0G | ETF NAV | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 197 | 0H | 주식예상체결 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 198 | 0I | 국제금환산가격 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 199 | 0J | 업종지수 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 200 | 0U | 업종등락 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 201 | 0g | 주식종목정보 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 202 | 0m | ELW 이론가 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 203 | 0s | 장시작시간 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 204 | 0u | ELW 지표 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 205 | 0w | 종목프로그램매매 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 206 | 1h | VI발동/해제 | 국내주식 | 실시간시세 | /api/dostk/websocket |
| 207 | 공통 | 오류코드 |  |  |  |


---

## API 상세 정보


### 접근토큰 발급 (au10001)

- **API ID**: au10001
- **Method**: POST
- **URL**: /oauth2/token
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | grant_type | grant_type | String | Y |  | client_credentials 입력 |
| request | appkey | 앱키 | String | Y |  |  |
| request | secretkey | 시크릿키 | String | Y |  |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | expires_dt | 만료일 | String | Y |  |  |
| response | token_type | 토큰타입 | String | Y |  |  |
| response | token | 접근토큰 | String | Y |  |  |

---

### 접근토큰폐기 (au10002)

- **API ID**: au10002
- **Method**: POST
- **URL**: /oauth2/revoke
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | appkey | 앱키 | String | Y |  |  |
| request | secretkey | 시크릿키 | String | Y |  |  |
| request | token | 접근토큰 | String | Y |  |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |

---

### 실시간종목조회순위 (ka00198)

- **API ID**: ka00198
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | qry_tp | 구분 | String | Y | 1 | 1:1분, 2:10분, 3:1시간, 4:당일 누적, 5:30초 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | item_inq_rank | 실시간종목조회순위 | LIST | N |  |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - bigd_rank | 빅데이터 순위 | String | N | 20 |  |
| response | - rank_chg | 순위 등락 | String | N | 20 |  |
| response | - rank_chg_sign | 순위 등락 부호 | String | N | 20 |  |
| response | - past_curr_prc | 과거 현재가 | String | N | 20 |  |
| response | - base_comp_sign | 기준가 대비 부호 | String | N | 20 |  |
| response | - base_comp_chgr | 기준가 대비 등락율 | String | N | 20 |  |
| response | - prev_base_sign | 직전 기준 대비 부호 | String | N | 20 |  |
| response | - prev_base_chgr | 직전 기준 대비 등락율 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - tm | 시간 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |

---

### 일별잔고수익률 (ka01690)

- **API ID**: ka01690
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | qry_dt | 조회일자 | String | Y | 8 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | dt | 일자 | String | N | 20 |  |
| response | tot_buy_amt | 총 매입가 | String | N | 20 |  |
| response | tot_evlt_amt | 총 평가금액 | String | N | 20 |  |
| response | tot_evltv_prft | 총 평가손익 | String | N | 20 |  |
| response | tot_prft_rt | 수익률 | String | N | 20 |  |
| response | dbst_bal | 예수금 | String | N | 20 |  |
| response | day_stk_asst | 추정자산 | String | N | 20 |  |
| response | buy_wght | 현금비중 | String | N | 20 |  |
| response | day_bal_rt | 일별잔고수익률 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 20 |  |
| response | - rmnd_qty | 보유 수량 | String | N | 20 |  |
| response | - buy_uv | 매입 단가 | String | N | 20 |  |
| response | - buy_wght | 매수비중 | String | N | 20 |  |
| response | - evltv_prft | 평가손익 | String | N | 20 |  |
| response | - prft_rt | 수익률 | String | N | 20 |  |

> ... 외 2개 필드

---

### 주식기본정보요청 (ka10001)

- **API ID**: ka10001
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_cd | 종목코드 | String | N | 20 |  |
| response | stk_nm | 종목명 | String | N | 40 |  |
| response | setl_mm | 결산월 | String | N | 20 |  |
| response | fav | 액면가 | String | N | 20 |  |
| response | cap | 자본금 | String | N | 20 |  |
| response | flo_stk | 상장주식 | String | N | 20 |  |
| response | crd_rt | 신용비율 | String | N | 20 |  |
| response | oyr_hgst | 연중최고 | String | N | 20 |  |
| response | oyr_lwst | 연중최저 | String | N | 20 |  |
| response | mac | 시가총액 | String | N | 20 |  |
| response | mac_wght | 시가총액비중 | String | N | 20 |  |
| response | for_exh_rt | 외인소진률 | String | N | 20 |  |
| response | repl_pric | 대용가 | String | N | 20 |  |
| response | per | PER | String | N | 20 | [ 주의 ] PER, ROE 값들은 외부벤더사에서 제공되는 데이터이며 일주일에 한번 또는  |
| response | eps | EPS | String | N | 20 |  |
| response | roe | ROE | String | N | 20 | [ 주의 ]  PER, ROE 값들은 외부벤더사에서 제공되는 데이터이며 일주일에 한번 또는 |
| response | pbr | PBR | String | N | 20 |  |

> ... 외 28개 필드

---

### 주식거래원요청 (ka10002)

- **API ID**: ka10002
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_cd | 종목코드 | String | N | 20 |  |
| response | stk_nm | 종목명 | String | N | 40 |  |
| response | cur_prc | 현재가 | String | N | 20 |  |
| response | flu_smbol | 등락부호 | String | N | 20 |  |
| response | base_pric | 기준가 | String | N | 20 |  |
| response | pred_pre | 전일대비 | String | N | 20 |  |
| response | flu_rt | 등락율 | String | N | 20 |  |
| response | sel_trde_ori_nm_1 | 매도거래원명1 | String | N | 20 |  |
| response | sel_trde_ori_1 | 매도거래원1 | String | N | 20 |  |
| response | sel_trde_qty_1 | 매도거래량1 | String | N | 20 |  |
| response | buy_trde_ori_nm_1 | 매수거래원명1 | String | N | 20 |  |
| response | buy_trde_ori_1 | 매수거래원1 | String | N | 20 |  |
| response | buy_trde_qty_1 | 매수거래량1 | String | N | 20 |  |
| response | sel_trde_ori_nm_2 | 매도거래원명2 | String | N | 20 |  |
| response | sel_trde_ori_2 | 매도거래원2 | String | N | 20 |  |
| response | sel_trde_qty_2 | 매도거래량2 | String | N | 20 |  |
| response | buy_trde_ori_nm_2 | 매수거래원명2 | String | N | 20 |  |

> ... 외 20개 필드

---

### 체결정보요청 (ka10003)

- **API ID**: ka10003
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | cntr_infr | 체결정보 | LIST | N |  |  |
| response | - tm | 시간 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - pre_rt | 대비율 | String | N | 20 |  |
| response | - pri_sel_bid_unit | 우선매도호가단위 | String | N | 20 |  |
| response | - pri_buy_bid_unit | 우선매수호가단위 | String | N | 20 |  |
| response | - cntr_trde_qty | 체결거래량 | String | N | 20 |  |
| response | - sign | sign | String | N | 20 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - acc_trde_prica | 누적거래대금 | String | N | 20 |  |
| response | - cntr_str | 체결강도 | String | N | 20 |  |
| response | - stex_tp | 거래소구분 | String | N | 20 | KRX , NXT , 통합 |

---

### 주식호가요청 (ka10004)

- **API ID**: ka10004
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | bid_req_base_tm | 호가잔량기준시간 | String | N | 20 | 호가시간 |
| response | sel_10th_pre_req_pre | 매도10차선잔량대비 | String | N | 20 | 매도호가직전대비10 |
| response | sel_10th_pre_req | 매도10차선잔량 | String | N | 20 | 매도호가수량10 |
| response | sel_10th_pre_bid | 매도10차선호가 | String | N | 20 | 매도호가10 |
| response | sel_9th_pre_req_pre | 매도9차선잔량대비 | String | N | 20 | 매도호가직전대비9 |
| response | sel_9th_pre_req | 매도9차선잔량 | String | N | 20 | 매도호가수량9 |
| response | sel_9th_pre_bid | 매도9차선호가 | String | N | 20 | 매도호가9 |
| response | sel_8th_pre_req_pre | 매도8차선잔량대비 | String | N | 20 | 매도호가직전대비8 |
| response | sel_8th_pre_req | 매도8차선잔량 | String | N | 20 | 매도호가수량8 |
| response | sel_8th_pre_bid | 매도8차선호가 | String | N | 20 | 매도호가8 |
| response | sel_7th_pre_req_pre | 매도7차선잔량대비 | String | N | 20 | 매도호가직전대비7 |
| response | sel_7th_pre_req | 매도7차선잔량 | String | N | 20 | 매도호가수량7 |
| response | sel_7th_pre_bid | 매도7차선호가 | String | N | 20 | 매도호가7 |
| response | sel_6th_pre_req_pre | 매도6차선잔량대비 | String | N | 20 | 매도호가직전대비6 |
| response | sel_6th_pre_req | 매도6차선잔량 | String | N | 20 | 매도호가수량6 |
| response | sel_6th_pre_bid | 매도6차선호가 | String | N | 20 | 매도호가6 |
| response | sel_5th_pre_req_pre | 매도5차선잔량대비 | String | N | 20 | 매도호가직전대비5 |

> ... 외 52개 필드

---

### 주식일주월시분요청 (ka10005)

- **API ID**: ka10005
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_ddwkmm | 주식일주월시분 | LIST | N |  |  |
| response | - date | 날짜 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |
| response | - close_pric | 종가 | String | N | 20 |  |
| response | - pre | 대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - trde_prica | 거래대금 | String | N | 20 |  |
| response | - for_poss | 외인보유 | String | N | 20 |  |
| response | - for_wght | 외인비중 | String | N | 20 |  |
| response | - for_netprps | 외인순매수 | String | N | 20 |  |
| response | - orgn_netprps | 기관순매수 | String | N | 20 |  |
| response | - ind_netprps | 개인순매수 | String | N | 20 |  |
| response | - frgn | 외국계 | String | N | 20 |  |
| response | - crd_remn_rt | 신용잔고율 | String | N | 20 |  |

> ... 외 1개 필드

---

### 주식시분요청 (ka10006)

- **API ID**: ka10006
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | date | 날짜 | String | N | 20 |  |
| response | open_pric | 시가 | String | N | 20 |  |
| response | high_pric | 고가 | String | N | 20 |  |
| response | low_pric | 저가 | String | N | 20 |  |
| response | close_pric | 종가 | String | N | 20 |  |
| response | pre | 대비 | String | N | 20 |  |
| response | flu_rt | 등락률 | String | N | 20 |  |
| response | trde_qty | 거래량 | String | N | 20 |  |
| response | trde_prica | 거래대금 | String | N | 20 |  |
| response | cntr_str | 체결강도 | String | N | 20 |  |

---

### 시세표성정보요청 (ka10007)

- **API ID**: ka10007
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_nm | 종목명 | String | N | 40 |  |
| response | stk_cd | 종목코드 | String | N | 6 |  |
| response | date | 날짜 | String | N | 20 |  |
| response | tm | 시간 | String | N | 20 |  |
| response | pred_close_pric | 전일종가 | String | N | 20 |  |
| response | pred_trde_qty | 전일거래량 | String | N | 20 |  |
| response | upl_pric | 상한가 | String | N | 20 |  |
| response | lst_pric | 하한가 | String | N | 20 |  |
| response | pred_trde_prica | 전일거래대금 | String | N | 20 |  |
| response | flo_stkcnt | 상장주식수 | String | N | 20 |  |
| response | cur_prc | 현재가 | String | N | 20 |  |
| response | smbol | 부호 | String | N | 20 |  |
| response | flu_rt | 등락률 | String | N | 20 |  |
| response | pred_rt | 전일비 | String | N | 20 |  |
| response | open_pric | 시가 | String | N | 20 |  |
| response | high_pric | 고가 | String | N | 20 |  |
| response | low_pric | 저가 | String | N | 20 |  |

> ... 외 107개 필드

---

### 주식외국인종목별매매동향 (ka10008)

- **API ID**: ka10008
- **Method**: POST
- **URL**: /api/dostk/frgnistt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_frgnr | 주식외국인 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - close_pric | 종가 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - chg_qty | 변동수량 | String | N | 20 |  |
| response | - poss_stkcnt | 보유주식수 | String | N | 20 |  |
| response | - wght | 비중 | String | N | 20 |  |
| response | - gain_pos_stkcnt | 취득가능주식수 | String | N | 20 |  |
| response | - frgnr_limit | 외국인한도 | String | N | 20 |  |
| response | - frgnr_limit_irds | 외국인한도증감 | String | N | 20 |  |
| response | - limit_exh_rt | 한도소진률 | String | N | 20 |  |

---

### 주식기관요청 (ka10009)

- **API ID**: ka10009
- **Method**: POST
- **URL**: /api/dostk/frgnistt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | date | 날짜 | String | N | 20 |  |
| response | close_pric | 종가 | String | N | 20 |  |
| response | pre | 대비 | String | N | 20 |  |
| response | orgn_dt_acc | 기관기간누적 | String | N | 20 |  |
| response | orgn_daly_nettrde | 기관일별순매매 | String | N | 20 |  |
| response | frgnr_daly_nettrde | 외국인일별순매매 | String | N | 20 |  |
| response | frgnr_qota_rt | 외국인지분율 | String | N | 20 |  |

---

### 업종프로그램요청 (ka10010)

- **API ID**: ka10010
- **Method**: POST
- **URL**: /api/dostk/sect
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | dfrt_trst_sell_qty | 차익위탁매도수량 | String | N | 20 |  |
| response | dfrt_trst_sell_amt | 차익위탁매도금액 | String | N | 20 |  |
| response | dfrt_trst_buy_qty | 차익위탁매수수량 | String | N | 20 |  |
| response | dfrt_trst_buy_amt | 차익위탁매수금액 | String | N | 20 |  |
| response | dfrt_trst_netprps_qty | 차익위탁순매수수량 | String | N | 20 |  |
| response | dfrt_trst_netprps_amt | 차익위탁순매수금액 | String | N | 20 |  |
| response | ndiffpro_trst_sell_qty | 비차익위탁매도수량 | String | N | 20 |  |
| response | ndiffpro_trst_sell_amt | 비차익위탁매도금액 | String | N | 20 |  |
| response | ndiffpro_trst_buy_qty | 비차익위탁매수수량 | String | N | 20 |  |
| response | ndiffpro_trst_buy_amt | 비차익위탁매수금액 | String | N | 20 |  |
| response | ndiffpro_trst_netprps_qty | 비차익위탁순매수수량 | String | N | 20 |  |
| response | ndiffpro_trst_netprps_amt | 비차익위탁순매수금액 | String | N | 20 |  |
| response | all_dfrt_trst_sell_qty | 전체차익위탁매도수량 | String | N | 20 |  |
| response | all_dfrt_trst_sell_amt | 전체차익위탁매도금액 | String | N | 20 |  |
| response | all_dfrt_trst_buy_qty | 전체차익위탁매수수량 | String | N | 20 |  |
| response | all_dfrt_trst_buy_amt | 전체차익위탁매수금액 | String | N | 20 |  |
| response | all_dfrt_trst_netprps_qty | 전체차익위탁순매수수량 | String | N | 20 |  |

> ... 외 1개 필드

---

### 신주인수권전체시세요청 (ka10011)

- **API ID**: ka10011
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | newstk_recvrht_tp | 신주인수권구분 | String | Y | 2 | 00:전체, 05:신주인수권증권, 07:신주인수권증서 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | newstk_recvrht_mrpr | 신주인수권시세 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - fpr_sel_bid | 최우선매도호가 | String | N | 20 |  |
| response | - fpr_buy_bid | 최우선매수호가 | String | N | 20 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |

---

### 신용매매동향요청 (ka10013)

- **API ID**: ka10013
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | dt | 일자 | String | Y | 8 | YYYYMMDD |
| request | qry_tp | 조회구분 | String | Y | 1 | 1:융자, 2:대주 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | crd_trde_trend | 신용매매동향 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - new | 신규 | String | N | 20 |  |
| response | - rpya | 상환 | String | N | 20 |  |
| response | - remn | 잔고 | String | N | 20 |  |
| response | - amt | 금액 | String | N | 20 |  |
| response | - pre | 대비 | String | N | 20 |  |
| response | - shr_rt | 공여율 | String | N | 20 |  |
| response | - remn_rt | 잔고율 | String | N | 20 |  |

---

### 공매도추이요청 (ka10014)

- **API ID**: ka10014
- **Method**: POST
- **URL**: /api/dostk/shsa
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | tm_tp | 시간구분 | String | N | 1 | 0:시작일, 1:기간 |
| request | strt_dt | 시작일자 | String | Y | 8 | YYYYMMDD |
| request | end_dt | 종료일자 | String | Y | 8 | YYYYMMDD |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | shrts_trnsn | 공매도추이 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - close_pric | 종가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - shrts_qty | 공매도량 | String | N | 20 |  |
| response | - ovr_shrts_qty | 누적공매도량 | String | N | 20 | 설정 기간의 공매도량 합산데이터 |
| response | - trde_wght | 매매비중 | String | N | 20 |  |
| response | - shrts_trde_prica | 공매도거래대금 | String | N | 20 |  |
| response | - shrts_avg_pric | 공매도평균가 | String | N | 20 |  |

---

### 일별거래상세요청 (ka10015)

- **API ID**: ka10015
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | strt_dt | 시작일자 | String | Y | 8 | YYYYMMDD |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | daly_trde_dtl | 일별거래상세 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - close_pric | 종가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - trde_prica | 거래대금 | String | N | 20 |  |
| response | - bf_mkrt_trde_qty | 장전거래량 | String | N | 20 |  |
| response | - bf_mkrt_trde_wght | 장전거래비중 | String | N | 20 |  |
| response | - opmr_trde_qty | 장중거래량 | String | N | 20 |  |
| response | - opmr_trde_wght | 장중거래비중 | String | N | 20 |  |
| response | - af_mkrt_trde_qty | 장후거래량 | String | N | 20 |  |
| response | - af_mkrt_trde_wght | 장후거래비중 | String | N | 20 |  |
| response | - tot_3 | 합계3 | String | N | 20 |  |
| response | - prid_trde_qty | 기간중거래량 | String | N | 20 |  |
| response | - cntr_str | 체결강도 | String | N | 20 |  |

> ... 외 14개 필드

---

### 신고저가요청 (ka10016)

- **API ID**: ka10016
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | ntl_tp | 신고저구분 | String | Y | 1 | 1:신고가,2:신저가 |
| request | high_low_close_tp | 고저종구분 | String | Y | 1 | 1:고저기준, 2:종가기준 |
| request | stk_cnd | 종목조건 | String | Y | 1 | 0:전체조회,1:관리종목제외, 3:우선주제외, 5:증100제외, 6:증100만보기, 7:증 |
| request | trde_qty_tp | 거래량구분 | String | Y | 5 | 00000:전체조회, 00010:만주이상, 00050:5만주이상, 00100:10만주이상, |
| request | crd_cnd | 신용조건 | String | Y | 1 | 0:전체조회, 1:신용융자A군, 2:신용융자B군, 3:신용융자C군, 4:신용융자D군, 7: |
| request | updown_incls | 상하한포함 | String | Y | 1 | 0:미포함, 1:포함 |
| request | dt | 기간 | String | Y | 3 | 5:5일, 10:10일, 20:20일, 60:60일, 250:250일, 250일까지 입력가 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | ntl_pric | 신고저가 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - pred_trde_qty_pre_rt | 전일거래량대비율 | String | N | 20 |  |
| response | - sel_bid | 매도호가 | String | N | 20 |  |
| response | - buy_bid | 매수호가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |

---

### 상하한가요청 (ka10017)

- **API ID**: ka10017
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | updown_tp | 상하한구분 | String | Y | 1 | 1:상한, 2:상승, 3:보합, 4: 하한, 5:하락, 6:전일상한, 7:전일하한 |
| request | sort_tp | 정렬구분 | String | Y | 1 | 1:종목코드순, 2:연속횟수순(상위100개), 3:등락률순 |
| request | stk_cnd | 종목조건 | String | Y | 1 | 0:전체조회,1:관리종목제외, 3:우선주제외, 4:우선주+관리종목제외, 5:증100제외,  |
| request | trde_qty_tp | 거래량구분 | String | Y | 5 | 00000:전체조회, 00010:만주이상, 00050:5만주이상, 00100:10만주이상, |
| request | crd_cnd | 신용조건 | String | Y | 1 | 0:전체조회, 1:신용융자A군, 2:신용융자B군, 3:신용융자C군, 4:신용융자D군, 7: |
| request | trde_gold_tp | 매매금구분 | String | Y | 1 | 0:전체조회, 1:1천원미만, 2:1천원~2천원, 3:2천원~3천원, 4:5천원~1만원,  |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | updown_pric | 상하한가 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_infr | 종목정보 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - pred_trde_qty | 전일거래량 | String | N | 20 |  |
| response | - sel_req | 매도잔량 | String | N | 20 |  |
| response | - sel_bid | 매도호가 | String | N | 20 |  |
| response | - buy_bid | 매수호가 | String | N | 20 |  |
| response | - buy_req | 매수잔량 | String | N | 20 |  |
| response | - cnt | 횟수 | String | N | 20 |  |

---

### 고저가근접요청 (ka10018)

- **API ID**: ka10018
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | high_low_tp | 고저구분 | String | Y | 1 | 1:고가, 2:저가 |
| request | alacc_rt | 근접율 | String | Y | 2 | 05:0.5 10:1.0, 15:1.5, 20:2.0. 25:2.5, 30:3.0 |
| request | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | trde_qty_tp | 거래량구분 | String | Y | 5 | 00000:전체조회, 00010:만주이상, 00050:5만주이상, 00100:10만주이상, |
| request | stk_cnd | 종목조건 | String | Y | 1 | 0:전체조회,1:관리종목제외, 3:우선주제외, 5:증100제외, 6:증100만보기, 7:증 |
| request | crd_cnd | 신용조건 | String | Y | 1 | 0:전체조회, 1:신용융자A군, 2:신용융자B군, 3:신용융자C군, 4:신용융자D군, 7: |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | high_low_pric_alacc | 고저가근접 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - sel_bid | 매도호가 | String | N | 20 |  |
| response | - buy_bid | 매수호가 | String | N | 20 |  |
| response | - tdy_high_pric | 당일고가 | String | N | 20 |  |
| response | - tdy_low_pric | 당일저가 | String | N | 20 |  |

---

### 가격급등락요청 (ka10019)

- **API ID**: ka10019
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥, 201:코스피200 |
| request | flu_tp | 등락구분 | String | Y | 1 | 1:급등, 2:급락 |
| request | tm_tp | 시간구분 | String | Y | 1 | 1:분전, 2:일전 |
| request | tm | 시간 | String | Y | 2 | 분 혹은 일입력 |
| request | trde_qty_tp | 거래량구분 | String | Y | 4 | 00000:전체조회, 00010:만주이상, 00050:5만주이상, 00100:10만주이상, |
| request | stk_cnd | 종목조건 | String | Y | 1 | 0:전체조회,1:관리종목제외, 3:우선주제외, 5:증100제외, 6:증100만보기, 7:증 |
| request | crd_cnd | 신용조건 | String | Y | 1 | 0:전체조회, 1:신용융자A군, 2:신용융자B군, 3:신용융자C군, 4:신용융자D군, 7: |
| request | pric_cnd | 가격조건 | String | Y | 1 | 0:전체조회, 1:1천원미만, 2:1천원~2천원, 3:2천원~3천원, 4:5천원~1만원,  |
| request | updown_incls | 상하한포함 | String | Y | 1 | 0:미포함, 1:포함 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | pric_jmpflu | 가격급등락 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_cls | 종목분류 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - base_pric | 기준가 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - base_pre | 기준대비 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - jmp_rt | 급등률 | String | N | 20 |  |

---

### 호가잔량상위요청 (ka10020)

- **API ID**: ka10020
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 001:코스피, 101:코스닥 |
| request | sort_tp | 정렬구분 | String | Y | 1 | 1:순매수잔량순, 2:순매도잔량순, 3:매수비율순, 4:매도비율순 |
| request | trde_qty_tp | 거래량구분 | String | Y | 4 | 0000:장시작전(0주이상), 0010:만주이상, 0050:5만주이상, 00100:10만주 |
| request | stk_cnd | 종목조건 | String | Y | 1 | 0:전체조회, 1:관리종목제외, 5:증100제외, 6:증100만보기, 7:증40만보기, 8 |
| request | crd_cnd | 신용조건 | String | Y | 1 | 0:전체조회, 1:신용융자A군, 2:신용융자B군, 3:신용융자C군, 4:신용융자D군, 7: |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | bid_req_upper | 호가잔량상위 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - tot_sel_req | 총매도잔량 | String | N | 20 |  |
| response | - tot_buy_req | 총매수잔량 | String | N | 20 |  |
| response | - netprps_req | 순매수잔량 | String | N | 20 |  |
| response | - buy_rt | 매수비율 | String | N | 20 |  |

---

### 호가잔량급증요청 (ka10021)

- **API ID**: ka10021
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 001:코스피, 101:코스닥 |
| request | trde_tp | 매매구분 | String | Y | 1 | 1:매수잔량, 2:매도잔량 |
| request | sort_tp | 정렬구분 | String | Y | 1 | 1:급증량, 2:급증률 |
| request | tm_tp | 시간구분 | String | Y | 2 | 분 입력 |
| request | trde_qty_tp | 거래량구분 | String | Y | 4 | 1:천주이상, 5:5천주이상, 10:만주이상, 50:5만주이상, 100:10만주이상 |
| request | stk_cnd | 종목조건 | String | Y | 1 | 0:전체조회, 1:관리종목제외, 5:증100제외, 6:증100만보기, 7:증40만보기, 8 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | bid_req_sdnin | 호가잔량급증 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - int | 기준률 | String | N | 20 |  |
| response | - now | 현재 | String | N | 20 |  |
| response | - sdnin_qty | 급증수량 | String | N | 20 |  |
| response | - sdnin_rt | 급증률 | String | N | 20 |  |
| response | - tot_buy_qty | 총매수량 | String | N | 20 |  |

---

### 잔량율급증요청 (ka10022)

- **API ID**: ka10022
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 001:코스피, 101:코스닥 |
| request | rt_tp | 비율구분 | String | Y | 1 | 1:매수/매도비율, 2:매도/매수비율 |
| request | tm_tp | 시간구분 | String | Y | 2 | 분 입력 |
| request | trde_qty_tp | 거래량구분 | String | Y | 1 | 5:5천주이상, 10:만주이상, 50:5만주이상, 100:10만주이상 |
| request | stk_cnd | 종목조건 | String | Y | 1 | 0:전체조회, 1:관리종목제외, 5:증100제외, 6:증100만보기, 7:증40만보기, 8 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | req_rt_sdnin | 잔량율급증 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - int | 기준률 | String | N | 20 |  |
| response | - now_rt | 현재비율 | String | N | 20 |  |
| response | - sdnin_rt | 급증률 | String | N | 20 |  |
| response | - tot_sel_req | 총매도잔량 | String | N | 20 |  |
| response | - tot_buy_req | 총매수잔량 | String | N | 20 |  |

---

### 거래량급증요청 (ka10023)

- **API ID**: ka10023
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | sort_tp | 정렬구분 | String | Y | 1 | 1:급증량, 2:급증률, 3:급감량, 4:급감률 |
| request | tm_tp | 시간구분 | String | Y | 1 | 1:분, 2:전일 |
| request | trde_qty_tp | 거래량구분 | String | Y | 1 | 5:5천주이상, 10:만주이상, 50:5만주이상, 100:10만주이상, 200:20만주이상 |
| request | tm | 시간 | String | N | 2 | 분 입력 |
| request | stk_cnd | 종목조건 | String | Y | 1 | 0:전체조회, 1:관리종목제외, 3:우선주제외, 11:정리매매종목제외, 4:관리종목,우선주 |
| request | pric_tp | 가격구분 | String | Y | 1 | 0:전체조회, 2:5만원이상, 5:1만원이상, 6:5천원이상, 8:1천원이상, 9:10만원 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | trde_qty_sdnin | 거래량급증 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - prev_trde_qty | 이전거래량 | String | N | 20 |  |
| response | - now_trde_qty | 현재거래량 | String | N | 20 |  |
| response | - sdnin_qty | 급증량 | String | N | 20 |  |
| response | - sdnin_rt | 급증률 | String | N | 20 |  |

---

### 거래량갱신요청 (ka10024)

- **API ID**: ka10024
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | cycle_tp | 주기구분 | String | Y | 1 | 5:5일, 10:10일, 20:20일, 60:60일, 250:250일 |
| request | trde_qty_tp | 거래량구분 | String | Y | 1 | 5:5천주이상, 10:만주이상, 50:5만주이상, 100:10만주이상, 200:20만주이상 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | trde_qty_updt | 거래량갱신 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - prev_trde_qty | 이전거래량 | String | N | 20 |  |
| response | - now_trde_qty | 현재거래량 | String | N | 20 |  |
| response | - sel_bid | 매도호가 | String | N | 20 |  |
| response | - buy_bid | 매수호가 | String | N | 20 |  |

---

### 매물대집중요청 (ka10025)

- **API ID**: ka10025
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | prps_cnctr_rt | 매물집중비율 | String | Y | 3 | 0~100 입력 |
| request | cur_prc_entry | 현재가진입 | String | Y | 1 | 0:현재가 매물대 진입 포함안함, 1:현재가 매물대 진입포함 |
| request | prpscnt | 매물대수 | String | Y | 2 | 숫자입력 |
| request | cycle_tp | 주기구분 | String | Y | 2 | 50:50일, 100:100일, 150:150일, 200:200일, 250:250일, 30 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | prps_cnctr | 매물대집중 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - now_trde_qty | 현재거래량 | String | N | 20 |  |
| response | - pric_strt | 가격대시작 | String | N | 20 |  |
| response | - pric_end | 가격대끝 | String | N | 20 |  |
| response | - prps_qty | 매물량 | String | N | 20 |  |
| response | - prps_rt | 매물비 | String | N | 20 |  |

---

### 고저PER요청 (ka10026)

- **API ID**: ka10026
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | pertp | PER구분 | String | Y | 1 | 1:저PBR, 2:고PBR, 3:저PER, 4:고PER, 5:저ROE, 6:고ROE |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | high_low_per | 고저PER | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - per | PER | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - now_trde_qty | 현재거래량 | String | N | 20 |  |
| response | - sel_bid | 매도호가 | String | N | 20 |  |

---

### 전일대비등락률상위요청 (ka10027)

- **API ID**: ka10027
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | sort_tp | 정렬구분 | String | Y | 1 | 1:상승률, 2:상승폭, 3:하락률, 4:하락폭, 5:보합 |
| request | trde_qty_cnd | 거래량조건 | String | Y | 5 | 0000:전체조회, 0010:만주이상, 0050:5만주이상, 0100:10만주이상, 015 |
| request | stk_cnd | 종목조건 | String | Y | 2 | 0:전체조회, 1:관리종목제외, 4:우선주+관리주제외, 3:우선주제외, 5:증100제외,  |
| request | crd_cnd | 신용조건 | String | Y | 1 | 0:전체조회, 1:신용융자A군, 2:신용융자B군, 3:신용융자C군, 4:신용융자D군, 7: |
| request | updown_incls | 상하한포함 | String | Y | 2 | 0:불 포함, 1:포함 |
| request | pric_cnd | 가격조건 | String | Y | 2 | 0:전체조회, 1:1천원미만, 2:1천원~2천원, 3:2천원~5천원, 4:5천원~1만원,  |
| request | trde_prica_cnd | 거래대금조건 | String | Y | 4 | 0:전체조회, 3:3천만원이상, 5:5천만원이상, 10:1억원이상, 30:3억원이상, 50 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | pred_pre_flu_rt_upper | 전일대비등락률상위 | LIST | N |  |  |
| response | - stk_cls | 종목분류 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - sel_req | 매도잔량 | String | N | 20 |  |
| response | - buy_req | 매수잔량 | String | N | 20 |  |
| response | - now_trde_qty | 현재거래량 | String | N | 20 |  |
| response | - cntr_str | 체결강도 | String | N | 20 |  |
| response | - cnt | 횟수 | String | N | 20 |  |

---

### 시가대비등락률요청 (ka10028)

- **API ID**: ka10028
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | sort_tp | 정렬구분 | String | Y | 1 | 1:시가, 2:고가, 3:저가, 4:기준가 |
| request | trde_qty_cnd | 거래량조건 | String | Y | 4 | 0000:전체조회, 0010:만주이상, 0050:5만주이상, 0100:10만주이상, 050 |
| request | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | updown_incls | 상하한포함 | String | Y | 1 | 0:불 포함, 1:포함 |
| request | stk_cnd | 종목조건 | String | Y | 2 | 0:전체조회, 1:관리종목제외, 4:우선주+관리주제외, 3:우선주제외, 5:증100제외,  |
| request | crd_cnd | 신용조건 | String | Y | 1 | 0:전체조회, 1:신용융자A군, 2:신용융자B군, 3:신용융자C군, 4:신용융자D군, 7: |
| request | trde_prica_cnd | 거래대금조건 | String | Y | 4 | 0:전체조회, 3:3천만원이상, 5:5천만원이상, 10:1억원이상, 30:3억원이상, 50 |
| request | flu_cnd | 등락조건 | String | Y | 1 | 1:상위, 2:하위 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | open_pric_pre_flu_rt | 시가대비등락률 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |
| response | - open_pric_pre | 시가대비 | String | N | 20 |  |
| response | - now_trde_qty | 현재거래량 | String | N | 20 |  |
| response | - cntr_str | 체결강도 | String | N | 20 |  |

---

### 예상체결등락률상위요청 (ka10029)

- **API ID**: ka10029
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | sort_tp | 정렬구분 | String | Y | 1 | 1:상승률, 2:상승폭, 3:보합, 4:하락률, 5:하락폭, 6:체결량, 7:상한, 8:하 |
| request | trde_qty_cnd | 거래량조건 | String | Y | 5 | 0:전체조회, 1;천주이상, 3:3천주, 5:5천주, 10:만주이상, 50:5만주이상, 1 |
| request | stk_cnd | 종목조건 | String | Y | 2 | 0:전체조회, 1:관리종목제외, 3:우선주제외, 4:관리종목,우선주제외, 5:증100제외, |
| request | crd_cnd | 신용조건 | String | Y | 1 | 0:전체조회, 1:신용융자A군, 2:신용융자B군, 3:신용융자C군, 4:신용융자D군, 5: |
| request | pric_cnd | 가격조건 | String | Y | 2 | 0:전체조회, 1:1천원미만, 2:1천원~2천원, 3:2천원~5천원, 4:5천원~1만원,  |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | exp_cntr_flu_rt_upper | 예상체결등락률상위 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - exp_cntr_pric | 예상체결가 | String | N | 20 |  |
| response | - base_pric | 기준가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - exp_cntr_qty | 예상체결량 | String | N | 20 |  |
| response | - sel_req | 매도잔량 | String | N | 20 |  |
| response | - sel_bid | 매도호가 | String | N | 20 |  |
| response | - buy_bid | 매수호가 | String | N | 20 |  |
| response | - buy_req | 매수잔량 | String | N | 20 |  |

---

### 당일거래량상위요청 (ka10030)

- **API ID**: ka10030
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | sort_tp | 정렬구분 | String | Y | 1 | 1:거래량, 2:거래회전율, 3:거래대금 |
| request | mang_stk_incls | 관리종목포함 | String | Y | 1 | 0:관리종목 포함, 1:관리종목 미포함, 3:우선주제외, 11:정리매매종목제외, 4:관리종 |
| request | crd_tp | 신용구분 | String | Y | 1 | 0:전체조회, 9:신용융자전체, 1:신용융자A군, 2:신용융자B군, 3:신용융자C군, 4: |
| request | trde_qty_tp | 거래량구분 | String | Y | 1 | 0:전체조회, 5:5천주이상, 10:1만주이상, 50:5만주이상, 100:10만주이상, 2 |
| request | pric_tp | 가격구분 | String | Y | 1 | 0:전체조회, 1:1천원미만, 2:1천원이상, 3:1천원~2천원, 4:2천원~5천원, 5: |
| request | trde_prica_tp | 거래대금구분 | String | Y | 1 | 0:전체조회, 1:1천만원이상, 3:3천만원이상, 4:5천만원이상, 10:1억원이상, 30 |
| request | mrkt_open_tp | 장운영구분 | String | Y | 1 | 0:전체조회, 1:장중, 2:장전시간외, 3:장후시간외 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | tdy_trde_qty_upper | 당일거래량상위 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - pred_rt | 전일비 | String | N | 20 |  |
| response | - trde_tern_rt | 거래회전율 | String | N | 20 |  |
| response | - trde_amt | 거래금액 | String | N | 20 |  |
| response | - opmr_trde_qty | 장중거래량 | String | N | 20 |  |
| response | - opmr_pred_rt | 장중전일비 | String | N | 20 |  |
| response | - opmr_trde_rt | 장중거래회전율 | String | N | 20 |  |
| response | - opmr_trde_amt | 장중거래금액 | String | N | 20 |  |
| response | - af_mkrt_trde_qty | 장후거래량 | String | N | 20 |  |
| response | - af_mkrt_pred_rt | 장후전일비 | String | N | 20 |  |

> ... 외 6개 필드

---

### 전일거래량상위요청 (ka10031)

- **API ID**: ka10031
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | qry_tp | 조회구분 | String | Y | 1 | 1:전일거래량 상위100종목, 2:전일거래대금 상위100종목 |
| request | rank_strt | 순위시작 | String | Y | 3 | 0 ~ 100 값 중에  조회를 원하는 순위 시작값 |
| request | rank_end | 순위끝 | String | Y | 3 | 0 ~ 100 값 중에  조회를 원하는 순위 끝값 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | pred_trde_qty_upper | 전일거래량상위 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |

---

### 거래대금상위요청 (ka10032)

- **API ID**: ka10032
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | mang_stk_incls | 관리종목포함 | String | Y | 1 | 0:관리종목 미포함, 1:관리종목 포함 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | trde_prica_upper | 거래대금상위 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - now_rank | 현재순위 | String | N | 20 |  |
| response | - pred_rank | 전일순위 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - sel_bid | 매도호가 | String | N | 20 |  |
| response | - buy_bid | 매수호가 | String | N | 20 |  |
| response | - now_trde_qty | 현재거래량 | String | N | 20 |  |
| response | - pred_trde_qty | 전일거래량 | String | N | 20 |  |
| response | - trde_prica | 거래대금 | String | N | 20 |  |

---

### 신용비율상위요청 (ka10033)

- **API ID**: ka10033
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | trde_qty_tp | 거래량구분 | String | Y | 3 | 0:전체조회, 10:만주이상, 50:5만주이상, 100:10만주이상, 200:20만주이상, |
| request | stk_cnd | 종목조건 | String | Y | 1 | 0:전체조회, 1:관리종목제외, 5:증100제외, 6:증100만보기, 7:증40만보기, 8 |
| request | updown_incls | 상하한포함 | String | Y | 1 | 0:상하한 미포함, 1:상하한포함 |
| request | crd_cnd | 신용조건 | String | Y | 1 | 0:전체조회, 1:신용융자A군, 2:신용융자B군, 3:신용융자C군, 4:신용융자D군, 7: |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | crd_rt_upper | 신용비율상위 | LIST | N |  |  |
| response | - stk_infr | 종목정보 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - crd_rt | 신용비율 | String | N | 20 |  |
| response | - sel_req | 매도잔량 | String | N | 20 |  |
| response | - buy_req | 매수잔량 | String | N | 20 |  |
| response | - now_trde_qty | 현재거래량 | String | N | 20 |  |

---

### 외인기간별매매상위요청 (ka10034)

- **API ID**: ka10034
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | trde_tp | 매매구분 | String | Y | 1 | 1:순매도, 2:순매수, 3:순매매 |
| request | dt | 기간 | String | Y | 2 | 0:당일, 1:전일, 5:5일, 10;10일, 20:20일, 60:60일 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT, 3:통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | for_dt_trde_upper | 외인기간별매매상위 | LIST | N |  |  |
| response | - rank | 순위 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - sel_bid | 매도호가 | String | N | 20 |  |
| response | - buy_bid | 매수호가 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - netprps_qty | 순매수량 | String | N | 20 |  |
| response | - gain_pos_stkcnt | 취득가능주식수 | String | N | 20 |  |

---

### 외인연속순매매상위요청 (ka10035)

- **API ID**: ka10035
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | trde_tp | 매매구분 | String | Y | 1 | 1:연속순매도, 2:연속순매수 |
| request | base_dt_tp | 기준일구분 | String | Y | 1 | 0:당일기준, 1:전일기준 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT, 3:통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | for_cont_nettrde_upper | 외인연속순매매상위 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - dm1 | D-1 | String | N | 20 |  |
| response | - dm2 | D-2 | String | N | 20 |  |
| response | - dm3 | D-3 | String | N | 20 |  |
| response | - tot | 합계 | String | N | 20 |  |
| response | - limit_exh_rt | 한도소진율 | String | N | 20 |  |
| response | - pred_pre_1 | 전일대비1 | String | N | 20 |  |
| response | - pred_pre_2 | 전일대비2 | String | N | 20 |  |
| response | - pred_pre_3 | 전일대비3 | String | N | 20 |  |

---

### 외인한도소진율증가상위 (ka10036)

- **API ID**: ka10036
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | dt | 기간 | String | Y | 2 | 0:당일, 1:전일, 5:5일, 10;10일, 20:20일, 60:60일 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT, 3:통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | for_limit_exh_rt_incrs_upper | 외인한도소진율증가상위 | LIST | N |  |  |
| response | - rank | 순위 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - poss_stkcnt | 보유주식수 | String | N | 20 |  |
| response | - gain_pos_stkcnt | 취득가능주식수 | String | N | 20 |  |
| response | - base_limit_exh_rt | 기준한도소진율 | String | N | 20 |  |
| response | - limit_exh_rt | 한도소진율 | String | N | 20 |  |
| response | - exh_rt_incrs | 소진율증가 | String | N | 20 |  |

---

### 외국계창구매매상위요청 (ka10037)

- **API ID**: ka10037
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | dt | 기간 | String | Y | 2 | 0:당일, 1:전일, 5:5일, 10;10일, 20:20일, 60:60일 |
| request | trde_tp | 매매구분 | String | Y | 1 | 1:순매수, 2:순매도, 3:매수, 4:매도 |
| request | sort_tp | 정렬구분 | String | Y | 1 | 1:금액, 2:수량 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT, 3:통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | frgn_wicket_trde_upper | 외국계창구매매상위 | LIST | N |  |  |
| response | - rank | 순위 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - sel_trde_qty | 매도거래량 | String | N | 20 |  |
| response | - buy_trde_qty | 매수거래량 | String | N | 20 |  |
| response | - netprps_trde_qty | 순매수거래량 | String | N | 20 |  |
| response | - netprps_prica | 순매수대금 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - trde_prica | 거래대금 | String | N | 20 |  |

---

### 종목별증권사순위요청 (ka10038)

- **API ID**: ka10038
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | strt_dt | 시작일자 | String | Y | 8 | YYYYMMDD
(연도4자리, 월 2자리, 일 2자리 형식) |
| request | end_dt | 종료일자 | String | Y | 8 | YYYYMMDD
(연도4자리, 월 2자리, 일 2자리 형식) |
| request | qry_tp | 조회구분 | String | Y | 1 | 1:순매도순위정렬, 2:순매수순위정렬 |
| request | dt | 기간 | String | Y | 2 | 1:전일, 4:5일, 9:10일, 19:20일, 39:40일, 59:60일, 119:120 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | rank_1 | 순위1 | String | N | 20 |  |
| response | rank_2 | 순위2 | String | N | 20 |  |
| response | rank_3 | 순위3 | String | N | 20 |  |
| response | prid_trde_qty | 기간중거래량 | String | N | 20 |  |
| response | stk_sec_rank | 종목별증권사순위 | LIST | N |  |  |
| response | - rank | 순위 | String | N | 20 |  |
| response | - mmcm_nm | 회원사명 | String | N | 20 |  |
| response | - buy_qty | 매수수량 | String | N | 20 |  |
| response | - sell_qty | 매도수량 | String | N | 20 |  |
| response | - acc_netprps_qty | 누적순매수수량 | String | N | 20 |  |

---

### 증권사별매매상위요청 (ka10039)

- **API ID**: ka10039
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mmcm_cd | 회원사코드 | String | Y | 3 | 회원사 코드는 ka10102 조회 |
| request | trde_qty_tp | 거래량구분 | String | Y | 4 | 0:전체, 5:5000주, 10:1만주, 50:5만주, 100:10만주, 500:50만주, |
| request | trde_tp | 매매구분 | String | Y | 2 | 1:순매수, 2:순매도 |
| request | dt | 기간 | String | Y | 2 | 1:전일, 5:5일, 10:10일, 60:60일 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | sec_trde_upper | 증권사별매매상위 | LIST | N |  |  |
| response | - rank | 순위 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - prid_stkpc_flu | 기간중주가등락 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - prid_trde_qty | 기간중거래량 | String | N | 20 |  |
| response | - netprps | 순매수 | String | N | 20 |  |
| response | - buy_trde_qty | 매수거래량 | String | N | 20 |  |
| response | - sel_trde_qty | 매도거래량 | String | N | 20 |  |
| response | - netprps_amt | 순매수금액 | String | N | 20 |  |
| response | - buy_amt | 매수금액 | String | N | 20 |  |
| response | - sell_amt | 매도금액 | String | N | 20 |  |

---

### 당일주요거래원요청 (ka10040)

- **API ID**: ka10040
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | sel_trde_ori_irds_1 | 매도거래원별증감1 | String | N |  |  |
| response | sel_trde_ori_qty_1 | 매도거래원수량1 | String | N |  |  |
| response | sel_trde_ori_1 | 매도거래원1 | String | N |  |  |
| response | sel_trde_ori_cd_1 | 매도거래원코드1 | String | N |  |  |
| response | buy_trde_ori_1 | 매수거래원1 | String | N |  |  |
| response | buy_trde_ori_cd_1 | 매수거래원코드1 | String | N |  |  |
| response | buy_trde_ori_qty_1 | 매수거래원수량1 | String | N |  |  |
| response | buy_trde_ori_irds_1 | 매수거래원별증감1 | String | N |  |  |
| response | sel_trde_ori_irds_2 | 매도거래원별증감2 | String | N |  |  |
| response | sel_trde_ori_qty_2 | 매도거래원수량2 | String | N |  |  |
| response | sel_trde_ori_2 | 매도거래원2 | String | N |  |  |
| response | sel_trde_ori_cd_2 | 매도거래원코드2 | String | N |  |  |
| response | buy_trde_ori_2 | 매수거래원2 | String | N |  |  |
| response | buy_trde_ori_cd_2 | 매수거래원코드2 | String | N |  |  |
| response | buy_trde_ori_qty_2 | 매수거래원수량2 | String | N |  |  |
| response | buy_trde_ori_irds_2 | 매수거래원별증감2 | String | N |  |  |
| response | sel_trde_ori_irds_3 | 매도거래원별증감3 | String | N |  |  |

> ... 외 36개 필드

---

### 순매수거래원순위요청 (ka10042)

- **API ID**: ka10042
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | strt_dt | 시작일자 | String | N | 8 | YYYYMMDD
(연도4자리, 월 2자리, 일 2자리 형식) |
| request | end_dt | 종료일자 | String | N | 8 | YYYYMMDD
(연도4자리, 월 2자리, 일 2자리 형식) |
| request | qry_dt_tp | 조회기간구분 | String | Y | 1 | 0:기간으로 조회, 1:시작일자, 종료일자로 조회 |
| request | pot_tp | 시점구분 | String | Y | 1 | 0:당일, 1:전일 |
| request | dt | 기간 | String | N | 4 | 5:5일, 10:10일, 20:20일, 40:40일, 60:60일, 120:120일 |
| request | sort_base | 정렬기준 | String | Y | 1 | 1:종가순, 2:날짜순 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | netprps_trde_ori_rank | 순매수거래원순위 | LIST | N |  |  |
| response | - rank | 순위 | String | N | 20 |  |
| response | - mmcm_cd | 회원사코드 | String | N | 20 |  |
| response | - mmcm_nm | 회원사명 | String | N | 20 |  |

---

### 거래원매물대분석요청 (ka10043)

- **API ID**: ka10043
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | strt_dt | 시작일자 | String | Y | 8 | YYYYMMDD |
| request | end_dt | 종료일자 | String | Y | 8 | YYYYMMDD |
| request | qry_dt_tp | 조회기간구분 | String | Y | 1 | 0:기간으로 조회, 1:시작일자, 종료일자로 조회 |
| request | pot_tp | 시점구분 | String | Y | 1 | 0:당일, 1:전일 |
| request | dt | 기간 | String | Y | 4 | 5:5일, 10:10일, 20:20일, 40:40일, 60:60일, 120:120일 |
| request | sort_base | 정렬기준 | String | Y | 1 | 1:종가순, 2:날짜순 |
| request | mmcm_cd | 회원사코드 | String | Y | 3 | 회원사 코드는 ka10102 조회 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | trde_ori_prps_anly | 거래원매물대분석 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - close_pric | 종가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - sel_qty | 매도량 | String | N | 20 |  |
| response | - buy_qty | 매수량 | String | N | 20 |  |
| response | - netprps_qty | 순매수수량 | String | N | 20 |  |
| response | - trde_qty_sum | 거래량합 | String | N | 20 |  |
| response | - trde_wght | 거래비중 | String | N | 20 |  |

---

### 일별기관매매종목요청 (ka10044)

- **API ID**: ka10044
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | strt_dt | 시작일자 | String | Y | 8 | YYYYMMDD |
| request | end_dt | 종료일자 | String | Y | 8 | YYYYMMDD |
| request | trde_tp | 매매구분 | String | Y | 1 | 1:순매도, 2:순매수 |
| request | mrkt_tp | 시장구분 | String | Y | 3 | 001:코스피, 101:코스닥 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | daly_orgn_trde_stk | 일별기관매매종목 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - netprps_qty | 순매수수량 | String | N | 20 |  |
| response | - netprps_amt | 순매수금액 | String | N | 20 |  |

---

### 종목별기관매매추이요청 (ka10045)

- **API ID**: ka10045
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | strt_dt | 시작일자 | String | Y | 8 | YYYYMMDD |
| request | end_dt | 종료일자 | String | Y | 8 | YYYYMMDD |
| request | orgn_prsm_unp_tp | 기관추정단가구분 | String | Y | 1 | 1:매수단가, 2:매도단가 |
| request | for_prsm_unp_tp | 외인추정단가구분 | String | Y | 1 | 1:매수단가, 2:매도단가 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | orgn_prsm_avg_pric | 기관추정평균가 | String | N |  |  |
| response | for_prsm_avg_pric | 외인추정평균가 | String | N |  |  |
| response | stk_orgn_trde_trnsn | 종목별기관매매추이 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - close_pric | 종가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - orgn_dt_acc | 기관기간누적 | String | N | 20 |  |
| response | - orgn_daly_nettrde_qty | 기관일별순매매수량 | String | N | 20 |  |
| response | - for_dt_acc | 외인기간누적 | String | N | 20 |  |
| response | - for_daly_nettrde_qty | 외인일별순매매수량 | String | N | 20 |  |
| response | - limit_exh_rt | 한도소진율 | String | N | 20 |  |

---

### 체결강도추이시간별요청 (ka10046)

- **API ID**: ka10046
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | cntr_str_tm | 체결강도시간별 | LIST | N |  |  |
| response | - cntr_tm | 체결시간 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - acc_trde_prica | 누적거래대금 | String | N | 20 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - cntr_str | 체결강도 | String | N | 20 |  |
| response | - cntr_str_5min | 체결강도5분 | String | N | 20 |  |
| response | - cntr_str_20min | 체결강도20분 | String | N | 20 |  |
| response | - cntr_str_60min | 체결강도60분 | String | N | 20 |  |
| response | - stex_tp | 거래소구분 | String | N | 20 |  |

---

### 체결강도추이일별요청 (ka10047)

- **API ID**: ka10047
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | cntr_str_daly | 체결강도일별 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - acc_trde_prica | 누적거래대금 | String | N | 20 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - cntr_str | 체결강도 | String | N | 20 |  |
| response | - cntr_str_5min | 체결강도5일 | String | N | 20 |  |
| response | - cntr_str_20min | 체결강도20일 | String | N | 20 |  |
| response | - cntr_str_60min | 체결강도60일 | String | N | 20 |  |

---

### ELW일별민감도지표요청 (ka10048)

- **API ID**: ka10048
- **Method**: POST
- **URL**: /api/dostk/elw
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | elwdaly_snst_ix | ELW일별민감도지표 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - iv | IV | String | N | 20 |  |
| response | - delta | 델타 | String | N | 20 |  |
| response | - gam | 감마 | String | N | 20 |  |
| response | - theta | 쎄타 | String | N | 20 |  |
| response | - vega | 베가 | String | N | 20 |  |
| response | - law | 로 | String | N | 20 |  |
| response | - lp | LP | String | N | 20 |  |

---

### ELW민감도지표요청 (ka10050)

- **API ID**: ka10050
- **Method**: POST
- **URL**: /api/dostk/elw
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | elwsnst_ix_array | ELW민감도지표배열 | LIST | N |  |  |
| response | - cntr_tm | 체결시간 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - elwtheory_pric | ELW이론가 | String | N | 20 |  |
| response | - iv | IV | String | N | 20 |  |
| response | - delta | 델타 | String | N | 20 |  |
| response | - gam | 감마 | String | N | 20 |  |
| response | - theta | 쎄타 | String | N | 20 |  |
| response | - vega | 베가 | String | N | 20 |  |
| response | - law | 로 | String | N | 20 |  |
| response | - lp | LP | String | N | 20 |  |

---

### 업종별투자자순매수요청 (ka10051)

- **API ID**: ka10051
- **Method**: POST
- **URL**: /api/dostk/sect
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 1 | 코스피:0, 코스닥:1 |
| request | amt_qty_tp | 금액수량구분 | String | Y | 1 | 금액:0, 수량:1 |
| request | base_dt | 기준일자 | String | N | 8 | YYYYMMDD |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT, 3:통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | inds_netprps | 업종별순매수 | LIST | N |  |  |
| response | - inds_cd | 업종코드 | String | N | 20 |  |
| response | - inds_nm | 업종명 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_smbol | 대비부호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - sc_netprps | 증권순매수 | String | N | 20 |  |
| response | - insrnc_netprps | 보험순매수 | String | N | 20 |  |
| response | - invtrt_netprps | 투신순매수 | String | N | 20 |  |
| response | - bank_netprps | 은행순매수 | String | N | 20 |  |
| response | - jnsinkm_netprps | 종신금순매수 | String | N | 20 |  |
| response | - endw_netprps | 기금순매수 | String | N | 20 |  |
| response | - etc_corp_netprps | 기타법인순매수 | String | N | 20 |  |
| response | - ind_netprps | 개인순매수 | String | N | 20 |  |
| response | - frgnr_netprps | 외국인순매수 | String | N | 20 |  |

> ... 외 4개 필드

---

### 거래원순간거래량요청 (ka10052)

- **API ID**: ka10052
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mmcm_cd | 회원사코드 | String | Y | 3 | 회원사 코드는 ka10102 조회 |
| request | stk_cd | 종목코드 | String | N | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | mrkt_tp | 시장구분 | String | Y | 1 | 0:전체, 1:코스피, 2:코스닥, 3:종목 |
| request | qty_tp | 수량구분 | String | Y | 3 | 0:전체, 1:1000주, 2:2000주, 3:, 5:, 10:10000주, 30: 300 |
| request | pric_tp | 가격구분 | String | Y | 1 | 0:전체, 1:1천원 미만, 8:1천원 이상, 2:1천원 ~ 2천원, 3:2천원 ~ 5천원 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | trde_ori_mont_trde_qty | 거래원순간거래량 | LIST | N |  |  |
| response | - tm | 시간 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 20 |  |
| response | - trde_ori_nm | 거래원명 | String | N | 20 |  |
| response | - tp | 구분 | String | N | 20 |  |
| response | - mont_trde_qty | 순간거래량 | String | N | 20 |  |
| response | - acc_netprps | 누적순매수 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |

---

### 당일상위이탈원요청 (ka10053)

- **API ID**: ka10053
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | tdy_upper_scesn_ori | 당일상위이탈원 | LIST | N |  |  |
| response | - sel_scesn_tm | 매도이탈시간 | String | N | 20 |  |
| response | - sell_qty | 매도수량 | String | N | 20 |  |
| response | - sel_upper_scesn_ori | 매도상위이탈원 | String | N | 20 |  |
| response | - buy_scesn_tm | 매수이탈시간 | String | N | 20 |  |
| response | - buy_qty | 매수수량 | String | N | 20 |  |
| response | - buy_upper_scesn_ori | 매수상위이탈원 | String | N | 20 |  |
| response | - qry_dt | 조회일자 | String | N | 20 |  |
| response | - qry_tm | 조회시간 | String | N | 20 |  |

---

### 변동성완화장치발동종목요청 (ka10054)

- **API ID**: ka10054
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001: 코스피, 101:코스닥 |
| request | bf_mkrt_tp | 장전구분 | String | Y | 1 | 0:전체, 1:정규시장,2:시간외단일가 |
| request | stk_cd | 종목코드 | String | N | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | motn_tp | 발동구분 | String | Y | 1 | 0:전체, 1:정적VI, 2:동적VI, 3:동적VI + 정적VI |
| request | skip_stk | 제외종목 | String | Y | 9 | 전종목포함 조회시 9개 0으로 설정(000000000),전종목제외 조회시 9개 1으로 설정 |
| request | trde_qty_tp | 거래량구분 | String | Y | 1 | 0:사용안함, 1:사용 |
| request | min_trde_qty | 최소거래량 | String | Y | 12 | 0 주 이상, 거래량구분이 1일때만 입력(공백허용) |
| request | max_trde_qty | 최대거래량 | String | Y | 12 | 100000000 주 이하, 거래량구분이 1일때만 입력(공백허용) |
| request | trde_prica_tp | 거래대금구분 | String | Y | 1 | 0:사용안함, 1:사용 |
| request | min_trde_prica | 최소거래대금 | String | Y | 10 | 0 백만원 이상, 거래대금구분 1일때만 입력(공백허용) |
| request | max_trde_prica | 최대거래대금 | String | Y | 10 | 100000000 백만원 이하, 거래대금구분 1일때만 입력(공백허용) |
| request | motn_drc | 발동방향 | String | Y | 1 | 0:전체, 1:상승, 2:하락 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | motn_stk | 발동종목 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - motn_pric | 발동가격 | String | N | 20 |  |
| response | - dynm_dispty_rt | 동적괴리율 | String | N | 20 |  |
| response | - trde_cntr_proc_time | 매매체결처리시각 | String | N | 20 |  |
| response | - virelis_time | VI해제시각 | String | N | 20 |  |
| response | - viaplc_tp | VI적용구분 | String | N | 20 |  |
| response | - dynm_stdpc | 동적기준가격 | String | N | 20 |  |
| response | - static_stdpc | 정적기준가격 | String | N | 20 |  |
| response | - static_dispty_rt | 정적괴리율 | String | N | 20 |  |
| response | - open_pric_pre_flu_rt | 시가대비등락률 | String | N | 20 |  |
| response | - vimotn_cnt | VI발동횟수 | String | N | 20 |  |
| response | - stex_tp | 거래소구분 | String | N | 20 |  |

---

### 당일전일체결량요청 (ka10055)

- **API ID**: ka10055
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | tdy_pred | 당일전일 | String | Y | 1 | 1:당일, 2:전일 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | tdy_pred_cntr_qty | 당일전일체결량 | LIST | N |  |  |
| response | - cntr_tm | 체결시간 | String | N | 20 |  |
| response | - cntr_pric | 체결가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - cntr_qty | 체결량 | String | N | 20 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - acc_trde_prica | 누적거래대금 | String | N | 20 |  |

---

### 투자자별일별매매종목요청 (ka10058)

- **API ID**: ka10058
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | strt_dt | 시작일자 | String | Y | 8 | YYYYMMDD |
| request | end_dt | 종료일자 | String | Y | 8 | YYYYMMDD |
| request | trde_tp | 매매구분 | String | Y | 1 | 순매도:1, 순매수:2 |
| request | mrkt_tp | 시장구분 | String | Y | 3 | 001:코스피, 101:코스닥 |
| request | invsr_tp | 투자자구분 | String | Y | 4 | 8000:개인, 9000:외국인, 1000:금융투자, 3000:투신, 5000:기타금융,  |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | invsr_daly_trde_stk | 투자자별일별매매종목 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - netslmt_qty | 순매도수량 | String | N | 20 |  |
| response | - netslmt_amt | 순매도금액 | String | N | 20 |  |
| response | - prsm_avg_pric | 추정평균가 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - avg_pric_pre | 평균가대비 | String | N | 20 |  |
| response | - pre_rt | 대비율 | String | N | 20 |  |
| response | - dt_trde_qty | 기간거래량 | String | N | 20 |  |

---

### 종목별투자자기관별요청 (ka10059)

- **API ID**: ka10059
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | dt | 일자 | String | Y | 8 | YYYYMMDD |
| request | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | amt_qty_tp | 금액수량구분 | String | Y | 1 | 1:금액, 2:수량 |
| request | trde_tp | 매매구분 | String | Y | 1 | 0:순매수, 1:매수, 2:매도 |
| request | unit_tp | 단위구분 | String | Y | 4 | 1000:천주, 1:단주 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_invsr_orgn | 종목별투자자기관별 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 | 우측 2자리 소수점자리수 |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - acc_trde_prica | 누적거래대금 | String | N | 20 |  |
| response | - ind_invsr | 개인투자자 | String | N | 20 |  |
| response | - frgnr_invsr | 외국인투자자 | String | N | 20 |  |
| response | - orgn | 기관계 | String | N | 20 |  |
| response | - fnnc_invt | 금융투자 | String | N | 20 |  |
| response | - insrnc | 보험 | String | N | 20 |  |
| response | - invtrt | 투신 | String | N | 20 |  |
| response | - etc_fnnc | 기타금융 | String | N | 20 |  |
| response | - bank | 은행 | String | N | 20 |  |
| response | - penfnd_etc | 연기금등 | String | N | 20 |  |

> ... 외 4개 필드

---

### 종목별투자자기관별차트요청 (ka10060)

- **API ID**: ka10060
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | dt | 일자 | String | Y | 8 | YYYYMMDD |
| request | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | amt_qty_tp | 금액수량구분 | String | Y | 1 | 1:금액, 2:수량 |
| request | trde_tp | 매매구분 | String | Y | 1 | 0:순매수, 1:매수, 2:매도 |
| request | unit_tp | 단위구분 | String | Y | 4 | 1000:천주, 1:단주 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_invsr_orgn_chart | 종목별투자자기관별차트 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - acc_trde_prica | 누적거래대금 | String | N | 20 |  |
| response | - ind_invsr | 개인투자자 | String | N | 20 |  |
| response | - frgnr_invsr | 외국인투자자 | String | N | 20 |  |
| response | - orgn | 기관계 | String | N | 20 |  |
| response | - fnnc_invt | 금융투자 | String | N | 20 |  |
| response | - insrnc | 보험 | String | N | 20 |  |
| response | - invtrt | 투신 | String | N | 20 |  |
| response | - etc_fnnc | 기타금융 | String | N | 20 |  |
| response | - bank | 은행 | String | N | 20 |  |
| response | - penfnd_etc | 연기금등 | String | N | 20 |  |
| response | - samo_fund | 사모펀드 | String | N | 20 |  |
| response | - natn | 국가 | String | N | 20 |  |
| response | - etc_corp | 기타법인 | String | N | 20 |  |

> ... 외 1개 필드

---

### 종목별투자자기관별합계요청 (ka10061)

- **API ID**: ka10061
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | strt_dt | 시작일자 | String | Y | 8 | YYYYMMDD |
| request | end_dt | 종료일자 | String | Y | 8 | YYYYMMDD |
| request | amt_qty_tp | 금액수량구분 | String | Y | 1 | 1:금액, 2:수량 |
| request | trde_tp | 매매구분 | String | Y | 1 | 0:순매수 |
| request | unit_tp | 단위구분 | String | Y | 4 | 1000:천주, 1:단주 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_invsr_orgn_tot | 종목별투자자기관별합계 | LIST | N |  |  |
| response | - ind_invsr | 개인투자자 | String | N | 20 |  |
| response | - frgnr_invsr | 외국인투자자 | String | N | 20 |  |
| response | - orgn | 기관계 | String | N | 20 |  |
| response | - fnnc_invt | 금융투자 | String | N | 20 |  |
| response | - insrnc | 보험 | String | N | 20 |  |
| response | - invtrt | 투신 | String | N | 20 |  |
| response | - etc_fnnc | 기타금융 | String | N | 20 |  |
| response | - bank | 은행 | String | N | 20 |  |
| response | - penfnd_etc | 연기금등 | String | N | 20 |  |
| response | - samo_fund | 사모펀드 | String | N | 20 |  |
| response | - natn | 국가 | String | N | 20 |  |
| response | - etc_corp | 기타법인 | String | N | 20 |  |
| response | - natfor | 내외국인 | String | N | 20 |  |

---

### 동일순매매순위요청 (ka10062)

- **API ID**: ka10062
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | strt_dt | 시작일자 | String | Y | 8 | YYYYMMDD
(연도4자리, 월 2자리, 일 2자리 형식) |
| request | end_dt | 종료일자 | String | N | 8 | YYYYMMDD
(연도4자리, 월 2자리, 일 2자리 형식) |
| request | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001: 코스피, 101:코스닥 |
| request | trde_tp | 매매구분 | String | Y | 1 | 1:순매수, 2:순매도 |
| request | sort_cnd | 정렬조건 | String | Y | 1 | 1:수량, 2:금액 |
| request | unit_tp | 단위구분 | String | Y | 1 | 1:단주, 1000:천주 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | eql_nettrde_rank | 동일순매매순위 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - rank | 순위 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - orgn_nettrde_qty | 기관순매매수량 | String | N | 20 |  |
| response | - orgn_nettrde_amt | 기관순매매금액 | String | N | 20 |  |
| response | - orgn_nettrde_avg_pric | 기관순매매평균가 | String | N | 20 |  |
| response | - for_nettrde_qty | 외인순매매수량 | String | N | 20 |  |
| response | - for_nettrde_amt | 외인순매매금액 | String | N | 20 |  |
| response | - for_nettrde_avg_pric | 외인순매매평균가 | String | N | 20 |  |
| response | - nettrde_qty | 순매매수량 | String | N | 20 |  |
| response | - nettrde_amt | 순매매금액 | String | N | 20 |  |

---

### 장중투자자별매매요청 (ka10063)

- **API ID**: ka10063
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | amt_qty_tp | 금액수량구분 | String | Y | 1 | 1: 금액&수량 |
| request | invsr | 투자자별 | String | Y | 1 | 6:외국인, 7:기관계, 1:투신, 0:보험, 2:은행, 3:연기금, 4:국가, 5:기타법 |
| request | frgn_all | 외국계전체 | String | Y | 1 | 1:체크, 0:미체크 |
| request | smtm_netprps_tp | 동시순매수구분 | String | Y | 1 | 1:체크, 0:미체크 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | opmr_invsr_trde | 장중투자자별매매 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - netprps_amt | 순매수금액 | String | N | 20 |  |
| response | - prev_netprps_amt | 이전순매수금액 | String | N | 20 |  |
| response | - buy_amt | 매수금액 | String | N | 20 |  |
| response | - netprps_amt_irds | 순매수금액증감 | String | N | 20 |  |
| response | - buy_amt_irds | 매수금액증감 | String | N | 20 |  |
| response | - sell_amt | 매도금액 | String | N | 20 |  |
| response | - sell_amt_irds | 매도금액증감 | String | N | 20 |  |
| response | - netprps_qty | 순매수수량 | String | N | 20 |  |
| response | - prev_pot_netprps_qty | 이전시점순매수수량 | String | N | 20 |  |

> ... 외 5개 필드

---

### 장중투자자별매매차트요청 (ka10064)

- **API ID**: ka10064
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | amt_qty_tp | 금액수량구분 | String | Y | 1 | 1:금액, 2:수량 |
| request | trde_tp | 매매구분 | String | Y | 1 | 0:순매수, 1:매수, 2:매도 |
| request | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | opmr_invsr_trde_chart | 장중투자자별매매차트 | LIST | N |  |  |
| response | - tm | 시간 | String | N | 20 |  |
| response | - frgnr_invsr | 외국인투자자 | String | N | 20 |  |
| response | - orgn | 기관계 | String | N | 20 |  |
| response | - invtrt | 투신 | String | N | 20 |  |
| response | - insrnc | 보험 | String | N | 20 |  |
| response | - bank | 은행 | String | N | 20 |  |
| response | - penfnd_etc | 연기금등 | String | N | 20 |  |
| response | - etc_corp | 기타법인 | String | N | 20 |  |
| response | - natn | 국가 | String | N | 20 |  |

---

### 장중투자자별매매상위요청 (ka10065)

- **API ID**: ka10065
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | trde_tp | 매매구분 | String | Y | 1 | 1:순매수, 2:순매도 |
| request | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | orgn_tp | 기관구분 | String | Y | 4 | 9000:외국인, 9100:외국계, 1000:금융투자, 3000:투신, 5000:기타금융, |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | opmr_invsr_trde_upper | 장중투자자별매매상위 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - sel_qty | 매도량 | String | N | 20 |  |
| response | - buy_qty | 매수량 | String | N | 20 |  |
| response | - netslmt | 순매도 | String | N | 20 |  |

---

### 장마감후투자자별매매요청 (ka10066)

- **API ID**: ka10066
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | amt_qty_tp | 금액수량구분 | String | Y | 1 | 1:금액, 2:수량 |
| request | trde_tp | 매매구분 | String | Y | 1 | 0:순매수, 1:매수, 2:매도 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | opaf_invsr_trde | 장중투자자별매매차트 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - ind_invsr | 개인투자자 | String | N | 20 |  |
| response | - frgnr_invsr | 외국인투자자 | String | N | 20 |  |
| response | - orgn | 기관계 | String | N | 20 |  |
| response | - fnnc_invt | 금융투자 | String | N | 20 |  |
| response | - insrnc | 보험 | String | N | 20 |  |
| response | - invtrt | 투신 | String | N | 20 |  |
| response | - etc_fnnc | 기타금융 | String | N | 20 |  |
| response | - bank | 은행 | String | N | 20 |  |
| response | - penfnd_etc | 연기금등 | String | N | 20 |  |

> ... 외 3개 필드

---

### 대차거래추이요청 (ka10068)

- **API ID**: ka10068
- **Method**: POST
- **URL**: /api/dostk/slb
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | strt_dt | 시작일자 | String | N | 8 | YYYYMMDD |
| request | end_dt | 종료일자 | String | N | 8 | YYYYMMDD |
| request | all_tp | 전체구분 | String | Y | 6 | 1: 전체표시 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | dbrt_trde_trnsn | 대차거래추이 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 8 |  |
| response | - dbrt_trde_cntrcnt | 대차거래체결주수 | String | N | 12 |  |
| response | - dbrt_trde_rpy | 대차거래상환주수 | String | N | 18 |  |
| response | - rmnd | 잔고주수 | String | N | 18 |  |
| response | - dbrt_trde_irds | 대차거래증감 | String | N | 60 |  |
| response | - remn_amt | 잔고금액 | String | N | 18 |  |

---

### 대차거래상위10종목요청 (ka10069)

- **API ID**: ka10069
- **Method**: POST
- **URL**: /api/dostk/slb
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | strt_dt | 시작일자 | String | Y | 8 | YYYYMMDD
(연도4자리, 월 2자리, 일 2자리 형식) |
| request | end_dt | 종료일자 | String | N | 8 | YYYYMMDD
(연도4자리, 월 2자리, 일 2자리 형식) |
| request | mrkt_tp | 시장구분 | String | Y | 3 | 001:코스피, 101:코스닥 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | dbrt_trde_cntrcnt_sum | 대차거래체결주수합 | String | N |  |  |
| response | dbrt_trde_rpy_sum | 대차거래상환주수합 | String | N |  |  |
| response | rmnd_sum | 잔고주수합 | String | N |  |  |
| response | remn_amt_sum | 잔고금액합 | String | N |  |  |
| response | dbrt_trde_cntrcnt_rt | 대차거래체결주수비율 | String | N |  |  |
| response | dbrt_trde_rpy_rt | 대차거래상환주수비율 | String | N |  |  |
| response | rmnd_rt | 잔고주수비율 | String | N |  |  |
| response | remn_amt_rt | 잔고금액비율 | String | N |  |  |
| response | dbrt_trde_upper_10stk | 대차거래상위10종목 | LIST | N |  |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - dbrt_trde_cntrcnt | 대차거래체결주수 | String | N | 20 |  |
| response | - dbrt_trde_rpy | 대차거래상환주수 | String | N | 20 |  |
| response | - rmnd | 잔고주수 | String | N | 20 |  |
| response | - remn_amt | 잔고금액 | String | N | 20 |  |

---

### 일자별종목별실현손익요청_일자 (ka10072)

- **API ID**: ka10072
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | N | 6 |  |
| request | strt_dt | 시작일자 | String | Y | 8 | YYYYMMDD |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | dt_stk_div_rlzt_pl | 일자별종목별실현손익 | LIST | N |  |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cntr_qty | 체결량 | String | N | 20 |  |
| response | - buy_uv | 매입단가 | String | N | 20 |  |
| response | - cntr_pric | 체결가 | String | N | 20 |  |
| response | - tdy_sel_pl | 당일매도손익 | String | N | 20 |  |
| response | - pl_rt | 손익율 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - tdy_trde_cmsn | 당일매매수수료 | String | N | 20 |  |
| response | - tdy_trde_tax | 당일매매세금 | String | N | 20 |  |
| response | - wthd_alowa | 인출가능금액 | String | N | 20 |  |
| response | - loan_dt | 대출일 | String | N | 20 |  |
| response | - crd_tp | 신용구분 | String | N | 20 |  |
| response | - stk_cd_1 | 종목코드1 | String | N | 20 |  |
| response | - tdy_sel_pl_1 | 당일매도손익1 | String | N | 20 |  |

---

### 일자별종목별실현손익요청_기간 (ka10073)

- **API ID**: ka10073
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | N | 6 |  |
| request | strt_dt | 시작일자 | String | Y | 8 | YYYYMMDD |
| request | end_dt | 종료일자 | String | Y | 8 | YYYYMMDD |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | dt_stk_rlzt_pl | 일자별종목별실현손익 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - tdy_htssel_cmsn | 당일hts매도수수료 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cntr_qty | 체결량 | String | N | 20 |  |
| response | - buy_uv | 매입단가 | String | N | 20 |  |
| response | - cntr_pric | 체결가 | String | N | 20 |  |
| response | - tdy_sel_pl | 당일매도손익 | String | N | 20 |  |
| response | - pl_rt | 손익율 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - tdy_trde_cmsn | 당일매매수수료 | String | N | 20 |  |
| response | - tdy_trde_tax | 당일매매세금 | String | N | 20 |  |
| response | - wthd_alowa | 인출가능금액 | String | N | 20 |  |
| response | - loan_dt | 대출일 | String | N | 20 |  |
| response | - crd_tp | 신용구분 | String | N | 20 |  |

---

### 일자별실현손익요청 (ka10074)

- **API ID**: ka10074
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | strt_dt | 시작일자 | String | Y | 8 |  |
| request | end_dt | 종료일자 | String | Y | 8 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | tot_buy_amt | 총매수금액 | String | N |  |  |
| response | tot_sell_amt | 총매도금액 | String | N |  |  |
| response | rlzt_pl | 실현손익 | String | N |  |  |
| response | trde_cmsn | 매매수수료 | String | N |  |  |
| response | trde_tax | 매매세금 | String | N |  |  |
| response | dt_rlzt_pl | 일자별실현손익 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - buy_amt | 매수금액 | String | N | 20 |  |
| response | - sell_amt | 매도금액 | String | N | 20 |  |
| response | - tdy_sel_pl | 당일매도손익 | String | N | 20 |  |
| response | - tdy_trde_cmsn | 당일매매수수료 | String | N | 20 |  |
| response | - tdy_trde_tax | 당일매매세금 | String | N | 20 |  |

---

### 미체결요청 (ka10075)

- **API ID**: ka10075
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | all_stk_tp | 전체종목구분 | String | Y | 1 | 0:전체, 1:종목 |
| request | trde_tp | 매매구분 | String | Y | 1 | 0:전체, 1:매도, 2:매수 |
| request | stk_cd | 종목코드 | String | N | 6 |  |
| request | stex_tp | 거래소구분 | String | Y | 1 | 0 : 통합, 1 : KRX, 2 : NXT |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | oso | 미체결 | LIST | N |  |  |
| response | - acnt_no | 계좌번호 | String | N | 20 |  |
| response | - ord_no | 주문번호 | String | N | 20 |  |
| response | - mang_empno | 관리사번 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - tsk_tp | 업무구분 | String | N | 20 |  |
| response | - ord_stt | 주문상태 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - ord_qty | 주문수량 | String | N | 20 |  |
| response | - ord_pric | 주문가격 | String | N | 20 |  |
| response | - oso_qty | 미체결수량 | String | N | 20 |  |
| response | - cntr_tot_amt | 체결누계금액 | String | N | 20 |  |
| response | - orig_ord_no | 원주문번호 | String | N | 20 |  |
| response | - io_tp_nm | 주문구분 | String | N | 20 |  |
| response | - trde_tp | 매매구분 | String | N | 20 |  |
| response | - tm | 시간 | String | N | 20 |  |
| response | - cntr_no | 체결번호 | String | N | 20 |  |

> ... 외 14개 필드

---

### 체결요청 (ka10076)

- **API ID**: ka10076
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | N | 6 |  |
| request | qry_tp | 조회구분 | String | Y | 1 | 0:전체, 1:종목 |
| request | sell_tp | 매도수구분 | String | Y | 1 | 0:전체, 1:매도, 2:매수 |
| request | ord_no | 주문번호 | String | N | 10 | 검색 기준 값으로 입력한 주문번호 보다 과거에 체결된 내역이 조회됩니다. |
| request | stex_tp | 거래소구분 | String | Y | 1 | 0 : 통합, 1 : KRX, 2 : NXT |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | cntr | 체결 | LIST | N |  |  |
| response | - ord_no | 주문번호 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - io_tp_nm | 주문구분 | String | N | 20 |  |
| response | - ord_pric | 주문가격 | String | N | 20 |  |
| response | - ord_qty | 주문수량 | String | N | 20 |  |
| response | - cntr_pric | 체결가 | String | N | 20 |  |
| response | - cntr_qty | 체결량 | String | N | 20 |  |
| response | - oso_qty | 미체결수량 | String | N | 20 |  |
| response | - tdy_trde_cmsn | 당일매매수수료 | String | N | 20 |  |
| response | - tdy_trde_tax | 당일매매세금 | String | N | 20 |  |
| response | - ord_stt | 주문상태 | String | N | 20 |  |
| response | - trde_tp | 매매구분 | String | N | 20 |  |
| response | - orig_ord_no | 원주문번호 | String | N | 20 |  |
| response | - ord_tm | 주문시간 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stex_tp | 거래소구분 | String | N | 20 | 0 : 통합, 1 : KRX, 2 : NXT |

> ... 외 3개 필드

---

### 당일실현손익상세요청 (ka10077)

- **API ID**: ka10077
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | tdy_rlzt_pl | 당일실현손익 | String | N |  |  |
| response | tdy_rlzt_pl_dtl | 당일실현손익상세 | LIST | N |  |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cntr_qty | 체결량 | String | N | 20 |  |
| response | - buy_uv | 매입단가 | String | N | 20 |  |
| response | - cntr_pric | 체결가 | String | N | 20 |  |
| response | - tdy_sel_pl | 당일매도손익 | String | N | 20 |  |
| response | - pl_rt | 손익율 | String | N | 20 |  |
| response | - tdy_trde_cmsn | 당일매매수수료 | String | N | 20 |  |
| response | - tdy_trde_tax | 당일매매세금 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |

---

### 증권사별종목매매동향요청 (ka10078)

- **API ID**: ka10078
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mmcm_cd | 회원사코드 | String | Y | 3 | 회원사 코드는 ka10102 조회 |
| request | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | strt_dt | 시작일자 | String | Y | 8 | YYYYMMDD |
| request | end_dt | 종료일자 | String | Y | 8 | YYYYMMDD |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | sec_stk_trde_trend | 증권사별종목매매동향 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - netprps_qty | 순매수수량 | String | N | 20 |  |
| response | - buy_qty | 매수수량 | String | N | 20 |  |
| response | - sell_qty | 매도수량 | String | N | 20 |  |

---

### 주식틱차트조회요청 (ka10079)

- **API ID**: ka10079
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | tic_scope | 틱범위 | String | Y | 2 | 1:1틱, 3:3틱, 5:5틱, 10:10틱, 30:30틱 |
| request | upd_stkpc_tp | 수정주가구분 | String | Y | 1 | 0 or 1 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_cd | 종목코드 | String | N | 6 |  |
| response | last_tic_cnt | 마지막틱갯수 | String | N |  |  |
| response | stk_tic_chart_qry | 주식틱차트조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - cntr_tm | 체결시간 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 | 현재가 - 전일종가 |
| response | - pred_pre_sig | 전일대비 기호 | String | N | 20 | 1: 상한가, 2:상승, 3:보합, 4:하한가, 5:하락 |

---

### 주식분봉차트조회요청 (ka10080)

- **API ID**: ka10080
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | tic_scope | 틱범위 | String | Y | 2 | 1:1분, 3:3분, 5:5분, 10:10분, 15:15분, 30:30분, 45:45분,  |
| request | upd_stkpc_tp | 수정주가구분 | String | Y | 1 | 0 or 1 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_cd | 종목코드 | String | N | 6 |  |
| response | stk_min_pole_chart_qry | 주식분봉차트조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 | 종가 |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - cntr_tm | 체결시간 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 | 현재가 - 전일종가 |
| response | - pred_pre_sig | 전일대비 기호 | String | N | 20 | 1: 상한가, 2:상승, 3:보합, 4:하한가, 5:하락 |

---

### 주식일봉차트조회요청 (ka10081)

- **API ID**: ka10081
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | base_dt | 기준일자 | String | Y | 8 | YYYYMMDD |
| request | upd_stkpc_tp | 수정주가구분 | String | Y | 1 | 0 or 1 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_cd | 종목코드 | String | N | 6 |  |
| response | stk_dt_pole_chart_qry | 주식일봉차트조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - trde_prica | 거래대금 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 | 현재가 - 전일종가 |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 | 1: 상한가, 2:상승, 3:보합, 4:하한가, 5:하락 |
| response | - trde_tern_rt | 거래회전율 | String | N | 20 |  |

---

### 주식주봉차트조회요청 (ka10082)

- **API ID**: ka10082
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | base_dt | 기준일자 | String | Y | 8 | YYYYMMDD |
| request | upd_stkpc_tp | 수정주가구분 | String | Y | 1 | 0 or 1 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_cd | 종목코드 | String | N | 6 |  |
| response | stk_stk_pole_chart_qry | 주식주봉차트조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - trde_prica | 거래대금 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 | 현재가 - 전일종가 |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 | 1: 상한가, 2:상승, 3:보합, 4:하한가, 5:하락 |
| response | - trde_tern_rt | 거래회전율 | String | N | 20 |  |

---

### 주식월봉차트조회요청 (ka10083)

- **API ID**: ka10083
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | base_dt | 기준일자 | String | Y | 8 | YYYYMMDD |
| request | upd_stkpc_tp | 수정주가구분 | String | Y | 1 | 0 or 1 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_cd | 종목코드 | String | N | 6 |  |
| response | stk_mth_pole_chart_qry | 주식월봉차트조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - trde_prica | 거래대금 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 | 현재가 - 전일종가 |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 | 1: 상한가, 2:상승, 3:보합, 4:하한가, 5:하락 |
| response | - trde_tern_rt | 거래회전율 | String | N | 20 |  |

---

### 당일전일체결요청 (ka10084)

- **API ID**: ka10084
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | tdy_pred | 당일전일 | String | Y | 1 | 당일 : 1, 전일 : 2 |
| request | tic_min | 틱분 | String | Y | 1 | 0:틱, 1:분 |
| request | tm | 시간 | String | N | 4 | 조회시간 4자리, 오전 9시일 경우 0900, 오후 2시 30분일 경우 1430 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | tdy_pred_cntr | 당일전일체결 | LIST | N |  |  |
| response | - tm | 시간 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - pre_rt | 대비율 | String | N | 20 |  |
| response | - pri_sel_bid_unit | 우선매도호가단위 | String | N | 20 |  |
| response | - pri_buy_bid_unit | 우선매수호가단위 | String | N | 20 |  |
| response | - cntr_trde_qty | 체결거래량 | String | N | 20 |  |
| response | - sign | 전일대비기호 | String | N | 20 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - acc_trde_prica | 누적거래대금 | String | N | 20 |  |
| response | - cntr_str | 체결강도 | String | N | 20 |  |
| response | - stex_tp | 거래소구분 | String | N | 20 | KRX , NXT , 통합 |

---

### 계좌수익률요청 (ka10085)

- **API ID**: ka10085
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stex_tp | 거래소구분 | String | Y | 1 | 0 : 통합, 1 : KRX, 2 : NXT |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | acnt_prft_rt | 계좌수익률 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pur_pric | 매입가 | String | N | 20 |  |
| response | - pur_amt | 매입금액 | String | N | 20 |  |
| response | - rmnd_qty | 보유수량 | String | N | 20 |  |
| response | - tdy_sel_pl | 당일매도손익 | String | N | 20 |  |
| response | - tdy_trde_cmsn | 당일매매수수료 | String | N | 20 |  |
| response | - tdy_trde_tax | 당일매매세금 | String | N | 20 |  |
| response | - crd_tp | 신용구분 | String | N | 20 |  |
| response | - loan_dt | 대출일 | String | N | 20 |  |
| response | - setl_remn | 결제잔고 | String | N | 20 |  |
| response | - clrn_alow_qty | 청산가능수량 | String | N | 20 |  |
| response | - crd_amt | 신용금액 | String | N | 20 |  |
| response | - crd_int | 신용이자 | String | N | 20 |  |

> ... 외 1개 필드

---

### 일별주가요청 (ka10086)

- **API ID**: ka10086
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | qry_dt | 조회일자 | String | Y | 8 | YYYYMMDD |
| request | indc_tp | 표시구분 | String | Y | 1 | 0:수량, 1:금액(백만원) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | daly_stkpc | 일별주가 | LIST | N |  |  |
| response | - date | 날짜 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |
| response | - close_pric | 종가 | String | N | 20 |  |
| response | - pred_rt | 전일비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - amt_mn | 금액(백만) | String | N | 20 |  |
| response | - crd_rt | 신용비 | String | N | 20 |  |
| response | - ind | 개인 | String | N | 20 |  |
| response | - orgn | 기관 | String | N | 20 |  |
| response | - for_qty | 외인수량 | String | N | 20 |  |
| response | - frgn | 외국계 | String | N | 20 |  |
| response | - prm | 프로그램 | String | N | 20 |  |
| response | - for_rt | 외인비 | String | N | 20 |  |

> ... 외 6개 필드

---

### 시간외단일가요청 (ka10087)

- **API ID**: ka10087
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | bid_req_base_tm | 호가잔량기준시간 | String | N |  |  |
| response | ovt_sigpric_sel_bid_jub_pre_5 | 시간외단일가_매도호가직전대비5 | String | N |  |  |
| response | ovt_sigpric_sel_bid_jub_pre_4 | 시간외단일가_매도호가직전대비4 | String | N |  |  |
| response | ovt_sigpric_sel_bid_jub_pre_3 | 시간외단일가_매도호가직전대비3 | String | N |  |  |
| response | ovt_sigpric_sel_bid_jub_pre_2 | 시간외단일가_매도호가직전대비2 | String | N |  |  |
| response | ovt_sigpric_sel_bid_jub_pre_1 | 시간외단일가_매도호가직전대비1 | String | N |  |  |
| response | ovt_sigpric_sel_bid_qty_5 | 시간외단일가_매도호가수량5 | String | N |  |  |
| response | ovt_sigpric_sel_bid_qty_4 | 시간외단일가_매도호가수량4 | String | N |  |  |
| response | ovt_sigpric_sel_bid_qty_3 | 시간외단일가_매도호가수량3 | String | N |  |  |
| response | ovt_sigpric_sel_bid_qty_2 | 시간외단일가_매도호가수량2 | String | N |  |  |
| response | ovt_sigpric_sel_bid_qty_1 | 시간외단일가_매도호가수량1 | String | N |  |  |
| response | ovt_sigpric_sel_bid_5 | 시간외단일가_매도호가5 | String | N |  |  |
| response | ovt_sigpric_sel_bid_4 | 시간외단일가_매도호가4 | String | N |  |  |
| response | ovt_sigpric_sel_bid_3 | 시간외단일가_매도호가3 | String | N |  |  |
| response | ovt_sigpric_sel_bid_2 | 시간외단일가_매도호가2 | String | N |  |  |
| response | ovt_sigpric_sel_bid_1 | 시간외단일가_매도호가1 | String | N |  |  |
| response | ovt_sigpric_buy_bid_1 | 시간외단일가_매수호가1 | String | N |  |  |

> ... 외 29개 필드

---

### 미체결 분할주문 상세 (ka10088)

- **API ID**: ka10088
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | ord_no | 주문번호 | String | Y | 20 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | osop | 미체결분할주문리스트 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - ord_no | 주문번호 | String | N | 20 |  |
| response | - ord_qty | 주문수량 | String | N | 20 |  |
| response | - ord_pric | 주문가격 | String | N | 20 |  |
| response | - osop_qty | 미체결수량 | String | N | 20 |  |
| response | - io_tp_nm | 주문구분 | String | N | 20 |  |
| response | - trde_tp | 매매구분 | String | N | 20 |  |
| response | - sell_tp | 매도/수 구분 | String | N | 20 |  |
| response | - cntr_qty | 체결량 | String | N | 20 |  |
| response | - ord_stt | 주문상태 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - stex_tp | 거래소구분 | String | N | 20 | 0 : 통합, 1 : KRX, 2 : NXT |
| response | - stex_tp_txt | 거래소구분텍스트 | String | N | 20 | 통합,KRX,NXT |

---

### 주식년봉차트조회요청 (ka10094)

- **API ID**: ka10094
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | base_dt | 기준일자 | String | Y | 8 | YYYYMMDD |
| request | upd_stkpc_tp | 수정주가구분 | String | Y | 1 | 0 or 1 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_cd | 종목코드 | String | N | 6 |  |
| response | stk_yr_pole_chart_qry | 주식년봉차트조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - trde_prica | 거래대금 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |

---

### 관심종목정보요청 (ka10095)

- **API ID**: ka10095
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | atn_stk_infr | 관심종목정보 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - base_pric | 기준가 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - trde_prica | 거래대금 | String | N | 20 |  |
| response | - cntr_qty | 체결량 | String | N | 20 |  |
| response | - cntr_str | 체결강도 | String | N | 20 |  |
| response | - pred_trde_qty_pre | 전일거래량대비 | String | N | 20 |  |
| response | - sel_bid | 매도호가 | String | N | 20 |  |
| response | - buy_bid | 매수호가 | String | N | 20 |  |
| response | - sel_1th_bid | 매도1차호가 | String | N | 20 |  |
| response | - sel_2th_bid | 매도2차호가 | String | N | 20 |  |

> ... 외 47개 필드

---

### 시간외단일가등락율순위요청 (ka10098)

- **API ID**: ka10098
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체,001:코스피,101:코스닥 |
| request | sort_base | 정렬기준 | String | Y | 1 | 1:상승률, 2:상승폭, 3:하락률, 4:하락폭, 5:보합 |
| request | stk_cnd | 종목조건 | String | Y | 2 | 0:전체조회,1:관리종목제외,2:정리매매종목제외,3:우선주제외,4:관리종목우선주제외,5:증 |
| request | trde_qty_cnd | 거래량조건 | String | Y | 5 | 0:전체조회, 10:백주이상,50:5백주이상,100;천주이상, 500:5천주이상, 1000 |
| request | crd_cnd | 신용조건 | String | Y | 1 | 0:전체조회, 9:신용융자전체, 1:신용융자A군, 2:신용융자B군, 3:신용융자C군, 4: |
| request | trde_prica | 거래대금 | String | Y | 5 | 0:전체조회, 5:5백만원이상,10:1천만원이상, 30:3천만원이상, 50:5천만원이상,  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | ovt_sigpric_flu_rt_rank | 시간외단일가등락율순위 | LIST | N |  |  |
| response | - rank | 순위 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - sel_tot_req | 매도총잔량 | String | N | 20 |  |
| response | - buy_tot_req | 매수총잔량 | String | N | 20 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - acc_trde_prica | 누적거래대금 | String | N | 20 |  |
| response | - tdy_close_pric | 당일종가 | String | N | 20 |  |
| response | - tdy_close_pric_flu_rt | 당일종가등락률 | String | N | 20 |  |

---

### 종목정보 리스트 (ka10099)

- **API ID**: ka10099
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 2 | 0:코스피,10:코스닥,3:ELW,8:ETF,30:K-OTC,50:코넥스,5:신주인수권,4 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | list | 종목리스트 | LIST | N |  |  |
| response | - code | 종목코드 | String | N | 20 | 단축코드 |
| response | - name | 종목명 | String | N | 40 |  |
| response | - listCount | 상장주식수 | String | N | 20 |  |
| response | - auditInfo | 감리구분 | String | N | 20 |  |
| response | - regDay | 상장일 | String | N | 20 |  |
| response | - lastPrice | 전일종가 | String | N | 20 |  |
| response | - state | 종목상태 | String | N | 20 |  |
| response | - marketCode | 시장구분코드 | String | N | 20 |  |
| response | - marketName | 시장명 | String | N | 20 |  |
| response | - upName | 업종명 | String | N | 20 |  |
| response | - upSizeName | 회사크기분류 | String | N | 20 |  |
| response | - companyClassName | 회사분류 | String | N | 20 | 코스닥만 존재함 |
| response | - orderWarning | 투자유의종목여부 | String | N | 20 | 0: 해당없음, 2: 정리매매, 3: 단기과열, 4: 투자위험, 5: 투자경과, 1: ET |
| response | - nxtEnable | NXT가능여부 | String | N | 20 | Y: 가능 |

---

### 종목정보 조회 (ka10100)

- **API ID**: ka10100
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | code | 종목코드 | String | N |  | 단축코드 |
| response | name | 종목명 | String | N | 40 |  |
| response | listCount | 상장주식수 | String | N |  |  |
| response | auditInfo | 감리구분 | String | N |  |  |
| response | regDay | 상장일 | String | N |  |  |
| response | lastPrice | 전일종가 | String | N |  |  |
| response | state | 종목상태 | String | N |  |  |
| response | marketCode | 시장구분코드 | String | N |  |  |
| response | marketName | 시장명 | String | N |  |  |
| response | upName | 업종명 | String | N |  |  |
| response | upSizeName | 회사크기분류 | String | N |  |  |
| response | companyClassName | 회사분류 | String | N |  | 코스닥만 존재함 |
| response | orderWarning | 투자유의종목여부 | String | N |  | 0: 해당없음, 2: 정리매매, 3: 단기과열, 4: 투자위험, 5: 투자경과, 1: ET |
| response | nxtEnable | NXT가능여부 | String | N |  | Y: 가능 |

---

### 업종코드 리스트 (ka10101)

- **API ID**: ka10101
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 1 | 0:코스피(거래소),1:코스닥,2:KOSPI200,4:KOSPI100,7:KRX100(통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | list | 업종코드리스트 | LIST | N |  |  |
| response | - marketCode | 시장구분코드 | LIST | N |  |  |
| response | - code | 코드 | String | N |  |  |
| response | - name | 업종명 | String | N |  |  |
| response | - group | 그룹 | String | N |  |  |

---

### 회원사 리스트 (ka10102)

- **API ID**: ka10102
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | list | 회원사코드리스트 | LIST | N |  |  |
| response | - code | 코드 | String | N |  |  |
| response | - name | 업종명 | String | N |  |  |
| response | - gb | 구분 | String | N |  |  |

---

### 기관외국인연속매매현황요청 (ka10131)

- **API ID**: ka10131
- **Method**: POST
- **URL**: /api/dostk/frgnistt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | dt | 기간 | String | Y | 3 | 1:최근일, 3:3일, 5:5일, 10:10일, 20:20일, 120:120일, 0:시작일 |
| request | strt_dt | 시작일자 | String | N | 8 | YYYYMMDD |
| request | end_dt | 종료일자 | String | N | 8 | YYYYMMDD |
| request | mrkt_tp | 장구분 | String | Y | 3 | 001:코스피, 101:코스닥 |
| request | netslmt_tp | 순매도수구분 | String | Y | 1 | 2:순매수(고정값) |
| request | stk_inds_tp | 종목업종구분 | String | Y | 1 | 0:종목(주식),1:업종 |
| request | amt_qty_tp | 금액수량구분 | String | Y | 1 | 0:금액, 1:수량 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT, 3:통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | orgn_frgnr_cont_trde_prst | 기관외국인연속매매현황 | LIST | N |  |  |
| response | - rank | 순위 | String | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 6 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - prid_stkpc_flu_rt | 기간중주가등락률 | String | N |  |  |
| response | - orgn_nettrde_amt | 기관순매매금액 | String | N |  |  |
| response | - orgn_nettrde_qty | 기관순매매량 | String | N |  |  |
| response | - orgn_cont_netprps_dys | 기관계연속순매수일수 | String | N |  |  |
| response | - orgn_cont_netprps_qty | 기관계연속순매수량 | String | N |  |  |
| response | - orgn_cont_netprps_amt | 기관계연속순매수금액 | String | N |  |  |
| response | - frgnr_nettrde_qty | 외국인순매매량 | String | N |  |  |
| response | - frgnr_nettrde_amt | 외국인순매매액 | String | N |  |  |
| response | - frgnr_cont_netprps_dys | 외국인연속순매수일수 | String | N |  |  |
| response | - frgnr_cont_netprps_qty | 외국인연속순매수량 | String | N |  |  |
| response | - frgnr_cont_netprps_amt | 외국인연속순매수금액 | String | N |  |  |
| response | - nettrde_qty | 순매매량 | String | N |  |  |
| response | - nettrde_amt | 순매매액 | String | N |  |  |

> ... 외 3개 필드

---

### 당일매매일지요청 (ka10170)

- **API ID**: ka10170
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | base_dt | 기준일자 | String | N | 8 | YYYYMMDD(공백입력시 금일데이터,최근 2개월까지 제공) |
| request | ottks_tp | 단주구분 | String | Y | 1 | 1:당일매수에 대한 당일매도,2:당일매도 전체 |
| request | ch_crd_tp | 현금신용구분 | String | Y | 1 | 0:전체, 1:현금매매만, 2:신용매매만 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | tot_sell_amt | 총매도금액 | String | N |  |  |
| response | tot_buy_amt | 총매수금액 | String | N |  |  |
| response | tot_cmsn_tax | 총수수료_세금 | String | N |  |  |
| response | tot_exct_amt | 총정산금액 | String | N |  |  |
| response | tot_pl_amt | 총손익금액 | String | N |  |  |
| response | tot_prft_rt | 총수익률 | String | N |  |  |
| response | tdy_trde_diary | 당일매매일지 | LIST | N |  |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - buy_avg_pric | 매수평균가 | String | N |  |  |
| response | - buy_qty | 매수수량 | String | N |  |  |
| response | - sel_avg_pric | 매도평균가 | String | N |  |  |
| response | - sell_qty | 매도수량 | String | N |  |  |
| response | - cmsn_alm_tax | 수수료_제세금 | String | N |  |  |
| response | - pl_amt | 손익금액 | String | N |  |  |
| response | - sell_amt | 매도금액 | String | N |  |  |
| response | - buy_amt | 매수금액 | String | N |  |  |
| response | - prft_rt | 수익률 | String | N |  |  |

> ... 외 1개 필드

---

### 조건검색 목록조회 (ka10171)

- **API ID**: ka10171
- **Method**: POST
- **URL**: /api/dostk/websocket
- **운영 도메인**: wss://api.kiwoom.com:10000
- **모의투자 도메인**: wss://mockapi.kiwoom.com:10000(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | trnm | TR명 | String | Y | 7 | CNSRLST고정값 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | return_code | 결과코드 | String | N |  | 정상 : 0 |
| response | return_msg | 결과메시지 | String | N |  | 정상인 경우는 메시지 없음 |
| response | trnm | 서비스명 | String | N | 7 | CNSRLST 고정값 |
| response | data | 조건검색식 목록 | LIST | N |  |  |
| response | - seq | 조건검색식 일련번호 | String | N |  |  |
| response | - name | 조건검색식 명 | String | N |  |  |

---

### 조건검색 요청 일반 (ka10172)

- **API ID**: ka10172
- **Method**: POST
- **URL**: /api/dostk/websocket
- **운영 도메인**: wss://api.kiwoom.com:10000
- **모의투자 도메인**: wss://mockapi.kiwoom.com:10000(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | trnm | 서비스명 | String | Y | 7 | CNSRREQ 고정값 |
| request | seq | 조건검색식 일련번호 | String | Y | 3 |  |
| request | search_type | 조회타입 | String | Y |  | 0:조건검색 |
| request | stex_tp | 거래소구분 | String | Y | 1 | K:KRX |
| request | cont_yn | 연속조회여부 | String | N | 1 | Y:연속조회요청,N:연속조회미요청 |
| request | next_key | 연속조회키 | String | N | 20 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | return_code | 결과코드 | String | N |  | 정상:0 나머지:에러 |
| response | return_msg | 결과메시지 | String | N |  | 정상인 경우는 메시지 없음 |
| response | trnm | 서비스명 | String | N |  | CNSRREQ |
| response | seq | 조건검색식 일련번호 | String | N |  |  |
| response | cont_yn | 연속조회여부 | String | N |  | 연속 데이터가 존재하는경우 Y, 없으면 N |
| response | next_key | 연속조회키 | String | N |  | 연속조회여부가Y일경우 다음 조회시 필요한 조회값 |
| response | data | 검색결과데이터 | LIST | N |  |  |
| response | - 9001 | 종목코드 | String | N |  |  |
| response | - 302 | 종목명 | String | N |  |  |
| response | - 10 | 현재가 | String | N |  |  |
| response | - 25 | 전일대비기호 | String | N |  |  |
| response | - 11 | 전일대비 | String | N |  |  |
| response | - 12 | 등락율 | String | N |  |  |
| response | - 13 | 누적거래량 | String | N |  |  |
| response | - 16 | 시가 | String | N |  |  |
| response | - 17 | 고가 | String | N |  |  |
| response | - 18 | 저가 | String | N |  |  |

---

### 조건검색 요청 실시간 (ka10173)

- **API ID**: ka10173
- **Method**: POST
- **URL**: /api/dostk/websocket
- **운영 도메인**: wss://api.kiwoom.com:10000
- **모의투자 도메인**: wss://mockapi.kiwoom.com:10000(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | trnm | 서비스명 | String | Y | 7 | CNSRREQ 고정값 |
| request | seq | 조건검색식 일련번호 | String | Y | 3 |  |
| request | search_type | 조회타입 | String | Y | 1 | 1: 조건검색+실시간조건검색 |
| request | stex_tp | 거래소구분 | String | Y | 1 | K:KRX |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | 조회 데이터 |  |  |  |  |  |
| response | return_code | 결과코드 | String | N |  | 정상:0 나머지:에러 |
| response | return_msg | 결과메시지 | String | N |  | 정상인 경우는 메시지 없음 |
| response | trnm | 서비스명 | String | N |  | CNSRREQ |
| response | seq | 조건검색식 일련번호 | String | N |  |  |
| response | data | 검색결과데이터 | LIST | N |  |  |
| response | - jmcode | 종목코드 | String | N |  |  |
| Body | 실시간 데이터 |  |  |  |  |  |
| response | data | 검색결과데이터 | LIST | Y |  |  |
| response | trnm | 서비스명 | String | Y |  | REAL |
| response | - type | 실시간 항목 | String | Y | 2 | TR 명(0A,0B....) |
| response | - name | 실시간 항목명 | String | Y |  | 종목코드 |
| response | - values | 실시간 수신 값 | Object | Y |  |  |
| response | - - 841 | 일련번호 | String | Y |  |  |
| response | - - 9001 | 종목코드 | String | Y |  |  |
| response | - - 843 | 삽입삭제 구분 | String | Y |  | I: 삽입, D: 삭제 |
| response | - - 20 | 체결시간 | String | Y |  |  |

> ... 외 1개 필드

---

### 조건검색 실시간 해제 (ka10174)

- **API ID**: ka10174
- **Method**: POST
- **URL**: /api/dostk/websocket
- **운영 도메인**: wss://api.kiwoom.com:10000
- **모의투자 도메인**: wss://mockapi.kiwoom.com:10000(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | trnm | 서비스명 | String | Y | 7 | CNSRCLR 고정값 |
| request | seq | 조건검색식 일련번호 | String | Y |  |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | return_code | 결과코드 | String | Y |  | 정상:0 나머지:에러 |
| response | return_msg | 결과메시지 | String | Y |  | 정상인 경우는 메시지 없음 |
| response | trnm | 서비스명 | String | Y |  | CNSRCLR 고정값 |
| response | seq | 조건검색식 일련번호 | String | Y |  |  |

---

### 업종현재가요청 (ka20001)

- **API ID**: ka20001
- **Method**: POST
- **URL**: /api/dostk/sect
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 1 | 0:코스피, 1:코스닥, 2:코스피200 |
| request | inds_cd | 업종코드 | String | Y | 3 | 001:종합(KOSPI), 002:대형주, 003:중형주, 004:소형주 101:종합(KO |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | cur_prc | 현재가 | String | N | 20 |  |
| response | pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | pred_pre | 전일대비 | String | N | 20 |  |
| response | flu_rt | 등락률 | String | N | 20 |  |
| response | trde_qty | 거래량 | String | N | 20 |  |
| response | trde_prica | 거래대금 | String | N | 20 |  |
| response | trde_frmatn_stk_num | 거래형성종목수 | String | N | 20 |  |
| response | trde_frmatn_rt | 거래형성비율 | String | N | 20 |  |
| response | open_pric | 시가 | String | N | 20 |  |
| response | high_pric | 고가 | String | N | 20 |  |
| response | low_pric | 저가 | String | N | 20 |  |
| response | upl | 상한 | String | N | 20 |  |
| response | rising | 상승 | String | N | 20 |  |
| response | stdns | 보합 | String | N | 20 |  |
| response | fall | 하락 | String | N | 20 |  |
| response | lst | 하한 | String | N | 20 |  |
| response | 52wk_hgst_pric | 52주최고가 | String | N | 20 |  |

> ... 외 13개 필드

---

### 업종별주가요청 (ka20002)

- **API ID**: ka20002
- **Method**: POST
- **URL**: /api/dostk/sect
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 1 | 0:코스피, 1:코스닥, 2:코스피200 |
| request | inds_cd | 업종코드 | String | Y | 3 | 001:종합(KOSPI), 002:대형주, 003:중형주, 004:소형주 101:종합(KO |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT, 3:통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | inds_stkpc | 업종별주가 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - now_trde_qty | 현재거래량 | String | N | 20 |  |
| response | - sel_bid | 매도호가 | String | N | 20 |  |
| response | - buy_bid | 매수호가 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |

---

### 전업종지수요청 (ka20003)

- **API ID**: ka20003
- **Method**: POST
- **URL**: /api/dostk/sect
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | inds_cd | 업종코드 | String | Y | 3 | 001:종합(KOSPI), 101:종합(KOSDAQ) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | all_inds_idex | 전업종지수 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - wght | 비중 | String | N | 20 |  |
| response | - trde_prica | 거래대금 | String | N | 20 |  |
| response | - upl | 상한 | String | N | 20 |  |
| response | - rising | 상승 | String | N | 20 |  |
| response | - stdns | 보합 | String | N | 20 |  |
| response | - fall | 하락 | String | N | 20 |  |
| response | - lst | 하한 | String | N | 20 |  |
| response | - flo_stk_num | 상장종목수 | String | N | 20 |  |

---

### 업종틱차트조회요청 (ka20004)

- **API ID**: ka20004
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | inds_cd | 업종코드 | String | Y | 3 | 001:종합(KOSPI), 002:대형주, 003:중형주, 004:소형주 101:종합(KO |
| request | tic_scope | 틱범위 | String | Y | 2 | 1:1틱, 3:3틱, 5:5틱, 10:10틱, 30:30틱 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | inds_cd | 업종코드 | String | N | 20 |  |
| response | inds_tic_chart_qry | 업종틱차트조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - cntr_tm | 체결시간 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - high_pric | 고가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - low_pric | 저가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - pred_pre | 전일대비 | String | N | 20 | 현재가 - 전일종가 |
| response | - pred_pre_sig | 전일대비 기호 | String | N | 20 | 1: 상한가, 2:상승, 3:보합, 4:하한가, 5:하락 |

---

### 업종분봉조회요청 (ka20005)

- **API ID**: ka20005
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | inds_cd | 업종코드 | String | Y | 3 | 001:종합(KOSPI), 002:대형주, 003:중형주, 004:소형주 101:종합(KO |
| request | tic_scope | 틱범위 | String | Y | 2 | 1:1틱, 3:3틱, 5:5틱, 10:10틱, 30:30틱 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | inds_cd | 업종코드 | String | N | 20 |  |
| response | inds_min_pole_qry | 업종분봉조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - cntr_tm | 체결시간 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - high_pric | 고가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - low_pric | 저가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 | 현재가 - 전일종가 |
| response | - pred_pre_sig | 전일대비 기호 | String | N | 20 | 1: 상한가, 2:상승, 3:보합, 4:하한가, 5:하락 |

---

### 업종일봉조회요청 (ka20006)

- **API ID**: ka20006
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | inds_cd | 업종코드 | String | Y | 3 | 001:종합(KOSPI), 002:대형주, 003:중형주, 004:소형주 101:종합(KO |
| request | base_dt | 기준일자 | String | Y | 8 | YYYYMMDD |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | inds_cd | 업종코드 | String | N | 20 |  |
| response | inds_dt_pole_qry | 업종일봉조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - high_pric | 고가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - low_pric | 저가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - trde_prica | 거래대금 | String | N | 20 |  |

---

### 업종주봉조회요청 (ka20007)

- **API ID**: ka20007
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | inds_cd | 업종코드 | String | Y | 8 | 001:종합(KOSPI), 002:대형주, 003:중형주, 004:소형주 101:종합(KO |
| request | base_dt | 기준일자 | String | Y | 3 | YYYYMMDD |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | inds_cd | 업종코드 | String | N | 20 |  |
| response | inds_stk_pole_qry | 업종주봉조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - high_pric | 고가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - low_pric | 저가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - trde_prica | 거래대금 | String | N | 20 |  |

---

### 업종월봉조회요청 (ka20008)

- **API ID**: ka20008
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | inds_cd | 업종코드 | String | Y | 3 | 001:종합(KOSPI), 002:대형주, 003:중형주, 004:소형주 101:종합(KO |
| request | base_dt | 기준일자 | String | Y | 8 | YYYYMMDD |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | inds_cd | 업종코드 | String | N | 20 |  |
| response | inds_mth_pole_qry | 업종월봉조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - high_pric | 고가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - low_pric | 저가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - trde_prica | 거래대금 | String | N | 20 |  |

---

### 업종현재가일별요청 (ka20009)

- **API ID**: ka20009
- **Method**: POST
- **URL**: /api/dostk/sect
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 1 | 0:코스피, 1:코스닥, 2:코스피200 |
| request | inds_cd | 업종코드 | String | Y | 3 | 001:종합(KOSPI), 002:대형주, 003:중형주, 004:소형주 101:종합(KO |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | cur_prc | 현재가 | String | N | 20 |  |
| response | pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | pred_pre | 전일대비 | String | N | 20 |  |
| response | flu_rt | 등락률 | String | N | 20 |  |
| response | trde_qty | 거래량 | String | N | 20 |  |
| response | trde_prica | 거래대금 | String | N | 20 |  |
| response | trde_frmatn_stk_num | 거래형성종목수 | String | N | 20 |  |
| response | trde_frmatn_rt | 거래형성비율 | String | N | 20 |  |
| response | open_pric | 시가 | String | N | 20 |  |
| response | high_pric | 고가 | String | N | 20 |  |
| response | low_pric | 저가 | String | N | 20 |  |
| response | upl | 상한 | String | N | 20 |  |
| response | rising | 상승 | String | N | 20 |  |
| response | stdns | 보합 | String | N | 20 |  |
| response | fall | 하락 | String | N | 20 |  |
| response | lst | 하한 | String | N | 20 |  |
| response | 52wk_hgst_pric | 52주최고가 | String | N | 20 |  |

> ... 외 12개 필드

---

### 업종년봉조회요청 (ka20019)

- **API ID**: ka20019
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | inds_cd | 업종코드 | String | Y | 3 | 001:종합(KOSPI), 002:대형주, 003:중형주, 004:소형주 101:종합(KO |
| request | base_dt | 기준일자 | String | Y | 8 | YYYYMMDD |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | inds_cd | 업종코드 | String | N | 20 |  |
| response | inds_yr_pole_qry | 업종년봉조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - high_pric | 고가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - low_pric | 저가 | String | N | 20 | 지수 값은 소수점 제거 후 100배 값으로 반환 |
| response | - trde_prica | 거래대금 | String | N | 20 |  |

---

### 대차거래추이요청(종목별) (ka20068)

- **API ID**: ka20068
- **Method**: POST
- **URL**: /api/dostk/slb
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | strt_dt | 시작일자 | String | N | 8 | YYYYMMDD |
| request | end_dt | 종료일자 | String | N | 8 | YYYYMMDD |
| request | all_tp | 전체구분 | String | N | 1 | 0:종목코드 입력종목만 표시 |
| request | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | dbrt_trde_trnsn | 대차거래추이 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - dbrt_trde_cntrcnt | 대차거래체결주수 | String | N | 20 |  |
| response | - dbrt_trde_rpy | 대차거래상환주수 | String | N | 20 |  |
| response | - dbrt_trde_irds | 대차거래증감 | String | N | 20 |  |
| response | - rmnd | 잔고주수 | String | N | 20 |  |
| response | - remn_amt | 잔고금액 | String | N | 20 |  |

---

### ELW가격급등락요청 (ka30001)

- **API ID**: ka30001
- **Method**: POST
- **URL**: /api/dostk/elw
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | flu_tp | 등락구분 | String | Y | 1 | 1:급등, 2:급락 |
| request | tm_tp | 시간구분 | String | Y | 1 | 1:분전, 2:일전 |
| request | tm | 시간 | String | Y | 2 | 분 혹은 일입력 (예 1, 3, 5) |
| request | trde_qty_tp | 거래량구분 | String | Y | 4 | 0:전체, 10:만주이상, 50:5만주이상, 100:10만주이상, 300:30만주이상, 5 |
| request | isscomp_cd | 발행사코드 | String | Y | 12 | 전체:000000000000, 한국투자증권:3, 미래대우:5, 신영:6, NK투자증권:12 |
| request | bsis_aset_cd | 기초자산코드 | String | Y | 12 | 전체:000000000000, KOSPI200:201, KOSDAQ150:150, 삼성전자 |
| request | rght_tp | 권리구분 | String | Y | 3 | 000:전체, 001:콜, 002:풋, 003:DC, 004:DP, 005:EX, 006: |
| request | lpcd | LP코드 | String | Y | 12 | 전체:000000000000, 한국투자증권:3, 미래대우:5, 신영:6, NK투자증권:12 |
| request | trde_end_elwskip | 거래종료ELW제외 | String | Y | 1 | 0:포함, 1:제외 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | base_pric_tm | 기준가시간 | String | N | 20 |  |
| response | elwpric_jmpflu | ELW가격급등락 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - rank | 순위 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - trde_end_elwbase_pric | 거래종료ELW기준가 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - base_pre | 기준대비 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - jmp_rt | 급등율 | String | N | 20 |  |

---

### 거래원별ELW순매매상위요청 (ka30002)

- **API ID**: ka30002
- **Method**: POST
- **URL**: /api/dostk/elw
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | isscomp_cd | 발행사코드 | String | Y | 3 | 3자리, 영웅문4 0273화면참조 (교보:001, 신한금융투자:002, 한국투자증권:003 |
| request | trde_qty_tp | 거래량구분 | String | Y | 4 | 0:전체, 5:5천주, 10:만주, 50:5만주, 100:10만주, 500:50만주, 10 |
| request | trde_tp | 매매구분 | String | Y | 1 | 1:순매수, 2:순매도 |
| request | dt | 기간 | String | Y | 2 | 1:전일, 5:5일, 10:10일, 40:40일, 60:60일 |
| request | trde_end_elwskip | 거래종료ELW제외 | String | Y | 1 | 0:포함, 1:제외 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | trde_ori_elwnettrde_upper | 거래원별ELW순매매상위 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - stkpc_flu | 주가등락 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - netprps | 순매수 | String | N | 20 |  |
| response | - buy_trde_qty | 매수거래량 | String | N | 20 |  |
| response | - sel_trde_qty | 매도거래량 | String | N | 20 |  |

---

### ELWLP보유일별추이요청 (ka30003)

- **API ID**: ka30003
- **Method**: POST
- **URL**: /api/dostk/elw
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | bsis_aset_cd | 기초자산코드 | String | Y | 12 |  |
| request | base_dt | 기준일자 | String | Y | 8 | YYYYMMDD |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | elwlpposs_daly_trnsn | ELWLP보유일별추이 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_tp | 대비구분 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - trde_prica | 거래대금 | String | N | 20 |  |
| response | - chg_qty | 변동수량 | String | N | 20 |  |
| response | - lprmnd_qty | LP보유수량 | String | N | 20 |  |
| response | - wght | 비중 | String | N | 20 |  |

---

### ELW괴리율요청 (ka30004)

- **API ID**: ka30004
- **Method**: POST
- **URL**: /api/dostk/elw
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | isscomp_cd | 발행사코드 | String | Y | 12 | 전체:000000000000, 한국투자증권:3, 미래대우:5, 신영:6, NK투자증권:12 |
| request | bsis_aset_cd | 기초자산코드 | String | Y | 12 | 전체:000000000000, KOSPI200:201, KOSDAQ150:150, 삼성전자 |
| request | rght_tp | 권리구분 | String | Y | 3 | 000: 전체, 001: 콜, 002: 풋, 003: DC, 004: DP, 005: EX |
| request | lpcd | LP코드 | String | Y | 12 | 전체:000000000000, 한국투자증권:3, 미래대우:5, 신영:6, NK투자증권:12 |
| request | trde_end_elwskip | 거래종료ELW제외 | String | Y | 1 | 1:거래종료ELW제외, 0:거래종료ELW포함 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | elwdispty_rt | ELW괴리율 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - isscomp_nm | 발행사명 | String | N | 20 |  |
| response | - sqnc | 회차 | String | N | 20 |  |
| response | - base_aset_nm | 기초자산명 | String | N | 20 |  |
| response | - rght_tp | 권리구분 | String | N | 20 |  |
| response | - dispty_rt | 괴리율 | String | N | 20 |  |
| response | - basis | 베이시스 | String | N | 20 |  |
| response | - srvive_dys | 잔존일수 | String | N | 20 |  |
| response | - theory_pric | 이론가 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_tp | 대비구분 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |

---

### ELW조건검색요청 (ka30005)

- **API ID**: ka30005
- **Method**: POST
- **URL**: /api/dostk/elw
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | isscomp_cd | 발행사코드 | String | Y | 12 | 12자리입력(전체:000000000000, 한국투자증권:000,,,3, 미래대우:000,, |
| request | bsis_aset_cd | 기초자산코드 | String | Y | 12 | 전체일때만 12자리입력(전체:000000000000, KOSPI200:201, KOSDAQ |
| request | rght_tp | 권리구분 | String | Y | 1 | 0:전체, 1:콜, 2:풋, 3:DC, 4:DP, 5:EX, 6:조기종료콜, 7:조기종료풋 |
| request | lpcd | LP코드 | String | Y | 12 | 전체일때만 12자리입력(전체:000000000000, 한국투자증권:003, 미래대우:005 |
| request | sort_tp | 정렬구분 | String | Y | 1 | 0:정렬없음, 1:상승율순, 2:상승폭순, 3:하락율순, 4:하락폭순, 5:거래량순, 6: |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | elwcnd_qry | ELW조건검색 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - isscomp_nm | 발행사명 | String | N | 20 |  |
| response | - sqnc | 회차 | String | N | 20 |  |
| response | - base_aset_nm | 기초자산명 | String | N | 20 |  |
| response | - rght_tp | 권리구분 | String | N | 20 |  |
| response | - expr_dt | 만기일 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_tp | 대비구분 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - trde_qty_pre | 거래량대비 | String | N | 20 |  |
| response | - trde_prica | 거래대금 | String | N | 20 |  |
| response | - pred_trde_qty | 전일거래량 | String | N | 20 |  |
| response | - sel_bid | 매도호가 | String | N | 20 |  |
| response | - buy_bid | 매수호가 | String | N | 20 |  |

> ... 외 23개 필드

---

### ELW등락율순위요청 (ka30009)

- **API ID**: ka30009
- **Method**: POST
- **URL**: /api/dostk/elw
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | sort_tp | 정렬구분 | String | Y | 1 | 1:상승률, 2:상승폭, 3:하락률, 4:하락폭 |
| request | rght_tp | 권리구분 | String | Y | 3 | 000:전체, 001:콜, 002:풋, 003:DC, 004:DP, 006:조기종료콜, 0 |
| request | trde_end_skip | 거래종료제외 | String | Y | 1 | 1:거래종료제외, 0:거래종료포함 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | elwflu_rt_rank | ELW등락율순위 | LIST | N |  |  |
| response | - rank | 순위 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - sel_req | 매도잔량 | String | N | 20 |  |
| response | - buy_req | 매수잔량 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - trde_prica | 거래대금 | String | N | 20 |  |

---

### ELW잔량순위요청 (ka30010)

- **API ID**: ka30010
- **Method**: POST
- **URL**: /api/dostk/elw
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | sort_tp | 정렬구분 | String | Y | 1 | 1:순매수잔량상위, 2: 순매도 잔량상위 |
| request | rght_tp | 권리구분 | String | Y | 3 | 000: 전체, 001: 콜, 002: 풋, 003: DC, 004: DP, 006: 조기 |
| request | trde_end_skip | 거래종료제외 | String | Y | 1 | 1:거래종료제외, 0:거래종료포함 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | elwreq_rank | ELW잔량순위 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - rank | 순위 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락률 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - sel_req | 매도잔량 | String | N | 20 |  |
| response | - buy_req | 매수잔량 | String | N | 20 |  |
| response | - netprps_req | 순매수잔량 | String | N | 20 |  |
| response | - trde_prica | 거래대금 | String | N | 20 |  |

---

### ELW근접율요청 (ka30011)

- **API ID**: ka30011
- **Method**: POST
- **URL**: /api/dostk/elw
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | elwalacc_rt | ELW근접율 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - alacc_rt | 근접율 | String | N | 20 |  |

---

### ELW종목상세정보요청 (ka30012)

- **API ID**: ka30012
- **Method**: POST
- **URL**: /api/dostk/elw
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | aset_cd | 자산코드 | String | N | 20 |  |
| response | cur_prc | 현재가 | String | N | 20 |  |
| response | pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | pred_pre | 전일대비 | String | N | 20 |  |
| response | flu_rt | 등락율 | String | N | 20 |  |
| response | lpmmcm_nm | LP회원사명 | String | N | 20 |  |
| response | lpmmcm_nm_1 | LP회원사명1 | String | N | 20 |  |
| response | lpmmcm_nm_2 | LP회원사명2 | String | N | 20 |  |
| response | elwrght_cntn | ELW권리내용 | String | N | 20 |  |
| response | elwexpr_evlt_pric | ELW만기평가가격 | String | N | 20 |  |
| response | elwtheory_pric | ELW이론가 | String | N | 20 |  |
| response | dispty_rt | 괴리율 | String | N | 20 |  |
| response | elwinnr_vltl | ELW내재변동성 | String | N | 20 |  |
| response | exp_rght_pric | 예상권리가 | String | N | 20 |  |
| response | elwpl_qutr_rt | ELW손익분기율 | String | N | 20 |  |
| response | elwexec_pric | ELW행사가 | String | N | 20 |  |
| response | elwcnvt_rt | ELW전환비율 | String | N | 20 |  |

> ... 외 48개 필드

---

### ETF수익율요청 (ka40001)

- **API ID**: ka40001
- **Method**: POST
- **URL**: /api/dostk/etf
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |
| request | etfobjt_idex_cd | ETF대상지수코드 | String | Y | 3 |  |
| request | dt | 기간 | String | Y | 1 | 0:1주, 1:1달, 2:6개월, 3:1년 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | etfprft_rt_lst | ETF수익율 | LIST | N |  |  |
| response | - etfprft_rt | ETF수익률 | String | N | 20 |  |
| response | - cntr_prft_rt | 체결수익률 | String | N | 20 |  |
| response | - for_netprps_qty | 외인순매수수량 | String | N | 20 |  |
| response | - orgn_netprps_qty | 기관순매수수량 | String | N | 20 |  |

---

### ETF종목정보요청 (ka40002)

- **API ID**: ka40002
- **Method**: POST
- **URL**: /api/dostk/etf
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_nm | 종목명 | String | N | 40 |  |
| response | etfobjt_idex_nm | ETF대상지수명 | String | N | 20 |  |
| response | wonju_pric | 원주가격 | String | N | 20 |  |
| response | etftxon_type | ETF과세유형 | String | N | 20 |  |
| response | etntxon_type | ETN과세유형 | String | N | 20 |  |

---

### ETF일별추이요청 (ka40003)

- **API ID**: ka40003
- **Method**: POST
- **URL**: /api/dostk/etf
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | etfdaly_trnsn | ETF일별추이 | LIST | N |  |  |
| response | - cntr_dt | 체결일자 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - pre_rt | 대비율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - nav | NAV | String | N | 20 |  |
| response | - acc_trde_prica | 누적거래대금 | String | N | 20 |  |
| response | - navidex_dispty_rt | NAV/지수괴리율 | String | N | 20 |  |
| response | - navetfdispty_rt | NAV/ETF괴리율 | String | N | 20 |  |
| response | - trace_eor_rt | 추적오차율 | String | N | 20 |  |
| response | - trace_cur_prc | 추적현재가 | String | N | 20 |  |
| response | - trace_pred_pre | 추적전일대비 | String | N | 20 |  |
| response | - trace_pre_sig | 추적대비기호 | String | N | 20 |  |

---

### ETF전체시세요청 (ka40004)

- **API ID**: ka40004
- **Method**: POST
- **URL**: /api/dostk/etf
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | txon_type | 과세유형 | String | Y | 1 | 0:전체, 1:비과세, 2:보유기간과세, 3:회사형, 4:외국, 5:비과세해외(보유기간관세 |
| request | navpre | NAV대비 | String | Y | 1 | 0:전체, 1:NAV > 전일종가, 2:NAV < 전일종가 |
| request | mngmcomp | 운용사 | String | Y | 4 | 0000:전체, 3020:KODEX(삼성), 3027:KOSEF(키움), 3191:TIGE |
| request | txon_yn | 과세여부 | String | Y | 1 | 0:전체, 1:과세, 2:비과세 |
| request | trace_idex | 추적지수 | String | Y | 1 | 0:전체 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT, 3:통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | etfall_mrpr | ETF전체시세 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_cls | 종목분류 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - close_pric | 종가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - pre_rt | 대비율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - nav | NAV | String | N | 20 |  |
| response | - trace_eor_rt | 추적오차율 | String | N | 20 |  |
| response | - txbs | 과표기준 | String | N | 20 |  |
| response | - dvid_bf_base | 배당전기준 | String | N | 20 |  |
| response | - pred_dvida | 전일배당금 | String | N | 20 |  |
| response | - trace_idex_nm | 추적지수명 | String | N | 20 |  |
| response | - drng | 배수 | String | N | 20 |  |
| response | - trace_idex_cd | 추적지수코드 | String | N | 20 |  |

> ... 외 2개 필드

---

### ETF시간대별추이요청 (ka40006)

- **API ID**: ka40006
- **Method**: POST
- **URL**: /api/dostk/etf
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_nm | 종목명 | String | N | 40 |  |
| response | etfobjt_idex_nm | ETF대상지수명 | String | N | 20 |  |
| response | wonju_pric | 원주가격 | String | N | 20 |  |
| response | etftxon_type | ETF과세유형 | String | N | 20 |  |
| response | etntxon_type | ETN과세유형 | String | N | 20 |  |
| response | etftisl_trnsn | ETF시간대별추이 | LIST | N |  |  |
| response | - tm | 시간 | String | N | 20 |  |
| response | - close_pric | 종가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - nav | NAV | String | N | 20 |  |
| response | - trde_prica | 거래대금 | String | N | 20 |  |
| response | - navidex | NAV지수 | String | N | 20 |  |
| response | - navetf | NAVETF | String | N | 20 |  |
| response | - trace | 추적 | String | N | 20 |  |

> ... 외 3개 필드

---

### ETF시간대별체결요청 (ka40007)

- **API ID**: ka40007
- **Method**: POST
- **URL**: /api/dostk/etf
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_cls | 종목분류 | String | N | 20 |  |
| response | stk_nm | 종목명 | String | N | 40 |  |
| response | etfobjt_idex_nm | ETF대상지수명 | String | N | 20 |  |
| response | etfobjt_idex_cd | ETF대상지수코드 | String | N | 20 |  |
| response | objt_idex_pre_rt | 대상지수대비율 | String | N | 20 |  |
| response | wonju_pric | 원주가격 | String | N | 20 |  |
| response | etftisl_cntr_array | ETF시간대별체결배열 | LIST | N |  |  |
| response | - cntr_tm | 체결시간 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - stex_tp | 거래소구분 | String | N | 20 | KRX , NXT , 통합 |

---

### ETF일자별체결요청 (ka40008)

- **API ID**: ka40008
- **Method**: POST
- **URL**: /api/dostk/etf
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | cntr_tm | 체결시간 | String | N | 20 |  |
| response | cur_prc | 현재가 | String | N | 20 |  |
| response | pre_sig | 대비기호 | String | N | 20 |  |
| response | pred_pre | 전일대비 | String | N | 20 |  |
| response | trde_qty | 거래량 | String | N | 20 |  |
| response | etfnetprps_qty_array | ETF순매수수량배열 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - cur_prc_n | 현재가n | String | N | 20 |  |
| response | - pre_sig_n | 대비기호n | String | N | 20 |  |
| response | - pred_pre_n | 전일대비n | String | N | 20 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - for_netprps_qty | 외인순매수수량 | String | N | 20 |  |
| response | - orgn_netprps_qty | 기관순매수수량 | String | N | 20 |  |

---

### ETF시간대별체결요청 (ka40009)

- **API ID**: ka40009
- **Method**: POST
- **URL**: /api/dostk/etf
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | etfnavarray | ETFNAV배열 | LIST | N |  |  |
| response | - nav | NAV | String | N | 20 |  |
| response | - navpred_pre | NAV전일대비 | String | N | 20 |  |
| response | - navflu_rt | NAV등락율 | String | N | 20 |  |
| response | - trace_eor_rt | 추적오차율 | String | N | 20 |  |
| response | - dispty_rt | 괴리율 | String | N | 20 |  |
| response | - stkcnt | 주식수 | String | N | 20 |  |
| response | - base_pric | 기준가 | String | N | 20 |  |
| response | - for_rmnd_qty | 외인보유수량 | String | N | 20 |  |
| response | - repl_pric | 대용가 | String | N | 20 |  |
| response | - conv_pric | 환산가격 | String | N | 20 |  |
| response | - drstk | DR/주 | String | N | 20 |  |
| response | - wonju_pric | 원주가격 | String | N | 20 |  |

---

### ETF시간대별추이요청 (ka40010)

- **API ID**: ka40010
- **Method**: POST
- **URL**: /api/dostk/etf
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 6 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | etftisl_trnsn | ETF시간대별추이 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - for_netprps | 외인순매수 | String | N | 20 |  |

---

### 금현물체결추이 (ka50010)

- **API ID**: ka50010
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | M04020000 금 99.99_1kg, M04020100 미니금 99.99_100g |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | gold_cntr | 금현물체결추이 | LIST | N |  |  |
| response | - cntr_pric | 체결가 | String | N | 20 |  |
| response | - pred_pre | 전일 대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 누적 거래량 | String | N | 20 |  |
| response | - acc_trde_prica | 누적 거래대금 | String | N | 20 |  |
| response | - cntr_trde_qty | 거래량(체결량) | String | N | 20 |  |
| response | - tm | 체결시간 | String | N | 20 |  |
| response | - pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pri_sel_bid_unit | 매도호가 | String | N | 20 |  |
| response | - pri_buy_bid_unit | 매수호가 | String | N | 20 |  |
| response | - trde_pre | 전일 거래량 대비 비율 | String | N | 20 |  |
| response | - trde_tern_rt | 전일 거래량 대비 순간 거래량 비율 | String | N | 20 |  |
| response | - cntr_str | 체결강도 | String | N | 20 |  |

---

### 금현물일별추이 (ka50012)

- **API ID**: ka50012
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | M04020000 금 99.99_1kg, M04020100 미니금 99.99_100g |
| request | base_dt | 기준일자 | String | Y | 8 | YYYYMMDD |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | gold_daly_trnsn | 금현물일별추이 | LIST | N |  |  |
| response | - cur_prc | 종가 | String | N | 20 |  |
| response | - pred_pre | 전일 대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 누적 거래량 | String | N | 20 |  |
| response | - acc_trde_prica | 누적 거래대금(백만) | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - orgn_netprps | 기관 순매수 수량 | String | N | 20 |  |
| response | - for_netprps | 외국인 순매수 수량 | String | N | 20 |  |
| response | - ind_netprps | 순매매량(개인) | String | N | 20 |  |

---

### 금현물틱차트조회요청 (ka50079)

- **API ID**: ka50079
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | M04020000 금 99.99_1kg, M04020100 미니금 99.99_100g |
| request | tic_scope | 틱범위 | String | Y | 2 | 1:1틱, 3:3틱, 5:5틱, 10:10틱, 30:30틱 |
| request | upd_stkpc_tp | 수정주가구분 | String | Y | 1 | 0 or 1 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | gds_tic_chart_qry | 금현물틱차트조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N |  |  |
| response | - cntr_tm | 체결시간 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |

---

### 금현물분봉차트조회요청 (ka50080)

- **API ID**: ka50080
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | M04020000 금 99.99_1kg, M04020100 미니금 99.99_100g |
| request | tic_scope | 틱범위 | String | Y | 3 | 1:1분, 3:3분, 5:5분, 10:10분, 15:15분, 30:30분, 45:45분,  |
| request | upd_stkpc_tp | 수정주가구분 | String | N | 1 | 0 or 1 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | gds_min_chart_qry | 금현물분봉차트조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |
| response | - cntr_tm | 체결시간 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |

---

### 금현물일봉차트조회요청 (ka50081)

- **API ID**: ka50081
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | M04020000 금 99.99_1kg, M04020100 미니금 99.99_100g |
| request | base_dt | 기준일자 | String | Y | 8 | YYYYMMDD |
| request | upd_stkpc_tp | 수정주가구분 | String | Y | 1 | 0 or 1 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | gds_day_chart_qry | 금현물일봉차트조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - acc_trde_qty | 누적 거래량 | String | N | 20 |  |
| response | - acc_trde_prica | 누적 거래대금 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |

---

### 금현물주봉차트조회요청 (ka50082)

- **API ID**: ka50082
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | M04020000 금 99.99_1kg, M04020100 미니금 99.99_100g |
| request | base_dt | 기준일자 | String | Y | 8 | YYYYMMDD |
| request | upd_stkpc_tp | 수정주가구분 | String | Y | 1 | 0 or 1 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | gds_week_chart_qry | 금현물일봉차트조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - acc_trde_qty | 누적 거래량 | String | N | 20 |  |
| response | - acc_trde_prica | 누적 거래대금 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |

---

### 금현물월봉차트조회요청 (ka50083)

- **API ID**: ka50083
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | M04020000 금 99.99_1kg, M04020100 미니금 99.99_100g |
| request | base_dt | 기준일자 | String | Y | 8 | YYYYMMDD |
| request | upd_stkpc_tp | 수정주가구분 | String | Y | 1 | 0 or 1 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | gds_month_chart_qry | 금현물일봉차트조회 | LIST | N |  |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - acc_trde_qty | 누적 거래량 | String | N | 20 |  |
| response | - acc_trde_prica | 누적 거래대금 | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |

---

### 금현물예상체결 (ka50087)

- **API ID**: ka50087
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | M04020000 금 99.99_1kg, M04020100 미니금 99.99_100g |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | gold_expt_exec | 금현물예상체결 | LIST | N |  |  |
| response | - exp_cntr_pric | 예상 체결가 | String | N | 20 |  |
| response | - exp_pred_pre | 예상 체결가 전일대비 | String | N | 20 |  |
| response | - exp_flu_rt | 예상 체결가 등락율 | String | N | 20 |  |
| response | - exp_acc_trde_qty | 예상 체결 수량(누적) | String | N | 20 |  |
| response | - exp_cntr_trde_qty | 예상 체결 수량 | String | N | 20 |  |
| response | - exp_tm | 예상 체결 시간 | String | N | 20 |  |
| response | - exp_pre_sig | 예상 체결가 전일대비기호 | String | N | 20 |  |
| response | - stex_tp | 거래소 구분 | String | N |  |  |

---

### 금현물당일틱차트조회요청 (ka50091)

- **API ID**: ka50091
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | M04020000 금 99.99_1kg, M04020100 미니금 99.99_100g |
| request | tic_scope | 틱범위 | String | Y | 2 | 1:1틱, 3:3틱, 5:5틱, 10:10틱, 30:30틱 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | gds_tic_chart_qry | 금현물일봉차트조회 | LIST | N |  |  |
| response | - cntr_pric | 체결가 | String | N | 20 |  |
| response | - pred_pre | 전일 대비(원) | String | N | 20 |  |
| response | - trde_qty | 거래량(체결량) | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |
| response | - cntr_tm | 체결시간 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |

---

### 금현물당일분봉차트조회요청 (ka50092)

- **API ID**: ka50092
- **Method**: POST
- **URL**: /api/dostk/chart
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | M04020000 금 99.99_1kg, M04020100 미니금 99.99_100g |
| request | tic_scope | 틱범위 | String | Y | 2 | 1:1틱, 3:3틱, 5:5틱, 10:10틱, 30:30틱 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | gds_min_chart_qry | 금현물일봉차트조회 | LIST | N |  |  |
| response | - cntr_pric | 체결가 | String | N | 20 |  |
| response | - pred_pre | 전일 대비(원) | String | N | 20 |  |
| response | - acc_trde_qty | 누적 거래량 | String | N | 20 |  |
| response | - acc_trde_prica | 누적 거래대금 | String | N | 20 |  |
| response | - trde_qty | 거래량(체결량) | String | N | 20 |  |
| response | - open_pric | 시가 | String | N | 20 |  |
| response | - high_pric | 고가 | String | N | 20 |  |
| response | - low_pric | 저가 | String | N | 20 |  |
| response | - cntr_tm | 체결시간 | String | N | 20 |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - pred_pre_sig | 전일대비기호 | String | N | 20 |  |

---

### 금현물 시세정보 (ka50100)

- **API ID**: ka50100
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | pred_pre_sig | 전일대비기호 | String | N | 20 |  |
| response | pred_pre | 전일대비 | String | N | 20 |  |
| response | flu_rt | 등락율 | String | N | 20 |  |
| response | trde_qty | 거래량 | String | N | 20 |  |
| response | open_pric | 시가 | String | N | 20 |  |
| response | high_pric | 고가 | String | N | 20 |  |
| response | low_pric | 저가 | String | N | 20 |  |
| response | pred_rt | 전일비 | String | N | 20 |  |
| response | upl_pric | 상한가 | String | N | 20 |  |
| response | lst_pric | 하한가 | String | N | 20 |  |
| response | pred_close_pric | 전일종가 | String | N | 20 |  |

---

### 금현물 호가 (ka50101)

- **API ID**: ka50101
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 20 | M04020000 금 99.99_1kg, M04020100 미니금 99.99_100g |
| request | tic_scope | 틱범위 | String | Y | 2 | 1:1틱, 3:3틱, 5:5틱, 10:10틱, 30:30틱 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | gold_bid | 금현물호가 | LIST | N |  |  |
| response | - cntr_pric | 체결가 | String | N | 20 |  |
| response | - pred_pre | 전일 대비(원) | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 누적 거래량 | String | N | 20 |  |
| response | - acc_trde_prica | 누적 거래대금 | String | N | 20 |  |
| response | - cntr_trde_qty | 거래량(체결량) | String | N | 20 |  |
| response | - tm | 체결시간 | String | N | 20 |  |
| response | - pre_sig | 전일대비기호 | String | N | 20 |  |
| response | - pri_sel_bid_unit | 매도호가 | String | N | 20 |  |
| response | - pri_buy_bid_unit | 매수호가 | String | N | 20 |  |
| response | - trde_pre | 전일 거래량 대비 비율 | String | N | 20 |  |
| response | - trde_tern_rt | 전일 거래량 대비 순간 거래량 비율 | String | N |  |  |
| response | - cntr_str | 체결강도 | String | N | 20 |  |
| response | - lpmmcm_nm_1 | K.O 접근도 | String | N | 20 |  |
| response | - stex_tp | 거래소구분 | String | N | 20 |  |

---

### 금현물투자자현황 (ka52301)

- **API ID**: ka52301
- **Method**: POST
- **URL**: /api/dostk/frgnistt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | inve_trad_stat | 금현물투자자현황 | LIST | N |  |  |
| response | - all_dfrt_trst_sell_qty | 투자자별 매도 수량(천) | String | N | 20 |  |
| response | - sell_qty_irds | 투자자별 매도 수량 증감(천) | String | N | 20 |  |
| response | - all_dfrt_trst_sell_amt | 투자자별 매도 금액(억) | String | N | 20 |  |
| response | - sell_amt_irds | 투자자별 매도 금액 증감(억) | String | N | 20 |  |
| response | - all_dfrt_trst_buy_qty | 투자자별 매수 수량(천) | String | N | 20 |  |
| response | - buy_qty_irds | 투자자별 매수 수량 증감(천) | String | N | 20 |  |
| response | - all_dfrt_trst_buy_amt | 투자자별 매수 금액(억) | String | N | 20 |  |
| response | - buy_amt_irds | 투자자별 매수 금액 증감(억) | String | N | 20 |  |
| response | - all_dfrt_trst_netprps_qty | 투자자별 순매수 수량(천) | String | N | 20 |  |
| response | - netprps_qty_irds | 투자자별 순매수 수량 증감(천) | String | N | 20 |  |
| response | - all_dfrt_trst_netprps_amt | 투자자별 순매수 금액(억) | String | N | 20 |  |
| response | - netprps_amt_irds | 투자자별 순매수 금액 증감(억) | String | N | 20 |  |
| response | - sell_uv | 투자자별 매도 단가 | String | N | 20 |  |
| response | - buy_uv | 투자자별 매수 단가 | String | N | 20 |  |
| response | - stk_nm | 투자자 구분명 | String | N | 20 |  |
| response | - acc_netprps_amt | 누적 순매수 금액(억) | String | N | 20 |  |

> ... 외 2개 필드

---

### 테마그룹별요청 (ka90001)

- **API ID**: ka90001
- **Method**: POST
- **URL**: /api/dostk/thme
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | qry_tp | 검색구분 | String | Y | 1 | 0:전체검색, 1:테마검색, 2:종목검색 |
| request | stk_cd | 종목코드 | String | N | 6 | 검색하려는 종목코드 |
| request | date_tp | 날짜구분 | String | Y | 2 | n일전 (1일 ~ 99일 날짜입력) |
| request | thema_nm | 테마명 | String | N | 50 | 검색하려는 테마명 |
| request | flu_pl_amt_tp | 등락수익구분 | String | Y | 1 | 1:상위기간수익률, 2:하위기간수익률, 3:상위등락률, 4:하위등락률 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | thema_grp | 테마그룹별 | LIST | N |  |  |
| response | - thema_grp_cd | 테마그룹코드 | String | N | 20 |  |
| response | - thema_nm | 테마명 | String | N | 20 |  |
| response | - stk_num | 종목수 | String | N | 20 |  |
| response | - flu_sig | 등락기호 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - rising_stk_num | 상승종목수 | String | N | 20 |  |
| response | - fall_stk_num | 하락종목수 | String | N | 20 |  |
| response | - dt_prft_rt | 기간수익률 | String | N | 20 |  |
| response | - main_stk | 주요종목 | String | N | 20 |  |

---

### 테마구성종목요청 (ka90002)

- **API ID**: ka90002
- **Method**: POST
- **URL**: /api/dostk/thme
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | date_tp | 날짜구분 | String | N | 1 | 1일 ~ 99일 날짜입력 |
| request | thema_grp_cd | 테마그룹코드 | String | Y | 6 | 테마그룹코드 번호 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | flu_rt | 등락률 | String | N | 20 |  |
| response | dt_prft_rt | 기간수익률 | String | N | 20 |  |
| response | thema_comp_stk | 테마구성종목 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - flu_sig | 등락기호 | String | N | 20 | 1: 상한가, 2:상승, 3:보합, 4:하한가, 5:하락 |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - sel_bid | 매도호가 | String | N | 20 |  |
| response | - sel_req | 매도잔량 | String | N | 20 |  |
| response | - buy_bid | 매수호가 | String | N | 20 |  |
| response | - buy_req | 매수잔량 | String | N | 20 |  |
| response | - dt_prft_rt_n | 기간수익률n | String | N | 20 |  |

---

### 프로그램순매수상위50요청 (ka90003)

- **API ID**: ka90003
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | trde_upper_tp | 매매상위구분 | String | Y | 1 | 1:순매도상위, 2:순매수상위 |
| request | amt_qty_tp | 금액수량구분 | String | Y | 2 | 1:금액, 2:수량 |
| request | mrkt_tp | 시장구분 | String | Y | 10 | P00101:코스피, P10102:코스닥 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | prm_netprps_upper_50 | 프로그램순매수상위50 | LIST | N |  |  |
| response | - rank | 순위 | String | N | 20 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - flu_sig | 등락기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - acc_trde_qty | 누적거래량 | String | N | 20 |  |
| response | - prm_sell_amt | 프로그램매도금액 | String | N | 20 |  |
| response | - prm_buy_amt | 프로그램매수금액 | String | N | 20 |  |
| response | - prm_netprps_amt | 프로그램순매수금액 | String | N | 20 |  |

---

### 종목별프로그램매매현황요청 (ka90004)

- **API ID**: ka90004
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | dt | 일자 | String | Y | 8 | YYYYMMDD |
| request | mrkt_tp | 시장구분 | String | Y | 10 | P00101:코스피, P10102:코스닥 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | tot_1 | 매수체결수량합계 | String | N | 20 |  |
| response | tot_2 | 매수체결금액합계 | String | N | 20 |  |
| response | tot_3 | 매도체결수량합계 | String | N | 20 |  |
| response | tot_4 | 매도체결금액합계 | String | N | 20 |  |
| response | tot_5 | 순매수대금합계 | String | N | 20 |  |
| response | tot_6 | 합계6 | String | N | 20 |  |
| response | stk_prm_trde_prst | 종목별프로그램매매현황 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - flu_sig | 등락기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - buy_cntr_qty | 매수체결수량 | String | N | 20 |  |
| response | - buy_cntr_amt | 매수체결금액 | String | N | 20 |  |
| response | - sel_cntr_qty | 매도체결수량 | String | N | 20 |  |
| response | - sel_cntr_amt | 매도체결금액 | String | N | 20 |  |
| response | - netprps_prica | 순매수대금 | String | N | 20 |  |

> ... 외 1개 필드

---

### 프로그램매매추이요청 시간대별 (ka90005)

- **API ID**: ka90005
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | date | 날짜 | String | Y | 8 | YYYYMMDD |
| request | amt_qty_tp | 금액수량구분 | String | Y | 1 | 1:금액(백만원), 2:수량(천주) |
| request | mrkt_tp | 시장구분 | String | Y | 10 | 코스피- 거래소구분값 1일경우:P00101, 2일경우:P001_NX01, 3일경우:P001 |
| request | min_tic_tp | 분틱구분 | String | Y | 1 | 0:틱, 1:분 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | prm_trde_trnsn | 프로그램매매추이 | LIST | N |  |  |
| response | - cntr_tm | 체결시간 | String | N | 20 |  |
| response | - dfrt_trde_sel | 차익거래매도 | String | N | 20 |  |
| response | - dfrt_trde_buy | 차익거래매수 | String | N | 20 |  |
| response | - dfrt_trde_netprps | 차익거래순매수 | String | N | 20 |  |
| response | - ndiffpro_trde_sel | 비차익거래매도 | String | N | 20 |  |
| response | - ndiffpro_trde_buy | 비차익거래매수 | String | N | 20 |  |
| response | - ndiffpro_trde_netprps | 비차익거래순매수 | String | N | 20 |  |
| response | - dfrt_trde_sell_qty | 차익거래매도수량 | String | N | 20 |  |
| response | - dfrt_trde_buy_qty | 차익거래매수수량 | String | N | 20 |  |
| response | - dfrt_trde_netprps_qty | 차익거래순매수수량 | String | N | 20 |  |
| response | - ndiffpro_trde_sell_qty | 비차익거래매도수량 | String | N | 20 |  |
| response | - ndiffpro_trde_buy_qty | 비차익거래매수수량 | String | N | 20 |  |
| response | - ndiffpro_trde_netprps_qty | 비차익거래순매수수량 | String | N | 20 |  |
| response | - all_sel | 전체매도 | String | N | 20 |  |
| response | - all_buy | 전체매수 | String | N | 20 |  |
| response | - all_netprps | 전체순매수 | String | N | 20 |  |

> ... 외 2개 필드

---

### 프로그램매매차익잔고추이요청 (ka90006)

- **API ID**: ka90006
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | date | 날짜 | String | Y | 8 | YYYYMMDD |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | prm_trde_dfrt_remn_trnsn | 프로그램매매차익잔고추이 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - buy_dfrt_trde_qty | 매수차익거래수량 | String | N | 20 |  |
| response | - buy_dfrt_trde_amt | 매수차익거래금액 | String | N | 20 |  |
| response | - buy_dfrt_trde_irds_amt | 매수차익거래증감액 | String | N | 20 |  |
| response | - sel_dfrt_trde_qty | 매도차익거래수량 | String | N | 20 |  |
| response | - sel_dfrt_trde_amt | 매도차익거래금액 | String | N | 20 |  |
| response | - sel_dfrt_trde_irds_amt | 매도차익거래증감액 | String | N | 20 |  |

---

### 프로그램매매누적추이요청 (ka90007)

- **API ID**: ka90007
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | date | 날짜 | String | Y | 8 | YYYYMMDD (종료일기준 1년간 데이터만 조회가능) |
| request | amt_qty_tp | 금액수량구분 | String | Y | 1 | 1:금액, 2:수량 |
| request | mrkt_tp | 시장구분 | String | Y | 5 | 0:코스피 , 1:코스닥 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT, 3:통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | prm_trde_acc_trnsn | 프로그램매매누적추이 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - kospi200 | KOSPI200 | String | N | 20 |  |
| response | - basis | BASIS | String | N | 20 |  |
| response | - dfrt_trde_tdy | 차익거래당일 | String | N | 20 |  |
| response | - dfrt_trde_acc | 차익거래누적 | String | N | 20 |  |
| response | - ndiffpro_trde_tdy | 비차익거래당일 | String | N | 20 |  |
| response | - ndiffpro_trde_acc | 비차익거래누적 | String | N | 20 |  |
| response | - all_tdy | 전체당일 | String | N | 20 |  |
| response | - all_acc | 전체누적 | String | N | 20 |  |

---

### 종목시간별프로그램매매추이요청 (ka90008)

- **API ID**: ka90008
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | amt_qty_tp | 금액수량구분 | String | Y | 1 | 1:금액, 2:수량 |
| request | stk_cd | 종목코드 | String | Y | 6 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | date | 날짜 | String | Y | 8 | YYYYMMDD |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_tm_prm_trde_trnsn | 종목시간별프로그램매매추이 | LIST | N |  |  |
| response | - tm | 시간 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - prm_sell_amt | 프로그램매도금액 | String | N | 20 |  |
| response | - prm_buy_amt | 프로그램매수금액 | String | N | 20 |  |
| response | - prm_netprps_amt | 프로그램순매수금액 | String | N | 20 |  |
| response | - prm_netprps_amt_irds | 프로그램순매수금액증감 | String | N | 20 |  |
| response | - prm_sell_qty | 프로그램매도수량 | String | N | 20 |  |
| response | - prm_buy_qty | 프로그램매수수량 | String | N | 20 |  |
| response | - prm_netprps_qty | 프로그램순매수수량 | String | N | 20 |  |
| response | - prm_netprps_qty_irds | 프로그램순매수수량증감 | String | N | 20 |  |
| response | - base_pric_tm | 기준가시간 | String | N | 20 |  |
| response | - dbrt_trde_rpy_sum | 대차거래상환주수합 | String | N | 20 |  |

> ... 외 2개 필드

---

### 외국인기관매매상위요청 (ka90009)

- **API ID**: ka90009
- **Method**: POST
- **URL**: /api/dostk/rkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | mrkt_tp | 시장구분 | String | Y | 3 | 000:전체, 001:코스피, 101:코스닥 |
| request | amt_qty_tp | 금액수량구분 | String | Y | 1 | 1:금액(천만), 2:수량(천) |
| request | qry_dt_tp | 조회일자구분 | String | Y | 1 | 0:조회일자 미포함, 1:조회일자 포함 |
| request | date | 날짜 | String | N | 8 | YYYYMMDD
(연도4자리, 월 2자리, 일 2자리 형식) |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT, 3:통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | frgnr_orgn_trde_upper | 외국인기관매매상위 | LIST | N |  |  |
| response | - for_netslmt_stk_cd | 외인순매도종목코드 | String | N | 20 |  |
| response | - for_netslmt_stk_nm | 외인순매도종목명 | String | N | 20 |  |
| response | - for_netslmt_amt | 외인순매도금액 | String | N | 20 |  |
| response | - for_netslmt_qty | 외인순매도수량 | String | N | 20 |  |
| response | - for_netprps_stk_cd | 외인순매수종목코드 | String | N | 20 |  |
| response | - for_netprps_stk_nm | 외인순매수종목명 | String | N | 20 |  |
| response | - for_netprps_amt | 외인순매수금액 | String | N | 20 |  |
| response | - for_netprps_qty | 외인순매수수량 | String | N | 20 |  |
| response | - orgn_netslmt_stk_cd | 기관순매도종목코드 | String | N | 20 |  |
| response | - orgn_netslmt_stk_nm | 기관순매도종목명 | String | N | 20 |  |
| response | - orgn_netslmt_amt | 기관순매도금액 | String | N | 20 |  |
| response | - orgn_netslmt_qty | 기관순매도수량 | String | N | 20 |  |
| response | - orgn_netprps_stk_cd | 기관순매수종목코드 | String | N | 20 |  |
| response | - orgn_netprps_stk_nm | 기관순매수종목명 | String | N | 20 |  |
| response | - orgn_netprps_amt | 기관순매수금액 | String | N | 20 |  |
| response | - orgn_netprps_qty | 기관순매수수량 | String | N | 20 |  |

---

### 프로그램매매추이요청 일자별 (ka90010)

- **API ID**: ka90010
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | date | 날짜 | String | Y | 8 | YYYYMMDD |
| request | amt_qty_tp | 금액수량구분 | String | Y | 1 | 1:금액(백만원), 2:수량(천주) |
| request | mrkt_tp | 시장구분 | String | Y | 10 | 코스피- 거래소구분값 1일경우:P00101, 2일경우:P001_NX01, 3일경우:P001 |
| request | min_tic_tp | 분틱구분 | String | Y | 1 | 0:틱, 1:분 |
| request | stex_tp | 거래소구분 | String | Y | 1 | 1:KRX, 2:NXT 3.통합 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | prm_trde_trnsn | 프로그램매매추이 | LIST | N |  |  |
| response | - cntr_tm | 체결시간 | String | N | 20 |  |
| response | - dfrt_trde_sel | 차익거래매도 | String | N | 20 |  |
| response | - dfrt_trde_buy | 차익거래매수 | String | N | 20 |  |
| response | - dfrt_trde_netprps | 차익거래순매수 | String | N | 20 |  |
| response | - ndiffpro_trde_sel | 비차익거래매도 | String | N | 20 |  |
| response | - ndiffpro_trde_buy | 비차익거래매수 | String | N | 20 |  |
| response | - ndiffpro_trde_netprps | 비차익거래순매수 | String | N | 20 |  |
| response | - dfrt_trde_sell_qty | 차익거래매도수량 | String | N | 20 |  |
| response | - dfrt_trde_buy_qty | 차익거래매수수량 | String | N | 20 |  |
| response | - dfrt_trde_netprps_qty | 차익거래순매수수량 | String | N | 20 |  |
| response | - ndiffpro_trde_sell_qty | 비차익거래매도수량 | String | N | 20 |  |
| response | - ndiffpro_trde_buy_qty | 비차익거래매수수량 | String | N | 20 |  |
| response | - ndiffpro_trde_netprps_qty | 비차익거래순매수수량 | String | N | 20 |  |
| response | - all_sel | 전체매도 | String | N | 20 |  |
| response | - all_buy | 전체매수 | String | N | 20 |  |
| response | - all_netprps | 전체순매수 | String | N | 20 |  |

> ... 외 2개 필드

---

### 대차거래내역요청 (ka90012)

- **API ID**: ka90012
- **Method**: POST
- **URL**: /api/dostk/slb
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | dt | 일자 | String | Y | 8 | YYYYMMDD |
| request | mrkt_tp | 시장구분 | String | Y | 3 | 001:코스피, 101:코스닥 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | dbrt_trde_prps | 대차거래내역 | LIST | N |  |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - stk_cd | 종목코드 | String | N | 20 |  |
| response | - dbrt_trde_cntrcnt | 대차거래체결주수 | String | N | 20 |  |
| response | - dbrt_trde_rpy | 대차거래상환주수 | String | N | 20 |  |
| response | - rmnd | 잔고주수 | String | N | 20 |  |
| response | - remn_amt | 잔고금액 | String | N | 20 |  |

---

### 종목일별프로그램매매추이요청 (ka90013)

- **API ID**: ka90013
- **Method**: POST
- **URL**: /api/dostk/mrkcond
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | amt_qty_tp | 금액수량구분 | String | N | 1 | 1:금액, 2:수량 |
| request | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드
(KRX:039490,NXT:039490_NX,SOR:039490_AL) |
| request | date | 날짜 | String | N | 8 | YYYYMMDD |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_daly_prm_trde_trnsn | 종목일별프로그램매매추이 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 20 |  |
| response | - cur_prc | 현재가 | String | N | 20 |  |
| response | - pre_sig | 대비기호 | String | N | 20 |  |
| response | - pred_pre | 전일대비 | String | N | 20 |  |
| response | - flu_rt | 등락율 | String | N | 20 |  |
| response | - trde_qty | 거래량 | String | N | 20 |  |
| response | - prm_sell_amt | 프로그램매도금액 | String | N | 20 |  |
| response | - prm_buy_amt | 프로그램매수금액 | String | N | 20 |  |
| response | - prm_netprps_amt | 프로그램순매수금액 | String | N | 20 |  |
| response | - prm_netprps_amt_irds | 프로그램순매수금액증감 | String | N | 20 |  |
| response | - prm_sell_qty | 프로그램매도수량 | String | N | 20 |  |
| response | - prm_buy_qty | 프로그램매수수량 | String | N | 20 |  |
| response | - prm_netprps_qty | 프로그램순매수수량 | String | N | 20 |  |
| response | - prm_netprps_qty_irds | 프로그램순매수수량증감 | String | N | 20 |  |
| response | - base_pric_tm | 기준가시간 | String | N | 20 |  |
| response | - dbrt_trde_rpy_sum | 대차거래상환주수합 | String | N | 20 |  |

> ... 외 2개 필드

---

### 예수금상세현황요청 (kt00001)

- **API ID**: kt00001
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | qry_tp | 조회구분 | String | Y | 1 | 3:추정조회, 2:일반조회 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | entr | 예수금 | String | N | 15 |  |
| response | profa_ch | 주식증거금현금 | String | N | 15 |  |
| response | bncr_profa_ch | 수익증권증거금현금 | String | N | 15 |  |
| response | nxdy_bncr_sell_exct | 익일수익증권매도정산대금 | String | N | 15 |  |
| response | fc_stk_krw_repl_set_amt | 해외주식원화대용설정금 | String | N | 15 |  |
| response | crd_grnta_ch | 신용보증금현금 | String | N | 15 |  |
| response | crd_grnt_ch | 신용담보금현금 | String | N | 15 |  |
| response | add_grnt_ch | 추가담보금현금 | String | N | 15 |  |
| response | etc_profa | 기타증거금 | String | N | 15 |  |
| response | uncl_stk_amt | 미수확보금 | String | N | 15 |  |
| response | shrts_prica | 공매도대금 | String | N | 15 |  |
| response | crd_set_grnta | 신용설정평가금 | String | N | 15 |  |
| response | chck_ina_amt | 수표입금액 | String | N | 15 |  |
| response | etc_chck_ina_amt | 기타수표입금액 | String | N | 15 |  |
| response | crd_grnt_ruse | 신용담보재사용 | String | N | 15 |  |
| response | knx_asset_evltv | 코넥스기본예탁금 | String | N | 15 |  |
| response | elwdpst_evlta | ELW예탁평가금 | String | N | 15 |  |

> ... 외 67개 필드

---

### 일별추정예탁자산현황요청 (kt00002)

- **API ID**: kt00002
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | start_dt | 시작조회기간 | String | Y | 8 | YYYYMMDD |
| request | end_dt | 종료조회기간 | String | Y | 8 | YYYYMMDD |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | daly_prsm_dpst_aset_amt_prst | 일별추정예탁자산현황 | LIST | N |  |  |
| response | - dt | 일자 | String | N | 8 |  |
| response | - entr | 예수금 | String | N | 12 |  |
| response | - grnt_use_amt | 담보대출금 | String | N | 12 |  |
| response | - crd_loan | 신용융자금 | String | N | 12 |  |
| response | - ls_grnt | 대주담보금 | String | N | 12 |  |
| response | - repl_amt | 대용금 | String | N | 12 |  |
| response | - prsm_dpst_aset_amt | 추정예탁자산 | String | N | 12 |  |
| response | - prsm_dpst_aset_amt_bncr_skip | 추정예탁자산수익증권제외 | String | N | 12 |  |

---

### 추정자산조회요청 (kt00003)

- **API ID**: kt00003
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | qry_tp | 상장폐지조회구분 | String | Y | 1 | 0:전체, 1:상장폐지종목제외 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | prsm_dpst_aset_amt | 추정예탁자산 | String | N | 12 |  |

---

### 계좌평가현황요청 (kt00004)

- **API ID**: kt00004
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | qry_tp | 상장폐지조회구분 | String | Y | 1 | 0:전체, 1:상장폐지종목제외 |
| request | dmst_stex_tp | 국내거래소구분 | String | Y | 6 | KRX:한국거래소,NXT:넥스트트레이드 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | acnt_nm | 계좌명 | String | N | 30 |  |
| response | brch_nm | 지점명 | String | N | 30 |  |
| response | entr | 예수금 | String | N | 12 |  |
| response | d2_entra | D+2추정예수금 | String | N | 12 |  |
| response | tot_est_amt | 유가잔고평가액 | String | N | 12 |  |
| response | aset_evlt_amt | 예탁자산평가액 | String | N | 12 |  |
| response | tot_pur_amt | 총매입금액 | String | N | 12 |  |
| response | prsm_dpst_aset_amt | 추정예탁자산 | String | N | 12 |  |
| response | tot_grnt_sella | 매도담보대출금 | String | N | 12 |  |
| response | tdy_lspft_amt | 당일투자원금 | String | N | 12 |  |
| response | invt_bsamt | 당월투자원금 | String | N | 12 |  |
| response | lspft_amt | 누적투자원금 | String | N | 12 |  |
| response | tdy_lspft | 당일투자손익 | String | N | 12 |  |
| response | lspft2 | 당월투자손익 | String | N | 12 |  |
| response | lspft | 누적투자손익 | String | N | 12 |  |
| response | tdy_lspft_rt | 당일손익율 | String | N | 12 |  |
| response | lspft_ratio | 당월손익율 | String | N | 12 |  |

> ... 외 17개 필드

---

### 체결잔고요청 (kt00005)

- **API ID**: kt00005
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | dmst_stex_tp | 국내거래소구분 | String | Y | 6 | KRX:한국거래소,NXT:넥스트트레이드 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | entr | 예수금 | String | N | 12 |  |
| response | entr_d1 | 예수금D+1 | String | N | 12 |  |
| response | entr_d2 | 예수금D+2 | String | N | 12 |  |
| response | pymn_alow_amt | 출금가능금액 | String | N | 12 |  |
| response | uncl_stk_amt | 미수확보금 | String | N | 12 |  |
| response | repl_amt | 대용금 | String | N | 12 |  |
| response | rght_repl_amt | 권리대용금 | String | N | 12 |  |
| response | ord_alowa | 주문가능현금 | String | N | 12 |  |
| response | ch_uncla | 현금미수금 | String | N | 12 |  |
| response | crd_int_npay_gold | 신용이자미납금 | String | N | 12 |  |
| response | etc_loana | 기타대여금 | String | N | 12 |  |
| response | nrpy_loan | 미상환융자금 | String | N | 12 |  |
| response | profa_ch | 증거금현금 | String | N | 12 |  |
| response | repl_profa | 증거금대용 | String | N | 12 |  |
| response | stk_buy_tot_amt | 주식매수총액 | String | N | 12 |  |
| response | evlt_amt_tot | 평가금액합계 | String | N | 12 |  |
| response | tot_pl_tot | 총손익합계 | String | N | 12 |  |

> ... 외 27개 필드

---

### 계좌별주문체결내역상세요청 (kt00007)

- **API ID**: kt00007
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | ord_dt | 주문일자 | String | N | 8 | YYYYMMDD |
| request | qry_tp | 조회구분 | String | Y | 1 | 1:주문순, 2:역순, 3:미체결, 4:체결내역만 |
| request | stk_bond_tp | 주식채권구분 | String | Y | 1 | 0:전체, 1:주식, 2:채권 |
| request | sell_tp | 매도수구분 | String | Y | 1 | 0:전체, 1:매도, 2:매수 |
| request | stk_cd | 종목코드 | String | N | 12 | 공백허용 (공백일때 전체종목) |
| request | fr_ord_no | 시작주문번호 | String | N | 7 | 공백허용 (공백일때 전체주문) |
| request | dmst_stex_tp | 국내거래소구분 | String | Y | 6 | %:(전체),KRX:한국거래소,NXT:넥스트트레이드,SOR:최선주문집행 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | acnt_ord_cntr_prps_dtl | 계좌별주문체결내역상세 | LIST | N |  |  |
| response | - ord_no | 주문번호 | String | N | 7 |  |
| response | - stk_cd | 종목번호 | String | N | 12 |  |
| response | - trde_tp | 매매구분 | String | N | 20 |  |
| response | - crd_tp | 신용구분 | String | N | 20 |  |
| response | - ord_qty | 주문수량 | String | N | 10 |  |
| response | - ord_uv | 주문단가 | String | N | 10 |  |
| response | - cnfm_qty | 확인수량 | String | N | 10 |  |
| response | - acpt_tp | 접수구분 | String | N | 20 |  |
| response | - rsrv_tp | 반대여부 | String | N | 20 |  |
| response | - ord_tm | 주문시간 | String | N | 8 |  |
| response | - ori_ord | 원주문 | String | N | 7 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - io_tp_nm | 주문구분 | String | N | 20 |  |
| response | - loan_dt | 대출일 | String | N | 8 |  |
| response | - cntr_qty | 체결수량 | String | N | 10 |  |
| response | - cntr_uv | 체결단가 | String | N | 10 |  |

> ... 외 6개 필드

---

### 계좌별익일결제예정내역요청 (kt00008)

- **API ID**: kt00008
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | strt_dcd_seq | 시작결제번호 | String | N | 7 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | trde_dt | 매매일자 | String | N | 8 |  |
| response | setl_dt | 결제일자 | String | N | 8 |  |
| response | sell_amt_sum | 매도정산합 | String | N | 12 |  |
| response | buy_amt_sum | 매수정산합 | String | N | 12 |  |
| response | acnt_nxdy_setl_frcs_prps_array | 계좌별익일결제예정내역배열 | LIST | N |  |  |
| response | - seq | 일련번호 | String | N | 7 |  |
| response | - stk_cd | 종목번호 | String | N | 12 |  |
| response | - loan_dt | 대출일 | String | N | 8 |  |
| response | - qty | 수량 | String | N | 12 |  |
| response | - engg_amt | 약정금액 | String | N | 12 |  |
| response | - cmsn | 수수료 | String | N | 12 |  |
| response | - incm_tax | 소득세 | String | N | 12 |  |
| response | - rstx | 농특세 | String | N | 12 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - sell_tp | 매도수구분 | String | N | 10 |  |
| response | - unp | 단가 | String | N | 12 |  |
| response | - exct_amt | 정산금액 | String | N | 12 |  |

> ... 외 3개 필드

---

### 계좌별주문체결현황요청 (kt00009)

- **API ID**: kt00009
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | ord_dt | 주문일자 | String | N | 8 | YYYYMMDD |
| request | stk_bond_tp | 주식채권구분 | String | Y | 1 | 0:전체, 1:주식, 2:채권 |
| request | mrkt_tp | 시장구분 | String | Y | 1 | 0:전체, 1:코스피, 2:코스닥, 3:OTCBB, 4:ECN |
| request | sell_tp | 매도수구분 | String | Y | 1 | 0:전체, 1:매도, 2:매수 |
| request | qry_tp | 조회구분 | String | Y | 1 | 0:전체, 1:체결 |
| request | stk_cd | 종목코드 | String | N | 12 | 전문 조회할 종목코드 |
| request | fr_ord_no | 시작주문번호 | String | N | 7 |  |
| request | dmst_stex_tp | 국내거래소구분 | String | Y | 6 | %:(전체),KRX:한국거래소,NXT:넥스트트레이드,SOR:최선주문집행 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | sell_grntl_engg_amt | 매도약정금액 | String | N | 12 |  |
| response | buy_engg_amt | 매수약정금액 | String | N | 12 |  |
| response | engg_amt | 약정금액 | String | N | 12 |  |
| response | acnt_ord_cntr_prst_array | 계좌별주문체결현황배열 | LIST | N |  |  |
| response | - stk_bond_tp | 주식채권구분 | String | N | 1 |  |
| response | - ord_no | 주문번호 | String | N | 7 |  |
| response | - stk_cd | 종목번호 | String | N | 12 |  |
| response | - trde_tp | 매매구분 | String | N | 15 |  |
| response | - io_tp_nm | 주문유형구분 | String | N | 20 |  |
| response | - ord_qty | 주문수량 | String | N | 10 |  |
| response | - ord_uv | 주문단가 | String | N | 10 |  |
| response | - cnfm_qty | 확인수량 | String | N | 10 |  |
| response | - rsrv_oppo | 예약/반대 | String | N | 4 |  |
| response | - cntr_no | 체결번호 | String | N | 7 |  |
| response | - acpt_tp | 접수구분 | String | N | 8 |  |
| response | - orig_ord_no | 원주문번호 | String | N | 7 |  |
| response | - stk_nm | 종목명 | String | N | 20 |  |

> ... 외 9개 필드

---

### 주문인출가능금액요청 (kt00010)

- **API ID**: kt00010
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | io_amt | 입출금액 | String | N | 12 |  |
| request | stk_cd | 종목번호 | String | Y | 12 |  |
| request | trde_tp | 매매구분 | String | Y | 1 | 1:매도, 2:매수 |
| request | trde_qty | 매매수량 | String | N | 10 |  |
| request | uv | 매수가격 | String | Y | 10 |  |
| request | exp_buy_unp | 예상매수단가 | String | N | 10 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | profa_20ord_alow_amt | 증거금20%주문가능금액 | String | N | 12 |  |
| response | profa_20ord_alowq | 증거금20%주문가능수량 | String | N | 10 |  |
| response | profa_30ord_alow_amt | 증거금30%주문가능금액 | String | N | 12 |  |
| response | profa_30ord_alowq | 증거금30%주문가능수량 | String | N | 10 |  |
| response | profa_40ord_alow_amt | 증거금40%주문가능금액 | String | N | 12 |  |
| response | profa_40ord_alowq | 증거금40%주문가능수량 | String | N | 10 |  |
| response | profa_50ord_alow_amt | 증거금50%주문가능금액 | String | N | 12 |  |
| response | profa_50ord_alowq | 증거금50%주문가능수량 | String | N | 10 |  |
| response | profa_60ord_alow_amt | 증거금60%주문가능금액 | String | N | 12 |  |
| response | profa_60ord_alowq | 증거금60%주문가능수량 | String | N | 10 |  |
| response | profa_rdex_60ord_alow_amt | 증거금감면60%주문가능금 | String | N | 12 |  |
| response | profa_rdex_60ord_alowq | 증거금감면60%주문가능수 | String | N | 10 |  |
| response | profa_100ord_alow_amt | 증거금100%주문가능금액 | String | N | 12 |  |
| response | profa_100ord_alowq | 증거금100%주문가능수량 | String | N | 10 |  |
| response | pred_reu_alowa | 전일재사용가능금액 | String | N | 12 |  |
| response | tdy_reu_alowa | 금일재사용가능금액 | String | N | 12 |  |
| response | entr | 예수금 | String | N | 12 |  |

> ... 외 11개 필드

---

### 증거금율별주문가능수량조회요청 (kt00011)

- **API ID**: kt00011
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목번호 | String | Y | 12 |  |
| request | uv | 매수가격 | String | N | 10 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_profa_rt | 종목증거금율 | String | N | 15 |  |
| response | profa_rt | 계좌증거금율 | String | N | 15 |  |
| response | aplc_rt | 적용증거금율 | String | N | 15 |  |
| response | profa_20ord_alow_amt | 증거금20%주문가능금액 | String | N | 12 |  |
| response | profa_20ord_alowq | 증거금20%주문가능수량 | String | N | 12 |  |
| response | profa_20pred_reu_amt | 증거금20%전일재사용금액 | String | N | 12 |  |
| response | profa_20tdy_reu_amt | 증거금20%금일재사용금액 | String | N | 12 |  |
| response | profa_30ord_alow_amt | 증거금30%주문가능금액 | String | N | 12 |  |
| response | profa_30ord_alowq | 증거금30%주문가능수량 | String | N | 12 |  |
| response | profa_30pred_reu_amt | 증거금30%전일재사용금액 | String | N | 12 |  |
| response | profa_30tdy_reu_amt | 증거금30%금일재사용금액 | String | N | 12 |  |
| response | profa_40ord_alow_amt | 증거금40%주문가능금액 | String | N | 12 |  |
| response | profa_40ord_alowq | 증거금40%주문가능수량 | String | N | 12 |  |
| response | profa_40pred_reu_amt | 증거금40전일재사용금액 | String | N | 12 |  |
| response | profa_40tdy_reu_amt | 증거금40%금일재사용금액 | String | N | 12 |  |
| response | profa_50ord_alow_amt | 증거금50%주문가능금액 | String | N | 12 |  |
| response | profa_50ord_alowq | 증거금50%주문가능수량 | String | N | 12 |  |

> ... 외 19개 필드

---

### 신용보증금율별주문가능수량조회요청 (kt00012)

- **API ID**: kt00012
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목번호 | String | Y | 12 |  |
| request | uv | 매수가격 | String | N | 10 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_assr_rt | 종목보증금율 | String | N | 1 |  |
| response | stk_assr_rt_nm | 종목보증금율명 | String | N | 4 |  |
| response | assr_30ord_alow_amt | 보증금30%주문가능금액 | String | N | 12 |  |
| response | assr_30ord_alowq | 보증금30%주문가능수량 | String | N | 12 |  |
| response | assr_30pred_reu_amt | 보증금30%전일재사용금액 | String | N | 12 |  |
| response | assr_30tdy_reu_amt | 보증금30%금일재사용금액 | String | N | 12 |  |
| response | assr_40ord_alow_amt | 보증금40%주문가능금액 | String | N | 12 |  |
| response | assr_40ord_alowq | 보증금40%주문가능수량 | String | N | 12 |  |
| response | assr_40pred_reu_amt | 보증금40%전일재사용금액 | String | N | 12 |  |
| response | assr_40tdy_reu_amt | 보증금40%금일재사용금액 | String | N | 12 |  |
| response | assr_50ord_alow_amt | 보증금50%주문가능금액 | String | N | 12 |  |
| response | assr_50ord_alowq | 보증금50%주문가능수량 | String | N | 12 |  |
| response | assr_50pred_reu_amt | 보증금50%전일재사용금액 | String | N | 12 |  |
| response | assr_50tdy_reu_amt | 보증금50%금일재사용금액 | String | N | 12 |  |
| response | assr_60ord_alow_amt | 보증금60%주문가능금액 | String | N | 12 |  |
| response | assr_60ord_alowq | 보증금60%주문가능수량 | String | N | 12 |  |
| response | assr_60pred_reu_amt | 보증금60%전일재사용금액 | String | N | 12 |  |

> ... 외 10개 필드

---

### 증거금세부내역조회요청 (kt00013)

- **API ID**: kt00013
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | tdy_reu_objt_amt | 금일재사용대상금액 | String | N | 15 |  |
| response | tdy_reu_use_amt | 금일재사용사용금액 | String | N | 15 |  |
| response | tdy_reu_alowa | 금일재사용가능금액 | String | N | 15 |  |
| response | tdy_reu_lmtt_amt | 금일재사용제한금액 | String | N | 15 |  |
| response | tdy_reu_alowa_fin | 금일재사용가능금액최종 | String | N | 15 |  |
| response | pred_reu_objt_amt | 전일재사용대상금액 | String | N | 15 |  |
| response | pred_reu_use_amt | 전일재사용사용금액 | String | N | 15 |  |
| response | pred_reu_alowa | 전일재사용가능금액 | String | N | 15 |  |
| response | pred_reu_lmtt_amt | 전일재사용제한금액 | String | N | 15 |  |
| response | pred_reu_alowa_fin | 전일재사용가능금액최종 | String | N | 15 |  |
| response | ch_amt | 현금금액 | String | N | 15 |  |
| response | ch_profa | 현금증거금 | String | N | 15 |  |
| response | use_pos_ch | 사용가능현금 | String | N | 15 |  |
| response | ch_use_lmtt_amt | 현금사용제한금액 | String | N | 15 |  |
| response | use_pos_ch_fin | 사용가능현금최종 | String | N | 15 |  |
| response | repl_amt_amt | 대용금액 | String | N | 15 |  |
| response | repl_profa | 대용증거금 | String | N | 15 |  |

> ... 외 33개 필드

---

### 위탁종합거래내역요청 (kt00015)

- **API ID**: kt00015
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | strt_dt | 시작일자 | String | Y | 8 |  |
| request | end_dt | 종료일자 | String | Y | 8 |  |
| request | tp | 구분 | String | Y | 1 | 0:전체,1:입출금,2:입출고,3:매매,4:매수,5:매도,6:입금,7:출금,A:예탁담보대출 |
| request | stk_cd | 종목코드 | String | N | 12 |  |
| request | crnc_cd | 통화코드 | String | N | 3 |  |
| request | gds_tp | 상품구분 | String | Y | 1 | 0:전체, 1:국내주식, 2:수익증권, 3:해외주식, 4:금융상품 |
| request | frgn_stex_code | 해외거래소코드 | String | N | 10 |  |
| request | dmst_stex_tp | 국내거래소구분 | String | Y | 6 | %:(전체),KRX:한국거래소,NXT:넥스트트레이드 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | trst_ovrl_trde_prps_array | 위탁종합거래내역배열 | LIST | N |  |  |
| response | - trde_dt | 거래일자 | String | N | 8 |  |
| response | - trde_no | 거래번호 | String | N | 9 |  |
| response | - rmrk_nm | 적요명 | String | N | 60 |  |
| response | - crd_deal_tp_nm | 신용거래구분명 | String | N | 20 |  |
| response | - exct_amt | 정산금액 | String | N | 15 |  |
| response | - loan_amt_rpya | 대출금상환 | String | N | 15 |  |
| response | - fc_trde_amt | 거래금액(외) | String | N | 15 |  |
| response | - fc_exct_amt | 정산금액(외) | String | N | 15 |  |
| response | - entra_remn | 예수금잔고 | String | N | 15 |  |
| response | - crnc_cd | 통화코드 | String | N | 3 |  |
| response | - trde_ocr_tp | 거래종류구분 | String | N | 2 | 1:입출금, 2:펀드, 3:ELS, 4:채권, 5:해외채권, 6:외화RP, 7:외화발행어음 |
| response | - trde_kind_nm | 거래종류명 | String | N | 20 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - trde_amt | 거래금액 | String | N | 15 |  |
| response | - trde_agri_tax | 거래및농특세 | String | N | 15 |  |
| response | - rpy_diffa | 상환차금 | String | N | 15 |  |

> ... 외 35개 필드

---

### 일별계좌수익률상세현황요청 (kt00016)

- **API ID**: kt00016
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | fr_dt | 평가시작일 | String | Y | 8 |  |
| request | to_dt | 평가종료일 | String | Y | 8 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | mang_empno | 관리사원번호 | String | N | 8 |  |
| response | mngr_nm | 관리자명 | String | N | 8 |  |
| response | dept_nm | 관리자지점 | String | N | 30 |  |
| response | entr_fr | 예수금_초 | String | N | 30 |  |
| response | entr_to | 예수금_말 | String | N | 12 |  |
| response | scrt_evlt_amt_fr | 유가증권평가금액_초 | String | N | 12 |  |
| response | scrt_evlt_amt_to | 유가증권평가금액_말 | String | N | 12 |  |
| response | ls_grnt_fr | 대주담보금_초 | String | N | 12 |  |
| response | ls_grnt_to | 대주담보금_말 | String | N | 12 |  |
| response | crd_loan_fr | 신용융자금_초 | String | N | 12 |  |
| response | crd_loan_to | 신용융자금_말 | String | N | 12 |  |
| response | ch_uncla_fr | 현금미수금_초 | String | N | 12 |  |
| response | ch_uncla_to | 현금미수금_말 | String | N | 12 |  |
| response | krw_asgna_fr | 원화대용금_초 | String | N | 12 |  |
| response | krw_asgna_to | 원화대용금_말 | String | N | 12 |  |
| response | ls_evlta_fr | 대주평가금_초 | String | N | 12 |  |
| response | ls_evlta_to | 대주평가금_말 | String | N | 12 |  |

> ... 외 22개 필드

---

### 계좌별당일현황요청 (kt00017)

- **API ID**: kt00017
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | d2_entra | D+2추정예수금 | String | N | 12 |  |
| response | crd_int_npay_gold | 신용이자미납금 | String | N | 12 |  |
| response | etc_loana | 기타대여금 | String | N | 12 |  |
| response | gnrl_stk_evlt_amt_d2 | 일반주식평가금액D+2 | String | N | 12 |  |
| response | dpst_grnt_use_amt_d2 | 예탁담보대출금D+2 | String | N | 12 |  |
| response | crd_stk_evlt_amt_d2 | 예탁담보주식평가금액D+2 | String | N | 12 |  |
| response | crd_loan_d2 | 신용융자금D+2 | String | N | 12 |  |
| response | crd_loan_evlta_d2 | 신용융자평가금D+2 | String | N | 12 |  |
| response | crd_ls_grnt_d2 | 신용대주담보금D+2 | String | N | 12 |  |
| response | crd_ls_evlta_d2 | 신용대주평가금D+2 | String | N | 12 |  |
| response | ina_amt | 입금금액 | String | N | 12 |  |
| response | outa | 출금금액 | String | N | 12 |  |
| response | inq_amt | 입고금액 | String | N | 12 |  |
| response | outq_amt | 출고금액 | String | N | 12 |  |
| response | sell_amt | 매도금액 | String | N | 12 |  |
| response | buy_amt | 매수금액 | String | N | 12 |  |
| response | cmsn | 수수료 | String | N | 12 |  |

> ... 외 8개 필드

---

### 계좌평가잔고내역요청 (kt00018)

- **API ID**: kt00018
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | qry_tp | 조회구분 | String | Y | 1 | 1:합산, 2:개별 |
| request | dmst_stex_tp | 국내거래소구분 | String | Y | 6 | KRX:한국거래소,NXT:넥스트트레이드 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | tot_pur_amt | 총매입금액 | String | N | 15 |  |
| response | tot_evlt_amt | 총평가금액 | String | N | 15 |  |
| response | tot_evlt_pl | 총평가손익금액 | String | N | 15 |  |
| response | tot_prft_rt | 총수익률(%) | String | N | 12 |  |
| response | prsm_dpst_aset_amt | 추정예탁자산 | String | N | 15 |  |
| response | tot_loan_amt | 총대출금 | String | N | 15 |  |
| response | tot_crd_loan_amt | 총융자금액 | String | N | 15 |  |
| response | tot_crd_ls_amt | 총대주금액 | String | N | 15 |  |
| response | acnt_evlt_remn_indv_tot | 계좌평가잔고개별합산 | LIST | N |  |  |
| response | - stk_cd | 종목번호 | String | N | 12 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - evltv_prft | 평가손익 | String | N | 15 |  |
| response | - prft_rt | 수익률(%) | String | N | 12 |  |
| response | - pur_pric | 매입가 | String | N | 15 |  |
| response | - pred_close_pric | 전일종가 | String | N | 12 |  |
| response | - rmnd_qty | 보유수량 | String | N | 15 |  |
| response | - trde_able_qty | 매매가능수량 | String | N | 15 |  |

> ... 외 15개 필드

---

### 주식 매수주문 (kt10000)

- **API ID**: kt10000
- **Method**: POST
- **URL**: /api/dostk/ordr
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | dmst_stex_tp | 국내거래소구분 | String | Y | 3 | KRX,NXT,SOR |
| request | stk_cd | 종목코드 | String | Y | 12 |  |
| request | ord_qty | 주문수량 | String | Y | 12 |  |
| request | ord_uv | 주문단가 | String | N | 12 |  |
| request | trde_tp | 매매구분 | String | Y | 2 | 0:보통 , 3:시장가 , 5:조건부지정가 , 81:장마감후시간외 , 61:장시작전시간외, |
| request | cond_uv | 조건단가 | String | N | 12 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | ord_no | 주문번호 | String | N | 7 |  |
| response | dmst_stex_tp | 국내거래소구분 | String | N | 6 |  |

---

### 주식 매도주문 (kt10001)

- **API ID**: kt10001
- **Method**: POST
- **URL**: /api/dostk/ordr
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | dmst_stex_tp | 국내거래소구분 | String | Y | 3 | KRX,NXT,SOR |
| request | stk_cd | 종목코드 | String | Y | 12 |  |
| request | ord_qty | 주문수량 | String | Y | 12 |  |
| request | ord_uv | 주문단가 | String | N | 12 |  |
| request | trde_tp | 매매구분 | String | Y | 2 | 0:보통 , 3:시장가 , 5:조건부지정가 , 81:장마감후시간외 , 61:장시작전시간외, |
| request | cond_uv | 조건단가 | String | N | 12 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | ord_no | 주문번호 | String | N | 7 |  |
| response | dmst_stex_tp | 국내거래소구분 | String | N | 6 |  |

---

### 주식 정정주문 (kt10002)

- **API ID**: kt10002
- **Method**: POST
- **URL**: /api/dostk/ordr
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | dmst_stex_tp | 국내거래소구분 | String | Y | 3 | KRX,NXT,SOR |
| request | orig_ord_no | 원주문번호 | String | Y | 7 |  |
| request | stk_cd | 종목코드 | String | Y | 12 |  |
| request | mdfy_qty | 정정수량 | String | Y | 12 |  |
| request | mdfy_uv | 정정단가 | String | Y | 12 |  |
| request | mdfy_cond_uv | 정정조건단가 | String | N | 12 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | ord_no | 주문번호 | String | N | 7 |  |
| response | base_orig_ord_no | 모주문번호 | String | N | 7 |  |
| response | mdfy_qty | 정정수량 | String | N | 12 |  |
| response | dmst_stex_tp | 국내거래소구분 | String | N | 6 |  |

---

### 주식 취소주문 (kt10003)

- **API ID**: kt10003
- **Method**: POST
- **URL**: /api/dostk/ordr
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | dmst_stex_tp | 국내거래소구분 | String | Y | 3 | KRX,NXT,SOR |
| request | orig_ord_no | 원주문번호 | String | Y | 7 |  |
| request | stk_cd | 종목코드 | String | Y | 12 |  |
| request | cncl_qty | 취소수량 | String | Y | 12 | '0' 입력시 잔량 전부 취소 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | ord_no | 주문번호 | String | N | 7 |  |
| response | base_orig_ord_no | 모주문번호 | String | N | 7 |  |
| response | cncl_qty | 취소수량 | String | N | 12 |  |

---

### 신용 매수주문 (kt10006)

- **API ID**: kt10006
- **Method**: POST
- **URL**: /api/dostk/crdordr
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | dmst_stex_tp | 국내거래소구분 | String | Y | 3 | KRX,NXT,SOR |
| request | stk_cd | 종목코드 | String | Y | 12 |  |
| request | ord_qty | 주문수량 | String | Y | 12 |  |
| request | ord_uv | 주문단가 | String | N | 12 |  |
| request | trde_tp | 매매구분 | String | Y | 2 | 0:보통 , 3:시장가 , 5:조건부지정가 , 81:장마감후시간외 , 61:장시작전시간외, |
| request | cond_uv | 조건단가 | String | N | 12 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | ord_no | 주문번호 | String | N | 7 |  |
| response | dmst_stex_tp | 국내거래소구분 | String | N | 6 |  |

---

### 신용 매도주문 (kt10007)

- **API ID**: kt10007
- **Method**: POST
- **URL**: /api/dostk/crdordr
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | dmst_stex_tp | 국내거래소구분 | String | Y | 3 | KRX,NXT,SOR |
| request | stk_cd | 종목코드 | String | Y | 12 |  |
| request | ord_qty | 주문수량 | String | Y | 12 |  |
| request | ord_uv | 주문단가 | String | N | 12 |  |
| request | trde_tp | 매매구분 | String | Y | 2 | 0:보통 , 3:시장가 , 5:조건부지정가 , 81:장마감후시간외 , 61:장시작전시간외, |
| request | crd_deal_tp | 신용거래구분 | String | Y | 2 | 33:융자 , 99:융자합 |
| request | crd_loan_dt | 대출일 | String | N | 8 | YYYYMMDD(융자일경우필수) |
| request | cond_uv | 조건단가 | String | N | 12 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | ord_no | 주문번호 | String | N | 7 |  |
| response | dmst_stex_tp | 국내거래소구분 | String | N | 6 |  |

---

### 신용 정정주문 (kt10008)

- **API ID**: kt10008
- **Method**: POST
- **URL**: /api/dostk/crdordr
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | dmst_stex_tp | 국내거래소구분 | String | Y | 3 | KRX,NXT,SOR |
| request | orig_ord_no | 원주문번호 | String | Y | 7 |  |
| request | stk_cd | 종목코드 | String | Y | 12 |  |
| request | mdfy_qty | 정정수량 | String | Y | 12 |  |
| request | mdfy_uv | 정정단가 | String | Y | 12 |  |
| request | mdfy_cond_uv | 정정조건단가 | String | N | 12 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | ord_no | 주문번호 | String | N | 7 |  |
| response | base_orig_ord_no | 모주문번호 | String | N | 7 |  |
| response | mdfy_qty | 정정수량 | String | N | 12 |  |
| response | dmst_stex_tp | 국내거래소구분 | String | N | 6 |  |

---

### 신용 취소주문 (kt10009)

- **API ID**: kt10009
- **Method**: POST
- **URL**: /api/dostk/crdordr
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | dmst_stex_tp | 국내거래소구분 | String | Y | 3 | KRX,NXT,SOR |
| request | orig_ord_no | 원주문번호 | String | Y | 7 |  |
| request | stk_cd | 종목코드 | String | Y | 12 |  |
| request | cncl_qty | 취소수량 | String | Y | 12 | '0' 입력시 잔량 전부 취소 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | ord_no | 주문번호 | String | N | 7 |  |
| response | base_orig_ord_no | 모주문번호 | String | N | 7 |  |
| response | cncl_qty | 취소수량 | String | N | 12 |  |

---

### 신용융자 가능종목요청 (kt20016)

- **API ID**: kt20016
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | crd_stk_grde_tp | 신용종목등급구분 | String | N | 1 | %:전체, A:A군, B:B군, C:C군, D:D군, E:E군 |
| request | mrkt_deal_tp | 시장거래구분 | String | Y | 1 | %:전체, 1:코스피, 0:코스닥 |
| request | stk_cd | 종목코드 | String | N | 12 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | crd_loan_able | 신용융자가능여부 | String | N | 40 |  |
| response | crd_loan_pos_stk | 신용융자가능종목 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 12 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - crd_assr_rt | 신용보증금율 | String | N | 4 |  |
| response | - repl_pric | 대용가 | String | N | 12 |  |
| response | - pred_close_pric | 전일종가 | String | N | 12 |  |
| response | - crd_limit_over_yn | 신용한도초과여부 | String | N | 1 |  |
| response | - crd_limit_over_txt | 신용한도초과 | String | N | 40 | N:공란,Y:회사한도 초과 |

---

### 신용융자 가능문의 (kt20017)

- **API ID**: kt20017
- **Method**: POST
- **URL**: /api/dostk/stkinfo
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 12 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | crd_alow_yn | 신용가능여부 | String | N | 40 |  |

---

### 금현물 매수주문 (kt50000)

- **API ID**: kt50000
- **Method**: POST
- **URL**: /api/dostk/ordr
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 12 | M04020000 금 99.99_1kg, M04020100 미니금 99.99_100g |
| request | ord_qty | 주문수량 | String | Y | 12 |  |
| request | ord_uv | 주문단가 | String | N | 12 |  |
| request | trde_tp | 매매구분 | String | Y | 2 | 00:보통, 10:보통(IOC), 20:보통(FOK) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | ord_no | 주문번호 | String | N | 7 |  |

---

### 금현물 매도주문 (kt50001)

- **API ID**: kt50001
- **Method**: POST
- **URL**: /api/dostk/ordr
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 12 | M04020000 금 99.99_1kg, M04020100 미니금 99.99_100g |
| request | ord_qty | 주문수량 | String | Y | 12 |  |
| request | ord_uv | 주문단가 | String | N | 12 |  |
| request | trde_tp | 매매구분 | String | Y | 2 | 00:보통, 10:보통(IOC), 20:보통(FOK) |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | ord_no | 주문번호 | String | N | 7 |  |

---

### 금현물 정정주문 (kt50002)

- **API ID**: kt50002
- **Method**: POST
- **URL**: /api/dostk/ordr
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | stk_cd | 종목코드 | String | Y | 12 | M04020000 금 99.99_1kg, M04020100 미니금 99.99_100g |
| request | orig_ord_no | 원주문번호 | String | Y | 7 |  |
| request | mdfy_qty | 정정수량 | String | Y | 12 |  |
| request | mdfy_uv | 정정단가 | String | Y | 12 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | ord_no | 주문번호 | String | N | 7 |  |
| response | base_orig_ord_no | 모주문번호 | String | N | 7 |  |
| response | mdfy_qty | 정정수량 | String | N | 12 |  |

---

### 금현물 취소주문 (kt50003)

- **API ID**: kt50003
- **Method**: POST
- **URL**: /api/dostk/ordr
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | orig_ord_no | 원주문번호 | String | Y | 7 |  |
| request | stk_cd | 종목코드 | String | Y | 12 | M04020000 금 99.99_1kg, M04020100 미니금 99.99_100g |
| request | cncl_qty | 취소수량 | String | Y | 12 | '0' 입력시 잔량 전부 취소 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | ord_no | 주문번호 | String | N | 7 |  |
| response | base_orig_ord_no | 모주문번호 | String | N | 7 |  |
| response | cncl_qty | 취소수량 | String | N | 12 |  |

---

### 금현물 잔고확인 (kt50020)

- **API ID**: kt50020
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | tot_entr | 예수금 | String | N | 12 |  |
| response | net_entr | 추정예수금 | String | N | 12 |  |
| response | tot_est_amt | 잔고평가액 | String | N | 12 |  |
| response | net_amt | 예탁자산평가액 | String | N | 12 |  |
| response | tot_book_amt2 | 총매입금액 | String | N | 12 |  |
| response | tot_dep_amt | 추정예탁자산 | String | N | 12 |  |
| response | paym_alowa | 출금가능금액 | String | N | 12 |  |
| response | pl_amt | 실현손익 | String | N | 12 |  |
| response | gold_acnt_evlt_prst | 금현물계좌평가현황 | LIST | N |  |  |
| response | - stk_cd | 종목코드 | String | N | 30 |  |
| response | - stk_nm | 종목명 | String | N | 12 |  |
| response | - real_qty | 보유수량 | String | N | 12 |  |
| response | - avg_prc | 평균단가 | String | N | 12 |  |
| response | - cur_prc | 현재가 | String | N | 12 |  |
| response | - est_amt | 평가금액 | String | N | 12 |  |
| response | - est_lspft | 손익금액 | String | N | 12 |  |
| response | - est_ratio | 손익율 | String | N | 12 |  |

> ... 외 8개 필드

---

### 금현물 예수금 (kt50021)

- **API ID**: kt50021
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | entra | 예수금 | String | N | 15 |  |
| response | profa_ch | 증거금현금 | String | N | 15 |  |
| response | chck_ina_amt | 수표입금액 | String | N | 15 |  |
| response | etc_loan | 기타대여금 | String | N | 15 |  |
| response | etc_loan_dlfe | 기타대여금연체료 | String | N | 15 |  |
| response | etc_loan_tot | 기타대여금합계 | String | N | 15 |  |
| response | prsm_entra | 추정예수금 | String | N | 15 |  |
| response | buy_exct_amt | 매수정산금 | String | N | 15 |  |
| response | sell_exct_amt | 매도정산금 | String | N | 15 |  |
| response | sell_buy_exct_amt | 매도매수정산금 | String | N | 15 |  |
| response | dly_amt | 미수변제소요금 | String | N | 15 |  |
| response | prsm_pymn_alow_amt | 추정출금가능금액 | String | N | 15 |  |
| response | pymn_alow_amt | 출금가능금액 | String | N | 15 |  |
| response | ord_alow_amt | 주문가능금액 | String | N | 15 |  |

---

### 금현물 주문체결전체조회 (kt50030)

- **API ID**: kt50030
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | ord_dt | 주문일자 | String | Y | 8 |  |
| request | qry_tp | 조회구분 | String | N | 1 | 1: 주문순, 2: 역순 |
| request | mrkt_deal_tp | 시장구분 | String | Y | 1 |  |
| request | stk_bond_tp | 주식채권구분 | String | Y | 1 | 0:전체, 1:주식, 2:채권 |
| request | slby_tp | 매도수구분 | String | Y | 1 | 0:전체, 1:매도, 2:매수 |
| request | stk_cd | 종목코드 | String | N | 12 |  |
| request | fr_ord_no | 시작주문번호 | String | N | 7 |  |
| request | dmst_stex_tp | 국내거래소구분 | String | N | 6 | %:(전체), KRX, NXT, SOR |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | acnt_ord_cntr_prst | 계좌별주문체결현황 | LIST | N |  |  |
| response | - stk_bond_tp | 주식채권구분 | String | N | 1 |  |
| response | - ord_no | 주문번호 | String | N | 7 |  |
| response | - stk_cd | 상품코드 | String | N | 12 |  |
| response | - trde_tp | 매매구분 | String | N | 12 |  |
| response | - io_tp_nm | 주문유형구분 | String | N | 20 |  |
| response | - ord_qty | 주문수량 | String | N | 10 |  |
| response | - ord_uv | 주문단가 | String | N | 10 |  |
| response | - cnfm_qty | 확인수량 | String | N | 10 |  |
| response | - data_send_end_tp | 접수구분 | String | N | 12 |  |
| response | - mrkt_deal_tp | 시장구분 | String | N | 1 |  |
| response | - rsrv_tp | 예약/반대여부 | String | N | 4 |  |
| response | - orig_ord_no | 원주문번호 | String | N | 7 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - dcd_tp_nm | 결제구분 | String | N | 4 |  |
| response | - crd_deal_tp | 신용거래구분 | String | N | 20 |  |
| response | - cntr_qty | 체결수량 | String | N | 10 |  |

> ... 외 6개 필드

---

### 금현물 주문체결조회 (kt50031)

- **API ID**: kt50031
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | ord_dt | 주문일자 | String | N | 8 | YYYYMMDD |
| request | qry_tp | 조회구분 | String | Y | 1 | 1:주문순, 2:역순, 3:미체결, 4:체결내역만 |
| request | stk_bond_tp | 주식채권구분 | String | Y | 1 | 0:전체, 1:주식, 2:채권 |
| request | sell_tp | 매도수구분 | String | Y | 1 | 0:전체, 1:매도, 2:매수 |
| request | stk_cd | 종목코드 | String | N | 12 | 공백허용 (공백일때 전체종목) |
| request | fr_ord_no | 시작주문번호 | String | N | 7 | 공백허용 (공백일때 전체주문) |
| request | dmst_stex_tp | 국내거래소구분 | String | Y | 6 | %:(전체),KRX:한국거래소,NXT:넥스트트레이드,SOR:최선주문집행 |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | acnt_ord_cntr_prps_dtl | 계좌별주문체결내역상세 | LIST | N |  |  |
| response | - ord_no | 주문번호 | String | N | 7 |  |
| response | - stk_cd | 종목번호 | String | N | 12 |  |
| response | - trde_tp | 매매구분 | String | N | 20 |  |
| response | - crd_tp | 신용구분 | String | N | 20 |  |
| response | - ord_qty | 주문수량 | String | N | 10 |  |
| response | - ord_uv | 주문단가 | String | N | 10 |  |
| response | - cnfm_qty | 확인수량 | String | N | 10 |  |
| response | - acpt_tp | 접수구분 | String | N | 20 |  |
| response | - rsrv_tp | 반대여부 | String | N | 20 |  |
| response | - ord_tm | 주문시간 | String | N | 8 |  |
| response | - ori_ord | 원주문 | String | N | 7 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - io_tp_nm | 주문구분 | String | N | 20 |  |
| response | - loan_dt | 대출일 | String | N | 8 |  |
| response | - cntr_qty | 체결수량 | String | N | 10 |  |
| response | - cntr_uv | 체결단가 | String | N | 10 |  |

> ... 외 6개 필드

---

### 금현물 거래내역조회 (kt50032)

- **API ID**: kt50032
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | strt_dt | 시작일자 | String | N | 8 |  |
| request | end_dt | 종료일자 | String | N | 8 |  |
| request | tp | 구분 | String | N | 1 | 0:전체, 1:입출금, 2:출고, 3:매매, 4:매수, 5:매도, 6:입금, 7:출금 |
| request | stk_cd | 종목코드 | String | N | 12 |  |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | acnt_print | 계좌번호 | String | N | 62 | 계좌번호 출력용 |
| response | gold_trde_hist | 금현물거래내역 | LIST | N |  |  |
| response | - deal_dt | 거래일자 | String | N |  |  |
| response | - deal_no | 거래번호 | String | N |  |  |
| response | - rmrk_nm | 적요명 | String | N |  |  |
| response | - deal_qty | 거래수량 | String | N |  |  |
| response | - gold_spot_vat | 금현물부가가치세 | String | N |  |  |
| response | - exct_amt | 정산금액 | String | N |  |  |
| response | - dly_sum | 연체합 | String | N |  |  |
| response | - entra_remn | 예수금잔고 | String | N |  |  |
| response | - mdia_nm | 메체구분명 | String | N |  |  |
| response | - orig_deal_no | 원거래번호 | String | N |  |  |
| response | - stk_nm | 종목명 | String | N |  |  |
| response | - uv_exrt | 거래단가 | String | N |  |  |
| response | - cmsn | 수수료 | String | N |  |  |
| response | - uncl_ocr | 미수(원/g) | String | N |  |  |
| response | - rpym_sum | 변제합 | String | N |  |  |

> ... 외 9개 필드

---

### 금현물 미체결조회 (kt50075)

- **API ID**: kt50075
- **Method**: POST
- **URL**: /api/dostk/acnt
- **운영 도메인**: https://api.kiwoom.com
- **모의투자 도메인**: https://mockapi.kiwoom.com(KRX만 지원가능)

#### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| request | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출 
 예) Bearer Egicyx... |
| request | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 con |
| request | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 nex |
| Body | ord_dt | 주문일자 | String | Y | 8 |  |
| request | qry_tp | 조회구분 | String | N | 1 | 1: 주문순, 2: 역순 |
| request | mrkt_deal_tp | 시장구분 | String | Y | 1 |  |
| request | stk_bond_tp | 주식채권구분 | String | Y | 1 | 0:전체, 1:주식, 2:채권 |
| request | sell_tp | 매도수구분 | String | Y | 1 | 0:전체, 1:매도, 2:매수 |
| request | stk_cd | 종목코드 | String | N | 12 |  |
| request | fr_ord_no | 시작주문번호 | String | N | 7 |  |
| request | dmst_stex_tp | 국내거래소구분 | String | N | 6 | %:(전체), KRX, NXT, SOR |

#### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
|------|---------|--------|------|----------|--------|-------------|
| Header | api-id | TR명 | String | Y | 10 |  |
| response | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| response | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | acnt_ord_oso_prst | 계좌별주문미체결현황 | LIST | N |  |  |
| response | - stk_bond_tp | 주식채권구분 | String | N | 1 |  |
| response | - ord_no | 주문번호 | String | N | 7 |  |
| response | - stk_cd | 상품코드 | String | N | 12 |  |
| response | - trde_tp | 매매구분 | String | N | 12 |  |
| response | - io_tp_nm | 주문유형구분 | String | N | 20 |  |
| response | - ord_qty | 주문수량 | String | N | 10 |  |
| response | - ord_uv | 주문단가 | String | N | 10 |  |
| response | - cnfm_qty | 확인수량 | String | N | 10 |  |
| response | - data_send_end_tp | 접수구분 | String | N | 12 |  |
| response | - mrkt_deal_tp | 시장구분 | String | N | 1 |  |
| response | - rsrv_tp | 예약/반대여부 | String | N | 4 |  |
| response | - orig_ord_no | 원주문번호 | String | N | 7 |  |
| response | - stk_nm | 종목명 | String | N | 40 |  |
| response | - dcd_tp_nm | 결제구분 | String | N | 4 |  |
| response | - crd_deal_tp | 신용거래구분 | String | N | 20 |  |
| response | - cntr_qty | 체결수량 | String | N | 10 |  |

> ... 외 6개 필드

---
