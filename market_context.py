# ══════════════════════════════════════════════════════════════════════════════
# market_context.py — Contexto global del mercado
#
# Lo que el análisis técnico NO puede ver:
#   - Psicología colectiva (Fear & Greed)
#   - Cuánto están apostando los traders con apalancamiento (Funding Rates)
#   - Hacia dónde fluye el dinero dentro de crypto (BTC Dominance)
#
# Estas señales explican por qué el precio sube o baja ANTES de que los
# indicadores técnicos lo reflejen. Un trader profesional los revisa siempre.
# ══════════════════════════════════════════════════════════════════════════════

import requests
import pandas as pd
import time
from datetime import datetime

# ─── URLs de APIs públicas y gratuitas ────────────────────────────────────────

FEAR_GREED_URL   = "https://api.alternative.me/fng/"
COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"
BINANCE_FUTURES  = "https://fapi.binance.com/fapi/v1/premiumIndex"


# ─── Fear & Greed Index ───────────────────────────────────────────────────────

def get_fear_greed_index() -> dict:
    """
    Fear & Greed Index — Estado emocional actual del mercado cripto.
    API gratuita de alternative.me.

    Interpretación:
      0-25   → Miedo Extremo  (pánico, posible fondo, comprar)
      25-45  → Miedo          (cautela, mercado débil)
      45-55  → Neutro         (sin señal clara)
      55-75  → Codicia        (optimismo, cuidado)
      75-100 → Codicia Extrema (todos ya compraron → caída inminente, NO comprar)

    Regla de Warren Buffett aplicada a crypto:
    "Sé codicioso cuando otros tienen miedo, sé temeroso cuando otros son codiciosos."
    """
    try:
        resp = requests.get(FEAR_GREED_URL, params={"limit": 1}, timeout=5)
        resp.raise_for_status()
        data = resp.json()["data"][0]
        return {
            "value":          int(data["value"]),
            "classification": data["value_classification"],
            "ok":             True,
        }
    except Exception as e:
        return {"value": 50, "classification": "Neutral", "ok": False, "error": str(e)}


def get_historical_fear_greed(days: int = 365) -> pd.Series | None:
    """
    Descarga el historial del Fear & Greed Index para usar en backtesting.
    Permite aplicar el filtro F&G en períodos pasados.

    Returns:
        Serie con índice de fechas y valores F&G (0-100).
    """
    try:
        resp = requests.get(FEAR_GREED_URL, params={"limit": days}, timeout=10)
        resp.raise_for_status()
        data = resp.json()["data"]

        records = []
        for d in data:
            ts  = datetime.fromtimestamp(int(d["timestamp"]))
            val = int(d["value"])
            records.append({"date": ts.date(), "fg_value": val})

        df = pd.DataFrame(records).set_index("date").sort_index()
        return df["fg_value"]

    except Exception:
        return None


# ─── BTC Dominance ────────────────────────────────────────────────────────────

def get_btc_dominance() -> dict:
    """
    BTC Dominance — % del mercado cripto total que representa Bitcoin.

    Interpretación:
      Dominance subiendo  → dinero saliendo de altcoins hacia BTC → NO comprar altcoins
      Dominance bajando   → dinero entrando a altcoins             → altcoin season
      > 58%               → BTC absorbe todo, altcoins sufren
      < 48%               → Altcoin season, todo sube

    Esto explica por qué a veces el bot pierde en altcoins aunque BTC sube:
    el dinero está yendo a BTC, no a las altcoins.
    """
    try:
        resp = requests.get(COINGECKO_GLOBAL, timeout=8)
        resp.raise_for_status()
        pct = resp.json()["data"]["market_cap_percentage"]["btc"]
        return {"btc_dominance": round(float(pct), 2), "ok": True}
    except Exception as e:
        return {"btc_dominance": 52.0, "ok": False, "error": str(e)}


# ─── Funding Rates ────────────────────────────────────────────────────────────

def get_funding_rate(symbol: str) -> dict:
    """
    Funding Rate — Tasa que los traders apalancados en futuros pagan cada 8h.

    Interpretación:
      > +0.10% cada 8h  → mercado MUY apalancado en longs → liquidación masiva inminente
                          Los precios bajan para liquidar esos longs (cascada)
      +0.01% a +0.05%   → Normal, mercado optimista
      ~0%               → Neutral
      < -0.03%          → Muchos shorts, posible short squeeze (precio sube)

    Por qué importa: cuando todo el mundo está apalancado en la misma dirección,
    el mercado los liquida brutalmente. Nunca comprar con funding muy positivo.
    """
    try:
        resp = requests.get(BINANCE_FUTURES, params={"symbol": symbol}, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        rate = float(data.get("lastFundingRate", 0))
        return {
            "rate":           rate,
            "rate_pct":       round(rate * 100, 4),
            "overleveraged":  rate > 0.001,    # > 0.1% = peligroso
            "short_squeeze":  rate < -0.0003,  # < -0.03% = posible squeeze
            "ok":             True,
        }
    except Exception as e:
        return {"rate": 0.0, "rate_pct": 0.0, "overleveraged": False,
                "short_squeeze": False, "ok": False, "error": str(e)}


# ─── Contexto completo ────────────────────────────────────────────────────────

def get_full_market_context(crypto_symbols: list[str]) -> dict:
    """
    Recopila todo el contexto de mercado de una vez.
    Llamar una sola vez antes de analizar todas las criptos.

    Returns:
        Dict con fear_greed, btc_dominance, y funding_rates por símbolo.
    """
    fg      = get_fear_greed_index()
    btc_dom = get_btc_dominance()
    time.sleep(0.3)

    funding_rates = {}
    for sym in crypto_symbols:
        if sym.endswith("USDT"):
            funding_rates[sym] = get_funding_rate(sym)
            time.sleep(0.1)

    return {
        "fear_greed":    fg,
        "btc_dominance": btc_dom,
        "funding_rates": funding_rates,
    }


# ─── Ajuste de score por contexto ────────────────────────────────────────────

def market_context_score_adjustment(
    symbol:     str,
    is_btc:     bool,
    market_ctx: dict,
    date=None,
    fg_history: pd.Series | None = None,
) -> tuple[int, list[str]]:
    """
    Calcula el ajuste de score basado en el contexto de mercado.

    Para backtesting: si se pasan fg_history y date, usa el F&G histórico.
    Para live: usa el F&G actual del market_ctx.

    Returns:
        (ajuste_score, razones)
    """
    adjustment = 0
    reasons    = []

    # ── Fear & Greed ──────────────────────────────────────────────────────────
    fg_value = 50  # default neutral

    if fg_history is not None and date is not None:
        # Modo backtesting: buscar valor histórico de F&G para esa fecha
        try:
            lookup_date = date.date() if hasattr(date, "date") else date
            if lookup_date in fg_history.index:
                fg_value = int(fg_history[lookup_date])
            else:
                # Buscar el más cercano anterior
                prior = fg_history[fg_history.index <= lookup_date]
                if not prior.empty:
                    fg_value = int(prior.iloc[-1])
        except Exception:
            fg_value = 50
    else:
        fg_value = market_ctx.get("fear_greed", {}).get("value", 50)

    if fg_value <= 20:
        # Miedo Extremo: pánico = oportunidad histórica de compra
        # v3: reducido a +10 (era +20). F&G es contexto, no señal primaria.
        adjustment += 10
        reasons.append(f"F&G Miedo Extremo ({fg_value}) → oportunidad")
    elif fg_value <= 35:
        adjustment += 5
        reasons.append(f"F&G Miedo ({fg_value}) → favorable")
    elif fg_value >= 80:
        # Codicia Extrema: señal de precaución, PERO en bull markets puede durar semanas.
        # v3: reducido a -10 (era -25). No bloquear trades en bulls prolongados.
        adjustment -= 10
        reasons.append(f"F&G Codicia Extrema ({fg_value}) → precaución")
    elif fg_value >= 65:
        adjustment -= 5
        reasons.append(f"F&G Codicia ({fg_value}) → cautela")

    # ── BTC Dominance (solo altcoins) ─────────────────────────────────────────
    btc_dom_val = market_ctx.get("btc_dominance", {}).get("btc_dominance", 52.0)
    if not is_btc and symbol.endswith("USDT"):
        if btc_dom_val > 58:
            adjustment -= 15
            reasons.append(f"BTC Dom {btc_dom_val:.0f}% → dinero en BTC, no altcoins")
        elif btc_dom_val > 54:
            adjustment -= 8
            reasons.append(f"BTC Dom {btc_dom_val:.0f}% → altcoins débiles")
        elif btc_dom_val < 48:
            adjustment += 12
            reasons.append(f"BTC Dom {btc_dom_val:.0f}% → altcoin season")
        elif btc_dom_val < 52:
            adjustment += 5
            reasons.append(f"BTC Dom {btc_dom_val:.0f}% → favorable altcoins")

    # ── Funding Rate (solo crypto, solo en live) ──────────────────────────────
    if symbol.endswith("USDT"):
        fr = market_ctx.get("funding_rates", {}).get(symbol, {})
        if fr.get("ok"):
            rate_pct = fr.get("rate_pct", 0)
            if fr.get("overleveraged"):
                adjustment -= 25
                reasons.append(f"Funding {rate_pct:.3f}% → longs apalancados = riesgo")
            elif fr.get("short_squeeze"):
                adjustment += 12
                reasons.append(f"Funding {rate_pct:.3f}% → shorts atrapados")

    return adjustment, reasons


# ─── Resumen imprimible ───────────────────────────────────────────────────────

def print_market_context(ctx: dict):
    """Imprime el contexto de mercado de forma legible."""
    fg     = ctx.get("fear_greed", {})
    btc_d  = ctx.get("btc_dominance", {})

    fg_val  = fg.get("value", "?")
    fg_cls  = fg.get("classification", "?")
    dom_val = btc_d.get("btc_dominance", "?")

    print(f"\n  🌍 Contexto de Mercado:")
    print(f"     Fear & Greed:   {fg_val}/100 — {fg_cls}")
    print(f"     BTC Dominance:  {dom_val}%")

    funding = ctx.get("funding_rates", {})
    for sym, fr in funding.items():
        if fr.get("ok"):
            warn = " ⚠️  APALANCAMIENTO ALTO" if fr.get("overleveraged") else ""
            print(f"     Funding {sym:<12}: {fr['rate_pct']:+.4f}%{warn}")
