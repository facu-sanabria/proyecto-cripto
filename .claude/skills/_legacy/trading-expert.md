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

### Stop-Loss
- Usar ATR para stop dinámico: `precio_entrada - 1.5 × ATR`
- Nunca mover el stop-loss hacia abajo (agravar pérdida)
- Si el mercado cae al SL: aceptar y salir

### Take-Profit
- Target: `precio_entrada + 2.5 × ATR`
- Risk/Reward mínimo aceptable: 1:1.5 (mejor 1:2.5 como tenemos)
- Opcional: salida parcial al 50% en 1.5× ATR, dejar correr el resto

### Tamaño de posición
- Nunca arriesgar más del 2% del capital total en un trade
- En mercados laterales: reducir tamaño 50%
- En alta volatilidad (ATR > 5%): reducir tamaño 70% o no entrar

### Timeout de posición
- Posición sin resolver en 10 días (60 velas × 4h): cerrar al precio de mercado
- Si el mercado no se movió en 10 días: el setup estaba equivocado

---

## Volatilidad (ATR)

| ATR % del precio | Acción |
|---|---|
| < 2% | Normal, ok para entrar |
| 2-5% | Aceptable, reducir tamaño |
| 5-8% | Penalizar fuerte (-15), no entrar con señal débil |
| > 8% | Bloquear entrada (-25), riesgo extremo |

---

## Errores comunes a evitar

1. **Buying the dip in a downtrend** — El mayor error. Esperar siempre confirmación alcista antes de comprar caídas.
2. **FOMO entry** — Entrar después de que el precio ya subió mucho. Mejor perder esa entrada que comprar sobreextendido.
3. **Ignorar el volumen** — Un breakout sin volumen falla el 70% de las veces.
4. **Mover el stop-loss** — Si el mercado va contra vos, salir. No "esperar que vuelva".
5. **Overtrading** — Menos trades de alta calidad > muchos trades mediocres. Win rate 50% con 3:1 R/R >> Win rate 60% con 1:1 R/R.
6. **Correlación de activos** — BTC baja → todo baja. No abrir 5 posiciones simultáneas en altcoins cuando BTC cae.

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

- **BTC**: líder del mercado, sus señales son las más confiables. Si BTC tiene tendencia bajista, las altcoins serán peores.
- **ETH**: sigue a BTC con más volatilidad. Señales confiables en bull market.
- **Altcoins (DOT, XRP, ADA, AVAX)**: más volátiles, más falsas señales. Requieren filtros más estrictos.
- **LTC/ATOM**: históricamente mejores señales técnicas (confirmado en backtest).
- **MATIC (ahora POL)**: renombrado, actualizar símbolo en config.py.
