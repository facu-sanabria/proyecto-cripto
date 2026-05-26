"""
main.py — Dashboard de scalping en tiempo real

Arquitectura:
  Thread 1 (price_updater):     precios de todos los activos cada 3s
  Thread 2 (indicator_updater): indicadores técnicos (5m/15m) cada 60s
  Main:                         Rich Live refresh cada 3s
  Telegram:                     alerta automática cuando hay señal COMPRAR

Activos: 15 criptos top de Binance con alta liquidez

Cómo correr:  python main.py
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)

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

from fetcher        import get_ohlcv
from scalper        import analyze_scalp, fmt_price
from notifier       import send_telegram, should_notify
from stocks_fetcher import fetch_stocks_all, get_stock_ohlcv_v8, get_stocks_prices_bulk
from analyzer       import analyze_crypto

# ─── Activos a analizar ───────────────────────────────────────────────────────
# Seleccionados por liquidez, volumen y comportamiento técnico en scalping
ASSETS = [
    {"symbol": "BTCUSDT",  "name": "BTC"},
    {"symbol": "ETHUSDT",  "name": "ETH"},
    {"symbol": "SOLUSDT",  "name": "SOL"},
    {"symbol": "BNBUSDT",  "name": "BNB"},
    {"symbol": "XRPUSDT",  "name": "XRP"},
    {"symbol": "ADAUSDT",  "name": "ADA"},
    {"symbol": "AVAXUSDT", "name": "AVAX"},
    {"symbol": "DOGEUSDT", "name": "DOGE"},
    {"symbol": "LINKUSDT", "name": "LINK"},
    {"symbol": "DOTUSDT",  "name": "DOT"},
    {"symbol": "LTCUSDT",  "name": "LTC"},
    {"symbol": "UNIUSDT",  "name": "UNI"},
    {"symbol": "ATOMUSDT", "name": "ATOM"},
    {"symbol": "NEARUSDT", "name": "NEAR"},
    {"symbol": "MATICUSDT","name": "MATIC"},
]

BINANCE_BASE          = "https://api.binance.com/api/v3"
PRICE_INTERVAL_SEC    = 3    # actualizar precios crypto cada N segundos
INDICATOR_INTERVAL    = 60   # recalcular indicadores crypto cada N segundos
STOCKS_PRICE_INTERVAL = 60   # actualizar precios acciones cada 60s
STOCKS_SIG_INTERVAL   = 180  # recalcular indicadores acciones cada 3 min
TF_FAST               = "5m"
TF_SLOW               = "15m"
CANDLES_FAST          = 100
CANDLES_SLOW          = 60
TRADE_LOG_COOLDOWN    = 90 * 60  # no re-loguear misma crypto en 90 min

# Acciones — análisis en 1h (swing/posición, NO scalping)
# Yahoo Finance gratis tiene 15 min de delay: no apto para scalping en 5m
STOCKS = [
    {"symbol": "NVDA",  "name": "NVIDIA",    "type": "stock"},
    {"symbol": "SPY",   "name": "S&P 500",   "type": "etf"},
    {"symbol": "AAPL",  "name": "Apple",     "type": "stock"},
    {"symbol": "MSFT",  "name": "Microsoft", "type": "stock"},
    {"symbol": "GOOGL", "name": "Google",    "type": "stock"},
    {"symbol": "META",  "name": "Meta",      "type": "stock"},
    {"symbol": "QQQ",   "name": "Nasdaq100", "type": "etf"},
]

# ─── Estado compartido ────────────────────────────────────────────────────────
_lock  = threading.Lock()
_state = {
    "prices":          {},
    "prev_prices":     {},
    "signals":         {},
    "change_24h":      {},
    "ts_prices":       None,
    "ts_signals":      None,
    "loading":         True,
    "trade_log":       [],   # historial de señales COMPRAR para estadísticas
    "trade_logged_at": {},   # sym → float (time.time()) del último log
}

# Estado de acciones — dos capas: precios rápidos + análisis lento
_stocks_prices  = {}   # symbol → (price, change_pct) — actualiza cada 60s
_stocks_state   = {}   # symbol → dict completo con score, rsi, etc. — cada 3 min
_ts_stocks_p    = None # timestamp último update de precios acciones
_ts_stocks      = None # timestamp último update de indicadores acciones
_stocks_loading = True


# ─── Fetching de precios ──────────────────────────────────────────────────────

def _get_all_prices() -> dict:
    """1 sola llamada → todos los precios. Muy eficiente."""
    try:
        r = requests.get(f"{BINANCE_BASE}/ticker/price", timeout=5)
        r.raise_for_status()
        return {t["symbol"]: float(t["price"]) for t in r.json()}
    except Exception:
        return {}


def _get_all_change_24h() -> dict:
    """1 sola llamada → variación 24h de todos los símbolos."""
    try:
        r = requests.get(f"{BINANCE_BASE}/ticker/24hr", timeout=8)
        r.raise_for_status()
        return {t["symbol"]: float(t["priceChangePercent"]) for t in r.json()}
    except Exception:
        return {}


# ─── Threads ──────────────────────────────────────────────────────────────────

def price_updater():
    """Thread 1: actualiza precios cada 3 segundos."""
    while True:
        prices = _get_all_prices()
        if prices:
            with _lock:
                for a in ASSETS:
                    sym = a["symbol"]
                    if sym in prices:
                        old = _state["prices"].get(sym, prices[sym])
                        _state["prev_prices"][sym] = old
                        _state["prices"][sym]      = prices[sym]
                _state["ts_prices"] = datetime.now()
        time.sleep(PRICE_INTERVAL_SEC)


def indicator_updater():
    """Thread 2: descarga OHLCV y recalcula indicadores cada 60s."""
    while True:
        changes  = _get_all_change_24h()
        new_sigs = {}

        for a in ASSETS:
            sym = a["symbol"]
            try:
                df5  = get_ohlcv(sym, TF_FAST,  CANDLES_FAST)
                df15 = get_ohlcv(sym, TF_SLOW,  CANDLES_SLOW)
                if df5 is not None and df15 is not None and len(df5) >= 30:
                    sig = analyze_scalp(df5, df15)
                    sig["name"]       = a["name"]
                    sig["change_24h"] = changes.get(sym, 0.0)
                    new_sigs[sym]     = sig

                    # Telegram: alertar solo señales fuertes de compra
                    if sig["signal"] == "COMPRAR" and should_notify(sym):
                        _send_scalp_alert(sym, sig)

            except Exception:
                pass
            time.sleep(0.2)   # pequeño delay entre descargas

        with _lock:
            _state["signals"].update(new_sigs)
            _state["change_24h"].update(changes)
            _state["ts_signals"] = datetime.now()
            _state["loading"]    = False

            # ── Trade log: registrar señales COMPRAR para estadísticas ──────
            now_ts = time.time()
            for sym, sig in new_sigs.items():
                if sig.get("signal") == "COMPRAR":
                    last_logged = _state["trade_logged_at"].get(sym, 0)
                    if (now_ts - last_logged) >= TRADE_LOG_COOLDOWN:
                        _state["trade_log"].append({
                            "sym":     sym,
                            "name":    sig["name"],
                            "entry":   sig["price"],
                            "sl_pct":  sig["sl_pct"],
                            "tp1_pct": sig["tp1_pct"],
                            "ts":      datetime.now(),
                        })
                        _state["trade_logged_at"][sym] = now_ts

        time.sleep(INDICATOR_INTERVAL)


def stocks_price_updater():
    """Thread 3a: precios rápidos de acciones cada 60s via Yahoo v8 API directo."""
    global _stocks_prices, _ts_stocks_p
    symbols = [s["symbol"] for s in STOCKS]
    while True:
        result = get_stocks_prices_bulk(symbols)
        if result:
            with _lock:
                _stocks_prices.update(result)
                _ts_stocks_p = datetime.now()
        time.sleep(STOCKS_PRICE_INTERVAL)


def stocks_indicator_updater():
    """Thread 3b: indicadores 1h de acciones cada 3 min via Yahoo v8 API."""
    global _stocks_state, _ts_stocks, _stocks_loading
    while True:
        new_stocks = {}
        for s in STOCKS:
            sym = s["symbol"]
            try:
                df, price, change_pct = get_stock_ohlcv_v8(sym, interval="1h", range_str="60d")
                if df is not None and len(df) >= 30 and price:
                    data = {
                        "crypto": {
                            "symbol":     sym,
                            "name":       s["name"],
                            "asset_type": s.get("type", "stock"),
                        },
                        "ohlcv": df,
                        "stats": {
                            "price":       price,
                            "change_pct":  change_pct,
                            "volume_usdt": 0,
                        },
                    }
                    result = analyze_crypto(data)
                    new_stocks[sym] = {
                        "name":       s["name"],
                        "price":      price,
                        "change_24h": change_pct,
                        "rsi":        result.get("rsi"),
                        "macd_hist":  result.get("macd_hist"),
                        "ema_trend":  result.get("ema_trend"),
                        "atr_pct":    result.get("atr_pct"),
                        "score":      result["score"],
                        "signal":     result["signal"],
                        "reason":     result.get("reason", ""),
                        "status":     "ok",
                    }
                elif price:
                    # Tenemos precio pero no suficientes velas para indicadores
                    new_stocks[sym] = {
                        "name":   s["name"],
                        "price":  price,
                        "change_24h": change_pct,
                        "status": "no_data",
                    }
            except Exception:
                pass
            time.sleep(0.5)

        with _lock:
            _stocks_state.update(new_stocks)
            _ts_stocks      = datetime.now()
            _stocks_loading = False

        time.sleep(STOCKS_SIG_INTERVAL)


def _send_scalp_alert(symbol: str, sig: dict):
    """Formatea y manda alerta Telegram para señal de compra."""
    name    = sig["name"]
    price   = sig["price"]
    score   = sig["score"]
    conf    = sig["confidence"]
    sl_pct  = sig["sl_pct"]
    tp1_pct = sig["tp1_pct"]
    tp2_pct = sig["tp2_pct"]
    rr      = sig["rr"]
    sl      = price * (1 - sl_pct  / 100)
    tp1     = price * (1 + tp1_pct / 100)
    tp2     = price * (1 + tp2_pct / 100)

    reasons_txt = "\n".join(f"  • {r}" for r in sig.get("reasons", [])[:3])

    msg = (
        f"🟢 *SEÑAL DE COMPRA — {name}* ({symbol.replace('USDT','')})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Precio entrada:*  {fmt_price(price)}\n"
        f"🛑 *Stop Loss:*       {fmt_price(sl)}  (-{sl_pct}%)\n"
        f"🎯 *Take Profit 1:*   {fmt_price(tp1)}  (+{tp1_pct}%)\n"
        f"🎯 *Take Profit 2:*   {fmt_price(tp2)}  (+{tp2_pct}%)\n"
        f"📊 *Score:* {score:+d}/100   *Confianza:* {conf:.0f}%   *R/R:* {rr}x\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*Por qué comprar:*\n{reasons_txt}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ TF: {TF_FAST}/{TF_SLOW}  │  {datetime.now().strftime('%H:%M:%S')}"
    )
    send_telegram(msg)


# ─── Construcción del display ─────────────────────────────────────────────────

SIGNAL_STYLE = {
    "COMPRAR":        ("bold white on green",   "⬆  COMPRAR"),
    "POSIBLE COMPRA": ("bold green",            "▲  POSIBLE COMPRA"),
    "ESPERAR":        ("yellow",                "─  ESPERAR"),
    "POSIBLE VENTA":  ("bold dark_orange",      "▼  POSIBLE VENTA"),
    "VENDER/EVITAR":  ("bold white on red",     "⬇  VENDER/EVITAR"),
}


def _fmt_signal(sig: str) -> Text:
    style, label = SIGNAL_STYLE.get(sig, ("white", sig))
    return Text(f" {label} ", style=style)


def _fmt_score(score: int) -> Text:
    if score >= 55:  return Text(f"{score:+d}", style="bold green")
    if score >= 28:  return Text(f"{score:+d}", style="green")
    if score <= -55: return Text(f"{score:+d}", style="bold red")
    if score <= -28: return Text(f"{score:+d}", style="red")
    return Text(f"{score:+d}", style="yellow")


def build_header() -> Panel:
    with _lock:
        ts_p    = _state["ts_prices"]
        ts_s    = _state["ts_signals"]
        loading = _state["loading"]

    now   = datetime.now().strftime("%H:%M:%S")
    p_str = ts_p.strftime("%H:%M:%S") if ts_p else "─"
    s_str = ts_s.strftime("%H:%M:%S") if ts_s else "calculando..."

    if loading:
        status = "[yellow bold]⏳ Cargando datos iniciales (30-60s)...[/]"
    else:
        status = (
            f"[green]● Precios: {p_str}[/]  [dim]│[/]  "
            f"[cyan]● Indicadores: {s_str}[/]  [dim]│[/]  "
            f"[dim]TF: {TF_FAST}/{TF_SLOW}  Refresh: {PRICE_INTERVAL_SEC}s  │  {len(ASSETS)} activos[/]"
        )

    return Panel(
        f"[bold white]🤖  BOT SCALPING — TIEMPO REAL[/]    {status}    [dim]{now}[/]",
        style="on grey11",
        box=box.HORIZONTALS,
        padding=(0, 1),
    )


def build_price_table() -> Table:
    """Tabla principal con todos los activos ordenados por score."""
    with _lock:
        sigs   = dict(_state["signals"])
        prices = dict(_state["prices"])
        prevs  = dict(_state["prev_prices"])

    table = Table(
        box=box.SIMPLE_HEAVY,
        header_style="bold white on navy_blue",
        border_style="steel_blue1",
        show_edge=True,
        expand=True,
        padding=(0, 1),
    )

    table.add_column("PAR",         width=7,  justify="left",  style="bold cyan")
    table.add_column("PRECIO",      width=14, justify="right")
    table.add_column("DIR",         width=3,  justify="center")
    table.add_column("24H %",       width=8,  justify="right")
    table.add_column("StochRSI",    width=9,  justify="center")
    table.add_column("VWAP",        width=7,  justify="center")
    table.add_column("VOL x",       width=6,  justify="center")
    table.add_column("SQUEEZE",     width=8,  justify="center")
    table.add_column("SCORE",       width=7,  justify="center")
    table.add_column("SEÑAL",       width=18, justify="center")

    # Ordenar: mejores señales arriba
    sym_list = [a["symbol"] for a in ASSETS]
    sym_list.sort(key=lambda s: sigs.get(s, {}).get("score", -999), reverse=True)

    for sym in sym_list:
        sig   = sigs.get(sym, {})
        price = prices.get(sym, sig.get("price", 0) if sig else 0)
        prev  = prevs.get(sym, price)
        name  = sig.get("name", sym.replace("USDT", ""))

        # Precio con flecha
        if price > prev * 1.00005:
            p_txt = Text(fmt_price(price), style="bold green")
            arrow = Text("▲", style="bold green")
        elif price < prev * 0.99995:
            p_txt = Text(fmt_price(price), style="bold red")
            arrow = Text("▼", style="bold red")
        else:
            p_txt = Text(fmt_price(price), style="white")
            arrow = Text("·", style="dim")

        # 24h change
        ch    = sig.get("change_24h", 0) if sig else 0
        ch_t  = Text(f"{ch:+.2f}%", style="green" if ch >= 0 else "red")

        if not sig:
            table.add_row(
                name, p_txt, arrow, ch_t,
                Text("...", style="dim"), Text("...", style="dim"),
                Text("...", style="dim"), Text("...", style="dim"),
                Text("...", style="dim"), Text("Calculando...", style="dim"),
            )
            continue

        # StochRSI K
        k = sig["stoch_k"]
        if k < 20:   k_t = Text(f"{k:.0f}", style="bold green")
        elif k > 80: k_t = Text(f"{k:.0f}", style="bold red")
        elif k < 35: k_t = Text(f"{k:.0f}", style="green")
        elif k > 65: k_t = Text(f"{k:.0f}", style="red")
        else:        k_t = Text(f"{k:.0f}", style="white")

        # VWAP
        vwap_t = Text("↑ SÍ", style="bold green") if sig["above_vwap"] \
            else Text("↓ NO", style="bold red")

        # Volumen
        vr = sig["vol_ratio"]
        if vr > 2.5:   vr_t = Text(f"{vr:.1f}x", style="bold yellow")
        elif vr > 1.5: vr_t = Text(f"{vr:.1f}x", style="green")
        else:          vr_t = Text(f"{vr:.1f}x", style="dim white")

        # BB Squeeze
        sq_t = Text("⚡ SÍ", style="bold magenta") if sig.get("bb_squeeze") \
            else Text("no", style="dim")

        table.add_row(
            name, p_txt, arrow, ch_t, k_t,
            vwap_t, vr_t, sq_t,
            _fmt_score(sig["score"]),
            _fmt_signal(sig["signal"]),
        )

    return table


def build_signal_panel() -> Panel:
    """Panel con instrucciones concretas para la mejor señal activa."""
    with _lock:
        sigs   = dict(_state["signals"])
        prices = dict(_state["prices"])

    # Mejor señal con score ≥ 28
    best_sym   = None
    best_score = 0
    for sym, sig in sigs.items():
        sc = sig.get("score", 0)
        if sc > best_score and sc >= 28:
            best_score = sc
            best_sym   = sym

    if not best_sym:
        return Panel(
            Align.center(
                "[bold yellow]Sin señales activas — Esperando configuración favorable...[/]",
                vertical="middle",
            ),
            title="[bold] SEÑAL ACTIVA [/]",
            border_style="yellow",
            height=9,
        )

    sig    = sigs[best_sym]
    name   = sig.get("name", best_sym.replace("USDT", ""))
    price  = prices.get(best_sym, sig["entry"])
    conf   = sig["confidence"]
    score  = sig["score"]

    sl_pct  = sig["sl_pct"]
    tp1_pct = sig["tp1_pct"]
    tp2_pct = sig["tp2_pct"]
    rr      = sig["rr"]

    sl  = price * (1 - sl_pct  / 100)
    tp1 = price * (1 + tp1_pct / 100)
    tp2 = price * (1 + tp2_pct / 100)

    signal  = sig["signal"]
    is_buy  = score > 0
    color   = "green" if is_buy else "red"

    lines = [
        f"  [bold {color}]{signal}: {name}/USDT[/]   "
        f"[white]Score: {score:+d}/100   Confianza: {conf:.0f}%[/]",
        "",
        f"  [bold]ENTRADA:[/]          [{color} bold]{fmt_price(price)}[/]   "
        f"[dim]← precio actual[/]",
        f"  [bold]STOP LOSS:[/]        [bold red]{fmt_price(sl)}[/]   "
        f"[dim](-{sl_pct}%) — cerrar si cae a esto[/]",
        f"  [bold]TAKE PROFIT 1:[/]    [bold green]{fmt_price(tp1)}[/]   "
        f"[dim](+{tp1_pct}%) — vender 50% de la posición acá[/]",
        f"  [bold]TAKE PROFIT 2:[/]    [bold green]{fmt_price(tp2)}[/]   "
        f"[dim](+{tp2_pct}%) — vender el resto acá[/]",
        "",
        f"  [dim]R/R: {rr}x  │  TF: {TF_FAST}/{TF_SLOW}  │  Stop siempre activo[/]",
        "",
        "  [bold]POR QUÉ:",
    ]
    for r in sig.get("reasons", [])[:4]:
        lines.append(f"    [dim]•[/] [white]{r}[/]")

    return Panel(
        "\n".join(lines),
        title=f"[bold {color}] {'🟢' if is_buy else '🔴'} SEÑAL ACTIVA — {name}/USDT [/]",
        border_style=color,
        padding=(0, 1),
    )


def build_stocks_table() -> Panel:
    """Tabla de acciones USA — precios cada 60s, indicadores 1h cada 3 min."""
    with _lock:
        snap    = dict(_stocks_state)
        fast_p  = dict(_stocks_prices)
        loading = _stocks_loading
        ts_sig  = _ts_stocks
        ts_p    = _ts_stocks_p

    # Horario de mercado NYSE (ET = UTC-4 verano, UTC-5 invierno)
    from datetime import timezone, timedelta
    et_now      = datetime.now(timezone(timedelta(hours=-4)))
    market_open = (
        et_now.weekday() < 5 and
        et_now.hour >= 9 and
        (et_now.hour > 9 or et_now.minute >= 30) and
        et_now.hour < 16
    )
    mkt_txt  = "[green]● ABIERTO[/]" if market_open else "[red]● CERRADO[/]"
    ts_str   = ts_sig.strftime("%H:%M:%S") if ts_sig else "─"
    tp_str   = ts_p.strftime("%H:%M:%S")   if ts_p   else "─"

    title = (
        f"[bold white] 📈 ACCIONES USA [/]  "
        f"[dim]│  {mkt_txt}  │  "
        f"precios: {tp_str}  │  indicadores: {ts_str}[/]"
    )

    if loading:
        return Panel(
            Align.center("[dim yellow]⏳ Descargando datos de acciones...[/]", vertical="middle"),
            title=title, border_style="magenta", height=4,
        )

    STOCK_SIG = {
        "STRONG BUY":  ("bold white on green",  "⬆  STRONG BUY"),
        "BUY":         ("bold green",            "▲  BUY"),
        "NEUTRAL":     ("yellow",                "─  NEUTRAL"),
        "SELL":        ("bold dark_orange",      "▼  SELL"),
        "STRONG SELL": ("bold white on red",     "⬇  STRONG SELL"),
    }

    table = Table(
        box=box.SIMPLE_HEAVY,
        header_style="bold white on dark_magenta",
        border_style="magenta",
        show_edge=True,
        expand=True,
        padding=(0, 1),
    )
    table.add_column("TICKER",    width=7,  justify="left",  style="bold magenta")
    table.add_column("NOMBRE",    width=11, justify="left")
    table.add_column("PRECIO",    width=11, justify="right")
    table.add_column("DIR",       width=3,  justify="center")
    table.add_column("24H %",     width=8,  justify="right")
    table.add_column("RSI (1h)",  width=9,  justify="center")
    table.add_column("MACD",      width=6,  justify="center")
    table.add_column("TENDENCIA", width=12, justify="center")
    table.add_column("SCORE",     width=7,  justify="center")
    table.add_column("SEÑAL",     width=16, justify="center")

    stock_list = sorted(
        STOCKS,
        key=lambda s: snap.get(s["symbol"], {}).get("score", -999) or -999,
        reverse=True,
    )

    for s in stock_list:
        sym    = s["symbol"]
        data   = snap.get(sym, {})
        fp     = fast_p.get(sym)            # (price, change_pct) or None

        # Precio: fast_prices tiene prioridad, fallback a snap
        if fp:
            price, ch = fp
        else:
            price = (data.get("price") or 0)
            ch    = data.get("change_24h") or 0

        # Flecha de dirección (comparar con precio de snapshot)
        snap_price = data.get("price") or price
        if   price > snap_price * 1.0001: arrow = Text("▲", style="bold green")
        elif price < snap_price * 0.9999: arrow = Text("▼", style="bold red")
        else:                             arrow = Text("·", style="dim")

        p_txt  = Text(f"${price:,.2f}" if price > 0 else "─", style="white")
        ch_txt = Text(f"{ch:+.2f}%", style="green" if ch >= 0 else "red") if ch else Text("─", style="dim")

        # Sin datos de indicadores todavía
        if not data or data.get("status") == "no_data":
            label = "Calculando..." if loading or not ts_sig else ("Sin datos" if market_open else "─")
            table.add_row(
                sym, s["name"], p_txt, arrow, ch_txt,
                Text("─", style="dim"), Text("─", style="dim"),
                Text("─", style="dim"), Text("─", style="dim"),
                Text(label, style="dim"),
            )
            continue

        rsi = data.get("rsi")
        if rsi is None:   rsi_t = Text("─", style="dim")
        elif rsi < 30:    rsi_t = Text(f"{rsi:.0f}", style="bold green")
        elif rsi > 70:    rsi_t = Text(f"{rsi:.0f}", style="bold red")
        elif rsi < 45:    rsi_t = Text(f"{rsi:.0f}", style="green")
        elif rsi > 55:    rsi_t = Text(f"{rsi:.0f}", style="red")
        else:             rsi_t = Text(f"{rsi:.0f}", style="white")

        mh = data.get("macd_hist")
        if mh is None:   macd_t = Text("─", style="dim")
        elif mh > 0:     macd_t = Text("▲ +", style="bold green")
        elif mh < 0:     macd_t = Text("▼ −", style="bold red")
        else:            macd_t = Text("─", style="dim")

        trend = data.get("ema_trend")
        if trend is None:
            trend_t = Text("─", style="dim")
        else:
            t_st    = "green" if "Alcista" in trend else ("red" if "Bajista" in trend else "dim")
            trend_t = Text(trend[:11], style=t_st)

        score  = data.get("score")
        sc_t   = _fmt_score(score) if score is not None else Text("─", style="dim")

        signal = data.get("signal")
        if signal:
            sty, lbl = STOCK_SIG.get(signal, ("white", signal))
            sig_t = Text(f" {lbl} ", style=sty)
        else:
            sig_t = Text("─", style="dim")

        table.add_row(sym, s["name"], p_txt, arrow, ch_txt,
                      rsi_t, macd_t, trend_t, sc_t, sig_t)

    return Panel(table, title=title, border_style="magenta", padding=(0, 0))


def build_tips() -> Panel:
    tips = (
        "[dim]💡  "
        "[green]StochRSI < 20[/] = sobrevendido (comprar)  │  "
        "[red]StochRSI > 80[/] = sobrecomprado (vender)  │  "
        "[magenta]⚡ Squeeze[/] = movimiento fuerte próximo  │  "
        "[yellow]SCORE ≥ 55[/] = señal fuerte  │  "
        "Telegram: alerta automática en COMPRAR"
        "[/]"
    )
    return Panel(tips, box=box.HORIZONTALS, style="on grey7", padding=(0, 1))


def build_stats_panel() -> Panel:
    """Panel de estadísticas de sesión: operaciones COMPRAR y rendimiento acumulado."""
    with _lock:
        log    = list(_state["trade_log"])
        prices = dict(_state["prices"])

    title = "[bold white] 📊 ESTADÍSTICAS DE SESIÓN [/]"

    if not log:
        msg = (
            "[dim]Sin operaciones registradas aún.  "
            "Cada señal COMPRAR queda registrada aquí automáticamente.[/]"
        )
        return Panel(
            Align.center(msg, vertical="middle"),
            title=title,
            border_style="steel_blue1",
            height=3,
        )

    wins = losses = open_ = 0
    accum_pct = 0.0
    rows = []

    for trade in log:
        sym     = trade["sym"]
        name    = trade["name"]
        entry   = trade["entry"]
        sl_pct  = trade["sl_pct"]
        tp1_pct = trade["tp1_pct"]
        ts      = trade["ts"]
        current = prices.get(sym, entry)

        tp1_price = entry * (1 + tp1_pct / 100)
        sl_price  = entry * (1 - sl_pct  / 100)
        pct_now   = (current - entry) / entry * 100

        if current >= tp1_price:
            result_t   = Text(f"✓ WIN  (+{tp1_pct:.1f}%)", style="bold green")
            accum_pct += tp1_pct
            wins      += 1
        elif current <= sl_price:
            result_t   = Text(f"✗ LOSS (-{sl_pct:.1f}%)", style="bold red")
            accum_pct -= sl_pct
            losses    += 1
        else:
            col      = "green" if pct_now >= 0 else "red"
            result_t = Text(f"● OPEN ({pct_now:+.2f}%)", style=col)
            open_   += 1

        rows.append((name, ts.strftime("%H:%M"), fmt_price(entry), fmt_price(current), result_t))

    closed   = wins + losses
    win_rate = (wins / closed * 100) if closed > 0 else 0.0
    acc_col  = "green" if accum_pct >= 0 else "red"

    # Línea de resumen
    summary = (
        f"  [bold white]Operaciones:[/] {len(log)}   "
        f"[bold green]✓ Ganadas: {wins}[/]   "
        f"[bold red]✗ Perdidas: {losses}[/]   "
        f"[yellow]● Abiertas: {open_}[/]   "
        f"[dim]│[/]   "
        f"[white]Win Rate: [bold]{win_rate:.0f}%[/][/]   "
        f"[white]Ganancia acumulada: [{acc_col} bold]{accum_pct:+.2f}%[/][/]"
    )

    # Tabla de operaciones individuales
    tbl = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="dim white",
        expand=True,
        padding=(0, 1),
    )
    tbl.add_column("PAR",      width=6,  justify="left",  style="cyan")
    tbl.add_column("HORA",     width=6,  justify="center", style="dim")
    tbl.add_column("ENTRADA",  width=13, justify="right")
    tbl.add_column("ACTUAL",   width=13, justify="right")
    tbl.add_column("RESULTADO",width=20, justify="left")

    for name, ts_str, entry_str, curr_str, result_t in rows:
        tbl.add_row(name, ts_str, entry_str, curr_str, result_t)

    return Panel(
        Group(Text.from_markup(summary), tbl),
        title=title,
        border_style="steel_blue1",
        padding=(0, 0),
    )


def build_display() -> Group:
    return Group(
        build_header(),
        build_price_table(),
        build_stats_panel(),    # siempre visible — justo bajo tabla crypto
        build_stocks_table(),
        build_signal_panel(),
        build_tips(),
    )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    console = Console()
    console.print("\n[bold cyan]🚀 Bot Scalping — iniciando...[/]")
    console.print(f"[dim]   {len(ASSETS)} activos  │  TF: {TF_FAST}/{TF_SLOW}  │  Refresh: {PRICE_INTERVAL_SEC}s[/]")
    console.print(f"[dim]   Indicadores: cada {INDICATOR_INTERVAL}s  │  Telegram: ON para señales COMPRAR[/]\n")

    t1 = threading.Thread(target=price_updater,          daemon=True, name="CryptoPriceThread")
    t2 = threading.Thread(target=indicator_updater,      daemon=True, name="CryptoIndThread")
    t3 = threading.Thread(target=stocks_price_updater,   daemon=True, name="StocksPriceThread")
    t4 = threading.Thread(target=stocks_indicator_updater, daemon=True, name="StocksIndThread")
    t1.start()
    t2.start()
    t3.start()
    t4.start()

    # Esperar primer lote de precios
    time.sleep(4)

    with Live(
        build_display(),
        refresh_per_second=1,
        screen=True,
        console=Console(force_terminal=True),
    ) as live:
        try:
            while True:
                live.update(build_display())
                time.sleep(PRICE_INTERVAL_SEC)
        except KeyboardInterrupt:
            pass

    console.print("\n[bold green]✓ Bot detenido.[/]")


if __name__ == "__main__":
    main()
