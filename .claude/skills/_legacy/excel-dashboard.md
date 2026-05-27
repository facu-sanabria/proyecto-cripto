# Excel Real-Time Dashboard — Crypto

## Trigger
Auto-activate when: user asks about Excel output, dashboard, spreadsheet, openpyxl, xlsxwriter, real-time update, formatting financial data, conditional formatting.

## Stack Recomendado

```
openpyxl     → leer/escribir .xlsx, conditional formatting, cell styles
pandas       → manipulación de datos antes de escribir
schedule     → refresh automático cada N segundos/minutos
```

```bash
pip install openpyxl pandas schedule
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
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.formatting.rule import ColorScaleRule, CellIsRule
from openpyxl.utils import get_column_letter
from datetime import datetime
import os

EXCEL_PATH = "crypto_dashboard.xlsx"

def create_workbook():
    wb = Workbook()
    
    # Dashboard sheet
    ws_dash = wb.active
    ws_dash.title = "Dashboard"
    
    # Análisis sheet
    ws_ta = wb.create_sheet("Análisis TA")
    
    # Historial sheet
    ws_hist = wb.create_sheet("Historial")
    
    setup_dashboard_headers(ws_dash)
    setup_ta_headers(ws_ta)
    setup_historial_headers(ws_hist)
    
    wb.save(EXCEL_PATH)
    return wb

def open_or_create():
    if os.path.exists(EXCEL_PATH):
        return load_workbook(EXCEL_PATH)
    return create_workbook()
```

## Headers y Estilos

```python
HEADER_FILL = PatternFill(start_color="1F3864", end_color="1F3864", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)

def style_header_row(ws, row, cols):
    for col in range(1, cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

def setup_dashboard_headers(ws):
    headers = ["Crypto", "Precio USD", "Cambio 24h%", "Score TA", "Señal", 
               "RSI", "MACD", "Tendencia EMA", "Volumen 24h", "Última actualización"]
    
    for i, h in enumerate(headers, 1):
        ws.cell(row=1, column=i, value=h)
    
    style_header_row(ws, 1, len(headers))
    
    # Anchos de columna
    col_widths = [10, 14, 14, 10, 12, 8, 10, 16, 16, 22]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
```

## Semáforo Visual — Conditional Formatting

```python
def apply_signal_formatting(ws, signal_col, data_rows):
    """Colorea columna Señal según valor."""
    
    # STRONG BUY → verde oscuro
    ws.conditional_formatting.add(
        f"{get_column_letter(signal_col)}2:{get_column_letter(signal_col)}{data_rows}",
        CellIsRule(operator='equal', formula=['"STRONG BUY"'],
                   fill=PatternFill(start_color="00B050", end_color="00B050", fill_type="solid"))
    )
    # BUY → verde claro
    ws.conditional_formatting.add(
        f"{get_column_letter(signal_col)}2:{get_column_letter(signal_col)}{data_rows}",
        CellIsRule(operator='equal', formula=['"BUY"'],
                   fill=PatternFill(start_color="92D050", end_color="92D050", fill_type="solid"))
    )
    # NEUTRAL → amarillo
    ws.conditional_formatting.add(
        f"{get_column_letter(signal_col)}2:{get_column_letter(signal_col)}{data_rows}",
        CellIsRule(operator='equal', formula=['"NEUTRAL"'],
                   fill=PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid"))
    )
    # SELL → naranja
    ws.conditional_formatting.add(
        f"{get_column_letter(signal_col)}2:{get_column_letter(signal_col)}{data_rows}",
        CellIsRule(operator='equal', formula=['"SELL"'],
                   fill=PatternFill(start_color="FFC000", end_color="FFC000", fill_type="solid"))
    )
    # STRONG SELL → rojo
    ws.conditional_formatting.add(
        f"{get_column_letter(signal_col)}2:{get_column_letter(signal_col)}{data_rows}",
        CellIsRule(operator='equal', formula=['"STRONG SELL"'],
                   fill=PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid"))
    )

def apply_score_colorscale(ws, score_col, data_rows):
    """Gradiente rojo→amarillo→verde en columna Score."""
    ws.conditional_formatting.add(
        f"{get_column_letter(score_col)}2:{get_column_letter(score_col)}{data_rows}",
        ColorScaleRule(
            start_type='num', start_value=-100, start_color='FF0000',
            mid_type='num', mid_value=0, mid_color='FFFF00',
            end_type='num', end_value=100, end_color='00B050'
        )
    )
```

## Patrón de Actualización en Tiempo Real

```python
import schedule
import time
import threading

def update_excel(data: list[dict]):
    """data = lista de dicts con info por crypto."""
    wb = open_or_create()
    ws = wb["Dashboard"]
    
    # Limpiar datos viejos (preservar headers)
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.value = None
    
    # Escribir nuevos datos
    for i, crypto in enumerate(data, start=2):
        ws.cell(row=i, column=1, value=crypto["symbol"])
        ws.cell(row=i, column=2, value=crypto["price"])
        ws.cell(row=i, column=3, value=crypto["change_24h"])
        ws.cell(row=i, column=4, value=crypto["score"])
        ws.cell(row=i, column=5, value=crypto["signal"])
        ws.cell(row=i, column=6, value=crypto["rsi"])
        ws.cell(row=i, column=7, value=crypto["macd_signal"])
        ws.cell(row=i, column=8, value=crypto["ema_trend"])
        ws.cell(row=i, column=9, value=crypto["volume_24h"])
        ws.cell(row=i, column=10, value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    
    apply_signal_formatting(ws, 5, len(data) + 1)
    apply_score_colorscale(ws, 4, len(data) + 1)
    
    wb.save(EXCEL_PATH)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Excel actualizado — {len(data)} cryptos")

def start_scheduler(fetch_and_analyze_fn, interval_minutes=5):
    schedule.every(interval_minutes).minutes.do(
        lambda: update_excel(fetch_and_analyze_fn())
    )
    
    # Primera ejecución inmediata
    update_excel(fetch_and_analyze_fn())
    
    while True:
        schedule.run_pending()
        time.sleep(1)
```

## Notas Importantes

- Excel NO puede estar abierto con edición exclusiva cuando el bot escribe → avisar al usuario
- Usar `load_workbook(EXCEL_PATH, keep_vba=False)` para archivos existentes
- Si se necesita que Excel se refresque solo mientras está abierto → usar `xlwings` (requiere Excel instalado)
- Para dashboards más avanzados considerar `streamlit` como alternativa web
