"""
live_dashboard.py — Dashboard de scalping en tiempo real

Arquitectura de threads:
  Thread 1 (price_updater):      actualiza precios cada 3s  (1 llamada API)
  Thread 2 (indicator_updater):  recalcula indicadores cada 60s
  Main:                          refresca la pantalla cada 3s con Rich Live

Cómo correr:
  python live_dashboard.py
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

import time
import threading
import requests
from datetime import datetime

from rich.live    import Live
from rich.table   import Table
from rich.panel   import Panel
from rich.console import Console, Group
from rich.text    import Text
from rich.align   import Align
from rich         import box

from config  import CRYPTOS
from fetcher import get_ohlcv
from scalper import analyze_scalp, fmt_price

# ─── Configuración ─────────────────────────────────────────────────────────────
BINANCE_BASE       = "https://api.binance.com/api/v3"
PRICE_INTERVAL_SEC = 3     # actualizar precios cada N segundos
INDICATOR_INTERVAL = 60    # recalcular indicadores cada N segundos
TF_FAST            = "5m"  # timeframe señales rápidas
TF_SLOW            = "15m" # timeframe confirmación
CANDLES_FAST       = 100
CANDLES_SLOW       = 60

# ─── Estado compartido (thread-safe) ──────────────────────────────────────────
_lock  = threading.Lock()
_state = {
    "prices":      {},    # symbol → precio actual float
    "prev_prices": {},    # symbol → precio anterior (para flecha)
    "signals":     {},    # symbol → dict resultado analyze_scalp
    "change_24h":  {},    # symbol → cambio % 24h
    "ts_prices":   None,  # timestamp último update de precios
    "ts_signals":  None,  # timestamp último update de indicadores
    "loading":     True,
}


# ─── Funciones de fetching rápido ──────────────────────────────────────────────

def _get_all_prices() -> dict:
    """1 llamada → todos los precios. Weight: 2."""
    try:
        r = requests.get(f"{BINANCE_BASE}/ticker/price", timeout=5)
        r.raise_for_status()
        return {t["symbol"]: float(t["price"]) for t in r.json()}
    except Exception:
        return {}


def _get_all_change_24h() -> dict:
    """1 llamada → cambios 24h de todos los símbolos. Weight: 40."""
    try:
        r = requests.get(f"{BINANCE_BASE}/ticker/24hr", timeout=8)
        r.raise_for_status()
        return {t["symbol"]: float(t["priceChangePercent"]) for t in r.json()}
    except Exception:
        return {}


# ─── Threads ──────────────────────────────────────────────────────────────────

def price_updater():
    """Thread 1: actualiza precios cada PRICE_INTERVAL_SEC segundos."""
    while True:
        prices = _get_all_prices()
        if prices:
            with _lock:
                for c in CRYPTOS:
                    sym = c["symbol"]
                    if sym in prices:
                        old = _state["prices"].get(sym, prices[sym])
                        _state["prev_prices"][sym] = old
                        _state["prices"][sym]      = prices[sym]
                _state["ts_prices"] = datetime.now()
        time.sleep(PRICE_INTERVAL_SEC)


def indicator_updater():
    """Thread 2: descarga OHLCV y recalcula señales cada INDICATOR_INTERVAL seg."""
    while True:
        changes = _get_all_change_24h()
        new_sigs = {}

        for c in CRYPTOS:
            sym = c["symbol"]
            try:
                df5  = get_ohlcv(sym, TF_FAST,  CANDLES_FAST)
                df15 = get_ohlcv(sym, TF_SLOW,  CANDLES_SLOW)
                if df5 is not None and df15 is not None and len(df5) >= 30:
                    sig = analyze_scalp(df5, df15)
                    sig["name"]      = c["name"]
                    sig["change_24h"]= changes.get(sym, 0.0)
                    new_sigs[sym]    = sig
            except Exception:
                pass
            time.sleep(0.15)

        with _lock:
            _state["signals"].update(new_sigs)
            _state["change_24h"].update(changes)
            _state["ts_signals"] = datetime.now()
            _state["loading"]    = False

        time.sleep(INDICATOR_INTERVAL)


# ─── Construcción del display ──────────────────────────────────────────────────

SIGNAL_STYLE = {
    "COMPRAR":       ("bold white on green",  "COMPRAR"),
    "POSIBLE COMPRA":("bold green",           "POSIBLE COMPRA"),
    "ESPERAR":       ("bold yellow",          "ESPERAR"),
    "POSIBLE VENTA": ("bold dark_orange",     "POSIBLE VENTA"),
    "VENDER/EVITAR": ("bold white on red",    "VENDER"),
}


def _fmt_signal(sig: str) -> Text:
    style, label = SIGNAL_STYLE.get(sig, ("white", sig))
    return Text(f" {label} ", style=style)


def _fmt_score(score: int) -> Text:
    if score >= 55:   return Text(f"{score:+d}", style="bold green")
    if score >= 25:   return Text(f"{score:+d}", style="green")
    if score <= -55:  return Text(f"{score:+d}", style="bold red")
    if score <= -25:  return Text(f"{score:+d}", style="red")
    return Text(f"{score:+d}", style="yellow")


def build_price_table() -> Table:
    """Tabla principal con precios en tiempo real y señales."""
    with _lock:
        sigs    = dict(_state["signals"])
        prices  = dict(_state["prices"])
        prevs   = dict(_state["prev_prices"])

    table = Table(
        box=box.SIMPLE_HEAVY,
        header_style="bold white on navy_blue",
        border_style="steel_blue1",
        show_edge=True,
        expand=True,
        padding=(0, 1),
    )

    table.add_column("PAR",         width=8,  justify="left",   style="bold cyan")
    table.add_column("PRECIO",      width=16, justify="right")
    table.add_column("DIR",         width=3,  justify="center")
    table.add_column("24H %",       width=9,  justify="right")
    table.add_column("StochRSI K",  width=11, justify="center")
    table.add_column("VWAP",        width=7,  justify="center")
    table.add_column("VOL x",       width=6,  justify="center")
    table.add_column("SQUEEZE",     width=8,  justify="center")
    table.add_column("SCORE",       width=7,  justify="center")
    table.add_column("SEÑAL",       width=16, justify="center")

    # Ordenar: señales de compra primero, venta al final
    sym_list = [c["symbol"] for c in CRYPTOS]
    sym_list.sort(key=lambda s: sigs.get(s, {}).get("score", 0), reverse=True)

    for sym in sym_list:
        sig   = sigs.get(sym, {})
        price = prices.get(sym, sig.get("price", 0) if sig else 0)
        prev  = prevs.get(sym, price)
        name  = sym.replace("USDT", "")

        # Precio y flecha
        if price > prev:
            p_str = Text(fmt_price(price), style="bold green")
            arrow = Text("▲", style="bold green")
        elif price < prev:
            p_str = Text(fmt_price(price), style="bold red")
            arrow = Text("▼", style="bold red")
        else:
            p_str = Text(fmt_price(price), style="white")
            arrow = Text("·", style="dim")

        # 24h
        ch = sig.get("change_24h", 0) if sig else 0
        ch_txt = Text(f"{ch:+.2f}%", style="green" if ch >= 0 else "red")

        if not sig:
            table.add_row(name, p_str, arrow, ch_txt,
                          Text("...", style="dim"), Text("...", style="dim"),
                          Text("...", style="dim"), Text("...", style="dim"),
                          Text("...", style="dim"), Text("Calculando...", style="dim"))
            continue

        # StochRSI K
        k = sig["stoch_k"]
        if k < 20:   k_txt = Text(f"{k:.0f}", style="bold green")
        elif k > 80: k_txt = Text(f"{k:.0f}", style="bold red")
        elif k < 35: k_txt = Text(f"{k:.0f}", style="green")
        elif k > 65: k_txt = Text(f"{k:.0f}", style="red")
        else:        k_txt = Text(f"{k:.0f}", style="white")

        # VWAP
        vwap_txt = Text("↑ SI",  style="bold green") if sig["above_vwap"] \
              else Text("↓ NO", style="bold red")

        # Volumen
        vr = sig["vol_ratio"]
        if vr > 2.5:   vr_txt = Text(f"{vr:.1f}x", style="bold yellow")
        elif vr > 1.5: vr_txt = Text(f"{vr:.1f}x", style="green")
        else:          vr_txt = Text(f"{vr:.1f}x", style="dim white")

        # BB Squeeze
        sq_txt = Text("⚡ SI", style="bold magenta") if sig.get("bb_squeeze") \
            else Text("no",   style="dim")

        table.add_row(
            name, p_str, arrow, ch_txt, k_txt,
            vwap_txt, vr_txt, sq_txt,
            _fmt_score(sig["score"]),
            _fmt_signal(sig["signal"]),
        )

    return table


def build_signal_panel() -> Panel:
    """Panel inferior con instrucciones concretas para la mejor señal."""
    with _lock:
        sigs   = dict(_state["signals"])
        prices = dict(_state["prices"])

    # Encontrar señal más fuerte con score ≥ 28
    best_sym   = None
    best_score = 0
    for sym, sig in sigs.items():
        sc = sig.get("score", 0)
        if abs(sc) > abs(best_score) and abs(sc) >= 28:
            best_score = sc
            best_sym   = sym

    if not best_sym:
        return Panel(
            Align.center("[bold yellow]Sin señales activas — Esperando configuración favorable...[/]", vertical="middle"),
            title="[bold] SEÑAL ACTIVA [/]",
            border_style="yellow",
            height=8,
        )

    sig    = sigs[best_sym]
    name   = best_sym.replace("USDT", "")
    signal = sig["signal"]
    price  = prices.get(best_sym, sig["entry"])
    is_buy = best_score > 0
    color  = "green" if is_buy else "red"
    conf   = sig["confidence"]

    sl_pct  = sig["sl_pct"]
    tp1_pct = sig["tp1_pct"]
    tp2_pct = sig["tp2_pct"]
    rr      = sig["rr"]

    sl  = price * (1 - sl_pct  / 100)
    tp1 = price * (1 + tp1_pct / 100)
    tp2 = price * (1 + tp2_pct / 100)

    action = "COMPRAR AHORA" if is_buy else "NO COMPRAR / EVITAR"
    verb   = "COMPRAR" if is_buy else "VENDER/EVITAR"

    lines = [
        f"  [{color} bold]{verb}: {name}/USDT[/]   [white]Score: {best_score:+d}/100   Confianza: {conf:.0f}%[/]",
        "",
        f"  [bold]ENTRADA:[/]          [{color} bold]{fmt_price(price)}[/]   ← [dim]precio actual — {action}[/]",
        f"  [bold]STOP LOSS:[/]        [bold red]{fmt_price(sl)}[/]   [dim](-{sl_pct}%) — cerrar operación si cae a esto[/]",
        f"  [bold]TAKE PROFIT 1:[/]    [bold green]{fmt_price(tp1)}[/]   [dim](+{tp1_pct}%) — vender el 50% de la posición acá[/]",
        f"  [bold]TAKE PROFIT 2:[/]    [bold green]{fmt_price(tp2)}[/]   [dim](+{tp2_pct}%) — vender el resto acá[/]",
        "",
        f"  [dim]R/R: {rr}x  |  Tiempo estimado: 5-30 min  |  TF: 5m/15m  |  Stop siempre activo[/]",
        "",
        "  [bold]POR QUÉ:",
    ]
    for r in sig.get("reasons", []):
        lines.append(f"    [dim]•[/] [white]{r}[/]")

    return Panel(
        "\n".join(lines),
        title=f"[bold {color}] SEÑAL ACTIVA — {name}/USDT [/]",
        border_style=color,
        padding=(0, 1),
    )


def build_header() -> Panel:
    """Barra de estado en la parte superior."""
    with _lock:
        ts_p    = _state["ts_prices"]
        ts_s    = _state["ts_signals"]
        loading = _state["loading"]

    now = datetime.now().strftime("%H:%M:%S")
    p_str = ts_p.strftime("%H:%M:%S") if ts_p else "—"
    s_str = ts_s.strftime("%H:%M:%S") if ts_s else "calculando..."

    if loading:
        status = "[yellow bold]⏳ Cargando datos iniciales (30-60s)...[/]"
    else:
        status = (
            f"[green]● Precios: {p_str}[/]  [dim]|[/]  "
            f"[cyan]● Indicadores: {s_str}[/]  [dim]|[/]  "
            f"[dim]TF: {TF_FAST}/{TF_SLOW}  Refresh: {PRICE_INTERVAL_SEC}s[/]"
        )

    return Panel(
        f"[bold white]🤖  BOT CRIPTO — SCALPING TIEMPO REAL[/]    {status}    [dim]{now}[/]",
        style="on grey11",
        box=box.HORIZONTALS,
        padding=(0, 1),
    )


def build_tips() -> Panel:
    """Panel con tips rápidos de interpretación."""
    tips = (
        "[dim]💡  "
        "[green]StochRSI < 20[/] = sobrevendido (comprar)  │  "
        "[red]StochRSI > 80[/] = sobrecomprado (vender)  │  "
        "[magenta]⚡ Squeeze[/] = movimiento fuerte próximo  │  "
        "[yellow]SCORE ≥ 55[/] = señal fuerte"
        "[/]"
    )
    return Panel(tips, box=box.HORIZONTALS, style="on grey7", padding=(0, 1))


def build_display():
    """Agrupa todos los componentes del dashboard."""
    return Group(
        build_header(),
        build_price_table(),
        build_signal_panel(),
        build_tips(),
    )


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    console = Console()
    console.print("\n[bold cyan]🚀 Bot Cripto Scalping — iniciando...[/]")
    console.print("[dim]   Cargando datos de Binance (5m y 15m). Esperar ~45 segundos...[/]\n")

    t1 = threading.Thread(target=price_updater,     daemon=True, name="PriceThread")
    t2 = threading.Thread(target=indicator_updater, daemon=True, name="IndicatorThread")
    t1.start()
    t2.start()

    # Esperar primera carga de precios antes de mostrar el display
    time.sleep(4)

    with Live(
        build_display(),
        refresh_per_second=0.5,
        screen=True,        # pantalla completa limpia
        console=Console(force_terminal=True),
    ) as live:
        try:
            while True:
                live.update(build_display())
                time.sleep(PRICE_INTERVAL_SEC)
        except KeyboardInterrupt:
            pass

    console.print("\n[bold green]✓ Bot detenido correctamente.[/]")


if __name__ == "__main__":
    main()
