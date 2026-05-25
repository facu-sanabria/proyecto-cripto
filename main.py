# ══════════════════════════════════════════════════════════════════════════════
# main.py — Director de orquesta del bot
#
# Ciclo cada REFRESH_MINUTES:
#   1. Descarga datos crypto (Binance) + stocks (Yahoo Finance)
#   2. Calcula indicadores y score en cada activo
#   3. Imprime tabla en consola
#   4. Actualiza Excel
#   5. Manda notificación Telegram si hay STRONG BUY
#
# Cartera activa (seleccionada por backtest 2024):
#   Crypto: BTC, SOL
#   Stocks: NVDA, SPY
# ══════════════════════════════════════════════════════════════════════════════

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

import schedule
import time
from datetime import datetime

from config import CRYPTOS, TIMEFRAME, REFRESH_MINUTES, EXCEL_PATH
from fetcher import fetch_all
from stocks_fetcher import STOCKS_CORE, fetch_stocks_all
from analyzer import analyze_crypto
from excel_writer import update_excel
from notifier import notify_strong_signals, notify_cycle_summary

# Contador de ciclos para resumen periódico
_cycle_count = 0


def run_analysis():
    """
    Ciclo completo: descarga → analiza → Excel → notificaciones Telegram.
    """
    global _cycle_count
    _cycle_count += 1

    print(f"\n{'═' * 60}")
    print(f"  🔄  Ciclo #{_cycle_count} — {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"{'═' * 60}")

    all_results = []

    # ── PASO 1A: Crypto (Binance) ─────────────────────────────────────────────
    print(f"\n📡 Crypto ({TIMEFRAME}) — {', '.join(c['name'] for c in CRYPTOS)}...")
    crypto_data = fetch_all(CRYPTOS, TIMEFRAME)

    for data in crypto_data:
        try:
            result = analyze_crypto(data)
            result["asset_type"] = "crypto"
            all_results.append(result)
        except Exception as e:
            print(f"  ⚠️  Error analizando {data['crypto']['symbol']}: {e}")

    # ── PASO 1B: Stocks (Yahoo Finance) ──────────────────────────────────────
    print(f"\n📡 Stocks (1h) — {', '.join(s['name'] for s in STOCKS_CORE)}...")
    stocks_data = fetch_stocks_all(STOCKS_CORE, interval="1h", months=3)

    for data in stocks_data:
        try:
            result = analyze_crypto(data)   # misma función, mismo formato
            result["asset_type"] = "stock"
            all_results.append(result)
        except Exception as e:
            print(f"  ⚠️  Error analizando {data['crypto']['symbol']}: {e}")

    if not all_results:
        print("❌ Sin datos. Reintentando en el próximo ciclo.")
        return

    # ── PASO 2: Tabla de señales ──────────────────────────────────────────────
    all_results.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n{'─' * 65}")
    print(f"  {'ACTIVO':<8}  {'TIPO':<7}  {'SEÑAL':<13}  {'SCORE':>6}  RAZÓN")
    print(f"{'─' * 65}")

    for r in all_results:
        icon = {
            "STRONG BUY":  "🟢",
            "BUY":         "🟩",
            "NEUTRAL":     "🟡",
            "SELL":        "🟠",
            "STRONG SELL": "🔴",
        }.get(r["signal"], "⚪")
        tipo = r.get("asset_type", "crypto")
        print(f"  {r['symbol']:<8}  {tipo:<7}  {icon} {r['signal']:<11}  {r['score']:>+5}  {r['reason'][:32]}")

    print(f"{'─' * 65}")

    # ── PASO 3: Top oportunidades ─────────────────────────────────────────────
    strong_buys = [r for r in all_results if r["signal"] == "STRONG BUY"]
    buys        = [r for r in all_results if r["signal"] in ("BUY", "STRONG BUY")]

    if strong_buys:
        print(f"\n🚨 STRONG BUY detectado(s):")
        for r in strong_buys:
            price_fmt = f"{r['price']:,.2f}" if r['price'] > 1 else f"{r['price']:.6f}"
            sl_pct    = (r['stop_loss']   - r['price']) / r['price'] * 100
            tp_pct    = (r['take_profit'] - r['price']) / r['price'] * 100
            print(f"   🟢 {r['symbol']:<6}  ${price_fmt}")
            print(f"      SL: ${r['stop_loss']:,.4f} ({sl_pct:.1f}%)  TP: ${r['take_profit']:,.4f} (+{tp_pct:.1f}%)")
            print(f"      {r['reason'][:55]}")
    elif buys:
        print(f"\n🏆 Mejores oportunidades:")
        for r in buys[:2]:
            price_fmt = f"{r['price']:,.2f}" if r['price'] > 1 else f"{r['price']:.6f}"
            print(f"   {r['symbol']:<6}  ${price_fmt}  score {r['score']:+}  →  TP: ${r['take_profit']:,.4f}  SL: ${r['stop_loss']:,.4f}")
    else:
        print(f"\n⏳ Sin señales de compra activas.")

    # ── PASO 4: Excel ─────────────────────────────────────────────────────────
    print(f"\n📊 Actualizando Excel...")
    try:
        update_excel(all_results, EXCEL_PATH)
    except Exception as e:
        print(f"  ⚠️  Error Excel: {e}")

    # ── PASO 5: Notificaciones Telegram ───────────────────────────────────────
    sent = notify_strong_signals(all_results)

    # Resumen periódico cada hora (12 ciclos × 5 min = 60 min)
    if _cycle_count % 12 == 0:
        notify_cycle_summary(all_results, _cycle_count)

    print(f"\n⏰ Próxima actualización en {REFRESH_MINUTES} min.")
    if sent:
        print(f"📱 {sent} notificación(es) Telegram enviada(s).")


# ─── Punto de entrada ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════╗
║     🤖  BOT DE TRADING — CARTERA CORE  🤖           ║
╠══════════════════════════════════════════════════════╣
║  Crypto:  BTC · SOL          (Binance, 4h)          ║
║  Stocks:  NVDA · SPY         (Yahoo Finance, 1h)    ║
║  Alertas: Telegram           (STRONG BUY → aviso)   ║
║  Presioná Ctrl+C para detener                       ║
╚══════════════════════════════════════════════════════╝
    """)

    print(f"  Timeframe crypto:   {TIMEFRAME}")
    print(f"  Actualización:      cada {REFRESH_MINUTES} minutos")
    print(f"  Excel:              {EXCEL_PATH}")

    # Primera ejecución inmediata
    run_analysis()

    # Ciclos automáticos
    schedule.every(REFRESH_MINUTES).minutes.do(run_analysis)

    print(f"\n✅ Bot activo. Ctrl+C para detener.\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n👋 Bot detenido.")
