"""Long-running paper trading runner.

This service still uses fictitious money only. It wraps ``src.paper`` with
configuration, log files, and retry behavior so it can run on a VPS later.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
from dataclasses import asdict, dataclass, fields
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import monotonic, sleep

from src.paper import PAPER_PRESETS, run_once


STOP_REQUESTED = False


@dataclass(frozen=True)
class PaperServiceConfig:
    preset: str = "aggressive-eth-2h"
    initial_cash: float = 1000.0
    fee_rate: float = 0.001
    state_dir: str = "paper_state"
    report_dir: str = "reports/paper"
    bootstrap_history: int = 0
    sleep_seconds: int = 60
    error_sleep_seconds: int = 60
    max_consecutive_errors: int = 10
    log_dir: str = "logs"
    log_file: str = "paper_service.log"


def load_config(path: Path) -> PaperServiceConfig:
    base = asdict(PaperServiceConfig())
    if not path.exists():
        return PaperServiceConfig(**base)

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("paper service config must be a JSON object")

    valid_fields = {field.name for field in fields(PaperServiceConfig)}
    unknown_fields = sorted(set(payload) - valid_fields)
    if unknown_fields:
        raise ValueError(f"unknown paper service config fields: {', '.join(unknown_fields)}")

    base.update(payload)
    return PaperServiceConfig(**base)


def apply_cli_overrides(config: PaperServiceConfig, args: argparse.Namespace) -> PaperServiceConfig:
    values = asdict(config)
    for name in values:
        override = getattr(args, name, None)
        if override is not None:
            values[name] = override
    return PaperServiceConfig(**values)


def setup_logger(config: PaperServiceConfig) -> tuple[logging.Logger, Path]:
    log_dir = Path(config.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / config.log_file

    logger = logging.getLogger("paper_service")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger, log_path


def install_signal_handlers(logger: logging.Logger) -> None:
    def request_stop(signum: int, _frame: object) -> None:
        global STOP_REQUESTED
        STOP_REQUESTED = True
        logger.info("Stop requested by signal %s; finishing current cycle.", signum)

    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is None:
            continue
        try:
            signal.signal(signal_value, request_stop)
        except ValueError:
            continue


def build_paper_args(config: PaperServiceConfig, reset: bool) -> argparse.Namespace:
    return argparse.Namespace(
        preset=config.preset,
        initial_cash=config.initial_cash,
        fee_rate=config.fee_rate,
        state_dir=config.state_dir,
        report_dir=config.report_dir,
        bootstrap_history=config.bootstrap_history,
        reset=reset,
    )


def wait_or_stop(seconds: int) -> None:
    deadline = monotonic() + max(1, seconds)
    while not STOP_REQUESTED and monotonic() < deadline:
        sleep(min(1.0, max(0.0, deadline - monotonic())))


def last_equity(state: object) -> float:
    equity_curve = getattr(state, "equity_curve", [])
    if equity_curve:
        return float(equity_curve[-1]["equity"])
    return float(getattr(state, "cash", 0.0))


def run_service(config: PaperServiceConfig, reset: bool = False, once: bool = False) -> int:
    global STOP_REQUESTED
    STOP_REQUESTED = False

    logger, log_path = setup_logger(config)
    install_signal_handlers(logger)

    logger.info("Paper service starting. Config=%s", asdict(config))
    logger.info("Log file: %s", log_path.resolve())
    logger.info("Mode: paper trading only; no API keys and no real orders.")

    consecutive_errors = 0
    reset_next_run = reset
    max_errors = max(1, config.max_consecutive_errors)

    while not STOP_REQUESTED:
        try:
            html_path, csv_path, state_file, processed, state = run_once(
                build_paper_args(config, reset=reset_next_run)
            )
            logger.info(
                "OK preset=%s symbol=%s interval=%s processed=%s action=%s equity=%.2f report=%s state=%s csv=%s",
                state.preset,
                state.symbol,
                state.interval,
                processed,
                state.last_action,
                last_equity(state),
                html_path.resolve(),
                state_file.resolve(),
                csv_path.resolve(),
            )
            consecutive_errors = 0
            reset_next_run = False
        except Exception:
            consecutive_errors += 1
            logger.exception("Paper service cycle failed. Consecutive errors: %s/%s", consecutive_errors, max_errors)
            reset_next_run = False
            if once or consecutive_errors >= max_errors:
                logger.critical("Paper service stopped after too many errors.")
                return 1
            wait_or_stop(max(10, config.error_sleep_seconds))
            continue

        if once:
            logger.info("One-cycle service check finished.")
            return 0

        wait_or_stop(max(30, config.sleep_seconds))

    logger.info("Paper service stopped cleanly.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run paper trading as a long-running service.")
    parser.add_argument("--config", default="config/paper.example.json")
    parser.add_argument("--preset", choices=PAPER_PRESETS)
    parser.add_argument("--initial-cash", type=float)
    parser.add_argument("--fee-rate", type=float)
    parser.add_argument("--state-dir")
    parser.add_argument("--report-dir")
    parser.add_argument("--bootstrap-history", type=int)
    parser.add_argument("--sleep-seconds", type=int)
    parser.add_argument("--error-sleep-seconds", type=int, dest="error_sleep_seconds")
    parser.add_argument("--max-consecutive-errors", type=int, dest="max_consecutive_errors")
    parser.add_argument("--log-dir")
    parser.add_argument("--log-file")
    parser.add_argument("--reset", action="store_true", help="Restart the fictitious wallet once at startup")
    parser.add_argument("--once", action="store_true", help="Run one service cycle and exit")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = apply_cli_overrides(load_config(Path(args.config)), args)
    raise SystemExit(run_service(config, reset=args.reset, once=args.once))


if __name__ == "__main__":
    main()
