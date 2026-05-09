"""Persistent storage for paper trading state.

The simulator still works with local JSON files. When DATABASE_URL is present,
it also stores the same paper state in Postgres/Supabase so Render restarts do
not erase the fictitious wallet.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


class StateStoreError(RuntimeError):
    """Raised when the configured persistent store cannot be used."""


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

    def save(self, state: dict[str, Any]) -> None:
        self.ensure_schema()
        payload = json.dumps(state)
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
