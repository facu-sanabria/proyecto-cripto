# ══════════════════════════════════════════════════════════════════════════════
# analyzer.py — El "analista" del bot
#
# Calcula indicadores técnicos usando solo pandas y numpy (sin librerías TA).
# Cada fórmula está explicada en comentarios.
# ══════════════════════════════════════════════════════════════════════════════

import pandas as pd
import numpy as np


# ─── Fórmulas de indicadores ──────────────────────────────────────────────────

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    RSI = 100 - (100 / (1 + RS))
    RS  = promedio de subidas / promedio de bajadas en N períodos
    """
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)

    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_macd(close: pd.Series, fast=12, slow=26, signal=9):
    """
    MACD Line   = EMA(12) - EMA(26)
    Signal Line = EMA(9) de la MACD Line
    Histograma  = MACD Line - Signal Line
    """
    ema_fast    = close.ewm(span=fast,   adjust=False).mean()
    ema_slow    = close.ewm(span=slow,   adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_ema(close: pd.Series, period: int) -> pd.Series:
    """EMA = promedio exponencial que da más peso a los datos recientes."""
    return close.ewm(span=period, adjust=False).mean()


def calc_bollinger(close: pd.Series, period=20, std_dev=2):
    """
    Banda media  = SMA(20)
    Banda superior = media + 2×std
    Banda inferior = media - 2×std
    %B = (precio - banda_inf) / (banda_sup - banda_inf)  → 0=inferior, 1=superior
    """
    ma    = close.rolling(window=period).mean()
    std   = close.rolling(window=period).std()
    upper = ma + std_dev * std
    lower = ma - std_dev * std
    pband = (close - lower) / (upper - lower).replace(0, np.nan)
    return upper, lower, pband


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period=14) -> pd.Series:
    """
    True Range = max(high-low, |high-close_prev|, |low-close_prev|)
    ATR        = EMA(14) del True Range
    """
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


# ─── Cálculo completo de indicadores ──────────────────────────────────────────

def calculate_indicators(df: pd.DataFrame) -> dict:
    """
    Calcula todos los indicadores y devuelve el valor de la última vela.

    Args:
        df: DataFrame con columnas open, high, low, close, volume

    Returns:
        Dict con valores actuales de cada indicador.
    """
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    rsi                          = calc_rsi(close).iloc[-1]
    macd_line, macd_sig, macd_h  = calc_macd(close)
    ema20                        = calc_ema(close, 20).iloc[-1]
    ema50                        = calc_ema(close, 50).iloc[-1]
    ema200                       = calc_ema(close, 200).iloc[-1]
    _, _, bb_pct                 = calc_bollinger(close)
    atr                          = calc_atr(high, low, close).iloc[-1]

    current_price  = close.iloc[-1]
    avg_volume     = volume.rolling(20).mean().iloc[-1]
    current_volume = volume.iloc[-1]
    volume_ratio   = current_volume / avg_volume if avg_volume > 0 else 1.0

    return {
        "price":        float(current_price),
        "rsi":          round(float(rsi), 2),
        "macd_hist":    round(float(macd_h.iloc[-1]), 6),
        "ema20":        round(float(ema20), 6),
        "ema50":        round(float(ema50), 6),
        "ema200":       round(float(ema200), 6),
        "bb_pct":       round(float(bb_pct.iloc[-1]), 4),
        "atr":          round(float(atr), 6),
        "atr_pct":      round((float(atr) / float(current_price)) * 100, 2),
        "volume_ratio": round(float(volume_ratio), 2),
    }


# ─── Sistema de scoring ───────────────────────────────────────────────────────

def score_crypto(ind: dict) -> tuple[int, str, str]:
    """
    Score de -100 a +100. Cuanto mayor, mejor oportunidad de compra.

    Returns:
        (score, señal, razón)
    """
    score   = 0
    reasons = []

    rsi          = ind["rsi"]
    macd_hist    = ind["macd_hist"]
    price        = ind["price"]
    ema50        = ind["ema50"]
    ema200       = ind["ema200"]
    bb_pct       = ind["bb_pct"]
    volume_ratio = ind["volume_ratio"]
    atr_pct      = ind["atr_pct"]

    # RSI (±20)
    if rsi < 30:
        score += 20;  reasons.append(f"RSI sobrevendido ({rsi:.0f})")
    elif rsi < 40:
        score += 10;  reasons.append(f"RSI bajo ({rsi:.0f})")
    elif rsi > 70:
        score -= 20;  reasons.append(f"RSI sobrecomprado ({rsi:.0f})")
    elif rsi > 60:
        score -= 10;  reasons.append(f"RSI alto ({rsi:.0f})")
    else:
        reasons.append(f"RSI neutral ({rsi:.0f})")

    # MACD histograma (±25)
    if macd_hist > 0:
        score += 25;  reasons.append("MACD alcista ↑")
    else:
        score -= 25;  reasons.append("MACD bajista ↓")

    # Posición vs EMA200 (±15)
    if price > ema200:
        score += 15;  reasons.append("Sobre EMA200")
    else:
        score -= 15;  reasons.append("Bajo EMA200")

    # EMA50 vs EMA200 — Golden/Death Cross (±10)
    if ema50 > ema200:
        score += 10;  reasons.append("Golden Cross")
    else:
        score -= 10;  reasons.append("Death Cross")

    # Bollinger Bands (±10)
    if bb_pct < 0.2:
        score += 10;  reasons.append("Banda inferior BB")
    elif bb_pct > 0.8:
        score -= 10;  reasons.append("Banda superior BB")

    # Volumen (±10)
    if volume_ratio > 1.5:
        if score > 0:
            score += 10;  reasons.append(f"Volumen {volume_ratio:.1f}x confirma")
        else:
            score -= 5;   reasons.append(f"Volumen {volume_ratio:.1f}x en caída")

    # Penalización volatilidad extrema
    if atr_pct > 5:
        score -= 10;  reasons.append(f"Volatilidad alta ({atr_pct:.1f}%)")

    score = max(-100, min(100, score))

    if score >= 60:
        signal = "STRONG BUY"
    elif score >= 25:
        signal = "BUY"
    elif score <= -60:
        signal = "STRONG SELL"
    elif score <= -25:
        signal = "SELL"
    else:
        signal = "NEUTRAL"

    return score, signal, " | ".join(reasons[:3])


# ─── Análisis completo ────────────────────────────────────────────────────────

def analyze_crypto(data: dict) -> dict:
    """
    Análisis completo de una criptomoneda.

    Args:
        data: Dict con keys "crypto", "ohlcv", "stats"

    Returns:
        Dict listo para el Excel.
    """
    crypto = data["crypto"]
    ohlcv  = data["ohlcv"]
    stats  = data["stats"]

    indicators         = calculate_indicators(ohlcv)
    score, signal, reason = score_crypto(indicators)

    atr   = indicators["atr"]
    price = stats["price"]

    stop_loss   = round(price - 1.5 * atr, 6)
    take_profit = round(price + 2.5 * atr, 6)
    risk_reward = round((take_profit - price) / (price - stop_loss), 2) if price > stop_loss else 0

    return {
        "symbol":      crypto["symbol"].replace("USDT", ""),
        "name":        crypto["name"],
        "price":       stats["price"],
        "change_24h":  stats["change_pct"],
        "volume_usdt": stats["volume_usdt"],
        "score":       score,
        "signal":      signal,
        "reason":      reason,
        "rsi":         indicators["rsi"],
        "macd_hist":   indicators["macd_hist"],
        "ema_trend":   "↑ Alcista" if indicators["ema50"] > indicators["ema200"] else "↓ Bajista",
        "bb_pct":      f"{indicators['bb_pct'] * 100:.0f}%",
        "atr_pct":     indicators["atr_pct"],
        "stop_loss":   stop_loss,
        "take_profit": take_profit,
        "risk_reward": risk_reward,
    }
