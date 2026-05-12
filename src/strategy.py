"""Trading signals for the educational simulator."""

from __future__ import annotations

from dataclasses import dataclass

from src.data import Candle
from src.risk import relative_strength_index


BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


def simple_moving_average(values: list[float], window: int) -> float | None:
    if window <= 0:
        raise ValueError("window must be greater than zero")
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


@dataclass(frozen=True)
class MovingAverageCrossover:
    fast_window: int = 20
    slow_window: int = 50

    def __post_init__(self) -> None:
        if self.fast_window <= 0 or self.slow_window <= 0:
            raise ValueError("moving average windows must be greater than zero")
        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window must be smaller than slow_window")

    def signal_at(self, candles: list[Candle], index: int) -> tuple[str, str]:
        """Return a signal and a human-readable reason."""
        if index <= 0 or index >= len(candles):
            return HOLD, "not enough candles"

        closes_now = [candle.close for candle in candles[: index + 1]]
        closes_prev = [candle.close for candle in candles[:index]]

        fast_now = simple_moving_average(closes_now, self.fast_window)
        slow_now = simple_moving_average(closes_now, self.slow_window)
        fast_prev = simple_moving_average(closes_prev, self.fast_window)
        slow_prev = simple_moving_average(closes_prev, self.slow_window)

        if None in (fast_now, slow_now, fast_prev, slow_prev):
            return HOLD, "waiting for enough moving average data"

        if fast_prev <= slow_prev and fast_now > slow_now:
            return BUY, f"fast MA {self.fast_window} crossed above slow MA {self.slow_window}"

        if fast_prev >= slow_prev and fast_now < slow_now:
            return SELL, f"fast MA {self.fast_window} crossed below slow MA {self.slow_window}"

        return HOLD, "no crossover"


@dataclass(frozen=True)
class PullbackInUptrend:
    fast_window: int = 20
    trend_window: int = 100
    pullback_window: int = 12
    min_pullback_pct: float = 0.015

    def __post_init__(self) -> None:
        if self.fast_window <= 0 or self.trend_window <= 0 or self.pullback_window <= 0:
            raise ValueError("strategy windows must be greater than zero")
        if self.fast_window >= self.trend_window:
            raise ValueError("fast_window must be smaller than trend_window")
        if self.min_pullback_pct < 0:
            raise ValueError("min_pullback_pct cannot be negative")

    def signal_at(self, candles: list[Candle], index: int) -> tuple[str, str]:
        """Buy pullbacks only when the broader trend is still rising."""
        needed = max(self.trend_window + 1, self.fast_window + 1, self.pullback_window)
        if index <= 0 or len(candles[: index + 1]) < needed:
            return HOLD, "waiting for enough pullback strategy data"

        closes_now = [candle.close for candle in candles[: index + 1]]
        closes_prev = [candle.close for candle in candles[:index]]

        fast_now = simple_moving_average(closes_now, self.fast_window)
        fast_prev = simple_moving_average(closes_prev, self.fast_window)
        trend_now = simple_moving_average(closes_now, self.trend_window)
        trend_prev = simple_moving_average(closes_prev, self.trend_window)

        if None in (fast_now, fast_prev, trend_now, trend_prev):
            return HOLD, "waiting for enough pullback strategy data"

        current_close = candles[index].close
        previous_close = candles[index - 1].close

        if current_close < trend_now:
            return SELL, f"price below trend MA {self.trend_window}"

        if previous_close >= fast_prev and current_close < fast_now:
            return SELL, f"price lost fast MA {self.fast_window}"

        trend_is_rising = trend_now > trend_prev
        price_above_trend = current_close > trend_now
        recent_candles = candles[index + 1 - self.pullback_window : index + 1]
        recent_high = max(candle.high for candle in recent_candles)
        recent_low = min(candle.low for candle in recent_candles)
        pullback_depth = (recent_high - recent_low) / recent_high if recent_high else 0.0
        recovered_fast_ma = previous_close <= fast_prev and current_close > fast_now

        if trend_is_rising and price_above_trend and pullback_depth >= self.min_pullback_pct and recovered_fast_ma:
            return (
                BUY,
                f"pullback recovered above fast MA {self.fast_window} in rising trend MA {self.trend_window}",
            )

        return HOLD, "no pullback recovery"


@dataclass(frozen=True)
class RangeBreakoutInTrend:
    fast_window: int = 10
    trend_window: int = 50
    breakout_window: int = 12
    breakout_buffer_pct: float = 0.001
    volume_window: int = 20
    min_volume_ratio: float = 1.2

    def __post_init__(self) -> None:
        if self.fast_window <= 0 or self.trend_window <= 0 or self.breakout_window <= 0 or self.volume_window <= 0:
            raise ValueError("strategy windows must be greater than zero")
        if self.fast_window >= self.trend_window:
            raise ValueError("fast_window must be smaller than trend_window")
        if self.breakout_buffer_pct < 0:
            raise ValueError("breakout_buffer_pct cannot be negative")
        if self.min_volume_ratio <= 0:
            raise ValueError("min_volume_ratio must be greater than zero")

    def signal_at(self, candles: list[Candle], index: int) -> tuple[str, str]:
        """Buy when price breaks a recent range while the broader trend is rising."""
        needed = max(self.trend_window + 1, self.fast_window + 1, self.breakout_window + 1, self.volume_window + 1)
        if index <= 0 or len(candles[: index + 1]) < needed:
            return HOLD, "waiting for enough breakout strategy data"

        closes_now = [candle.close for candle in candles[: index + 1]]
        closes_prev = [candle.close for candle in candles[:index]]

        fast_now = simple_moving_average(closes_now, self.fast_window)
        fast_prev = simple_moving_average(closes_prev, self.fast_window)
        trend_now = simple_moving_average(closes_now, self.trend_window)
        trend_prev = simple_moving_average(closes_prev, self.trend_window)

        if None in (fast_now, fast_prev, trend_now, trend_prev):
            return HOLD, "waiting for enough breakout strategy data"

        current_close = candles[index].close
        previous_close = candles[index - 1].close

        if current_close < trend_now:
            return SELL, f"price below trend MA {self.trend_window}"

        if previous_close >= fast_prev and current_close < fast_now:
            return SELL, f"price lost fast MA {self.fast_window}"

        trend_is_rising = trend_now > trend_prev
        previous_range = candles[index - self.breakout_window : index]
        previous_high = max(candle.high for candle in previous_range)
        breakout_price = previous_high * (1 + self.breakout_buffer_pct)
        volume_range = candles[index - self.volume_window : index]
        average_volume = sum(candle.volume for candle in volume_range) / self.volume_window
        current_volume = candles[index].volume
        volume_confirmed = average_volume > 0 and current_volume >= average_volume * self.min_volume_ratio

        if trend_is_rising and current_close > breakout_price and previous_close <= previous_high and volume_confirmed:
            return (
                BUY,
                f"volume-confirmed breakout above {self.breakout_window}-candle high in rising trend MA {self.trend_window}",
            )

        if trend_is_rising and current_close > breakout_price and previous_close <= previous_high:
            return HOLD, "breakout without enough volume"

        return HOLD, "no range breakout"


@dataclass(frozen=True)
class RsiTrendBounce:
    trend_window: int = 30
    buy_rsi: float = 38.0
    sell_rsi: float = 58.0
    rsi_window: int = 14

    def __post_init__(self) -> None:
        if self.trend_window <= 1 or self.rsi_window <= 1:
            raise ValueError("RSI bounce windows must be greater than one")
        if self.buy_rsi <= 0 or self.sell_rsi <= 0:
            raise ValueError("RSI thresholds must be greater than zero")
        if self.buy_rsi >= self.sell_rsi:
            raise ValueError("buy_rsi must be lower than sell_rsi")

    def signal_at(self, candles: list[Candle], index: int) -> tuple[str, str]:
        needed = max(self.trend_window + 1, self.rsi_window + 1)
        if index <= 0 or len(candles[: index + 1]) < needed:
            return HOLD, "waiting for enough RSI bounce data"

        closes_now = [candle.close for candle in candles[: index + 1]]
        closes_prev = [candle.close for candle in candles[:index]]
        trend_now = simple_moving_average(closes_now, self.trend_window)
        trend_prev = simple_moving_average(closes_prev, self.trend_window)
        rsi_now = relative_strength_index(candles, index, self.rsi_window)
        rsi_prev = relative_strength_index(candles, index - 1, self.rsi_window)
        if None in (trend_now, trend_prev, rsi_now, rsi_prev):
            return HOLD, "waiting for enough RSI bounce data"

        current_close = candles[index].close
        if current_close < trend_now:
            return SELL, f"price below trend MA {self.trend_window}"

        if rsi_now >= self.sell_rsi:
            return SELL, f"RSI rebound reached {rsi_now:.2f}"

        trend_is_not_falling = trend_now >= trend_prev
        rsi_is_recovering = rsi_prev <= self.buy_rsi and rsi_now > rsi_prev
        if trend_is_not_falling and current_close > trend_now and rsi_is_recovering:
            return BUY, f"RSI rebound from {rsi_prev:.2f} to {rsi_now:.2f} above trend MA {self.trend_window}"

        return HOLD, "no RSI rebound"
