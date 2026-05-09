"""Persistent storage for paper trading state.

The simulator still works with local JSON files. When DATABASE_URL is present,
it also stores the same paper state in Postgres/Supabase so Render restarts do
not erase the fictitious wallet.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


class StateStoreError(RuntimeError):
    """Raised when the configured persistent store cannot be used."""


_SCHEMA_LOCK = threading.Lock()


def parse_market_time(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        normalized = text.replace(" UTC", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def trade_id_for(state: dict[str, Any], trade: dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(state.get("preset", "")),
            str(state.get("symbol", "")),
            str(state.get("interval", "")),
            str(trade.get("entry_time", "")),
            str(trade.get("exit_time", "")),
            str(trade.get("entry_price", "")),
            str(trade.get("exit_price", "")),
            str(trade.get("quantity", "")),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_trade_record(state: dict[str, Any], trade: dict[str, Any]) -> tuple[Any, ...]:
    return (
        trade_id_for(state, trade),
        state["preset"],
        state["symbol"],
        state["interval"],
        str(trade.get("entry_time", "")),
        parse_market_time(trade.get("entry_time")),
        str(trade.get("exit_time", "")),
        parse_market_time(trade.get("exit_time")),
        float(trade.get("entry_price") or 0.0),
        float(trade.get("exit_price") or 0.0),
        float(trade.get("quantity") or 0.0),
        str(trade.get("entry_reason", "")),
        str(trade.get("exit_reason", "")),
        float(trade.get("pnl") or 0.0),
        float(trade.get("return_pct") or 0.0),
    )


def build_equity_record(state: dict[str, Any], point: dict[str, Any]) -> tuple[Any, ...]:
    candle_time = str(point.get("date", ""))
    return (
        state["preset"],
        candle_time,
        parse_market_time(candle_time),
        state["symbol"],
        state["interval"],
        float(point.get("close") or 0.0),
        float(point.get("equity") or 0.0),
        float(point.get("cash") or 0.0),
        float(point.get("position_value") or 0.0),
        float(point.get("drawdown_pct") or 0.0),
    )


def latest_equity(state: dict[str, Any]) -> float:
    equity_curve = state.get("equity_curve") or []
    if equity_curve:
        return float(equity_curve[-1].get("equity") or 0.0)
    return float(state.get("cash") or 0.0)


@dataclass
class PostgresStateStore:
    database_url: str
    _schema_ready: bool = False

    def _connect(self):
        try:
            import psycopg
        except ImportError as error:
            raise StateStoreError("psycopg is required when DATABASE_URL is configured") from error

        return psycopg.connect(self.database_url)

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return

        with _SCHEMA_LOCK:
            if self._schema_ready:
                return

            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        create table if not exists paper_states (
                            preset text primary key,
                            symbol text not null,
                            interval text not null,
                            state jsonb not null,
                            updated_at timestamptz not null default now()
                        )
                        """
                    )
                    cursor.execute(
                        """
                        create table if not exists paper_runs (
                            id bigint generated always as identity primary key,
                            preset text not null,
                            symbol text not null,
                            interval text not null,
                            checked_at timestamptz not null default now(),
                            state_updated_at timestamptz,
                            last_processed_candle text,
                            last_processed_at timestamptz,
                            latest_candle text,
                            latest_candle_at timestamptz,
                            processed_count integer,
                            last_action text not null,
                            equity numeric,
                            cash numeric,
                            position_qty numeric,
                            open_position boolean not null,
                            trades_count integer not null
                        )
                        """
                    )
                    cursor.execute(
                        """
                        create table if not exists paper_trades (
                            trade_id text primary key,
                            preset text not null,
                            symbol text not null,
                            interval text not null,
                            entry_time text not null,
                            entry_at timestamptz,
                            exit_time text not null,
                            exit_at timestamptz,
                            entry_price numeric not null,
                            exit_price numeric not null,
                            quantity numeric not null,
                            entry_reason text,
                            exit_reason text,
                            pnl numeric not null,
                            return_pct numeric not null,
                            updated_at timestamptz not null default now()
                        )
                        """
                    )
                    cursor.execute(
                        """
                        create table if not exists paper_equity_points (
                            preset text not null,
                            candle_time text not null,
                            candle_at timestamptz,
                            symbol text not null,
                            interval text not null,
                            close_price numeric not null,
                            equity numeric not null,
                            cash numeric not null,
                            position_value numeric not null,
                            drawdown_pct numeric not null,
                            updated_at timestamptz not null default now(),
                            primary key (preset, candle_time)
                        )
                        """
                    )
                    cursor.execute(
                        "create index if not exists paper_runs_preset_checked_idx on paper_runs (preset, checked_at desc)"
                    )
                    cursor.execute(
                        "create index if not exists paper_trades_preset_exit_idx on paper_trades (preset, exit_at desc)"
                    )
                    cursor.execute(
                        "create index if not exists paper_equity_points_preset_candle_idx on paper_equity_points (preset, candle_at desc)"
                    )
            self._schema_ready = True

    def load(self, preset: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select state from paper_states where preset = %s", (preset,))
                row = cursor.fetchone()
        if row is None:
            return None
        state = row[0]
        if isinstance(state, str):
            return json.loads(state)
        return dict(state)

    def save(self, state: dict[str, Any], run_context: dict[str, Any] | None = None) -> None:
        self.ensure_schema()
        payload = json.dumps(state)
        run_context = run_context or {}
        trade_records = [build_trade_record(state, trade) for trade in state.get("trades", [])]
        equity_records = [build_equity_record(state, point) for point in state.get("equity_curve", [])]
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into paper_states (preset, symbol, interval, state, updated_at)
                    values (%s, %s, %s, %s::jsonb, now())
                    on conflict (preset) do update set
                        symbol = excluded.symbol,
                        interval = excluded.interval,
                        state = excluded.state,
                        updated_at = now()
                    """,
                    (state["preset"], state["symbol"], state["interval"], payload),
                )
                cursor.execute(
                    """
                    insert into paper_runs (
                        preset,
                        symbol,
                        interval,
                        state_updated_at,
                        last_processed_candle,
                        last_processed_at,
                        latest_candle,
                        latest_candle_at,
                        processed_count,
                        last_action,
                        equity,
                        cash,
                        position_qty,
                        open_position,
                        trades_count
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        state["preset"],
                        state["symbol"],
                        state["interval"],
                        parse_market_time(state.get("updated_at")),
                        str(state.get("last_processed_candle") or ""),
                        parse_market_time(state.get("last_processed_candle")),
                        str(run_context.get("latest_candle") or ""),
                        parse_market_time(run_context.get("latest_candle")),
                        run_context.get("processed_count"),
                        str(state.get("last_action") or "HOLD"),
                        latest_equity(state),
                        float(state.get("cash") or 0.0),
                        float(state.get("position_qty") or 0.0),
                        bool(float(state.get("position_qty") or 0.0) > 0),
                        len(state.get("trades") or []),
                    ),
                )
                if trade_records:
                    cursor.executemany(
                        """
                        insert into paper_trades (
                            trade_id,
                            preset,
                            symbol,
                            interval,
                            entry_time,
                            entry_at,
                            exit_time,
                            exit_at,
                            entry_price,
                            exit_price,
                            quantity,
                            entry_reason,
                            exit_reason,
                            pnl,
                            return_pct
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        on conflict (trade_id) do update set
                            preset = excluded.preset,
                            symbol = excluded.symbol,
                            interval = excluded.interval,
                            entry_time = excluded.entry_time,
                            entry_at = excluded.entry_at,
                            exit_time = excluded.exit_time,
                            exit_at = excluded.exit_at,
                            entry_price = excluded.entry_price,
                            exit_price = excluded.exit_price,
                            quantity = excluded.quantity,
                            entry_reason = excluded.entry_reason,
                            exit_reason = excluded.exit_reason,
                            pnl = excluded.pnl,
                            return_pct = excluded.return_pct,
                            updated_at = now()
                        """,
                        trade_records,
                    )
                if equity_records:
                    cursor.executemany(
                        """
                        insert into paper_equity_points (
                            preset,
                            candle_time,
                            candle_at,
                            symbol,
                            interval,
                            close_price,
                            equity,
                            cash,
                            position_value,
                            drawdown_pct
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        on conflict (preset, candle_time) do update set
                            candle_at = excluded.candle_at,
                            symbol = excluded.symbol,
                            interval = excluded.interval,
                            close_price = excluded.close_price,
                            equity = excluded.equity,
                            cash = excluded.cash,
                            position_value = excluded.position_value,
                            drawdown_pct = excluded.drawdown_pct,
                            updated_at = now()
                        """,
                        equity_records,
                    )


_STORE: PostgresStateStore | None = None


def state_store_from_env() -> PostgresStateStore | None:
    """Return a persistent store when DATABASE_URL is configured."""

    global _STORE
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return None

    if _STORE is None or _STORE.database_url != database_url:
        _STORE = PostgresStateStore(database_url=database_url)
    return _STORE
