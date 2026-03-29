# CLAUDE.md

## 코드 관리 규칙

- 각 파일은 **500줄 이하**로 유지한다
- 500줄을 초과할 경우 기능 단위로 파일을 분리한다
- 탭 모듈은 `tabs/` 디렉토리에 `tab_*.py` 패턴으로 관리한다
- 공통 유틸리티는 `utils.py`에 모아둔다
- 브로커별 로직은 `broker_*.py`로 분리한다

## 프로젝트 구조

- `app.py` — Streamlit 메인 대시보드 (탭 구성, 사이드바)
- `broker_upbit.py` — 업비트 브로커
- `broker_kis.py` — 한국투자증권 브로커
- `strategy.py` — MA 전략 모듈 (업비트, 로컬 Streamlit용)
- `strategy_engine.py` — VM 자동매매 엔진 (SMA/Donchian 전환감지, 스케줄 실행)
- `grid_engine.py` — 그리드 매매 엔진 (업비트, 주문 배치/체결/카운터 주문)
- `strategy_laa.py` — LAA 자산배분 전략 (한투)
- `utils.py` — 공통 헬퍼 함수
- `tabs/` — 각 탭 UI 모듈
  - `tab_monitor.py` — LIVE TRADING (실시간 모니터링)
  - `tab_grid_live.py` — 그리드 라이브 매매 (업비트, 실시간 주문)
  - `tab_backtest.py` — 그리드 매매 백테스트 (업비트)
  - `tab_laa_live.py` — LAA 라이브 리밸런싱 (한투)
  - `tab_laa_backtest.py` — LAA 백테스트 (한투)
  - `tab_order.py` — 수동주문
  - `tab_reserve.py` — 예약주문
  - `tab_history.py` — 거래내역
  - `tab_connection.py` — 연결상태
  - `tab_log.py` — 로그
  - `tab_status.py` — 작업현황

## 실행 아키텍처

1. **모든 거래·조회·매매는 VM에서만 동작**한다
   - 잔고 조회, 시세 조회, 주문 실행 등 모든 업비트/한투 API 호출은 반드시 VM에서 수행
   - 업비트 API 키의 허용 IP가 VM IP(`34.123.196.34`)로 설정되어 있으므로 로컬 PC에서는 API 호출 불가

2. **로컬 PC의 Streamlit은 화면 표시용**이다
   - 로컬 PC에서 직접 주문하거나 API를 호출하지 않는다
   - 로컬 Streamlit은 VM에서 가져온 결과 데이터를 화면에 표시하는 역할만 수행

3. **작업/매매 요청 흐름**
   ```
   로컬 Streamlit에서 작업 또는 매매 요청
     → VM으로 전달
       → VM에서 주문 실행
         → 결과를 VM에 기록
           → 기록을 로컬 PC로 가져와서 Streamlit에 표시
   ```

## VM 배포

- GCP 프로젝트: `quanters-489305`
- VM: `my-free-vm` (us-central1-a, e2-micro)
- VM IP: `34.123.196.34`
- gcloud 경로: `C:\Users\basra\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd`
- PowerShell로 실행: `powershell.exe -NoProfile -Command '& "경로\gcloud.cmd" ...'`

## API 키 관리

- `.env` 파일의 업비트 키는 VM 전용 (허용 IP: `34.123.196.34`)
- 로컬 PC에서 API 테스트 시 `no_authorization_ip` 에러는 정상 (VM에서만 동작)
- API 키 변경 시 업비트 Open API 관리 페이지에서 허용 IP 확인 필수

## 작업 기록 규칙

- **30분마다** 작업 내역을 아래 파일에 업데이트한다
  - `HISTORY.md` — 작업 히스토리 (무엇을 했는지, 생성/수정한 파일, 배포 내역)
  - `ERROR_FIX_HISTORY.md` — 오류 발생 및 수정 내역 (에러 메시지, 원인, 해결법)
- 새로운 오류가 발생하면 `ERROR_FIX_HISTORY.md`에 즉시 기록한다 (ERR-NNN 형식)
- 기존 오류와 동일한 에러가 재발하면 해당 항목에 재발 이력을 추가한다
- 작업 완료 시점에도 반드시 두 파일을 최신 상태로 업데이트한다
