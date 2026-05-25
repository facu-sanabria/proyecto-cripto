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


def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    """
    ADX — Average Directional Index.
    Mide la FUERZA de la tendencia, no su dirección.

    ADX < 18: mercado lateral / sin tendencia → señales técnicas son RUIDO
              RSI y MACD dan señales falsas constantemente en laterales
    ADX 18-25: tendencia débil, operar con precaución
    ADX 25-40: tendencia clara → señales más confiables
    ADX > 40:  tendencia muy fuerte → alta confiabilidad

    +DI > -DI: la tendencia es alcista
    -DI > +DI: la tendencia es bajista

    Returns:
        (adx_series, plus_di_series, minus_di_series)
    """
    prev_high  = high.shift(1)
    prev_low   = low.shift(1)
    prev_close = close.shift(1)

    # True Range
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Movimientos direccionales
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

    # Suavizado exponencial
    atr_s     = tr.ewm(span=period, adjust=False).mean()
    plus_di   = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, np.nan)
    minus_di  = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, np.nan)

    di_sum    = (plus_di + minus_di).replace(0, np.nan)
    dx        = 100 * (plus_di - minus_di).abs() / di_sum
    adx       = dx.ewm(span=period, adjust=False).mean()

    return adx, plus_di, minus_di


# ─── Cálculo completo de indicadores ──────────────────────────────────────────

def calculate_indicators(df: pd.DataFrame) -> dict:
    """
    Calcula todos los indicadores y devuelve el valor de la última vela.

    Args:
        df: DataFrame con columnas open, high, low, close, volume

    Returns:
        Dict con valores actuales de cada indicador.
        Incluye valores "prev" (vela anterior) para detectar momentum y cambios de dirección.
    """
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    rsi_series                   = calc_rsi(close)
    rsi                          = rsi_series.iloc[-1]
    rsi_prev                     = rsi_series.iloc[-2] if len(rsi_series) >= 2 else rsi

    macd_line, macd_sig, macd_h  = calc_macd(close)
    macd_hist                    = macd_h.iloc[-1]
    macd_hist_prev               = macd_h.iloc[-2] if len(macd_h) >= 2 else macd_hist

    ema20                        = calc_ema(close, 20).iloc[-1]
    ema50                        = calc_ema(close, 50).iloc[-1]
    ema200                       = calc_ema(close, 200).iloc[-1]
    _, _, bb_pct                 = calc_bollinger(close)
    atr                          = calc_atr(high, low, close).iloc[-1]
    adx_series, plus_di_s, minus_di_s = calc_adx(high, low, close)
    adx                          = adx_series.iloc[-1]
    plus_di                      = plus_di_s.iloc[-1]
    minus_di                     = minus_di_s.iloc[-1]

    current_price  = close.iloc[-1]
    avg_volume     = volume.rolling(20).mean().iloc[-1]
    current_volume = volume.iloc[-1]
    volume_ratio   = current_volume / avg_volume if avg_volume > 0 else 1.0

    return {
        "price":          float(current_price),
        "rsi":            round(float(rsi), 2),
        "rsi_prev":       round(float(rsi_prev), 2),
        "macd_hist":      round(float(macd_hist), 6),
        "macd_hist_prev": round(float(macd_hist_prev), 6),
        "ema20":          round(float(ema20), 6),
        "ema50":          round(float(ema50), 6),
        "ema200":         round(float(ema200), 6),
        "bb_pct":         round(float(bb_pct.iloc[-1]), 4),
        "atr":            round(float(atr), 6),
        "atr_pct":        round((float(atr) / float(current_price)) * 100, 2),
        "volume_ratio":   round(float(volume_ratio), 2),
        "adx":            round(float(adx), 2),
        "plus_di":        round(float(plus_di), 2),
        "minus_di":       round(float(minus_di), 2),
    }


# ─── Sistema de scoring ───────────────────────────────────────────────────────

def score_crypto(ind: dict) -> tuple[int, str, str]:
    """
    Score de -100 a +100. Cuanto mayor, mejor oportunidad de compra.

    Versión 3: orientado a trend following (como operan los traders profesionales).

    Cambios respecto a v2:
    - ADX como HARD BLOCK (<18) en lugar de multiplicador ×0.6.
      El multiplicador aplastaba scores válidos: 85×0.6=51 nunca llegaba a 60.
    - RSI 60-78 en tendencia fuerte: NO penaliza.
      En trend following RSI alto = FUERZA, no sobrecompra.
    - BB superior: eliminada penalización en tendencias.
      Precio en banda superior durante uptrend = normal y saludable.
    - Bear market: hard block directo (retorna -35) en lugar de cap=15.
    - Sin tendencia: retorna 0/NEUTRAL directamente (ADX<18).

    Returns:
        (score, señal, razón)
    """
    price          = ind["price"]
    ema20          = ind["ema20"]
    ema50          = ind["ema50"]
    ema200         = ind["ema200"]
    rsi            = ind["rsi"]
    rsi_prev       = ind.get("rsi_prev", rsi)
    macd_hist      = ind["macd_hist"]
    macd_hist_prev = ind.get("macd_hist_prev", macd_hist)
    bb_pct         = ind["bb_pct"]
    volume_ratio   = ind["volume_ratio"]
    atr_pct        = ind["atr_pct"]
    adx            = ind.get("adx", 25.0)
    plus_di        = ind.get("plus_di", 25.0)
    minus_di       = ind.get("minus_di", 25.0)

    # ═══════════════════════════════════════════════════════════════════════════
    # HARD BLOCKS — condiciones donde nunca operamos, retorno inmediato
    # ═══════════════════════════════════════════════════════════════════════════

    # 1. Bear market: tendencia bajista confirmada en 2 plazos temporales.
    #    Cada rebote es una trampa. Los traders profesionales no compran en bear.
    if (price < ema200) and (ema50 < ema200):
        return -35, "STRONG SELL", "Bear market: precio y EMA50 bajo EMA200"

    # 2. Sin tendencia: ADX < 18 = mercado completamente lateral.
    #    RSI y MACD generan señales falsas en laterales. No operar.
    if adx < 18:
        return 0, "NEUTRAL", f"Sin tendencia (ADX {adx:.0f} < 18)"

    # 3. Volatilidad extrema: stop-loss demasiado ancho = riesgo incontrolable.
    if atr_pct > 8:
        return -10, "NEUTRAL", f"Volatilidad extrema ({atr_pct:.1f}%)"

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. ALINEACIÓN DE TENDENCIA (base: 0 a +30)
    #    La tendencia determina el techo del score posible.
    #    Setup ideal: precio > EMA20 > EMA50 > EMA200.
    # ═══════════════════════════════════════════════════════════════════════════
    score   = 0
    reasons = []

    perfect_trend = (price > ema20) and (ema20 > ema50) and (ema50 > ema200)
    good_trend    = (price > ema50) and (ema50 > ema200)   # pullback bajo EMA20 pero uptrend sano
    weak_uptrend  = price > ema200                          # solo sobre tendencia de largo plazo

    if perfect_trend:
        score += 30
        reasons.append("Tendencia perfecta (EMA20>50>200)")
    elif good_trend:
        score += 18
        reasons.append("Uptrend (pullback a EMA20)")
    elif weak_uptrend:
        score += 8
        reasons.append("Sobre EMA200")
    else:
        # Precio bajo EMA200 pero EMA50 aún sobre EMA200 → transición/distribución
        score -= 15
        reasons.append("Precio bajo EMA200 (debilitando)")

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. MOMENTUM MACD (±25)
    #    El trigger de entrada. Lo más importante es el CAMBIO de dirección.
    #    Cruce de 0 = momentum cambió de bajista a alcista → señal más fuerte.
    # ═══════════════════════════════════════════════════════════════════════════
    macd_cross_up   = macd_hist > 0 and macd_hist_prev <= 0
    macd_growing    = macd_hist > macd_hist_prev
    macd_cross_down = macd_hist < 0 and macd_hist_prev >= 0

    if macd_cross_up:
        score += 25
        reasons.append("MACD cruce alcista ⚡")
    elif macd_hist > 0 and macd_growing:
        score += 18
        reasons.append("MACD momentum creciente ↑")
    elif macd_hist > 0:
        score += 6
        reasons.append("MACD positivo (debilitando)")
    elif macd_cross_down:
        score -= 25
        reasons.append("MACD cruce bajista ↓")
    elif macd_hist < 0 and macd_growing:
        score -= 8
        reasons.append("MACD negativo (recuperando)")
    else:
        score -= 20
        reasons.append("MACD bajista ↓↓")

    # ═══════════════════════════════════════════════════════════════════════════
    # 3. RSI CON CONTEXTO DE TENDENCIA (±15)
    #
    #    CLAVE v3: RSI 60-78 en tendencia fuerte NO es sobrecompra, es FUERZA.
    #    Un trader no evita entrar porque el RSI está en 68 durante un bull run.
    #    Solo penalizamos RSI extremo (>78) o alto sin confirmación de tendencia.
    # ═══════════════════════════════════════════════════════════════════════════
    strong_trend = adx > 25 and plus_di > minus_di  # tendencia alcista confirmada por ADX

    if rsi < 30:
        score += 15
        reasons.append(f"RSI sobrevendido ({rsi:.0f})")
    elif rsi < 45 and rsi > rsi_prev:
        # Recuperación desde zona baja = dip-buy clásico
        score += 15
        reasons.append(f"RSI recuperando ({rsi:.0f}↑)")
    elif rsi < 50 and rsi > rsi_prev and (good_trend or perfect_trend):
        # Pullback a zona saludable en uptrend = excelente entrada
        score += 10
        reasons.append(f"RSI dip-buy ({rsi:.0f}↑ en uptrend)")
    elif rsi > 78:
        # Extremadamente sobrecomprado incluso en tendencias fuertes
        score -= 18
        reasons.append(f"RSI extremo ({rsi:.0f})")
    elif rsi > 70 and not strong_trend:
        # Sobrecomprado sin confirmación de tendencia fuerte
        score -= 12
        reasons.append(f"RSI alto ({rsi:.0f}) sin tendencia fuerte")
    # RSI 50-78 en uptrend: no penalizar. Es fuerza del mercado.

    # ═══════════════════════════════════════════════════════════════════════════
    # 4. BOLLINGER BANDS — solo en pullbacks (±8)
    #    En tendencias el precio corre cerca de la banda superior: es NORMAL.
    #    Solo usamos BB para confirmar pullbacks/rebotes.
    # ═══════════════════════════════════════════════════════════════════════════
    if bb_pct < 0.2 and not perfect_trend:
        score += 8
        reasons.append("Banda inferior BB (oversold)")
    elif bb_pct < 0.3 and good_trend:
        score += 4
        reasons.append("Cerca banda inferior BB")
    # No penalizar banda superior en tendencias alcistas

    # ═══════════════════════════════════════════════════════════════════════════
    # 5. VOLUMEN — CONFIRMACIÓN (±12)
    #    Volumen confirma movimientos legítimos. Sin volumen = sin convicción.
    # ═══════════════════════════════════════════════════════════════════════════
    if volume_ratio > 2.0 and macd_hist > 0:
        score += 12
        reasons.append(f"Volumen fuerte {volume_ratio:.1f}x confirma")
    elif volume_ratio > 1.5 and macd_hist > 0:
        score += 8
        reasons.append(f"Volumen {volume_ratio:.1f}x confirma")
    elif volume_ratio < 0.7:
        score -= 8
        reasons.append(f"Volumen débil {volume_ratio:.1f}x")

    # ═══════════════════════════════════════════════════════════════════════════
    # 6. VOLATILIDAD — FILTRO DE RIESGO (hasta -15)
    #    ATR alto = stop-loss más ancho = riesgo mayor por operación.
    # ═══════════════════════════════════════════════════════════════════════════
    if atr_pct > 5:
        score -= 15
        reasons.append(f"Volatilidad alta ({atr_pct:.1f}%)")
    elif atr_pct > 3:
        score -= 5
        reasons.append(f"Volatilidad moderada ({atr_pct:.1f}%)")

    # ═══════════════════════════════════════════════════════════════════════════
    # ADX: amplificador de tendencias fuertes (sin multiplicador negativo)
    # v3: solo amplificamos señales positivas en tendencias muy fuertes.
    #     Eliminado el ×0.6 que aplastaba scores en ADX 18-25.
    # ═══════════════════════════════════════════════════════════════════════════
    if adx > 35 and plus_di > minus_di and score > 0:
        score = min(100, int(score * 1.15))
        reasons.append(f"ADX {adx:.0f} tendencia fuerte ↑")

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
