# ══════════════════════════════════════════════════════════════════════════════
# backtester.py — Simulador histórico del bot
#
# Descarga meses de datos históricos y simula cómo hubiera operado el bot.
# Responde: "Si el bot hubiera operado los últimos 6 meses, ¿ganaba o perdía?"
#
# Uso:
#   python backtester.py                    → 6 meses, todas las criptos de config.py
#   python backtester.py --months 12        → 12 meses
#   python backtester.py --symbol BTCUSDT   → solo Bitcoin
#   python backtester.py --capital 500      → capital inicial $500
#   python backtester.py --threshold 60     → solo entrar con señal STRONG BUY
# ══════════════════════════════════════════════════════════════════════════════

import argparse
import sys
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Forzar UTF-8 en la consola de Windows para que los emojis no rompan
sys.stdout.reconfigure(encoding="utf-8")

from config import CRYPTOS, TIMEFRAME, SL_ATR_MULT, TP_ATR_MULT
from indicators import (
    calc_rsi, calc_macd, calc_ema, calc_bollinger, calc_atr, calc_adx,
    calculate_indicators_at, INDICATOR_WINDOW as _IND_WINDOW,
)
from analyzer import score_crypto
from market_context import get_historical_fear_greed, market_context_score_adjustment

# ─── Configuración del backtest ───────────────────────────────────────────────

BINANCE_BASE = "https://api.binance.com/api/v3"

# Score mínimo para entrar en una posición
# 40 = BUY calificado → balance entre calidad y frecuencia de trades
# v2 usaba 60 (solo STRONG BUY) → demasiado restrictivo, 0 trades en muchos períodos
DEFAULT_THRESHOLD  = 40

# Capital inicial en USDT para la simulación
DEFAULT_CAPITAL    = 1000.0

# Meses de historial a descargar
DEFAULT_MONTHS     = 6

# Ventana mínima de velas — importada desde indicators.py para mantener consistencia
INDICATOR_WINDOW   = _IND_WINDOW   # = 200, definido en indicators.py

# Máximo de velas a mantener una posición sin cerrar
# 1h × 96 velas = 4 días  |  4h × 96 velas = 16 días
MAX_HOLD_CANDLES   = 96

# Stop-loss y Take-profit: importados desde config.py (ÚNICA FUENTE DE VERDAD).
# Mismo valor que usa analyzer.py en live → paridad live/backtest garantizada.
# SL_ATR_MULT = 1.5, TP_ATR_MULT = 3.0  →  R/R = 2.0, break-even WR = 33.3%
SL_MULTIPLIER      = SL_ATR_MULT   # alias local para no romper el resto del archivo
TP_MULTIPLIER      = TP_ATR_MULT   # alias local para no romper el resto del archivo


# ─── Descarga de datos históricos ─────────────────────────────────────────────

def fetch_historical_ohlcv(
    symbol: str,
    interval: str,
    months: int,
    start_dt: datetime | None = None,
    end_dt:   datetime | None = None,
) -> pd.DataFrame | None:
    """
    Descarga datos históricos de Binance para un rango de fechas.

    Si se pasan start_dt / end_dt se usan directamente.
    Si no, calcula N meses hacia atrás desde hoy.

    Binance permite máximo 1000 velas por petición → paginamos.

    Returns:
        DataFrame con columnas: open, high, low, close, volume
        None si hubo error.
    """
    if end_dt is None:
        end_dt = datetime.now()
    if start_dt is None:
        start_dt = end_dt - timedelta(days=months * 30)

    end_ms   = int(end_dt.timestamp()   * 1000)
    start_ms = int(start_dt.timestamp() * 1000)

    all_candles   = []
    current_start = start_ms
    page          = 0

    while current_start < end_ms:
        page += 1
        params = {
            "symbol":    symbol,
            "interval":  interval,
            "startTime": current_start,
            "endTime":   end_ms,
            "limit":     1000,
        }

        try:
            resp = requests.get(f"{BINANCE_BASE}/klines", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"  ⚠️  Error descargando {symbol} página {page}: {e}")
            return None

        if not data:
            break

        all_candles.extend(data)

        # Siguiente lote: empieza 1ms después del cierre de la última vela
        last_close_time = data[-1][6]
        if last_close_time >= end_ms:
            break
        current_start = last_close_time + 1

        # Pausa para no saturar la API de Binance
        time.sleep(0.2)

    if not all_candles:
        print(f"  ⚠️  Sin datos para {symbol}")
        return None

    df = pd.DataFrame(all_candles, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp")
    return df.set_index("timestamp")[["open", "high", "low", "close", "volume"]]


# calculate_indicators_at importada desde indicators.py (no duplicada aquí).
# Garantía anti-look-ahead: ventana = df.iloc[max(0, idx-WINDOW+1) : idx+1].

# ─── Daily timeframe helper ───────────────────────────────────────────────────

def get_daily_trend_at(df_daily: pd.DataFrame | None, timestamp) -> bool:
    """
    Verifica si la tendencia DIARIA es alcista en un momento dado.
    Tendencia diaria alcista = precio > EMA20 diario.

    Esto es la confirmación multi-timeframe: antes de entrar en 4h,
    asegurarse de que el gráfico diario también está en uptrend.
    Un trader profesional SIEMPRE verifica el timeframe mayor.

    Returns:
        True si tendencia diaria es alcista (o si no hay datos diarios)
    """
    if df_daily is None or df_daily.empty:
        return True  # sin datos = no filtrar

    # Todas las velas diarias hasta esta fecha
    mask = df_daily.index <= timestamp
    if mask.sum() < 25:
        return True  # sin suficiente historia, no filtrar

    idx    = int(mask.sum())
    window = df_daily["close"].iloc[max(0, idx - 200): idx]

    if len(window) < 20:
        return True

    ema20_daily = calc_ema(window, 20).iloc[-1]
    price_daily = float(window.iloc[-1])

    return price_daily > float(ema20_daily)


# ─── Simulación de trades ─────────────────────────────────────────────────────

def run_backtest(
    df:              pd.DataFrame,
    initial_capital: float,
    threshold:       int,
    fg_history:      pd.Series | None  = None,
    symbol:          str               = "",
    is_btc:          bool              = False,
    use_trailing:    bool              = False,
    trade_from:      datetime | None   = None,
    use_breakeven:   bool              = False,
    use_macd_exit:   bool              = False,
) -> dict:
    """
    Simula las operaciones del bot sobre datos históricos.

    Lógica v3:
    - Trailing Stop:    opcional — TP fijo mejor para crypto volátil
    - Breakeven Stop:   cuando trade sube +1.5×ATR, SL se mueve a precio entrada
                        → el peor caso pasa de -1.5 ATR a 0% (breakeven)
    - MACD Exit:        salida cuando MACD cruza a negativo MIENTRAS el trade
                        está en profit → deja correr tendencias, no las corta en TP fijo
    - F&G histórico:    ajuste ±10 max al score por contexto emocional
    - ADX hard block:   bloquea mercados laterales (ya en score_crypto)
    - trade_from:       no entrar antes de esta fecha (warmup de indicadores)

    Args:
        use_breakeven:  Mover SL a breakeven cuando precio sube +1.5×ATR
        use_macd_exit:  Salir cuando MACD cruza negativo estando en profit
    """
    trades       = []
    equity_curve = []
    capital      = initial_capital

    # Estado de posición
    in_position          = False
    entry_price          = 0.0
    stop_loss            = 0.0
    take_profit          = 0.0
    entry_date           = None
    entry_idx            = 0
    entry_atr            = 0.0
    entry_score          = 0
    entry_signal         = ""
    highest_since_entry  = 0.0   # para trailing stop
    breakeven_activated  = False  # para breakeven stop

    empty_ctx = {"fear_greed": {}, "btc_dominance": {}, "funding_rates": {}}

    total_rows = len(df)

    for i in range(INDICATOR_WINDOW, total_rows):
        row  = df.iloc[i]
        date = df.index[i]

        ind = calculate_indicators_at(df, i)
        if ind is None:
            continue

        score, signal, reason = score_crypto(ind)
        close = row["close"]
        high  = row["high"]
        low   = row["low"]

        macd_hist      = ind["macd_hist"]
        macd_hist_prev = ind.get("macd_hist_prev", macd_hist)

        # ── Ajuste por Fear & Greed histórico ─────────────────────────────────
        if fg_history is not None:
            fg_adj, _ = market_context_score_adjustment(
                symbol, is_btc, empty_ctx, date=date, fg_history=fg_history
            )
            score = max(-100, min(100, score + fg_adj))
            if score >= 60:    signal = "STRONG BUY"
            elif score >= 25:  signal = "BUY"
            elif score <= -60: signal = "STRONG SELL"
            elif score <= -25: signal = "SELL"
            else:              signal = "NEUTRAL"

        # ── Trailing Stop: subir SL si el precio subió ─────────────────────────
        if in_position and use_trailing:
            if close > highest_since_entry:
                highest_since_entry = close
            new_trailing_sl = highest_since_entry - SL_MULTIPLIER * entry_atr
            if new_trailing_sl > stop_loss:
                stop_loss = new_trailing_sl

        # ── Breakeven Stop: SL → precio entrada cuando trade sube +1.5×ATR ────
        # Una vez el trade está en zona de ganancia clara, el riesgo real = 0.
        # Esto elimina las pérdidas en trades que "casi ganaron".
        if in_position and use_breakeven and not breakeven_activated:
            if high >= entry_price + 1.5 * entry_atr:
                new_sl = entry_price  # mover SL a precio de entrada (breakeven)
                if new_sl > stop_loss:
                    stop_loss = new_sl
                breakeven_activated = True

        # ── Condiciones de salida ──────────────────────────────────────────────
        if in_position:
            hold_candles = i - entry_idx
            exit_price   = None
            exit_reason  = None

            if low <= stop_loss:
                exit_price  = max(low, stop_loss)
                exit_reason = "Trailing Stop" if use_trailing else "Stop-Loss"

            elif not use_trailing and high >= take_profit:
                exit_price  = take_profit
                exit_reason = "Take-Profit"

            elif use_macd_exit and macd_hist < 0 and macd_hist_prev >= 0 and close > entry_price:
                # MACD acaba de cruzar a negativo y el trade está en profit.
                # Señal de que el momentum alcista terminó → salir y conservar ganancia.
                exit_price  = close
                exit_reason = "MACD exit (ganancia asegurada)"

            elif signal in ("SELL", "STRONG SELL") and score <= -threshold:
                exit_price  = close
                exit_reason = "Señal SELL"

            elif hold_candles >= MAX_HOLD_CANDLES:
                exit_price  = close
                exit_reason = "Timeout"

            if exit_price is not None:
                pnl_pct   = (exit_price - entry_price) / entry_price * 100
                pnl_usdt  = capital * (pnl_pct / 100)
                capital  += pnl_usdt

                trades.append({
                    "symbol":         "",
                    "entrada_fecha":  entry_date,
                    "salida_fecha":   date,
                    "entrada_precio": entry_price,
                    "salida_precio":  exit_price,
                    "stop_loss_ini":  entry_price - SL_MULTIPLIER * entry_atr,
                    "stop_loss_fin":  stop_loss,
                    "take_profit":    take_profit,
                    "razon_entrada":  f"{entry_signal} (score {entry_score})",
                    "razon_salida":   exit_reason,
                    "pnl_pct":        round(pnl_pct, 2),
                    "pnl_usdt":       round(pnl_usdt, 4),
                    "capital":        round(capital, 4),
                    "velas_abierto":  hold_candles,
                    "ganadora":       pnl_usdt > 0,
                })

                in_position         = False
                breakeven_activated = False

        # ── Señal de entrada ───────────────────────────────────────────────────
        elif score >= threshold:
            if trade_from is not None and date < trade_from:
                equity_curve.append({"fecha": date, "capital": round(capital, 4)})
                continue

            atr         = ind["atr"]
            entry_price = close
            stop_loss   = close - SL_MULTIPLIER * atr
            take_profit = close + TP_MULTIPLIER * atr
            highest_since_entry = close
            breakeven_activated = False

            in_position  = True
            entry_date   = date
            entry_idx    = i
            entry_atr    = atr
            entry_score  = score
            entry_signal = signal

        equity_curve.append({"fecha": date, "capital": round(capital, 4)})

    # Cerrar posición abierta al final del período
    if in_position:
        exit_price = df.iloc[-1]["close"]
        date       = df.index[-1]
        pnl_pct    = (exit_price - entry_price) / entry_price * 100
        pnl_usdt   = capital * (pnl_pct / 100)
        capital   += pnl_usdt

        trades.append({
            "symbol":         "",
            "entrada_fecha":  entry_date,
            "salida_fecha":   date,
            "entrada_precio": entry_price,
            "salida_precio":  exit_price,
            "stop_loss_ini":  entry_price - SL_MULTIPLIER * entry_atr,
            "stop_loss_fin":  stop_loss,
            "take_profit":    take_profit,
            "razon_entrada":  f"{entry_signal} (score {entry_score})",
            "razon_salida":   "Fin backtest",
            "pnl_pct":        round(pnl_pct, 2),
            "pnl_usdt":       round(pnl_usdt, 4),
            "capital":        round(capital, 4),
            "velas_abierto":  total_rows - 1 - entry_idx,
            "ganadora":       pnl_usdt > 0,
        })

    return {
        "trades":        trades,
        "equity_curve":  equity_curve,
        "final_capital": round(capital, 4),
    }


# ─── Estadísticas ─────────────────────────────────────────────────────────────

def calc_stats(result: dict, initial_capital: float, symbol: str) -> dict:
    """Calcula métricas de performance de un backtest."""

    trades        = result["trades"]
    final_capital = result["final_capital"]

    if not trades:
        return {
            "symbol": symbol, "total_trades": 0,
            "ganadas": 0, "perdidas": 0,
            "win_rate": 0.0, "total_return": 0.0, "total_return_pct": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0,
            "best_trade": 0.0, "worst_trade": 0.0,
            "max_drawdown": 0.0, "profit_factor": 0.0,
            "avg_hold_candles": 0, "capital_final": round(final_capital, 2),
        }

    winners = [t for t in trades if t["ganadora"]]
    losers  = [t for t in trades if not t["ganadora"]]

    win_rate      = len(winners) / len(trades) * 100
    total_return  = final_capital - initial_capital
    total_ret_pct = (final_capital / initial_capital - 1) * 100

    avg_win   = np.mean([t["pnl_pct"] for t in winners]) if winners else 0.0
    avg_loss  = np.mean([t["pnl_pct"] for t in losers])  if losers  else 0.0
    best      = max(t["pnl_pct"] for t in trades)
    worst     = min(t["pnl_pct"] for t in trades)
    avg_hold  = int(np.mean([t["velas_abierto"] for t in trades]))

    gross_profit  = sum(t["pnl_usdt"] for t in winners) if winners else 0
    gross_loss    = abs(sum(t["pnl_usdt"] for t in losers)) if losers else 0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf")

    # Máximo Drawdown desde pico de equity
    eq_values = [e["capital"] for e in result["equity_curve"]]
    max_dd    = 0.0
    if eq_values:
        peak = eq_values[0]
        for val in eq_values:
            if val > peak:
                peak = val
            dd = (peak - val) / peak * 100
            if dd > max_dd:
                max_dd = dd

    return {
        "symbol":           symbol,
        "total_trades":     len(trades),
        "ganadas":          len(winners),
        "perdidas":         len(losers),
        "win_rate":         round(win_rate, 1),
        "total_return":     round(total_return, 2),
        "total_return_pct": round(total_ret_pct, 2),
        "avg_win":          round(avg_win, 2),
        "avg_loss":         round(avg_loss, 2),
        "best_trade":       round(best, 2),
        "worst_trade":      round(worst, 2),
        "max_drawdown":     round(max_dd, 2),
        "profit_factor":    profit_factor,
        "avg_hold_candles": avg_hold,
        "capital_final":    round(final_capital, 2),
    }


# ─── Reporte en consola ───────────────────────────────────────────────────────

def print_summary(all_stats, all_trades, initial_capital, period_label, interval, threshold):
    bar = "═" * 72

    print(f"\n{bar}")
    print(f"  📊  REPORTE DE BACKTESTING")
    print(f"  Período: {period_label}  |  Timeframe: {interval}  |  Score mínimo: {threshold}")
    print(f"  Capital inicial por cripto: ${initial_capital:,.2f} USDT")
    print(f"{bar}\n")

    header = f"{'CRIPTO':<12} {'TRADES':>7} {'W/L':>6} {'WIN%':>6} {'RETORNO':>10} {'AVG WIN':>8} {'AVG LOSS':>9} {'MAX DD':>8} {'P.FACTOR':>9}"
    print(header)
    print("─" * 72)

    for s in all_stats:
        if s["total_trades"] == 0:
            print(f"  {s['symbol']:<12} sin señales")
            continue

        wl_str  = f"{s['ganadas']}/{s['perdidas']}"
        ret_str = f"{s['total_return_pct']:+.1f}%"
        dd_str  = f"{s['max_drawdown']:.1f}%"
        pf_str  = str(s['profit_factor']) if s['profit_factor'] != float('inf') else "∞"

        print(
            f"  {s['symbol']:<12}"
            f"{s['total_trades']:>6}"
            f"{wl_str:>7}"
            f"{s['win_rate']:>5.1f}%"
            f"{ret_str:>10}"
            f"{s['avg_win']:>7.2f}%"
            f"{s['avg_loss']:>8.2f}%"
            f"{dd_str:>8}"
            f"{pf_str:>9}"
        )

    print("─" * 72)

    if all_trades:
        total    = len(all_trades)
        winners  = sum(1 for t in all_trades if t["ganadora"])
        glob_wr  = winners / total * 100
        avg_w    = np.mean([t["pnl_pct"] for t in all_trades if t["ganadora"]] or [0])
        avg_l    = np.mean([t["pnl_pct"] for t in all_trades if not t["ganadora"]] or [0])
        print(f"\n  GLOBAL: {total} operaciones | Win rate: {glob_wr:.1f}% | Avg ganancia: {avg_w:+.2f}% | Avg pérdida: {avg_l:.2f}%")

    sorted_stats = sorted([s for s in all_stats if s["total_trades"] > 0],
                          key=lambda x: x["total_return_pct"], reverse=True)
    if sorted_stats:
        best  = sorted_stats[0]
        worst = sorted_stats[-1]
        print(f"\n  🏆 Mejor:  {best['symbol']:<12} {best['total_return_pct']:+.1f}%  ({best['total_trades']} trades, {best['win_rate']}% WR)")
        print(f"  💀 Peor:   {worst['symbol']:<12} {worst['total_return_pct']:+.1f}%  ({worst['total_trades']} trades, {worst['win_rate']}% WR)")

    if all_trades:
        print(f"\n  TOP 5 MEJORES TRADES:")
        for t in sorted(all_trades, key=lambda x: x["pnl_pct"], reverse=True)[:5]:
            fecha = t["entrada_fecha"].strftime("%Y-%m-%d") if hasattr(t["entrada_fecha"], "strftime") else str(t["entrada_fecha"])
            print(f"    {t['symbol']:<12} {fecha}  {t['razon_entrada']:<28}  +{t['pnl_pct']:.2f}%")

        print(f"\n  TOP 5 PEORES TRADES:")
        for t in sorted(all_trades, key=lambda x: x["pnl_pct"])[:5]:
            fecha = t["entrada_fecha"].strftime("%Y-%m-%d") if hasattr(t["entrada_fecha"], "strftime") else str(t["entrada_fecha"])
            print(f"    {t['symbol']:<12} {fecha}  {t['razon_salida']:<28}  {t['pnl_pct']:.2f}%")

    print(f"\n{bar}\n")


# ─── Guardar resultados en CSV ────────────────────────────────────────────────

def save_results(all_trades, all_stats, months):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

    if all_trades:
        trades_file = f"backtest_trades_{months}m_{timestamp}.csv"
        pd.DataFrame(all_trades).to_csv(trades_file, index=False)
        print(f"  💾 Trades guardados en: {trades_file}")

    stats_file = f"backtest_resumen_{months}m_{timestamp}.csv"
    pd.DataFrame(all_stats).to_csv(stats_file, index=False)
    print(f"  💾 Resumen guardado en:  {stats_file}\n")


# ─── Punto de entrada ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Backtest v3 — crypto + stocks, trailing stop, F&G, multi-timeframe"
    )
    parser.add_argument("--months",     type=int,   default=DEFAULT_MONTHS,
                        help=f"Meses de historial (default: {DEFAULT_MONTHS})")
    parser.add_argument("--start",      type=str,   default=None,
                        help="Fecha inicio YYYY-MM-DD  (ej: 2024-01-01)")
    parser.add_argument("--end",        type=str,   default=None,
                        help="Fecha fin   YYYY-MM-DD  (ej: 2024-06-30)")
    parser.add_argument("--capital",    type=float, default=DEFAULT_CAPITAL,
                        help=f"Capital inicial USDT (default: {DEFAULT_CAPITAL})")
    parser.add_argument("--threshold",  type=int,   default=DEFAULT_THRESHOLD,
                        help=f"Score mínimo para entrar (default: {DEFAULT_THRESHOLD})")
    parser.add_argument("--symbol",     type=str,   default=None,
                        help="Símbolo específico: BTCUSDT, AAPL, SPY...")
    parser.add_argument("--interval",   type=str,   default=TIMEFRAME,
                        help=f"Timeframe velas (default: {TIMEFRAME})")
    parser.add_argument("--assets",     type=str,   default="crypto",
                        choices=["crypto", "stocks", "all"],
                        help="Qué activos analizar: crypto, stocks, all (default: crypto)")
    parser.add_argument("--trailing",    action="store_true",
                        help="Activar trailing stop (default: TP fijo, mejor para crypto)")
    parser.add_argument("--breakeven",   action="store_true",
                        help="Mover SL a breakeven cuando trade sube +1.5×ATR")
    parser.add_argument("--macd-exit",   action="store_true",
                        help="Salir cuando MACD cruza negativo estando en profit (deja correr tendencias)")
    parser.add_argument("--no-fg",       action="store_true",
                        help="Desactivar filtro Fear & Greed histórico")
    args = parser.parse_args()

    use_trailing   = args.trailing
    use_breakeven  = args.breakeven
    use_macd_exit  = args.macd_exit
    use_fg         = not args.no_fg

    # ── Parsear fechas ──────────────────────────────────────────────────────────
    start_dt = None
    end_dt   = None
    if args.start:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d")
    if args.end:
        end_dt = datetime.strptime(args.end, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

    if start_dt:
        end_label    = end_dt.strftime("%Y-%m-%d") if end_dt else "hoy"
        period_label = f"{start_dt.strftime('%Y-%m-%d')} → {end_label}"
    else:
        period_label = f"{args.months} meses"

    # ── Construir lista de activos ──────────────────────────────────────────────
    from stocks_fetcher import STOCKS_CORE, get_stock_ohlcv, get_stock_daily_ohlcv
    from fetcher import get_daily_ohlcv

    all_assets = []

    if args.symbol:
        sym = args.symbol.upper()
        # Buscar en crypto primero, luego en stocks
        match = ([c for c in CRYPTOS if c["symbol"] == sym] or
                 [s for s in STOCKS_CORE if s["symbol"] == sym] or
                 [{"symbol": sym, "name": sym}])
        all_assets = match
    else:
        if args.assets in ("crypto", "all"):
            all_assets.extend(CRYPTOS)
        if args.assets in ("stocks", "all"):
            all_assets.extend(STOCKS_CORE)

    # ── Fear & Greed histórico ──────────────────────────────────────────────────
    fg_history = None
    if use_fg:
        print(f"\n📡 Descargando Fear & Greed histórico...", end=" ", flush=True)
        fg_history = get_historical_fear_greed(days=800)
        print("✓" if fg_history is not None else "✗ (usando neutral)")

    print(f"\n🔍 Período: {period_label} | Assets: {args.assets}")
    print(f"   Trailing: {'ON' if use_trailing else 'OFF'} | "
          f"Breakeven: {'ON' if use_breakeven else 'OFF'} | "
          f"MACD exit: {'ON' if use_macd_exit else 'OFF'} | "
          f"F&G: {'ON' if use_fg and fg_history is not None else 'OFF'}")
    print(f"   Capital: ${args.capital:,.2f} | Score mínimo: {args.threshold}\n")

    all_trades = []
    all_stats  = []

    for i, asset in enumerate(all_assets):
        symbol   = asset["symbol"]
        name     = asset.get("name", symbol)
        is_stock = not symbol.endswith("USDT")
        is_btc   = symbol == "BTCUSDT"

        print(f"  [{i+1}/{len(all_assets)}] {name} ({symbol})...", end=" ", flush=True)

        # ── Descargar OHLCV principal ───────────────────────────────────────────
        if is_stock:
            interval_stock = "1h"  # 1h para acciones ≈ 4h en crypto

            # Para acciones con fecha de inicio fija, agregar warmup extra:
            # necesitamos INDICATOR_WINDOW candles de calentamiento antes de
            # la fecha de inicio. Con datos diarios (1d), 200 días extra ≈ 10 meses.
            if start_dt:
                warmup_start = start_dt - timedelta(days=300)  # ~210 días de trading
            else:
                warmup_start = None

            df = get_stock_ohlcv(symbol, interval_stock, args.months, warmup_start or start_dt, end_dt)
        else:
            df = fetch_historical_ohlcv(symbol, args.interval, args.months, start_dt, end_dt)

        if df is None or len(df) < INDICATOR_WINDOW + 10:
            cant = len(df) if df is not None else 0
            print(f"✗ (datos insuficientes: {cant} velas)")
            all_stats.append({
                "symbol": symbol, "asset_type": "stock" if is_stock else "crypto",
                "total_trades": 0, "ganadas": 0, "perdidas": 0,
                "win_rate": 0.0, "total_return": 0.0, "total_return_pct": 0.0,
                "avg_win": 0.0, "avg_loss": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
                "max_drawdown": 0.0, "profit_factor": 0.0,
                "avg_hold_candles": 0, "capital_final": args.capital,
            })
            continue

        print(f"{len(df)} velas. Simulando...", end=" ", flush=True)

        result = run_backtest(
            df             = df,
            initial_capital = args.capital,
            threshold      = args.threshold,
            fg_history     = fg_history if use_fg else None,
            symbol         = symbol,
            is_btc         = is_btc,
            use_trailing   = use_trailing,
            trade_from     = start_dt,
            use_breakeven  = use_breakeven,
            use_macd_exit  = use_macd_exit,
        )

        for trade in result["trades"]:
            trade["symbol"]     = symbol
            trade["asset_type"] = "stock" if is_stock else "crypto"

        stats = calc_stats(result, args.capital, symbol)
        stats["asset_type"] = "stock" if is_stock else "crypto"
        print(f"✓  ({stats['total_trades']} trades, {stats['win_rate']}% WR, {stats['total_return_pct']:+.1f}%)")

        all_trades.extend(result["trades"])
        all_stats.append(stats)

    print_summary(all_stats, all_trades, args.capital, period_label, args.interval, args.threshold)
    save_results(all_trades, all_stats, period_label.replace(" → ", "_").replace("-", ""))


if __name__ == "__main__":
    main()
