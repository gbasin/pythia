#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "yfinance>=0.2.65"]
# ///
"""Benchmark whether Pythia's daily recommendation intensity has signal.

V1 benchmark:
  - signal date = run started_at converted to America/New_York calendar date
  - basket = top N tickers by net_score (bullish - bearish)
  - baseline = all valid mentioned tickers that day
  - return = next market session open -> close

Prices are cached in SQLite so reruns only fetch missing bars.
"""

from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("PYTHIA_DB_PATH", ROOT / "db" / "panel.sqlite"))
MARKET_TZ = ZoneInfo("America/New_York")
BENCHMARK_TICKERS = ("SPY", "QQQ")
YFINANCE_SKIP = {"SPX", "NDX", "RUT", "DJI", "DJX", "VIX", "COMP", "DXY", "IXIC"}


@dataclass(frozen=True)
class DayResult:
    signal_date: str
    trade_date: str
    top_n: int
    top_available: int
    all_available: int
    top_return: float
    all_return: float
    excess_return: float
    spy_return: float | None
    qqq_return: float | None


def signal_day(started_at: str) -> str:
    """Convert an ISO UTC-ish timestamp to the market-local signal date."""
    dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(MARKET_TZ).date().isoformat()


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS daily_signals (
          signal_date TEXT NOT NULL,
          ticker TEXT NOT NULL,
          bull INTEGER NOT NULL,
          bear INTEGER NOT NULL,
          neutral INTEGER NOT NULL,
          context INTEGER NOT NULL,
          net_score INTEGER NOT NULL,
          mentions INTEGER NOT NULL,
          providers INTEGER NOT NULL,
          personas INTEGER NOT NULL,
          first_seen INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (signal_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS prices (
          ticker TEXT NOT NULL,
          date TEXT NOT NULL,
          open REAL,
          close REAL,
          adj_close REAL,
          volume INTEGER,
          source TEXT NOT NULL,
          PRIMARY KEY (ticker, date, source)
        );

        CREATE TABLE IF NOT EXISTS forward_returns (
          signal_date TEXT NOT NULL,
          ticker TEXT NOT NULL,
          horizon_days INTEGER NOT NULL,
          entry_date TEXT NOT NULL,
          exit_date TEXT NOT NULL,
          entry_price REAL NOT NULL,
          exit_price REAL NOT NULL,
          return_pct REAL NOT NULL,
          PRIMARY KEY (signal_date, ticker, horizon_days)
        );
        """
    )
    con.commit()


def clean_runs(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT id, started_at
        FROM runs
        WHERE is_clean = 1
          AND status IN ('completed', 'partial')
        ORDER BY started_at
        """
    ).fetchall()


def rebuild_daily_signals(con: sqlite3.Connection) -> None:
    con.execute("DELETE FROM daily_signals")

    first_seen: dict[str, str] = {}
    rows_by_day: dict[str, dict[str, dict[str, int | set[str]]]] = {}

    for run in clean_runs(con):
        day = signal_day(run["started_at"])
        run_rows = con.execute(
            """
            SELECT m.ticker,
                   m.sentiment_hint,
                   mc.provider,
                   r.persona_id
            FROM responses r
            JOIN mentions m ON m.response_id = r.id
            JOIN model_configs mc ON mc.id = r.model_config_id
            WHERE r.run_id = ?
              AND r.error IS NULL
              AND m.needs_review = 0
              AND m.sentiment_hint IN ('bullish', 'bearish', 'neutral', 'context')
            """,
            (run["id"],),
        ).fetchall()
        day_map = rows_by_day.setdefault(day, {})
        for row in run_rows:
            ticker = row["ticker"]
            first_seen.setdefault(ticker, day)
            rec = day_map.setdefault(
                ticker,
                {
                    "bull": 0,
                    "bear": 0,
                    "neutral": 0,
                    "context": 0,
                    "mentions": 0,
                    "providers": set(),
                    "personas": set(),
                },
            )
            stance = row["sentiment_hint"]
            if stance == "bullish":
                rec["bull"] += 1
            elif stance == "bearish":
                rec["bear"] += 1
            elif stance == "neutral":
                rec["neutral"] += 1
            elif stance == "context":
                rec["context"] += 1
            rec["mentions"] += 1
            rec["providers"].add(row["provider"])
            rec["personas"].add(row["persona_id"])

    for day, tickers in rows_by_day.items():
        for ticker, rec in tickers.items():
            bull = int(rec["bull"])
            bear = int(rec["bear"])
            con.execute(
                """
                INSERT INTO daily_signals (
                  signal_date, ticker, bull, bear, neutral, context,
                  net_score, mentions, providers, personas, first_seen
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    day,
                    ticker,
                    bull,
                    bear,
                    int(rec["neutral"]),
                    int(rec["context"]),
                    bull - bear,
                    int(rec["mentions"]),
                    len(rec["providers"]),
                    len(rec["personas"]),
                    1 if first_seen.get(ticker) == day else 0,
                ),
            )
    con.commit()


def yahoo_symbol(ticker: str) -> str:
    # Yahoo writes share classes as BRK-B while Pythia stores BRK.B.
    return ticker.replace(".", "-")


def fetch_price_history(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    yahoo_to_ticker = {yahoo_symbol(t): t for t in tickers}
    data = yf.download(
        tickers=list(yahoo_to_ticker),
        start=start.isoformat(),
        end=end.isoformat(),
        auto_adjust=False,
        group_by="ticker",
        progress=False,
        threads=True,
    )
    if data.empty:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    if isinstance(data.columns, pd.MultiIndex):
        for yf_ticker, ticker in yahoo_to_ticker.items():
            if yf_ticker not in data.columns.get_level_values(0):
                continue
            df = data[yf_ticker].copy()
            df["Ticker"] = ticker
            frames.append(df)
    else:
        df = data.copy()
        df["Ticker"] = tickers[0]
        frames.append(df)
    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames)
    out = out.reset_index().rename(columns={"Date": "date"})
    out["date"] = pd.to_datetime(out["date"]).dt.date.astype(str)
    return out


def cache_prices(con: sqlite3.Connection, tickers: list[str], start: date, end: date) -> None:
    tickers = [t for t in tickers if t not in YFINANCE_SKIP]
    stale_tickers: list[str] = []
    stale_start = start
    for ticker in tickers:
        row = con.execute(
            "SELECT MAX(date) AS max_date FROM prices WHERE ticker = ? AND source = 'yfinance'",
            (ticker,),
        ).fetchone()
        if not row or not row["max_date"]:
            stale_tickers.append(ticker)
            continue
        max_date = date.fromisoformat(row["max_date"])
        if max_date < end - timedelta(days=3):
            stale_tickers.append(ticker)
            stale_start = min(stale_start, max_date + timedelta(days=1))

    if not stale_tickers:
        return

    print(f"[benchmark] fetching prices for {len(stale_tickers)} ticker(s)")
    for i in range(0, len(stale_tickers), 100):
        batch = stale_tickers[i : i + 100]
        hist = fetch_price_history(batch, stale_start, end)
        for _, row in hist.iterrows():
            ticker = str(row["Ticker"]).upper()
            open_px = value_or_none(row.get("Open"))
            close_px = value_or_none(row.get("Close"))
            adj_close = value_or_none(row.get("Adj Close"))
            volume = value_or_none(row.get("Volume"))
            if open_px is None or close_px is None:
                continue
            con.execute(
                """
                INSERT OR REPLACE INTO prices
                  (ticker, date, open, close, adj_close, volume, source)
                VALUES (?, ?, ?, ?, ?, ?, 'yfinance')
                """,
                (
                    ticker,
                    row["date"],
                    open_px,
                    close_px,
                    adj_close,
                    int(volume) if volume is not None else None,
                ),
            )
        con.commit()


def value_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value) or math.isnan(float(value)):
            return None
    except TypeError:
        return None
    return float(value)


def next_trade_date(con: sqlite3.Connection, signal_date: str) -> str | None:
    row = con.execute(
        """
        SELECT MIN(date) AS trade_date
        FROM prices
        WHERE ticker = 'SPY'
          AND source = 'yfinance'
          AND date > ?
          AND open IS NOT NULL
          AND close IS NOT NULL
        """,
        (signal_date,),
    ).fetchone()
    return row["trade_date"] if row and row["trade_date"] else None


def day_return(con: sqlite3.Connection, ticker: str, trade_date: str) -> float | None:
    row = con.execute(
        """
        SELECT open, close
        FROM prices
        WHERE ticker = ?
          AND date = ?
          AND source = 'yfinance'
          AND open IS NOT NULL
          AND close IS NOT NULL
        """,
        (ticker, trade_date),
    ).fetchone()
    if not row or not row["open"]:
        return None
    return (float(row["close"]) / float(row["open"])) - 1.0


def compute_forward_returns(con: sqlite3.Connection) -> None:
    con.execute("DELETE FROM forward_returns WHERE horizon_days = 1")
    rows = con.execute(
        "SELECT DISTINCT signal_date, ticker FROM daily_signals ORDER BY signal_date, ticker"
    ).fetchall()
    for row in rows:
        trade_date = next_trade_date(con, row["signal_date"])
        if not trade_date:
            continue
        price = con.execute(
            """
            SELECT open, close
            FROM prices
            WHERE ticker = ? AND date = ? AND source = 'yfinance'
            """,
            (row["ticker"], trade_date),
        ).fetchone()
        if not price or not price["open"] or not price["close"]:
            continue
        ret = (float(price["close"]) / float(price["open"])) - 1.0
        con.execute(
            """
            INSERT OR REPLACE INTO forward_returns (
              signal_date, ticker, horizon_days, entry_date, exit_date,
              entry_price, exit_price, return_pct
            )
            VALUES (?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (
                row["signal_date"],
                row["ticker"],
                trade_date,
                trade_date,
                float(price["open"]),
                float(price["close"]),
                ret,
            ),
        )
    con.commit()


def basket_average(returns: list[float]) -> float | None:
    if not returns:
        return None
    return sum(returns) / len(returns)


def benchmark_results(con: sqlite3.Connection, top_n: int) -> list[DayResult]:
    results: list[DayResult] = []
    days = [
        r["signal_date"]
        for r in con.execute(
            "SELECT DISTINCT signal_date FROM daily_signals ORDER BY signal_date"
        ).fetchall()
    ]
    for day in days:
        trade_date = next_trade_date(con, day)
        if not trade_date:
            continue
        ranked = con.execute(
            """
            SELECT ticker, net_score, mentions
            FROM daily_signals
            WHERE signal_date = ?
            ORDER BY net_score DESC, mentions DESC, ticker
            """,
            (day,),
        ).fetchall()
        if not ranked:
            continue

        top_tickers = [r["ticker"] for r in ranked[:top_n]]
        all_tickers = [r["ticker"] for r in ranked]
        top_returns = [r for t in top_tickers if (r := day_return(con, t, trade_date)) is not None]
        all_returns = [r for t in all_tickers if (r := day_return(con, t, trade_date)) is not None]
        top_avg = basket_average(top_returns)
        all_avg = basket_average(all_returns)
        if top_avg is None or all_avg is None:
            continue
        results.append(
            DayResult(
                signal_date=day,
                trade_date=trade_date,
                top_n=top_n,
                top_available=len(top_returns),
                all_available=len(all_returns),
                top_return=top_avg,
                all_return=all_avg,
                excess_return=top_avg - all_avg,
                spy_return=day_return(con, "SPY", trade_date),
                qqq_return=day_return(con, "QQQ", trade_date),
            )
        )
    return results


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:>7.2f}%"


def print_results(results: list[DayResult]) -> None:
    if not results:
        print("[benchmark] no benchmarkable days yet")
        return

    print()
    print(
        "signal_date  trade_date   top_avail  all_avail  "
        "top20_1d  all_1d   excess   SPY      QQQ"
    )
    for r in results:
        print(
            f"{r.signal_date}  {r.trade_date}  "
            f"{r.top_available:>9}  {r.all_available:>9}  "
            f"{pct(r.top_return)} {pct(r.all_return)} {pct(r.excess_return)} "
            f"{pct(r.spy_return)} {pct(r.qqq_return)}"
        )

    top_avg = basket_average([r.top_return for r in results])
    all_avg = basket_average([r.all_return for r in results])
    excess_avg = basket_average([r.excess_return for r in results])
    spy_avg = basket_average([r.spy_return for r in results if r.spy_return is not None])
    qqq_avg = basket_average([r.qqq_return for r in results if r.qqq_return is not None])

    print()
    print(
        f"running average over {len(results)} day(s): "
        f"top20={pct(top_avg).strip()}  "
        f"all-mentioned={pct(all_avg).strip()}  "
        f"excess={pct(excess_avg).strip()}  "
        f"SPY={pct(spy_avg).strip()}  "
        f"QQQ={pct(qqq_avg).strip()}"
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-n", type=int, default=20)
    ap.add_argument(
        "--rebuild-signals",
        action="store_true",
        help="Rebuild daily_signals before benchmarking.",
    )
    ap.add_argument(
        "--price-start",
        default=None,
        help="Override yfinance start date, YYYY-MM-DD. Defaults to first signal date.",
    )
    ap.add_argument(
        "--price-end",
        default=None,
        help="Override yfinance exclusive end date, YYYY-MM-DD. Defaults to tomorrow.",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if not DB_PATH.exists():
        print(f"db missing: {DB_PATH}", file=sys.stderr)
        return 1

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    ensure_schema(con)

    if args.rebuild_signals or not con.execute("SELECT 1 FROM daily_signals LIMIT 1").fetchone():
        print("[benchmark] rebuilding daily_signals")
        rebuild_daily_signals(con)

    bounds = con.execute(
        "SELECT MIN(signal_date) AS first_day, MAX(signal_date) AS last_day FROM daily_signals"
    ).fetchone()
    if not bounds or not bounds["first_day"]:
        print("[benchmark] no daily signals found")
        return 0

    tickers = [
        r["ticker"]
        for r in con.execute(
            "SELECT DISTINCT ticker FROM daily_signals UNION SELECT 'SPY' UNION SELECT 'QQQ'"
        ).fetchall()
    ]
    start = (
        date.fromisoformat(args.price_start)
        if args.price_start
        else date.fromisoformat(bounds["first_day"])
    )
    end = date.fromisoformat(args.price_end) if args.price_end else date.today() + timedelta(days=2)
    cache_prices(con, sorted(tickers), start, end)
    compute_forward_returns(con)
    print_results(benchmark_results(con, args.top_n))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
