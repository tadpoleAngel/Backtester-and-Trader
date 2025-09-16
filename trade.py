import os
import sys
import threading
import pandas as pd
import alpaca_trade_api as tradeapi
from datetime import datetime, time, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from dotenv import load_dotenv
import time as sleepy_time

# =====================
# Strategy Parameters (from backtest.py)
# =====================
GAP_THRESHOLD = 0.02         # 2% gap
VOL_MULTIPLIER = 1.5         # Volume filter multiplier
LOOKBACK_VOL = 20            # Days for average volume
TRANSACTION_BPS = 1          # Per-side, in basis points
MAX_POSITIONS = 3            # Max signals to take per day
ALLOC_PER_TRADE = 0.25       # Max allocation per trade (fraction of equity)
MODE = "revert"              # "revert" | "momentum" | "both"
TRADING_START = time(3, 50)  # Edit as needed 24 hr
TRADING_END = time(4, 00)    # Edit as needed 24 hr

# =====================
# Alpaca API Setup
# =====================
load_dotenv('.env')
API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')
BASE_URL = 'https://paper-api.alpaca.markets'
api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version='v2')
trading_client = TradingClient(API_KEY, API_SECRET, paper=True)

# =====================
# Utility Functions
# =====================
def get_equity():
    return float(api.get_account().equity)

def get_active_assets():
    return [asset.symbol for asset in api.list_assets(status='active') if asset.tradable and asset.shortable]

def get_historical_data(symbol, days=LOOKBACK_VOL+1):
    bars = api.get_bars(symbol, '1Day', limit=days).df
    if bars.empty:
        raise ValueError(f"No historical data for {symbol}")
    return bars

def get_current_bar(symbol):
    bars = api.get_bars(symbol, '1Day', limit=1).df
    if bars.empty:
        raise ValueError(f"No daily bar data for {symbol}")
    last_bar = bars.iloc[-1]
    return {
        'Open': last_bar['open'],
        'High': last_bar['high'],
        'Close': last_bar['close'],
        'Volume': last_bar['volume']
    }

# =====================
# Gap Reversion Trade Logic (modular)
# =====================
def gap_reversion_signals(symbol, current_bar, historical_data):
    intraday_ret = current_bar['Close'] / current_bar['Open'] - 1
    avg_vol = pd.Series(historical_data['volume']).rolling(LOOKBACK_VOL).mean().iloc[-1]
    vol_ok = current_bar['Volume'] >= VOL_MULTIPLIER * avg_vol
    gap_up = intraday_ret >= GAP_THRESHOLD
    gap_down = intraday_ret <= -GAP_THRESHOLD
    signals = []
    if vol_ok:
        if gap_up:
            signals.append(("gap_up", abs(intraday_ret)))
        elif gap_down:
            signals.append(("gap_down", abs(intraday_ret)))
    return signals

def rank_and_size_signals(signals):
    signals = sorted(signals, key=lambda x: x[1], reverse=True)
    signals = signals[:MAX_POSITIONS]
    if signals:
        alloc_per_trade = min(ALLOC_PER_TRADE, 1.0 / len(signals))
        return [(sig, alloc_per_trade) for sig, _ in signals]
    return []

def place_trade(symbol, action, alloc_per_trade, equity, price):
    trade_amount = alloc_per_trade * equity
    quantity = max(1, int(trade_amount / price))
    side = OrderSide.SELL if action == "gap_up" and MODE in ("revert", "both") else OrderSide.BUY
    order_data = MarketOrderRequest(
        symbol=symbol,
        qty=quantity,
        side=side,
        time_in_force=TimeInForce.DAY
    )
    try:
        order = trading_client.submit_order(order_data=order_data)
        print(f"Placed {side} order for {quantity} shares of {symbol} at ${price}")
        return order
    except Exception as e:
        print(f"Error placing order for {symbol}: {e}")
        return None

# =====================
# Main Trading Loop
# =====================

def close_all_positions():
    positions = trading_client.get_all_positions()
    for pos in positions:
        try:
            trading_client.close_position(pos.symbol)
            print(f"Closed position for {pos.symbol}")
        except Exception as e:
            print(f"Error closing position for {pos.symbol}: {e}")

def print_time_status():
    now = datetime.now()
    print(f"Current time: {now.strftime('%H:%M:%S')} | Date: {now.date()}")
    print(f"Trading window: {TRADING_START.strftime('%H:%M')} - {TRADING_END.strftime('%H:%M')}")


def in_trading_window(now=None):
    if now is None:
        now = datetime.now().time()
    elif isinstance(now, datetime):
        now = now.time()
    return TRADING_START <= now <= TRADING_END

def seconds_until(dt):
    now = datetime.now()
    if isinstance(dt, time):
        target = datetime.combine(now.date(), dt)
        if now.time() > dt:
            target += timedelta(days=1)
    else:
        target = dt
    return max(1, int((target - now).total_seconds()))

def sleep_until(dt, message=None):
    if message:
        print(message)
    
    secs = seconds_until(dt)
    while secs > 0 and not stop_script:
        print(f"\rSleeping for {secs//60//60:02d}:{secs%(60*60)//60:02d}:{secs%60}...", end="")
        secs = seconds_until(dt)
        sleepy_time.sleep(1)

stop_script = False
errors = []

def input_listener():
    global stop_script
    input("Press Enter to terminate the script normally...\n")
    stop_script = True
    print("terminating...")

def urgent_listener():
    global errors
    userInput = ""
    while userInput != "now":
        userInput = input("Type \"now\" and press enter to terminate the script immediately...\n")
    print("terminating now...")
    print("script terminated.\n")
    print("Exceptions: ")
    print(errors)
    os._exit(os.EX_OK)


def trading_window_sleep(now):
    print(f"It's {now.time()}, on {now.date()} I'll just nap until it's time for me to place some trades.")
    print(f"\nSleeping until {TRADING_END.strftime('%H:%M')} EST...")
    sleep_until(datetime.combine(now.date(), TRADING_END))

def outside_window_sleep(now):
    positions = trading_client.get_all_positions()
    if positions:
        print(f"\nIt's {now.time()}, on {now.date()} and I've got open positions!")
        print("Closing all open positions...")
    close_all_positions()
    print(f"\nSleeping until {TRADING_START.strftime('%H:%M')} EST...")
    sleep_until(TRADING_START)

def main():
    assets = get_active_assets()
    equity = get_equity()
    print(f"Starting trading loop with equity: ${equity:.2f}")
    print_time_status()
    while not stop_script:
        now = datetime.now()
        try:
            if in_trading_window(now):
                print(f"\nTrading window open. Placing trades...")
                for symbol in assets:
                    try:
                        current_bar = get_current_bar(symbol)
                        historical_data = get_historical_data(symbol)
                        signals = gap_reversion_signals(symbol, current_bar, historical_data)
                        ranked = rank_and_size_signals(signals)
                        for sig, alloc_per_trade in ranked:
                            action = sig
                            price = current_bar['Close']
                            place_trade(symbol, action, alloc_per_trade, equity, price)
                        if not ranked:
                            print(f"{symbol}: No trade signal.")
                    except Exception as e:
                        print(f"Error processing {symbol}: {e}")
                        errors.append(e)
                trading_window_sleep(now)
            else:
                outside_window_sleep(now)
        except Exception as e:
            print(f"Main loop error: {e}")
            errors.append(e)

if __name__ == "__main__":
    listener_thread = threading.Thread(target=input_listener)
    listener_thread.start()
    urgent_thread = threading.Thread(target=urgent_listener)
    urgent_thread.daemon = True
    urgent_thread.start()
    main()

# if __name__ == "__main__":
#     main()
