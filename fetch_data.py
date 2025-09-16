import argparse
import yfinance as yf

def fetch_and_save(ticker: str, start: str = "2015-01-01", end: str = None, filename: str = "data.csv"):
    # Download daily OHLCV data
    df = yf.download(ticker, start=start, end=end, interval="1d", auto_adjust=True)

    # Keep only Date, Open, High, Low, Close, Volume
    df = df[["Open", "High", "Low", "Close", "Volume"]]

    # Save to CSV
    df.to_csv(filename, index=True, index_label="Date")

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Overnight Gap Strategy Backtester")
    p.add_argument("--tickers", type=str, default="SPY,HIMS,SMR,NBIS,QQQ,OMEX,AMBA,PTNM,AAPL,MSFT,V,NVDA,TSLA,VTI,HOOD",
                   help="Comma-separated list of tickers")
    return p.parse_args(argv)

if __name__ == "__main__":
    args = parse_args()
    tickers = args.tickers.replace(" ", "").split(",")
    for ticker in tickers:
        filename = f"data/data_{ticker}.csv"
        fetch_and_save(ticker, start="2015-01-01", filename=filename)
