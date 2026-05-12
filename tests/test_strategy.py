import unittest
from datetime import UTC, datetime, timedelta

from src.data import Candle
from src.strategy import BUY, HOLD, SELL, MovingAverageCrossover, PullbackInUptrend, RangeBreakoutInTrend, RsiTrendBounce


def make_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Candle(
            timestamp=start + timedelta(days=index),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=10.0,
        )
        for index, close in enumerate(closes)
    ]


class MovingAverageCrossoverTest(unittest.TestCase):
    def test_buy_signal_after_fast_average_crosses_above_slow(self):
        candles = make_candles([10, 10, 10, 10, 10, 20])
        strategy = MovingAverageCrossover(fast_window=2, slow_window=5)

        signal, reason = strategy.signal_at(candles, index=5)

        self.assertEqual(signal, BUY)
        self.assertIn("crossed above", reason)

    def test_sell_signal_after_fast_average_crosses_below_slow(self):
        candles = make_candles([20, 20, 20, 20, 20, 10])
        strategy = MovingAverageCrossover(fast_window=2, slow_window=5)

        signal, reason = strategy.signal_at(candles, index=5)

        self.assertEqual(signal, SELL)
        self.assertIn("crossed below", reason)


class PullbackInUptrendTest(unittest.TestCase):
    def test_buy_signal_after_pullback_recovers_in_rising_trend(self):
        candles = make_candles([100, 102, 104, 101, 100, 105])
        strategy = PullbackInUptrend(fast_window=2, trend_window=4, pullback_window=3, min_pullback_pct=0.02)

        signal, reason = strategy.signal_at(candles, index=5)

        self.assertEqual(signal, BUY)
        self.assertIn("pullback recovered", reason)

    def test_sell_signal_when_price_loses_trend(self):
        candles = make_candles([100, 102, 104, 106, 105, 102])
        strategy = PullbackInUptrend(fast_window=2, trend_window=4, pullback_window=3, min_pullback_pct=0.02)

        signal, reason = strategy.signal_at(candles, index=5)

        self.assertEqual(signal, SELL)
        self.assertIn("price below trend", reason)


class RangeBreakoutInTrendTest(unittest.TestCase):
    def test_buy_signal_after_range_breakout_in_rising_trend(self):
        candles = make_candles([100, 101, 102, 103, 104, 103, 104, 106])
        candles[-1] = Candle(
            timestamp=candles[-1].timestamp,
            open=candles[-1].open,
            high=candles[-1].high,
            low=candles[-1].low,
            close=candles[-1].close,
            volume=30.0,
        )
        strategy = RangeBreakoutInTrend(
            fast_window=2,
            trend_window=4,
            breakout_window=3,
            breakout_buffer_pct=0.0,
            volume_window=3,
            min_volume_ratio=1.2,
        )

        signal, reason = strategy.signal_at(candles, index=7)

        self.assertEqual(signal, BUY)
        self.assertIn("volume-confirmed breakout", reason)

    def test_sell_signal_when_breakout_loses_fast_average(self):
        candles = make_candles([100, 102, 104, 106, 108, 106])
        strategy = RangeBreakoutInTrend(
            fast_window=2,
            trend_window=4,
            breakout_window=3,
            breakout_buffer_pct=0.0,
            volume_window=3,
            min_volume_ratio=1.2,
        )

        signal, reason = strategy.signal_at(candles, index=5)

        self.assertEqual(signal, SELL)
        self.assertIn("price lost fast", reason)

    def test_blocks_breakout_without_volume_confirmation(self):
        candles = make_candles([100, 101, 102, 103, 104, 103, 104, 106])
        strategy = RangeBreakoutInTrend(
            fast_window=2,
            trend_window=4,
            breakout_window=3,
            breakout_buffer_pct=0.0,
            volume_window=3,
            min_volume_ratio=2.0,
        )

        signal, reason = strategy.signal_at(candles, index=7)

        self.assertEqual(signal, HOLD)
        self.assertIn("without enough volume", reason)


class RsiTrendBounceTest(unittest.TestCase):
    def test_buy_signal_after_rsi_rebounds_above_trend(self):
        candles = make_candles([100, 101, 102, 103, 104, 102, 101, 103])
        strategy = RsiTrendBounce(trend_window=4, buy_rsi=45.0, sell_rsi=70.0, rsi_window=3)

        signal, reason = strategy.signal_at(candles, index=7)

        self.assertEqual(signal, BUY)
        self.assertIn("RSI rebound", reason)

    def test_sell_signal_when_rebound_gets_hot(self):
        candles = make_candles([100, 101, 102, 103, 104, 105])
        strategy = RsiTrendBounce(trend_window=4, buy_rsi=45.0, sell_rsi=70.0, rsi_window=3)

        signal, reason = strategy.signal_at(candles, index=5)

        self.assertEqual(signal, SELL)
        self.assertIn("RSI rebound reached", reason)


if __name__ == "__main__":
    unittest.main()
