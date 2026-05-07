"""Select strategy candidates per asset across multiple periods."""

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


PERIOD_LIMITS = {
    "1h": [("3m", 2160), ("6m", 4320), ("12m", 8760)],
    "4h": [("3m", 540), ("6m", 1080), ("12m", 2190)],
}


@dataclass(frozen=True)
class PeriodResult:
    period: str
    result: BacktestResult


@dataclass(frozen=True)
class SelectionResult:
    candidate: Candidate
    period_results: list[PeriodResult]
    score: float

    @property
    def average_return(self) -> float:
        return sum(item.result.return_pct for item in self.period_results) / len(self.period_results)

    @property
    def worst_return(self) -> float:
        return min(item.result.return_pct for item in self.period_results)

    @property
    def worst_drawdown(self) -> float:
        return max(item.result.max_drawdown_pct for item in self.period_results)

    @property
    def total_trades(self) -> int:
        return sum(item.result.closed_trades for item in self.period_results)

    @property
    def positive_periods(self) -> int:
        return sum(1 for item in self.period_results if item.result.return_pct > 0)


def generate_curated_candidates(symbol: str, interval: str) -> list[Candidate]:
    candidates: list[Candidate] = []

    for fast in [15, 20]:
        for trend in [50, 100]:
            if fast >= trend:
                continue
            for pullback_window in [6, 12]:
                for min_pullback in [0.01, 0.02]:
                    for take_profit in [0.04, 0.06]:
                        for trailing_stop, trailing_activation in [(0.0, 0.0), (0.005, 0.006)]:
                            candidates.append(
                                Candidate(
                                    symbol=symbol,
                                    interval=interval,
                                    strategy_name="pullback",
                                    fast_window=fast,
                                    slow_window=50,
                                    trend_window=trend,
                                    pullback_window=pullback_window,
                                    min_pullback_pct=min_pullback,
                                    stop_loss_pct=0.02,
                                    take_profit_pct=take_profit,
                                    rsi_min=50.0,
                                    rsi_max=75.0,
                                    position_size_pct=0.30,
                                    trailing_stop_pct=trailing_stop,
                                    trailing_activation_pct=trailing_activation,
                                )
                            )

    for fast in [8, 10]:
        for trend in [30, 50]:
            if fast >= trend:
                continue
            for breakout_window in [6, 12]:
                for breakout_buffer in [0.001, 0.002]:
                    for volume_ratio in [1.0, 1.2]:
                        for trailing_stop, trailing_activation in [(0.005, 0.006), (0.01, 0.01)]:
                            candidates.append(
                                Candidate(
                                    symbol=symbol,
                                    interval=interval,
                                    strategy_name="breakout",
                                    fast_window=fast,
                                    slow_window=50,
                                    trend_window=trend,
                                    pullback_window=breakout_window,
                                    min_pullback_pct=breakout_buffer,
                                    stop_loss_pct=0.02,
                                    take_profit_pct=0.04,
                                    rsi_min=50.0,
                                    rsi_max=75.0,
                                    position_size_pct=0.30,
                                    volume_window=20,
                                    min_volume_ratio=volume_ratio,
                                    trailing_stop_pct=trailing_stop,
                                    trailing_activation_pct=trailing_activation,
                                )
                            )

    return candidates


def score_periods(period_results: list[PeriodResult], min_total_trades: int) -> float:
    returns = [item.result.return_pct for item in period_results]
    drawdowns = [item.result.max_drawdown_pct for item in period_results]
    total_trades = sum(item.result.closed_trades for item in period_results)
    positive_periods = sum(1 for value in returns if value > 0)
    average_return = sum(returns) / len(returns)
    worst_return = min(returns)
    worst_drawdown = max(drawdowns)

    score = average_return
    score += worst_return * 2.0
    score -= worst_drawdown * 1.5
    score += positive_periods * 0.005

    if total_trades < min_total_trades:
        score -= 0.03

    if worst_return < 0:
        score -= abs(worst_return) * 1.5

    if any(not item.result.risk_status.startswith("Normal") for item in period_results):
        score -= 0.03

    return score


def run_candidate(candidate: Candidate, candles_by_interval: dict[str, list[Candle]], initial_cash: float, min_total_trades: int) -> SelectionResult:
    period_results: list[PeriodResult] = []
    candles = candles_by_interval[candidate.interval]

    for period, limit in PERIOD_LIMITS[candidate.interval]:
        period_candles = candles[-limit:]
        result = Backtester(
            strategy=build_strategy(candidate),
            risk_config=build_risk(candidate),
            config=BacktestConfig(initial_cash=initial_cash, symbol=candidate.symbol),
        ).run(period_candles)
        period_results.append(PeriodResult(period=period, result=result))

    return SelectionResult(
        candidate=candidate,
        period_results=period_results,
        score=score_periods(period_results, min_total_trades=min_total_trades),
    )


def write_selection_csv(results: list[SelectionResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "rank",
                "score",
                "symbol",
                "interval",
                "strategy",
                "label",
                "average_return_pct",
                "worst_return_pct",
                "worst_drawdown_pct",
                "positive_periods",
                "total_trades",
                "return_3m",
                "return_6m",
                "return_12m",
                "risk_3m",
                "risk_6m",
                "risk_12m",
            ],
        )
        writer.writeheader()
        for rank, result in enumerate(results, start=1):
            returns = {item.period: item.result.return_pct for item in result.period_results}
            risks = {item.period: item.result.risk_status for item in result.period_results}
            writer.writerow(
                {
                    "rank": rank,
                    "score": f"{result.score:.8f}",
                    "symbol": result.candidate.symbol,
                    "interval": result.candidate.interval,
                    "strategy": result.candidate.strategy_name,
                    "label": result.candidate.label,
                    "average_return_pct": f"{result.average_return:.8f}",
                    "worst_return_pct": f"{result.worst_return:.8f}",
                    "worst_drawdown_pct": f"{result.worst_drawdown:.8f}",
                    "positive_periods": result.positive_periods,
                    "total_trades": result.total_trades,
                    "return_3m": f"{returns.get('3m', 0.0):.8f}",
                    "return_6m": f"{returns.get('6m', 0.0):.8f}",
                    "return_12m": f"{returns.get('12m', 0.0):.8f}",
                    "risk_3m": risks.get("3m", ""),
                    "risk_6m": risks.get("6m", ""),
                    "risk_12m": risks.get("12m", ""),
                }
            )


def write_selection_html(results: list[SelectionResult], path: Path, csv_name: str) -> None:
    rows: list[str] = []
    for rank, result in enumerate(results[:25], start=1):
        result_class = "positive" if result.average_return >= 0 else "negative"
        worst_class = "positive" if result.worst_return >= 0 else "negative"
        returns = {item.period: item.result.return_pct for item in result.period_results}
        rows.append(
            "<tr>"
            f"<td>{rank}</td>"
            f"<td>{escape(result.candidate.symbol)}</td>"
            f"<td>{escape(result.candidate.interval)}</td>"
            f"<td>{escape(result.candidate.strategy_name)}</td>"
            f'<td class="{result_class}">{pct(result.average_return)}</td>'
            f'<td class="{worst_class}">{pct(result.worst_return)}</td>'
            f'<td class="negative">-{pct(result.worst_drawdown)}</td>'
            f"<td>{result.positive_periods}/3</td>"
            f"<td>{result.total_trades}</td>"
            f"<td>{pct(returns.get('3m', 0.0))}</td>"
            f"<td>{pct(returns.get('6m', 0.0))}</td>"
            f"<td>{pct(returns.get('12m', 0.0))}</td>"
            f"<td>{escape(result.candidate.label)}</td>"
            f"<td>{result.score:.4f}</td>"
            "</tr>"
        )

    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Selector por activo</title>
  <style>
    body {{ margin: 0; background: #f6f8fb; color: #172033; font-family: Segoe UI, Arial, sans-serif; }}
    header {{ background: #101827; color: white; padding: 28px 40px; }}
    main {{ width: min(1320px, calc(100% - 32px)); margin: 24px auto 48px; }}
    .panel {{ background: white; border: 1px solid #d9e1ec; border-radius: 8px; padding: 18px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 1280px; }}
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
    <h1>Selector por activo</h1>
    <p>Ranking por 3m, 6m y 12m. Dinero ficticio, sin API keys, sin ordenes reales.</p>
  </header>
  <main>
    <section class="panel">
      <p><a href="{escape(csv_name)}">Abrir CSV completo</a></p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Activo</th>
              <th>Intervalo</th>
              <th>Estrategia</th>
              <th>Promedio</th>
              <th>Peor periodo</th>
              <th>Peor DD</th>
              <th>Positivos</th>
              <th>Trades</th>
              <th>3m</th>
              <th>6m</th>
              <th>12m</th>
              <th>Configuracion</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
      <p class="note">El score castiga el peor periodo, drawdown, pocos trades y pausas de riesgo. No garantiza resultados futuros.</p>
    </section>
  </main>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Select per-asset crypto strategy candidates.")
    parser.add_argument("--symbols", default="ETHUSDT,BTCUSDT,SOLUSDT")
    parser.add_argument("--intervals", default="1h,4h")
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--min-total-trades", type=int, default=12)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--output-dir", default="reports\\asset_selection")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    intervals = [interval.strip() for interval in args.intervals.split(",") if interval.strip()]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_results: list[SelectionResult] = []

    for symbol in symbols:
        candles_by_interval: dict[str, list[Candle]] = {}
        for interval in intervals:
            max_limit = PERIOD_LIMITS[interval][-1][1]
            candles_by_interval[interval] = load_or_fetch(symbol=symbol, interval=interval, limit=max_limit)

        symbol_results: list[SelectionResult] = []
        candidates = [
            candidate
            for interval in intervals
            for candidate in generate_curated_candidates(symbol=symbol, interval=interval)
        ]
        print(f"Probando {symbol}: {len(candidates)} candidatos...")

        for candidate in candidates:
            try:
                symbol_results.append(
                    run_candidate(
                        candidate=candidate,
                        candles_by_interval=candles_by_interval,
                        initial_cash=args.initial_cash,
                        min_total_trades=args.min_total_trades,
                    )
                )
            except ValueError:
                continue

        symbol_results.sort(key=lambda item: item.score, reverse=True)
        all_results.extend(symbol_results)

        symbol_dir = output_dir / safe_name(symbol)
        write_selection_csv(symbol_results, symbol_dir / "selection_results.csv")
        write_selection_html(symbol_results, symbol_dir / "selection_results.html", csv_name="selection_results.csv")

        for rank, selection in enumerate(symbol_results[: args.top], start=1):
            detail_dir = symbol_dir / f"top_{rank}_{safe_name(selection.candidate.interval)}"
            for period_result in selection.period_results:
                write_reports(
                    period_result.result,
                    symbol=symbol,
                    interval=selection.candidate.interval,
                    output_dir=detail_dir / period_result.period,
                    report_label=f"{selection.candidate.label}_{period_result.period}",
                )

        print("Mejores:")
        for rank, selection in enumerate(symbol_results[: args.top], start=1):
            returns = {item.period: item.result.return_pct for item in selection.period_results}
            print(
                f"{rank}. {selection.candidate.interval} {selection.candidate.label} | "
                f"prom {pct(selection.average_return)} | peor {pct(selection.worst_return)} | "
                f"3m {pct(returns.get('3m', 0.0))} | 6m {pct(returns.get('6m', 0.0))} | "
                f"12m {pct(returns.get('12m', 0.0))}"
            )

    all_results.sort(key=lambda item: item.score, reverse=True)
    write_selection_csv(all_results, output_dir / "all_selection_results.csv")
    write_selection_html(all_results, output_dir / "all_selection_results.html", csv_name="all_selection_results.csv")

    print(f"\nResumen HTML: {(output_dir / 'all_selection_results.html').resolve()}")
    print(f"Resumen CSV:  {(output_dir / 'all_selection_results.csv').resolve()}")


if __name__ == "__main__":
    main()
