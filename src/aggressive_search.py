"""Aggressive-but-controlled short-term search for the simulator.

This is still backtesting only: no API keys, no exchange account, no real orders.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from html import escape
from pathlib import Path

from src.backtest import BacktestConfig, Backtester, BacktestResult
from src.data import Candle, load_or_fetch
from src.report import pct, safe_name, write_reports
from src.risk import RiskConfig
from src.strategy import PullbackInUptrend, RangeBreakoutInTrend


@dataclass(frozen=True)
class AggressiveCandidate:
    symbol: str
    interval: str
    strategy_name: str
    fast_window: int
    trend_window: int
    signal_window: int
    signal_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    trailing_stop_pct: float
    trailing_activation_pct: float
    position_size_pct: float
    rsi_min: float
    rsi_max: float
    volume_ratio: float = 1.0

    @property
    def label(self) -> str:
        if self.strategy_name == "breakout":
            return (
                f"aggr_breakout_{self.interval}_f{self.fast_window}_t{self.trend_window}_"
                f"w{self.signal_window}_buf{self.signal_pct:.3f}_sl{self.stop_loss_pct:.3f}_"
                f"tp{self.take_profit_pct:.3f}_tr{self.trailing_stop_pct:.3f}_"
                f"act{self.trailing_activation_pct:.3f}_pos{self.position_size_pct:.2f}_vol{self.volume_ratio:.1f}"
            )
        return (
            f"aggr_pullback_{self.interval}_f{self.fast_window}_t{self.trend_window}_"
            f"w{self.signal_window}_pb{self.signal_pct:.3f}_sl{self.stop_loss_pct:.3f}_"
            f"tp{self.take_profit_pct:.3f}_tr{self.trailing_stop_pct:.3f}_"
            f"act{self.trailing_activation_pct:.3f}_pos{self.position_size_pct:.2f}"
        )


@dataclass(frozen=True)
class WindowResult:
    group: str
    name: str
    result: BacktestResult


@dataclass(frozen=True)
class SearchResult:
    candidate: AggressiveCandidate
    windows: list[WindowResult]
    score: float

    @property
    def average_30d_return(self) -> float:
        values = [item.result.return_pct for item in self.windows if item.group == "30d"]
        return sum(values) / len(values) if values else 0.0

    @property
    def average_14d_return(self) -> float:
        values = [item.result.return_pct for item in self.windows if item.group == "14d"]
        return sum(values) / len(values) if values else 0.0

    @property
    def worst_return(self) -> float:
        return min((item.result.return_pct for item in self.windows), default=0.0)

    @property
    def worst_drawdown(self) -> float:
        return max((item.result.max_drawdown_pct for item in self.windows), default=0.0)

    @property
    def positive_30d(self) -> tuple[int, int]:
        values = [item.result.return_pct for item in self.windows if item.group == "30d"]
        return sum(1 for value in values if value > 0), len(values)

    @property
    def total_trades(self) -> int:
        return sum(item.result.closed_trades for item in self.windows)


def interval_days_to_candles(interval: str, days: int) -> int:
    if interval == "1h":
        return days * 24
    if interval == "2h":
        return days * 12
    if interval == "4h":
        return days * 6
    raise ValueError(f"unsupported interval: {interval}")


def generate_candidates(symbol: str, intervals: list[str], profile: str) -> list[AggressiveCandidate]:
    candidates: list[AggressiveCandidate] = []

    if profile == "quick":
        breakout_fast = [6, 8]
        breakout_trends = [30]
        breakout_windows = [4, 6]
        breakout_buffers = [0.0, 0.001]
        volume_ratios = [1.0]
        pullback_fast = [8, 10]
        pullback_trends = [30, 50]
        pullback_windows = [4, 6]
        pullback_depths = [0.005, 0.01]
        take_profits = [0.025, 0.04]
        trailing_pairs = [(0.004, 0.005)]
    else:
        breakout_fast = [6, 8, 10]
        breakout_trends = [30, 50]
        breakout_windows = [4, 6, 8]
        breakout_buffers = [0.0, 0.001]
        volume_ratios = [1.0, 1.2]
        pullback_fast = [8, 10, 15]
        pullback_trends = [30, 50]
        pullback_windows = [4, 6, 8]
        pullback_depths = [0.005, 0.01]
        take_profits = [0.025, 0.04]
        trailing_pairs = [(0.004, 0.005), (0.006, 0.006)]

    for interval in intervals:
        for fast in breakout_fast:
            for trend in breakout_trends:
                if fast >= trend:
                    continue
                for window in breakout_windows:
                    for buffer in breakout_buffers:
                        for volume_ratio in volume_ratios:
                            for take_profit in take_profits:
                                for trailing_stop, trailing_activation in trailing_pairs:
                                    candidates.append(
                                        AggressiveCandidate(
                                            symbol=symbol,
                                            interval=interval,
                                            strategy_name="breakout",
                                            fast_window=fast,
                                            trend_window=trend,
                                            signal_window=window,
                                            signal_pct=buffer,
                                            stop_loss_pct=0.025,
                                            take_profit_pct=take_profit,
                                            trailing_stop_pct=trailing_stop,
                                            trailing_activation_pct=trailing_activation,
                                            position_size_pct=0.60,
                                            rsi_min=45.0,
                                            rsi_max=82.0,
                                            volume_ratio=volume_ratio,
                                        )
                                    )

        for fast in pullback_fast:
            for trend in pullback_trends:
                if fast >= trend:
                    continue
                for window in pullback_windows:
                    for pullback in pullback_depths:
                        for take_profit in take_profits:
                            for trailing_stop, trailing_activation in trailing_pairs:
                                candidates.append(
                                    AggressiveCandidate(
                                        symbol=symbol,
                                        interval=interval,
                                        strategy_name="pullback",
                                        fast_window=fast,
                                        trend_window=trend,
                                        signal_window=window,
                                        signal_pct=pullback,
                                        stop_loss_pct=0.025,
                                        take_profit_pct=take_profit,
                                        trailing_stop_pct=trailing_stop,
                                        trailing_activation_pct=trailing_activation,
                                        position_size_pct=0.60,
                                        rsi_min=45.0,
                                        rsi_max=82.0,
                                    )
                                )

    return candidates


def build_strategy(candidate: AggressiveCandidate):
    if candidate.strategy_name == "breakout":
        return RangeBreakoutInTrend(
            fast_window=candidate.fast_window,
            trend_window=candidate.trend_window,
            breakout_window=candidate.signal_window,
            breakout_buffer_pct=candidate.signal_pct,
            volume_window=20,
            min_volume_ratio=candidate.volume_ratio,
        )

    return PullbackInUptrend(
        fast_window=candidate.fast_window,
        trend_window=candidate.trend_window,
        pullback_window=candidate.signal_window,
        min_pullback_pct=candidate.signal_pct,
    )


def build_risk(candidate: AggressiveCandidate) -> RiskConfig:
    return RiskConfig(
        stop_loss_pct=candidate.stop_loss_pct,
        take_profit_pct=candidate.take_profit_pct,
        trailing_stop_pct=candidate.trailing_stop_pct,
        trailing_activation_pct=candidate.trailing_activation_pct,
        max_drawdown_pct=0.18,
        max_consecutive_losses=4,
        loss_streak_cooldown_bars=24,
        require_price_above_trend=True,
        trend_filter_window=candidate.trend_window,
        require_rsi_confirmation=True,
        rsi_window=14,
        rsi_min=candidate.rsi_min,
        rsi_max=candidate.rsi_max,
        crash_lookback_bars=12,
        crash_block_pct=0.10,
        cooldown_bars_after_loss=1,
        position_size_pct=candidate.position_size_pct,
    )


def slice_recent_windows(candles: list[Candle], window_size: int, count: int) -> list[tuple[str, list[Candle]]]:
    windows: list[tuple[str, list[Candle]]] = []
    total = len(candles)
    for offset in range(count):
        end = total - offset * window_size
        start = end - window_size
        if start < 0:
            break
        windows.append((f"window_{offset + 1}", candles[start:end]))
    return windows


def run_candidate(candidate: AggressiveCandidate, candles: list[Candle], initial_cash: float) -> SearchResult:
    windows: list[WindowResult] = []
    strategy = build_strategy(candidate)
    risk = build_risk(candidate)
    config = BacktestConfig(initial_cash=initial_cash, symbol=candidate.symbol)

    for group, days, count in [("14d", 14, 8), ("30d", 30, 8), ("60d", 60, 4)]:
        window_size = interval_days_to_candles(candidate.interval, days)
        for name, window_candles in slice_recent_windows(candles, window_size=window_size, count=count):
            result = Backtester(strategy=strategy, risk_config=risk, config=config).run(window_candles)
            windows.append(WindowResult(group=group, name=name, result=result))

    return SearchResult(candidate=candidate, windows=windows, score=score_windows(windows))


def score_windows(windows: list[WindowResult]) -> float:
    returns_14d = [item.result.return_pct for item in windows if item.group == "14d"]
    returns_30d = [item.result.return_pct for item in windows if item.group == "30d"]
    returns_60d = [item.result.return_pct for item in windows if item.group == "60d"]
    all_returns = [item.result.return_pct for item in windows]
    all_drawdowns = [item.result.max_drawdown_pct for item in windows]
    total_trades = sum(item.result.closed_trades for item in windows)

    avg_14d = sum(returns_14d) / len(returns_14d) if returns_14d else 0.0
    avg_30d = sum(returns_30d) / len(returns_30d) if returns_30d else 0.0
    avg_60d = sum(returns_60d) / len(returns_60d) if returns_60d else 0.0
    worst_return = min(all_returns, default=0.0)
    worst_drawdown = max(all_drawdowns, default=0.0)
    positive_30d = sum(1 for value in returns_30d if value > 0)

    score = avg_30d * 2.0 + avg_14d + avg_60d * 0.5
    score += positive_30d * 0.004
    score -= worst_drawdown * 0.9

    if worst_return < -0.04:
        score -= abs(worst_return) * 1.5
    elif worst_return < 0:
        score -= abs(worst_return) * 0.5

    if total_trades < 20:
        score -= 0.03

    if any(not item.result.risk_status.startswith("Normal") for item in windows):
        score -= 0.05

    return score


def write_csv(results: list[SearchResult], path: Path) -> None:
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
                "avg_14d",
                "avg_30d",
                "worst_return",
                "worst_drawdown",
                "positive_30d",
                "total_30d",
                "total_trades",
            ],
        )
        writer.writeheader()
        for rank, result in enumerate(results, start=1):
            positive_30d, total_30d = result.positive_30d
            writer.writerow(
                {
                    "rank": rank,
                    "score": f"{result.score:.8f}",
                    "symbol": result.candidate.symbol,
                    "interval": result.candidate.interval,
                    "strategy": result.candidate.strategy_name,
                    "label": result.candidate.label,
                    "avg_14d": f"{result.average_14d_return:.8f}",
                    "avg_30d": f"{result.average_30d_return:.8f}",
                    "worst_return": f"{result.worst_return:.8f}",
                    "worst_drawdown": f"{result.worst_drawdown:.8f}",
                    "positive_30d": positive_30d,
                    "total_30d": total_30d,
                    "total_trades": result.total_trades,
                }
            )


def write_html(results: list[SearchResult], path: Path, csv_name: str) -> None:
    rows: list[str] = []
    for rank, result in enumerate(results[:30], start=1):
        positive_30d, total_30d = result.positive_30d
        rows.append(
            "<tr>"
            f"<td>{rank}</td>"
            f"<td>{escape(result.candidate.symbol)}</td>"
            f"<td>{escape(result.candidate.interval)}</td>"
            f"<td>{escape(result.candidate.strategy_name)}</td>"
            f'<td class="{"positive" if result.average_30d_return >= 0 else "negative"}">{pct(result.average_30d_return)}</td>'
            f'<td class="{"positive" if result.average_14d_return >= 0 else "negative"}">{pct(result.average_14d_return)}</td>'
            f'<td class="{"positive" if result.worst_return >= 0 else "negative"}">{pct(result.worst_return)}</td>'
            f'<td class="negative">-{pct(result.worst_drawdown)}</td>'
            f"<td>{positive_30d}/{total_30d}</td>"
            f"<td>{result.total_trades}</td>"
            f"<td>{escape(result.candidate.label)}</td>"
            f"<td>{result.score:.4f}</td>"
            "</tr>"
        )

    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Busqueda agresiva controlada</title>
  <style>
    body {{ margin: 0; background: #f6f8fb; color: #172033; font-family: Segoe UI, Arial, sans-serif; }}
    header {{ background: #101827; color: white; padding: 28px 40px; }}
    main {{ width: min(1320px, calc(100% - 32px)); margin: 24px auto 48px; }}
    .panel {{ background: white; border: 1px solid #d9e1ec; border-radius: 8px; padding: 18px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 1240px; }}
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
    <h1>Busqueda agresiva controlada</h1>
    <p>Mayor posicion por trade y foco en 14/30/60 dias. Dinero ficticio, sin ordenes reales.</p>
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
              <th>Prom 30d</th>
              <th>Prom 14d</th>
              <th>Peor ventana</th>
              <th>Peor DD</th>
              <th>30d positivas</th>
              <th>Trades</th>
              <th>Configuracion</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
      <p class="note">Esto busca mas ganancia en corto plazo, pero permite mas variacion. No es dinero real ni garantia.</p>
    </section>
  </main>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def write_top_reports(results: list[SearchResult], output_dir: Path, top: int) -> None:
    for rank, search_result in enumerate(results[:top], start=1):
        candidate = search_result.candidate
        strategy = build_strategy(candidate)
        risk = build_risk(candidate)
        candles = load_or_fetch(symbol=candidate.symbol, interval=candidate.interval, limit=interval_days_to_candles(candidate.interval, 90))
        result = Backtester(
            strategy=strategy,
            risk_config=risk,
            config=BacktestConfig(initial_cash=1000.0, symbol=candidate.symbol),
        ).run(candles)
        write_reports(
            result,
            symbol=candidate.symbol,
            interval=candidate.interval,
            output_dir=output_dir / f"top_{rank}_{safe_name(candidate.symbol)}_{safe_name(candidate.interval)}",
            report_label=candidate.label,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggressive short-term crypto bot search.")
    parser.add_argument("--symbols", default="SOLUSDT,ETHUSDT,BTCUSDT")
    parser.add_argument("--intervals", default="1h,2h,4h")
    parser.add_argument("--history-days", type=int, default=180)
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--profile", choices=["quick", "full"], default="quick")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--output-dir", default="reports\\aggressive_search")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    intervals = [interval.strip() for interval in args.intervals.split(",") if interval.strip()]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[SearchResult] = []
    for symbol in symbols:
        for interval in intervals:
            candles = load_or_fetch(
                symbol=symbol,
                interval=interval,
                limit=interval_days_to_candles(interval, args.history_days),
            )
            candidates = generate_candidates(symbol=symbol, intervals=[interval], profile=args.profile)
            print(f"Probando {symbol} {interval}: {len(candidates)} candidatos...")
            for candidate in candidates:
                try:
                    results.append(run_candidate(candidate=candidate, candles=candles, initial_cash=args.initial_cash))
                except ValueError:
                    continue

    results.sort(key=lambda item: item.score, reverse=True)
    csv_path = output_dir / "aggressive_results.csv"
    html_path = output_dir / "aggressive_results.html"
    write_csv(results, csv_path)
    write_html(results, html_path, csv_name=csv_path.name)
    write_top_reports(results, output_dir=output_dir, top=args.top)

    print("Mejores agresivos:")
    for rank, result in enumerate(results[: args.top], start=1):
        positive_30d, total_30d = result.positive_30d
        print(
            f"{rank}. {result.candidate.symbol} {result.candidate.interval} {result.candidate.strategy_name} | "
            f"prom 30d {pct(result.average_30d_return)} | prom 14d {pct(result.average_14d_return)} | "
            f"peor {pct(result.worst_return)} | DD -{pct(result.worst_drawdown)} | "
            f"30d {positive_30d}/{total_30d} | {result.candidate.label}"
        )

    print(f"\nAgresivo HTML: {html_path.resolve()}")
    print(f"Agresivo CSV:  {csv_path.resolve()}")


if __name__ == "__main__":
    main()
