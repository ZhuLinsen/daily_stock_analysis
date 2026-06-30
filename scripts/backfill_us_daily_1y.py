import sqlite3
from datetime import datetime
import pandas as pd
import yfinance as yf

DB = "data/stock_analysis.db"
SYMBOLS = ["GOOG", "AAPL"]

def normalize_df(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns={
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    })
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["pct_chg"] = df["close"].pct_change() * 100
    df["volume_ratio"] = df["volume"] / df["volume"].rolling(5).mean().shift(1)
    return df

conn = sqlite3.connect(DB)
cur = conn.cursor()
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

for symbol in SYMBOLS:
    print(f"Fetching {symbol} 1y daily...")
    df = yf.download(symbol, period="1y", interval="1d", auto_adjust=False, progress=False)
    df = normalize_df(df)

    if df.empty:
        print(f"{symbol}: no data")
        continue

    start_date = df.index.min().strftime("%Y-%m-%d")
    end_date = df.index.max().strftime("%Y-%m-%d")

    cur.execute(
        "delete from stock_daily where code=? and date between ? and ?",
        (symbol, start_date, end_date),
    )

    rows = []
    for idx, row in df.iterrows():
        rows.append((
            symbol,
            idx.strftime("%Y-%m-%d"),
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
            int(row["volume"]),
            0,
            None if pd.isna(row["pct_chg"]) else float(row["pct_chg"]),
            None if pd.isna(row["ma5"]) else float(row["ma5"]),
            None if pd.isna(row["ma10"]) else float(row["ma10"]),
            None if pd.isna(row["ma20"]) else float(row["ma20"]),
            None if pd.isna(row["volume_ratio"]) else float(row["volume_ratio"]),
            "yfinance_1y_backfill",
            now,
            now,
        ))

    cur.executemany("""
        insert into stock_daily
        (code, date, open, high, low, close, volume, amount, pct_chg,
         ma5, ma10, ma20, volume_ratio, data_source, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)

    print(f"{symbol}: inserted {len(rows)} rows, {start_date} ~ {end_date}")

conn.commit()

print("\nCurrent stock_daily counts:")
for symbol in SYMBOLS:
    count, min_date, max_date = cur.execute(
        "select count(*), min(date), max(date) from stock_daily where code=?",
        (symbol,),
    ).fetchone()
    print(symbol, count, min_date, max_date)

conn.close()
