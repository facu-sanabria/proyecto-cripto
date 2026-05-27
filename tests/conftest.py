"""
conftest.py — Fixtures compartidos para los tests del bot.

Genera DataFrames sintéticos deterministas para evitar llamadas a APIs externas.
Todos los tests son offline — no requieren red ni Binance.
"""

import pandas as pd
import numpy as np
import pytest


def make_ohlcv(n: int = 300, base_price: float = 100.0, trend: float = 0.001,
               seed: int = 42) -> pd.DataFrame:
    """
    Genera n velas OHLCV sintéticas con tendencia alcista suave.

    Args:
        n:          Número de velas.
        base_price: Precio inicial.
        trend:      Retorno por vela (e.g. 0.001 = +0.1% por vela).
        seed:       Semilla para reproducibilidad.

    Returns:
        DataFrame con columnas open, high, low, close, volume.
        Index: DatetimeIndex en 4h comenzando en 2024-01-01.
    """
    rng = np.random.default_rng(seed)
    closes = [base_price]
    for _ in range(n - 1):
        r = 1 + trend + rng.normal(0, 0.005)
        closes.append(closes[-1] * r)
    closes = np.array(closes)

    noise = rng.uniform(0, 0.002, n)
    highs  = closes * (1 + noise)
    lows   = closes * (1 - noise)
    opens  = np.roll(closes, 1)
    opens[0] = base_price
    volumes = rng.uniform(1000, 5000, n)

    idx = pd.date_range("2024-01-01", periods=n, freq="4h")
    return pd.DataFrame({
        "open":   opens,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": volumes,
    }, index=idx)


def make_price_series(n: int = 300, base: float = 100.0, trend: float = 0.001,
                      seed: int = 42) -> pd.Series:
    """Retorna solo la serie de closes del make_ohlcv correspondiente."""
    return make_ohlcv(n=n, base_price=base, trend=trend, seed=seed)["close"]


@pytest.fixture
def df_uptrend():
    """300 velas 4h con tendencia alcista."""
    return make_ohlcv(n=300, trend=0.002)


@pytest.fixture
def df_flat():
    """300 velas 4h laterales (sin tendencia)."""
    return make_ohlcv(n=300, trend=0.0, seed=99)


@pytest.fixture
def df_downtrend():
    """300 velas 4h con tendencia bajista."""
    return make_ohlcv(n=300, trend=-0.002, seed=7)
