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
STOCKS_PRICE_INTERVAL = 15   # actualizar precios acciones cada 15s (7 req paralelas)
STOCKS_SIG_INTERVAL   = 180  # recalcular indicadores acciones cada 3 min
STOCK_NOTIFY_SIGNAL   = "STRONG BUY"  # señal que dispara Telegram + estadísticas
TF_FAST               = "5m"
TF_SLOW               = "15m"
CANDLES_FAST          = 100
CANDLES_SLOW          = 60
TRADE_LOG_COOLDOWN    = 90 * 60  # no re-loguear misma crypto en 90 min  [LEGACY — reemplazado por positions]

# Costos por operación (se descuentan al cerrar cada posición)
# Binance taker spot: 0.10% por lado | slippage conservador: 0.05% por lado
COMMISSION_PCT      = 0.10   # % por lado
SLIPPAGE_PCT        = 0.05   # % por lado  (estimación conservadora)
ROUND_TRIP_COST_PCT = (COMMISSION_PCT + SLIPPAGE_PCT) * 2  # total round-trip

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
    # ── Simulador de sesión (reemplaza trade_log) ─────────────────────────
    # Máximo UNA posición por símbolo. Cerradas por toque de SL/TP en velas.
    "positions":      {},   # sym → posición abierta (ver _open_position)
    "closed_trades":  [],   # operaciones cerradas con PnL realizado (neto de costos)
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

        # Revisar posiciones crypto abiertas ANTES de tomar el lock
        # (descarga velas 5m — no bloquear UI durante la red)
        _check_crypto_positions()

        with _lock:
            _state["signals"].update(new_sigs)
            _state["change_24h"].update(changes)
            _state["ts_signals"] = datetime.now()
            _state["loading"]    = False

            # ── Abrir posición si hay señal COMPRAR y no hay una ya abierta ──
            for sym, sig in new_sigs.items():
                if sig.get("signal") == "COMPRAR":
                    if sym not in _state["positions"]:
                        entry   = sig["price"]
                        sl_pct  = sig["sl_pct"]
                        tp1_pct = sig["tp1_pct"]
                        _state["positions"][sym] = {
                            "sym":            sym,
                            "name":           sig["name"],
                            "type":           "crypto",
                            "entry":          entry,
                            "sl":             entry * (1 - sl_pct  / 100),
                            "tp":             entry * (1 + tp1_pct / 100),
                            "sl_pct":         sl_pct,
                            "tp_pct":         tp1_pct,
                            "ts_entry":       datetime.now(),       # local — sólo display
                            "ts_entry_unix":  time.time(),          # UTC unix — para comparar velas
                            "tf":             TF_FAST,
                        }

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
    """Thread 3b: indicadores 1h de acciones cada 3 min via Yahoo v8 API.
    Dispara Telegram + loguea en trade_log cuando señal = STRONG BUY."""
    global _stocks_state, _ts_stocks, _stocks_loading
    while True:
        new_stocks     = {}
        alerts_pending = []   # (sym, data_dict) a notificar tras liberar el lock

        for s in STOCKS:
            sym = s["symbol"]
            try:
                df, price, change_pct = get_stock_ohlcv_v8(sym, interval="1h", range_str="60d")
                if df is not None and len(df) >= 30 and price:
                    input_data = {
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
                    result = analyze_crypto(input_data)

                    stop_loss   = result.get("stop_loss")
                    take_profit = result.get("take_profit")
                    sl_pct  = ((price - stop_loss)   / price * 100) if stop_loss   else 2.0
                    tp1_pct = ((take_profit - price) / price * 100) if take_profit else 4.0

                    entry = {
                        "name":         s["name"],
                        "price":        price,
                        "change_24h":   change_pct,
                        "rsi":          result.get("rsi"),
                        "macd_hist":    result.get("macd_hist"),
                        "ema_trend":    result.get("ema_trend"),
                        "atr_pct":      result.get("atr_pct"),
                        "score":        result["score"],
                        "signal":       result["signal"],
                        "reason":       result.get("reason", ""),
                        "stop_loss":    stop_loss,
                        "take_profit":  take_profit,
                        "risk_reward":  result.get("risk_reward"),
                        "sl_pct":       sl_pct,
                        "tp1_pct":      tp1_pct,
                        "status":       "ok",
                    }
                    new_stocks[sym] = entry

                    # Telegram cuando STRONG BUY
                    if result["signal"] == STOCK_NOTIFY_SIGNAL and should_notify(sym):
                        alerts_pending.append((sym, entry))

                    # Revisar posición abierta de este símbolo contra velas descargadas
                    if df is not None:
                        _check_stock_position(sym, df)

                elif price:
                    new_stocks[sym] = {
                        "name":       s["name"],
                        "price":      price,
                        "change_24h": change_pct,
                        "status":     "no_data",
                    }
            except Exception:
                pass
            time.sleep(0.5)

        # ── Actualizar estado + abrir nuevas posiciones (con lock) ────────────
        with _lock:
            _stocks_state.update(new_stocks)
            _ts_stocks      = datetime.now()
            _stocks_loading = False

            for sym, entry in alerts_pending:
                if sym not in _state["positions"]:
                    price      = entry["price"]
                    stop_loss  = entry.get("stop_loss")
                    take_profit = entry.get("take_profit")
                    if stop_loss and take_profit:
                        sl_pct = (price - stop_loss)    / price * 100
                        tp_pct = (take_profit - price)  / price * 100
                        _state["positions"][sym] = {
                            "sym":           sym,
                            "name":          entry["name"],
                            "type":          "stock",
                            "entry":         price,
                            "sl":            stop_loss,
                            "tp":            take_profit,
                            "sl_pct":        round(sl_pct, 3),
                            "tp_pct":        round(tp_pct, 3),
                            "ts_entry":      datetime.now(),      # local — sólo display
                            "ts_entry_unix": time.time(),         # UTC unix — para comparar velas
                            "tf":            "1h",
                        }

        # ── Mandar Telegram fuera del lock ─────────────────────────────────────
        for sym, entry in alerts_pending:
            if should_notify(sym):
                _send_stock_alert(sym, entry)

        time.sleep(STOCKS_SIG_INTERVAL)


# ─── Simulador de posiciones ──────────────────────────────────────────────────
# Las funciones _close_position, _check_crypto_positions y _check_stock_position
# deben llamarse sin el lock (toman el lock internamente).

def _close_position(sym: str, exit_px: float, reason: str, ts_exit) -> None:
    """
    Cierra una posición, calcula PnL neto descontando comisión + slippage,
    y la mueve a closed_trades.

    Debe llamarse CON _lock ya tomado por el caller.
    """
    pos = _state["positions"].pop(sym, None)
    if pos is None:
        return
    pnl_gross = (exit_px - pos["entry"]) / pos["entry"] * 100
    pnl_net   = pnl_gross - ROUND_TRIP_COST_PCT
    _state["closed_trades"].append({
        **pos,
        "exit":      round(float(exit_px), 8),
        "pnl_gross": round(pnl_gross, 3),
        "pnl_net":   round(pnl_net, 3),
        "result":    "WIN" if pnl_net >= 0 else "LOSS",
        "reason":    reason,
        "ts_exit":   ts_exit,
    })


def _check_crypto_positions() -> None:
    """
    Revisa posiciones crypto abiertas buscando el PRIMER toque de SL o TP
    en velas de 5m. Descarga velas sin lock; aplica resultados con lock.

    Limitaciones de precisión (documentadas):
    - Resolución de 5m: fills intrabar no distinguibles.
    - Si SL y TP se tocan en la misma vela, asume SL (worst-case conservador).
    - Sin datos tick-a-tick: aproximación de fill, no ejecución real.
    - Timestamps en UTC (Binance) vs local time: comparación via Unix epoch.
    """
    # 1. Snapshot de posiciones bajo lock
    with _lock:
        to_check = {
            s: dict(p) for s, p in _state["positions"].items()
            if p.get("type") == "crypto"
        }

    if not to_check:
        return

    # 2. Descargar velas y detectar fills (sin lock — red I/O)
    fills = {}  # sym → (reason, exit_px, ts_fill)
    for sym, pos in to_check.items():
        df = get_ohlcv(sym, "5m", 100)  # ~8h de cobertura
        if df is None:
            continue
        # Filtrar velas posteriores a la entrada usando Unix epoch (timezone-safe)
        entry_unix = pos["ts_entry_unix"]
        df_unix    = df.index.astype("int64") // 1_000_000  # pandas 3.x: µs → s
        post       = df[df_unix > entry_unix]

        for ts, row in post.iterrows():
            sl_hit = row["low"]  <= pos["sl"]
            tp_hit = row["high"] >= pos["tp"]
            if sl_hit:  # SL tiene prioridad ante ambos en misma vela (worst-case)
                fills[sym] = ("Stop-Loss",   pos["sl"], ts)
                break
            elif tp_hit:
                fills[sym] = ("Take-Profit", pos["tp"], ts)
                break

    # 3. Aplicar fills bajo lock
    if fills:
        with _lock:
            for sym, (reason, exit_px, ts) in fills.items():
                _close_position(sym, exit_px, reason, ts)


def _check_stock_position(sym: str, df) -> None:
    """
    Revisa una posición de acción usando el DataFrame descargado de Yahoo Finance.
    Yahoo tiene 15min de delay: fill aproximado, no real.
    Diseñado para llamarse desde stocks_indicator_updater (sin lock).
    """
    with _lock:
        pos = _state["positions"].get(sym)

    if pos is None or pos.get("type") != "stock":
        return

    entry_unix = pos["ts_entry_unix"]
    df_unix    = df.index.astype("int64") // 1_000_000  # pandas 3.x: µs → s
    post       = df[df_unix > entry_unix]

    fill = None
    for ts, row in post.iterrows():
        sl_hit = row["low"]  <= pos["sl"]
        tp_hit = row["high"] >= pos["tp"]
        if sl_hit:
            fill = ("Stop-Loss",   pos["sl"], ts)
            break
        elif tp_hit:
            fill = ("Take-Profit", pos["tp"], ts)
            break

    if fill:
        with _lock:
            _close_position(sym, fill[1], fill[0], fill[2])


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


def _send_stock_alert(symbol: str, data: dict):
    """Formatea y manda alerta Telegram para señal STRONG BUY de acción USA."""
    name       = data["name"]
    price      = data["price"]
    score      = data.get("score", 0)
    signal     = data.get("signal", "STRONG BUY")
    rsi        = data.get("rsi")
    ema_trend  = data.get("ema_trend", "─")
    reason     = data.get("reason", "")
    sl         = data.get("stop_loss")
    tp         = data.get("take_profit")
    rr         = data.get("risk_reward", "─")

    sl_pct  = ((price - sl)  / price * 100) if sl  else 0
    tp_pct  = ((tp - price)  / price * 100) if tp  else 0
    p_fmt   = f"${price:,.2f}" if price > 1 else f"${price:.4f}"
    sl_fmt  = f"${sl:,.2f}"   if sl   else "─"
    tp_fmt  = f"${tp:,.2f}"   if tp   else "─"

    reasons_txt = "\n".join(f"  • {r.strip()}" for r in reason.split(" | ")[:3] if r.strip())

    msg = (
        f"📈 *STRONG BUY ACCIÓN — {name}* ({symbol})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Precio entrada:*  {p_fmt}\n"
        f"🛑 *Stop Loss:*       {sl_fmt}  (-{sl_pct:.1f}%)\n"
        f"🎯 *Take Profit:*     {tp_fmt}  (+{tp_pct:.1f}%)\n"
        f"📊 *Score:* {score:+d}/100   *R/R:* {rr}x\n"
        f"📉 *RSI (1h):* {rsi:.0f}   *Tendencia:* {ema_trend}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*Por qué comprar:*\n{reasons_txt}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ TF: 1h  │  {datetime.now().strftime('%H:%M:%S')}"
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
        "Telegram: 🪙 COMPRAR crypto  +  📈 STRONG BUY acciones"
        "[/]"
    )
    return Panel(tips, box=box.HORIZONTALS, style="on grey7", padding=(0, 1))


def build_stats_panel() -> Panel:
    """
    Panel de estadísticas de sesión — simulación de fills fiel por posición.

    Muestra:
    - CERRADAS: resultado real (primera vela que toca SL o TP) con PnL neto de costos.
    - ABIERTAS: PnL flotante no realizado (precio actual vs entrada).
    - Acumulado: SOLO PnL realizado de cerradas (con comisión + slippage descontados).

    Limitaciones documentadas:
    - Resolución de 5m para crypto: fills intrabar no distinguibles.
    - Stocks: Yahoo Finance con 15min de delay.
    - Sin tick-a-tick: aproximación, no ejecución real.
    """
    with _lock:
        positions     = dict(_state["positions"])
        closed_trades = list(_state["closed_trades"])
        crypto_px     = dict(_state["prices"])
        stocks_px     = dict(_stocks_prices)

    title     = "[bold white] 📊 ESTADÍSTICAS DE SESIÓN [/]"
    cost_note = (
        f"[dim]costos: {COMMISSION_PCT:.2f}%+{SLIPPAGE_PCT:.2f}% × 2 "
        f"= {ROUND_TRIP_COST_PCT:.2f}% round-trip | "
        f"fills: 1ª vela 5m que toca SL/TP (no tick a tick)[/]"
    )

    if not positions and not closed_trades:
        return Panel(
            Align.center(
                "[dim]Sin operaciones. Crypto COMPRAR → 🪙 | Stocks STRONG BUY → 📈[/]\n" + cost_note,
                vertical="middle",
            ),
            title=title, border_style="steel_blue1", height=4,
        )

    wins = losses = 0
    realized_pct  = 0.0
    rows = []

    # ── Cerradas ─────────────────────────────────────────────────────────────
    for trade in closed_trades:
        if trade["result"] == "WIN":
            wins += 1
            result_t = Text(f"✓ WIN  ({trade['pnl_net']:+.2f}% neto)", style="bold green")
        else:
            losses += 1
            result_t = Text(f"✗ LOSS ({trade['pnl_net']:+.2f}% neto)", style="bold red")
        realized_pct += trade["pnl_net"]
        type_tag = Text("📈" if trade["type"] == "stock" else "🪙",
                        style="magenta" if trade["type"] == "stock" else "cyan")
        rows.append((
            type_tag, trade["name"],
            trade["ts_entry"].strftime("%H:%M"),
            fmt_price(trade["entry"]),
            fmt_price(trade["exit"]),
            result_t,
        ))

    # ── Abiertas ──────────────────────────────────────────────────────────────
    unrealized_pct = 0.0
    open_count     = 0
    for sym, pos in positions.items():
        if pos["type"] == "stock":
            fp      = stocks_px.get(sym)
            current = fp[0] if fp else pos["entry"]
        else:
            current = crypto_px.get(sym, pos["entry"])

        floating = (current - pos["entry"]) / pos["entry"] * 100
        unrealized_pct += floating
        open_count     += 1

        col      = "green" if floating >= 0 else "red"
        result_t = Text(f"● OPEN ({floating:+.2f}% float)", style=col)
        type_tag = Text("📈" if pos["type"] == "stock" else "🪙",
                        style="magenta" if pos["type"] == "stock" else "cyan")
        rows.append((
            type_tag, pos["name"],
            pos["ts_entry"].strftime("%H:%M"),
            fmt_price(pos["entry"]),
            fmt_price(current),
            result_t,
        ))

    closed   = wins + losses
    wr       = (wins / closed * 100) if closed > 0 else 0.0
    acc_col  = "green" if realized_pct  >= 0 else "red"
    ur_col   = "green" if unrealized_pct >= 0 else "red"

    summary = (
        f"  [bold white]Cerradas:[/] {closed}  "
        f"[bold green]✓ {wins}[/]  "
        f"[bold red]✗ {losses}[/]  "
        f"[yellow]● Abiertas: {open_count}[/]  [dim]│[/]  "
        f"[white]Win Rate: [bold]{wr:.0f}%[/][/]  [dim]│[/]  "
        f"[white]Realizado: [{acc_col} bold]{realized_pct:+.2f}%[/]  "
        f"No realizado: [{ur_col}]{unrealized_pct:+.2f}%[/][/]"
    )

    tbl = Table(box=box.SIMPLE, show_header=True, header_style="dim white",
                expand=True, padding=(0, 1))
    tbl.add_column("",           width=2,  justify="center")
    tbl.add_column("PAR",        width=8,  justify="left", style="cyan")
    tbl.add_column("HORA",       width=6,  justify="center", style="dim")
    tbl.add_column("ENTRADA",    width=13, justify="right")
    tbl.add_column("ACTUAL/EXIT",width=13, justify="right")
    tbl.add_column("RESULTADO",  width=24, justify="left")

    for type_tag, name, ts_str, entry_str, curr_str, result_t in rows:
        tbl.add_row(type_tag, name, ts_str, entry_str, curr_str, result_t)

    return Panel(
        Group(Text.from_markup(summary), Text.from_markup("  " + cost_note), tbl),
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
