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
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import sleep
from urllib.parse import unquote, urlparse

from src.env import load_local_env
from src.paper import PAPER_PRESETS, run_once
from src.paper import display_time_text
from src.paper_service import PaperServiceConfig, last_equity, load_config


DEFAULT_RENDER_PRESETS = (
    "aggressive-eth-2h",
    "active-eth-1h",
    "aggressive-eth-30m",
    "growth-eth-4h",
    "stable-sol-4h",
)

PRESET_DESCRIPTIONS = {
    "aggressive-eth-2h": {
        "title": "Base agresiva 2h",
        "summary": "Estrategia principal actual. Busca rupturas en ETH con velas de 2 horas. Opera poco, filtra mas ruido y sirve como comparacion base.",
        "risk": "Menos activa; puede pasar uno o varios dias sin operar.",
    },
    "active-eth-1h": {
        "title": "Activa ETH 1h",
        "summary": "Experimento mas activo. Busca rupturas en ETH con velas de 1 hora, stop loss, take profit y trailing stop.",
        "risk": "Mas oportunidades, pero tambien mas falsas entradas y mas comisiones simuladas.",
    },
    "aggressive-eth-30m": {
        "title": "Agresiva ETH 30m",
        "summary": "Experimento rapido. Busca rupturas en ETH con velas de 30 minutos para detectar oportunidades mas frecuentes.",
        "risk": "Mas agresiva que 1h; puede reaccionar antes, pero tambien equivocarse mas.",
    },
    "growth-eth-4h": {
        "title": "Crecimiento ETH 4h",
        "summary": "Experimento 4h orientado a mas crecimiento. Busca pullbacks en tendencia de ETH y usa una posicion ficticia mas grande por operacion.",
        "risk": "Puede ganar mas que candidatos conservadores, pero una senal mala tambien pesa mas.",
    },
    "stable-sol-4h": {
        "title": "Estable SOL 4h",
        "summary": "Candidato mas conservador por validacion rolling. Busca pullbacks en SOL con velas de 4 horas.",
        "risk": "Mas lento; pensado para comparar consistencia.",
    },
    "experimental-eth-1m": {
        "title": "Visual ETH 1m",
        "summary": "Solo para ver movimiento rapido en velas de 1 minuto.",
        "risk": "No validado para buscar ganancias; demasiado ruidoso.",
    },
}


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
    reports: dict[str, dict[str, object]] = field(default_factory=dict)


STATUS = AppStatus(started_at="")
STATUS_LOCK = threading.Lock()
STOP_EVENT = threading.Event()


def utc_text() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def local_time_text(value: object) -> str:
    return display_time_text(str(value or ""))


def apply_env_overrides(config: PaperServiceConfig, include_preset: bool = True) -> PaperServiceConfig:
    values = asdict(config)
    env_map = {
        "PAPER_INITIAL_CASH": ("initial_cash", float),
        "PAPER_FEE_RATE": ("fee_rate", float),
        "PAPER_STATE_DIR": ("state_dir", str),
        "PAPER_REPORT_DIR": ("report_dir", str),
        "PAPER_BOOTSTRAP_HISTORY": ("bootstrap_history", int),
        "PAPER_SLEEP_SECONDS": ("sleep_seconds", int),
        "PAPER_ERROR_SLEEP_SECONDS": ("error_sleep_seconds", int),
    }
    if include_preset:
        env_map["PAPER_PRESET"] = ("preset", str)

    for env_name, (field_name, parser) in env_map.items():
        raw_value = os.getenv(env_name)
        if raw_value not in (None, ""):
            values[field_name] = parser(raw_value)
    return PaperServiceConfig(**values)


def parse_preset_names(raw_value: str | None) -> list[str]:
    if not raw_value:
        return list(DEFAULT_RENDER_PRESETS)

    names = [name.strip() for name in raw_value.split(",") if name.strip()]
    return names or list(DEFAULT_RENDER_PRESETS)


def load_render_configs() -> list[PaperServiceConfig]:
    config_path = Path(os.getenv("PAPER_CONFIG", "config/paper.example.json"))
    base_config = apply_env_overrides(load_config(config_path), include_preset=False)
    preset_names = parse_preset_names(os.getenv("PAPER_PRESETS"))
    unknown_presets = sorted(set(preset_names) - set(PAPER_PRESETS))
    if unknown_presets:
        raise ValueError(f"unknown paper presets for Render: {', '.join(unknown_presets)}")
    return [replace(base_config, preset=preset) for preset in preset_names]


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


def update_report_status(preset_name: str, **changes: object) -> None:
    with STATUS_LOCK:
        current = dict(STATUS.reports.get(preset_name, {}))
        current.update(changes)
        STATUS.reports[preset_name] = current

        STATUS.cycles += 1
        STATUS.last_check_at = str(changes.get("last_check_at") or STATUS.last_check_at)
        STATUS.last_success_at = str(changes.get("last_success_at") or STATUS.last_success_at)
        STATUS.last_error_at = str(changes.get("last_error_at") or STATUS.last_error_at)
        STATUS.last_error = str(changes.get("last_error") or "")
        STATUS.latest_report = str(changes.get("latest_report") or STATUS.latest_report)
        STATUS.latest_csv = str(changes.get("latest_csv") or STATUS.latest_csv)
        STATUS.state_file = str(changes.get("state_file") or STATUS.state_file)
        STATUS.symbol = str(changes.get("symbol") or STATUS.symbol)
        STATUS.interval = str(changes.get("interval") or STATUS.interval)
        STATUS.preset = preset_name
        STATUS.last_action = str(changes.get("last_action") or STATUS.last_action)
        STATUS.processed_last_cycle = int(changes.get("processed_last_cycle") or 0)
        STATUS.equity = float(changes.get("equity") or STATUS.equity)


def snapshot_status() -> dict[str, object]:
    with STATUS_LOCK:
        payload = asdict(STATUS)
    reports = payload.get("reports", {})
    report_errors = [report.get("last_error") for report in reports.values()]
    payload["ok"] = not bool(payload["last_error"]) and not any(report_errors)
    return payload


def paper_loop(config: PaperServiceConfig) -> None:
    while not STOP_EVENT.is_set():
        had_error = False
        update_report_status(
            config.preset,
            last_check_at=utc_text(),
            last_action="CHECKING",
            preset=config.preset,
            equity=snapshot_status()["reports"].get(config.preset, {}).get("equity", config.initial_cash),
        )
        try:
            html_path, csv_path, state_file, processed, state = run_once(paper_args(config))
            now = utc_text()
            now_local = local_time_text(now)
            update_report_status(
                config.preset,
                cycles=int(snapshot_status()["reports"].get(config.preset, {}).get("cycles", 0)) + 1,
                last_check_at=now,
                last_check_local=now_local,
                last_success_at=now,
                last_success_local=now_local,
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
                trades=len(state.trades),
                open_position=state.position_qty > 0,
            )
        except Exception as error:
            had_error = True
            now = utc_text()
            now_local = local_time_text(now)
            update_report_status(
                config.preset,
                cycles=int(snapshot_status()["reports"].get(config.preset, {}).get("cycles", 0)) + 1,
                last_check_at=now,
                last_check_local=now_local,
                last_error_at=now,
                last_error_local=now_local,
                last_error=f"{type(error).__name__}: {error}",
                preset=config.preset,
            )
            traceback.print_exc()

        if had_error:
            STOP_EVENT.wait(max(10, config.error_sleep_seconds))
        else:
            STOP_EVENT.wait(max(30, config.sleep_seconds))


def report_path_from_status(preset: str | None = None) -> Path | None:
    status = snapshot_status()
    latest_report = status.get("latest_report")
    if preset is not None:
        latest_report = status.get("reports", {}).get(preset, {}).get("latest_report")
    if not latest_report:
        return None
    path = Path(str(latest_report))
    if path.exists():
        return path
    return None


def state_backup_payload() -> dict[str, object]:
    root = Path("paper_state")
    states: dict[str, object] = {}
    if root.exists():
        for path in sorted(root.glob("*.json")):
            try:
                states[path.name] = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                states[path.name] = {"error": f"invalid json: {error}"}

    return {
        "generated_at": utc_text(),
        "note": "Paper trading fictitious state only. No API keys and no real exchange orders.",
        "status": snapshot_status(),
        "states": states,
    }


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
        if path.startswith("/state/"):
            self.send_state_file(path.removeprefix("/state/"), include_body=False)
            return
        if path == "/backup":
            self.send_json(state_backup_payload(), include_body=False)
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
        if path.startswith("/state/"):
            self.send_state_file(path.removeprefix("/state/"))
            return
        if path == "/backup":
            self.send_json(state_backup_payload())
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
        status = snapshot_status()
        reports = status.get("reports", {})
        cards = []
        for preset in parse_preset_names(os.getenv("PAPER_PRESETS")):
            report = reports.get(preset, {})
            details = PRESET_DESCRIPTIONS.get(
                preset,
                {
                    "title": preset,
                    "summary": "Reporte paper trading.",
                    "risk": "Revisar resultados antes de confiar en el candidato.",
                },
            )
            latest_report = str(report.get("latest_report") or "")
            report_name = Path(latest_report).name if latest_report else ""
            report_link = f"/paper/{escape(report_name)}" if report_name else "#"
            disabled = " disabled" if not report_name else ""
            cards.append(
                f"""<article class="card">
    <div class="card-top">
      <h2>{escape(details["title"])}</h2>
      <span>{escape(str(report.get("interval") or "?"))}</span>
    </div>
    <p>{escape(details["summary"])}</p>
    <p class="risk">{escape(details["risk"])}</p>
    <dl>
      <div><dt>Ultima revision</dt><dd>{escape(str(report.get("last_success_local") or local_time_text(report.get("last_success_at"))))}</dd></div>
      <div><dt>Accion</dt><dd>{escape(str(report.get("last_action") or "START"))}</dd></div>
      <div><dt>Trades</dt><dd>{escape(str(report.get("trades") or 0))}</dd></div>
      <div><dt>Capital</dt><dd>{escape(f'{float(report.get("equity") or 0):,.2f} USDT')}</dd></div>
    </dl>
    <a class="button{disabled}" href="{report_link}">Abrir reporte</a>
  </article>"""
            )

        body = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>Trading bot paper reports</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; color: #071427; background: #f4f7fb; }}
    header {{ background: #101827; color: white; padding: 40px 56px; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 48px; }}
    h1 {{ margin: 0 0 8px; font-size: 44px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 18px; }}
    .card {{ background: white; border: 1px solid #d7e0ef; border-radius: 8px; padding: 22px; }}
    .card-top {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
    .card-top span {{ border: 1px solid #d7e0ef; border-radius: 999px; padding: 6px 10px; color: #496183; }}
    h2 {{ margin: 0; font-size: 24px; }}
    p {{ color: #415675; line-height: 1.45; }}
    .risk {{ color: #8a5a12; }}
    dl {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 20px 0; }}
    dt {{ color: #5b7194; font-size: 13px; }}
    dd {{ margin: 4px 0 0; font-weight: 700; }}
    .button {{ display: inline-block; background: #0f766e; color: white; text-decoration: none; padding: 11px 14px; border-radius: 6px; font-weight: 700; }}
    .button.disabled {{ background: #8da0bc; pointer-events: none; }}
    .note {{ margin-top: 22px; background: #fff7e8; border-left: 4px solid #b7791f; padding: 16px 18px; border-radius: 6px; }}
  </style>
</head>
<body>
  <header>
    <h1>Trading bot paper reports</h1>
    <p>Simulacion con dinero ficticio. No usa API keys, no toca Binance real y no envia ordenes reales.</p>
  </header>
  <main>
    <div class="grid">
      {''.join(cards)}
    </div>
    <div class="note">
      El reporte base cuida mas el ruido. El reporte activo busca mas oportunidades. Comparalos por varios dias antes de sacar conclusiones.
      Ultimo chequeo general: {escape(local_time_text(status.get("last_check_at")))}.
    </div>
  </main>
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

    def send_state_file(self, relative_path: str, include_body: bool = True) -> None:
        root = Path("paper_state").resolve()
        target = (root / unquote(relative_path)).resolve()
        if root not in target.parents and target != root:
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)


def main() -> None:
    load_local_env()
    configs = load_render_configs()
    update_status(
        started_at=utc_text(),
        preset=",".join(config.preset for config in configs),
        equity=sum(config.initial_cash for config in configs),
    )

    for config in configs:
        update_report_status(
            config.preset,
            last_action="START",
            preset=config.preset,
            equity=config.initial_cash,
            trades=0,
        )
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
