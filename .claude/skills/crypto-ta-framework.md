# Crypto Technical Analysis Framework

## Trigger
Auto-activate when: user asks about crypto analysis, buy/sell signals, indicators, scoring, RSI, MACD, technical analysis, chart patterns, market trends for crypto.

## Framework

### Indicadores Primarios (peso total: 60%)

| Indicador | Peso | Señal Bullish | Señal Bearish |
|-----------|------|---------------|---------------|
| RSI (14) | 20% | < 30 (oversold) | > 70 (overbought) |
| MACD | 20% | Cruce bullish + histograma positivo | Cruce bearish + histograma negativo |
| EMA 20/50/200 | 20% | Precio > EMA200, EMA20 > EMA50 | Precio < EMA200, EMA20 < EMA50 |

### Indicadores Secundarios (peso total: 40%)

| Indicador | Peso | Señal Bullish | Señal Bearish |
|-----------|------|---------------|---------------|
| Bollinger Bands | 15% | Precio toca banda inferior | Precio toca banda superior |
| Volumen | 15% | Volumen > promedio 20d en suba | Volumen > promedio 20d en baja |
| ATR (volatilidad) | 10% | ATR bajo = entry seguro | ATR muy alto = riesgo elevado |

### Sistema de Scoring

```
Score total = suma ponderada de todos los indicadores
Rango: -100 (máx bearish) → +100 (máx bullish)

STRONG BUY:   score >= +60
BUY:          score >= +30
NEUTRAL:      score entre -30 y +30
SELL:         score <= -30
STRONG SELL:  score <= -60
```

### Timeframes

- **Scalping**: 15m + 1h
- **Swing trading**: 4h + 1d (recomendado para este bot)
- **Position**: 1d + 1w

Siempre analizar en al menos 2 timeframes. Si 4h dice BUY y 1d dice SELL → NEUTRAL.

### Implementación Python

```python
import pandas as pd
import ta  # pip install ta

def calculate_rsi(close, period=14):
    return ta.momentum.RSIIndicator(close, window=period).rsi()

def calculate_macd(close):
    macd = ta.trend.MACD(close)
    return macd.macd(), macd.macd_signal(), macd.macd_diff()

def calculate_bollinger(close, period=20):
    bb = ta.volatility.BollingerBands(close, window=period)
    return bb.bollinger_hband(), bb.bollinger_lband(), bb.bollinger_mavg()

def calculate_ema(close, periods=[20, 50, 200]):
    return {p: ta.trend.EMAIndicator(close, window=p).ema_indicator() for p in periods}

def score_signal(rsi, macd_hist, price, ema200, bb_lower, bb_upper, volume, avg_volume):
    score = 0
    
    # RSI (20%)
    if rsi < 30: score += 20
    elif rsi < 45: score += 10
    elif rsi > 70: score -= 20
    elif rsi > 55: score -= 10
    
    # MACD (20%)
    if macd_hist > 0: score += 20
    else: score -= 20
    
    # EMA200 (20%)
    if price > ema200: score += 20
    else: score -= 20
    
    # Bollinger (15%)
    if price <= bb_lower: score += 15
    elif price >= bb_upper: score -= 15
    
    # Volumen (15%)
    if volume > avg_volume * 1.5: score += 15
    elif volume < avg_volume * 0.5: score -= 5
    
    return max(-100, min(100, score))
```

### Reglas de Entrada

1. **Nunca entrar** si ATR > 5% del precio (demasiada volatilidad)
2. **Confirmar** con al menos 3 indicadores alineados
3. **Stop loss** = precio entry - (1.5 × ATR)
4. **Take profit** = precio entry + (2.5 × ATR) mínimo

### Análisis Fundamental (bonus)

Incluir en scoring si datos disponibles:
- Market cap rank (top 20 = +5pts)
- Volumen 24h / Market cap > 0.1 = liquidez OK
- Dominancia BTC: si sube → altcoins en riesgo
- Fear & Greed Index < 25 = oportunidad histórica
