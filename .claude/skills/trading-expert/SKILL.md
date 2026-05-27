---
name: trading-expert
description: Usar cuando el usuario pregunta sobre estrategia de trading, análisis técnico (RSI, MACD, EMA, ATR), gestión de riesgo, stop-loss, take-profit, o interpretación de señales de este bot.
---

# Trading Expert — Crypto Technical Analysis

## Principios fundamentales

### La regla más importante
**Nunca comprar contra la tendencia principal.** Un mercado bajista castiga todas las señales de compra.
El 80% de las pérdidas del bot provienen de comprar dips en downtrends.

### Jerarquía de señales (de más a menos importante)
1. Tendencia macro (EMA200, estructura de mercado)
2. Momentum (MACD, cambio de dirección)
3. Nivel de precio (RSI, Bollinger)
4. Confirmación (volumen, ATR)

---

## Condiciones de mercado

### Mercado alcista (permitir compras)
- Precio > EMA200
- EMA50 > EMA200
- Estructura: higher highs + higher lows

### Mercado bajista (BLOQUEAR compras)
- Precio < EMA200 Y EMA50 < EMA200 → NO entrar bajo ninguna señal
- En downtrend, cada rebote es una trampa alcista
- Excepción: RSI < 20 con divergencia alcista (extremo absoluto)

### Mercado lateral / consolidación
- EMA20 ≈ EMA50 ≈ EMA200 (todas juntas)
- Bollinger Bands angostas (squeeze)
- Reducir tamaño de posición, esperar breakout

---

## Señales de entrada de alta calidad

### Setup ideal (todos deben cumplirse)
1. ✅ Precio > EMA50 > EMA200 (tendencia alcista confirmada)
2. ✅ MACD histograma cruza de negativo a positivo (momentum shift)
3. ✅ RSI 35-55 y subiendo (no sobrecomprado, con espacio para subir)
4. ✅ Precio cerca de EMA20 o banda inferior BB (pullback, no extensión)
5. ✅ Volumen > 1.5x promedio (convicción del movimiento)

### Setup bueno (mínimo 3 de 5)
- Precio > EMA200 (mercado alcista)
- MACD histograma positivo y creciendo
- RSI < 50
- BB% < 0.4 (precio en mitad inferior del canal)
- Volumen confirmando

### Señales a IGNORAR
- MACD positivo pero RSI > 65 → sobreextendido
- RSI oversold pero precio < EMA200 → trampa bajista
- Volumen débil (< 0.8x promedio) → falta convicción
- ATR > 5% → riesgo demasiado alto

---

## MACD — Interpretación correcta

### Lo que importa NO es el nivel, sino el cambio
```
macd_hist[i] vs macd_hist[i-1]
```

| Situación | Señal | Peso |
|-----------|-------|------|
| Cruce de negativo → positivo | FUERTE ALCISTA | +25 |
| Positivo y creciendo | Alcista | +15 |
| Positivo pero decreciendo | Momentum débil | +5 |
| Negativo mejorando (menos negativo) | Posible giro | -5 |
| Negativo y empeorando | Bajista | -20 |

### Divergencias (señales avanzadas)
- **Divergencia alcista**: precio hace lower low, MACD hace higher low → COMPRA fuerte
- **Divergencia bajista**: precio hace higher high, MACD hace lower high → VENTA

---

## RSI — Interpretación correcta

### Lo que importa: momentum Y nivel
```
¿De dónde viene el RSI? ¿Hacia dónde va?
```

| Situación | Señal | Peso |
|-----------|-------|------|
| RSI 30-50 y subiendo (recuperación) | FUERTE | +20 |
| RSI < 30 (oversold) | Alcista | +15 |
| RSI < 45 | Positivo | +10 |
| RSI 50-60 | Neutro | 0 |
| RSI > 60 | Negativo | -10 |
| RSI > 70 (overbought) | FUERTE NEGATIVO | -20 |

### NO comprar cuando:
- RSI > 65 aunque MACD sea positivo
- RSI baja desde >70 (momentum bajando)

---

## EMA — Alineación de tendencia

### Configuración alcista perfecta
```
precio > EMA20 > EMA50 > EMA200
```
Score: +30. La tendencia en todos los plazos coincide.

### Pullback al EMA20 en tendencia alcista
```
EMA50 > EMA200, precio tocó EMA20 y rebotó
```
Esta es la entrada de mejor calidad: comprar el pullback en uptrend.

### Configuración bajista (BLOQUEAR)
```
precio < EMA200 Y EMA50 < EMA200
```
Score máximo: 15 (jamás disparará BUY ni STRONG BUY).

---

## Volumen — Confirmación de movimiento

### Regla básica
Sin volumen, no hay convicción. Un movimiento alcista sin volumen es sospechoso.

| Volume ratio | Acción |
|---|---|
| > 2.0x + señal positiva | Confirmar con +15 |
| 1.5-2.0x + señal positiva | Confirmar con +10 |
| < 0.8x | Penalizar -10 (señal débil) |
| > 2.0x + señal negativa | Penalizar -10 (venta con fuerza) |

---

## Gestión de riesgo

### Stop-Loss y Take-Profit (ÚNICA FUENTE: config.py)
- **SL**: `precio_entrada - SL_ATR_MULT × ATR`  (SL_ATR_MULT = 1.5)
- **TP**: `precio_entrada + TP_ATR_MULT × ATR`  (TP_ATR_MULT = 3.0)
- **R/R**: 2.0 — break-even WR mínimo: 33.3%
- Nunca mover el SL hacia abajo
- Nota: scalper.py (5m) usa SL_MULT=1.0 — timeframe distinto

### Tamaño de posición
- Nunca arriesgar más del 2% del capital total en un trade
- En mercados laterales: reducir tamaño 50%
- En alta volatilidad (ATR > 5%): reducir tamaño 70% o no entrar

### Timeout de posición
- MAX_HOLD_CANDLES = 96 velas (16 días en 4h) → cerrar al mercado
- Si el mercado no se movió: el setup estaba equivocado

---

## Volatilidad (ATR)

| ATR % del precio | Acción |
|---|---|
| < 2% | Normal, ok para entrar |
| 2-5% | Aceptable, reducir tamaño |
| 5-8% | Penalizar fuerte (-15), no entrar con señal débil |
| > 8% | Bloquear entrada (HARD BLOCK), riesgo extremo |

---

## Errores comunes a evitar

1. **Buying the dip in a downtrend** — El mayor error.
2. **FOMO entry** — Entrar después de que el precio ya subió mucho.
3. **Ignorar el volumen** — Un breakout sin volumen falla el 70% de las veces.
4. **Mover el stop-loss** — Si el mercado va contra vos, salir.
5. **Overtrading** — Menos trades de alta calidad > muchos trades mediocres.
6. **Correlación de activos** — BTC baja → todo baja.

---

## Ranking de señales por confiabilidad

| Señal | Confiabilidad | Condición |
|---|---|---|
| Pullback a EMA20 en tendencia perfecta + volumen | ⭐⭐⭐⭐⭐ | Todas las EMAs alineadas |
| MACD cruce 0 + RSI recuperando + sobre EMA200 | ⭐⭐⭐⭐ | Mínimo 2 confirmaciones |
| RSI oversold + BB inferior + sobre EMA200 | ⭐⭐⭐ | Mercado alcista solo |
| Solo MACD positivo | ⭐⭐ | Muy ruidoso solo |
| RSI oversold bajo EMA200 | ⭐ | Trampa bajista frecuente |

---

## Criptos con comportamiento especial

- **BTC**: líder del mercado, sus señales son las más confiables.
- **ETH**: sigue a BTC con más volatilidad.
- **Altcoins (DOT, XRP, ADA, AVAX)**: más volátiles, más falsas señales.
- **MATIC (ahora POL)**: renombrado, actualizar símbolo en config.py.
