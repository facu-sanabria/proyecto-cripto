# CLAUDE.md — Reglas para Claude Code en este repo

## Qué es este proyecto

Bot de análisis técnico cripto + acciones USA. **No opera dinero real** — genera señales
y simula PnL de sesión. Dos modos:

| Modo | Archivo | Timeframe | Mercado |
|------|---------|-----------|---------|
| Live dashboard (scalping) | `main.py` | 5m / 15m | Crypto Binance |
| Bot Excel (swing) | N/A — legado | 4h | Crypto Binance |
| Backtesting histórico | `backtester.py` | 4h | Crypto Binance + Stocks |

## Cómo correr

```powershell
# Instalar dependencias (una sola vez)
pip install requests pandas numpy openpyxl schedule python-dotenv rich pytest

# Dashboard live
cd C:\proyecto-cripto
$env:PYTHONIOENCODING="utf-8"
python main.py

# Backtester
python backtester.py --months 6
python backtester.py --months 3 --symbol BTCUSDT --no-fg
```

## Mapa de módulos

| Archivo | Rol | Importado por |
|---------|-----|---------------|
| `config.py` | Constantes globales (CRYPTOS, SL/TP multipliers, etc.) | todo |
| `indicators.py` | Cálculos técnicos puros (RSI, MACD, EMA, ATR, ADX, Bollinger) | `analyzer.py`, `backtester.py` |
| `analyzer.py` | Scoring trend-following + SL/TP para 4h/1h | `main.py`, `backtester.py` |
| `scalper.py` | Scoring scalping (StochRSI, VWAP, BB Squeeze) + SL/TP para 5m/15m | `main.py` |
| `fetcher.py` | Descarga OHLCV de Binance (API pública) | `main.py`, `backtester.py` |
| `stocks_fetcher.py` | Descarga OHLCV de Yahoo Finance para acciones USA | `main.py`, `backtester.py` |
| `backtester.py` | Simulación histórica con fills, SL/TP, equity curve | standalone |
| `market_context.py` | Fear & Greed histórico (ajuste opcional de score) | `backtester.py` |
| `notifier.py` | Telegram alerts (requiere .env) | `main.py` |
| `main.py` | Dashboard Rich live, threads, simulador de sesión | entry point |

## ⚡ Reglas de oro — LEER ANTES DE CAMBIAR CÓDIGO

### 1. Prohibido look-ahead (regla #1)

Cualquier cálculo en la barra `t` debe usar SOLO datos de `t-N ... t`.
Nunca `df.iloc[i+1]`, nunca `.shift(-1)`, nunca acceder a filas futuras.

**Test de paridad:** `tests/test_no_lookahead.py` verifica que ningún indicador
en la barra `t` cambie cuando se agrega una barra futura.

### 2. Paridad live/backtest

`SL_ATR_MULT` y `TP_ATR_MULT` en `config.py` son la ÚNICA fuente de verdad.
`analyzer.py` y `backtester.py` los importan desde ahí.
**Nunca hardcodear** multiplicadores en esos archivos.

Los indicadores calculados deben ser idénticos en live y backtest:
ambos usan las funciones de `indicators.py`.

**Excepción documentada:** `scalper.py` usa `SL = max(1.0×ATR, 0.3%)` para 5m,
diferente de `config.SL_ATR_MULT=1.5`. El backtester corre en 4h — no cubre
el path de scalping en 5m.

### 3. Backtests siempre con costos

El `backtester.py` **no descuenta** comisión/slippage todavía (pendiente Tarea futura).
El simulador de sesión en `main.py` sí descuenta: `ROUND_TRIP_COST_PCT = 0.30%`.
Al agregar o modificar el backtester, incluir costos de trading.

### 4. Estadísticas de sesión = simulación real de fills

`build_stats_panel()` en `main.py` usa el módulo de posiciones con simulación por velas:
- Máximo 1 posición por símbolo
- Cierre en primera vela que toca SL o TP
- PnL neto de costos en cada cerrada

**Nunca** comparar precio actual contra TP/SL para decidir WIN/LOSS.
Eso es un snapshot, no una simulación.

### 5. Secretos solo en .env

- `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` van en `.env` (ignorado por git).
- `.gitignore` incluye `.env`.
- Nunca hardcodear tokens, API keys, ni credenciales en código.

## Pendientes conocidos

- [ ] **Backtester sin costos**: agregar `COMMISSION_PCT`/`SLIPPAGE_PCT` desde config.
- [ ] **Scalper en backtest**: el path 5m/15m de scalper.py no está backtestado.
- [ ] **SOL esperanza negativa** (3 meses recientes, ambos TP configs): revisar estrategia o excluir.
- [ ] **Tests de integración**: probar que main.py arranca sin errores en modo --dry-run.

## Sobre el diagnóstico de Mayo 2026

### Bugs corregidos
1. `TP_ATR_MULT` desajuste live/backtest → **unificado en config.py** (T2)
2. `build_stats_panel` comparaba snapshot precio vs TP/SL → **simulador por velas** (T3)
3. Re-registro de operaciones (cooldown 90min) → **max 1 posición/símbolo** (T3)

### Qué se encontró
- Backtest usa 4h pero live scalper usa 5m: son paths distintos, el backtest no valida el scalper.
- SOL PF < 1 en ambas configs (3 meses): muestra negativa insuficiente para conclusiones.
- La "ganancia acumulada" negativa reportada era artefacto del bug de snapshot, no pérdida real.
