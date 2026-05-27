# ══════════════════════════════════════════════════════════════════════════════
# config.py — Configuración del bot
# Acá podés cambiar qué criptos analizar, cada cuánto tiempo y más.
# ══════════════════════════════════════════════════════════════════════════════

# Lista de criptomonedas a analizar
# "symbol" es el par de trading en Binance (siempre termina en USDT)
# "name"   es el nombre amigable para mostrar en el Excel
# Cartera core — seleccionados por backtest 2024:
#   BTC: PF 1.59, +44.1%, 47 trades (mayor muestra estadística crypto)
#   SOL: PF 1.35, +44.8%, 39 trades (mejor altcoin en bulls)
CRYPTOS = [
    {"symbol": "BTCUSDT", "name": "Bitcoin"},
    {"symbol": "SOLUSDT", "name": "Solana"},
]

# Timeframe para el análisis técnico
# "15m" = velas de 15 minutos (para trading rápido)
# "1h"  = velas de 1 hora
# "4h"  = velas de 4 horas (recomendado para swing trading)
# "1d"  = velas diarias (para inversiones más largas)
TIMEFRAME = "4h"

# Cuántas velas descargar para calcular los indicadores
# Más velas = indicadores más precisos, pero descarga más lenta
CANDLES = 200

# Cada cuántos minutos se actualiza el Excel
REFRESH_MINUTES = 5

# Nombre del archivo Excel de salida
EXCEL_PATH = "crypto_signals.xlsx"

# ─── Parámetros ATR para Stop-Loss y Take-Profit ──────────────────────────────
# ÚNICA FUENTE DE VERDAD — usada por analyzer.py Y backtester.py.
# Live y backtest deben ser matemáticamente idénticos.
#
# SL = precio_entrada - SL_ATR_MULT × ATR
# TP = precio_entrada + TP_ATR_MULT × ATR
# R/R = TP_ATR_MULT / SL_ATR_MULT = 3.0 / 1.5 = 2.0
# Break-even WR mínimo = SL_ATR_MULT / (SL_ATR_MULT + TP_ATR_MULT) = 33.3%
#
# NOTA: scalper.py (crypto 5m/15m live) usa SL=1.0×ATR con floor 0.3%.
# Es un path diferente (timeframe distinto) y NO está cubierto por el backtest de 4h.
SL_ATR_MULT = 1.5
TP_ATR_MULT = 3.0
