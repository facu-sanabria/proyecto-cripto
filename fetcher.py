# ══════════════════════════════════════════════════════════════════════════════
# fetcher.py — El "periodista" del bot
#
# Este módulo se encarga de ir a buscar los datos de precios a Binance.
# Piénsalo como un periodista que sale a buscar información del mercado.
# Usamos la API pública de Binance (no necesitás cuenta ni API key).
# ══════════════════════════════════════════════════════════════════════════════

import requests
import pandas as pd
import time
from config import TIMEFRAME, CANDLES, CRYPTOS

# URL base de la API de Binance
BINANCE_BASE = "https://api.binance.com/api/v3"


def get_ohlcv(symbol: str, interval: str = TIMEFRAME, limit: int = CANDLES) -> pd.DataFrame | None:
    """
    Descarga datos OHLCV de Binance para un símbolo dado.

    OHLCV = Open, High, Low, Close, Volume
    (Apertura, Máximo, Mínimo, Cierre, Volumen)
    Son las "velas" que ves en los gráficos de trading.

    Args:
        symbol:   Par de trading, ej: "BTCUSDT"
        interval: Timeframe de cada vela, ej: "4h", "1d"
        limit:    Cuántas velas descargar (máx 1000 en Binance)

    Returns:
        DataFrame de pandas con columnas: open, high, low, close, volume
        None si hubo un error.
    """
    url = f"{BINANCE_BASE}/klines"
    params = {
        "symbol":   symbol,
        "interval": interval,
        "limit":    limit,
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()  # lanza excepción si hay error HTTP
        data = response.json()

        # Binance devuelve una lista de listas. Cada sublista es una vela con 12 campos.
        df = pd.DataFrame(data, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_buy_base", "taker_buy_quote", "ignore"
        ])

        # Convertir timestamp (unix ms) a fecha legible
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

        # Convertir precios y volumen a números flotantes
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        # Usar timestamp como índice y quedarnos solo con columnas útiles
        return df.set_index("timestamp")[["open", "high", "low", "close", "volume"]]

    except requests.RequestException as e:
        print(f"  ⚠️  Error descargando {symbol}: {e}")
        return None


def get_stats_24h(symbol: str) -> dict | None:
    """
    Obtiene estadísticas de las últimas 24 horas para un símbolo.

    Returns:
        Dict con precio actual, cambio %, volumen, máximo y mínimo del día.
    """
    url = f"{BINANCE_BASE}/ticker/24hr"

    try:
        response = requests.get(url, params={"symbol": symbol}, timeout=5)
        response.raise_for_status()
        d = response.json()

        return {
            "price":       float(d["lastPrice"]),
            "change_pct":  float(d["priceChangePercent"]),
            "volume_usdt": float(d["quoteVolume"]),
            "high_24h":    float(d["highPrice"]),
            "low_24h":     float(d["lowPrice"]),
        }

    except requests.RequestException as e:
        print(f"  ⚠️  Error obteniendo stats de {symbol}: {e}")
        return None


def fetch_all(cryptos: list = CRYPTOS, interval: str = TIMEFRAME, limit: int = CANDLES) -> list:
    """
    Descarga datos para TODAS las criptomonedas de la lista.

    Hace una pausa pequeña entre cada descarga para no saturar la API.

    Returns:
        Lista de dicts, cada uno con:
        {
          "crypto": {"symbol": "BTCUSDT", "name": "Bitcoin"},
          "ohlcv":  DataFrame con velas históricas,
          "stats":  dict con datos de las últimas 24h
        }
    """
    results = []
    total = len(cryptos)

    for i, crypto in enumerate(cryptos):
        symbol = crypto["symbol"]
        print(f"  [{i+1}/{total}] Descargando {symbol}...", end=" ")

        ohlcv = get_ohlcv(symbol, interval, limit)
        stats = get_stats_24h(symbol)

        if ohlcv is not None and stats is not None:
            results.append({
                "crypto": crypto,
                "ohlcv":  ohlcv,
                "stats":  stats,
            })
            print("✓")
        else:
            print("✗ (skipped)")

        # Pausa de 100ms para respetar los rate limits de Binance
        time.sleep(0.1)

    return results
