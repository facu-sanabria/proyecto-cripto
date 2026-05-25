# ══════════════════════════════════════════════════════════════════════════════
# main.py — El "director de orquesta" del bot
#
# Este es el punto de entrada principal. Coordina a los demás módulos:
#   1. fetcher.py   → va a buscar los datos de Binance
#   2. analyzer.py  → analiza los datos y calcula señales
#   3. excel_writer → genera/actualiza el archivo Excel
#
# Se ejecuta con:   python main.py
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
from analyzer import analyze_crypto
from excel_writer import update_excel


def run_analysis():
    """
    Ejecuta un ciclo completo de análisis:
    Descarga datos → Analiza → Actualiza Excel
    """
    print(f"\n{'═' * 55}")
    print(f"  🔄  Análisis iniciado — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'═' * 55}")

    # ── PASO 1: Descargar datos ────────────────────────────────────────────────
    print(f"\n📡 Descargando datos de Binance ({TIMEFRAME})...")
    raw_data = fetch_all(CRYPTOS, TIMEFRAME)

    if not raw_data:
        print("❌ No se pudieron obtener datos. Reintentando en el próximo ciclo.")
        return

    print(f"   ✓ {len(raw_data)} criptomonedas descargadas")

    # ── PASO 2: Analizar cada crypto ──────────────────────────────────────────
    print(f"\n🔍 Calculando indicadores técnicos...")
    results = []

    for data in raw_data:
        try:
            result = analyze_crypto(data)
            results.append(result)
        except Exception as e:
            symbol = data["crypto"]["symbol"]
            print(f"  ⚠️  Error analizando {symbol}: {e}")

    # Ordenar por score: mejores oportunidades primero
    results.sort(key=lambda x: x["score"], reverse=True)

    # Mostrar resumen en consola
    print(f"\n{'─' * 55}")
    print(f"  {'CRYPTO':<8}  {'SEÑAL':<13}  {'SCORE':>6}  RAZÓN")
    print(f"{'─' * 55}")
    for r in results:
        icon = {
            "STRONG BUY":  "🟢",
            "BUY":         "🟩",
            "NEUTRAL":     "🟡",
            "SELL":        "🟠",
            "STRONG SELL": "🔴",
        }.get(r["signal"], "⚪")
        print(f"  {r['symbol']:<8}  {icon} {r['signal']:<11}  {r['score']:>+5}  {r['reason'][:35]}")
    print(f"{'─' * 55}")

    # Mostrar top 3 oportunidades
    buys = [r for r in results if r["signal"] in ("BUY", "STRONG BUY")]
    if buys:
        print(f"\n🏆 Top oportunidades de compra:")
        for r in buys[:3]:
            print(f"   {r['symbol']:6}  ${r['price']:,.4f}  →  TP: ${r['take_profit']:,.4f}  SL: ${r['stop_loss']:,.4f}  (R/R: {r['risk_reward']}x)")
    else:
        print(f"\n⏳ Sin señales de compra claras en este momento.")

    # ── PASO 3: Actualizar Excel ───────────────────────────────────────────────
    print(f"\n📊 Actualizando Excel...")
    update_excel(results, EXCEL_PATH)

    print(f"\n⏰ Próxima actualización en {REFRESH_MINUTES} minutos.")


# ─── Punto de entrada ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════╗
║     🤖  BOT DE ANÁLISIS CRIPTO  🤖           ║
╠══════════════════════════════════════════════╣
║  Fuente de datos:  Binance (público)         ║
║  Presioná Ctrl+C para detener el bot         ║
╚══════════════════════════════════════════════╝
    """)

    print(f"  Criptos a analizar: {len(CRYPTOS)}")
    print(f"  Timeframe:          {TIMEFRAME}")
    print(f"  Actualización:      cada {REFRESH_MINUTES} minutos")
    print(f"  Archivo Excel:      {EXCEL_PATH}")

    # Primera ejecución inmediata (no esperar N minutos)
    run_analysis()

    # Programar ejecuciones automáticas cada REFRESH_MINUTES minutos
    schedule.every(REFRESH_MINUTES).minutes.do(run_analysis)

    print(f"\n✅ Bot activo. Ctrl+C para detener.\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n👋 Bot detenido correctamente.")
