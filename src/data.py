"""Market data loading for the educational simulator.

This module only uses public market data. It does not connect to an account,
does not require API keys, and cannot place orders.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


BINANCE_PUBLIC_API = "https://api.binance.com/api/v3/klines"
BINANCE_MAX_LIMIT = 1000


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def _fetch_binance_batch(symbol: str, interval: str, limit: int, end_time_ms: int | None = None) -> list[list]:
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    if end_time_ms is not None:
        params["endTime"] = end_time_ms
    url = f"{BINANCE_PUBLIC_API}?{urlencode(params)}"

    with urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _row_to_candle(row: list) -> Candle:
    return Candle(
        timestamp=datetime.fromtimestamp(row[0] / 1000, tz=UTC),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
    )


def fetch_binance_klines(symbol: str = "BTCUSDT", interval: str = "1d", limit: int = 365) -> list[Candle]:
    """Fetch public Binance candles without authentication."""
    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    rows_by_open_time: dict[int, list] = {}
    remaining = limit
    end_time_ms: int | None = None

    while remaining > 0:
        batch_limit = min(remaining, BINANCE_MAX_LIMIT)
        payload = _fetch_binance_batch(
            symbol=symbol,
            interval=interval,
            limit=batch_limit,
            end_time_ms=end_time_ms,
        )
        if not payload:
            break

        for row in payload:
            rows_by_open_time[int(row[0])] = row

        first_open_time = int(payload[0][0])
        end_time_ms = first_open_time - 1
        remaining -= len(payload)

        if len(payload) < batch_limit:
            break

    rows = [rows_by_open_time[key] for key in sorted(rows_by_open_time)]
    candles: list[Candle] = []
    for row in rows[-limit:]:
        candles.append(_row_to_candle(row))
    return candles


def read_csv(path: Path) -> list[Candle]:
    candles: list[Candle] = []
    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            candles.append(
                Candle(
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
    return candles


def write_csv(path: Path, candles: list[Candle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        fieldnames = ["timestamp", "open", "high", "low", "close", "volume"]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for candle in candles:
            writer.writerow(
                {
                    "timestamp": candle.timestamp.isoformat(),
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                }
            )


def load_or_fetch(
    symbol: str = "BTCUSDT",
    interval: str = "1d",
    limit: int = 365,
    cache_dir: Path | str = "data",
) -> list[Candle]:
    """Load cached candles or fetch public candles and cache them."""
    cache_path = Path(cache_dir) / f"{symbol.upper()}_{interval}_{limit}.csv"
    if cache_path.exists():
        return read_csv(cache_path)

    candles = fetch_binance_klines(symbol=symbol, interval=interval, limit=limit)
    write_csv(cache_path, candles)
    return candles
