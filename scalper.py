# ══════════════════════════════════════════════════════════════════════════════
# scalper.py — Motor de análisis para scalping (trading corto plazo)
#
# Usa timeframes cortos (5m y 15m) e indicadores más sensibles que el bot
# original (4h). El objetivo es detectar movimientos de minutos, no días.
# ══════════════════════════════════════════════════════════════════════════════

import numpy as np
import pandas as pd
from indicators import calc_rsi, calc_ema, calc_macd, calc_atr, calc_bollinger


def calc_stoch_rsi(close: pd.Series, rsi_p=14, stoch_p=14, k_s=3, d_s=3):
    """
    Stochastic RSI — más sensible que el RSI normal. Ideal para scalping.
    Oscila entre 0 y 100.
      K < 20  = sobrevendido → posible rebote ↑
      K > 80  = sobrecomprado → posible caída ↓
    """
    rsi     = calc_rsi(close, rsi_p)
    rsi_min = rsi.rolling(stoch_p).min()
    rsi_max = rsi.rolling(stoch_p).max()
    diff    = (rsi_max - rsi_min).replace(0, np.nan)
    stoch   = (rsi - rsi_min) / diff * 100
    k_line  = stoch.rolling(k_s).mean()
    d_line  = k_line.rolling(d_s).mean()
    return k_line, d_line


def calc_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    VWAP de SESIÓN con reset diario (UTC).

    El VWAP clásico DEBE resetear al inicio de cada día de trading.
    Sin reset, la acumulación desde la barra 1 del dataset produce un
    promedio inútil que mezcla sesiones de días anteriores.

    Para crypto 24/7 en Binance: se resetea a las 00:00 UTC cada día.
    Precio > VWAP → mercado alcista intraday (referencia institucional)
    Precio < VWAP → mercado bajista intraday
    """
    tp  = (high + low + close) / 3
    idx = pd.to_datetime(high.index)
    day = idx.normalize()  # floor a UTC midnight — reset por día
    tpv = tp * volume
    df  = pd.DataFrame({"tpv": tpv.values, "vol": volume.values, "day": day},
                       index=high.index)
    df["cum_tpv"] = df.groupby("day")["tpv"].cumsum()
    df["cum_vol"] = df.groupby("day")["vol"].cumsum()
    return (df["cum_tpv"] / df["cum_vol"]).rename("vwap")


def fmt_price(price: float) -> str:
    """Formatea precio con decimales apropiados según magnitud."""
    if price >= 1000:  return f"${price:,.2f}"
    elif price >= 10:  return f"${price:,.3f}"
    elif price >= 1:   return f"${price:,.4f}"
    else:              return f"${price:,.6f}"


def analyze_scalp(df_5m: pd.DataFrame, df_15m: pd.DataFrame) -> dict:
    """
    Análisis completo de scalping usando 2 timeframes:
      df_5m  → señales rápidas (StochRSI, EMA crossover, Volumen, VWAP)
      df_15m → filtro de tendencia (MACD)

    Returns: dict con score, señal, entry/SL/TP y razones.
    """
    close_5  = df_5m["close"]
    high_5   = df_5m["high"]
    low_5    = df_5m["low"]
    vol_5    = df_5m["volume"]
    close_15 = df_15m["close"]

    price = float(close_5.iloc[-1])

    # ── Indicadores en 5m ─────────────────────────────────────────────────────
    stoch_k, stoch_d = calc_stoch_rsi(close_5)
    k_now  = float(stoch_k.iloc[-1])
    k_prev = float(stoch_k.iloc[-2])
    d_now  = float(stoch_d.iloc[-1])

    e5_now   = float(calc_ema(close_5, 5).iloc[-1])
    e5_prev  = float(calc_ema(close_5, 5).iloc[-2])
    e13_now  = float(calc_ema(close_5, 13).iloc[-1])
    e13_prev = float(calc_ema(close_5, 13).iloc[-2])

    vwap_val   = float(calc_vwap(high_5, low_5, close_5, vol_5).iloc[-1])
    above_vwap = price > vwap_val

    atr_val = float(calc_atr(high_5, low_5, close_5, 14).iloc[-1])
    atr_pct = (atr_val / price) * 100

    vol_avg   = float(vol_5.rolling(20).mean().iloc[-1])
    vol_now_v = float(vol_5.iloc[-1])
    vol_ratio = vol_now_v / vol_avg if vol_avg > 0 else 1.0

    # Bollinger Band squeeze: bandas muy estrechas = movimiento fuerte inminente
    bb_upper, bb_lower, bb_pct = calc_bollinger(close_5)
    bb_width = float((bb_upper.iloc[-1] - bb_lower.iloc[-1]) / close_5.rolling(20).mean().iloc[-1] * 100)
    # AJUSTE v2: 0.6% para 5m BTC (en 5m el width normal es 0.3-0.8%).
    # El threshold original de 2.0% solo se cumplía en momentos de volatilidad extrema.
    bb_squeeze = bb_width < 0.6

    # ── Indicadores en 15m ────────────────────────────────────────────────────
    _, _, macd_hist_15 = calc_macd(close_15)
    mh_now  = float(macd_hist_15.iloc[-1])
    mh_prev = float(macd_hist_15.iloc[-2])

    # ── Sistema de Scoring ────────────────────────────────────────────────────
    score   = 0
    reasons = []

    # Stochastic RSI (±30 pts) — el indicador más importante para scalping
    #
    # MEJORA v2: Exigir que K cruce SOBRE D para la señal más fuerte.
    # K > D (K cruzando D desde abajo) = confirmación real de reversión.
    # Solo K > k_prev sin confirmar con D = señal débil, muchos falsos.
    k_crossed_d_up   = k_now > d_now and k_prev <= d_now   # K cruza D al alza
    k_crossed_d_down = k_now < d_now and k_prev >= d_now   # K cruza D a la baja

    if k_now < 25 and k_crossed_d_up:
        # Cross K>D desde sobreventa = señal más confiable del scalper
        score += 30; reasons.append(f"StochRSI K({k_now:.0f}) cruzó D desde sobreventa [FUERTE]")
    elif k_now < 20 and k_now > k_prev:
        score += 22; reasons.append(f"StochRSI giró en sobreventa ({k_now:.0f})")
    elif k_now < 20:
        score += 14; reasons.append(f"StochRSI sobrevendido ({k_now:.0f})")
    elif k_now < 30:
        score += 8;  reasons.append(f"StochRSI bajo ({k_now:.0f})")
    elif k_now > 75 and k_crossed_d_down:
        score -= 30; reasons.append(f"StochRSI K({k_now:.0f}) cruzó D desde sobrecompra [FUERTE]")
    elif k_now > 80 and k_now < k_prev:
        score -= 22; reasons.append(f"StochRSI giró en sobrecompra ({k_now:.0f})")
    elif k_now > 80:
        score -= 14; reasons.append(f"StochRSI sobrecomprado ({k_now:.0f})")
    elif k_now > 70:
        score -= 8;  reasons.append(f"StochRSI alto ({k_now:.0f})")
    else:
        reasons.append(f"StochRSI neutral ({k_now:.0f})")

    # EMA 5/13 crossover (±25 pts) — detección de cambio de tendencia a corto
    crossed_up   = e5_now > e13_now and e5_prev <= e13_prev
    crossed_down = e5_now < e13_now and e5_prev >= e13_prev

    if crossed_up:
        score += 25; reasons.append("EMA5 cruza EMA13 al alza [AHORA]")
    elif e5_now > e13_now:
        score += 10; reasons.append("EMA5 sobre EMA13")
    elif crossed_down:
        score -= 25; reasons.append("EMA5 cruza EMA13 a la baja [AHORA]")
    elif e5_now < e13_now:
        score -= 10; reasons.append("EMA5 bajo EMA13")

    # MACD en 15m (±20 pts) — confirma tendencia en TF mayor
    if mh_now > 0 and mh_prev <= 0:
        score += 20; reasons.append("MACD(15m) cruza cero [AHORA]")
    elif mh_now > 0 and mh_now > mh_prev:
        score += 15; reasons.append("MACD(15m) alcista y creciendo")
    elif mh_now > 0:
        score += 8;  reasons.append("MACD(15m) positivo")
    elif mh_now < 0 and mh_prev >= 0:
        score -= 20; reasons.append("MACD(15m) cruza cero [AHORA]")
    elif mh_now < 0 and mh_now < mh_prev:
        score -= 15; reasons.append("MACD(15m) bajista y cayendo")
    else:
        score -= 8;  reasons.append("MACD(15m) negativo")

    # Volumen (±15 pts) — volumen alto confirma el movimiento
    if vol_ratio > 2.5:
        if score > 0:
            score += 15; reasons.append(f"Volumen {vol_ratio:.1f}x MUY ALTO confirma")
        else:
            score -= 10; reasons.append(f"Volumen {vol_ratio:.1f}x en caida = peligro")
    elif vol_ratio > 1.5:
        if score > 0:
            score += 8; reasons.append(f"Volumen {vol_ratio:.1f}x confirma")

    # VWAP (±10 pts) — referencia institucional intraday
    if above_vwap:
        score += 10; reasons.append("Sobre VWAP (alcista intraday)")
    else:
        score -= 10; reasons.append("Bajo VWAP (bajista intraday)")

    # Bollinger Squeeze — bonus si hay squeeze y score positivo
    # AJUSTE v2: threshold BB 0.6% (antes 2.0% nunca se cumplía en 5m).
    # BB width en 5m BTC suele ser 0.3-0.8%; 2.0% es solo en volatilidad extrema.
    if bb_squeeze and score > 30:
        score += 10; reasons.append("BB Squeeze: movimiento fuerte inminente")

    score = max(-100, min(100, score))

    # ── Señal ─────────────────────────────────────────────────────────────────
    # AJUSTE v2: threshold COMPRAR sube 55→62 para filtrar entradas marginales.
    # Score 55-61 mostraba win rate < 45% históricamente (señales de calidad media).
    if score >= 62:
        signal = "COMPRAR"
    elif score >= 30:
        signal = "POSIBLE COMPRA"
    elif score <= -62:
        signal = "VENDER/EVITAR"
    elif score <= -30:
        signal = "POSIBLE VENTA"
    else:
        signal = "ESPERAR"

    # ── Parámetros de entrada para scalping ───────────────────────────────────
    # Stop Loss: 1× ATR, mínimo 0.3% (no menor — slippage)
    # TP1: 1.5× SL (salir con 50% de la posición)
    # TP2: 2.5× SL (salir con el resto)
    sl_dist  = max(atr_val * 1.0, price * 0.003)
    tp1_dist = sl_dist * 1.5
    tp2_dist = sl_dist * 2.5

    sl_pct  = round((sl_dist  / price) * 100, 2)
    tp1_pct = round((tp1_dist / price) * 100, 2)
    tp2_pct = round((tp2_dist / price) * 100, 2)
    rr      = round(tp1_dist / sl_dist, 2)
    conf    = min(95, max(30, abs(score) + 20))

    return {
        "score":      score,
        "signal":     signal,
        "reasons":    reasons[:4],
        "price":      price,
        "stoch_k":    round(k_now, 1),
        "stoch_d":    round(d_now, 1),
        "ema5":       round(e5_now, 6),
        "ema13":      round(e13_now, 6),
        "macd_hist":  round(mh_now, 8),
        "vol_ratio":  round(vol_ratio, 2),
        "vwap":       round(vwap_val, 6),
        "above_vwap": above_vwap,
        "atr_pct":    round(atr_pct, 3),
        "bb_squeeze": bb_squeeze,
        "entry":      price,
        "sl_pct":     sl_pct,
        "tp1_pct":    tp1_pct,
        "tp2_pct":    tp2_pct,
        "rr":         rr,
        "confidence": conf,
    }
