"""Risk controls that can block or close trades independently of strategy."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.data import Candle


@dataclass(frozen=True)
class RiskConfig:
    stop_loss_pct: float = 0.03
    take_profit_pct: float = 0.08
    trailing_stop_pct: float = 0.0
    trailing_activation_pct: float = 0.0
    max_drawdown_pct: float = 0.12
    max_consecutive_losses: int = 3
    loss_streak_cooldown_bars: int = 0
    require_price_above_trend: bool = True
    trend_filter_window: int = 200
    require_rsi_confirmation: bool = True
    rsi_window: int = 14
    rsi_min: float = 50.0
    rsi_max: float = 75.0
    crash_lookback_bars: int = 7
    crash_block_pct: float = 0.12
    cooldown_bars_after_loss: int = 1
    position_size_pct: float = 0.30


@dataclass
class RiskState:
    peak_equity: float
    consecutive_losses: int = 0
    cooldown_until_index: int = -1
    paused: bool = False
    pause_reason: str = ""
    risk_events: list[str] = field(default_factory=list)


class RiskManager:
    def __init__(self, config: RiskConfig):
        self.config = config

    def update_peak_and_drawdown(self, equity: float, state: RiskState) -> float:
        state.peak_equity = max(state.peak_equity, equity)
        if state.peak_equity <= 0:
            return 0.0

        drawdown = (state.peak_equity - equity) / state.peak_equity
        if drawdown >= self.config.max_drawdown_pct and not state.paused:
            state.paused = True
            state.pause_reason = f"max drawdown reached: {drawdown:.2%}"
            state.risk_events.append(state.pause_reason)
        return drawdown

    def entry_block_reason(self, candles: list[Candle], index: int, state: RiskState) -> str | None:
        if state.paused:
            return state.pause_reason or "risk manager paused trading"

        if index <= state.cooldown_until_index:
            return "cooldown after a losing trade"

        if state.consecutive_losses >= self.config.max_consecutive_losses:
            if self.config.loss_streak_cooldown_bars > 0:
                reason = (
                    f"loss streak cooldown: {state.consecutive_losses} consecutive losses, "
                    f"waiting {self.config.loss_streak_cooldown_bars} candles"
                )
                state.cooldown_until_index = max(
                    state.cooldown_until_index,
                    index + self.config.loss_streak_cooldown_bars,
                )
                state.consecutive_losses = 0
                state.risk_events.append(reason)
                return reason

            state.paused = True
            state.pause_reason = "too many consecutive losses"
            state.risk_events.append(state.pause_reason)
            return state.pause_reason

        if self.config.require_price_above_trend:
            window = self.config.trend_filter_window
            if window <= 0:
                return "invalid trend filter window"
            if index + 1 >= window:
                closes = [candle.close for candle in candles[index + 1 - window : index + 1]]
                trend_average = sum(closes) / window
                current_close = candles[index].close
                if current_close < trend_average:
                    return f"price below {window}-candle trend average"

        if self.config.require_rsi_confirmation:
            rsi = relative_strength_index(candles, index, self.config.rsi_window)
            if rsi is None:
                return "waiting for enough RSI data"
            if rsi < self.config.rsi_min:
                return f"RSI too weak: {rsi:.2f}"
            if rsi > self.config.rsi_max:
                return f"RSI too hot: {rsi:.2f}"

        lookback = self.config.crash_lookback_bars
        if index >= lookback:
            previous_close = candles[index - lookback].close
            current_close = candles[index].close
            if previous_close > 0:
                drop = (previous_close - current_close) / previous_close
                if drop >= self.config.crash_block_pct:
                    return f"market dropped {drop:.2%} over last {lookback} candles"

        return None

    def exit_reason(self, entry_price: float, current_price: float, highest_price: float | None = None) -> str | None:
        if entry_price <= 0:
            return None

        change = (current_price - entry_price) / entry_price
        if change <= -self.config.stop_loss_pct:
            return f"stop loss hit ({change:.2%})"

        if (
            self.config.trailing_stop_pct > 0
            and highest_price is not None
            and highest_price > entry_price
        ):
            gain_from_entry = (highest_price - entry_price) / entry_price
            drop_from_high = (current_price - highest_price) / highest_price
            if gain_from_entry >= self.config.trailing_activation_pct and drop_from_high <= -self.config.trailing_stop_pct:
                return f"trailing stop hit ({drop_from_high:.2%} from high)"

        if change >= self.config.take_profit_pct:
            return f"take profit hit ({change:.2%})"

        return None


def relative_strength_index(candles: list[Candle], index: int, window: int) -> float | None:
    """Return a simple RSI value for the current candle."""
    if window <= 0:
        raise ValueError("RSI window must be greater than zero")
    if index < window:
        return None

    gains = 0.0
    losses = 0.0
    for candle_index in range(index - window + 1, index + 1):
        change = candles[candle_index].close - candles[candle_index - 1].close
        if change >= 0:
            gains += change
        else:
            losses += abs(change)

    average_gain = gains / window
    average_loss = losses / window

    if average_loss == 0:
        return 100.0

    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))
