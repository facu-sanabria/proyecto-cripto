---
name: excel-dashboard
description: Usar cuando el usuario pregunta sobre la salida Excel del bot, formateo de hojas, openpyxl, conditional formatting, o cómo generar/actualizar el archivo crypto_signals.xlsx.
---

# Excel Real-Time Dashboard — Crypto

## Stack

```
openpyxl     → leer/escribir .xlsx, conditional formatting, cell styles
pandas       → manipulación de datos antes de escribir
schedule     → refresh automático cada N segundos/minutos
```

## Estructura del Excel

```
Sheet 1: "Dashboard"     → resumen top picks, semáforo visual
Sheet 2: "Análisis TA"   → todos los indicadores por crypto
Sheet 3: "Historial"     → log de señales con timestamp
Sheet 4: "Config"        → parámetros ajustables por usuario
```

## Patrón Base — Escritura con openpyxl

```python
from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.formatting.rule import ColorScaleRule, CellIsRule
from openpyxl.utils import get_column_letter
from datetime import datetime
import os

EXCEL_PATH = "crypto_signals.xlsx"

def open_or_create():
    if os.path.exists(EXCEL_PATH):
        return load_workbook(EXCEL_PATH)
    wb = Workbook()
    # setup sheets...
    wb.save(EXCEL_PATH)
    return wb
```

## Semáforo Visual — Conditional Formatting

```python
def apply_signal_formatting(ws, signal_col, data_rows):
    col_letter = get_column_letter(signal_col)
    cell_range = f"{col_letter}2:{col_letter}{data_rows}"
    
    colors = {
        "STRONG BUY":  "00B050",
        "BUY":         "92D050",
        "NEUTRAL":     "FFFF00",
        "SELL":        "FFC000",
        "STRONG SELL": "FF0000",
    }
    for signal, color in colors.items():
        ws.conditional_formatting.add(
            cell_range,
            CellIsRule(operator='equal', formula=[f'"{signal}"'],
                       fill=PatternFill(start_color=color, end_color=color, fill_type="solid"))
        )
```

## Patrón de Actualización

```python
import schedule, time

def update_excel(data: list[dict]):
    wb = open_or_create()
    ws = wb["Dashboard"]
    # Limpiar filas de datos (preservar headers row 1)
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row: cell.value = None
    # Escribir nuevos datos
    for i, row_data in enumerate(data, start=2):
        ws.cell(row=i, column=1, value=row_data["symbol"])
        # ...
    wb.save(EXCEL_PATH)

schedule.every(5).minutes.do(lambda: update_excel(fetch_and_analyze()))
update_excel(fetch_and_analyze())  # primera ejecución inmediata
while True:
    schedule.run_pending()
    time.sleep(1)
```

## Notas Importantes

- Excel NO puede estar abierto con edición exclusiva cuando el bot escribe
- Usar `load_workbook(EXCEL_PATH, keep_vba=False)` para archivos existentes
- Para auto-refresh mientras Excel está abierto: usar `xlwings` (requiere Excel instalado)
- Alternativa web más moderna: `streamlit`
