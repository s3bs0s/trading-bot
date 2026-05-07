"""Render web entrypoint for the paper trading simulator.

This exposes a tiny HTTP server for Render health checks while a background
thread runs the paper trading loop with fictitious money only.
"""

from __future__ import annotations

import json
import mimetypes
import os
import threading
import traceback
from argparse import Namespace
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import sleep
from urllib.parse import unquote, urlparse

from src.paper import run_once
from src.paper_service import PaperServiceConfig, last_equity, load_config


@dataclass
class AppStatus:
    started_at: str
    cycles: int = 0
    last_check_at: str = ""
    last_success_at: str = ""
    last_error_at: str = ""
    last_error: str = ""
    latest_report: str = ""
    latest_csv: str = ""
    state_file: str = ""
    symbol: str = ""
    interval: str = ""
    preset: str = ""
    last_action: str = "START"
    processed_last_cycle: int = 0
    equity: float = 0.0


STATUS = AppStatus(started_at="")
STATUS_LOCK = threading.Lock()
STOP_EVENT = threading.Event()


def utc_text() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def apply_env_overrides(config: PaperServiceConfig) -> PaperServiceConfig:
    values = asdict(config)
    env_map = {
        "PAPER_PRESET": ("preset", str),
        "PAPER_INITIAL_CASH": ("initial_cash", float),
        "PAPER_FEE_RATE": ("fee_rate", float),
        "PAPER_STATE_DIR": ("state_dir", str),
        "PAPER_REPORT_DIR": ("report_dir", str),
        "PAPER_BOOTSTRAP_HISTORY": ("bootstrap_history", int),
        "PAPER_SLEEP_SECONDS": ("sleep_seconds", int),
        "PAPER_ERROR_SLEEP_SECONDS": ("error_sleep_seconds", int),
    }
    for env_name, (field_name, parser) in env_map.items():
        raw_value = os.getenv(env_name)
        if raw_value not in (None, ""):
            values[field_name] = parser(raw_value)
    return PaperServiceConfig(**values)


def load_render_config() -> PaperServiceConfig:
    config_path = Path(os.getenv("PAPER_CONFIG", "config/paper.example.json"))
    return apply_env_overrides(load_config(config_path))


def paper_args(config: PaperServiceConfig) -> Namespace:
    return Namespace(
        preset=config.preset,
        initial_cash=config.initial_cash,
        fee_rate=config.fee_rate,
        state_dir=config.state_dir,
        report_dir=config.report_dir,
        bootstrap_history=config.bootstrap_history,
        reset=False,
    )


def update_status(**changes: object) -> None:
    with STATUS_LOCK:
        for name, value in changes.items():
            setattr(STATUS, name, value)


def snapshot_status() -> dict[str, object]:
    with STATUS_LOCK:
        payload = asdict(STATUS)
    payload["ok"] = not bool(payload["last_error"])
    return payload


def paper_loop(config: PaperServiceConfig) -> None:
    while not STOP_EVENT.is_set():
        try:
            html_path, csv_path, state_file, processed, state = run_once(paper_args(config))
            update_status(
                cycles=snapshot_status()["cycles"] + 1,
                last_check_at=utc_text(),
                last_success_at=utc_text(),
                last_error="",
                latest_report=str(html_path),
                latest_csv=str(csv_path),
                state_file=str(state_file),
                symbol=state.symbol,
                interval=state.interval,
                preset=state.preset,
                last_action=state.last_action,
                processed_last_cycle=processed,
                equity=last_equity(state),
            )
        except Exception as error:
            update_status(
                cycles=snapshot_status()["cycles"] + 1,
                last_check_at=utc_text(),
                last_error_at=utc_text(),
                last_error=f"{type(error).__name__}: {error}",
            )
            traceback.print_exc()
            sleep(max(10, config.error_sleep_seconds))
            continue

        STOP_EVENT.wait(max(30, config.sleep_seconds))


def report_path_from_status() -> Path | None:
    latest_report = snapshot_status().get("latest_report")
    if not latest_report:
        return None
    path = Path(str(latest_report))
    if path.exists():
        return path
    return None


class RenderRequestHandler(BaseHTTPRequestHandler):
    server_version = "CryptoPaperRender/1.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def do_HEAD(self) -> None:
        path = urlparse(self.path).path
        if path in ("/health", "/status"):
            self.send_json(snapshot_status(), include_body=False)
            return
        if path == "/":
            report_path = report_path_from_status()
            if report_path is not None:
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", f"/paper/{report_path.name}")
                self.end_headers()
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path.startswith("/paper/"):
            self.send_paper_file(path.removeprefix("/paper/"), include_body=False)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self.send_json(snapshot_status())
            return
        if path == "/status":
            self.send_json(snapshot_status())
            return
        if path == "/":
            self.send_home()
            return
        if path.startswith("/paper/"):
            self.send_paper_file(path.removeprefix("/paper/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def send_json(self, payload: dict[str, object], include_body: bool = True) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def send_home(self) -> None:
        report_path = report_path_from_status()
        if report_path is not None:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", f"/paper/{report_path.name}")
            self.end_headers()
            return

        status = snapshot_status()
        body = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="15">
  <title>Paper trading iniciando</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 40px; color: #071427; }}
    code {{ background: #eef3fb; padding: 2px 6px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Paper trading iniciando</h1>
  <p>El servidor esta vivo. El reporte aparecera aqui cuando termine el primer ciclo.</p>
  <p>Ultimo chequeo: {escape(str(status.get("last_check_at") or "pendiente"))}</p>
  <p>Estado tecnico: <code>{escape(str(status.get("last_error") or "ok"))}</code></p>
</body>
</html>"""
        self.send_html(body)

    def send_html(self, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_paper_file(self, relative_path: str, include_body: bool = True) -> None:
        root = Path("reports/paper").resolve()
        target = (root / unquote(relative_path)).resolve()
        if root not in target.parents and target != root:
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)


def main() -> None:
    config = load_render_config()
    update_status(started_at=utc_text(), preset=config.preset, equity=config.initial_cash)

    worker = threading.Thread(target=paper_loop, args=(config,), daemon=True)
    worker.start()

    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), RenderRequestHandler)
    print(f"Render paper app listening on port {port}. Mode: paper trading only, no real orders.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STOP_EVENT.set()
        server.server_close()


if __name__ == "__main__":
    main()
