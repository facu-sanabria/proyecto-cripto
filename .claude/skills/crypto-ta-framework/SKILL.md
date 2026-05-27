---
name: crypto-ta-framework
description: Usar cuando el usuario pregunta sobre el framework de análisis técnico del bot, cómo funciona el scoring de -100 a +100, pesos de indicadores, o quiere entender la lógica de señales BUY/SELL/NEUTRAL.
---

# Crypto Technical Analysis Framework

## Sistema de Scoring

```
Score total = suma ponderada de todos los indicadores
Rango: -100 (máx bearish) → +100 (máx bullish)

STRONG BUY:   score >= +60
BUY:          score >= +25
NEUTRAL:      score entre -25 y +25
SELL:         score <= -25
STRONG SELL:  score <= -60
```

## Indicadores y pesos (versión 3 — trend-following)

| Indicador | Peso máx | Notas |
|-----------|----------|-------|
| Alineación EMA (20/50/200) | ±30 | Base — determina el techo del score |
| MACD histograma | ±25 | Trigger de entrada principal |
| RSI (14) | ±18 | Con contexto de tendencia (RSI alto en uptrend = FUERZA) |
| Bollinger Bands | ±8 | Solo en pullbacks, no en tendencias |
| Volumen relativo | ±12 | Confirmación de movimiento |
| Volatilidad ATR | hasta -15 | Filtro de riesgo |
| ADX (bonus) | ×1.15 | Amplifica scores positivos en tendencias fuertes |

## Hard Blocks (retorno inmediato, sin scoring)

1. **Bear market**: `precio < EMA200 AND EMA50 < EMA200` → retorna -35, "STRONG SELL"
2. **Sin tendencia**: `ADX < 18` → retorna 0, "NEUTRAL"
3. **Volatilidad extrema**: `ATR% > 8%` → retorna -10, "NEUTRAL"

## Timeframes

- **Scalping (scalper.py)**: 5m + 15m — StochRSI, VWAP, EMA crossover 5/13
- **Swing/4h (analyzer.py)**: 4h — RSI, MACD, EMA 20/50/200, ADX
- **Backtest**: 4h (mismo que swing)

Siempre analizar tendencia mayor antes de entrar.

## Paridad live/backtest (regla de oro)

- `SL_ATR_MULT` y `TP_ATR_MULT` definidos en `config.py`
- `analyzer.py` y `backtester.py` los importan desde ahí
- **Nunca hardcodear** multiplicadores
- `scalper.py` usa parámetros diferentes (5m TF distinto) — documentado

## Implementación Python

Los indicadores están en `indicators.py` (shared) e importados por `analyzer.py` y `backtester.py`:

```python
from indicators import calc_rsi, calc_macd, calc_ema, calc_bollinger, calc_atr, calc_adx
```

**NO usar la librería `ta`** — este bot calcula todo manualmente en pandas/numpy
para control total sobre las fórmulas y ausencia de dependencias externas.
