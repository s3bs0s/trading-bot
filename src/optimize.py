"""Parameter optimizer for the educational crypto simulator."""

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
from src.strategy import MovingAverageCrossover, PullbackInUptrend, RangeBreakoutInTrend


@dataclass(frozen=True)
class Candidate:
    symbol: str
    interval: str
    strategy_name: str
    fast_window: int
    slow_window: int
    trend_window: int
    pullback_window: int
    min_pullback_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    rsi_min: float
    rsi_max: float
    position_size_pct: float
    volume_window: int = 20
    min_volume_ratio: float = 1.2
    trailing_stop_pct: float = 0.0
    trailing_activation_pct: float = 0.0

    @property
    def label(self) -> str:
        trailing = (
            f"_tr{self.trailing_stop_pct:.3f}_act{self.trailing_activation_pct:.3f}"
            if self.trailing_stop_pct > 0
            else ""
        )
        if self.strategy_name == "pullback":
            return (
                f"pullback_f{self.fast_window}_t{self.trend_window}_pb{self.pullback_window}_"
                f"p{self.min_pullback_pct:.3f}_sl{self.stop_loss_pct:.2f}_tp{self.take_profit_pct:.2f}_"
                f"rsi{int(self.rsi_min)}-{int(self.rsi_max)}{trailing}"
            )
        if self.strategy_name == "breakout":
            return (
                f"breakout_f{self.fast_window}_t{self.trend_window}_bo{self.pullback_window}_"
                f"buf{self.min_pullback_pct:.3f}_sl{self.stop_loss_pct:.2f}_tp{self.take_profit_pct:.2f}_"
                f"rsi{int(self.rsi_min)}-{int(self.rsi_max)}_vol{self.min_volume_ratio:.1f}{trailing}"
            )
        return (
            f"crossover_f{self.fast_window}_s{self.slow_window}_t{self.trend_window}_"
            f"sl{self.stop_loss_pct:.2f}_tp{self.take_profit_pct:.2f}_rsi{int(self.rsi_min)}-{int(self.rsi_max)}{trailing}"
        )


@dataclass(frozen=True)
class CandidateResult:
    candidate: Candidate
    result: BacktestResult
    score: float


def build_strategy(candidate: Candidate):
    if candidate.strategy_name == "pullback":
        return PullbackInUptrend(
            fast_window=candidate.fast_window,
            trend_window=candidate.trend_window,
            pullback_window=candidate.pullback_window,
            min_pullback_pct=candidate.min_pullback_pct,
        )

    if candidate.strategy_name == "breakout":
        return RangeBreakoutInTrend(
            fast_window=candidate.fast_window,
            trend_window=candidate.trend_window,
            breakout_window=candidate.pullback_window,
            breakout_buffer_pct=candidate.min_pullback_pct,
            volume_window=candidate.volume_window,
            min_volume_ratio=candidate.min_volume_ratio,
        )

    return MovingAverageCrossover(
        fast_window=candidate.fast_window,
        slow_window=candidate.slow_window,
    )


def build_risk(candidate: Candidate) -> RiskConfig:
    return RiskConfig(
        stop_loss_pct=candidate.stop_loss_pct,
        take_profit_pct=candidate.take_profit_pct,
        trailing_stop_pct=candidate.trailing_stop_pct,
        trailing_activation_pct=candidate.trailing_activation_pct,
        max_drawdown_pct=0.12,
        max_consecutive_losses=3,
        loss_streak_cooldown_bars=72,
        require_price_above_trend=True,
        trend_filter_window=candidate.trend_window,
        require_rsi_confirmation=True,
        rsi_window=14,
        rsi_min=candidate.rsi_min,
        rsi_max=candidate.rsi_max,
        position_size_pct=candidate.position_size_pct,
    )


def score_result(result: BacktestResult, min_trades: int) -> float:
    score = result.return_pct
    score -= result.max_drawdown_pct * 1.25

    if result.closed_trades < min_trades:
        score -= 0.02

    if result.open_position:
        score -= 0.005

    if not result.risk_status.startswith("Normal"):
        score -= 0.005

    if result.return_pct < 0:
        score -= 0.02

    return score


def generate_candidates(symbols: list[str], intervals: list[str], strategies: set[str], profile: str) -> list[Candidate]:
    candidates: list[Candidate] = []

    if profile == "quick":
        pullback_fast = [15, 20]
        pullback_trend = [50, 100]
        pullback_windows = [6, 12]
        pullback_depths = [0.01, 0.02]
        breakout_fast = [8, 10]
        breakout_trend = [30, 50]
        breakout_windows = [6, 12]
        breakout_buffers = [0.0, 0.001, 0.002, 0.003]
        volume_ratios = [1.0, 1.2, 1.5]
        stops = [0.02]
        takes = [0.04, 0.06, 0.08]
        rsi_ranges = [(50.0, 75.0), (50.0, 80.0)]
        trailing_pairs = [(0.0, 0.0), (0.005, 0.006), (0.01, 0.01), (0.015, 0.01)]
    else:
        pullback_fast = [10, 15, 20]
        pullback_trend = [50, 100, 200]
        pullback_windows = [6, 12]
        pullback_depths = [0.01, 0.02]
        breakout_fast = [8, 10, 15]
        breakout_trend = [30, 50, 100]
        breakout_windows = [6, 12, 18]
        breakout_buffers = [0.0, 0.001, 0.002, 0.003, 0.005]
        volume_ratios = [1.0, 1.2, 1.5]
        stops = [0.015, 0.02, 0.03]
        takes = [0.025, 0.04, 0.06]
        rsi_ranges = [(45.0, 75.0), (50.0, 75.0), (50.0, 80.0)]
        trailing_pairs = [(0.0, 0.0), (0.005, 0.006), (0.008, 0.008), (0.01, 0.01), (0.015, 0.01), (0.02, 0.015)]

    for symbol in symbols:
        for interval in intervals:
            if "pullback" in strategies:
                for fast in pullback_fast:
                    for trend in pullback_trend:
                        if fast >= trend:
                            continue
                        for pullback_window in pullback_windows:
                            for min_pullback in pullback_depths:
                                for stop_loss in stops:
                                    for take_profit in takes:
                                        for rsi_min, rsi_max in rsi_ranges:
                                            for trailing_stop, trailing_activation in trailing_pairs:
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
                                                        stop_loss_pct=stop_loss,
                                                        take_profit_pct=take_profit,
                                                        rsi_min=rsi_min,
                                                        rsi_max=rsi_max,
                                                        position_size_pct=0.30,
                                                        trailing_stop_pct=trailing_stop,
                                                        trailing_activation_pct=trailing_activation,
                                                    )
                                                )

            if "breakout" in strategies:
                for fast in breakout_fast:
                    for trend in breakout_trend:
                        if fast >= trend:
                            continue
                        for breakout_window in breakout_windows:
                            for breakout_buffer in breakout_buffers:
                                for volume_ratio in volume_ratios:
                                    for stop_loss in stops:
                                        for take_profit in takes:
                                            for rsi_min, rsi_max in rsi_ranges:
                                                for trailing_stop, trailing_activation in trailing_pairs:
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
                                                            stop_loss_pct=stop_loss,
                                                            take_profit_pct=take_profit,
                                                            rsi_min=rsi_min,
                                                            rsi_max=rsi_max,
                                                            position_size_pct=0.30,
                                                            volume_window=20,
                                                            min_volume_ratio=volume_ratio,
                                                            trailing_stop_pct=trailing_stop,
                                                            trailing_activation_pct=trailing_activation,
                                                        )
                                                    )

            if "crossover" in strategies:
                for fast in [10, 20]:
                    for slow in [30, 50]:
                        if fast >= slow:
                            continue
                        for trend in pullback_trend:
                            if fast >= trend:
                                continue
                            for stop_loss in stops:
                                for take_profit in takes:
                                    for rsi_min, rsi_max in rsi_ranges:
                                        candidates.append(
                                            Candidate(
                                                symbol=symbol,
                                                interval=interval,
                                                strategy_name="crossover",
                                                fast_window=fast,
                                                slow_window=slow,
                                                trend_window=trend,
                                                pullback_window=0,
                                                min_pullback_pct=0.0,
                                                stop_loss_pct=stop_loss,
                                                take_profit_pct=take_profit,
                                                rsi_min=rsi_min,
                                                rsi_max=rsi_max,
                                                position_size_pct=0.30,
                                            )
                                        )

    return candidates


def run_candidate(candidate: Candidate, candles: list[Candle], initial_cash: float, min_trades: int) -> CandidateResult:
    strategy = build_strategy(candidate)
    risk = build_risk(candidate)
    config = BacktestConfig(initial_cash=initial_cash, symbol=candidate.symbol)
    result = Backtester(strategy=strategy, risk_config=risk, config=config).run(candles)
    return CandidateResult(candidate=candidate, result=result, score=score_result(result, min_trades=min_trades))


def write_results_csv(results: list[CandidateResult], path: Path) -> None:
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
                "return_pct",
                "buy_hold_pct",
                "max_drawdown_pct",
                "closed_trades",
                "win_rate",
                "open_position",
                "floating_pnl",
                "fast",
                "slow",
                "trend",
                "pullback_window",
                "min_pullback_pct",
                "stop_loss_pct",
                "take_profit_pct",
                "trailing_stop_pct",
                "trailing_activation_pct",
                "rsi_min",
                "rsi_max",
                "volume_window",
                "min_volume_ratio",
            ],
        )
        writer.writeheader()
        for rank, candidate_result in enumerate(results, start=1):
            candidate = candidate_result.candidate
            result = candidate_result.result
            writer.writerow(
                {
                    "rank": rank,
                    "score": f"{candidate_result.score:.8f}",
                    "symbol": candidate.symbol,
                    "interval": candidate.interval,
                    "strategy": candidate.strategy_name,
                    "return_pct": f"{result.return_pct:.8f}",
                    "buy_hold_pct": f"{result.buy_and_hold_return_pct:.8f}",
                    "max_drawdown_pct": f"{result.max_drawdown_pct:.8f}",
                    "closed_trades": result.closed_trades,
                    "win_rate": f"{result.win_rate:.8f}",
                    "open_position": result.open_position,
                    "floating_pnl": f"{result.floating_pnl:.8f}",
                    "fast": candidate.fast_window,
                    "slow": candidate.slow_window,
                    "trend": candidate.trend_window,
                    "pullback_window": candidate.pullback_window,
                    "min_pullback_pct": f"{candidate.min_pullback_pct:.8f}",
                    "stop_loss_pct": f"{candidate.stop_loss_pct:.8f}",
                    "take_profit_pct": f"{candidate.take_profit_pct:.8f}",
                    "trailing_stop_pct": f"{candidate.trailing_stop_pct:.8f}",
                    "trailing_activation_pct": f"{candidate.trailing_activation_pct:.8f}",
                    "rsi_min": candidate.rsi_min,
                    "rsi_max": candidate.rsi_max,
                    "volume_window": candidate.volume_window,
                    "min_volume_ratio": f"{candidate.min_volume_ratio:.8f}",
                }
            )


def write_results_html(results: list[CandidateResult], path: Path, csv_name: str) -> None:
    rows: list[str] = []
    for rank, candidate_result in enumerate(results[:25], start=1):
        candidate = candidate_result.candidate
        result = candidate_result.result
        result_class = "positive" if result.return_pct >= 0 else "negative"
        rows.append(
            "<tr>"
            f"<td>{rank}</td>"
            f"<td>{escape(candidate.symbol)}</td>"
            f"<td>{escape(candidate.interval)}</td>"
            f"<td>{escape(candidate.strategy_name)}</td>"
            f'<td class="{result_class}">{pct(result.return_pct)}</td>'
            f"<td>{pct(result.buy_and_hold_return_pct)}</td>"
            f'<td class="negative">-{pct(result.max_drawdown_pct)}</td>'
            f"<td>{result.closed_trades}</td>"
            f"<td>{pct(result.win_rate)}</td>"
            f"<td>{'SI' if result.open_position else 'NO'}</td>"
            f"<td>{candidate.fast_window}/{candidate.slow_window}/{candidate.trend_window}</td>"
            f"<td>{candidate.pullback_window}</td>"
            f"<td>{pct(candidate.stop_loss_pct)} / {pct(candidate.take_profit_pct)}</td>"
            f"<td>{pct(candidate.trailing_stop_pct)} / {pct(candidate.trailing_activation_pct)}</td>"
            f"<td>{candidate.rsi_min:.0f}-{candidate.rsi_max:.0f}</td>"
            f"<td>{candidate.min_volume_ratio:.1f}</td>"
            f"<td>{candidate_result.score:.4f}</td>"
            "</tr>"
        )

    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Optimizador crypto-bot</title>
  <style>
    body {{
      margin: 0;
      background: #f6f8fb;
      color: #172033;
      font-family: Segoe UI, Arial, sans-serif;
    }}
    header {{
      background: #101827;
      color: white;
      padding: 28px 40px;
    }}
    main {{
      width: min(1280px, calc(100% - 32px));
      margin: 24px auto 48px;
    }}
    .panel {{
      background: white;
      border: 1px solid #d9e1ec;
      border-radius: 8px;
      padding: 18px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 1200px;
    }}
    .table-wrap {{
      overflow-x: auto;
    }}
    th, td {{
      border-bottom: 1px solid #d9e1ec;
      padding: 10px;
      text-align: left;
      font-size: 14px;
      vertical-align: top;
    }}
    th {{
      color: #61708a;
      font-size: 12px;
      text-transform: uppercase;
      background: #fbfdff;
    }}
    a {{ color: #2563eb; font-weight: 600; text-decoration: none; }}
    .positive {{ color: #16805a; font-weight: 700; }}
    .negative {{ color: #c2413d; font-weight: 700; }}
    .note {{
      color: #61708a;
      margin-top: 12px;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Optimizador crypto-bot</h1>
    <p>Ranking educativo. Dinero ficticio, sin API keys, sin ordenes reales.</p>
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
              <th>Bot</th>
              <th>Buy/Hold</th>
              <th>Drawdown</th>
              <th>Trades</th>
              <th>Win rate</th>
              <th>Abierta</th>
              <th>MA fast/slow/trend</th>
              <th>Pullback</th>
              <th>SL / TP</th>
              <th>Trail / Act</th>
              <th>RSI</th>
              <th>Vol</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>
            {''.join(rows)}
          </tbody>
        </table>
      </div>
      <p class="note">El score penaliza drawdown, pocos trades, perdida total y posiciones abiertas. No garantiza resultados futuros.</p>
    </section>
  </main>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optimize educational crypto bot parameters.")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT", help="Comma-separated symbols")
    parser.add_argument("--intervals", default="4h", help="Comma-separated intervals")
    parser.add_argument("--limit", type=int, default=540, help="Candles per symbol/interval")
    parser.add_argument("--initial-cash", type=float, default=1000.0, help="Fictitious initial USDT")
    parser.add_argument("--min-trades", type=int, default=3, help="Penalty threshold for too few trades")
    parser.add_argument("--top", type=int, default=5, help="Detailed reports to write for top candidates")
    parser.add_argument("--strategies", default="pullback,breakout,crossover", help="Comma-separated strategies")
    parser.add_argument("--profile", choices=["quick", "full"], default="quick", help="Search size")
    parser.add_argument("--output-dir", default="reports\\optimizer", help="Output directory")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    intervals = [interval.strip() for interval in args.intervals.split(",") if interval.strip()]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    strategies = {strategy.strip() for strategy in args.strategies.split(",") if strategy.strip()}
    candidates = generate_candidates(symbols=symbols, intervals=intervals, strategies=strategies, profile=args.profile)
    candles_by_market: dict[tuple[str, str], list[Candle]] = {}
    results: list[CandidateResult] = []

    print(f"Probando {len(candidates)} combinaciones...")
    for candidate in candidates:
        market_key = (candidate.symbol, candidate.interval)
        if market_key not in candles_by_market:
            candles_by_market[market_key] = load_or_fetch(
                symbol=candidate.symbol,
                interval=candidate.interval,
                limit=args.limit,
            )

        try:
            results.append(
                run_candidate(
                    candidate=candidate,
                    candles=candles_by_market[market_key],
                    initial_cash=args.initial_cash,
                    min_trades=args.min_trades,
                )
            )
        except ValueError:
            continue

    results.sort(key=lambda item: item.score, reverse=True)

    csv_path = output_dir / "optimizer_results.csv"
    html_path = output_dir / "optimizer_results.html"
    write_results_csv(results, csv_path)
    write_results_html(results, html_path, csv_name=csv_path.name)

    for rank, candidate_result in enumerate(results[: args.top], start=1):
        candidate = candidate_result.candidate
        detailed_dir = output_dir / f"top_{rank}_{safe_name(candidate.symbol)}_{safe_name(candidate.interval)}"
        write_reports(
            candidate_result.result,
            symbol=candidate.symbol,
            interval=candidate.interval,
            output_dir=detailed_dir,
            report_label=candidate.label,
        )

    print("\nMejores resultados:")
    for rank, candidate_result in enumerate(results[:10], start=1):
        candidate = candidate_result.candidate
        result = candidate_result.result
        print(
            f"{rank}. {candidate.symbol} {candidate.interval} {candidate.label} | "
            f"bot {pct(result.return_pct)} | DD -{pct(result.max_drawdown_pct)} | "
            f"trades {result.closed_trades} | abierta {'SI' if result.open_position else 'NO'} | "
            f"score {candidate_result.score:.4f}"
        )

    print(f"\nRanking HTML: {html_path.resolve()}")
    print(f"Ranking CSV:  {csv_path.resolve()}")


if __name__ == "__main__":
    main()
