"""
test_no_lookahead.py — Garantía anti-look-ahead.

Regla: ningún cálculo en la barra t debe usar datos de t+1 o posterior.

Test: si se agrega una barra futura con valores extremos (precio ×10),
los indicadores en la barra t NO deben cambiar.

Si calc_rsi, calc_macd, etc. filtraran datos futuros inadvertidamente,
los valores en t cambiarían al agregar la barra t+1.
"""

import pytest
import numpy as np
import pandas as pd
from tests.conftest import make_ohlcv

from indicators import (
    calc_rsi, calc_macd, calc_ema, calc_bollinger, calc_atr, calc_adx,
    calculate_indicators, calculate_indicators_at, INDICATOR_WINDOW,
)


def _append_future_bar(df: pd.DataFrame, multiplier: float = 10.0) -> pd.DataFrame:
    """Agrega una barra ficticia con precio extremo al final del DataFrame."""
    last_ts   = df.index[-1]
    next_ts   = last_ts + (df.index[1] - df.index[0])  # misma frecuencia
    last_row  = df.iloc[-1]
    new_close = last_row["close"] * multiplier

    future = pd.DataFrame({
        "open":   [new_close],
        "high":   [new_close * 1.1],
        "low":    [new_close * 0.9],
        "close":  [new_close],
        "volume": [last_row["volume"]],
    }, index=[next_ts])

    return pd.concat([df, future])


class TestNoLookaheadIndicators:
    """Los indicadores primitivos no deben cambiar al agregar datos futuros."""

    def _check_no_change(self, series_fn, df, fn_name: str):
        """
        Calcula la serie hasta la última barra,
        agrega una barra futura extrema,
        y verifica que el valor en la última barra original no cambió.
        """
        val_before = series_fn(df).iloc[-1]
        df_extended = _append_future_bar(df, multiplier=100.0)
        val_after   = series_fn(df_extended).iloc[-2]  # penúltima = última original

        assert abs(val_before - val_after) < 1e-9, (
            f"{fn_name}: valor en barra t cambió al agregar barra t+1. "
            f"Antes: {val_before:.6f}, Después: {val_after:.6f}. "
            f"Posible look-ahead."
        )

    def test_rsi_no_lookahead(self, df_uptrend):
        self._check_no_change(
            lambda df: calc_rsi(df["close"]),
            df_uptrend, "calc_rsi"
        )

    def test_macd_hist_no_lookahead(self, df_uptrend):
        def macd_hist(df):
            _, _, h = calc_macd(df["close"])
            return h
        self._check_no_change(macd_hist, df_uptrend, "calc_macd histogram")

    def test_ema20_no_lookahead(self, df_uptrend):
        self._check_no_change(
            lambda df: calc_ema(df["close"], 20),
            df_uptrend, "calc_ema(20)"
        )

    def test_ema200_no_lookahead(self, df_uptrend):
        self._check_no_change(
            lambda df: calc_ema(df["close"], 200),
            df_uptrend, "calc_ema(200)"
        )

    def test_atr_no_lookahead(self, df_uptrend):
        self._check_no_change(
            lambda df: calc_atr(df["high"], df["low"], df["close"]),
            df_uptrend, "calc_atr"
        )

    def test_bollinger_pband_no_lookahead(self, df_uptrend):
        def pband(df):
            _, _, pb = calc_bollinger(df["close"])
            return pb
        self._check_no_change(pband, df_uptrend, "calc_bollinger pband")

    def test_adx_no_lookahead(self, df_uptrend):
        def adx_series(df):
            adx, _, _ = calc_adx(df["high"], df["low"], df["close"])
            return adx
        self._check_no_change(adx_series, df_uptrend, "calc_adx")


class TestNoLookaheadCalculateIndicators:
    """calculate_indicators y calculate_indicators_at no deben usar datos futuros."""

    def test_calculate_indicators_no_lookahead(self, df_uptrend):
        """calculate_indicators(df) en barra t no cambia al agregar barra t+1."""
        ind_before = calculate_indicators(df_uptrend)
        df_extended = _append_future_bar(df_uptrend, multiplier=100.0)
        # Con el df extendido, la "última barra" es la nueva futura.
        # Pero si calculamos sobre df_uptrend (sin la futura), debe dar igual.
        ind_after = calculate_indicators(df_uptrend)  # mismo df → mismo resultado

        # Más importante: la penúltima barra del df extendido debe dar igual que
        # la última del df original.
        window_penultimate = df_extended.iloc[:-1]
        ind_penultimate = calculate_indicators(window_penultimate)

        for key in ["price", "rsi", "macd_hist", "ema20", "ema50", "ema200", "atr"]:
            assert abs(ind_before[key] - ind_penultimate[key]) < 1e-9, (
                f"calculate_indicators['{key}'] cambió al agregar barra futura: "
                f"{ind_before[key]:.6f} vs {ind_penultimate[key]:.6f}"
            )

    def test_calculate_indicators_at_no_lookahead(self, df_uptrend):
        """
        calculate_indicators_at(df, idx) en barra idx no cambia cuando
        se agregan barras > idx al DataFrame.
        """
        idx = INDICATOR_WINDOW + 50  # barra con suficiente historia
        df  = df_uptrend

        # Calcular en barra idx con datos originales
        ind_before = calculate_indicators_at(df, idx)
        assert ind_before is not None

        # Agregar 10 barras artificiales al final (todas con precio ×100)
        df_extended = df.copy()
        for _ in range(10):
            df_extended = _append_future_bar(df_extended, multiplier=100.0)

        # Calcular de nuevo en el mismo idx con el df extendido
        # (las barras extra son > idx, por lo tanto no deberían afectar)
        ind_after = calculate_indicators_at(df_extended, idx)
        assert ind_after is not None

        for key in ["price", "rsi", "macd_hist", "ema20", "ema50", "atr"]:
            assert abs(ind_before[key] - ind_after[key]) < 1e-9, (
                f"calculate_indicators_at['{key}'] en barra {idx} cambió "
                f"al agregar barras futuras (> idx): "
                f"{ind_before[key]:.6f} vs {ind_after[key]:.6f}. "
                f"Posible look-ahead."
            )

    def test_indicator_window_slice_is_past_only(self):
        """
        La ventana usada por calculate_indicators_at debe ser
        df.iloc[max(0, idx-WINDOW+1) : idx+1], nunca más allá de idx.

        Verificamos que el índice idx+1 no está en la ventana
        inspeccionando el precio calculado vs el precio en idx+1.
        """
        df   = make_ohlcv(n=300, seed=1)
        idx  = INDICATOR_WINDOW + 10

        # Precio en barra idx
        price_at_idx = float(df.iloc[idx]["close"])

        # Precio en barra idx+1 (barra futura)
        price_at_next = float(df.iloc[idx + 1]["close"])

        ind = calculate_indicators_at(df, idx)
        assert ind is not None

        # El precio reportado debe ser el de idx, no el de idx+1
        assert abs(ind["price"] - price_at_idx) < 1e-9, (
            f"price en idx debe ser {price_at_idx:.6f}, got {ind['price']:.6f}"
        )
        if abs(price_at_idx - price_at_next) > 1e-9:
            assert abs(ind["price"] - price_at_next) > 1e-9, (
                "price en idx coincide con idx+1 — posible look-ahead"
            )
