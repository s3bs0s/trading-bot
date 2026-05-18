"""Paper trading simulator using public live market data only.

This module never connects to an exchange account, never uses API keys, and
never sends real orders. It updates a local fictitious wallet from public
candles.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path
from time import sleep

from src.aggressive_search import AggressiveCandidate
from src.aggressive_search import build_risk as build_aggressive_risk
from src.aggressive_search import build_strategy as build_aggressive_strategy
from src.backtest import EquityPoint, Trade, format_timestamp
from src.data import Candle, fetch_binance_klines
from src.report import money, pct, safe_name
from src.risk import RiskConfig, RiskManager, RiskState
from src.state_store import state_store_from_env
from src.strategy import BUY, SELL, PullbackInUptrend, RsiTrendBounce


PAPER_PRESETS = [
    "rsi-eth-2h",
    "rsi-sol-1h",
    "rsi-sol-4h",
    "aggressive-eth-2h",
    "active-eth-1h",
    "aggressive-eth-30m",
    "growth-eth-4h",
    "balanced-btc-4h",
    "stable-sol-4h",
    "experimental-eth-1m",
]
DISPLAY_TIMEZONE_LABEL = "Colombia"


@dataclass
class PaperState:
    version: int
    mode: str
    symbol: str
    interval: str
    preset: str
    strategy_label: str
    initial_cash: float
    fee_rate: float
    cash: float
    position_qty: float = 0.0
    entry_price: float = 0.0
    entry_cost: float = 0.0
    entry_time: str = ""
    entry_reason: str = ""
    highest_price_since_entry: float = 0.0
    last_processed_candle: str = ""
    peak_equity: float = 0.0
    paused: bool = False
    pause_reason: str = ""
    consecutive_losses: int = 0
    cooldown_bars_remaining: int = 0
    loss_streak_cooldown_remaining: int = 0
    last_action: str = "START"
    risk_events: list[str] = field(default_factory=list)
    trades: list[dict[str, object]] = field(default_factory=list)
    equity_curve: list[dict[str, object]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class PaperPreset:
    name: str
    symbol: str
    interval: str
    strategy_label: str
    strategy: object
    risk_config: RiskConfig
    lookback_candles: int


def utc_now_text() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def display_time_text(value: str) -> str:
    if not value:
        return "pendiente"
    try:
        normalized = value.replace(" UTC", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return (parsed.astimezone(UTC) - timedelta(hours=5)).strftime("%Y-%m-%d %I:%M:%S %p Colombia")
    except ValueError:
        return value


def build_preset(name: str) -> PaperPreset:
    if name == "rsi-eth-2h":
        return PaperPreset(
            name=name,
            symbol="ETHUSDT",
            interval="2h",
            strategy_label="rsi_eth_2h_bounce_t30_buy38_sell58_sl0.025_tp0.04_pos0.60",
            strategy=RsiTrendBounce(
                trend_window=30,
                buy_rsi=38.0,
                sell_rsi=58.0,
            ),
            risk_config=RiskConfig(
                stop_loss_pct=0.025,
                take_profit_pct=0.04,
                trailing_stop_pct=0.004,
                trailing_activation_pct=0.006,
                max_drawdown_pct=0.18,
                max_consecutive_losses=4,
                loss_streak_cooldown_bars=18,
                require_price_above_trend=True,
                trend_filter_window=30,
                require_rsi_confirmation=False,
                crash_lookback_bars=12,
                crash_block_pct=0.10,
                cooldown_bars_after_loss=1,
                position_size_pct=0.60,
            ),
            lookback_candles=360,
        )

    if name == "rsi-sol-1h":
        return PaperPreset(
            name=name,
            symbol="SOLUSDT",
            interval="1h",
            strategy_label="rsi_sol_1h_bounce_t30_buy48_sell68_sl0.025_tp0.04_pos0.60",
            strategy=RsiTrendBounce(
                trend_window=30,
                buy_rsi=48.0,
                sell_rsi=68.0,
            ),
            risk_config=RiskConfig(
                stop_loss_pct=0.025,
                take_profit_pct=0.04,
                trailing_stop_pct=0.004,
                trailing_activation_pct=0.006,
                max_drawdown_pct=0.12,
                max_consecutive_losses=3,
                loss_streak_cooldown_bars=18,
                require_price_above_trend=True,
                trend_filter_window=30,
                require_rsi_confirmation=False,
                crash_lookback_bars=12,
                crash_block_pct=0.10,
                cooldown_bars_after_loss=1,
                position_size_pct=0.60,
            ),
            lookback_candles=720,
        )

    if name == "rsi-sol-4h":
        return PaperPreset(
            name=name,
            symbol="SOLUSDT",
            interval="4h",
            strategy_label="rsi_sol_4h_bounce_t20_buy42_sell62_sl0.025_tp0.04_pos0.60",
            strategy=RsiTrendBounce(
                trend_window=20,
                buy_rsi=42.0,
                sell_rsi=62.0,
            ),
            risk_config=RiskConfig(
                stop_loss_pct=0.025,
                take_profit_pct=0.04,
                trailing_stop_pct=0.004,
                trailing_activation_pct=0.006,
                max_drawdown_pct=0.12,
                max_consecutive_losses=3,
                loss_streak_cooldown_bars=18,
                require_price_above_trend=True,
                trend_filter_window=20,
                require_rsi_confirmation=False,
                crash_lookback_bars=12,
                crash_block_pct=0.10,
                cooldown_bars_after_loss=1,
                position_size_pct=0.60,
            ),
            lookback_candles=540,
        )

    if name == "experimental-eth-1m":
        candidate = AggressiveCandidate(
            symbol="ETHUSDT",
            interval="1m",
            strategy_name="breakout",
            fast_window=6,
            trend_window=30,
            signal_window=4,
            signal_pct=0.0,
            stop_loss_pct=0.025,
            take_profit_pct=0.025,
            trailing_stop_pct=0.004,
            trailing_activation_pct=0.005,
            position_size_pct=0.60,
            rsi_min=45.0,
            rsi_max=82.0,
            volume_ratio=1.0,
        )
        return PaperPreset(
            name=name,
            symbol=candidate.symbol,
            interval=candidate.interval,
            strategy_label=f"experimental_1m_{candidate.label}",
            strategy=build_aggressive_strategy(candidate),
            risk_config=build_aggressive_risk(candidate),
            lookback_candles=1440,
        )

    if name == "aggressive-eth-2h":
        candidate = AggressiveCandidate(
            symbol="ETHUSDT",
            interval="2h",
            strategy_name="breakout",
            fast_window=6,
            trend_window=30,
            signal_window=4,
            signal_pct=0.0,
            stop_loss_pct=0.025,
            take_profit_pct=0.025,
            trailing_stop_pct=0.004,
            trailing_activation_pct=0.005,
            position_size_pct=0.60,
            rsi_min=45.0,
            rsi_max=82.0,
            volume_ratio=1.0,
        )
        return PaperPreset(
            name=name,
            symbol=candidate.symbol,
            interval=candidate.interval,
            strategy_label=candidate.label,
            strategy=build_aggressive_strategy(candidate),
            risk_config=build_aggressive_risk(candidate),
            lookback_candles=260,
        )

    if name == "active-eth-1h":
        candidate = AggressiveCandidate(
            symbol="ETHUSDT",
            interval="1h",
            strategy_name="breakout",
            fast_window=8,
            trend_window=50,
            signal_window=6,
            signal_pct=0.001,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            trailing_stop_pct=0.005,
            trailing_activation_pct=0.006,
            position_size_pct=0.50,
            rsi_min=50.0,
            rsi_max=75.0,
            volume_ratio=1.0,
        )
        return PaperPreset(
            name=name,
            symbol=candidate.symbol,
            interval=candidate.interval,
            strategy_label=f"active_1h_{candidate.label}",
            strategy=build_aggressive_strategy(candidate),
            risk_config=build_aggressive_risk(candidate),
            lookback_candles=360,
        )

    if name == "aggressive-eth-30m":
        candidate = AggressiveCandidate(
            symbol="ETHUSDT",
            interval="30m",
            strategy_name="breakout",
            fast_window=8,
            trend_window=50,
            signal_window=6,
            signal_pct=0.001,
            stop_loss_pct=0.018,
            take_profit_pct=0.03,
            trailing_stop_pct=0.004,
            trailing_activation_pct=0.005,
            position_size_pct=0.50,
            rsi_min=48.0,
            rsi_max=80.0,
            volume_ratio=1.0,
        )
        return PaperPreset(
            name=name,
            symbol=candidate.symbol,
            interval=candidate.interval,
            strategy_label=f"aggressive_30m_{candidate.label}",
            strategy=build_aggressive_strategy(candidate),
            risk_config=build_aggressive_risk(candidate),
            lookback_candles=720,
        )

    if name == "growth-eth-4h":
        candidate = AggressiveCandidate(
            symbol="ETHUSDT",
            interval="4h",
            strategy_name="pullback",
            fast_window=15,
            trend_window=50,
            signal_window=4,
            signal_pct=0.005,
            stop_loss_pct=0.025,
            take_profit_pct=0.04,
            trailing_stop_pct=0.004,
            trailing_activation_pct=0.005,
            position_size_pct=0.60,
            rsi_min=45.0,
            rsi_max=82.0,
            volume_ratio=1.0,
        )
        return PaperPreset(
            name=name,
            symbol=candidate.symbol,
            interval=candidate.interval,
            strategy_label=f"growth_4h_{candidate.label}",
            strategy=build_aggressive_strategy(candidate),
            risk_config=build_aggressive_risk(candidate),
            lookback_candles=540,
        )

    if name == "balanced-btc-4h":
        return PaperPreset(
            name=name,
            symbol="BTCUSDT",
            interval="4h",
            strategy_label="balanced_btc_4h_pullback_f20_t100_pb12_sl0.02_tp0.04_rsi50-75",
            strategy=PullbackInUptrend(
                fast_window=20,
                trend_window=100,
                pullback_window=12,
                min_pullback_pct=0.02,
            ),
            risk_config=RiskConfig(
                stop_loss_pct=0.02,
                take_profit_pct=0.04,
                max_drawdown_pct=0.12,
                max_consecutive_losses=3,
                loss_streak_cooldown_bars=18,
                require_price_above_trend=True,
                trend_filter_window=100,
                require_rsi_confirmation=True,
                rsi_window=14,
                rsi_min=50.0,
                rsi_max=75.0,
                cooldown_bars_after_loss=1,
                position_size_pct=0.30,
            ),
            lookback_candles=540,
        )

    if name == "stable-sol-4h":
        return PaperPreset(
            name=name,
            symbol="SOLUSDT",
            interval="4h",
            strategy_label="stable_sol_4h_pullback_f15_t50_pb6_sl0.02_tp0.04_rsi50-75",
            strategy=PullbackInUptrend(
                fast_window=15,
                trend_window=50,
                pullback_window=6,
                min_pullback_pct=0.01,
            ),
            risk_config=RiskConfig(
                stop_loss_pct=0.02,
                take_profit_pct=0.04,
                max_drawdown_pct=0.12,
                max_consecutive_losses=3,
                loss_streak_cooldown_bars=18,
                require_price_above_trend=True,
                trend_filter_window=50,
                require_rsi_confirmation=True,
                rsi_window=14,
                rsi_min=50.0,
                rsi_max=75.0,
                cooldown_bars_after_loss=1,
                position_size_pct=0.30,
            ),
            lookback_candles=260,
        )

    raise ValueError(f"unknown paper preset: {name}")


def state_path(state_dir: Path, preset: PaperPreset) -> Path:
    return state_dir / f"paper_{safe_name(preset.name)}_{safe_name(preset.symbol)}_{safe_name(preset.interval)}.json"


def load_state(path: Path, preset: PaperPreset, initial_cash: float, fee_rate: float, store: object | None = None) -> PaperState:
    if store is not None:
        payload = store.load(preset.name)
        if payload is not None:
            return PaperState(**payload)

    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        return PaperState(**payload)

    now = utc_now_text()
    return PaperState(
        version=1,
        mode="paper",
        symbol=preset.symbol,
        interval=preset.interval,
        preset=preset.name,
        strategy_label=preset.strategy_label,
        initial_cash=initial_cash,
        fee_rate=fee_rate,
        cash=initial_cash,
        peak_equity=initial_cash,
        created_at=now,
        updated_at=now,
    )


def save_state(
    path: Path,
    state: PaperState,
    store: object | None = None,
    run_context: dict[str, object] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = utc_now_text()
    payload = asdict(state)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if store is not None:
        store.save(payload, run_context=run_context)


def closed_public_candles(symbol: str, interval: str, limit: int) -> list[Candle]:
    candles = fetch_binance_klines(symbol=symbol, interval=interval, limit=limit + 1)
    if len(candles) > 1:
        return candles[:-1]
    return candles


def equity_at(state: PaperState, price: float) -> float:
    return state.cash + state.position_qty * price


def position_value_at(state: PaperState, price: float) -> float:
    return state.position_qty * price


def paper_risk_status(state: PaperState) -> str:
    if state.paused:
        return state.pause_reason or "paper trading paused"
    if state.risk_events:
        return f"Normal; eventos: {len(state.risk_events)}"
    return "Normal"


def register_risk_and_drawdown(state: PaperState, risk_config: RiskConfig, equity: float) -> float:
    state.peak_equity = max(state.peak_equity, equity)
    if state.peak_equity <= 0:
        return 0.0

    drawdown = (state.peak_equity - equity) / state.peak_equity
    if drawdown >= risk_config.max_drawdown_pct and not state.paused:
        state.paused = True
        state.pause_reason = f"max drawdown reached: {drawdown:.2%}"
        state.risk_events.append(state.pause_reason)
    return drawdown


def entry_block_reason(
    candles: list[Candle],
    index: int,
    state: PaperState,
    risk_manager: RiskManager,
    risk_config: RiskConfig,
) -> str | None:
    if state.paused:
        return state.pause_reason or "paper trading paused"

    if state.cooldown_bars_remaining > 0:
        return "cooldown after a losing trade"

    if state.loss_streak_cooldown_remaining > 0:
        return "loss streak cooldown after consecutive losses"

    if state.consecutive_losses >= risk_config.max_consecutive_losses:
        if risk_config.loss_streak_cooldown_bars > 0:
            reason = (
                f"loss streak cooldown: {state.consecutive_losses} consecutive losses, "
                f"waiting {risk_config.loss_streak_cooldown_bars} candles"
            )
            state.loss_streak_cooldown_remaining = risk_config.loss_streak_cooldown_bars
            state.consecutive_losses = 0
            state.risk_events.append(reason)
            return reason

        state.paused = True
        state.pause_reason = "too many consecutive losses"
        state.risk_events.append(state.pause_reason)
        return state.pause_reason

    local_risk_state = RiskState(peak_equity=state.peak_equity)
    return risk_manager.entry_block_reason(candles, index=index, state=local_risk_state)


def decrement_existing_cooldowns(state: PaperState, starting_loss_cooldown: int, starting_streak_cooldown: int) -> None:
    if starting_loss_cooldown > 0:
        state.cooldown_bars_remaining = max(0, state.cooldown_bars_remaining - 1)
    if starting_streak_cooldown > 0:
        state.loss_streak_cooldown_remaining = max(0, state.loss_streak_cooldown_remaining - 1)


def trade_from_dict(item: dict[str, object]) -> Trade:
    return Trade(
        entry_time=str(item["entry_time"]),
        exit_time=str(item["exit_time"]),
        entry_price=float(item["entry_price"]),
        exit_price=float(item["exit_price"]),
        quantity=float(item["quantity"]),
        entry_reason=str(item["entry_reason"]),
        exit_reason=str(item["exit_reason"]),
        pnl=float(item["pnl"]),
        return_pct=float(item["return_pct"]),
    )


def process_candles(state: PaperState, preset: PaperPreset, candles: list[Candle], bootstrap_history: int = 0) -> int:
    if not candles:
        return 0

    risk_manager = RiskManager(preset.risk_config)
    last_processed = state.last_processed_candle
    if last_processed:
        indexes = [index for index, candle in enumerate(candles) if format_timestamp(candle) > last_processed]
    elif bootstrap_history > 0:
        start = max(0, len(candles) - bootstrap_history)
        indexes = list(range(start, len(candles)))
    else:
        indexes = [len(candles) - 1]

    processed = 0
    for index in indexes:
        candle = candles[index]
        candle_time = format_timestamp(candle)
        if state.last_processed_candle and candle_time <= state.last_processed_candle:
            continue

        starting_loss_cooldown = state.cooldown_bars_remaining
        starting_streak_cooldown = state.loss_streak_cooldown_remaining
        price = candle.close
        current_equity = equity_at(state, price)
        drawdown = register_risk_and_drawdown(state, preset.risk_config, current_equity)
        signal, signal_reason = preset.strategy.signal_at(candles, index)

        if state.position_qty > 0:
            state.highest_price_since_entry = max(state.highest_price_since_entry, price)
            risk_exit_reason = risk_manager.exit_reason(
                entry_price=state.entry_price,
                current_price=price,
                highest_price=state.highest_price_since_entry,
            )
            should_sell = signal == SELL or risk_exit_reason is not None

            if should_sell:
                exit_reason = risk_exit_reason or signal_reason
                proceeds = state.position_qty * price * (1 - state.fee_rate)
                pnl = proceeds - state.entry_cost
                state.cash += proceeds
                state.trades.append(
                    {
                        "entry_time": state.entry_time,
                        "exit_time": candle_time,
                        "entry_price": state.entry_price,
                        "exit_price": price,
                        "quantity": state.position_qty,
                        "entry_reason": state.entry_reason,
                        "exit_reason": exit_reason,
                        "pnl": pnl,
                        "return_pct": pnl / state.entry_cost if state.entry_cost else 0.0,
                    }
                )

                if pnl < 0:
                    state.consecutive_losses += 1
                    state.cooldown_bars_remaining = max(
                        state.cooldown_bars_remaining,
                        preset.risk_config.cooldown_bars_after_loss,
                    )
                else:
                    state.consecutive_losses = 0

                state.position_qty = 0.0
                state.entry_price = 0.0
                state.entry_cost = 0.0
                state.entry_time = ""
                state.entry_reason = ""
                state.highest_price_since_entry = 0.0
                state.last_action = f"SELL - {exit_reason}"

        if state.position_qty == 0 and signal == BUY:
            block_reason = entry_block_reason(
                candles=candles,
                index=index,
                state=state,
                risk_manager=risk_manager,
                risk_config=preset.risk_config,
            )
            if block_reason is not None:
                state.last_action = f"HOLD - blocked: {block_reason}"
            else:
                spend = state.cash * preset.risk_config.position_size_pct
                if spend <= 0:
                    state.last_action = "HOLD - no fictitious cash"
                else:
                    state.position_qty = (spend * (1 - state.fee_rate)) / price
                    state.cash -= spend
                    state.entry_price = price
                    state.entry_cost = spend
                    state.entry_time = candle_time
                    state.entry_reason = signal_reason
                    state.highest_price_since_entry = price
                    state.last_action = f"BUY - {signal_reason}"

        final_equity = equity_at(state, price)
        final_drawdown = register_risk_and_drawdown(state, preset.risk_config, final_equity)
        state.equity_curve.append(
            {
                "date": candle_time,
                "close": price,
                "equity": final_equity,
                "cash": state.cash,
                "position_value": position_value_at(state, price),
                "drawdown_pct": max(drawdown, final_drawdown),
            }
        )
        state.last_processed_candle = candle_time
        if not state.last_action.startswith(("BUY", "SELL", "HOLD - blocked")):
            state.last_action = "HOLD"

        decrement_existing_cooldowns(
            state,
            starting_loss_cooldown=starting_loss_cooldown,
            starting_streak_cooldown=starting_streak_cooldown,
        )
        processed += 1

    return processed


def write_trades_csv(state: PaperState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "fecha_compra",
                "precio_compra",
                "motivo_compra",
                "fecha_venta",
                "precio_venta",
                "motivo_venta",
                "cantidad",
                "ganancia_usdt",
                "ganancia_pct",
            ],
        )
        writer.writeheader()
        for trade in state.trades:
            writer.writerow(
                {
                    "fecha_compra": trade["entry_time"],
                    "precio_compra": f"{float(trade['entry_price']):.8f}",
                    "motivo_compra": trade["entry_reason"],
                    "fecha_venta": trade["exit_time"],
                    "precio_venta": f"{float(trade['exit_price']):.8f}",
                    "motivo_venta": trade["exit_reason"],
                    "cantidad": f"{float(trade['quantity']):.12f}",
                    "ganancia_usdt": f"{float(trade['pnl']):.8f}",
                    "ganancia_pct": f"{float(trade['return_pct']):.8f}",
                }
            )


def scale(value: float, min_value: float, max_value: float, size: float) -> float:
    if min_value == max_value:
        return size / 2
    return (value - min_value) / (max_value - min_value) * size


def polyline(values: list[float], width: int, height: int, padding: int) -> str:
    if not values:
        return ""
    min_value = min(values)
    max_value = max(values)
    inner_width = width - padding * 2
    inner_height = height - padding * 2
    points: list[str] = []
    for index, value in enumerate(values):
        x = padding + (index / max(len(values) - 1, 1)) * inner_width
        y = padding + inner_height - scale(value, min_value, max_value, inner_height)
        points.append(f"{x:.2f},{y:.2f}")
    return " ".join(points)


def render_chart(points: list[dict[str, object]], value_key: str, stroke: str, label: str) -> str:
    width = 980
    height = 260
    padding = 44
    values = [float(point[value_key]) for point in points]
    if not values:
        values = [0.0]
    return f"""
    <svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label)}">
      <rect class="chart-bg" x="0" y="0" width="{width}" height="{height}" rx="8"></rect>
      <line class="grid-line" x1="{padding}" y1="{padding}" x2="{padding}" y2="{height - padding}"></line>
      <line class="grid-line" x1="{padding}" y1="{height - padding}" x2="{width - padding}" y2="{height - padding}"></line>
      <text class="axis-label" x="{padding}" y="24">Max {money(max(values))}</text>
      <text class="axis-label" x="{padding}" y="{height - 14}">Min {money(min(values))}</text>
      <polyline fill="none" stroke="{stroke}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" points="{polyline(values, width, height, padding)}"></polyline>
    </svg>
    """


def render_market_price_chart(candles: list[Candle], state: PaperState, context_limit: int = 120) -> str:
    width = 980
    height = 300
    padding = 44
    view_candles = candles[-context_limit:] if len(candles) > context_limit else candles
    if not view_candles:
        return render_chart([], "close", "#2563eb", "Precio reciente del mercado")

    buy_markers = {str(trade["entry_time"]): float(trade["entry_price"]) for trade in state.trades}
    sell_markers = {str(trade["exit_time"]): float(trade["exit_price"]) for trade in state.trades}
    if state.position_qty > 0 and state.entry_time:
        buy_markers[state.entry_time] = state.entry_price

    visible_times = {format_timestamp(candle) for candle in view_candles}
    values = [candle.close for candle in view_candles]
    values.extend(price for time, price in buy_markers.items() if time in visible_times)
    values.extend(price for time, price in sell_markers.items() if time in visible_times)

    min_value = min(values)
    max_value = max(values)
    inner_width = width - padding * 2
    inner_height = height - padding * 2

    def x_at(index: int) -> float:
        return padding + (index / max(len(view_candles) - 1, 1)) * inner_width

    def y_at(value: float) -> float:
        return padding + inner_height - scale(value, min_value, max_value, inner_height)

    line_points = " ".join(f"{x_at(index):.2f},{y_at(candle.close):.2f}" for index, candle in enumerate(view_candles))
    marker_items: list[str] = []

    for index, candle in enumerate(view_candles):
        candle_time = format_timestamp(candle)
        if candle_time in buy_markers:
            marker_items.append(
                f'<circle class="chart-marker-buy" cx="{x_at(index):.2f}" cy="{y_at(buy_markers[candle_time]):.2f}" r="5">'
                f"<title>Compra {escape(candle_time)}</title></circle>"
            )
        if candle_time in sell_markers:
            marker_items.append(
                f'<circle class="chart-marker-sell" cx="{x_at(index):.2f}" cy="{y_at(sell_markers[candle_time]):.2f}" r="5">'
                f"<title>Venta {escape(candle_time)}</title></circle>"
            )

    markers = "\n".join(marker_items)
    first_time = format_timestamp(view_candles[0])
    last_time = format_timestamp(view_candles[-1])

    return f"""
    <svg viewBox="0 0 {width} {height}" role="img" aria-label="Precio reciente del mercado">
      <rect class="chart-bg" x="0" y="0" width="{width}" height="{height}" rx="8"></rect>
      <line class="grid-line" x1="{padding}" y1="{padding}" x2="{padding}" y2="{height - padding}"></line>
      <line class="grid-line" x1="{padding}" y1="{height - padding}" x2="{width - padding}" y2="{height - padding}"></line>
      <text class="axis-label" x="{padding}" y="24">Max {money(max_value)}</text>
      <text class="axis-label" x="{padding}" y="{height - 14}">Min {money(min_value)}</text>
      <text class="axis-label" x="{padding}" y="{height - 2}">{escape(first_time)}</text>
      <text class="axis-label" x="{width - padding - 118}" y="{height - 2}">{escape(last_time)}</text>
      <polyline fill="none" stroke="#2563eb" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" points="{line_points}"></polyline>
      {markers}
    </svg>
    """


def render_trade_rows(state: PaperState) -> str:
    if not state.trades:
        return '<tr><td colspan="8">Aun no hay operaciones cerradas.</td></tr>'

    rows: list[str] = []
    for number, trade in enumerate(state.trades, start=1):
        pnl = float(trade["pnl"])
        result_class = "positive" if pnl >= 0 else "negative"
        rows.append(
            "<tr>"
            f"<td>{number}</td>"
            f"<td>{escape(str(trade['entry_time']))}</td>"
            f"<td>{money(float(trade['entry_price']))}</td>"
            f"<td>{escape(str(trade['entry_reason']))}</td>"
            f"<td>{escape(str(trade['exit_time']))}</td>"
            f"<td>{money(float(trade['exit_price']))}</td>"
            f"<td>{escape(str(trade['exit_reason']))}</td>"
            f'<td class="{result_class}">{money(pnl)} USDT<br><span>{pct(float(trade["return_pct"]))}</span></td>'
            "</tr>"
        )
    return "\n".join(rows)


def write_paper_report(
    state: PaperState,
    output_dir: Path,
    processed_count: int,
    latest_candle: Candle,
    state_file: Path,
    market_candles: list[Candle],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"paper_{safe_name(state.preset)}_{safe_name(state.symbol)}_{safe_name(state.interval)}.csv"
    html_path = output_dir / f"paper_{safe_name(state.preset)}_{safe_name(state.symbol)}_{safe_name(state.interval)}.html"
    write_trades_csv(state, csv_path)

    current_price = latest_candle.close
    current_equity = equity_at(state, current_price)
    return_pct = (current_equity - state.initial_cash) / state.initial_cash if state.initial_cash else 0.0
    max_drawdown = max((float(point["drawdown_pct"]) for point in state.equity_curve), default=0.0)
    winning_trades = sum(1 for trade in state.trades if float(trade["pnl"]) > 0)
    losing_trades = sum(1 for trade in state.trades if float(trade["pnl"]) < 0)
    win_rate = winning_trades / len(state.trades) if state.trades else 0.0
    floating_pnl = position_value_at(state, current_price) - state.entry_cost if state.position_qty > 0 else 0.0
    floating_return = floating_pnl / state.entry_cost if state.position_qty > 0 and state.entry_cost else 0.0
    result_class = "positive" if return_pct >= 0 else "negative"
    floating_class = "positive" if floating_pnl >= 0 else "negative"
    trade_rows = render_trade_rows(state)
    price_chart = render_market_price_chart(market_candles, state)
    equity_chart = render_chart(state.equity_curve, "equity", "#16805a", "Capital ficticio paper trading")
    context_candles = min(len(market_candles), 120)
    updated_display = display_time_text(state.updated_at)

    open_position_section = ""
    if state.position_qty > 0:
        open_position_section = f"""
        <section class="section">
          <h2>Posicion abierta ficticia</h2>
          <div class="summary-grid">
            <div class="metric"><span>Entrada</span><strong>{escape(state.entry_time)}</strong></div>
            <div class="metric"><span>Precio entrada</span><strong>{money(state.entry_price)}</strong></div>
            <div class="metric"><span>Valor actual</span><strong>{money(position_value_at(state, current_price))} USDT</strong></div>
            <div class="metric"><span>PnL flotante</span><strong class="{floating_class}">{money(floating_pnl)} USDT ({pct(floating_return)})</strong></div>
          </div>
        </section>
        """

    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <meta http-equiv="cache-control" content="no-cache">
  <meta http-equiv="expires" content="0">
  <title>Paper trading {escape(state.symbol)}</title>
  <style>
    :root {{
      --bg: #f6f8fb;
      --panel: #ffffff;
      --ink: #172033;
      --muted: #61708a;
      --line: #d9e1ec;
      --green: #16805a;
      --red: #c2413d;
      --amber: #b26b00;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: Segoe UI, Arial, sans-serif; line-height: 1.45; }}
    header {{ background: #101827; color: white; padding: 28px clamp(18px, 4vw, 46px); }}
    header h1 {{ margin: 0 0 8px; font-size: clamp(28px, 4vw, 42px); }}
    header p {{ margin: 0; color: #cbd5e1; max-width: 920px; }}
    main {{ width: min(1180px, calc(100% - 32px)); margin: 24px auto 48px; }}
    .status-line {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 18px; }}
    .pill {{ border: 1px solid var(--line); border-radius: 999px; padding: 6px 10px; color: var(--muted); background: #fbfdff; font-size: 13px; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 18px; }}
    .metric, .section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }}
    .section {{ margin-top: 16px; }}
    .metric span {{ display: block; color: var(--muted); font-size: 13px; margin-bottom: 6px; }}
    .metric strong {{ display: block; font-size: 22px; }}
    .positive {{ color: var(--green); }}
    .negative {{ color: var(--red); }}
    .warning {{ border-left: 4px solid var(--amber); background: #fff8ea; color: #5b3a00; }}
    svg {{ display: block; width: 100%; height: auto; }}
    .chart-bg {{ fill: #fbfdff; }}
    .grid-line {{ stroke: var(--line); stroke-width: 1.2; }}
    .axis-label {{ fill: var(--muted); font-size: 13px; }}
    .chart-marker-buy {{ fill: var(--green); stroke: white; stroke-width: 2; }}
    .chart-marker-sell {{ fill: var(--red); stroke: white; stroke-width: 2; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 900px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 11px 10px; text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; background: #fbfdff; }}
    a {{ color: #2563eb; font-weight: 600; text-decoration: none; }}
    .muted {{ color: var(--muted); }}
  </style>
</head>
<body>
  <header>
    <h1>Paper trading {escape(state.symbol)}</h1>
    <p>SIMULACION EN VIVO: usa precios publicos, dinero ficticio y no envia ordenes reales.</p>
  </header>
  <main>
    <div class="status-line">
      <span class="pill">Modo: paper trading</span>
      <span class="pill">Preset: {escape(state.preset)}</span>
      <span class="pill">Temporalidad: {escape(state.interval)}</span>
      <span class="pill">Ultima revision bot: {escape(updated_display)}</span>
      <span class="pill">Ultima vela cerrada: {escape(format_timestamp(latest_candle))}</span>
      <span class="pill">Velas contexto: {context_candles}</span>
      <span class="pill">Velas procesadas ahora: {processed_count}</span>
      <span class="pill">Auto-refresh pagina: <span id="refresh-countdown">30</span>s</span>
      <span class="pill">Hora navegador: <span id="browser-clock">cargando...</span></span>
      <span class="pill">Riesgo: {escape(paper_risk_status(state))}</span>
    </div>

    <section class="summary-grid">
      <div class="metric"><span>Capital ficticio inicial</span><strong>{money(state.initial_cash)} USDT</strong></div>
      <div class="metric"><span>Capital ficticio actual</span><strong>{money(current_equity)} USDT</strong></div>
      <div class="metric"><span>Resultado paper</span><strong class="{result_class}">{pct(return_pct)}</strong></div>
      <div class="metric"><span>Precio actual usado</span><strong>{money(current_price)}</strong></div>
      <div class="metric"><span>Max drawdown</span><strong class="negative">-{pct(max_drawdown)}</strong></div>
      <div class="metric"><span>Trades cerrados</span><strong>{len(state.trades)}</strong></div>
      <div class="metric"><span>Win rate</span><strong>{pct(win_rate)}</strong></div>
      <div class="metric"><span>Ultima accion</span><strong>{escape(state.last_action)}</strong></div>
      <div class="metric"><span>Posicion abierta</span><strong>{"SI" if state.position_qty > 0 else "NO"}</strong></div>
    </section>

    <section class="section warning">
      Este tablero no usa tu cuenta, no usa API keys y no toca dinero real. Todo es ficticio.
    </section>

    <section class="section">
      <h2>Precio reciente del mercado</h2>
      <p class="muted">Muestra las ultimas {context_candles} velas cerradas. Los puntos de compra/venta apareceran encima cuando existan.</p>
      {price_chart}
    </section>

    <section class="section">
      <h2>Capital ficticio</h2>
      {equity_chart}
    </section>

    {open_position_section}

    <section class="section">
      <h2>Operaciones ficticias</h2>
      <p><a href="{escape(csv_path.name)}">Abrir CSV</a></p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Compra</th>
              <th>Precio compra</th>
              <th>Motivo compra</th>
              <th>Venta</th>
              <th>Precio venta</th>
              <th>Motivo venta</th>
              <th>Resultado</th>
            </tr>
          </thead>
          <tbody>{trade_rows}</tbody>
        </table>
      </div>
    </section>

    <section class="section">
      <h2>Archivos</h2>
      <p class="muted">Estado local: {escape(str(state_file.resolve()))}</p>
      <p class="muted">Ultima revision del bot: {escape(updated_display)}</p>
    </section>
  </main>
  <script>
    const refreshSeconds = 30;
    let remainingSeconds = refreshSeconds;
    const countdown = document.getElementById("refresh-countdown");
    const browserClock = document.getElementById("browser-clock");

    function renderBrowserStatus() {{
      if (browserClock) {{
        browserClock.textContent = new Date().toLocaleTimeString();
      }}
      if (countdown) {{
        countdown.textContent = String(remainingSeconds);
      }}
    }}

    renderBrowserStatus();
    setInterval(() => {{
      remainingSeconds -= 1;
      if (remainingSeconds <= 0) {{
        window.location.reload();
        return;
      }}
      renderBrowserStatus();
    }}, 1000);
  </script>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    return html_path, csv_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paper trading simulator with fictitious money.")
    parser.add_argument("--preset", choices=PAPER_PRESETS, default="aggressive-eth-2h")
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--fee-rate", type=float, default=0.001)
    parser.add_argument("--state-dir", default="paper_state")
    parser.add_argument("--report-dir", default="reports\\paper")
    parser.add_argument("--bootstrap-history", type=int, default=0, help="Optional historical candles to simulate on a new state")
    parser.add_argument("--reset", action="store_true", help="Delete the local fictitious state before running")
    parser.add_argument("--watch", action="store_true", help="Keep checking periodically")
    parser.add_argument("--sleep-seconds", type=int, default=300)
    return parser


def run_once(args: argparse.Namespace) -> tuple[Path, Path, Path, int, PaperState]:
    preset = build_preset(args.preset)
    state_file = state_path(Path(args.state_dir), preset)
    if args.reset and state_file.exists():
        state_file.unlink()

    store = state_store_from_env()
    state = load_state(state_file, preset=preset, initial_cash=args.initial_cash, fee_rate=args.fee_rate, store=store)
    candles = closed_public_candles(preset.symbol, preset.interval, preset.lookback_candles)
    processed = process_candles(state, preset=preset, candles=candles, bootstrap_history=args.bootstrap_history)
    latest_candle = candles[-1]
    save_state(
        state_file,
        state,
        store=store,
        run_context={
            "processed_count": processed,
            "latest_candle": format_timestamp(latest_candle),
            "current_price": latest_candle.close,
        },
    )
    html_path, csv_path = write_paper_report(
        state,
        output_dir=Path(args.report_dir),
        processed_count=processed,
        latest_candle=latest_candle,
        state_file=state_file,
        market_candles=candles,
    )
    return html_path, csv_path, state_file, processed, state


def main() -> None:
    args = build_parser().parse_args()

    while True:
        html_path, csv_path, state_file, processed, state = run_once(args)
        print("Paper trading actualizado")
        print(f"Preset:        {state.preset}")
        print(f"Activo:        {state.symbol}")
        print(f"Temporalidad:  {state.interval}")
        print(f"Velas nuevas:  {processed}")
        print(f"Ultima accion: {state.last_action}")
        print(f"Reporte HTML:  {html_path.resolve()}")
        print(f"Reporte CSV:   {csv_path.resolve()}")
        print(f"Estado JSON:   {state_file.resolve()}")
        print("Nota: simulacion ficticia, sin API keys y sin ordenes reales.")

        if not args.watch:
            break
        sleep(max(30, args.sleep_seconds))


if __name__ == "__main__":
    main()
