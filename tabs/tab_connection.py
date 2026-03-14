"""
Tab: Connection Test
Verifies live communication with broker API.
Tests: balance, current price, OHLCV, individual holding, pending orders, completed orders.
"""
import time
import streamlit as st
from tabs.tab_log import add_log
from utils import get_ticker_display, is_stock


def _test(label: str, fn):
    """Run fn(), measure latency, return (ok, latency_ms, result_or_error)."""
    t0 = time.time()
    try:
        result = fn()
        ms = int((time.time() - t0) * 1000)
        return True, ms, result
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        return False, ms, str(e)


def render(broker):
    broker_name = getattr(broker, "name", "브로커")
    acct = getattr(broker, "account_number", "")
    acct_display = f" (계좌: {acct})" if acct else ""

    st.subheader(f"🔌 {broker_name} 연결 상태 확인{acct_display}")
    st.caption("버튼을 눌러 각 API 엔드포인트의 응답 상태와 실제 데이터를 확인합니다.")

    active_tickers = st.session_state.get("TICKERS", ["KRW-BTC"])
    test_tickers = active_tickers[:3]
    ticker = st.selectbox("테스트 종목", test_tickers, key="conn_ticker",
                          format_func=get_ticker_display)

    asset_label = "주식" if is_stock(ticker) else "코인"

    if st.button("🔄 연결 테스트 실행", type="primary"):
        results = []

        # 1. 잔고 조회 (전체)
        ok, ms, data = _test("잔고 조회", lambda: broker.get_balances())
        results.append(("💰 잔고 조회 (get_balances)", ok, ms, data if ok else None, data if not ok else None))
        add_log(f"잔고 조회 {'성공' if ok else '실패'} ({ms}ms)", "INFO" if ok else "ERROR")

        # 2. 보유자산 조회 (특정 종목)
        ok, ms, data = _test("보유자산 조회", lambda: broker.get_balance(ticker))
        display_val = f"{data:,.0f}주" if is_stock(ticker) and ok else (f"{data:.8f}" if ok else data)
        results.append((f"📦 보유자산 조회 ({get_ticker_display(ticker)})", ok, ms, display_val if ok else None, data if not ok else None))
        add_log(f"보유자산 조회 {'성공' if ok else '실패'} ({ms}ms)", "INFO" if ok else "ERROR")

        # 3. 현재가 조회
        ok, ms, data = _test("현재가 조회", lambda: broker.get_current_price(ticker))
        results.append(("📈 현재가 조회 (get_current_price)", ok, ms, f"{data:,.0f}원" if ok else None, data if not ok else None))
        add_log(f"현재가 조회 {'성공' if ok else '실패'} ({ms}ms)", "INFO" if ok else "ERROR")

        # 4. OHLCV 일봉
        ok, ms, data = _test("일봉 데이터", lambda: broker.get_ohlcv(ticker, interval="day", count=3))
        results.append(("📊 일봉 OHLCV (get_ohlcv day)", ok, ms, data if ok else None, data if not ok else None))
        add_log(f"일봉 OHLCV {'성공' if ok else '실패'} ({ms}ms)", "INFO" if ok else "ERROR")

        # 5. 미체결 주문 조회
        ok, ms, data = _test("미체결 주문", lambda: broker.get_order(ticker, state="wait"))
        count_str = f"{len(data)}건" if ok and isinstance(data, list) else "—"
        results.append(("📋 미체결 주문 조회 (state=wait)", ok, ms, f"{count_str} | {data}" if ok else None, data if not ok else None))
        add_log(f"미체결 조회 {'성공' if ok else '실패'} ({ms}ms)", "INFO" if ok else "ERROR")

        # 6. 체결 내역 조회
        ok, ms, data = _test("체결 내역", lambda: broker.get_order(ticker, state="done"))
        count_str = f"{len(data)}건" if ok and isinstance(data, list) else "—"
        results.append(("📂 체결 내역 조회 (state=done)", ok, ms, f"{count_str}" if ok else None, data if not ok else None))
        add_log(f"체결내역 조회 {'성공' if ok else '실패'} ({ms}ms)", "INFO" if ok else "ERROR")

        st.divider()

        passed = 0
        failed = 0
        for label, ok, ms, success_data, err_msg in results:
            status_icon = "✅" if ok else "❌"
            if ok:
                passed += 1
            else:
                failed += 1
            col1, col2 = st.columns([3, 1])
            col1.markdown(f"{status_icon} **{label}**")
            col2.markdown(f"`{ms} ms`")

            if ok and success_data is not None:
                with st.expander("응답 데이터 보기"):
                    st.write(success_data)
            elif err_msg:
                st.error(f"오류: {err_msg}")

        st.divider()
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("전체 테스트", f"{len(results)}건")
        mc2.metric("성공", f"{passed}건")
        mc3.metric("실패", f"{failed}건")

        if failed == 0:
            st.success(f"🎉 모든 API 연결이 정상입니다! ({broker_name}{acct_display})")
        else:
            st.error(f"⚠️ {failed}건의 API 연결에 문제가 있습니다. 로그 탭을 확인하세요.")
