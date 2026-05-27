# ══════════════════════════════════════════════════════════════════════════════
# indicators.py — Cálculos técnicos puros
#
# ÚNICA FUENTE DE VERDAD para todos los indicadores técnicos.
# Usado por analyzer.py (live) y backtester.py (histórico).
# Sin estado. Sin I/O. Solo pandas/numpy.
#
# Regla de oro: NINGUNA función aquí debe usar datos futuros (look-ahead).
# Toda ventana debe ser [start : i+1], nunca [start : i+N] con N > 1.
# ══════════════════════════════════════════════════════════════════════════════

import pandas as pd
import numpy as np


# ─── Indicadores primitivos ───────────────────────────────────────────────────

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    RSI = 100 - (100 / (1 + RS))
    RS  = promedio de subidas / promedio de bajadas en N períodos
    Usa EWM (com = period-1) para suavizado tipo Wilder.
    """
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """
    MACD Line   = EMA(fast) - EMA(slow)
    Signal Line = EMA(signal) del MACD Line
    Histograma  = MACD Line - Signal Line

    Returns:
        (macd_line, signal_line, histogram) — todas pd.Series
    """
    ema_fast    = close.ewm(span=fast,   adjust=False).mean()
    ema_slow    = close.ewm(span=slow,   adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_ema(close: pd.Series, period: int) -> pd.Series:
    """EMA: promedio exponencial que da más peso a los datos recientes."""
    return close.ewm(span=period, adjust=False).mean()


def calc_bollinger(close: pd.Series, period: int = 20, std_dev: float = 2):
    """
    Banda media  = SMA(20)
    Banda sup    = media + std_dev×std
    Banda inf    = media - std_dev×std
    %B           = (precio - banda_inf) / (banda_sup - banda_inf)
                   0 = banda inferior, 1 = banda superior

    Returns:
        (upper, lower, pband) — todas pd.Series
    """
    ma    = close.rolling(window=period).mean()
    std   = close.rolling(window=period).std()
    upper = ma + std_dev * std
    lower = ma - std_dev * std
    pband = (close - lower) / (upper - lower).replace(0, np.nan)
    return upper, lower, pband


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series,
             period: int = 14) -> pd.Series:
    """
    True Range = max(high-low, |high-close_prev|, |low-close_prev|)
    ATR        = EWM(14) del True Range
    """
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series,
             period: int = 14):
    """
    ADX — Average Directional Index.
    Mide la FUERZA de la tendencia, no su dirección.

    ADX < 18: mercado lateral → señales técnicas son ruido
    ADX 18-25: tendencia débil
    ADX 25-40: tendencia clara
    ADX > 40:  tendencia muy fuerte

    +DI > -DI: tendencia alcista
    -DI > +DI: tendencia bajista

    Returns:
        (adx, plus_di, minus_di) — todas pd.Series
    """
    prev_high  = high.shift(1)
    prev_low   = low.shift(1)
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    up_move   = high - prev_high
    down_move = prev_low - low

    plus_dm  = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=high.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=high.index,
    )

    atr_s    = tr.ewm(span=period, adjust=False).mean()
    plus_di  = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, np.nan)

    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx     = 100 * (plus_di - minus_di).abs() / di_sum
    adx    = dx.ewm(span=period, adjust=False).mean()

    return adx, plus_di, minus_di


# ─── Cálculo de indicadores sobre una ventana ─────────────────────────────────

def compute_indicators(window: pd.DataFrame) -> dict:
    """
    Calcula todos los indicadores sobre un DataFrame de velas y devuelve
    el valor de la ÚLTIMA vela.

    Este es el núcleo compartido entre:
    - calculate_indicators(df)         → usa todo el df (live)
    - calculate_indicators_at(df, idx) → usa ventana [idx-N : idx] (backtest)

    Args:
        window: DataFrame con columnas open, high, low, close, volume.
                Debe tener al menos 200 filas para EMA200 estable.

    Returns:
        Dict con valores actuales de cada indicador.
        Incluye 'prev' (vela anterior) para detectar momentum.

    NO usa datos futuros: solo window.iloc[-1] y window.iloc[-2].
    """
    close  = window["close"]
    high   = window["high"]
    low    = window["low"]
    volume = window["volume"]

    rsi_series                   = calc_rsi(close)
    rsi                          = rsi_series.iloc[-1]
    rsi_prev                     = rsi_series.iloc[-2] if len(rsi_series) >= 2 else rsi

    _, _, macd_h                 = calc_macd(close)
    macd_hist                    = macd_h.iloc[-1]
    macd_hist_prev               = macd_h.iloc[-2] if len(macd_h) >= 2 else macd_hist

    ema20                        = calc_ema(close, 20).iloc[-1]
    ema50                        = calc_ema(close, 50).iloc[-1]
    ema200                       = calc_ema(close, 200).iloc[-1]
    _, _, bb_pct_s               = calc_bollinger(close)
    atr_s                        = calc_atr(high, low, close)
    atr                          = atr_s.iloc[-1]
    adx_s, plus_di_s, minus_di_s = calc_adx(high, low, close)

    current_price  = float(close.iloc[-1])
    avg_volume     = volume.rolling(20).mean().iloc[-1]
    current_volume = float(volume.iloc[-1])
    volume_ratio   = current_volume / avg_volume if avg_volume > 0 else 1.0

    return {
        "price":          current_price,
        "rsi":            round(float(rsi),            2),
        "rsi_prev":       round(float(rsi_prev),       2),
        "macd_hist":      round(float(macd_hist),      6),
        "macd_hist_prev": round(float(macd_hist_prev), 6),
        "ema20":          round(float(ema20),           6),
        "ema50":          round(float(ema50),           6),
        "ema200":         round(float(ema200),          6),
        "bb_pct":         round(float(bb_pct_s.iloc[-1]), 4),
        "atr":            round(float(atr),             6),
        "atr_pct":        round((float(atr) / current_price) * 100, 2),
        "volume_ratio":   round(float(volume_ratio),   2),
        "adx":            round(float(adx_s.iloc[-1]),      2),
        "plus_di":        round(float(plus_di_s.iloc[-1]),  2),
        "minus_di":       round(float(minus_di_s.iloc[-1]), 2),
    }


# ─── API pública de alto nivel ────────────────────────────────────────────────

def calculate_indicators(df: pd.DataFrame) -> dict:
    """
    Calcula indicadores usando todo el DataFrame (modo live / Excel bot).

    Args:
        df: DataFrame con columnas open, high, low, close, volume.

    Returns:
        Dict con valores actuales de cada indicador (última vela).
    """
    return compute_indicators(df)


# Tamaño mínimo de ventana para calcular EMA200 y demás indicadores.
# Debe coincidir con INDICATOR_WINDOW en backtester.py.
INDICATOR_WINDOW = 200


def calculate_indicators_at(df: pd.DataFrame, idx: int) -> dict | None:
    """
    Calcula indicadores usando las últimas INDICATOR_WINDOW velas hasta idx.
    Equivalente al modo live pero aplicado a un punto histórico.

    Garantía anti-look-ahead: la ventana es df.iloc[max(0, idx-WINDOW+1) : idx+1].
    Nunca accede a filas > idx.

    Args:
        df:  DataFrame completo con toda la historia.
        idx: Índice de la barra actual (incluida en el cálculo).

    Returns:
        Dict con indicadores, o None si hay insuficientes datos.
    """
    if idx < INDICATOR_WINDOW:
        return None
    window = df.iloc[max(0, idx - INDICATOR_WINDOW + 1): idx + 1]
    return compute_indicators(window)
