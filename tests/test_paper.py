import unittest
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.data import Candle
from src.paper import (
    PaperPreset,
    PaperState,
    build_preset,
    display_time_text,
    load_state,
    process_candles,
    save_state,
    write_paper_report,
)
from src.risk import RiskConfig
from src.strategy import BUY, HOLD, SELL


def make_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Candle(
            timestamp=start + timedelta(hours=index * 2),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=100.0,
        )
        for index, close in enumerate(closes)
    ]


class ScheduledStrategy:
    def __init__(self, signals: dict[int, tuple[str, str]]):
        self.signals = signals

    def signal_at(self, candles: list[Candle], index: int) -> tuple[str, str]:
        return self.signals.get(index, (HOLD, "scheduled hold"))


class MemoryStore:
    def __init__(self):
        self.states = {}

    def load(self, preset: str):
        return self.states.get(preset)

    def save(self, state: dict, run_context=None):
        self.states[state["preset"]] = dict(state)


def make_preset(strategy: ScheduledStrategy) -> PaperPreset:
    return PaperPreset(
        name="test-paper",
        symbol="TESTUSDT",
        interval="2h",
        strategy_label="scheduled test strategy",
        strategy=strategy,
        risk_config=RiskConfig(
            stop_loss_pct=0.99,
            take_profit_pct=0.99,
            max_drawdown_pct=0.99,
            max_consecutive_losses=99,
            require_price_above_trend=False,
            require_rsi_confirmation=False,
            crash_block_pct=0.99,
            cooldown_bars_after_loss=0,
            position_size_pct=1.0,
        ),
        lookback_candles=10,
    )


def make_state() -> PaperState:
    return PaperState(
        version=1,
        mode="paper",
        symbol="TESTUSDT",
        interval="2h",
        preset="test-paper",
        strategy_label="scheduled test strategy",
        initial_cash=1000.0,
        fee_rate=0.0,
        cash=1000.0,
        peak_equity=1000.0,
    )


class PaperTradingTest(unittest.TestCase):
    def test_display_time_text_shows_colombia_time(self):
        text = display_time_text("2026-05-08 14:00:00 UTC")

        self.assertIn("2026-05-08 09:00:00 AM Colombia", text)

    def test_experimental_one_minute_preset_uses_60_second_candles(self):
        preset = build_preset("experimental-eth-1m")

        self.assertEqual(preset.symbol, "ETHUSDT")
        self.assertEqual(preset.interval, "1m")
        self.assertGreaterEqual(preset.lookback_candles, 120)

    def test_active_one_hour_preset_uses_more_frequent_eth_candles(self):
        preset = build_preset("active-eth-1h")

        self.assertEqual(preset.symbol, "ETHUSDT")
        self.assertEqual(preset.interval, "1h")
        self.assertGreaterEqual(preset.lookback_candles, 240)

    def test_aggressive_thirty_minute_preset_uses_fast_eth_candles(self):
        preset = build_preset("aggressive-eth-30m")

        self.assertEqual(preset.symbol, "ETHUSDT")
        self.assertEqual(preset.interval, "30m")
        self.assertGreaterEqual(preset.lookback_candles, 480)

    def test_first_live_run_processes_only_latest_closed_candle(self):
        candles = make_candles([100.0, 101.0, 102.0])
        state = make_state()
        preset = make_preset(ScheduledStrategy({0: (BUY, "old buy"), 2: (BUY, "latest buy")}))

        processed = process_candles(state, preset=preset, candles=candles, bootstrap_history=0)

        self.assertEqual(processed, 1)
        self.assertEqual(state.entry_reason, "latest buy")
        self.assertEqual(len(state.equity_curve), 1)

        processed_again = process_candles(state, preset=preset, candles=candles, bootstrap_history=0)

        self.assertEqual(processed_again, 0)
        self.assertEqual(len(state.equity_curve), 1)

    def test_bootstrap_can_create_closed_fictitious_trade_for_demo_reports(self):
        candles = make_candles([100.0, 101.0, 102.0])
        state = make_state()
        preset = make_preset(ScheduledStrategy({0: (BUY, "demo buy"), 2: (SELL, "demo sell")}))

        processed = process_candles(state, preset=preset, candles=candles, bootstrap_history=3)

        self.assertEqual(processed, 3)
        self.assertEqual(len(state.trades), 1)
        self.assertEqual(state.position_qty, 0.0)
        self.assertAlmostEqual(state.cash, 1020.0)
        self.assertAlmostEqual(float(state.trades[0]["pnl"]), 20.0)

    def test_report_shows_recent_market_context_before_first_trade(self):
        candles = make_candles([100.0, 101.0, 102.0, 103.0])
        state = make_state()
        state.updated_at = "2026-05-07 15:00:00 UTC"

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            state_file = output_dir / "paper_state.json"
            html_path, _csv_path = write_paper_report(
                state,
                output_dir=output_dir,
                processed_count=0,
                latest_candle=candles[-1],
                state_file=state_file,
                market_candles=candles,
            )
            html = html_path.read_text(encoding="utf-8")

        self.assertIn("Precio reciente del mercado", html)
        self.assertIn("Velas contexto: 4", html)
        self.assertIn("103.00", html)

    def test_state_store_can_restore_state_when_local_file_is_missing(self):
        preset = make_preset(ScheduledStrategy({}))
        store = MemoryStore()
        state = make_state()
        state.cash = 950.0

        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "missing.json"
            save_state(state_path, state, store=store)
            state_path.unlink()

            restored = load_state(state_path, preset=preset, initial_cash=1000.0, fee_rate=0.0, store=store)

        self.assertEqual(restored.cash, 950.0)
        self.assertEqual(restored.preset, "test-paper")


if __name__ == "__main__":
    unittest.main()
