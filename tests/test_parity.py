"""
test_parity.py — Paridad live/backtest.

Verifica que los mismos indicadores y multiplicadores SL/TP se calculen
de forma idéntica en el path live (calculate_indicators) y en el path
de backtest (calculate_indicators_at en la última barra).

Regla de oro: si estos tests fallan, el backtest no representa lo que
corre en producción.
"""

import pytest
import numpy as np
from tests.conftest import make_ohlcv

from indicators import calculate_indicators, calculate_indicators_at, INDICATOR_WINDOW
from config import SL_ATR_MULT, TP_ATR_MULT


class TestIndicatorParity:
    """calculate_indicators == calculate_indicators_at en la última barra."""

    def _check_parity(self, df):
        """Helper: compara live vs backtest en la última barra disponible."""
        last_idx = len(df) - 1
        ind_live    = calculate_indicators(df)
        ind_backtest = calculate_indicators_at(df, last_idx)

        assert ind_backtest is not None, "calculate_indicators_at devolvió None"

        keys = [
            "price", "rsi", "rsi_prev", "macd_hist", "macd_hist_prev",
            "ema20", "ema50", "ema200", "bb_pct", "atr", "atr_pct",
            "volume_ratio", "adx", "plus_di", "minus_di",
        ]
        for key in keys:
            live_val = ind_live[key]
            bt_val   = ind_backtest[key]
            assert abs(live_val - bt_val) < 1e-9, (
                f"Desajuste en '{key}': live={live_val} backtest={bt_val}"
            )

    def test_parity_uptrend(self, df_uptrend):
        self._check_parity(df_uptrend)

    def test_parity_flat(self, df_flat):
        self._check_parity(df_flat)

    def test_parity_downtrend(self, df_downtrend):
        self._check_parity(df_downtrend)

    def test_parity_mid_series(self, df_uptrend):
        """Paridad no solo en el final sino en barra intermedia."""
        df = df_uptrend
        idx = INDICATOR_WINDOW + 20  # barra intermedia con suficiente historia
        window = df.iloc[:idx + 1]   # ventana hasta esa barra (inclusive)

        ind_live    = calculate_indicators(window)
        ind_backtest = calculate_indicators_at(df, idx)

        assert ind_backtest is not None
        assert abs(ind_live["price"] - ind_backtest["price"]) < 1e-9


class TestSLTPMultipliers:
    """Los multiplicadores SL/TP deben ser iguales en config, analyzer y backtester."""

    def test_config_values(self):
        assert SL_ATR_MULT == 1.5, f"SL_ATR_MULT debe ser 1.5, es {SL_ATR_MULT}"
        assert TP_ATR_MULT == 3.0, f"TP_ATR_MULT debe ser 3.0, es {TP_ATR_MULT}"

    def test_backtester_aliases(self):
        import backtester
        assert backtester.SL_MULTIPLIER == SL_ATR_MULT, (
            f"backtester.SL_MULTIPLIER ({backtester.SL_MULTIPLIER}) "
            f"!= config.SL_ATR_MULT ({SL_ATR_MULT})"
        )
        assert backtester.TP_MULTIPLIER == TP_ATR_MULT, (
            f"backtester.TP_MULTIPLIER ({backtester.TP_MULTIPLIER}) "
            f"!= config.TP_ATR_MULT ({TP_ATR_MULT})"
        )

    def test_analyzer_uses_config(self, df_uptrend):
        """analyze_crypto debe usar SL_ATR_MULT y TP_ATR_MULT desde config."""
        from analyzer import analyze_crypto, calculate_indicators
        from config import SL_ATR_MULT, TP_ATR_MULT

        ind   = calculate_indicators(df_uptrend)
        price = ind["price"]
        atr   = ind["atr"]

        result = analyze_crypto({
            "crypto": {"symbol": "BTCUSDT", "name": "Bitcoin"},
            "ohlcv":  df_uptrend,
            "stats":  {"price": price, "change_pct": 0.0, "volume_usdt": 0.0},
        })

        expected_sl = round(price - SL_ATR_MULT * atr, 6)
        expected_tp = round(price + TP_ATR_MULT * atr, 6)

        assert abs(result["stop_loss"]   - expected_sl) < 1e-5, (
            f"SL incorrecto: {result['stop_loss']} != {expected_sl}"
        )
        assert abs(result["take_profit"] - expected_tp) < 1e-5, (
            f"TP incorrecto: {result['take_profit']} != {expected_tp}"
        )
