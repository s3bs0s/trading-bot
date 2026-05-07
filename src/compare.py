"""Compare the current stable candidate across assets and periods."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from html import escape
from pathlib import Path

from src.backtest import BacktestConfig, Backtester, BacktestResult
from src.data import load_or_fetch
from src.report import pct, safe_name, write_reports
from src.risk import RiskConfig
from src.strategy import RangeBreakoutInTrend


@dataclass(frozen=True)
class ComparisonRow:
    symbol: str
    period: str
    limit: int
    result: BacktestResult
    html_report: Path
    csv_report: Path


def build_stable_strategy() -> RangeBreakoutInTrend:
    return RangeBreakoutInTrend(
        fast_window=10,
        trend_window=30,
        breakout_window=12,
        breakout_buffer_pct=0.002,
        volume_window=20,
        min_volume_ratio=1.0,
    )


def build_stable_risk(loss_streak_cooldown_bars: int) -> RiskConfig:
    return RiskConfig(
        stop_loss_pct=0.02,
        take_profit_pct=0.04,
        trailing_stop_pct=0.005,
        trailing_activation_pct=0.006,
        max_drawdown_pct=0.12,
        max_consecutive_losses=3,
        loss_streak_cooldown_bars=loss_streak_cooldown_bars,
        require_price_above_trend=True,
        trend_filter_window=30,
        require_rsi_confirmation=True,
        rsi_window=14,
        rsi_min=50,
        rsi_max=75,
        position_size_pct=0.30,
    )


def write_comparison_csv(rows: list[ComparisonRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "symbol",
                "period",
                "start",
                "end",
                "return_pct",
                "buy_hold_pct",
                "max_drawdown_pct",
                "closed_trades",
                "win_rate",
                "risk_status",
                "html_report",
                "csv_report",
            ],
        )
        writer.writeheader()
        for row in rows:
            result = row.result
            writer.writerow(
                {
                    "symbol": row.symbol,
                    "period": row.period,
                    "start": result.first_candle,
                    "end": result.last_candle,
                    "return_pct": f"{result.return_pct:.8f}",
                    "buy_hold_pct": f"{result.buy_and_hold_return_pct:.8f}",
                    "max_drawdown_pct": f"{result.max_drawdown_pct:.8f}",
                    "closed_trades": result.closed_trades,
                    "win_rate": f"{result.win_rate:.8f}",
                    "risk_status": result.risk_status,
                    "html_report": str(row.html_report.resolve()),
                    "csv_report": str(row.csv_report.resolve()),
                }
            )


def write_comparison_html(rows: list[ComparisonRow], path: Path, csv_name: str) -> None:
    table_rows: list[str] = []
    for row in rows:
        result = row.result
        result_class = "positive" if result.return_pct >= 0 else "negative"
        risk_class = "positive" if result.risk_status.startswith("Normal") else "negative"
        report_href = row.html_report.relative_to(path.parent).as_posix()
        table_rows.append(
            "<tr>"
            f"<td>{escape(row.symbol)}</td>"
            f"<td>{escape(row.period)}</td>"
            f"<td>{escape(result.first_candle)}</td>"
            f"<td>{escape(result.last_candle)}</td>"
            f'<td class="{result_class}">{pct(result.return_pct)}</td>'
            f"<td>{pct(result.buy_and_hold_return_pct)}</td>"
            f'<td class="negative">-{pct(result.max_drawdown_pct)}</td>'
            f"<td>{result.closed_trades}</td>"
            f"<td>{pct(result.win_rate)}</td>"
            f'<td class="{risk_class}">{escape(result.risk_status)}</td>'
            f'<td><a href="{escape(report_href)}">HTML</a></td>'
            "</tr>"
        )

    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Comparacion candidato estable</title>
  <style>
    body {{ margin: 0; background: #f6f8fb; color: #172033; font-family: Segoe UI, Arial, sans-serif; }}
    header {{ background: #101827; color: white; padding: 28px 40px; }}
    main {{ width: min(1280px, calc(100% - 32px)); margin: 24px auto 48px; }}
    .panel {{ background: white; border: 1px solid #d9e1ec; border-radius: 8px; padding: 18px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 1120px; }}
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
    <h1>Comparacion candidato estable</h1>
    <p>Backtesting educativo con dinero ficticio. Sin API keys, sin ordenes reales.</p>
  </header>
  <main>
    <section class="panel">
      <p><a href="{escape(csv_name)}">Abrir CSV completo</a></p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Activo</th>
              <th>Periodo</th>
              <th>Inicio</th>
              <th>Fin</th>
              <th>Bot</th>
              <th>Buy/Hold</th>
              <th>Drawdown</th>
              <th>Trades</th>
              <th>Win rate</th>
              <th>Riesgo</th>
              <th>Reporte</th>
            </tr>
          </thead>
          <tbody>{''.join(table_rows)}</tbody>
        </table>
      </div>
      <p class="note">Una estrategia que gana en un activo puede fallar en otro. Esto todavia no es paper trading.</p>
    </section>
  </main>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare the stable crypto bot candidate.")
    parser.add_argument("--symbols", default="ETHUSDT,BTCUSDT,SOLUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--loss-streak-cooldown", type=int, default=72)
    parser.add_argument("--output-dir", default="reports\\stable_candidate_comparison")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    periods = [("3m", 2160), ("6m", 4320), ("12m", 8760)]
    output_dir = Path(args.output_dir)
    rows: list[ComparisonRow] = []

    for symbol in symbols:
        for period, limit in periods:
            candles = load_or_fetch(symbol=symbol, interval=args.interval, limit=limit)
            result = Backtester(
                strategy=build_stable_strategy(),
                risk_config=build_stable_risk(loss_streak_cooldown_bars=args.loss_streak_cooldown),
                config=BacktestConfig(initial_cash=args.initial_cash, symbol=symbol),
            ).run(candles)
            detail_dir = output_dir / f"{safe_name(symbol)}_{period}"
            html_report, csv_report = write_reports(
                result,
                symbol=symbol,
                interval=args.interval,
                output_dir=detail_dir,
                report_label=f"stable_{period}",
            )
            rows.append(
                ComparisonRow(
                    symbol=symbol,
                    period=period,
                    limit=limit,
                    result=result,
                    html_report=html_report,
                    csv_report=csv_report,
                )
            )

    csv_path = output_dir / "comparison_results.csv"
    html_path = output_dir / "comparison_results.html"
    write_comparison_csv(rows, csv_path)
    write_comparison_html(rows, html_path, csv_name=csv_path.name)

    print("Comparacion candidato estable:")
    for row in rows:
        result = row.result
        print(
            f"- {row.symbol} {row.period}: bot {pct(result.return_pct)} | "
            f"DD -{pct(result.max_drawdown_pct)} | trades {result.closed_trades} | riesgo {result.risk_status}"
        )

    print(f"\nComparacion HTML: {html_path.resolve()}")
    print(f"Comparacion CSV:  {csv_path.resolve()}")


if __name__ == "__main__":
    main()
