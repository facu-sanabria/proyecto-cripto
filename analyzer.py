# ══════════════════════════════════════════════════════════════════════════════
# analyzer.py — El "analista" del bot
#
# Calcula indicadores técnicos usando solo pandas y numpy (sin librerías TA).
# Cada fórmula está explicada en comentarios.
# ══════════════════════════════════════════════════════════════════════════════

import pandas as pd
import numpy as np

from config import SL_ATR_MULT, TP_ATR_MULT

# Indicadores importados desde indicators.py (ÚNICA FUENTE DE VERDAD).
# Re-exportados aquí para backward-compat: scalper.py y cualquier código que haga
# "from analyzer import calc_rsi" sigue funcionando sin cambios.
from indicators import (
    calc_rsi, calc_macd, calc_ema, calc_bollinger, calc_atr, calc_adx,
    calculate_indicators,
)


# ─── Sistema de scoring ───────────────────────────────────────────────────────

def score_crypto(ind: dict, adx_min: int = 18) -> tuple[int, str, str]:
    """
    Score de -100 a +100. Cuanto mayor, mejor oportunidad de compra.

    Versión 4: mejoras basadas en análisis de pérdidas del bot.

    Cambios respecto a v3:
    - adx_min parametrizable: 18 para 4h crypto, 13 para 1h stocks
      (ADX 1h es naturalmente más bajo por mayor ruido intraday).
    - Volumen DIRECCIONAL: volumen alto + MACD bajista ahora penaliza
      (confirma presión de venta, no solo ignora).
    - Detección de distribución/techo: cuando EMA50 converge hacia EMA200
      y ADX declina, cappear score ≤ 30 (tendencia debilitándose).
    - Calidad de pullback: bonus +8 si precio ≤ 2% sobre EMA20 en perfect_trend
      (dip-buy = entrada óptima); penalización -10 si >5% extendido
      (chasing = peor ratio de éxito).

    Args:
        ind:     dict de indicadores de compute_indicators().
        adx_min: ADX mínimo para considerar que hay tendencia.
                 Usar 18 para 4h, 13 para 1h.

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
    adx_prev       = ind.get("adx_prev", adx)
    plus_di        = ind.get("plus_di", 25.0)
    minus_di       = ind.get("minus_di", 25.0)

    # ═══════════════════════════════════════════════════════════════════════════
    # HARD BLOCKS — condiciones donde nunca operamos, retorno inmediato
    # ═══════════════════════════════════════════════════════════════════════════

    # 1. Bear market: tendencia bajista confirmada en 2 plazos temporales.
    #    Cada rebote es una trampa. Los traders profesionales no compran en bear.
    if (price < ema200) and (ema50 < ema200):
        return -35, "STRONG SELL", "Bear market: precio y EMA50 bajo EMA200"

    # 2. Sin tendencia: ADX < adx_min = mercado completamente lateral.
    #    RSI y MACD generan señales falsas en laterales. No operar.
    if adx < adx_min:
        return 0, "NEUTRAL", f"Sin tendencia (ADX {adx:.0f} < {adx_min})"

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

    # ─── Detección de distribución / techo de tendencia ──────────────────────
    # Señal de alerta: EMA50 converge hacia EMA200 Y ADX declina desde zona alta.
    # Esto precede frecuentemente a cruces bajistas. Cappear score a 30.
    if ema200 > 0:
        ema50_gap_pct = (ema50 - ema200) / ema200 * 100
    else:
        ema50_gap_pct = 100.0
    adx_declining = adx < adx_prev  # ADX bajando = tendencia perdiendo fuerza

    if (perfect_trend or good_trend) and ema50_gap_pct < 2.5 and adx_declining and adx < 28:
        score = min(score, 30)
        reasons.append(f"Tendencia debilitándose (gap EMA50/200: {ema50_gap_pct:.1f}%)")

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
    #    CLAVE v4: RSI 60-78 en tendencia fuerte NO es sobrecompra, es FUERZA.
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
    # 5. VOLUMEN — CONFIRMACIÓN DIRECCIONAL (±12)
    #    Volumen confirma dirección del movimiento.
    #    NUEVO v4: volumen alto en caída = presión vendedora = penalizar también.
    # ═══════════════════════════════════════════════════════════════════════════
    if volume_ratio > 2.0:
        if macd_hist > 0:
            score += 12
            reasons.append(f"Volumen fuerte {volume_ratio:.1f}x confirma alza")
        else:
            score -= 10
            reasons.append(f"Volumen {volume_ratio:.1f}x confirma caída")
    elif volume_ratio > 1.5:
        if macd_hist > 0:
            score += 8
            reasons.append(f"Volumen {volume_ratio:.1f}x confirma")
        elif macd_hist < 0:
            score -= 6
            reasons.append(f"Volumen {volume_ratio:.1f}x presión bajista")
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
    # 7. CALIDAD DEL PULLBACK (±10) — NUEVO v4
    #    En perfect_trend: el dip-buy cerca de EMA20 es la entrada óptima.
    #    "Chasing" (precio muy extendido sobre EMA20) = peor probabilidad.
    # ═══════════════════════════════════════════════════════════════════════════
    if ema20 > 0:
        price_vs_ema20_pct = (price - ema20) / ema20 * 100
    else:
        price_vs_ema20_pct = 0.0

    if perfect_trend:
        if -1.5 <= price_vs_ema20_pct <= 2.0:
            # Precio justo en la EMA20 o levemente sobre ella: zona óptima de entrada
            score += 8
            reasons.append(f"Pullback a EMA20 ({price_vs_ema20_pct:+.1f}%) ideal")
        elif price_vs_ema20_pct > 5.0:
            # Precio muy extendido: comprar tarde = mayor riesgo de corrección
            score -= 10
            reasons.append(f"Precio extendido {price_vs_ema20_pct:.1f}% sobre EMA20")

    # ═══════════════════════════════════════════════════════════════════════════
    # ADX: amplificador de tendencias fuertes (sin multiplicador negativo)
    # v4: solo amplificamos señales positivas en tendencias muy fuertes.
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

def analyze_crypto(data: dict, adx_threshold: int = 18) -> dict:
    """
    Análisis completo de una criptomoneda o acción.

    Args:
        data:          Dict con keys "crypto", "ohlcv", "stats"
        adx_threshold: ADX mínimo para considerar tendencia.
                       18 para 4h crypto (default), 13 para 1h stocks
                       (1h produce ADX naturalmente más bajo por ruido intraday).

    Returns:
        Dict listo para el Excel / display.
    """
    crypto = data["crypto"]
    ohlcv  = data["ohlcv"]
    stats  = data["stats"]

    indicators         = calculate_indicators(ohlcv)
    score, signal, reason = score_crypto(indicators, adx_min=adx_threshold)

    atr   = indicators["atr"]
    price = stats["price"]

    stop_loss   = round(price - SL_ATR_MULT * atr, 6)
    take_profit = round(price + TP_ATR_MULT * atr, 6)
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
