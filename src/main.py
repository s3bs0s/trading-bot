"""Command-line entry point for the educational crypto simulator."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.backtest import BacktestConfig, Backtester, BacktestResult
from src.data import load_or_fetch
from src.report import write_reports
from src.risk import RiskConfig
from src.strategy import MovingAverageCrossover, PullbackInUptrend, RangeBreakoutInTrend


def money(value: float) -> str:
    return f"{value:,.2f}"


def pct(value: float) -> str:
    return f"{value:.2%}"


def print_result(result: BacktestResult, symbol: str, interval: str, html_report: Path | None = None, csv_report: Path | None = None) -> None:
    print("\n=== Crypto Bot - SIMULACION EDUCATIVA ===")
    print("Modo: backtesting local, dinero ficticio, sin API key, sin ordenes reales")
    print(f"Activo: {symbol}")
    print(f"Temporalidad: {interval}")
    print(f"Periodo: {result.first_candle} -> {result.last_candle}")
    print()
    print(f"Capital inicial: {money(result.initial_cash)} USDT")
    print(f"Capital final:   {money(result.final_equity)} USDT")
    print(f"Resultado bot:   {pct(result.return_pct)}")
    print(f"Buy and hold:    {pct(result.buy_and_hold_return_pct)}")
    print(f"Max drawdown:    -{pct(result.max_drawdown_pct)}")
    print()
    print(f"Trades cerrados: {result.closed_trades}")
    print(f"Ganadores:       {result.winning_trades}")
    print(f"Perdedores:      {result.losing_trades}")
    print(f"Win rate:        {pct(result.win_rate)}")
    print(f"Riesgo:          {result.risk_status}")
    print(f"Ultima accion:   {result.last_action}")
    if result.open_position:
        print()
        print("Posicion abierta: SI")
        print(f"Entrada:          {result.open_entry_time} a {money(result.open_entry_price)}")
        print(f"Valor actual:     {money(result.open_position_value)} USDT")
        print(f"PnL flotante:     {money(result.floating_pnl)} USDT ({pct(result.floating_return_pct)})")

    if result.trades:
        print("\nUltimos trades:")
        for trade in result.trades[-5:]:
            print(
                f"- {trade.entry_time} -> {trade.exit_time} | "
                f"{money(trade.entry_price)} -> {money(trade.exit_price)} | "
                f"PnL {money(trade.pnl)} USDT ({pct(trade.return_pct)}) | "
                f"salida: {trade.exit_reason}"
            )

    print("\nNota: un backtest no garantiza resultados futuros.")
    if html_report is not None and csv_report is not None:
        print(f"\nReporte HTML: {html_report.resolve()}")
        print(f"Reporte CSV:  {csv_report.resolve()}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Educational crypto backtesting bot.")
    parser.add_argument("--symbol", default="BTCUSDT", help="Trading pair, e.g. BTCUSDT or ETHUSDT")
    parser.add_argument("--interval", default="1d", help="Candle interval, e.g. 1d, 4h, 1h")
    parser.add_argument("--limit", type=int, default=365, help="Number of candles to load")
    parser.add_argument("--initial-cash", type=float, default=1000.0, help="Fictitious initial USDT")
    parser.add_argument("--strategy", choices=["crossover", "pullback", "breakout"], default="pullback", help="Signal strategy to backtest")
    parser.add_argument("--fast", type=int, default=20, help="Fast moving average window")
    parser.add_argument("--slow", type=int, default=50, help="Slow moving average window")
    parser.add_argument("--pullback-window", type=int, default=12, help="Candles used to detect a pullback")
    parser.add_argument("--min-pullback", type=float, default=0.015, help="Minimum pullback depth, e.g. 0.015 = 1.5%%")
    parser.add_argument("--volume-window", type=int, default=20, help="Volume average window for breakout")
    parser.add_argument("--min-volume-ratio", type=float, default=1.2, help="Breakout volume must exceed average by this ratio")
    parser.add_argument("--stop-loss", type=float, default=0.03, help="Stop loss, e.g. 0.03 = 3%%")
    parser.add_argument("--take-profit", type=float, default=0.08, help="Take profit, e.g. 0.08 = 8%%")
    parser.add_argument("--trailing-stop", type=float, default=0.0, help="Trailing stop from best price after entry, e.g. 0.015 = 1.5%%")
    parser.add_argument("--trailing-activation", type=float, default=0.0, help="Minimum gain before trailing stop activates, e.g. 0.01 = 1%%")
    parser.add_argument("--max-drawdown", type=float, default=0.12, help="Pause threshold, e.g. 0.12 = 12%%")
    parser.add_argument("--max-consecutive-losses", type=int, default=3, help="Pause after this many losing trades")
    parser.add_argument("--loss-streak-cooldown", type=int, default=0, help="Temporary backtest cooldown after max consecutive losses; 0 keeps hard pause")
    parser.add_argument("--position-size", type=float, default=0.30, help="Fraction of cash used per entry")
    parser.add_argument("--trend-window", type=int, default=200, help="Trend filter window used before buying")
    parser.add_argument("--no-trend-filter", action="store_true", help="Allow buys below the long-term trend average")
    parser.add_argument("--no-rsi-filter", action="store_true", help="Allow buys without RSI momentum confirmation")
    parser.add_argument("--rsi-window", type=int, default=14, help="RSI window used before buying")
    parser.add_argument("--rsi-min", type=float, default=50.0, help="Minimum RSI allowed for new buys")
    parser.add_argument("--rsi-max", type=float, default=75.0, help="Maximum RSI allowed for new buys")
    parser.add_argument("--data-dir", default="data", help="Directory for candle CSV cache")
    parser.add_argument("--report-dir", default="reports", help="Directory for generated HTML and CSV reports")
    parser.add_argument("--no-report", action="store_true", help="Run without writing report files")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    candles = load_or_fetch(
        symbol=args.symbol,
        interval=args.interval,
        limit=args.limit,
        cache_dir=Path(args.data_dir),
    )
    if args.strategy == "pullback":
        strategy = PullbackInUptrend(
            fast_window=args.fast,
            trend_window=args.trend_window,
            pullback_window=args.pullback_window,
            min_pullback_pct=args.min_pullback,
        )
    elif args.strategy == "breakout":
        strategy = RangeBreakoutInTrend(
            fast_window=args.fast,
            trend_window=args.trend_window,
            breakout_window=args.pullback_window,
            breakout_buffer_pct=args.min_pullback,
            volume_window=args.volume_window,
            min_volume_ratio=args.min_volume_ratio,
        )
    else:
        strategy = MovingAverageCrossover(fast_window=args.fast, slow_window=args.slow)
    risk_config = RiskConfig(
        stop_loss_pct=args.stop_loss,
        take_profit_pct=args.take_profit,
        trailing_stop_pct=args.trailing_stop,
        trailing_activation_pct=args.trailing_activation,
        max_drawdown_pct=args.max_drawdown,
        max_consecutive_losses=args.max_consecutive_losses,
        loss_streak_cooldown_bars=args.loss_streak_cooldown,
        position_size_pct=args.position_size,
        trend_filter_window=args.trend_window,
        require_price_above_trend=not args.no_trend_filter,
        require_rsi_confirmation=not args.no_rsi_filter,
        rsi_window=args.rsi_window,
        rsi_min=args.rsi_min,
        rsi_max=args.rsi_max,
    )
    config = BacktestConfig(initial_cash=args.initial_cash, symbol=args.symbol)
    result = Backtester(strategy=strategy, risk_config=risk_config, config=config).run(candles)
    html_report = None
    csv_report = None
    if not args.no_report:
        report_label = f"trend{args.trend_window}" if not args.no_trend_filter else "baseline"
        report_label = f"{args.strategy}_{report_label}"
        if not args.no_rsi_filter:
            report_label = f"{report_label}_rsi{int(args.rsi_min)}-{int(args.rsi_max)}"
        if args.trailing_stop > 0:
            report_label = f"{report_label}_trail{args.trailing_stop:.3f}_act{args.trailing_activation:.3f}"
        if args.loss_streak_cooldown > 0:
            report_label = f"{report_label}_cool{args.loss_streak_cooldown}"
        html_report, csv_report = write_reports(
            result,
            symbol=args.symbol,
            interval=args.interval,
            output_dir=Path(args.report_dir),
            report_label=report_label,
        )
    print_result(result, symbol=args.symbol.upper(), interval=args.interval, html_report=html_report, csv_report=csv_report)


if __name__ == "__main__":
    main()
