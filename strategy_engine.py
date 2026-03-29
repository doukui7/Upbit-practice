"""
VM 전략 실행 엔진 — D:\upbit 패턴 기반
- 스케줄 룰 (4H: 01/05/09/13/17/21시, 1D: 09시)
- 전환 감지 (signal_state.json prev ↔ current)
- 매도 우선 실행
- 최소 주문금액 5,000원 필터
"""
import logging
import time
import pandas as pd
from datetime import datetime

from utils import round_price_upbit
from cache_utils import (
    load_signal_state, save_signal_state,
    append_trade_log, append_execution_log,
)
from notifier import send_telegram

logger = logging.getLogger(__name__)

MIN_ORDER_KRW = 5000
_DEFAULT_PORTFOLIO = [
    {"ticker": "KRW-BTC", "strategy": "Donchian", "param": 115,
     "sell_param": 105, "interval": "minute240", "weight": 100},
]


def load_portfolio():
    """cache/portfolio.json에서 포트폴리오 설정 로드."""
    import json
    from pathlib import Path
    p = Path(__file__).parent / "cache" / "portfolio.json"
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"portfolio.json 로드 실패: {e}")
    return list(_DEFAULT_PORTFOLIO)

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except Exception:
    KST = None


def _now_kst():
    return datetime.now(KST) if KST else datetime.now()


# ── 주기 필터 (D:\upbit 패턴) ──────────────────────────────

def is_interval_due(interval: str, now_kst=None) -> bool:
    """현재 시각이 해당 주기의 실행 시간인지 판단."""
    if now_kst is None:
        now_kst = _now_kst()
    hour = now_kst.hour
    minute = now_kst.minute
    due_window = 55  # 정시~55분 사이 실행

    if interval == "day":
        return hour == 9 and minute <= due_window
    elif interval == "minute240":
        return hour in (1, 5, 9, 13, 17, 21) and minute <= due_window
    return True


def _make_signal_key(ticker: str, strategy: str, param: int, interval: str) -> str:
    """신호 상태 키 생성."""
    return f"{ticker}_{strategy}_{param}_{interval}"


# ── 전략 분석 ──────────────────────────────────────────────

def analyze_sma(broker, ticker: str, period: int, interval: str = "day") -> dict:
    """SMA 전략 분석 — 현재가가 SMA 위면 BUY, 아래면 SELL."""
    warm_up = period + 10
    df = broker.get_ohlcv(ticker, interval=interval, count=warm_up)
    if df is None or df.empty or len(df) < period + 2:
        return {}

    df["SMA"] = df["close"].rolling(window=period).mean()
    # 마지막 완성된 캔들 기준 (진행 중인 캔들 제외)
    last = df.iloc[-2]
    sma_val = float(last["SMA"]) if pd.notna(last["SMA"]) else 0

    current_price = broker.get_current_price(ticker)
    if not current_price or current_price <= 0:
        return {}

    position_state = "BUY" if current_price > sma_val else "SELL"

    return {
        "ticker": ticker,
        "strategy": "SMA",
        "param": period,
        "interval": interval,
        "current_price": current_price,
        "indicator_value": sma_val,
        "position_state": position_state,
        "label": f"SMA({period}, {interval})",
    }


def analyze_donchian(broker, ticker: str, buy_period: int,
                     sell_period: int, interval: str = "minute240") -> dict:
    """Donchian 전략 분석 — 상단 돌파 BUY, 하단 이탈 SELL."""
    max_p = max(buy_period, sell_period)
    warm_up = max_p + 10
    df = broker.get_ohlcv(ticker, interval=interval, count=warm_up)
    if df is None or df.empty or len(df) < max_p + 2:
        return {}

    df["upper"] = df["high"].rolling(window=buy_period).max()
    df["lower"] = df["low"].rolling(window=sell_period).min()
    last = df.iloc[-2]
    upper = float(last["upper"]) if pd.notna(last["upper"]) else 0
    lower = float(last["lower"]) if pd.notna(last["lower"]) else 0

    current_price = broker.get_current_price(ticker)
    if not current_price or current_price <= 0:
        return {}

    if current_price > upper and upper > 0:
        position_state = "BUY"
    elif current_price < lower and lower > 0:
        position_state = "SELL"
    else:
        position_state = "HOLD"

    return {
        "ticker": ticker,
        "strategy": "Donchian",
        "param": buy_period,
        "sell_param": sell_period,
        "interval": interval,
        "current_price": current_price,
        "upper": upper,
        "lower": lower,
        "indicator_value": upper,
        "position_state": position_state,
        "label": f"Donchian({buy_period}/{sell_period}, {interval})",
    }


# ── 전환 감지 (D:\upbit 패턴) ─────────────────────────────

def determine_signal(position_state: str, prev_state: str | None) -> str:
    """이전 상태와 비교하여 전환 시그널 결정."""
    if position_state == "HOLD":
        return "HOLD"
    if prev_state is None:
        return position_state
    if position_state == prev_state:
        return "HOLD"
    return position_state


# ── 메인 실행 ─────────────────────────────────────────────

def run_strategy(broker, portfolio: list[dict], dry_run: bool = False):
    """
    전략 실행 메인 함수.

    portfolio 예시:
    [
        {"ticker": "KRW-BTC", "strategy": "Donchian", "param": 115,
         "sell_param": 105, "interval": "minute240", "weight": 100},
    ]

    Returns: list of execution results
    """
    now = _now_kst()
    results = []
    signal_state = load_signal_state()

    # ── 1단계: 분석 ──
    analyses = []
    for item in portfolio:
        ticker = item["ticker"]
        strategy = item.get("strategy", "SMA")
        interval = item.get("interval", "day")
        param = item.get("param", 20)

        # 주기 필터
        if not is_interval_due(interval, now):
            logger.info(f"[{ticker}] 주기 미도래 ({interval}) — 스킵")
            append_execution_log({
                "action": "skip", "ticker": ticker,
                "strategy": f"{strategy}({param})",
                "reason": f"주기 미도래 ({interval})",
            })
            continue

        # 전략별 분석
        try:
            if strategy == "Donchian":
                sell_param = item.get("sell_param", max(5, param // 2))
                analysis = analyze_donchian(broker, ticker, param, sell_param, interval)
            else:
                analysis = analyze_sma(broker, ticker, param, interval)
        except Exception as e:
            logger.error(f"[{ticker}] 분석 오류: {e}")
            append_execution_log({
                "action": "error", "ticker": ticker,
                "strategy": f"{strategy}({param})",
                "error": str(e)[:200],
            })
            continue

        if not analysis:
            logger.warning(f"[{ticker}] 분석 결과 없음")
            continue

        # 전환 감지
        sig_key = _make_signal_key(ticker, strategy, param, interval)
        prev = signal_state.get(sig_key, {}).get("state") if isinstance(
            signal_state.get(sig_key), dict) else signal_state.get(sig_key)
        signal = determine_signal(analysis["position_state"], prev)
        analysis["signal"] = signal
        analysis["signal_key"] = sig_key
        analysis["prev_state"] = prev
        analysis["weight"] = item.get("weight", 100)

        logger.info(
            f"[{ticker}] {analysis['label']} | "
            f"prev={prev} → pos={analysis['position_state']} → signal={signal} | "
            f"price={analysis['current_price']:,.0f}"
        )
        analyses.append(analysis)

    if not analyses:
        logger.info("실행할 전략 없음")
        return results

    # ── 2단계: 매도 우선 실행 (D:\upbit 패턴) ──
    for a in analyses:
        if a["signal"] != "SELL":
            continue
        ticker = a["ticker"]
        coin_sym = ticker.split("-")[-1]

        try:
            coin_balance = float(broker.get_balance(coin_sym) or 0)
        except Exception:
            coin_balance = 0

        if coin_balance <= 0:
            logger.info(f"[{ticker}] SELL 스킵 — 보유량 없음")
            continue

        sell_value = coin_balance * a["current_price"]
        if sell_value < MIN_ORDER_KRW:
            logger.info(f"[{ticker}] SELL 스킵 — 주문금액 미달 {sell_value:,.0f}원 < {MIN_ORDER_KRW:,}원")
            continue

        logger.info(f"[{ticker}] SELL 실행: {coin_balance:.8f} {coin_sym} (≈{sell_value:,.0f}원)")

        if dry_run:
            result = {"dry_run": True, "side": "SELL", "ticker": ticker,
                      "qty": coin_balance, "value": sell_value}
        else:
            result = broker.sell_market_order(ticker, coin_balance)

        a["exec_result"] = result
        results.append({"side": "SELL", "ticker": ticker, "result": result})
        append_trade_log({
            "mode": "auto", "ticker": ticker, "side": "SELL",
            "strategy": a["label"], "qty": f"{coin_balance:.8f}",
            "value": f"{sell_value:,.0f}",
            "result": str(result)[:200],
        })
        logger.info(f"[{ticker}] SELL 결과: {result}")
        time.sleep(1)

    # ── 3단계: 매수 실행 ──
    for a in analyses:
        if a["signal"] != "BUY":
            continue
        ticker = a["ticker"]

        try:
            krw_balance = float(broker.get_balance("KRW") or 0)
        except Exception:
            krw_balance = 0

        # 가중치 기반 매수 금액 계산
        buy_amount = krw_balance * (a["weight"] / 100)
        if buy_amount < MIN_ORDER_KRW:
            logger.info(f"[{ticker}] BUY 스킵 — 금액 부족 {buy_amount:,.0f}원 < {MIN_ORDER_KRW:,}원")
            continue

        logger.info(f"[{ticker}] BUY 실행: {buy_amount:,.0f}원 (잔고 {krw_balance:,.0f}원의 {a['weight']}%)")

        if dry_run:
            result = {"dry_run": True, "side": "BUY", "ticker": ticker,
                      "amount": buy_amount}
        else:
            result = broker.buy_market_order(ticker, buy_amount)

        a["exec_result"] = result
        results.append({"side": "BUY", "ticker": ticker, "result": result})
        append_trade_log({
            "mode": "auto", "ticker": ticker, "side": "BUY",
            "strategy": a["label"], "amount": f"{buy_amount:,.0f}",
            "result": str(result)[:200],
        })
        logger.info(f"[{ticker}] BUY 결과: {result}")
        time.sleep(1)

    # ── 4단계: signal_state 업데이트 ──
    for a in analyses:
        sig_key = a["signal_key"]
        effective_state = a["position_state"]
        if effective_state == "HOLD" and a.get("prev_state") in ("BUY", "SELL"):
            effective_state = a["prev_state"]
        signal_state[sig_key] = {
            "state": effective_state,
            "price": a["current_price"],
            "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "label": a["label"],
        }

    save_signal_state(signal_state)
    logger.info(f"signal_state 저장 완료 ({len(analyses)}개 전략)")

    append_execution_log({
        "action": "strategy_run",
        "strategies": len(analyses),
        "sells": sum(1 for r in results if r["side"] == "SELL"),
        "buys": sum(1 for r in results if r["side"] == "BUY"),
        "portfolio": [a["ticker"] for a in analyses],
    })

    # ── 텔레그램 알림 ──
    if results:
        lines = [f"<b>자동매매 실행</b> ({now.strftime('%H:%M')})"]
        for r in results:
            lines.append(f"  {r['side']} {r['ticker']}: {str(r['result'])[:100]}")
        try:
            send_telegram("\n".join(lines))
        except Exception:
            pass

    return results
