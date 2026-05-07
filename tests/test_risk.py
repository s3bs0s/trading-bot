import unittest
from datetime import UTC, datetime, timedelta

from src.data import Candle
from src.risk import RiskConfig, RiskManager, RiskState, relative_strength_index


def candle(day: int, close: float) -> Candle:
    timestamp = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=day)
    return Candle(timestamp=timestamp, open=close, high=close, low=close, close=close, volume=1.0)


class RiskManagerTest(unittest.TestCase):
    def test_blocks_entry_after_large_recent_drop(self):
        candles = [candle(index, close) for index, close in enumerate([100, 99, 98, 97, 96, 95, 94, 82])]
        manager = RiskManager(RiskConfig(crash_lookback_bars=7, crash_block_pct=0.12, require_rsi_confirmation=False))
        state = RiskState(peak_equity=1000)

        reason = manager.entry_block_reason(candles, index=7, state=state)

        self.assertIsNotNone(reason)
        self.assertIn("market dropped", reason)

    def test_exit_reason_uses_stop_loss(self):
        manager = RiskManager(RiskConfig(stop_loss_pct=0.03))

        reason = manager.exit_reason(entry_price=100, current_price=96)

        self.assertIsNotNone(reason)
        self.assertIn("stop loss", reason)

    def test_exit_reason_uses_trailing_stop_after_activation(self):
        manager = RiskManager(RiskConfig(trailing_stop_pct=0.01, trailing_activation_pct=0.02))

        reason = manager.exit_reason(entry_price=100, current_price=108, highest_price=110)

        self.assertIsNotNone(reason)
        self.assertIn("trailing stop", reason)

    def test_trailing_stop_waits_for_activation_gain(self):
        manager = RiskManager(RiskConfig(trailing_stop_pct=0.01, trailing_activation_pct=0.02, take_profit_pct=0.10))

        reason = manager.exit_reason(entry_price=100, current_price=100, highest_price=101)

        self.assertIsNone(reason)

    def test_blocks_entry_below_trend_average(self):
        candles = [candle(index, close) for index, close in enumerate([100, 100, 100, 100, 80])]
        manager = RiskManager(RiskConfig(trend_filter_window=5, require_price_above_trend=True, require_rsi_confirmation=False))
        state = RiskState(peak_equity=1000)

        reason = manager.entry_block_reason(candles, index=4, state=state)

        self.assertEqual(reason, "price below 5-candle trend average")

    def test_blocks_entry_when_rsi_is_too_weak(self):
        candles = [candle(index, close) for index, close in enumerate([100, 99, 98, 97, 96, 95])]
        manager = RiskManager(
            RiskConfig(
                require_price_above_trend=False,
                require_rsi_confirmation=True,
                rsi_window=5,
                rsi_min=50,
            )
        )
        state = RiskState(peak_equity=1000)

        reason = manager.entry_block_reason(candles, index=5, state=state)

        self.assertIsNotNone(reason)
        self.assertIn("RSI too weak", reason)

    def test_loss_streak_can_trigger_temporary_cooldown(self):
        candles = [candle(index, close) for index, close in enumerate([100, 101, 102, 103, 104])]
        manager = RiskManager(
            RiskConfig(
                max_consecutive_losses=3,
                loss_streak_cooldown_bars=5,
                require_price_above_trend=False,
                require_rsi_confirmation=False,
            )
        )
        state = RiskState(peak_equity=1000, consecutive_losses=3)

        reason = manager.entry_block_reason(candles, index=4, state=state)

        self.assertIn("loss streak cooldown", reason or "")
        self.assertFalse(state.paused)
        self.assertEqual(state.consecutive_losses, 0)
        self.assertEqual(state.cooldown_until_index, 9)
        self.assertEqual(len(state.risk_events), 1)

    def test_loss_streak_hard_pauses_by_default(self):
        candles = [candle(index, close) for index, close in enumerate([100, 101, 102, 103, 104])]
        manager = RiskManager(
            RiskConfig(
                max_consecutive_losses=3,
                require_price_above_trend=False,
                require_rsi_confirmation=False,
            )
        )
        state = RiskState(peak_equity=1000, consecutive_losses=3)

        reason = manager.entry_block_reason(candles, index=4, state=state)

        self.assertEqual(reason, "too many consecutive losses")
        self.assertTrue(state.paused)

    def test_relative_strength_index_returns_high_value_for_gains(self):
        candles = [candle(index, close) for index, close in enumerate([100, 101, 102, 103, 104, 105])]

        rsi = relative_strength_index(candles, index=5, window=5)

        self.assertEqual(rsi, 100.0)


if __name__ == "__main__":
    unittest.main()
