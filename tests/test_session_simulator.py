"""
test_session_simulator.py — Simulador de sesión (test de fills por posición).

Dado una serie de precios sintética:
- Si el precio toca TP → WIN con el PnL correcto
- Si el precio toca SL → LOSS con el PnL correcto
- Si toca ambos en la misma vela → LOSS (SL tiene prioridad, worst-case)
- Si no toca ninguno → posición queda OPEN (no se cierra)
- Verifica el orden del toque (primera vela que toca)

Prueba la lógica de _check_crypto_positions del simulador de sesión,
replicando el algoritmo de forma offline (sin red).
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


# ─── Réplica offline del algoritmo de simulación ─────────────────────────────

def ts_to_unix(ts) -> int:
    """
    Convierte un pandas Timestamp (naive) a Unix segundos UTC.

    pd.Timestamp.timestamp() usa hora LOCAL para naive datetimes (bug timezone).
    pd.Timestamp.value es siempre nanosegundos desde epoch UTC → correcto.
    """
    return int(ts.value) // 1_000_000_000


def simulate_fill(df: pd.DataFrame, entry_unix: float,
                  sl_price: float, tp_price: float):
    """
    Réplica del algoritmo de _check_crypto_positions en main.py.

    Busca en velas post-entrada la primera que toca SL o TP.
    SL tiene prioridad cuando ambos se tocan en la misma vela.

    Args:
        df:          DataFrame OHLCV con index DatetimeIndex (UTC-naive).
        entry_unix:  Unix timestamp UTC de la entrada (usar ts_to_unix()).
        sl_price:    Precio de stop-loss absoluto.
        tp_price:    Precio de take-profit absoluto.

    Returns:
        ("Stop-Loss", price, ts) | ("Take-Profit", price, ts) | None

    Nota: en pandas 3.x, df.index.astype("int64") devuelve MICROsegundos (µs),
    no nanosegundos. Dividir por 1_000_000 → segundos UTC.
    pd.Timestamp.value sigue siendo nanosegundos → dividir por 1_000_000_000.
    NUNCA usar pd.Timestamp.timestamp() para entry_unix — devuelve hora local.
    """
    df_unix = df.index.astype("int64") // 1_000_000
    post    = df[df_unix > entry_unix]

    for ts, row in post.iterrows():
        sl_hit = row["low"]  <= sl_price
        tp_hit = row["high"] >= tp_price
        if sl_hit:  # SL prioridad worst-case
            return ("Stop-Loss",   sl_price, ts)
        elif tp_hit:
            return ("Take-Profit", tp_price, ts)
    return None


def make_fill_df(prices: list, entry_time: datetime = None):
    """
    Crea un DataFrame OHLCV donde high=close=price y low=price para
    simular velas con precios conocidos. Útil para tests de fill.

    prices: lista de floats, uno por vela.
    """
    if entry_time is None:
        entry_time = datetime(2024, 1, 1, 0, 0, 0)
    idx = pd.date_range(entry_time, periods=len(prices), freq="5min")
    close  = np.array(prices, dtype=float)
    # high y low con pequeño spread para simular movimiento intrabar
    high   = close * 1.001
    low    = close * 0.999
    return pd.DataFrame({
        "open":   close,
        "high":   high,
        "low":    low,
        "close":  close,
        "volume": np.ones(len(prices)) * 1000,
    }, index=idx)


# ─── Constantes de costos (deben coincidir con main.py) ──────────────────────

COMMISSION_PCT      = 0.10
SLIPPAGE_PCT        = 0.05
ROUND_TRIP_COST_PCT = (COMMISSION_PCT + SLIPPAGE_PCT) * 2   # = 0.30


class TestTPHit:
    """Escenario: precio sube hasta TP — debe reportar WIN."""

    def test_tp_hit_second_candle(self):
        """Precio neutro en vela 1, sube al TP en vela 2."""
        entry_price = 100.0
        sl_price    = 98.5   # -1.5%
        tp_price    = 103.0  # +3.0%

        # Vela 0: igual que entry (no toca nada)
        # Vela 1: sube a 103.5 (toca TP)
        prices = [100.0, 103.5]
        df     = make_fill_df(prices)

        # entry_unix: un segundo ANTES de la primera vela
        entry_unix = ts_to_unix(df.index[0]) - 1

        result = simulate_fill(df, entry_unix, sl_price, tp_price)

        assert result is not None, "Debería haber un fill"
        reason, fill_px, ts = result
        assert reason   == "Take-Profit",  f"Esperaba TP, got {reason}"
        assert fill_px  == tp_price,       f"Fill price {fill_px} != TP {tp_price}"
        assert ts       == df.index[1],    f"Fill en vela incorrecta: {ts}"

        # Verificar PnL neto
        pnl_gross = (fill_px - entry_price) / entry_price * 100
        pnl_net   = pnl_gross - ROUND_TRIP_COST_PCT
        assert pnl_net  > 0, f"PnL neto {pnl_net:.3f}% debe ser positivo en WIN"
        assert abs(pnl_gross - 3.0) < 0.01, f"PnL bruto {pnl_gross:.3f}% != 3.0%"

    def test_tp_hit_first_candle(self):
        """Precio sube al TP en la primera vela post-entrada."""
        entry_price = 100.0
        tp_price    = 103.0

        prices = [103.5]  # una sola vela que toca TP
        df     = make_fill_df(prices)
        entry_unix = ts_to_unix(df.index[0]) - 1

        result = simulate_fill(df, entry_unix, 98.5, tp_price)
        assert result is not None
        assert result[0] == "Take-Profit"


class TestSLHit:
    """Escenario: precio cae hasta SL — debe reportar LOSS."""

    def test_sl_hit_second_candle(self):
        """Precio neutro en vela 1, cae al SL en vela 2."""
        entry_price = 100.0
        sl_price    = 98.5
        tp_price    = 103.0

        prices = [100.0, 98.0]  # vela 2: low=98*0.999 < 98.5 → SL hit
        df     = make_fill_df(prices)
        entry_unix = ts_to_unix(df.index[0]) - 1

        result = simulate_fill(df, entry_unix, sl_price, tp_price)

        assert result is not None
        reason, fill_px, ts = result
        assert reason   == "Stop-Loss",  f"Esperaba SL, got {reason}"
        assert fill_px  == sl_price,     f"Fill price {fill_px} != SL {sl_price}"
        assert ts       == df.index[1]

        pnl_gross = (fill_px - entry_price) / entry_price * 100
        pnl_net   = pnl_gross - ROUND_TRIP_COST_PCT
        assert pnl_net  < 0, f"PnL neto {pnl_net:.3f}% debe ser negativo en LOSS"

    def test_sl_priority_over_tp(self):
        """
        Cuando low <= SL y high >= TP en la misma vela:
        SL tiene prioridad (worst-case conservador).
        """
        entry_price = 100.0
        sl_price    = 98.5
        tp_price    = 103.0

        # Vela con rango amplio que toca ambos
        idx    = pd.date_range("2024-01-01", periods=1, freq="5min")
        df     = pd.DataFrame({
            "open":   [100.0],
            "high":   [104.0],   # toca TP
            "low":    [98.0],    # toca SL
            "close":  [101.0],
            "volume": [1000.0],
        }, index=idx)

        entry_unix = ts_to_unix(idx[0]) - 1
        result = simulate_fill(df, entry_unix, sl_price, tp_price)

        assert result is not None
        assert result[0] == "Stop-Loss", (
            "SL debe tener prioridad sobre TP cuando ambos se tocan en la misma vela"
        )


class TestOpenPosition:
    """Escenario: precio no toca SL ni TP — posición queda OPEN."""

    def test_no_fill_when_price_range_neutral(self):
        """Precio se mueve entre SL y TP durante 10 velas → OPEN."""
        entry_price = 100.0
        sl_price    = 98.5
        tp_price    = 103.0

        # Precios entre 99 y 102: nunca tocan SL ni TP
        prices = [99.5, 100.2, 101.0, 100.8, 101.5,
                  100.0, 99.8,  100.5, 101.2, 102.5]
        df     = make_fill_df(prices)
        entry_unix = ts_to_unix(df.index[0]) - 1

        result = simulate_fill(df, entry_unix, sl_price, tp_price)
        assert result is None, f"No debería haber fill, got {result}"

    def test_no_fill_before_entry(self):
        """Velas anteriores a la entrada no cuentan para el fill."""
        entry_price = 100.0
        sl_price    = 98.5
        tp_price    = 103.0

        # 5 velas pre-entrada que tocarían SL, luego 5 velas neutras
        all_prices = [97.0, 97.5, 98.0, 98.3, 98.4,   # tocarían SL
                      100.0, 100.1, 100.2, 100.3, 100.4]  # post-entrada: neutral
        df = make_fill_df(all_prices)

        # Entrada después de las primeras 5 velas
        entry_unix = ts_to_unix(df.index[4])  # exactamente al cierre de vela 4 (UTC-safe)

        result = simulate_fill(df, entry_unix, sl_price, tp_price)
        assert result is None, (
            "Las velas pre-entrada no deben causar fill"
        )


class TestFillOrder:
    """Verifica que el fill ocurre en la PRIMERA vela que toca, no en la última."""

    def test_tp_hit_on_first_touch(self):
        """Si hay múltiples velas que tocan TP, el fill es en la primera."""
        entry_price = 100.0
        sl_price    = 98.5
        tp_price    = 103.0

        # Velas: neutral, TP hit, neutral, TP hit de nuevo
        prices = [101.0, 103.5, 101.5, 104.0]
        df     = make_fill_df(prices)
        entry_unix = ts_to_unix(df.index[0]) - 1

        result = simulate_fill(df, entry_unix, sl_price, tp_price)
        assert result is not None
        assert result[2] == df.index[1], (
            f"Fill debe ser en vela 1 (primer toque), got {result[2]}"
        )

    def test_sl_before_tp(self):
        """Si SL se toca antes que TP, el resultado es LOSS aunque TP se toque después."""
        entry_price = 100.0
        sl_price    = 98.5
        tp_price    = 103.0

        # Vela 0: neutral. Vela 1: SL hit. Vela 2: TP hit.
        prices = [100.0, 98.0, 104.0]
        df     = make_fill_df(prices)
        entry_unix = ts_to_unix(df.index[0]) - 1

        result = simulate_fill(df, entry_unix, sl_price, tp_price)
        assert result is not None
        assert result[0] == "Stop-Loss",  f"SL ocurre antes, got {result[0]}"
        assert result[2] == df.index[1],  f"Fill debe ser en vela 1, got {result[2]}"


class TestPnLCalculation:
    """Verifica que el PnL neto descuenta correctamente costos."""

    def test_pnl_net_deducts_round_trip(self):
        """PnL neto = PnL bruto - ROUND_TRIP_COST_PCT."""
        entry_price = 100.0
        tp_price    = 103.0
        expected_pnl_gross = (tp_price - entry_price) / entry_price * 100  # 3.0%
        expected_pnl_net   = expected_pnl_gross - ROUND_TRIP_COST_PCT       # 2.70%

        assert abs(expected_pnl_net - 2.70) < 0.01, (
            f"PnL neto con TP 3% debería ser ~2.70%, got {expected_pnl_net:.3f}%"
        )

    def test_pnl_loss_net(self):
        """PnL neto en LOSS incluye los costos (pérdida mayor que el bruto)."""
        entry_price = 100.0
        sl_price    = 98.5
        pnl_gross   = (sl_price - entry_price) / entry_price * 100  # -1.5%
        pnl_net     = pnl_gross - ROUND_TRIP_COST_PCT                 # -1.80%

        assert pnl_net < pnl_gross, "PnL neto en LOSS debe ser peor que el bruto"
        assert abs(pnl_net - (-1.80)) < 0.01, (
            f"PnL neto LOSS: esperaba -1.80%, got {pnl_net:.3f}%"
        )

    def test_breakeven_requires_covering_costs(self):
        """Un trade que cierra exactamente en entry tiene PnL neto = -ROUND_TRIP."""
        entry_price = 100.0
        exit_price  = 100.0
        pnl_gross   = 0.0
        pnl_net     = pnl_gross - ROUND_TRIP_COST_PCT
        assert pnl_net == -ROUND_TRIP_COST_PCT
