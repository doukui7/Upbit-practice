"""
VM용 FastAPI 서버 — 브로커 API 중계 + 스케줄러
- 로컬 Streamlit → HTTP → 이 서버 → 업비트/한투 API
- 예약 주문 스케줄러 (백그라운드)
uvicorn api_server:app --host 0.0.0.0 --port 8000
"""
import os
import json
import logging
import threading
import time as _time
from datetime import datetime
from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from utils import round_price_upbit
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 브로커 초기화 ─────────────────────────────────────────────────────
from broker_upbit import BrokerUpbit
from broker_kis import BrokerKIS

API_KEY = os.getenv("VM_API_KEY", "")
_brokers = {}


def _init_brokers():
    access = os.getenv("UPBIT_ACCESS_KEY")
    secret = os.getenv("UPBIT_SECRET_KEY")
    if access and secret:
        try:
            _brokers["upbit"] = BrokerUpbit(access, secret)
            logger.info("Upbit broker initialized")
        except Exception as e:
            logger.error(f"Upbit init failed: {e}")

    for env_prefix, key, mock in [
        ("KIS_REAL", "kis_real", False),
        ("KIS_MOCK", "kis_mock", True),
    ]:
        app_key = os.getenv(f"{env_prefix}_APP_KEY")
        app_secret = os.getenv(f"{env_prefix}_APP_SECRET")
        account = os.getenv(f"{env_prefix}_ACCOUNT")
        if app_key and app_secret:
            try:
                _brokers[key] = BrokerKIS(app_key, app_secret, account, mock=mock)
                logger.info(f"KIS broker ({key}) initialized")
            except Exception as e:
                logger.error(f"KIS {key} init failed: {e}")


_init_brokers()

# ── FastAPI 앱 ─────────────────────────────────────────────────────────
app = FastAPI(title="Trading API Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _get_broker(broker_key: str):
    b = _brokers.get(broker_key)
    if not b:
        raise HTTPException(404, f"Broker '{broker_key}' not found. Available: {list(_brokers.keys())}")
    return b


def _check_auth(x_api_key: str = Header(default="")):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, "Invalid API key")


# ── 헬스체크 ──────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "brokers": list(_brokers.keys()), "time": datetime.now().isoformat()}


# ── 브로커 정보 ───────────────────────────────────────────────────────
@app.get("/api/broker_info")
def broker_info(broker: str = Query(...), x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    b = _get_broker(broker)
    return {"name": b.name, "account_number": getattr(b, "account_number", "")}


# ── 잔고 ─────────────────────────────────────────────────────────────
@app.get("/api/balances")
def get_balances(broker: str = Query(...), x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    return _get_broker(broker).get_balances()


@app.get("/api/balance")
def get_balance(broker: str = Query(...), ticker: str = Query(...), x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    return {"balance": _get_broker(broker).get_balance(ticker)}


# ── 시세 ─────────────────────────────────────────────────────────────
@app.get("/api/current_price")
def get_current_price(broker: str = Query(...), ticker: str = Query(...), x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    return {"price": _get_broker(broker).get_current_price(ticker)}


@app.get("/api/ohlcv")
def get_ohlcv(broker: str = Query(...), ticker: str = Query(...),
              interval: str = Query("day"), count: int = Query(200),
              x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    df = _get_broker(broker).get_ohlcv(ticker, interval=interval, count=count)
    if df is None or df.empty:
        return {"data": [], "columns": []}
    df_reset = df.reset_index()
    for col in df_reset.columns:
        if 'datetime' in str(df_reset[col].dtype):
            df_reset[col] = df_reset[col].astype(str)
    return {"data": df_reset.to_dict(orient="records"), "columns": list(df_reset.columns), "index_name": df.index.name}


# ── 주문 조회 ────────────────────────────────────────────────────────
@app.get("/api/orders")
def get_orders(broker: str = Query(...), ticker: str = Query(...),
               state: str = Query("wait"), x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    return _get_broker(broker).get_order(ticker, state=state)


# ── 주문 실행 ────────────────────────────────────────────────────────
class OrderRequest(BaseModel):
    broker: str
    ticker: str
    price: float = 0
    volume: float = 0
    virtual: bool = False  # True → 체결 안 되는 가격으로 변환


def _apply_virtual_price(broker, ticker, side, price, virtual):
    """가상 모드: 매수 *0.5, 매도 *1.5 → 체결 불가능한 가격으로 변환"""
    if not virtual:
        return price
    # 현재가 기준으로 계산
    b = _get_broker(broker)
    cur = b.get_current_price(ticker)
    if not cur or cur == 0:
        cur = price if price > 0 else 1
    if side == "buy":
        return round_price_upbit(cur * 0.5)
    else:
        return round_price_upbit(cur * 1.5)


@app.post("/api/buy_market")
def buy_market(req: OrderRequest, x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    b = _get_broker(req.broker)
    if req.virtual:
        # 시장가 → 체결 안 되는 지정가로 변환
        vp = _apply_virtual_price(req.broker, req.ticker, "buy", req.price, True)
        cur = b.get_current_price(req.ticker) or 1
        qty = req.price / cur if cur > 0 else 0
        logger.info(f"[VIRTUAL] buy_limit {req.ticker} @ {vp:.0f} (real: {cur:.0f}) qty: {qty:.8f}")
        return {"result": b.buy_limit_order(req.ticker, vp, qty), "virtual": True}
    return {"result": b.buy_market_order(req.ticker, req.price)}


@app.post("/api/sell_market")
def sell_market(req: OrderRequest, x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    b = _get_broker(req.broker)
    if req.virtual:
        vp = _apply_virtual_price(req.broker, req.ticker, "sell", 0, True)
        logger.info(f"[VIRTUAL] sell_limit {req.ticker} @ {vp:.0f} qty: {req.volume}")
        return {"result": b.sell_limit_order(req.ticker, vp, req.volume), "virtual": True}
    return {"result": b.sell_market_order(req.ticker, req.volume)}


@app.post("/api/buy_limit")
def buy_limit(req: OrderRequest, x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    b = _get_broker(req.broker)
    price = _apply_virtual_price(req.broker, req.ticker, "buy", req.price, req.virtual)
    price = round_price_upbit(price) if price > 0 else price
    if req.virtual:
        logger.info(f"[VIRTUAL] buy_limit {req.ticker} @ {price:.0f} (orig: {req.price:.0f}) qty: {req.volume}")
    return {"result": b.buy_limit_order(req.ticker, price, req.volume), "virtual": req.virtual}


@app.post("/api/sell_limit")
def sell_limit(req: OrderRequest, x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    b = _get_broker(req.broker)
    price = _apply_virtual_price(req.broker, req.ticker, "sell", req.price, req.virtual)
    price = round_price_upbit(price) if price > 0 else price
    if req.virtual:
        logger.info(f"[VIRTUAL] sell_limit {req.ticker} @ {price:.0f} (orig: {req.price:.0f}) qty: {req.volume}")
    return {"result": b.sell_limit_order(req.ticker, price, req.volume), "virtual": req.virtual}


@app.post("/api/cancel_order")
def cancel_order(broker: str = Query(...), uuid: str = Query(...), x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    return {"result": _get_broker(broker).cancel_order(uuid)}


# ── 개별 주문 상태 조회 ──────────────────────────────────────────────
@app.get("/api/order_detail")
def order_detail(broker: str = Query(...), uuid: str = Query(...), x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    b = _get_broker(broker)
    if hasattr(b, 'upbit'):
        return {"result": b.upbit.get_order(uuid)}
    return {"result": None}


# ── 입출금 내역 ──────────────────────────────────────────────────────
@app.get("/api/deposits")
def get_deposits(broker: str = Query(...), currency: str = Query("KRW"),
                 count: int = Query(20), x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    b = _get_broker(broker)
    return b.get_deposit_history(currency, count) if hasattr(b, 'get_deposit_history') else []


@app.get("/api/withdraws")
def get_withdraws(broker: str = Query(...), currency: str = Query("KRW"),
                  count: int = Query(20), x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    b = _get_broker(broker)
    return b.get_withdraw_history(currency, count) if hasattr(b, 'get_withdraw_history') else []


# ══════════════════════════════════════════════════════════════════════
# 스케줄러 — 예약 주문 (백그라운드)
# ══════════════════════════════════════════════════════════════════════
_scheduled_orders = []  # {"id", "broker", "ticker", "side", "price", "volume", "trigger_time", "status"}
_schedule_lock = threading.Lock()
_next_id = 1


class ScheduleRequest(BaseModel):
    broker: str
    ticker: str
    side: str        # "buy" or "sell"
    order_type: str  # "market" or "limit"
    price: float = 0
    volume: float = 0
    trigger_time: str  # ISO format "2026-03-21T15:30:00"


@app.post("/api/schedule/add")
def schedule_add(req: ScheduleRequest, x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    global _next_id
    with _schedule_lock:
        order = {
            "id": _next_id,
            "broker": req.broker,
            "ticker": req.ticker,
            "side": req.side,
            "order_type": req.order_type,
            "price": req.price,
            "volume": req.volume,
            "trigger_time": req.trigger_time,
            "status": "waiting",
            "created_at": datetime.now().isoformat(),
            "result": None,
        }
        _scheduled_orders.append(order)
        _next_id += 1
        logger.info(f"Schedule added: #{order['id']} {req.side} {req.ticker} at {req.trigger_time}")
        return order


@app.get("/api/schedule/list")
def schedule_list(x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    return _scheduled_orders


@app.delete("/api/schedule/cancel")
def schedule_cancel(order_id: int = Query(...), x_api_key: str = Header(default="")):
    _check_auth(x_api_key)
    with _schedule_lock:
        for order in _scheduled_orders:
            if order["id"] == order_id and order["status"] == "waiting":
                order["status"] = "cancelled"
                return {"result": "cancelled", "id": order_id}
    raise HTTPException(404, f"Order #{order_id} not found or not cancellable")


# ══════════════════════════════════════════════════════════════════════
# 확장 스케줄러 — 예약주문 + 잔고동기화 + GitHub push + 하트비트
# ══════════════════════════════════════════════════════════════════════

from cache_utils import (
    save_balance_cache, save_signal_state, save_scheduler_state,
    append_trade_log, append_execution_log, push_all_cache, CACHE_FILES,
    record_scheduler_error, record_scheduler_success,
)

GH_PAT = os.getenv("GH_PAT", "")
BALANCE_SYNC_INTERVAL = 30
GITHUB_PUSH_INTERVAL = 300

try:
    from zoneinfo import ZoneInfo
    _KST = ZoneInfo("Asia/Seoul")
except Exception:
    _KST = None

def _now_kst():
    if _KST:
        return datetime.now(_KST)
    return datetime.now()

_scheduler_state = {"__started_at_kst": _now_kst().strftime("%Y-%m-%d %H:%M:%S")}


def _sync_balance():
    """잔고 + 현재 보유 종목 시세 동기화 → cache/balance_cache.json"""
    try:
        for broker_key, broker in _brokers.items():
            balances = broker.get_balances()
            if not isinstance(balances, list):
                continue
            prices = {}
            holdings = {}
            for b in balances:
                curr = b.get("currency", "")
                bal = float(b.get("balance", 0))
                if curr == "KRW":
                    holdings["KRW"] = bal
                elif bal > 0:
                    holdings[curr] = bal
                    ticker = f"KRW-{curr}" if broker_key == "upbit" else curr
                    try:
                        p = broker.get_current_price(ticker)
                        if p:
                            prices[ticker] = p
                    except Exception:
                        pass
            save_balance_cache({
                "broker": broker_key,
                "balances": holdings,
                "prices": prices,
            })
    except Exception as e:
        logger.error(f"Balance sync error: {e}")
        record_scheduler_error(_scheduler_state, "balance_sync", e)


def _push_to_github():
    """캐시 파일을 GitHub에 push"""
    if not GH_PAT:
        return
    try:
        push_all_cache(GH_PAT)
    except Exception as e:
        logger.error(f"GitHub push error: {e}")


def _load_portfolio():
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
    # 기본 포트폴리오 (BTC Donchian 115/105 4H)
    return [
        {"ticker": "KRW-BTC", "strategy": "Donchian", "param": 115,
         "sell_param": 105, "interval": "minute240", "weight": 100},
    ]


def _run_strategy():
    """전략 자동 실행 — strategy_engine 호출."""
    from strategy_engine import run_strategy, is_interval_due
    broker = _brokers.get("upbit")
    if not broker:
        return
    portfolio = _load_portfolio()
    # 주기 필터: 실행할 전략이 하나도 없으면 스킵
    now_kst = _now_kst()
    any_due = any(is_interval_due(item.get("interval", "day"), now_kst) for item in portfolio)
    if not any_due:
        return
    try:
        results = run_strategy(broker, portfolio)
        if results:
            record_scheduler_success(_scheduler_state, "auto_trade")
            logger.info(f"전략 실행 완료: {len(results)}건 주문")
        else:
            logger.info("전략 실행 완료: 주문 없음 (조건 미충족)")
    except Exception as e:
        logger.error(f"전략 실행 오류: {e}")
        record_scheduler_error(_scheduler_state, "auto_trade", e)


def _scheduler_loop():
    """통합 스케줄러 — 전략실행 + 예약주문 + 잔고동기화 + GitHub push + 하트비트"""
    last_balance_sync = 0
    last_github_push = 0
    last_strategy_check = 0
    STRATEGY_CHECK_INTERVAL = 60  # 1분마다 주기 체크

    while True:
        now_ts = _time.time()
        now = _now_kst()

        # ── 하트비트 (매 루프) ──────────────────────────────
        save_scheduler_state(_scheduler_state)

        # ── 잔고 동기화 (30초) ──────────────────────────────
        if now_ts - last_balance_sync >= BALANCE_SYNC_INTERVAL:
            _sync_balance()
            last_balance_sync = now_ts

        # ── 전략 자동 실행 (1분 체크) ──────────────────────
        if now_ts - last_strategy_check >= STRATEGY_CHECK_INTERVAL:
            _run_strategy()
            last_strategy_check = now_ts

        # ── GitHub push (5분) ───────────────────────────────
        if now_ts - last_github_push >= GITHUB_PUSH_INTERVAL:
            _push_to_github()
            last_github_push = now_ts

        # ── 예약 주문 체크 (매 루프) ────────────────────────
        with _schedule_lock:
            for order in _scheduled_orders:
                if order["status"] != "waiting":
                    continue
                try:
                    trigger = datetime.fromisoformat(order["trigger_time"])
                    if now >= trigger:
                        b = _brokers.get(order["broker"])
                        if not b:
                            order["status"] = "error"
                            order["result"] = "broker not found"
                            continue

                        # 호가 단위 보정
                        if order["order_type"] == "limit" and order.get("price", 0) > 0:
                            order["price"] = round_price_upbit(order["price"])

                        result = None
                        if order["side"] == "buy" and order["order_type"] == "market":
                            result = b.buy_market_order(order["ticker"], order["price"])
                        elif order["side"] == "sell" and order["order_type"] == "market":
                            result = b.sell_market_order(order["ticker"], order["volume"])
                        elif order["side"] == "buy" and order["order_type"] == "limit":
                            result = b.buy_limit_order(order["ticker"], order["price"], order["volume"])
                        elif order["side"] == "sell" and order["order_type"] == "limit":
                            result = b.sell_limit_order(order["ticker"], order["price"], order["volume"])

                        order["status"] = "executed"
                        order["result"] = str(result)
                        order["executed_at"] = now.isoformat()
                        logger.info(f"Schedule executed: #{order['id']} {order['side']} {order['ticker']} -> {result}")

                        append_trade_log({
                            "mode": "schedule",
                            "broker": order["broker"],
                            "ticker": order["ticker"],
                            "side": order["side"],
                            "result": str(result),
                        })
                        record_scheduler_success(_scheduler_state, "schedule")

                except Exception as e:
                    order["status"] = "error"
                    order["result"] = str(e)
                    logger.error(f"Schedule error: #{order['id']} {e}")
                    record_scheduler_error(_scheduler_state, "schedule", e)

        _time.sleep(10)


# 스케줄러 스레드 시작
_scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
_scheduler_thread.start()
logger.info("Scheduler thread started (balance sync + GitHub push + heartbeat)")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
