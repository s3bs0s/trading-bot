# Crypto Bot Educativo

Proyecto para aprender a construir un bot de trading de criptomonedas de forma segura.

Esta primera version es solo simulacion/backtesting:

- No usa dinero real.
- No se conecta a tu cuenta de Binance.
- No necesita API keys.
- No puede enviar ordenes reales.
- Usa datos publicos de mercado para simular compras y ventas.

## Objetivo

Aprender a responder preguntas como:

- Cuando habria comprado el bot?
- Cuando habria vendido?
- Cuanto habria ganado o perdido?
- Cuanto fue la peor caida desde el punto mas alto?
- La estrategia supero a comprar y mantener?
- Las reglas de riesgo bloquearon operaciones peligrosas?

## Primer escenario

```text
Modo: backtesting local
Activo: BTC/USDT
Capital: 1000 USDT ficticios
Temporalidad: 1 dia
Estrategia: pullback en tendencia alcista
Riesgo: stop loss, take profit, drawdown maximo y bloqueo por caida fuerte
```

## Estructura

```text
crypto-bot/
  README.md
  requirements.txt
  data/
  src/
    main.py
    data.py
    strategy.py
    backtest.py
    risk.py
    paper.py
  tests/
```

## Como ejecutarlo

Desde esta carpeta:

```powershell
python -m src.main
```

Si `python` no funciona en Windows, prueba:

```powershell
py -m src.main
```

Ejemplo con parametros:

```powershell
py -m src.main --symbol BTCUSDT --interval 1d --limit 365 --initial-cash 1000 --fast 20 --slow 50
```

La estrategia por defecto ahora es `pullback`:

```text
Compra si hay tendencia alcista, retroceso controlado y recuperacion sobre la media rapida.
```

Para comparar contra el cruce simple anterior:

```powershell
py -m src.main --strategy crossover
```

Para probar ruptura de rango en tendencia:

```powershell
py -m src.main --strategy breakout
```

Para activar trailing stop:

```powershell
py -m src.main --trailing-stop 0.005 --trailing-activation 0.006
```

Eso significa: si la operacion sube al menos 0.6%, el bot protege la ganancia y vende si el precio retrocede 0.5% desde su mejor punto.

Al correrlo, tambien se generan reportes en:

```text
reports/backtest_BTCUSDT_1d_trend200.html
reports/backtest_BTCUSDT_1d_trend200.csv
```

Abre el archivo `.html` en el navegador para ver el tablero visual.
Abre el `.csv` con Excel si quieres revisar las operaciones como tabla.

La consola imprime la ruta completa del reporte desde `C:\...`.

Si solo quieres ver la consola sin crear reportes:

```powershell
py -m src.main --no-report
```

Para comparar contra la version sin filtro de tendencia:

```powershell
py -m src.main --no-trend-filter
```

La version actual tambien usa filtro RSI antes de comprar:

```text
Compra solo si RSI esta entre 50 y 75
```

Para comparar sin RSI:

```powershell
py -m src.main --no-rsi-filter
```

## Que mirar en el resultado

```text
Capital inicial
Capital final
Resultado del bot
Resultado de buy and hold
Max drawdown
Trades ganadores y perdedores
Riesgo
Ultima accion
```

El reporte HTML muestra:

- Resumen de capital, retorno, drawdown y win rate.
- Grafica de precio reciente del mercado, aunque todavia no haya trades.
- Puntos de compra y venta sobre la grafica cuando existan.
- Grafica de capital simulado.
- Tabla de operaciones con motivo de compra y venta.
- Enlace al CSV de operaciones.

El dato mas importante al principio no es solo la ganancia. Es el riesgo:

```text
Max drawdown: cuanto cayo desde el punto mas alto
Perdedores: cuantas operaciones salieron mal
Riesgo: si el bot se pauso o bloqueo operaciones
```

## Reglas de seguridad actuales

- Usa solo una parte del capital ficticio por compra.
- Cobra una comision simulada.
- Vende si se activa stop loss.
- Vende si se activa take profit.
- Vende si se activa trailing stop, cuando esta configurado.
- Pausa si el drawdown supera el limite.
- Bloquea compras si BTC esta por debajo de su media de tendencia de 200 dias.
- Bloquea compras si el RSI esta debil o demasiado caliente.
- Bloquea compras si el mercado viene cayendo fuerte.
- Enfria el bot despues de una perdida.

## Pruebas

```powershell
py -m unittest discover -s tests
```

## Paper trading ficticio

Paper trading significa correr el bot con precios publicos recientes, pero usando una billetera falsa.

- No usa tu cuenta de Binance.
- No usa API keys.
- No envia ordenes reales.
- Guarda el estado local para no repetir la misma vela.
- Solo procesa velas cerradas.

Para correr el experimento recomendado actual:

```powershell
py -m src.paper
```

Genera:

```text
reports/paper/paper_aggressive-eth-2h_ETHUSDT_2h.html
reports/paper/paper_aggressive-eth-2h_ETHUSDT_2h.csv
paper_state/paper_aggressive-eth-2h_ETHUSDT_2h.json
```

La consola imprime la ruta completa desde `C:\...`.

Para dejarlo revisando cada 5 minutos:

```powershell
py -m src.paper --watch --sleep-seconds 300
```

Para comparar con el candidato mas estable:

```powershell
py -m src.paper --preset stable-sol-4h
```

Para ver el experimento visual de 1 minuto:

```powershell
py -m src.paper --preset experimental-eth-1m
```

Para reiniciar la billetera ficticia de ese preset:

```powershell
py -m src.paper --reset
```

## Servicio 24/7 para paper trading

Para correrlo como proceso largo con logs y reintentos:

```powershell
py -m src.paper_service
```

Ese servicio usa:

```text
config/paper.example.json
```

Y escribe logs en:

```text
logs/paper_service.log
```

El reporte HTML se recarga solo cada 30 segundos en el navegador. El servicio actualiza los datos cada 60 segundos por defecto. Si no hay vela nueva o senal nueva, veras lo mismo; mira `Ultima revision bot`, `Auto-refresh pagina` y `Hora navegador` para confirmar que todo sigue vivo.

Aunque no haya comprado todavia, la grafica de precio muestra las ultimas velas del mercado para que puedas ver si ETH esta subiendo, bajando o lateral.

El preset por defecto de paper trading usa velas de `2h`, porque reduce ruido y falsas entradas. El preset `experimental-eth-1m` queda solo para mirar movimiento rapido y aprender.

Para probar solo un ciclo:

```powershell
py -m src.paper_service --once
```

Para cambiar configuracion sin tocar el ejemplo, copia `config/paper.example.json` a:

```text
config/paper.local.json
```

Luego ejecuta:

```powershell
py -m src.paper_service --config config\paper.local.json
```

Para un VPS, este es el comando que debe quedar corriendo 24/7. Si se cierra, el estado ficticio sigue guardado en `paper_state/`, pero el bot no monitorea mientras esta apagado.

## Docker / VPS

El proyecto incluye `Dockerfile` y `docker-compose.yml` para dejarlo online en un VPS.

En el servidor:

```bash
git clone URL_DEL_REPO crypto-bot
cd crypto-bot
docker compose up -d --build
```

El bot queda corriendo en segundo plano y el reporte se publica en:

```text
http://IP_DEL_SERVIDOR:8080/paper/paper_aggressive-eth-2h_ETHUSDT_2h.html
```

Mas detalle en `DEPLOY.md`.

## Render

Para usar Render como servicio web:

- Tipo: Web Service.
- Runtime: Docker.
- Repo: `s3bs0s/trading-bot`.
- Health check: `/health`.
- URL principal: muestra un menu para abrir los reportes paper.

Variables opcionales:

```text
PAPER_PRESETS=aggressive-eth-2h,active-eth-1h,aggressive-eth-30m,growth-eth-4h,balanced-btc-4h,stable-sol-4h
PAPER_INITIAL_CASH=1000
PAPER_SLEEP_SECONDS=60
```

La URL de Render mostrara un menu con reportes separados:

- `aggressive-eth-2h`: base actual, menos activa, usa velas de 2 horas.
- `active-eth-1h`: experimento mas activo, usa velas de 1 hora.
- `aggressive-eth-30m`: experimento rapido, busca mas oportunidades con velas de 30 minutos.
- `growth-eth-4h`: experimento ETH 4h de crecimiento, usa pullbacks y posicion ficticia mas grande.
- `balanced-btc-4h`: comparacion BTC 4h, mejor candidato historico de la busqueda 3m/6m/12m.
- `stable-sol-4h`: comparacion estable en SOL, mas lenta pero util para medir consistencia.

```text
https://TU-SERVICIO.onrender.com/
```

La ruta `/health` responde JSON para monitoreo y para mantener despierto el servicio con un monitor externo. Sigue siendo paper trading: no usa API keys y no envia ordenes reales. Cada reporte guarda su propio estado ficticio y sus operaciones por separado.

Rutas utiles:

```text
/health   estado general para monitoreo
/backup   descarga todos los estados paper actuales como JSON
/state/NOMBRE.json   descarga un estado paper especifico
```

En Render Free el disco puede reiniciarse. Para no perder la billetera ficticia, configura una base de datos externa con `DATABASE_URL`.

## Variables locales

Para correr local con variables de entorno:

```powershell
copy .env.example .env
py -m src.render_app
```

El archivo `.env` queda ignorado por git. Ahi van credenciales locales como Supabase y configuracion de paper trading. No subas `.env` al repo.

Si usas Supabase, pon en `.env` o en Render:

```text
DATABASE_URL=postgresql://USUARIO:PASSWORD@HOST:PUERTO/postgres?sslmode=require
```

Con eso el bot crea automaticamente la tabla `paper_states` y guarda ahi el estado de cada reporte. El archivo local `paper_state/*.json` queda como respaldo, pero la base de datos es la fuente que sobrevive a reinicios.

Tablas creadas automaticamente:

```text
paper_states         checkpoint actual por preset para restaurar el bot
paper_runs           cada revision del bot con accion, capital y velas procesadas
paper_trades         operaciones cerradas con entrada, salida, motivo y resultado
paper_equity_points  historial de capital por vela para analizar drawdown y curva
```

`paper_states` existe para continuidad. Las otras tablas existen para trazabilidad y analisis.

## Proximos pasos

1. Ejecutar el primer backtest y leer los resultados.
2. Revisar los trades para entender cada compra y venta.
3. Ajustar parametros de riesgo.
4. Agregar graficas.
5. Monitorear paper trading con dinero ficticio.
6. Mucho despues, evaluar testnet de Binance.

## Optimizador

Para probar muchas combinaciones de forma automatica:

```powershell
py -m src.optimize
```

Genera:

```text
reports/optimizer/optimizer_results.html
reports/optimizer/optimizer_results.csv
```

El ranking no elige "dinero facil". Penaliza drawdown, pocos trades, perdidas, posiciones abiertas y pausas de riesgo.

## Candidatos actuales

Mas ganancia en la prueba amplia:

```powershell
py -m src.main --symbol ETHUSDT --interval 1h --limit 1000 --initial-cash 1000 --strategy breakout --fast 8 --trend-window 50 --pullback-window 6 --min-pullback 0.001 --min-volume-ratio 1.0 --stop-loss 0.02 --take-profit 0.04 --trailing-stop 0.005 --trailing-activation 0.006 --rsi-min 50 --rsi-max 75
```

Mas estable en ventanas cortas:

```powershell
py -m src.main --symbol ETHUSDT --interval 1h --limit 1000 --initial-cash 1000 --strategy breakout --fast 10 --trend-window 30 --pullback-window 12 --min-pullback 0.002 --min-volume-ratio 1.0 --stop-loss 0.02 --take-profit 0.04 --trailing-stop 0.005 --trailing-activation 0.006 --rsi-min 50 --rsi-max 75
```

El segundo gana menos en la prueba amplia, pero baja el drawdown y reduce la peor ventana corta.

Para comparar ese candidato contra BTC, ETH y SOL en 3, 6 y 12 meses:

```powershell
py -m src.compare
```

Por defecto esa comparacion usa un enfriamiento de 72 velas despues de 3 perdidas seguidas. Para volver al bloqueo duro:

```powershell
py -m src.compare --loss-streak-cooldown 0
```

Genera:

```text
reports/stable_candidate_comparison/comparison_results.html
reports/stable_candidate_comparison/comparison_results.csv
```

## Selector por activo

Para buscar una configuracion distinta por moneda y castigar el peor periodo:

```powershell
py -m src.select_asset --symbols ETHUSDT,BTCUSDT,SOLUSDT --intervals 4h --initial-cash 1000 --min-total-trades 8 --top 3 --output-dir reports\asset_selection_4h_all
```

Genera:

```text
reports/asset_selection_4h_all/all_selection_results.html
reports/asset_selection_4h_all/all_selection_results.csv
```

Los candidatos actuales mas prometedores son pullback en 4h por activo. Siguen siendo resultados de laboratorio, no paper trading.

## Validacion rolling

Para validar los candidatos actuales en ventanas separadas de 30, 60 y 90 dias:

```powershell
py -m src.rolling_validate
```

Genera:

```text
reports/rolling_validation_shortlist/rolling_validation.html
reports/rolling_validation_shortlist/rolling_validation_summary.csv
reports/rolling_validation_shortlist/rolling_validation_details.csv
```

Resultado actual: SOL 4h pullback es el candidato mas consistente en rolling validation, pero aun tiene ventanas de 30 dias negativas.

## Busqueda agresiva controlada

Para buscar mas ganancia en corto plazo, aceptando mas variacion:

```powershell
py -m src.aggressive_search --symbols SOLUSDT,ETHUSDT,BTCUSDT --intervals 1h,2h,4h --history-days 120 --initial-cash 1000 --profile quick --top 8 --output-dir reports\aggressive_search_quick_v1
```

Genera:

```text
reports/aggressive_search_quick_v1/aggressive_results.html
reports/aggressive_search_quick_v1/aggressive_results.csv
```

Resultado actual: ETH 2h breakout fue el mejor en los ultimos 120 dias, pero fallo en los 120 dias anteriores. Es candidato de experimento agresivo, no candidato para dinero real.

## Advertencia

Este proyecto es educativo. Un backtest positivo no garantiza ganancias futuras.
La prioridad inicial es aprender, medir riesgos y evitar errores antes de pensar en dinero real.
