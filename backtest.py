import pandas as pd
from backtesting import Backtest, Strategy
from backtesting.test import GOOG  # Replace with your OHLCV data
from fetch_data import parse_args

# =====================
# Strategy Parameters
# =====================
GAP_THRESHOLD = 0.02         # 2% gap
VOL_MULTIPLIER = 1.5         # Volume filter multiplier
LOOKBACK_VOL = 20            # Days for average volume
TRANSACTION_BPS = 1          # Per-side, in basis points
MAX_POSITIONS = 3            # Max signals to take per day
ALLOC_PER_TRADE = 0.25       # Max allocation per trade (fraction of equity)
MODE = "revert"              # "revert" | "momentum" | "both" (default "revert")


class GapReversionStrategy(Strategy):
    def init(self):
        # Precompute intraday return (close/open - 1)
        self.intraday_ret = self.I(lambda: self.data.Close / self.data.Open - 1)

        # Rolling average volume (20-day SMA)
        self.avg_vol = self.I(lambda v: pd.Series(v).rolling(LOOKBACK_VOL).mean(),
                              self.data.Volume)
        

    def next(self):
        # Always exit yesterday’s positions at today’s open
        if self.position:
            self.position.close()
        # print(self.intraday_ret, self.data.Volume[-1], self.avg_vol[-1])
        # --- Signal Construction ---
        gap_up = self.intraday_ret[-1] >= GAP_THRESHOLD
        gap_down = self.intraday_ret[-1] <= -GAP_THRESHOLD
        vol_ok = self.data.Volume[-1] >= VOL_MULTIPLIER * self.avg_vol[-1]

        signals = []
        if vol_ok:
            if gap_up:
                signals.append(("gap_up", abs(self.intraday_ret[-1])))
            elif gap_down:
                signals.append(("gap_down", abs(self.intraday_ret[-1])))

        # --- Signal Ranking (by absolute move) ---
        signals = sorted(signals, key=lambda x: x[1], reverse=True)
        signals = signals[:MAX_POSITIONS]

        # --- Position Sizing ---
        if signals:
            alloc_per_trade = min(ALLOC_PER_TRADE, 1.0 / len(signals))

            for sig, strength in signals:
                if MODE in ("revert", "both"):
                    if sig == "gap_up":
                        self.sell(size=alloc_per_trade) #takes in fraction of equity
                    elif sig == "gap_down":
                        self.buy(size=alloc_per_trade)
                elif MODE == "momentum":
                    if sig == "gap_up":
                        self.buy(size=alloc_per_trade)
                    elif sig == "gap_down":
                        self.sell(size=alloc_per_trade)


# # Example run
# bt = Backtest(
#     GOOG,  # Replace with your data (DataFrame with Open, High, Low, Close, Volume)
#     GapReversionStrategy,
#     cash=100_000,
#     commission=2 * TRANSACTION_BPS / 10_000.0,  # round-trip transaction cost
#     exclusive_orders=True,
# )

# stats = bt.run()
# bt.plot()
# print(stats)

if __name__ == "__main__":
    for ticker in parse_args().tickers.split(","):
        print(f"Backtesting {ticker}...")
        data = pd.read_csv(f"data/data_{ticker}.csv", parse_dates=False, usecols=["Open", "High", "Low", "Close", "Volume"]).dropna()
        print(type(data["Open"].iloc[0]))
        bt = Backtest(
            data,
            GapReversionStrategy,
            cash=100_000,
            commission=2 * TRANSACTION_BPS / 10_000.0,  # round-trip transaction cost
            exclusive_orders=True,
        )

        stats = bt.run()
        bt.plot()
        print(stats)