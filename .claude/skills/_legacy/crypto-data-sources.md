# Crypto Data Sources — API Reference

## Trigger
Auto-activate when: user asks about crypto APIs, price data, historical data, OHLCV, market cap, on-chain data, CoinGecko, Binance API, rate limits, free vs paid data.

## APIs Disponibles

### 1. CoinGecko — GRATIS (recomendado para empezar)

```
Base URL: https://api.coingecko.com/api/v3
Rate limit FREE: 10-30 calls/min (sin API key), 500/min (con key gratis)
Registro: https://www.coingecko.com/en/api
```

| Dato | Endpoint | Params clave |
|------|----------|--------------|
| Precio actual + cambios | `/simple/price` | `ids`, `vs_currencies`, `include_24hr_change` |
| OHLCV histórico | `/coins/{id}/ohlc` | `vs_currency`, `days` |
| Market data completo | `/coins/{id}` | `localization=false`, `tickers=false` |
| Top N por market cap | `/coins/markets` | `vs_currency`, `order`, `per_page` |
| Fear & Greed Index | API externa: `https://api.alternative.me/fng/` | `limit` |

```python
import requests

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

def get_top_cryptos(vs_currency="usd", top_n=50):
    url = f"{COINGECKO_BASE}/coins/markets"
    params = {
        "vs_currency": vs_currency,
        "order": "market_cap_desc",
        "per_page": top_n,
        "page": 1,
        "sparkline": False,
        "price_change_percentage": "24h,7d"
    }
    r = requests.get(url, params=params)
    r.raise_for_status()
    return r.json()

def get_ohlcv(coin_id: str, days: int = 30, vs_currency="usd"):
    """Retorna OHLCV para calcular indicadores TA."""
    url = f"{COINGECKO_BASE}/coins/{coin_id}/ohlc"
    params = {"vs_currency": vs_currency, "days": days}
    r = requests.get(url, params=params)
    r.raise_for_status()
    # Formato: [[timestamp, open, high, low, close], ...]
    return r.json()

def get_fear_greed():
    r = requests.get("https://api.alternative.me/fng/?limit=1")
    r.raise_for_status()
    data = r.json()["data"][0]
    return int(data["value"]), data["value_classification"]
```

---

### 2. Binance API — GRATIS, datos más ricos

```
Base URL: https://api.binance.com/api/v3
Rate limit: 1200 requests/min (peso variable por endpoint)
Sin API key: OK para datos públicos (precios, OHLCV)
```

| Dato | Endpoint | Params |
|------|----------|--------|
| OHLCV (klines) | `/klines` | `symbol`, `interval`, `limit` |
| Precio actual | `/ticker/price` | `symbol` |
| Stats 24h | `/ticker/24hr` | `symbol` |
| Book ticker | `/ticker/bookTicker` | `symbol` |

```python
BINANCE_BASE = "https://api.binance.com/api/v3"

INTERVALS = {
    "15m": "15m",
    "1h": "1h", 
    "4h": "4h",
    "1d": "1d",
    "1w": "1w"
}

def get_klines_binance(symbol: str, interval: str = "4h", limit: int = 200):
    """
    symbol: e.g. "BTCUSDT", "ETHUSDT"
    interval: "15m", "1h", "4h", "1d"
    Retorna DataFrame con OHLCV.
    """
    import pandas as pd
    
    url = f"{BINANCE_BASE}/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params)
    r.raise_for_status()
    
    data = r.json()
    df = pd.DataFrame(data, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore"
    ])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    
    return df.set_index("timestamp")[["open", "high", "low", "close", "volume"]]

def get_all_tickers_binance():
    """Todos los pares con precio actual."""
    r = requests.get(f"{BINANCE_BASE}/ticker/price")
    r.raise_for_status()
    return {t["symbol"]: float(t["price"]) for t in r.json()}
```

---

### 3. CryptoCompare — Alternativa para datos históricos

```
Base URL: https://min-api.cryptocompare.com/data
Free tier: 100k calls/mes
```

```python
def get_historical_daily(symbol: str, limit: int = 200, currency="USD"):
    url = "https://min-api.cryptocompare.com/data/v2/histoday"
    params = {"fsym": symbol, "tsym": currency, "limit": limit}
    r = requests.get(url, params=params)
    return r.json()["Data"]["Data"]
```

---

## Mapeo CoinGecko ID ↔ Binance Symbol

| Crypto | CoinGecko ID | Binance Symbol |
|--------|-------------|----------------|
| Bitcoin | `bitcoin` | `BTCUSDT` |
| Ethereum | `ethereum` | `ETHUSDT` |
| BNB | `binancecoin` | `BNBUSDT` |
| Solana | `solana` | `SOLUSDT` |
| XRP | `ripple` | `XRPUSDT` |
| Cardano | `cardano` | `ADAUSDT` |
| Avalanche | `avalanche-2` | `AVAXUSDT` |
| Chainlink | `chainlink` | `LINKUSDT` |
| Polkadot | `polkadot` | `DOTUSDT` |
| Dogecoin | `dogecoin` | `DOGEUSDT` |

---

## Manejo de Rate Limits

```python
import time
import functools

def rate_limited(calls_per_minute: int):
    min_interval = 60.0 / calls_per_minute
    last_called = [0.0]
    
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_called[0]
            wait = min_interval - elapsed
            if wait > 0:
                time.sleep(wait)
            result = fn(*args, **kwargs)
            last_called[0] = time.time()
            return result
        return wrapper
    return decorator

@rate_limited(calls_per_minute=25)  # seguro para CoinGecko free
def safe_coingecko_call(url, params):
    r = requests.get(url, params=params)
    r.raise_for_status()
    return r.json()
```

## Estrategia Recomendada para este Bot

```
Precios actuales + market data  → CoinGecko /coins/markets  (cada 5 min)
OHLCV para indicadores TA       → Binance /klines           (cada refresh)
Fear & Greed Index              → alternative.me/fng        (cada hora)
Datos on-chain avanzados        → Glassnode (pago) o        (opcional)
                                   CryptoQuant (pago)
```

## Librerías Python Útiles

```bash
pip install requests pandas ta schedule openpyxl python-dotenv
```

- `ta` → todos los indicadores técnicos sobre DataFrames de pandas
- `python-dotenv` → manejar API keys en archivo `.env` (no hardcodear)
- `ccxt` → si se necesita conectar a múltiples exchanges (trading real)
