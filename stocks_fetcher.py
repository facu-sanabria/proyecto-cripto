# ══════════════════════════════════════════════════════════════════════════════
# stocks_fetcher.py — Datos de acciones USA y ETFs via Yahoo Finance
#
# Por qué acciones además de crypto:
#   - Mercado regulado, menos manipulación que crypto
#   - Empresas tech (NVDA, AAPL, MSFT) siguen tendencias claras multi-mes
#   - ETFs (SPY, QQQ) son diversificados y menos volátiles
#   - Gold ETF (GLD) actúa como refugio en crisis → descorrelacionado de crypto
#   - Mismo análisis técnico funciona: RSI, MACD, EMA, Bollinger
#
# API: Yahoo Finance via yfinance (gratis, sin API key)
# Limitaciones: datos 1h disponibles hasta 730 días atrás
# ══════════════════════════════════════════════════════════════════════════════

import yfinance as yf
import pandas as pd
import numpy as np
import time
import threading
import requests
import concurrent.futures

# ─── Lista de acciones y ETFs a analizar ─────────────────────────────────────

STOCKS = [
    # Mega-cap tech: tendencias claras, análisis técnico muy efectivo
    {"symbol": "AAPL",  "name": "Apple",       "type": "stock"},
    {"symbol": "MSFT",  "name": "Microsoft",   "type": "stock"},
    {"symbol": "NVDA",  "name": "NVIDIA",      "type": "stock"},
    {"symbol": "GOOGL", "name": "Google",      "type": "stock"},
    {"symbol": "META",  "name": "Meta",        "type": "stock"},

    # ETFs: menos volátiles, más predecibles
    {"symbol": "SPY",   "name": "S&P 500",     "type": "etf"},
    {"symbol": "QQQ",   "name": "Nasdaq 100",  "type": "etf"},

    # Activos de refugio: se mueven diferente a tech/crypto
    {"symbol": "GLD",   "name": "Gold ETF",    "type": "commodity"},
    {"symbol": "SLV",   "name": "Silver ETF",  "type": "commodity"},
]

# Cartera core — seleccionados por backtest 2024:
#   NVDA: PF 3.63, +77.7%, 70% WR  (mejor activo del dataset)
#   SPY:  PF 2.80, +16.2%, 54% WR  (ultra-consistente, low DD 3.2%)
STOCKS_CORE = [s for s in STOCKS if s["symbol"] in ("NVDA", "SPY")]

# ─── Descarga de datos históricos ─────────────────────────────────────────────

def get_stock_ohlcv(
    symbol:   str,
    interval: str   = "1h",
    months:   int   = 6,
    start_dt  = None,
    end_dt    = None,
) -> pd.DataFrame | None:
    """
    Descarga datos OHLCV de una acción o ETF usando Yahoo Finance.

    Intervalos disponibles:
      "1h"  → velas de 1 hora (máx 730 días atrás) — equivalente a 4h en crypto
      "1d"  → velas diarias (cualquier fecha)
      "1wk" → semanal

    Auto-detecta si el rango pedido excede 730 días y cambia a "1d".

    Returns:
        DataFrame con columnas: open, high, low, close, volume
        None si hubo error o sin datos.
    """
    from datetime import datetime, timedelta

    # Auto-fallback a diario si el período está fuera del límite de 730 días
    cutoff = datetime.now() - timedelta(days=720)
    if start_dt and start_dt < cutoff:
        interval = "1d"
    elif start_dt is None:
        check_start = datetime.now() - timedelta(days=months * 30)
        if check_start < cutoff:
            interval = "1d"

    try:
        # yf.download() es más robusto ante rate limits que yf.Ticker().history()
        # porque no necesita el flujo separado de cookie/crumb que Yahoo bloquea
        # con mayor frecuencia. Referencia: yfinance issue #2066.
        if start_dt and end_dt:
            yf_kwargs = dict(start=start_dt, end=end_dt, interval=interval)
        elif start_dt:
            yf_kwargs = dict(start=start_dt, interval=interval)
        else:
            period_map = {1: "1mo", 2: "2mo", 3: "3mo", 6: "6mo",
                          12: "1y", 24: "2y", 36: "3y", 60: "5y"}
            period = next((v for k, v in sorted(period_map.items()) if months <= k), "5y")
            yf_kwargs = dict(period=period, interval=interval)

        df = yf.download(symbol, progress=False, auto_adjust=True, **yf_kwargs)

        if df.empty:
            return None

        # yf.download devuelve MultiIndex cuando se pasa una lista; para un solo
        # símbolo puede devolver columnas simples o MultiIndex según versión.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Normalizar nombres de columnas
        df.columns = [c.lower() for c in df.columns]
        df.index.name = "timestamp"

        # yfinance a veces incluye columnas extra (dividends, stock splits)
        cols_needed = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        df = df[cols_needed].copy()

        # Eliminar filas con NaN
        df = df.dropna()

        # Asegurar que el índice es timezone-naive (para comparar con fechas crypto)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        return df

    except Exception as e:
        print(f"  ⚠️  Error descargando {symbol}: {e}")
        return None


def get_stock_daily_ohlcv(symbol: str, months: int = 8) -> pd.DataFrame | None:
    """Descarga datos diarios de una acción para confirmación multi-timeframe."""
    return get_stock_ohlcv(symbol, interval="1d", months=months)


def get_stock_stats(symbol: str) -> dict | None:
    """
    Obtiene estadísticas actuales de una acción.
    Devuelve el mismo formato que fetcher.get_stats_24h para compatibilidad.
    """
    try:
        ticker = yf.Ticker(symbol)
        hist   = ticker.history(period="5d", interval="1d")

        if hist.empty or len(hist) < 2:
            return None

        hist.columns = [c.lower() for c in hist.columns]

        current = float(hist["close"].iloc[-1])
        prev    = float(hist["close"].iloc[-2])
        change  = (current - prev) / prev * 100

        return {
            "price":       current,
            "change_pct":  round(change, 2),
            "volume_usdt": float(hist["volume"].iloc[-1]),  # shares, no USDT
            "high_24h":    float(hist["high"].iloc[-1]),
            "low_24h":     float(hist["low"].iloc[-1]),
        }

    except Exception as e:
        print(f"  ⚠️  Error obteniendo stats de {symbol}: {e}")
        return None


_TIMED_OUT = object()   # sentinel para distinguir "timeout" de "None real"


def _run_with_timeout(fn, args=(), kwargs=None, timeout_sec=45):
    """
    Llama fn(*args, **kwargs) en un daemon thread.
    - Retorna el resultado si termina a tiempo.
    - Retorna _TIMED_OUT si se pasa de timeout_sec (thread abandona en bg).
    - Relanza la excepción si fn falla internamente.
    Daemon thread = nunca bloquea el proceso principal.
    """
    if kwargs is None:
        kwargs = {}
    result   = [None]
    exc      = [None]

    def _worker():
        try:
            result[0] = fn(*args, **kwargs)
        except Exception as e:
            exc[0] = e

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)

    if t.is_alive():
        return _TIMED_OUT   # thread sigue en bg pero no bloquea
    if exc[0] is not None:
        raise exc[0]
    return result[0]


def fetch_stocks_all(
    stocks:   list  = None,
    interval: str   = "1h",
    months:   int   = 6,
    start_dt  = None,
    end_dt    = None,
) -> list:
    """
    Descarga datos para todas las acciones de la lista.
    Devuelve el mismo formato que fetcher.fetch_all para compatibilidad total.

    Returns:
        Lista de dicts: [{"crypto": {...}, "ohlcv": df, "stats": {...}}]
        Nota: usamos "crypto" como key para compatibilidad con el resto del bot.
    """
    if stocks is None:
        stocks = STOCKS_CORE

    results = []
    total   = len(stocks)

    for i, stock in enumerate(stocks):
        symbol = stock["symbol"]
        name   = stock["name"]
        print(f"  [{i+1}/{total}] {name} ({symbol})...", end=" ", flush=True)

        try:
            _r = _run_with_timeout(
                get_stock_ohlcv,
                args=(symbol, interval, months, start_dt, end_dt),
                timeout_sec=45,
            )
            if _r is _TIMED_OUT:
                print(f"\n  ⚠️  Timeout (45s) — {symbol} no respondió a tiempo", flush=True)
                ohlcv = None
            else:
                ohlcv = _r
        except Exception as e:
            print(f"\n  ⚠️  Error descargando {symbol}: {e}")
            ohlcv = None

        try:
            _r = _run_with_timeout(
                get_stock_stats,
                args=(symbol,),
                timeout_sec=20,
            )
            stats = None if _r is _TIMED_OUT else _r
        except Exception as e:
            print(f"\n  ⚠️  Error stats {symbol}: {e}")
            stats = None

        if ohlcv is not None and not ohlcv.empty and stats is not None:
            # Usar misma estructura que crypto para compatibilidad
            results.append({
                "crypto": {"symbol": symbol, "name": name, "asset_type": stock.get("type", "stock")},
                "ohlcv":  ohlcv,
                "stats":  stats,
            })
            print(f"✓ ({len(ohlcv)} velas)")
        else:
            print("✗ (sin datos)")

        time.sleep(0.3)  # Respetar rate limits de Yahoo Finance

    return results


# ─── Información de activos ───────────────────────────────────────────────────

def get_stock_info(symbol: str) -> dict:
    """
    Información básica de un activo (sector, market cap, P/E).
    Útil para análisis fundamental básico.
    """
    try:
        ticker = yf.Ticker(symbol)
        info   = ticker.info
        return {
            "sector":      info.get("sector", "ETF/Unknown"),
            "market_cap":  info.get("marketCap", 0),
            "pe_ratio":    info.get("trailingPE", None),
            "beta":        info.get("beta", None),
            "52w_high":    info.get("fiftyTwoWeekHigh", None),
            "52w_low":     info.get("fiftyTwoWeekLow", None),
        }
    except Exception:
        return {}


# ─── API v8 directa (más rápida y confiable que yfinance) ─────────────────────

_YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}


def get_stock_ohlcv_v8(
    symbol:    str,
    interval:  str = "1h",
    range_str: str = "60d",
) -> tuple:
    """
    Descarga OHLCV + precio actual via Yahoo Finance v8 API (requests directo).
    Evita yfinance y su overhead/inestabilidad. Sin API key.

    Args:
        symbol:    ticker Yahoo (ej: "AAPL", "SPY")
        interval:  "1m", "5m", "15m", "1h", "1d"
        range_str: "1d", "5d", "60d", "1y"  — rango de velas a descargar

    Returns:
        (df, current_price, change_pct_24h)
        df tiene columnas open/high/low/close/volume con DatetimeIndex.
        Cualquiera puede ser None si hubo error.
    """
    url    = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {
        "interval":       interval,
        "range":          range_str,
        "includePrePost": "false",
        "events":         "div,split",
    }
    try:
        r = requests.get(url, headers=_YF_HEADERS, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        result = data["chart"]["result"][0]
        meta   = result["meta"]

        current_price = float(meta.get("regularMarketPrice") or 0)
        prev_close    = float(meta.get("previousClose") or meta.get("chartPreviousClose") or 0)
        change_pct    = ((current_price - prev_close) / prev_close * 100) if prev_close else 0.0

        timestamps = result.get("timestamp") or []
        quotes     = result["indicators"]["quote"][0]

        if not timestamps or not current_price:
            return None, (current_price or None), change_pct

        df = pd.DataFrame({
            "open":   [float(v) if v is not None else None for v in quotes.get("open",   [])],
            "high":   [float(v) if v is not None else None for v in quotes.get("high",   [])],
            "low":    [float(v) if v is not None else None for v in quotes.get("low",    [])],
            "close":  [float(v) if v is not None else None for v in quotes.get("close",  [])],
            "volume": [float(v) if v is not None else 0.0  for v in quotes.get("volume", [])],
        }, index=pd.to_datetime(timestamps, unit="s"))

        df.index.name = "timestamp"
        df = df.dropna(subset=["open", "high", "low", "close"])

        return (df if not df.empty else None), current_price, change_pct

    except Exception:
        return None, None, None


def get_stocks_prices_bulk(symbols: list) -> dict:
    """
    Fetch precios actuales para múltiples acciones en paralelo.
    1 request por símbolo, concurrente — similar a ticker/price de Binance.

    Returns:
        {symbol: (price, change_pct_24h)}  — solo símbolos con datos válidos
    """
    def _fetch_one(sym: str):
        url    = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
        params = {"interval": "1m", "range": "1d", "includePrePost": "false"}
        try:
            r    = requests.get(url, headers=_YF_HEADERS, params=params, timeout=8)
            r.raise_for_status()
            meta = r.json()["chart"]["result"][0]["meta"]
            price    = float(meta.get("regularMarketPrice") or 0)
            prev_c   = float(meta.get("previousClose") or meta.get("chartPreviousClose") or 0)
            chg_pct  = ((price - prev_c) / prev_c * 100) if prev_c else 0.0
            return sym, (price, chg_pct) if price > 0 else None
        except Exception:
            return sym, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        pairs = list(ex.map(_fetch_one, symbols))

    return {sym: val for sym, val in pairs if val is not None}
