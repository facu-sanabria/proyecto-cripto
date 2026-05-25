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
