"""
mega_backtest.py — Backtest comprehensivo multi-activo multi-período.

Testea todos los activos disponibles en 3m, 6m y 12m.
Genera ranking final por PF promedio ponderado.
Uso: python mega_backtest.py
"""

import sys
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

from backtester import (
    fetch_historical_ohlcv, run_backtest, calc_stats,
    DEFAULT_CAPITAL, INDICATOR_WINDOW,
)
from stocks_fetcher import get_stock_ohlcv
from config import SL_ATR_MULT, TP_ATR_MULT, COMMISSION_PCT, SLIPPAGE_PCT
from market_context import get_historical_fear_greed

# ─── Activos a probar ─────────────────────────────────────────────────────────

CRYPTO_ASSETS = [
    {"symbol": "BTCUSDT",  "name": "Bitcoin",  "type": "crypto"},
    {"symbol": "ETHUSDT",  "name": "Ethereum", "type": "crypto"},
    {"symbol": "SOLUSDT",  "name": "Solana",   "type": "crypto"},
    {"symbol": "BNBUSDT",  "name": "BNB",      "type": "crypto"},
    {"symbol": "XRPUSDT",  "name": "XRP",      "type": "crypto"},
    {"symbol": "ADAUSDT",  "name": "ADA",      "type": "crypto"},
    {"symbol": "AVAXUSDT", "name": "AVAX",     "type": "crypto"},
    {"symbol": "LINKUSDT", "name": "LINK",     "type": "crypto"},
    {"symbol": "DOGEUSDT", "name": "DOGE",     "type": "crypto"},
]

STOCK_ASSETS = [
    {"symbol": "NVDA",  "name": "NVIDIA",    "type": "stock"},
    {"symbol": "AAPL",  "name": "Apple",     "type": "stock"},
    {"symbol": "MSFT",  "name": "Microsoft", "type": "stock"},
    {"symbol": "META",  "name": "Meta",      "type": "stock"},
    {"symbol": "GOOGL", "name": "Google",    "type": "stock"},
    {"symbol": "SPY",   "name": "S&P 500",   "type": "etf"},
    {"symbol": "QQQ",   "name": "Nasdaq100", "type": "etf"},
    {"symbol": "GLD",   "name": "Gold ETF",  "type": "commodity"},
]

PERIODS_MONTHS = [3, 6, 12]
THRESHOLD      = 50
CAPITAL        = 1000.0
TIMEFRAME      = "4h"

# ─── Helpers ──────────────────────────────────────────────────────────────────

def score_pf(pf):
    """Transforma PF a score numérico manejando infinito."""
    if pf == float("inf"):
        return 3.0
    return pf

def run_one(asset, months):
    """Descarga datos y corre backtest para un activo y período."""
    sym      = asset["symbol"]
    is_stock = asset["type"] in ("stock", "etf", "commodity")

    try:
        if is_stock:
            df = get_stock_ohlcv(sym, "1h", months)
        else:
            df = fetch_historical_ohlcv(sym, TIMEFRAME, months)

        if df is None or len(df) < INDICATOR_WINDOW + 10:
            return None

        result = run_backtest(
            df              = df,
            initial_capital = CAPITAL,
            threshold       = THRESHOLD,
            fg_history      = None,
            symbol          = sym,
            is_btc          = sym == "BTCUSDT",
        )
        stats = calc_stats(result, CAPITAL, sym)
        stats["months"] = months
        return stats

    except Exception as e:
        print(f"    ERROR {sym} {months}m: {e}")
        return None


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    all_assets = CRYPTO_ASSETS + STOCK_ASSETS
    total      = len(all_assets) * len(PERIODS_MONTHS)
    done       = 0

    bar = "═" * 76
    print(f"\n{bar}")
    print(f"  MEGA BACKTEST — {len(all_assets)} activos × {PERIODS_MONTHS} meses = {total} simulaciones")
    print(f"  Threshold: {THRESHOLD} | Capital: ${CAPITAL:,.0f} | SL={SL_ATR_MULT}×ATR | TP={TP_ATR_MULT}×ATR")
    print(f"  Costos: {COMMISSION_PCT}%+{SLIPPAGE_PCT}% × 2 lados = {(COMMISSION_PCT+SLIPPAGE_PCT)*2:.2f}% round-trip")
    print(f"{bar}\n")

    # {sym: {months: stats}}
    results = {}

    for asset in all_assets:
        sym  = asset["symbol"]
        name = asset["name"]
        results[sym] = {}

        for months in PERIODS_MONTHS:
            done += 1
            print(f"  [{done:>2}/{total}] {name:<12} {months}m ...", end=" ", flush=True)

            stats = run_one(asset, months)
            if stats is None:
                results[sym][months] = None
                print("sin datos")
                continue

            results[sym][months] = stats
            t  = stats["total_trades"]
            wr = stats["win_rate"]
            rt = stats["total_return_pct"]
            pf = stats["profit_factor"]
            pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
            print(f"{t:>3} trades | WR {wr:.0f}% | {rt:+.1f}% | PF {pf_str}")

            # Pausa para no saturar APIs
            time.sleep(0.3 if asset["type"] == "crypto" else 1.5)

    # ─── Tabla de síntesis ────────────────────────────────────────────────────
    print(f"\n{bar}")
    print(f"  SÍNTESIS POR ACTIVO")
    print(f"{bar}")

    rows = []
    for asset in all_assets:
        sym   = asset["symbol"]
        name  = asset["name"]
        atype = asset["type"]

        period_stats = [results[sym].get(m) for m in PERIODS_MONTHS]
        valid        = [s for s in period_stats if s and s["total_trades"] >= 3]

        if not valid:
            rows.append({
                "symbol": sym, "name": name, "type": atype,
                "trades_avg": 0, "wr_avg": 0, "ret_avg": 0,
                "ret_6m": 0, "ret_12m": 0,
                "pf_avg": 0, "pf_6m": 0,
                "consistency": 0, "score": 0,
                "verdict": "❌ Sin datos suficientes",
            })
            continue

        pfs  = [score_pf(s["profit_factor"]) for s in valid]
        wrs  = [s["win_rate"]         for s in valid]
        rets = [s["total_return_pct"] for s in valid]

        pf_avg  = float(np.mean(pfs))
        wr_avg  = float(np.mean(wrs))
        ret_avg = float(np.mean(rets))

        s6  = results[sym].get(6)
        s12 = results[sym].get(12)
        ret_6m  = s6["total_return_pct"]  if s6  and s6["total_trades"]  >= 3 else None
        ret_12m = s12["total_return_pct"] if s12 and s12["total_trades"] >= 3 else None
        pf_6m   = score_pf(s6["profit_factor"]) if s6 and s6["total_trades"] >= 3 else None

        # Consistencia: % de períodos con PF > 1
        consistency = sum(1 for s in valid if score_pf(s["profit_factor"]) > 1.0) / len(PERIODS_MONTHS) * 100

        # Score compuesto para ranking:
        # 40% PF promedio + 30% consistencia normalizada + 30% retorno promedio normalizado
        score = pf_avg * 0.4 + (consistency / 100) * 2 * 0.3 + max(ret_avg / 10, 0) * 0.3

        if pf_avg >= 1.3 and consistency >= 67:
            verdict = "✅ OPERAR"
        elif pf_avg >= 1.1 and consistency >= 50:
            verdict = "⚠️  Marginal"
        else:
            verdict = "❌ No operar"

        rows.append({
            "symbol":      sym,
            "name":        name,
            "type":        atype,
            "trades_avg":  int(np.mean([s["total_trades"] for s in valid])),
            "wr_avg":      round(wr_avg, 1),
            "ret_avg":     round(ret_avg, 2),
            "ret_6m":      round(ret_6m,  2) if ret_6m  is not None else None,
            "ret_12m":     round(ret_12m, 2) if ret_12m is not None else None,
            "pf_avg":      round(pf_avg,  2),
            "pf_6m":       round(pf_6m,   2) if pf_6m   is not None else None,
            "consistency": round(consistency, 0),
            "score":       round(score, 3),
            "verdict":     verdict,
        })

    rows.sort(key=lambda r: r["score"], reverse=True)

    # Header
    print(f"\n  {'SÍMBOLO':<10} {'NOMBRE':<12} {'TIPO':<10} "
          f"{'PF prom':>8} {'WR%':>5} {'Ret prom':>9} "
          f"{'Ret 6m':>7} {'Ret 12m':>8} {'Consist':>8} {'VEREDICTO'}")
    print("  " + "─" * 90)

    for r in rows:
        pf_str  = f"{r['pf_avg']:.2f}" if r['pf_avg'] else "─"
        r6_str  = f"{r['ret_6m']:+.1f}%"  if r['ret_6m']  is not None else "─"
        r12_str = f"{r['ret_12m']:+.1f}%" if r['ret_12m'] is not None else "─"

        print(f"  {r['symbol']:<10} {r['name']:<12} {r['type']:<10} "
              f"{pf_str:>8} {r['wr_avg']:>4.0f}% {r['ret_avg']:>+8.1f}% "
              f"{r6_str:>7} {r12_str:>8} {r['consistency']:>6.0f}%   {r['verdict']}")

    # ─── Recomendación de cartera ─────────────────────────────────────────────
    operar  = [r for r in rows if r["verdict"] == "✅ OPERAR"]
    margin  = [r for r in rows if r["verdict"] == "⚠️  Marginal"]

    print(f"\n{bar}")
    print(f"  CARTERA RECOMENDADA")
    print(f"{bar}")

    if operar:
        print(f"\n  ✅ OPERAR ({len(operar)} activos):")
        for r in operar:
            print(f"     {r['symbol']:<10} PF={r['pf_avg']:.2f}  WR={r['wr_avg']:.0f}%  "
                  f"Ret.prom={r['ret_avg']:+.1f}%  Consistencia={r['consistency']:.0f}%")

    if margin:
        print(f"\n  ⚠️  MARGINAL (operar solo si mercado acompaña):")
        for r in margin:
            print(f"     {r['symbol']:<10} PF={r['pf_avg']:.2f}  WR={r['wr_avg']:.0f}%  "
                  f"Ret.prom={r['ret_avg']:+.1f}%  Consistencia={r['consistency']:.0f}%")

    no_op = [r for r in rows if r["verdict"] == "❌ No operar"]
    if no_op:
        print(f"\n  ❌ NO OPERAR: {', '.join(r['symbol'] for r in no_op)}")

    # ─── Sugerencia de config.py ──────────────────────────────────────────────
    crypto_ok    = [r for r in operar if r["type"] == "crypto"]
    stocks_ok    = [r for r in operar if r["type"] in ("stock", "etf", "commodity")]
    stocks_marg  = [r for r in margin if r["type"] in ("stock", "etf", "commodity")]
    crypto_marg  = [r for r in margin if r["type"] == "crypto"]

    print(f"\n{bar}")
    print(f"  SUGERENCIA PARA config.py")
    print(f"{bar}")

    print("\n  # CRYPTOS (probadas en backtester 4h):")
    for r in crypto_ok + crypto_marg:
        sym_binance = r["symbol"]
        name        = r["name"]
        print(f'  {{"symbol": "{sym_binance}", "name": "{name}"}},  # PF={r["pf_avg"]:.2f}')

    print("\n  # STOCKS_CORE en stocks_fetcher.py:")
    for r in stocks_ok + stocks_marg:
        print(f'  {{"symbol": "{r["symbol"]}", "name": "{r["name"]}", "type": "{r["type"]}"}},  # PF={r["pf_avg"]:.2f}')

    print(f"\n{bar}\n")


if __name__ == "__main__":
    main()
