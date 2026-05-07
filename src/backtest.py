"""Backtesting engine for the educational crypto simulator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from src.data import Candle
from src.risk import RiskConfig, RiskManager, RiskState
from src.strategy import BUY, SELL


def format_timestamp(candle: Candle) -> str:
    return candle.timestamp.strftime("%Y-%m-%d %H:%M")


class Strategy(Protocol):
    def signal_at(self, candles: list[Candle], index: int) -> tuple[str, str]:
        ...


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 1000.0
    fee_rate: float = 0.001
    symbol: str = "BTCUSDT"


@dataclass(frozen=True)
class Trade:
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    quantity: float
    entry_reason: str
    exit_reason: str
    pnl: float
    return_pct: float


@dataclass(frozen=True)
class EquityPoint:
    date: str
    close: float
    equity: float
    cash: float
    position_value: float
    drawdown_pct: float


@dataclass
class BacktestResult:
    initial_cash: float
    final_equity: float
    buy_and_hold_equity: float
    max_drawdown_pct: float
    equity_curve: list[EquityPoint] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    last_action: str = "HOLD"
    risk_status: str = "Normal"
    first_candle: str = ""
    last_candle: str = ""
    open_position: bool = False
    open_entry_time: str = ""
    open_entry_price: float = 0.0
    open_quantity: float = 0.0
    open_entry_reason: str = ""
    open_position_value: float = 0.0
    floating_pnl: float = 0.0
    floating_return_pct: float = 0.0
    risk_events: list[str] = field(default_factory=list)

    @property
    def return_pct(self) -> float:
        return (self.final_equity - self.initial_cash) / self.initial_cash if self.initial_cash else 0.0

    @property
    def buy_and_hold_return_pct(self) -> float:
        return (self.buy_and_hold_equity - self.initial_cash) / self.initial_cash if self.initial_cash else 0.0

    @property
    def closed_trades(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> int:
        return sum(1 for trade in self.trades if trade.pnl > 0)

    @property
    def losing_trades(self) -> int:
        return sum(1 for trade in self.trades if trade.pnl < 0)

    @property
    def win_rate(self) -> float:
        return self.winning_trades / self.closed_trades if self.closed_trades else 0.0


class Backtester:
    def __init__(
        self,
        strategy: Strategy,
        risk_config: RiskConfig,
        config: BacktestConfig | None = None,
    ):
        self.strategy = strategy
        self.risk_manager = RiskManager(risk_config)
        self.risk_config = risk_config
        self.config = config or BacktestConfig()

    def run(self, candles: list[Candle]) -> BacktestResult:
        if len(candles) < 2:
            raise ValueError("at least two candles are required")

        cash = self.config.initial_cash
        position_qty = 0.0
        entry_price = 0.0
        entry_cost = 0.0
        entry_time = ""
        entry_reason = ""
        highest_price_since_entry = 0.0

        trades: list[Trade] = []
        equity_curve: list[EquityPoint] = []
        state = RiskState(peak_equity=self.config.initial_cash)
        max_drawdown = 0.0
        last_action = "HOLD"

        for index, candle in enumerate(candles):
            price = candle.close
            equity = cash + position_qty * price
            drawdown = self.risk_manager.update_peak_and_drawdown(equity, state)
            max_drawdown = max(max_drawdown, drawdown)

            signal, signal_reason = self.strategy.signal_at(candles, index)

            if position_qty > 0:
                highest_price_since_entry = max(highest_price_since_entry, price)
                risk_exit_reason = self.risk_manager.exit_reason(
                    entry_price,
                    price,
                    highest_price=highest_price_since_entry,
                )
                should_sell = signal == SELL or risk_exit_reason is not None

                if should_sell:
                    exit_reason = risk_exit_reason or signal_reason
                    proceeds = position_qty * price * (1 - self.config.fee_rate)
                    pnl = proceeds - entry_cost
                    cash += proceeds

                    trade = Trade(
                        entry_time=entry_time,
                        exit_time=format_timestamp(candle),
                        entry_price=entry_price,
                        exit_price=price,
                        quantity=position_qty,
                        entry_reason=entry_reason,
                        exit_reason=exit_reason,
                        pnl=pnl,
                        return_pct=pnl / entry_cost if entry_cost else 0.0,
                    )
                    trades.append(trade)

                    if pnl < 0:
                        state.consecutive_losses += 1
                        state.cooldown_until_index = index + self.risk_config.cooldown_bars_after_loss
                    else:
                        state.consecutive_losses = 0

                    position_qty = 0.0
                    entry_price = 0.0
                    entry_cost = 0.0
                    entry_time = ""
                    entry_reason = ""
                    highest_price_since_entry = 0.0
                    last_action = "SELL"

            if position_qty == 0 and signal == BUY:
                block_reason = self.risk_manager.entry_block_reason(candles, index, state)
                if block_reason is not None:
                    last_action = f"HOLD - blocked: {block_reason}"
                else:
                    spend = cash * self.risk_config.position_size_pct
                    if spend <= 0:
                        last_action = "HOLD - no cash"
                    else:
                        position_qty = (spend * (1 - self.config.fee_rate)) / price
                        cash -= spend
                        entry_price = price
                        entry_cost = spend
                        entry_time = format_timestamp(candle)
                        entry_reason = signal_reason
                        highest_price_since_entry = price
                        last_action = "BUY"

            close_equity = cash + position_qty * price
            close_drawdown = self.risk_manager.update_peak_and_drawdown(close_equity, state)
            max_drawdown = max(max_drawdown, close_drawdown)
            equity_curve.append(
                EquityPoint(
                    date=format_timestamp(candle),
                    close=price,
                    equity=close_equity,
                    cash=cash,
                    position_value=position_qty * price,
                    drawdown_pct=close_drawdown,
                )
            )

        final_price = candles[-1].close
        final_equity = cash + position_qty * final_price
        final_drawdown = self.risk_manager.update_peak_and_drawdown(final_equity, state)
        max_drawdown = max(max_drawdown, final_drawdown)

        first_price = candles[0].close
        buy_and_hold_equity = self.config.initial_cash * (final_price / first_price) if first_price else 0.0
        if state.paused:
            risk_status = state.pause_reason
        elif state.risk_events:
            risk_status = f"Normal; cooldowns: {len(state.risk_events)}"
        else:
            risk_status = "Normal"
        open_position = position_qty > 0
        open_position_value = position_qty * final_price if open_position else 0.0
        floating_pnl = open_position_value - entry_cost if open_position else 0.0
        floating_return_pct = floating_pnl / entry_cost if open_position and entry_cost else 0.0

        return BacktestResult(
            initial_cash=self.config.initial_cash,
            final_equity=final_equity,
            buy_and_hold_equity=buy_and_hold_equity,
            max_drawdown_pct=max_drawdown,
            equity_curve=equity_curve,
            trades=trades,
            last_action=last_action,
            risk_status=risk_status,
            first_candle=format_timestamp(candles[0]),
            last_candle=format_timestamp(candles[-1]),
            open_position=open_position,
            open_entry_time=entry_time if open_position else "",
            open_entry_price=entry_price if open_position else 0.0,
            open_quantity=position_qty if open_position else 0.0,
            open_entry_reason=entry_reason if open_position else "",
            open_position_value=open_position_value,
            floating_pnl=floating_pnl,
            floating_return_pct=floating_return_pct,
            risk_events=state.risk_events,
        )
