"""
Tab: Reserve Orders
Schedule orders by time or strategy condition.
Execution time is fully user-configurable: date + hour + minute.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
from streamlit_autorefresh import st_autorefresh
from tabs.tab_log import add_log
from utils import get_ticker_display, is_stock, round_price_upbit

TICKERS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-ADA", "KRW-DOGE"]
STRATEGIES = ["시간 지정 실행", "목표가 돌파 시 매수", "이평선 상향 돌파 시 매수", "리밸런싱 (비율)"]

def _init():
    if "reserve_orders" not in st.session_state:
        st.session_state.reserve_orders = []

def _execute_order(broker, order: dict) -> tuple[bool, str]:
    """
    Execute a single reserve order via pyupbit API.
    Returns (success: bool, message: str)
    """
    ticker      = order["ticker"]
    side        = order["side"]
    order_type  = order.get("order_type", "시장가")
    limit_price_raw = float(order.get("limit_price") or 0)
    limit_price = round_price_upbit(limit_price_raw) if limit_price_raw > 0 else 0
    if limit_price_raw > 0 and limit_price != limit_price_raw:
        add_log(f"[호가보정] {ticker} 가격 {limit_price_raw:,.0f}원 → {limit_price:,.0f}원 (호가 단위 자동 보정)", "INFO")
    amount      = float(order["amount"])
    try:
        result = None
        if side == "매수":
            if order_type == "지정가" and limit_price > 0:
                qty    = amount / limit_price
                result = broker.buy_limit_order(ticker, limit_price, qty)
                label  = f"✅ 지정가매수 {ticker} {limit_price:,.0f}원×{qty:.6f}"
            else:
                result = broker.buy_market_order(ticker, amount)
                label  = f"✅ 시장가매수 {ticker} {amount:,.0f}원"
        else:  # 매도
            if order_type == "지정가" and limit_price > 0:
                result = broker.sell_limit_order(ticker, limit_price, amount)
                label  = f"✅ 지정가매도 {ticker} {limit_price:,.0f}원×{amount:.6f}"
            else:
                result = broker.sell_market_order(ticker, amount)
                label  = f"✅ 시장가매도 {ticker} {amount:.6f}"

        # 전체 API 응답 로깅
        add_log(f"[예약주문 API응답] {side} {ticker}: {result}", "INFO")

        if result is None:
            return False, f"❌ 주문 거부 (잔고 부족 또는 최소금액 미달) | {side} {ticker} {order_type}"
        # API가 에러 dict를 반환한 경우
        if isinstance(result, dict) and "error" in result:
            err = result["error"]
            err_msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            return False, f"❌ API 오류: {err_msg} | {side} {ticker}"
        uuid = result.get("uuid", "") if isinstance(result, dict) else ""
        return True, f"{label} | uuid={uuid}" if uuid else label
    except Exception as e:
        return False, f"❌ 실행 오류: {type(e).__name__}: {e}"


def check_and_execute(broker):
    """
    Scan all active 'wait' orders whose exec_at <= now and execute them.
    Called from app.py on every rerun (not just when reserve tab is visible).
    Only handles '시간 지정 실행' strategy for now.
    """
    if "reserve_orders" not in st.session_state:
        return False
    now = datetime.now()
    changed = False
    for i, order in enumerate(st.session_state.reserve_orders):
        if not order.get("active") or order.get("status") != "대기중":
            continue
        exec_at_str = order.get("exec_at", "")
        if not exec_at_str:
            continue
        try:
            exec_dt = datetime.strptime(exec_at_str, "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        # Fire if execution time has arrived
        if now >= exec_dt:
            strategy = order.get("strategy", "")
            add_log(f"[예약체크] #{order['id']} 시간 도래 (예약: {exec_at_str}, 현재: {now.strftime('%H:%M:%S')}, 전략: {strategy})", "INFO")
            if strategy == "시간 지정 실행":
                success, msg = _execute_order(broker, order)
                st.session_state.reserve_orders[i]["status"] = "완료" if success else "실패"
                st.session_state.reserve_orders[i]["result"]  = msg
                level = "ORDER" if success else "ERROR"
                add_log(f"[예약실행] #{order['id']} {msg}", level)
                changed = True
            else:
                add_log(f"[예약체크] #{order['id']} 전략 '{strategy}'은(는) 아직 미구현", "WARNING")
    return changed


def _datetime_picker(key_prefix: str):
    """
    Custom date+time picker using st.date_input + two number_inputs (hour, minute).
    Returns a datetime object.
    """
    now = datetime.now()
    col_d, col_h, col_m = st.columns([3, 1, 1])
    with col_d:
        exec_date = st.date_input(
            "실행 날짜",
            value=now.date(),
            min_value=now.date(),
            key=f"{key_prefix}_date",
        )
    with col_h:
        exec_hour = st.number_input(
            "시",
            min_value=0, max_value=23,
            value=now.hour,
            step=1,
            key=f"{key_prefix}_hour",
        )
    with col_m:
        exec_min = st.number_input(
            "분",
            min_value=0, max_value=59,
            value=now.minute,
            step=5,
            key=f"{key_prefix}_min",
        )
    exec_dt = datetime.combine(exec_date, time(int(exec_hour), int(exec_min)))
    st.caption(f"⏰ 실행 예정: **{exec_dt.strftime('%Y-%m-%d %H:%M')}**")
    return exec_dt


def render(broker):
    _init()
    
    # 30초마다 자동 갱신
    st_autorefresh(interval=30_000, key="reserve_autorefresh")

    # 시간에 도달한 예약 주문 실행 (fragment rerun에서도 동작)
    if check_and_execute(broker):
        st.rerun(scope="fragment")

    st.subheader("📅 예약 주문")
    st.caption("시간 또는 전략 조건에 따라 자동으로 실행될 주문을 예약합니다.")

    tab_add, tab_list = st.tabs(["➕ 예약 추가", "📋 예약 목록"])

    # ── 예약 추가 폼 ──────────────────────────────────────────────────
    with tab_add:
        active_tickers = st.session_state.get("TICKERS", TICKERS)
        c1, c2 = st.columns(2)
        with c1:
            res_ticker   = st.selectbox("종목", active_tickers, key="res_ticker",
                                        format_func=get_ticker_display)
            _is_stock = is_stock(res_ticker)
            res_side     = st.radio("방향", ["매수", "매도"], horizontal=True, key="res_side")
            res_order_type = st.radio("주문 유형", ["시장가", "지정가"], horizontal=True, key="res_order_type")
            res_strategy = st.selectbox("전략 유형", STRATEGIES, key="res_strategy")

            # 지정가 선택 시 가격 입력
            if res_order_type == "지정가":
                try:
                    curr = broker.get_current_price(res_ticker) or 0
                except Exception:
                    curr = 0
                default_price = int(round_price_upbit(curr * 0.98)) if curr else 100_000
                res_limit_price_raw = st.number_input(
                    "지정 가격 (KRW)" if _is_stock else "지정 가격 (KRW/코인)",
                    min_value=1,
                    value=default_price,
                    step=1000,
                    key="res_limit_price",
                    help="지정가 매수: 현재가보다 낮게 / 매도: 현재가보다 높게 설정",
                )
                res_limit_price = int(round_price_upbit(res_limit_price_raw)) if res_limit_price_raw > 0 else 0
                if res_limit_price != res_limit_price_raw:
                    st.caption(f"호가 단위 보정: {res_limit_price_raw:,.0f}원 → **{res_limit_price:,.0f}원**")
                if curr:
                    st.caption(f"현재가: {curr:,.0f}원 | 설정가: {res_limit_price:,.0f}원 ({(res_limit_price/curr-1)*100:+.2f}%)")
            else:
                res_limit_price = 0

            if res_side == "매수":
                res_amount = st.number_input(
                    "주문 금액 (KRW)", min_value=5000, value=50000, step=1000, key="res_amount"
                )
                if res_order_type == "지정가" and res_limit_price > 0:
                    auto_qty = res_amount / res_limit_price
                    st.caption(f"환산 수량: **{auto_qty:.8f}** ({res_amount:,.0f}원 ÷ {res_limit_price:,.0f}원)")
            else:
                if _is_stock:
                    res_amount = st.number_input(
                        "주문 수량 (주)", min_value=0, value=1,
                        step=1, key="res_amount_coin"
                    )
                else:
                    res_amount = st.number_input(
                        "주문 수량 (코인)", min_value=0.0, value=0.001,
                        step=0.0001, format="%.8f", key="res_amount_coin"
                    )
                if res_order_type == "지정가" and res_limit_price > 0:
                    total_krw = float(res_amount) * res_limit_price
                    st.caption(f"환산 금액: **{total_krw:,.0f}원** ({float(res_amount):.8f} × {res_limit_price:,.0f}원)")

        with c2:
            # ── 전략별 조건 입력 ────────────────────────────────────
            if res_strategy == "시간 지정 실행":
                exec_dt  = _datetime_picker("res_ts")
                res_note = f"예약 실행: {exec_dt.strftime('%Y-%m-%d %H:%M')}"

            elif res_strategy == "목표가 돌파 시 매수":
                try:
                    curr = broker.get_current_price(res_ticker) or 100_000_000
                except Exception:
                    curr = 100_000_000
                res_target = st.number_input(
                    "목표가 (KRW)", min_value=1, value=int(curr * 1.05),
                    step=1000, key="res_target",
                    help="현재가보다 높게 설정하면 돌파 매수"
                )
                st.caption(f"현재가: **{curr:,.0f}원** | 목표: **{res_target:,.0f}원**")
                # 만료 시각 선택 (선택적)
                st.markdown("**조건 만료 시각** (이 시각까지 미달성시 취소)")
                exec_dt  = _datetime_picker("res_tgt_exp")
                res_note = f"목표가 {res_target:,}원 돌파 시 (만료: {exec_dt.strftime('%Y-%m-%d %H:%M')})"

            elif res_strategy == "이평선 상향 돌파 시 매수":
                res_ma = st.number_input(
                    "이동평균 기간 (일)", min_value=1, value=20, key="res_ma"
                )
                st.markdown("**조건 확인 시각**")
                exec_dt  = _datetime_picker("res_ma_ts")
                res_note = f"MA{res_ma} 상향 돌파 시 (확인: {exec_dt.strftime('%Y-%m-%d %H:%M')})"

            elif res_strategy == "리밸런싱 (비율)":
                res_ratio = st.slider(
                    "코인 비율 (%)", 0, 100, 50, key="res_ratio",
                    help="총 자산 대비 코인 보유 비율 목표"
                )
                st.markdown("**리밸런싱 실행 시각**")
                exec_dt  = _datetime_picker("res_reb_ts")
                res_note = f"코인 {res_ratio}% 비율 유지 (실행: {exec_dt.strftime('%Y-%m-%d %H:%M')})"

            res_active = st.toggle("활성화", value=True, key="res_active")

        st.divider()
        if st.button("📌 예약 등록", type="primary", key="res_submit"):
            order = {
                "id":          len(st.session_state.reserve_orders) + 1,
                "created":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "exec_at":     exec_dt.strftime("%Y-%m-%d %H:%M"),
                "ticker":      res_ticker,
                "side":        res_side,
                "order_type":  res_order_type,
                "limit_price": res_limit_price,
                "strategy":    res_strategy,
                "amount":      res_amount,
                "note":        res_note,
                "active":      res_active,
                "status":      "대기중",
            }
            type_label = f"지정가({res_limit_price:,}원)" if res_order_type == "지정가" else "시장가"
            st.session_state.reserve_orders.append(order)
            add_log(f"[예약등록] {res_ticker} {res_side} {type_label} / {res_note}", "INFO")
            st.success(f"✅ 예약 주문 등록: {res_ticker} {res_side} [{type_label}] — {exec_dt.strftime('%Y-%m-%d %H:%M')}")

    # ── 예약 목록 ──────────────────────────────────────────────────────
    with tab_list:
        orders = st.session_state.reserve_orders
        if not orders:
            st.info("등록된 예약 주문이 없습니다.")
        else:
            if st.button("🗑 전체 삭제", key="res_clear_all"):
                st.session_state.reserve_orders = []
                add_log("[예약주문] 전체 삭제", "INFO")
                st.rerun(scope="fragment")

            status_icons = {"대기중": "⏳", "완료": "✅", "취소": "❌", "실패": "🔴"}

            for o in orders:
                oid = o["id"]
                active_icon = "🟢" if o["active"] else "⚫"
                s_icon = status_icons.get(o["status"], "")
                with st.expander(
                    f"{active_icon} [{oid}] {get_ticker_display(o['ticker'])} {o['side']}"
                    f" ⏰{o.get('exec_at','?')} — {s_icon} {o['status']}"
                ):
                    # 실행 결과 배너
                    result_msg = o.get("result", "")
                    if o["status"] == "실패" and result_msg:
                        st.error(f"실행 결과: {result_msg}")
                    elif o["status"] == "완료" and result_msg:
                        st.success(f"실행 결과: {result_msg}")

                    col_i1, col_i2 = st.columns(2)
                    with col_i1:
                        st.write(f"- **종목**: {get_ticker_display(o['ticker'])}")
                        st.write(f"- **방향**: {o['side']}")
                        order_type_str = o.get('order_type', '시장가')
                        limit_price = float(o.get('limit_price') or 0)
                        amount = o['amount']
                        if order_type_str == '지정가' and limit_price > 0:
                            st.write(f"- **주문 유형**: 지정가 **{limit_price:,.0f}원**")
                            if o['side'] == '매수':
                                qty = float(amount) / limit_price
                                st.write(f"- **주문 금액**: {float(amount):,.0f}원 → 수량 {qty:.8f}")
                            else:
                                total = float(amount) * limit_price
                                st.write(f"- **주문 수량**: {float(amount):.8f} → 금액 {total:,.0f}원")
                        else:
                            st.write(f"- **주문 유형**: 시장가")
                            if o['side'] == '매수':
                                st.write(f"- **주문 금액**: {float(amount):,.0f}원")
                            else:
                                st.write(f"- **주문 수량**: {float(amount):.8f}")
                        st.write(f"- **전략**: {o['strategy']}")
                    with col_i2:
                        st.write(f"- **실행 시각**: {o.get('exec_at', '—')}")
                        st.write(f"- **등록**: {o['created']}")
                        st.write(f"- **상태**: {o['status']}")
                        st.write(f"- **조건**: {o['note']}")

                    bc1, bc2, bc3, bc4 = st.columns(4)
                    with bc1:
                        toggle_label = "비활성화" if o["active"] else "활성화"
                        if st.button(toggle_label, key=f"res_tog_{oid}"):
                            for idx, x in enumerate(st.session_state.reserve_orders):
                                if x["id"] == oid:
                                    st.session_state.reserve_orders[idx]["active"] = not o["active"]
                                    break
                            add_log(f"[예약주문] #{oid} {toggle_label}", "INFO")
                            st.rerun(scope="fragment")
                    with bc2:
                        if o["status"] == "대기중":
                            if st.button("❌ 취소", key=f"res_cancel_{oid}"):
                                for idx, x in enumerate(st.session_state.reserve_orders):
                                    if x["id"] == oid:
                                        st.session_state.reserve_orders[idx]["status"] = "취소"
                                        st.session_state.reserve_orders[idx]["active"] = False
                                        break
                                add_log(f"[예약주문] #{oid} 취소", "INFO")
                                st.rerun(scope="fragment")
                    with bc3:
                        if st.button("🗑 삭제", key=f"res_del_{oid}"):
                            st.session_state.reserve_orders = [
                                x for x in st.session_state.reserve_orders if x["id"] != oid
                            ]
                            add_log(f"[예약주문] #{oid} 삭제", "INFO")
                            st.rerun(scope="fragment")
                    with bc4:
                        if st.button("✅ 완료 처리", key=f"res_done_{oid}"):
                            for idx, x in enumerate(st.session_state.reserve_orders):
                                if x["id"] == oid:
                                    st.session_state.reserve_orders[idx]["status"] = "완료"
                                    break
                            add_log(f"[예약주문] #{oid} 완료", "ORDER")
                            st.rerun(scope="fragment")
