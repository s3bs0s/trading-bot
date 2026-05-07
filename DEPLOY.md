# Deploy 24/7 en VPS

Este despliegue sigue siendo paper trading: no usa API keys, no toca Binance real y no envia ordenes reales.

## Que hace

- `paper-bot`: corre `src.paper_service` todo el tiempo.
- `report-server`: publica la carpeta `reports/` por HTTP en el puerto `8080`.
- `paper_state/`, `reports/` y `logs/` quedan persistentes en el servidor.

## Comandos en el VPS

En un VPS Linux con Docker instalado:

```bash
git clone URL_DEL_REPO crypto-bot
cd crypto-bot
docker compose up -d --build
```

Ver estado:

```bash
docker compose ps
docker compose logs -f paper-bot
```

Ver reporte:

```text
http://IP_DEL_SERVIDOR:8080/paper/paper_aggressive-eth-2h_ETHUSDT_2h.html
```

Detener:

```bash
docker compose down
```

Actualizar codigo:

```bash
git pull
docker compose up -d --build
```

## Seguridad

- No subas `.env`.
- No pongas API keys en GitHub.
- No abras puertos innecesarios.
- Para real money, primero se necesita testnet/read-only, limites de riesgo y confirmacion explicita.
