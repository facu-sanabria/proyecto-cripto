# ══════════════════════════════════════════════════════════════════════════════
# config.py — Configuración del bot
# Acá podés cambiar qué criptos analizar, cada cuánto tiempo y más.
# ══════════════════════════════════════════════════════════════════════════════

# Lista de criptomonedas a analizar
# "symbol" es el par de trading en Binance (siempre termina en USDT)
# "name"   es el nombre amigable para mostrar en el Excel
#
# Cartera seleccionada por mega_backtest.py (17 activos × 3m/6m/12m, con costos):
#   BTC:  PF=1.21, WR=46%, Ret.prom=+5.0%,  Consistencia 100% (3/3 períodos > 1.0)
#   SOL:  PF=1.25, WR=48%, Ret.prom=+10.1%, Consistencia 100% — 12m: +26.2%
#
# Descartados: ETH (PF=0.54), XRP (PF=0.43), ADA (PF=0.73), AVAX (PF=0.58),
#              BNB (0% sin pérdidas pero inconsistente), DOGE/LINK marginales.
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
# R/R = TP_ATR_MULT / SL_ATR_MULT = 2.5 / 1.5 = 1.67
# Break-even WR mínimo = SL_ATR_MULT / (SL_ATR_MULT + TP_ATR_MULT) = 37.5%
#
# Elegido por backtest 6 meses (BTC PF=1.65, WR=50% vs PF=1.28, WR=38% con TP=3.0).
# TP=2.5 cierra ganadores antes de que el precio revierta — más robusto en mercado
# lateral/volátil. TP=3.0 requiere tendencias largas que son menos frecuentes.
#
# NOTA: scalper.py (crypto 5m/15m live) usa SL=1.0×ATR con floor 0.3%.
# Es un path diferente (timeframe distinto) y NO está cubierto por el backtest de 4h.
SL_ATR_MULT = 1.5
TP_ATR_MULT = 2.5

# ─── Costos de trading (backtester y simulador de sesión) ────────────────────
# Binance Spot taker: 0.075% por lado (con BNB o VIP 0).
# Slippage conservador en 4h: 0.05% (poca urgencia, mercados líquidos).
# Round-trip total = (comisión + slippage) × 2 lados.
#
# Con R/R=1.67 y SL=1.5×ATR, el break-even win-rate SIN costos es 37.5%.
# Con 0.25% round-trip round-trip, sube a ~40.5% → necesita mayor calidad de señales.
COMMISSION_PCT      = 0.075   # % por lado (Binance taker fee)
SLIPPAGE_PCT        = 0.050   # % por lado (estimación conservadora 4h)
ROUND_TRIP_COST_PCT = (COMMISSION_PCT + SLIPPAGE_PCT) * 2  # total: 0.25%
