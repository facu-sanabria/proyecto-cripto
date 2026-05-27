---
name: crypto-data-sources
description: Usar cuando el usuario pregunta sobre APIs de datos crypto (Binance, CoinGecko), rate limits, descarga de OHLCV histórico, o cómo obtener Fear & Greed Index.
---

# Crypto Data Sources — API Reference

## APIs que usa este bot

### Binance API (principal — gratis, sin key)

```
Base URL: https://api.binance.com/api/v3
Rate limit: 1200 requests/min
Sin API key: OK para datos públicos
```

| Dato | Endpoint | Params |
|------|----------|--------|
| OHLCV (klines) | `/klines` | `symbol`, `interval`, `limit` |
| Precio actual (todos) | `/ticker/price` | — |
| Stats 24h (todos) | `/ticker/24hr` | — |

```python
# Implementación actual en fetcher.py
BINANCE_BASE = "https://api.binance.com/api/v3"

def get_ohlcv(symbol: str, interval: str = "4h", limit: int = 200):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(f"{BINANCE_BASE}/klines", params=params, timeout=10)
    resp.raise_for_status()
    # retorna DataFrame con index timestamp, cols: open, high, low, close, volume
```

### Yahoo Finance v8 (stocks — gratis, 15min delay)

```python
# En stocks_fetcher.py
# get_stock_ohlcv_v8(symbol, interval="1h", range_str="60d")
# Retorna (df, price, change_pct)
```

### Fear & Greed Index (alternativa.me)

```python
# En market_context.py
def get_historical_fear_greed(days: int = 800) -> pd.Series | None:
    # https://api.alternative.me/fng/?limit=800
    # Retorna Serie con fechas como index, valores 0-100
```

## Mapeo CoinGecko ID ↔ Binance Symbol

| Crypto | Binance Symbol |
|--------|----------------|
| Bitcoin | `BTCUSDT` |
| Ethereum | `ETHUSDT` |
| BNB | `BNBUSDT` |
| Solana | `SOLUSDT` |
| XRP | `XRPUSDT` |
| Cardano | `ADAUSDT` |
| Avalanche | `AVAXUSDT` |
| Chainlink | `LINKUSDT` |
| Polkadot | `DOTUSDT` |

## Paginación histórica (fetch_historical_ohlcv en backtester.py)

Binance permite máximo 1000 velas por petición. Para meses de historia:

```python
while current_start < end_ms:
    params = {"symbol": symbol, "interval": interval,
              "startTime": current_start, "endTime": end_ms, "limit": 1000}
    data = requests.get(f"{BINANCE_BASE}/klines", params=params).json()
    all_candles.extend(data)
    last_close_time = data[-1][6]  # close_time del último kline
    if last_close_time >= end_ms: break
    current_start = last_close_time + 1
    time.sleep(0.2)  # respetar rate limit
```

## Manejo de Rate Limits

```python
# Pausa entre descargas (ya implementado):
time.sleep(0.2)  # backtester.py entre páginas
time.sleep(0.1)  # fetcher.py entre activos

# Para el live dashboard: 1 sola llamada a /ticker/price trae TODOS los precios
# Mucho más eficiente que N llamadas individuales
```

## Notas de Confiabilidad

- Binance: alta disponibilidad, timestamps siempre en UTC (epoch ms)
- Yahoo Finance: 15min de delay para stocks, puede fallar en horarios de alta carga
- Fear & Greed: datos diarios, útil solo para filtro de contexto de mercado
- CoinGecko free: rate limit estricto (10-30 req/min) — NO usar en loops frecuentes
