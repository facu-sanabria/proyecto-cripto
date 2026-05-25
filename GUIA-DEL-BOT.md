# 🤖 Guía Completa del Bot de Análisis Cripto

> **Para quién es esta guía:** Para alguien que quiere entender cómo funciona el bot sin necesidad de ser programador. Explicamos cada pieza del rompecabezas con analogías simples.

---

## ¿Qué hace este bot?

Hay **dos modos** de uso:

### Modo 1: Live Dashboard (Scalping — tiempo real)
```
python live_dashboard.py
```
Un dashboard en la terminal que se actualiza **cada 3 segundos**. Ideal para trading de corto plazo (minutos). Muestra qué comprar ahora, con precio exacto de entrada, stop loss y take profit.

### Modo 2: Excel Bot (Swing Trading — cada 5 minutos)
```
python main.py
```
Genera un archivo Excel (`crypto_signals.xlsx`) que se actualiza cada 5 minutos. Ideal para tendencias de horas o días.

---

## La arquitectura: cómo está organizado el código

Pensá el bot como una empresa pequeña con empleados especializados:

```
                        ┌─────────────────────────────────────┐
                        │         live_dashboard.py           │
                        │   🎬 El Director + Pantalla         │
                        │   Coordina threads, muestra UI      │
                        └────────────┬────────────────────────┘
                                     │
               ┌─────────────────────┼──────────────────────┐
               ▼                     ▼                       ▼
    ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐
    │   fetcher.py     │  │   scalper.py     │  │   excel_writer.py    │
    │                  │  │                  │  │                      │
    │ 📡 El Periodista │  │ 📊 El Analista   │  │ 🎨 El Diseñador      │
    │                  │  │ de Scalping      │  │ (para modo Excel)    │
    │ Va a Binance y   │  │                  │  │                      │
    │ trae datos de    │  │ StochRSI, VWAP,  │  │ Genera Excel con     │
    │ precios (3s)     │  │ EMA crossover,   │  │ colores y semáforo   │
    │ y velas (60s)    │  │ BB Squeeze       │  │                      │
    └──────────────────┘  └──────────────────┘  └──────────────────────┘
               │
    ┌──────────────────┐    ┌──────────────────┐
    │   analyzer.py    │    │    config.py      │
    │ Indicadores base │    │ ⚙️ Configuración  │
    │ (RSI, EMA, MACD, │    │ Lista de cryptos  │
    │  Bollinger, ATR) │    │ Timeframe, etc.   │
    └──────────────────┘    └──────────────────┘
```

### Los dos threads del Live Dashboard

El Live Dashboard usa dos hilos de ejecución en paralelo:

```
Thread 1 — price_updater (cada 3 segundos)
    └── Llama a Binance /ticker/price
    └── Obtiene precios de TODAS las cryptos en 1 sola llamada
    └── Actualiza el estado compartido
    └── Calcula flecha ▲ ▼ comparando con precio anterior

Thread 2 — indicator_updater (cada 60 segundos)
    └── Descarga velas de 5m y 15m para cada crypto
    └── Calcula StochRSI, EMA crossover, MACD, VWAP, Volumen
    └── Genera señal (COMPRAR / ESPERAR / VENDER)
    └── Calcula Entry, Stop Loss, Take Profit

Main thread — display
    └── Lee el estado compartido cada 3 segundos
    └── Dibuja la tabla y el panel con Rich
    └── Actualiza la pantalla
```

---

## Módulo por módulo

### 📁 `config.py` — La configuración

El único archivo que necesitás tocar para personalizar.

```python
CRYPTOS = [
    {"symbol": "BTCUSDT", "name": "Bitcoin"},
    # agregar más acá...
]
TIMEFRAME = "4h"          # para el bot Excel
REFRESH_MINUTES = 5       # cada cuánto actualiza el Excel
```

---

### 📡 `fetcher.py` — El Periodista

Habla con la API pública de Binance (sin necesidad de cuenta).

**¿Qué son los datos OHLCV?**
Para cada período de tiempo, recibe:

| Letra | Español  | Qué significa                    |
|-------|----------|----------------------------------|
| O     | Apertura | Precio al inicio del período     |
| H     | Máximo   | Precio más alto del período      |
| L     | Mínimo   | Precio más bajo del período      |
| C     | Cierre   | Precio al final del período      |
| V     | Volumen  | Cuánto se negoció ese período    |

Estos son las "velas japonesas" que ves en todos los gráficos.

---

### 📊 `scalper.py` — El Analista de Scalping

Este módulo es el cerebro del Live Dashboard. Usa indicadores optimizados para **trading de corto plazo** (minutos a horas), no para inversión a largo plazo.

#### Indicador 1: Stochastic RSI (el más importante para scalping)

**Qué mide:** Cuándo el precio está "demasiado arriba" o "demasiado abajo" en relación a su rango reciente. Es más sensible que el RSI normal.

**Rango:** 0 a 100

```
   0 ──────────────────────────────────────── 100
        │                        │
       20                        80
   SOBREVENDIDO              SOBRECOMPRADO
   K < 20 = posible         K > 80 = posible
   rebote ↑                 caída ↓

   Lo mejor: K estaba bajo 20 y ahora SUBE → señal fuerte de compra
```

**En el bot:** aparece como "StochRSI K" en la tabla. Si es verde (< 20), es zona de compra.

#### Indicador 2: EMA Crossover (EMA5 vs EMA13)

**Qué mide:** Cuándo la tendencia de corto plazo cambia de dirección.

**Analogía:** Son como dos autos en una carretera. Cuando el auto rápido (EMA5) adelanta al auto lento (EMA13), la tendencia cambió hacia arriba.

```
Precio │
       │   ────── EMA5 (rápida)
       │         ╲
       │          ╲──── EMA13 (lenta)
       │               ╲
       │                ↑ aquí EMA5 "cruza" EMA13
       └──────────────────────────────────── tiempo
                        ↑
                  Señal de compra
              "EMA5 cruza EMA13 al alza [AHORA]"
```

#### Indicador 3: MACD en 15 minutos (filtro de tendencia)

**Qué mide:** La dirección general de la tendencia en un timeframe mayor (15m).

Usamos el MACD de 15m como **filtro**: si la señal de 5m dice COMPRAR pero el MACD de 15m es bajista, la señal es más débil.

#### Indicador 4: VWAP (Volume Weighted Average Price)

**Qué mide:** El precio promedio del día ponderado por volumen. Es la referencia que usan los grandes traders institucionales.

- Precio **sobre** VWAP → mercado alcista intraday → bueno para comprar
- Precio **bajo** VWAP → mercado bajista intraday → cuidado

#### Indicador 5: Volumen relativo

**Qué mide:** Si el volumen actual es mayor o menor al promedio de las últimas 20 velas.

- `VOL 2.3x` → se está operando 2.3 veces más que lo normal → movimiento fuerte inminente
- El volumen alto **confirma** la señal. Sin volumen, la señal es débil.

#### Indicador 6: Bollinger Band Squeeze (⚡)

**Qué mide:** Cuando las bandas de Bollinger se "aprietan" (se acercan entre sí), significa que el precio lleva rato sin moverse mucho. Cuando eso termina, suele haber un movimiento brusco.

- `⚡ SI` = squeeze activo → ojo, movimiento fuerte próximo
- No dice para qué lado, pero avisa que algo viene

---

### El Sistema de Scoring para Scalping

```
┌──────────────────────────────────────────────────────┐
│           SCORING DE SCALPING (5m/15m)               │
├───────────────────────┬────────┬─────────────────────┤
│ Indicador             │ Puntos │ Condición           │
├───────────────────────┼────────┼─────────────────────┤
│ Stochastic RSI        │ ±30    │ < 20 ó > 80 + giro  │
│ EMA5 / EMA13 crossover│ ±25    │ Cruce en este candle│
│ MACD (15m)            │ ±20    │ Dirección y momentum│
│ Volumen relativo      │ ±15    │ > 1.5x o > 2.5x     │
│ VWAP                  │ ±10    │ Precio sobre/bajo   │
│ BB Squeeze            │ +10    │ Bonus si squeeze     │
├───────────────────────┼────────┼─────────────────────┤
│ TOTAL                 │ ±100   │                      │
└───────────────────────┴────────┴─────────────────────┘

Score +55 a +100  →  COMPRAR       🟢
Score +28 a +54   →  POSIBLE COMPRA 🟩
Score -27 a +27   →  ESPERAR       🟡
Score -54 a -28   →  POSIBLE VENTA 🟠
Score -100 a -55  →  VENDER/EVITAR 🔴
```

---

### Cómo leer el dashboard en vivo

```
 PAR     PRECIO           DIR  24H %    StochRSI K  VWAP    VOL x  SQUEEZE  SCORE  SEÑAL
──────────────────────────────────────────────────────────────────────────────────────────
 BNB     $661.140         ▲    +3.2%       18       ↑ SI    2.3x   ⚡ SI    +72    COMPRAR
```

| Columna | Qué dice |
|---------|----------|
| `DIR ▲▼` | Si el precio subió o bajó en los últimos 3 segundos |
| `24H %` | Variación respecto a ayer a esta hora |
| `StochRSI K` | Verde (< 20) = zona de compra, Rojo (> 80) = zona de venta |
| `VWAP ↑SI` | El precio está sobre el promedio institucional del día |
| `VOL 2.3x` | El volumen es 2.3 veces el promedio → movimiento real |
| `⚡ SI` | Hay un squeeze de Bollinger → movimiento fuerte próximo |
| `SCORE +72` | 72/100 de señal alcista |
| `SEÑAL` | La recomendación final |

---

### Cómo leer el panel de señal activa

```
═══ SEÑAL ACTIVA — BNB/USDT ══════════════════════════════════════
  COMPRAR: BNB/USDT    Score: +72/100   Confianza: 85%

  ENTRADA:       $661.14  ← comprás a este precio ahora
  STOP LOSS:     $654.82  (-0.95%) ← si cae acá, salís (límite de pérdida)
  TAKE PROFIT 1: $670.60  (+1.43%) ← vendés el 50% acá (asegurás ganancia)
  TAKE PROFIT 2: $677.71  (+2.50%) ← vendés el resto acá

  R/R: 1.5x  |  Tiempo estimado: 5-30 min
═══════════════════════════════════════════════════════════════════
```

**¿Qué es el R/R (Risk/Reward)?**
Cuánto ganás por cada peso que arriesgás.
- R/R 1.5x = si arriesgás $100, podés ganar $150
- Siempre buscar R/R > 1.3 para que valga la pena operar

**¿Qué hacer con los dos Take Profits?**
1. Cuando el precio llega al TP1 → vendés la mitad de tu posición (asegurás ganancia mínima)
2. Movés el Stop Loss al precio de entrada (ya no podés perder)
3. Esperás a que llegue al TP2 con la otra mitad

---

## Cómo instalar y usar

### Instalación (una sola vez)
```bash
# En C:\proyecto-cripto
pip install requests pandas numpy openpyxl schedule python-dotenv rich
```

### Modo Live Dashboard (scalping)
```powershell
cd C:\proyecto-cripto
$env:PYTHONIOENCODING="utf-8"
python live_dashboard.py
```
- Pantalla completa, actualiza cada 3 segundos
- Tarda ~45 segundos en cargar la primera vez
- `Ctrl+C` para salir

### Modo Excel Bot (swing trading)
```powershell
cd C:\proyecto-cripto
$env:PYTHONIOENCODING="utf-8"
python main.py
```
- Genera `crypto_signals.xlsx`, actualiza cada 5 minutos
- Abrí el Excel mientras el bot corre

---

## Roadmap: lo que viene después

### ✅ Fase 1 (completada): Bot de análisis
- Live dashboard en tiempo real
- Señales de scalping con StochRSI, EMA, MACD, VWAP
- Bot Excel para swing trading
- Parámetros exactos: entry, stop loss, take profit

### 🔜 Fase 2: Backtesting (simulación histórica)

Responde la pregunta: *"Si hubiera seguido las señales del bot en los últimos 6 meses, ¿cuánto habría ganado o perdido?"*

```
Proceso:
  1. Descargar 6 meses de velas de 5m
  2. Simular cada señal COMPRAR/VENDER en el pasado
  3. Calcular ganancia/pérdida de cada operación
  4. Generar reporte: % de operaciones ganadoras, ganancia total,
     máximo drawdown (mayor caída), mejor y peor operación
```

Esto es **fundamental** antes de arriesgar dinero real. Valida si la estrategia funciona.

### 🔜 Fase 3: Notificaciones (Telegram)

Cuando el bot detecta COMPRAR con score ≥ 55, te manda un mensaje al celular al instante.

```
🤖 BOT CRIPTO — SEÑAL

🟢 COMPRAR: BNB/USDT
Score: +72 | Confianza: 85%

Entrada:    $661.14
Stop Loss:  $654.82 (-0.95%)
TP1:        $670.60 (+1.43%)
TP2:        $677.71 (+2.50%)

StochRSI giró en sobreventa | EMA5 cruzó EMA13 | Vol 2.3x
```

- Gratis con Telegram Bot API
- Funciona en cualquier celular
- ~20 líneas de código adicionales

### 🔜 Fase 4: Trading semi-automático

El bot detecta señal → te manda notificación con botón → vos apretás "COMPRAR" → se ejecuta en Binance.

```
Requiere:
  - API Key de Binance (solo permisos de trading, NUNCA de retiro)
  - librería ccxt para ejecutar órdenes
  - Telegram bot con botones inline
```

### 🔜 Fase 5: Trading automático

El bot opera solo. Solo recomendado **después** de que el backtesting demuestre resultados positivos consistentes.

```
Orden lógico recomendado:
  Backtesting → Notificaciones → Semi-auto → Auto-completo
```

---

## Conceptos clave de trading

| Concepto | Qué es | En el bot |
|----------|--------|-----------|
| **Scalping** | Trading de minutos buscando pequeñas ganancias | Live Dashboard (5m/15m) |
| **Swing Trading** | Trading de horas/días buscando tendencias | Bot Excel (4h) |
| **Stop Loss** | Precio al que cerrás si el mercado va en tu contra | Precio - 1×ATR |
| **Take Profit** | Precio objetivo de ganancia | TP1: 1.5×SL, TP2: 2.5×SL |
| **Risk/Reward** | Cuánto ganás vs. cuánto arriesgás | R/R > 1.3 = aceptable |
| **VWAP** | Precio promedio ponderado por volumen (referencia institucional) | Columna VWAP |
| **Squeeze** | Bandas de Bollinger muy juntas → movimiento inminente | Columna ⚡ |
| **Timeframe** | Duración de cada vela | 5m (scalping), 4h (swing) |
| **Volumen** | Cuánto se negoció | Confirma señales |

---

## ⚠️ Aviso importante

Este bot es una **herramienta de análisis educativo**. Los indicadores técnicos no son perfectos — pueden generar señales falsas, especialmente en mercados muy volátiles o sin tendencia clara.

**Reglas básicas para no perder todo:**
1. Nunca invertir más del 1-2% del capital en una sola operación
2. Siempre respetar el Stop Loss (nunca moverlo para abajo esperando que recupere)
3. Validar la estrategia con backtesting antes de usar dinero real
4. El bot no garantiza ganancias — el mercado cripto es impredecible

> *"El análisis técnico dice qué es probable, no qué es seguro."*

---

*Documentación del proyecto `C:\proyecto-cripto`*
*Última actualización: Mayo 2026*
