"""Rolling validation for the current per-asset candidate shortlist."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from html import escape
from pathlib import Path

from src.backtest import BacktestConfig, Backtester, BacktestResult
from src.data import Candle, load_or_fetch
from src.optimize import Candidate, build_risk, build_strategy
from src.report import pct, safe_name, write_reports


@dataclass(frozen=True)
class CandidateSpec:
    symbol: str
    candidate: Candidate


@dataclass(frozen=True)
class RollingResult:
    symbol: str
    interval: str
    candidate_label: str
    window_group: str
    window_name: str
    start: str
    end: str
    result: BacktestResult


def current_shortlist() -> list[CandidateSpec]:
    return [
        CandidateSpec(
            symbol="BTCUSDT",
            candidate=Candidate(
                symbol="BTCUSDT",
                interval="4h",
                strategy_name="pullback",
                fast_window=20,
                slow_window=50,
                trend_window=100,
                pullback_window=12,
                min_pullback_pct=0.02,
                stop_loss_pct=0.02,
                take_profit_pct=0.04,
                rsi_min=50.0,
                rsi_max=75.0,
                position_size_pct=0.30,
            ),
        ),
        CandidateSpec(
            symbol="ETHUSDT",
            candidate=Candidate(
                symbol="ETHUSDT",
                interval="4h",
                strategy_name="pullback",
                fast_window=15,
                slow_window=50,
                trend_window=50,
                pullback_window=6,
                min_pullback_pct=0.01,
                stop_loss_pct=0.02,
                take_profit_pct=0.06,
                rsi_min=50.0,
                rsi_max=75.0,
                position_size_pct=0.30,
                trailing_stop_pct=0.005,
                trailing_activation_pct=0.006,
            ),
        ),
        CandidateSpec(
            symbol="SOLUSDT",
            candidate=Candidate(
                symbol="SOLUSDT",
                interval="4h",
                strategy_name="pullback",
                fast_window=15,
                slow_window=50,
                trend_window=50,
                pullback_window=6,
                min_pullback_pct=0.01,
                stop_loss_pct=0.02,
                take_profit_pct=0.04,
                rsi_min=50.0,
                rsi_max=75.0,
                position_size_pct=0.30,
            ),
        ),
    ]


def slice_windows(candles: list[Candle], window_size: int, max_windows: int) -> list[tuple[str, list[Candle]]]:
    windows: list[tuple[str, list[Candle]]] = []
    total = len(candles)
    for offset in range(max_windows):
        end = total - offset * window_size
        start = end - window_size
        if start < 0:
            break
        windows.append((f"window_{offset + 1}", candles[start:end]))
    return windows


def run_candidate_windows(
    spec: CandidateSpec,
    candles: list[Candle],
    initial_cash: float,
    window_groups: list[tuple[str, int, int]],
) -> list[RollingResult]:
    rows: list[RollingResult] = []
    strategy = build_strategy(spec.candidate)
    risk = build_risk(spec.candidate)
    config = BacktestConfig(initial_cash=initial_cash, symbol=spec.symbol)

    for group_name, window_size, max_windows in window_groups:
        for window_name, window_candles in slice_windows(candles, window_size=window_size, max_windows=max_windows):
            result = Backtester(strategy=strategy, risk_config=risk, config=config).run(window_candles)
            rows.append(
                RollingResult(
                    symbol=spec.symbol,
                    interval=spec.candidate.interval,
                    candidate_label=spec.candidate.label,
                    window_group=group_name,
                    window_name=window_name,
                    start=result.first_candle,
                    end=result.last_candle,
                    result=result,
                )
            )
    return rows


def summarize(rows: list[RollingResult]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    keys = sorted({(row.symbol, row.window_group) for row in rows})
    for symbol, window_group in keys:
        group_rows = [row for row in rows if row.symbol == symbol and row.window_group == window_group]
        returns = [row.result.return_pct for row in group_rows]
        drawdowns = [row.result.max_drawdown_pct for row in group_rows]
        summaries.append(
            {
                "symbol": symbol,
                "window_group": window_group,
                "windows": len(group_rows),
                "positive_windows": sum(1 for value in returns if value > 0),
                "average_return": sum(returns) / len(returns) if returns else 0.0,
                "worst_return": min(returns, default=0.0),
                "best_return": max(returns, default=0.0),
                "worst_drawdown": max(drawdowns, default=0.0),
                "total_trades": sum(row.result.closed_trades for row in group_rows),
            }
        )
    return summaries


def write_csv(rows: list[RollingResult], summary_rows: list[dict[str, object]], output_dir: Path) -> tuple[Path, Path]:
    detail_path = output_dir / "rolling_validation_details.csv"
    summary_path = output_dir / "rolling_validation_summary.csv"
    output_dir.mkdir(parents=True, exist_ok=True)

    with detail_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "symbol",
                "interval",
                "candidate",
                "window_group",
                "window",
                "start",
                "end",
                "return_pct",
                "buy_hold_pct",
                "max_drawdown_pct",
                "closed_trades",
                "win_rate",
                "risk_status",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "symbol": row.symbol,
                    "interval": row.interval,
                    "candidate": row.candidate_label,
                    "window_group": row.window_group,
                    "window": row.window_name,
                    "start": row.start,
                    "end": row.end,
                    "return_pct": f"{row.result.return_pct:.8f}",
                    "buy_hold_pct": f"{row.result.buy_and_hold_return_pct:.8f}",
                    "max_drawdown_pct": f"{row.result.max_drawdown_pct:.8f}",
                    "closed_trades": row.result.closed_trades,
                    "win_rate": f"{row.result.win_rate:.8f}",
                    "risk_status": row.result.risk_status,
                }
            )

    with summary_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "symbol",
                "window_group",
                "windows",
                "positive_windows",
                "average_return",
                "worst_return",
                "best_return",
                "worst_drawdown",
                "total_trades",
            ],
        )
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)

    return detail_path, summary_path


def write_html(summary_rows: list[dict[str, object]], detail_rows: list[RollingResult], output_dir: Path, detail_csv: Path, summary_csv: Path) -> Path:
    summary_html_rows: list[str] = []
    for row in summary_rows:
        avg = float(row["average_return"])
        worst = float(row["worst_return"])
        summary_html_rows.append(
            "<tr>"
            f"<td>{escape(str(row['symbol']))}</td>"
            f"<td>{escape(str(row['window_group']))}</td>"
            f"<td>{row['positive_windows']}/{row['windows']}</td>"
            f'<td class="{"positive" if avg >= 0 else "negative"}">{pct(avg)}</td>'
            f'<td class="{"positive" if worst >= 0 else "negative"}">{pct(worst)}</td>'
            f"<td>{pct(float(row['best_return']))}</td>"
            f'<td class="negative">-{pct(float(row["worst_drawdown"]))}</td>'
            f"<td>{row['total_trades']}</td>"
            "</tr>"
        )

    detail_html_rows: list[str] = []
    for row in detail_rows:
        result_class = "positive" if row.result.return_pct >= 0 else "negative"
        detail_html_rows.append(
            "<tr>"
            f"<td>{escape(row.symbol)}</td>"
            f"<td>{escape(row.window_group)}</td>"
            f"<td>{escape(row.window_name)}</td>"
            f"<td>{escape(row.start)}</td>"
            f"<td>{escape(row.end)}</td>"
            f'<td class="{result_class}">{pct(row.result.return_pct)}</td>'
            f"<td>{pct(row.result.buy_and_hold_return_pct)}</td>"
            f'<td class="negative">-{pct(row.result.max_drawdown_pct)}</td>'
            f"<td>{row.result.closed_trades}</td>"
            f"<td>{pct(row.result.win_rate)}</td>"
            f"<td>{escape(row.result.risk_status)}</td>"
            "</tr>"
        )

    path = output_dir / "rolling_validation.html"
    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Validacion rolling</title>
  <style>
    body {{ margin: 0; background: #f6f8fb; color: #172033; font-family: Segoe UI, Arial, sans-serif; }}
    header {{ background: #101827; color: white; padding: 28px 40px; }}
    main {{ width: min(1320px, calc(100% - 32px)); margin: 24px auto 48px; }}
    .panel {{ background: white; border: 1px solid #d9e1ec; border-radius: 8px; padding: 18px; margin-bottom: 18px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 980px; }}
    th, td {{ border-bottom: 1px solid #d9e1ec; padding: 10px; text-align: left; font-size: 14px; vertical-align: top; }}
    th {{ color: #61708a; font-size: 12px; text-transform: uppercase; background: #fbfdff; }}
    a {{ color: #2563eb; font-weight: 600; text-decoration: none; }}
    .positive {{ color: #16805a; font-weight: 700; }}
    .negative {{ color: #c2413d; font-weight: 700; }}
    .note {{ color: #61708a; }}
  </style>
</head>
<body>
  <header>
    <h1>Validacion rolling</h1>
    <p>Candidatos 4h por activo, evaluados en ventanas de 30, 60 y 90 dias. Dinero ficticio, sin ordenes reales.</p>
  </header>
  <main>
    <section class="panel">
      <p><a href="{escape(summary_csv.name)}">CSV resumen</a> · <a href="{escape(detail_csv.name)}">CSV detalle</a></p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Activo</th>
              <th>Ventana</th>
              <th>Positivas</th>
              <th>Promedio</th>
              <th>Peor</th>
              <th>Mejor</th>
              <th>Peor DD</th>
              <th>Trades</th>
            </tr>
          </thead>
          <tbody>{''.join(summary_html_rows)}</tbody>
        </table>
      </div>
    </section>
    <section class="panel">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Activo</th>
              <th>Grupo</th>
              <th>Ventana</th>
              <th>Inicio</th>
              <th>Fin</th>
              <th>Bot</th>
              <th>Buy/Hold</th>
              <th>Drawdown</th>
              <th>Trades</th>
              <th>Win rate</th>
              <th>Riesgo</th>
            </tr>
          </thead>
          <tbody>{''.join(detail_html_rows)}</tbody>
        </table>
      </div>
      <p class="note">Si una estrategia falla en varias ventanas, no esta lista para paper trading.</p>
    </section>
  </main>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rolling validation for selected per-asset candidates.")
    parser.add_argument("--history-limit", type=int, default=2190)
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--output-dir", default="reports\\rolling_validation_shortlist")
    parser.add_argument("--write-detail-reports", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    window_groups = [
        ("30d", 180, 12),
        ("60d", 360, 6),
        ("90d", 540, 4),
    ]
    rows: list[RollingResult] = []

    for spec in current_shortlist():
        candles = load_or_fetch(
            symbol=spec.symbol,
            interval=spec.candidate.interval,
            limit=args.history_limit,
        )
        candidate_rows = run_candidate_windows(
            spec=spec,
            candles=candles,
            initial_cash=args.initial_cash,
            window_groups=window_groups,
        )
        rows.extend(candidate_rows)

        if args.write_detail_reports:
            for row in candidate_rows:
                write_reports(
                    row.result,
                    symbol=row.symbol,
                    interval=row.interval,
                    output_dir=output_dir / safe_name(row.symbol) / row.window_group / row.window_name,
                    report_label=f"rolling_{row.window_group}_{row.window_name}",
                )

    summary_rows = summarize(rows)
    detail_csv, summary_csv = write_csv(rows, summary_rows, output_dir)
    html_path = write_html(summary_rows, rows, output_dir, detail_csv=detail_csv, summary_csv=summary_csv)

    print("Validacion rolling:")
    for row in summary_rows:
        print(
            f"- {row['symbol']} {row['window_group']}: "
            f"{row['positive_windows']}/{row['windows']} positivas | "
            f"prom {pct(float(row['average_return']))} | "
            f"peor {pct(float(row['worst_return']))} | "
            f"DD -{pct(float(row['worst_drawdown']))}"
        )

    print(f"\nRolling HTML: {html_path.resolve()}")
    print(f"Resumen CSV:  {summary_csv.resolve()}")
    print(f"Detalle CSV:  {detail_csv.resolve()}")


if __name__ == "__main__":
    main()
