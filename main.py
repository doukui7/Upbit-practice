"""
Upbit Auto Trading Bot - Main Entry Point
Moving Average Strategy
"""
import os
import time
import datetime
import pyupbit
from dotenv import load_dotenv
from broker_upbit import BrokerUpbit
from strategy import get_start_time, check_ma_signal
from utils import setup_logger, format_price

# 1. Load environment variables and login
load_dotenv()
access = os.getenv("UPBIT_ACCESS_KEY")
secret = os.getenv("UPBIT_SECRET_KEY")

# Create Broker Instance
broker = BrokerUpbit(access, secret)

# --- Configuration ---
TICKER = "KRW-BTC"      # Target coin
MA_PERIOD = 20           # Moving average period
INTERVAL = "day"         # Candle interval
MIN_KRW_ORDER = 5000     # Minimum KRW order amount

# --- Logger ---
logger = setup_logger()

def run_bot():
    """Main trading loop."""
    logger.info(f"=== {TICKER} Auto Trading Bot Started ===")
    logger.info(f"Strategy: Moving Average ({MA_PERIOD}) | Interval: {INTERVAL}")

    while True:
        try:
            now = datetime.datetime.now()
            # Get start time using broker instance
            start_time = get_start_time(broker, TICKER)
            
            if start_time:
                end_time = start_time + datetime.timedelta(days=1)
                
                # Check signal
                signal = check_ma_signal(broker, TICKER, ma_period=MA_PERIOD, interval=INTERVAL)

                logger.info(
                    f"Price: {format_price(signal['current_price'])} | "
                    f"MA{MA_PERIOD}: {format_price(signal['ma_value'])} | "
                    f"Label: {signal['signal_label']}"
                )

                # Buy when signal is positive (Simple logic for demonstration)
                if signal['buy_signal']:
                    # Logic for trading can be added here
                    pass

            time.sleep(10)  # Moderate polling interval

        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_bot()
