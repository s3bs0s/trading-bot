"""HTML and CSV reports for backtest results."""

from __future__ import annotations

import csv
from html import escape
from pathlib import Path

from src.backtest import BacktestResult, Trade


def money(value: float) -> str:
    return f"{value:,.2f}"


def pct(value: float) -> str:
    return f"{value:.2%}"


def safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in value)


def write_trade_csv(result: BacktestResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "fecha_compra",
                "precio_compra",
                "motivo_compra",
                "fecha_venta",
                "precio_venta",
                "motivo_venta",
                "cantidad",
                "ganancia_usdt",
                "ganancia_pct",
            ],
        )
        writer.writeheader()
        for trade in result.trades:
            writer.writerow(
                {
                    "fecha_compra": trade.entry_time,
                    "precio_compra": f"{trade.entry_price:.8f}",
                    "motivo_compra": trade.entry_reason,
                    "fecha_venta": trade.exit_time,
                    "precio_venta": f"{trade.exit_price:.8f}",
                    "motivo_venta": trade.exit_reason,
                    "cantidad": f"{trade.quantity:.12f}",
                    "ganancia_usdt": f"{trade.pnl:.8f}",
                    "ganancia_pct": f"{trade.return_pct:.8f}",
                }
            )


def _scale(value: float, min_value: float, max_value: float, size: float) -> float:
    if max_value == min_value:
        return size / 2
    return (value - min_value) / (max_value - min_value) * size


def _polyline(values: list[float], width: int, height: int, padding: int) -> str:
    if not values:
        return ""

    min_value = min(values)
    max_value = max(values)
    inner_width = width - padding * 2
    inner_height = height - padding * 2
    points: list[str] = []

    for index, value in enumerate(values):
        x = padding + (index / max(len(values) - 1, 1)) * inner_width
        y = padding + inner_height - _scale(value, min_value, max_value, inner_height)
        points.append(f"{x:.2f},{y:.2f}")

    return " ".join(points)


def _trade_marker_map(result: BacktestResult) -> tuple[set[str], set[str]]:
    buys = {trade.entry_time for trade in result.trades}
    sells = {trade.exit_time for trade in result.trades}
    if result.open_position:
        buys.add(result.open_entry_time)
    return buys, sells


def render_price_svg(result: BacktestResult) -> str:
    width = 980
    height = 320
    padding = 44
    closes = [point.close for point in result.equity_curve]
    polyline = _polyline(closes, width, height, padding)
    min_price = min(closes) if closes else 0.0
    max_price = max(closes) if closes else 0.0
    buys, sells = _trade_marker_map(result)
    markers: list[str] = []

    for index, point in enumerate(result.equity_curve):
        if point.date not in buys and point.date not in sells:
            continue

        x = padding + (index / max(len(result.equity_curve) - 1, 1)) * (width - padding * 2)
        y = padding + (height - padding * 2) - _scale(point.close, min_price, max_price, height - padding * 2)

        if point.date in buys:
            markers.append(
                f'<circle class="buy-marker" cx="{x:.2f}" cy="{y:.2f}" r="6">'
                f"<title>Compra {escape(point.date)} a {money(point.close)}</title></circle>"
            )
        if point.date in sells:
            markers.append(
                f'<circle class="sell-marker" cx="{x:.2f}" cy="{y:.2f}" r="6">'
                f"<title>Venta {escape(point.date)} a {money(point.close)}</title></circle>"
            )

    return f"""
    <svg viewBox="0 0 {width} {height}" role="img" aria-label="Grafica de precio con compras y ventas">
      <rect class="chart-bg" x="0" y="0" width="{width}" height="{height}" rx="8"></rect>
      <line class="grid-line" x1="{padding}" y1="{padding}" x2="{padding}" y2="{height - padding}"></line>
      <line class="grid-line" x1="{padding}" y1="{height - padding}" x2="{width - padding}" y2="{height - padding}"></line>
      <text class="axis-label" x="{padding}" y="24">Max {money(max_price)}</text>
      <text class="axis-label" x="{padding}" y="{height - 14}">Min {money(min_price)}</text>
      <polyline class="price-line" points="{polyline}"></polyline>
      {''.join(markers)}
    </svg>
    """


def render_equity_svg(result: BacktestResult) -> str:
    width = 980
    height = 260
    padding = 44
    equities = [point.equity for point in result.equity_curve]
    polyline = _polyline(equities, width, height, padding)
    min_equity = min(equities) if equities else 0.0
    max_equity = max(equities) if equities else 0.0

    return f"""
    <svg viewBox="0 0 {width} {height}" role="img" aria-label="Grafica de capital simulado">
      <rect class="chart-bg" x="0" y="0" width="{width}" height="{height}" rx="8"></rect>
      <line class="grid-line" x1="{padding}" y1="{padding}" x2="{padding}" y2="{height - padding}"></line>
      <line class="grid-line" x1="{padding}" y1="{height - padding}" x2="{width - padding}" y2="{height - padding}"></line>
      <text class="axis-label" x="{padding}" y="24">Max {money(max_equity)} USDT</text>
      <text class="axis-label" x="{padding}" y="{height - 14}">Min {money(min_equity)} USDT</text>
      <polyline class="equity-line" points="{polyline}"></polyline>
    </svg>
    """


def render_trade_rows(trades: list[Trade]) -> str:
    if not trades:
        return '<tr><td colspan="8">No hubo operaciones cerradas.</td></tr>'

    rows: list[str] = []
    for number, trade in enumerate(trades, start=1):
        result_class = "positive" if trade.pnl >= 0 else "negative"
        rows.append(
            "<tr>"
            f"<td>{number}</td>"
            f"<td>{escape(trade.entry_time)}</td>"
            f"<td>{money(trade.entry_price)}</td>"
            f"<td>{escape(trade.entry_reason)}</td>"
            f"<td>{escape(trade.exit_time)}</td>"
            f"<td>{money(trade.exit_price)}</td>"
            f"<td>{escape(trade.exit_reason)}</td>"
            f'<td class="{result_class}">{money(trade.pnl)} USDT<br><span>{pct(trade.return_pct)}</span></td>'
            "</tr>"
        )
    return "\n".join(rows)


def render_open_position(result: BacktestResult) -> str:
    if not result.open_position:
        return ""

    result_class = "positive" if result.floating_pnl >= 0 else "negative"
    return f"""
    <section class="section">
      <h2>Posicion abierta</h2>
      <div class="open-position">
        <div><span>Entrada</span><strong>{escape(result.open_entry_time)}</strong></div>
        <div><span>Precio entrada</span><strong>{money(result.open_entry_price)}</strong></div>
        <div><span>Valor actual</span><strong>{money(result.open_position_value)} USDT</strong></div>
        <div><span>PnL flotante</span><strong class="{result_class}">{money(result.floating_pnl)} USDT ({pct(result.floating_return_pct)})</strong></div>
      </div>
      <p class="muted">Esta operacion no esta cerrada. La ganancia o perdida sigue flotando hasta que haya venta.</p>
    </section>
    """


def render_html(result: BacktestResult, symbol: str, interval: str, csv_filename: str, report_label: str = "") -> str:
    result_class = "positive" if result.return_pct >= 0 else "negative"
    buy_hold_class = "positive" if result.buy_and_hold_return_pct >= 0 else "negative"
    trade_rows = render_trade_rows(result.trades)
    open_position_section = render_open_position(result)
    price_svg = render_price_svg(result)
    equity_svg = render_equity_svg(result)
    label_pill = f'<span class="pill">Configuracion: {escape(report_label)}</span>' if report_label else ""

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Backtest {escape(symbol)} {escape(interval)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f8fb;
      --panel: #ffffff;
      --ink: #172033;
      --muted: #61708a;
      --line: #d9e1ec;
      --blue: #2563eb;
      --green: #16805a;
      --red: #c2413d;
      --amber: #b26b00;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, Segoe UI, Arial, sans-serif;
      line-height: 1.45;
    }}
    header {{
      background: #101827;
      color: white;
      padding: 28px clamp(18px, 4vw, 46px);
    }}
    header h1 {{
      margin: 0 0 8px;
      font-size: clamp(28px, 4vw, 44px);
      letter-spacing: 0;
    }}
    header p {{
      margin: 0;
      color: #cbd5e1;
      max-width: 860px;
    }}
    main {{
      width: min(1180px, calc(100% - 32px));
      margin: 24px auto 48px;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 6px;
    }}
    .metric strong {{
      display: block;
      font-size: 24px;
    }}
    .positive {{ color: var(--green); }}
    .negative {{ color: var(--red); }}
    .muted {{ color: var(--muted); }}
    .section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin-top: 16px;
    }}
    .section h2 {{
      margin: 0 0 14px;
      font-size: 20px;
    }}
    .status-line {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 0 0 18px;
    }}
    .pill {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 6px 10px;
      color: var(--muted);
      background: #fbfdff;
      font-size: 13px;
    }}
    .warning {{
      border-left: 4px solid var(--amber);
      background: #fff8ea;
      padding: 12px 14px;
      border-radius: 8px;
      color: #5b3a00;
    }}
    .open-position {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }}
    .open-position div {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fbfdff;
    }}
    .open-position span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 6px;
    }}
    .open-position strong {{
      font-size: 18px;
    }}
    svg {{
      display: block;
      width: 100%;
      height: auto;
    }}
    .chart-bg {{ fill: #fbfdff; }}
    .grid-line {{ stroke: var(--line); stroke-width: 1.2; }}
    .axis-label {{
      fill: var(--muted);
      font-size: 13px;
    }}
    .price-line {{
      fill: none;
      stroke: var(--blue);
      stroke-width: 3;
      stroke-linejoin: round;
      stroke-linecap: round;
    }}
    .equity-line {{
      fill: none;
      stroke: var(--green);
      stroke-width: 3;
      stroke-linejoin: round;
      stroke-linecap: round;
    }}
    .buy-marker {{
      fill: var(--green);
      stroke: white;
      stroke-width: 2;
    }}
    .sell-marker {{
      fill: var(--red);
      stroke: white;
      stroke-width: 2;
    }}
    .legend {{
      display: flex;
      gap: 14px;
      color: var(--muted);
      font-size: 13px;
      margin-top: 10px;
    }}
    .dot {{
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      margin-right: 6px;
    }}
    .buy-dot {{ background: var(--green); }}
    .sell-dot {{ background: var(--red); }}
    .table-wrap {{
      overflow-x: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 900px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 11px 10px;
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
      background: #fbfdff;
    }}
    td span {{
      color: inherit;
      font-size: 12px;
    }}
    a {{
      color: var(--blue);
      font-weight: 600;
      text-decoration: none;
    }}
    footer {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 18px;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Backtest {escape(symbol)}</h1>
    <p>Reporte educativo con dinero ficticio. No hay API keys, no hay cuenta real y no se enviaron ordenes a ningun exchange.</p>
  </header>
  <main>
    <div class="status-line">
      <span class="pill">Modo: simulacion</span>
      <span class="pill">Temporalidad: {escape(interval)}</span>
      <span class="pill">Periodo: {escape(result.first_candle)} -> {escape(result.last_candle)}</span>
      <span class="pill">Riesgo: {escape(result.risk_status)}</span>
      {label_pill}
    </div>

    <section class="summary-grid" aria-label="Resumen del backtest">
      <div class="metric"><span>Capital inicial</span><strong>{money(result.initial_cash)} USDT</strong></div>
      <div class="metric"><span>Capital final</span><strong>{money(result.final_equity)} USDT</strong></div>
      <div class="metric"><span>Resultado bot</span><strong class="{result_class}">{pct(result.return_pct)}</strong></div>
      <div class="metric"><span>Buy and hold</span><strong class="{buy_hold_class}">{pct(result.buy_and_hold_return_pct)}</strong></div>
      <div class="metric"><span>Max drawdown</span><strong class="negative">-{pct(result.max_drawdown_pct)}</strong></div>
      <div class="metric"><span>Trades cerrados</span><strong>{result.closed_trades}</strong></div>
      <div class="metric"><span>Win rate</span><strong>{pct(result.win_rate)}</strong></div>
      <div class="metric"><span>Ultima accion</span><strong>{escape(result.last_action)}</strong></div>
      <div class="metric"><span>Posicion abierta</span><strong>{"SI" if result.open_position else "NO"}</strong></div>
    </section>

    <section class="section">
      <h2>Precio con compras y ventas</h2>
      {price_svg}
      <div class="legend">
        <span><i class="dot buy-dot"></i>Compra</span>
        <span><i class="dot sell-dot"></i>Venta</span>
      </div>
    </section>

    <section class="section">
      <h2>Capital simulado</h2>
      {equity_svg}
    </section>

    {open_position_section}

    <section class="section">
      <h2>Operaciones</h2>
      <p><a href="{escape(csv_filename)}">Abrir CSV de operaciones</a></p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Compra</th>
              <th>Precio compra</th>
              <th>Motivo compra</th>
              <th>Venta</th>
              <th>Precio venta</th>
              <th>Motivo venta</th>
              <th>Resultado</th>
            </tr>
          </thead>
          <tbody>
            {trade_rows}
          </tbody>
        </table>
      </div>
    </section>

    <section class="section warning">
      Este reporte no garantiza resultados futuros. Sirve para aprender, detectar riesgos y decidir si una estrategia merece mas pruebas.
    </section>

    <footer>
      Generado localmente por el simulador educativo crypto-bot.
    </footer>
  </main>
</body>
</html>
"""


def write_reports(
    result: BacktestResult,
    symbol: str,
    interval: str,
    output_dir: Path | str = "reports",
    report_label: str = "",
) -> tuple[Path, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    stem = f"backtest_{safe_name(symbol.upper())}_{safe_name(interval)}"
    if report_label:
        stem = f"{stem}_{safe_name(report_label)}"
    csv_path = output_path / f"{stem}.csv"
    html_path = output_path / f"{stem}.html"

    write_trade_csv(result, csv_path)
    html = render_html(
        result,
        symbol=symbol.upper(),
        interval=interval,
        csv_filename=csv_path.name,
        report_label=report_label,
    )
    html_path.write_text(html, encoding="utf-8")

    return html_path, csv_path
