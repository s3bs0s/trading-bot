"""Validate one strategy configuration across rolling historical windows."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from html import escape
from pathlib import Path

from src.backtest import BacktestConfig, Backtester, BacktestResult
from src.data import Candle, load_or_fetch
from src.report import pct, write_reports
from src.risk import RiskConfig
from src.strategy import PullbackInUptrend, RangeBreakoutInTrend


@dataclass(frozen=True)
class WindowResult:
    name: str
    start: str
    end: str
    result: BacktestResult


def slice_windows(candles: list[Candle], window_size: int, count: int) -> list[tuple[str, list[Candle]]]:
    windows: list[tuple[str, list[Candle]]] = []
    total = len(candles)
    for offset in range(count):
        end = total - offset * window_size
        start = end - window_size
        if start < 0 or end > total:
            continue
        label = f"window_{offset + 1}"
        windows.append((label, candles[start:end]))
    return windows


def run_window(name: str, candles: list[Candle], args: argparse.Namespace) -> WindowResult:
    if args.strategy == "breakout":
        strategy = RangeBreakoutInTrend(
            fast_window=args.fast,
            trend_window=args.trend_window,
            breakout_window=args.pullback_window,
            breakout_buffer_pct=args.min_pullback,
            volume_window=args.volume_window,
            min_volume_ratio=args.min_volume_ratio,
        )
    else:
        strategy = PullbackInUptrend(
            fast_window=args.fast,
            trend_window=args.trend_window,
            pullback_window=args.pullback_window,
            min_pullback_pct=args.min_pullback,
        )
    risk = RiskConfig(
        stop_loss_pct=args.stop_loss,
        take_profit_pct=args.take_profit,
        trailing_stop_pct=args.trailing_stop,
        trailing_activation_pct=args.trailing_activation,
        max_drawdown_pct=0.12,
        max_consecutive_losses=3,
        loss_streak_cooldown_bars=args.loss_streak_cooldown,
        require_price_above_trend=True,
        trend_filter_window=args.trend_window,
        require_rsi_confirmation=True,
        rsi_window=14,
        rsi_min=args.rsi_min,
        rsi_max=args.rsi_max,
        position_size_pct=args.position_size,
    )
    config = BacktestConfig(initial_cash=args.initial_cash, symbol=args.symbol)
    result = Backtester(strategy=strategy, risk_config=risk, config=config).run(candles)
    return WindowResult(name=name, start=result.first_candle, end=result.last_candle, result=result)


def write_validation_csv(results: list[WindowResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "window",
                "start",
                "end",
                "return_pct",
                "buy_hold_pct",
                "max_drawdown_pct",
                "closed_trades",
                "win_rate",
                "open_position",
                "floating_pnl",
                "risk_status",
            ],
        )
        writer.writeheader()
        for window in results:
            result = window.result
            writer.writerow(
                {
                    "window": window.name,
                    "start": window.start,
                    "end": window.end,
                    "return_pct": f"{result.return_pct:.8f}",
                    "buy_hold_pct": f"{result.buy_and_hold_return_pct:.8f}",
                    "max_drawdown_pct": f"{result.max_drawdown_pct:.8f}",
                    "closed_trades": result.closed_trades,
                    "win_rate": f"{result.win_rate:.8f}",
                    "open_position": result.open_position,
                    "floating_pnl": f"{result.floating_pnl:.8f}",
                    "risk_status": result.risk_status,
                }
            )


def write_validation_html(results: list[WindowResult], path: Path, csv_name: str) -> None:
    rows: list[str] = []
    wins = sum(1 for item in results if item.result.return_pct > 0)
    avg_return = sum(item.result.return_pct for item in results) / len(results) if results else 0.0
    worst_drawdown = max((item.result.max_drawdown_pct for item in results), default=0.0)

    for item in results:
        result = item.result
        result_class = "positive" if result.return_pct >= 0 else "negative"
        rows.append(
            "<tr>"
            f"<td>{escape(item.name)}</td>"
            f"<td>{escape(item.start)}</td>"
            f"<td>{escape(item.end)}</td>"
            f'<td class="{result_class}">{pct(result.return_pct)}</td>'
            f"<td>{pct(result.buy_and_hold_return_pct)}</td>"
            f'<td class="negative">-{pct(result.max_drawdown_pct)}</td>'
            f"<td>{result.closed_trades}</td>"
            f"<td>{pct(result.win_rate)}</td>"
            f"<td>{'SI' if result.open_position else 'NO'}</td>"
            f"<td>{escape(result.risk_status)}</td>"
            "</tr>"
        )

    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Validacion crypto-bot</title>
  <style>
    body {{ margin: 0; background: #f6f8fb; color: #172033; font-family: Segoe UI, Arial, sans-serif; }}
    header {{ background: #101827; color: white; padding: 28px 40px; }}
    main {{ width: min(1180px, calc(100% - 32px)); margin: 24px auto 48px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin-bottom: 16px; }}
    .metric, .panel {{ background: white; border: 1px solid #d9e1ec; border-radius: 8px; padding: 16px; }}
    .metric span {{ display: block; color: #61708a; font-size: 13px; margin-bottom: 6px; }}
    .metric strong {{ font-size: 24px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 900px; }}
    th, td {{ border-bottom: 1px solid #d9e1ec; padding: 10px; text-align: left; font-size: 14px; }}
    th {{ color: #61708a; font-size: 12px; text-transform: uppercase; background: #fbfdff; }}
    a {{ color: #2563eb; font-weight: 600; text-decoration: none; }}
    .positive {{ color: #16805a; font-weight: 700; }}
    .negative {{ color: #c2413d; font-weight: 700; }}
    .note {{ color: #61708a; }}
  </style>
</head>
<body>
  <header>
    <h1>Validacion por ventanas</h1>
    <p>Misma configuracion probada en varios periodos. Dinero ficticio, sin ordenes reales.</p>
  </header>
  <main>
    <section class="grid">
      <div class="metric"><span>Ventanas</span><strong>{len(results)}</strong></div>
      <div class="metric"><span>Ventanas positivas</span><strong>{wins}</strong></div>
      <div class="metric"><span>Retorno promedio</span><strong class="{'positive' if avg_return >= 0 else 'negative'}">{pct(avg_return)}</strong></div>
      <div class="metric"><span>Peor drawdown</span><strong class="negative">-{pct(worst_drawdown)}</strong></div>
    </section>
    <section class="panel">
      <p><a href="{escape(csv_name)}">Abrir CSV</a></p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Ventana</th>
              <th>Inicio</th>
              <th>Fin</th>
              <th>Bot</th>
              <th>Buy/Hold</th>
              <th>Drawdown</th>
              <th>Trades</th>
              <th>Win rate</th>
              <th>Abierta</th>
              <th>Riesgo</th>
            </tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
      <p class="note">Si una configuracion solo gana en una ventana, no es suficiente.</p>
    </section>
  </main>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate one candidate across rolling windows.")
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--history-limit", type=int, default=1500)
    parser.add_argument("--window-size", type=int, default=540)
    parser.add_argument("--windows", type=int, default=4)
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--strategy", choices=["pullback", "breakout"], default="pullback")
    parser.add_argument("--fast", type=int, default=20)
    parser.add_argument("--trend-window", type=int, default=50)
    parser.add_argument("--pullback-window", type=int, default=6)
    parser.add_argument("--min-pullback", type=float, default=0.02)
    parser.add_argument("--volume-window", type=int, default=20)
    parser.add_argument("--min-volume-ratio", type=float, default=1.2)
    parser.add_argument("--stop-loss", type=float, default=0.02)
    parser.add_argument("--take-profit", type=float, default=0.04)
    parser.add_argument("--trailing-stop", type=float, default=0.0)
    parser.add_argument("--trailing-activation", type=float, default=0.0)
    parser.add_argument("--loss-streak-cooldown", type=int, default=0)
    parser.add_argument("--rsi-min", type=float, default=50.0)
    parser.add_argument("--rsi-max", type=float, default=75.0)
    parser.add_argument("--position-size", type=float, default=0.30)
    parser.add_argument("--output-dir", default="reports\\validation_eth_top1")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candles = load_or_fetch(symbol=args.symbol, interval=args.interval, limit=args.history_limit)
    windows = slice_windows(candles, window_size=args.window_size, count=args.windows)
    results = [run_window(name=name, candles=window_candles, args=args) for name, window_candles in windows]

    csv_path = output_dir / "validation_results.csv"
    html_path = output_dir / "validation_results.html"
    write_validation_csv(results, csv_path)
    write_validation_html(results, html_path, csv_name=csv_path.name)

    for item in results:
        detail_dir = output_dir / item.name
        write_reports(
            item.result,
            symbol=args.symbol,
            interval=args.interval,
            output_dir=detail_dir,
            report_label=f"validation_{item.name}",
        )

    print("Validacion:")
    for item in results:
        result = item.result
        print(
            f"- {item.name}: {item.start} -> {item.end} | "
            f"bot {pct(result.return_pct)} | DD -{pct(result.max_drawdown_pct)} | "
            f"trades {result.closed_trades} | abierta {'SI' if result.open_position else 'NO'}"
        )

    print(f"\nValidacion HTML: {html_path.resolve()}")
    print(f"Validacion CSV:  {csv_path.resolve()}")


if __name__ == "__main__":
    main()
