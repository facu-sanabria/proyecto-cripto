"""
test_close_notification.py — verifica la notificación de cierre (Fix 2).

- _close_position devuelve el trade cerrado (para notificar fuera del lock).
- _format_close_msg arma un mensaje correcto WIN/LOSS con PnL neto.
- _send_close_alert llama a send_telegram exactamente una vez por cierre.

Nota: main.py es importable porque la reconfiguración de stdout vive en
_force_utf8_streams() (se llama desde main(), no al importar).
"""

import datetime as dt
import pytest

import main


@pytest.fixture(autouse=True)
def _reset_state():
    """Aísla el estado compartido entre tests."""
    with main._lock:
        main._state["positions"].clear()
        main._state["closed_trades"].clear()
    yield
    with main._lock:
        main._state["positions"].clear()
        main._state["closed_trades"].clear()


def _open(sym="BTCUSDT", entry=100.0, tp=103.0, sl=98.5, typ="crypto"):
    main._state["positions"][sym] = {
        "sym": sym, "name": sym.replace("USDT", ""), "type": typ,
        "entry": entry, "sl": sl, "tp": tp, "sl_pct": 1.5, "tp_pct": 3.0,
        "ts_entry": dt.datetime(2024, 1, 1, 10, 0, 0),
        "ts_entry_unix": 1704103200.0, "tf": "5m",
    }


class TestClosePositionReturnsTrade:
    def test_returns_trade_dict(self):
        _open()
        trade = main._close_position("BTCUSDT", 103.0, "Take-Profit", dt.datetime(2024, 1, 1, 11, 0))
        assert trade is not None
        assert trade["result"] == "WIN"
        assert "BTCUSDT" not in main._state["positions"]
        assert main._state["closed_trades"][-1] is trade

    def test_returns_none_when_no_position(self):
        assert main._close_position("NOPE", 1.0, "x", None) is None

    def test_win_loss_classification_net_of_costs(self):
        # exit == entry → bruto 0%, neto = -ROUND_TRIP → LOSS
        _open(sym="ETHUSDT", entry=100.0)
        trade = main._close_position("ETHUSDT", 100.0, "Take-Profit", None)
        assert trade["result"] == "LOSS"
        assert trade["pnl_net"] == pytest.approx(-main.ROUND_TRIP_COST_PCT, abs=1e-6)


class TestFormatCloseMsg:
    def test_win_message_contents(self):
        trade = {
            "sym": "BTCUSDT", "name": "BTC", "type": "crypto",
            "entry": 100.0, "exit": 103.0, "pnl_gross": 3.0, "pnl_net": 2.70,
            "result": "WIN", "reason": "Take-Profit", "tf": "5m",
        }
        msg = main._format_close_msg(trade)
        assert "CIERRE WIN" in msg
        assert "+2.70%" in msg
        assert "BTC" in msg
        assert "Take-Profit" in msg

    def test_loss_message_contents(self):
        trade = {
            "sym": "SOLUSDT", "name": "SOL", "type": "crypto",
            "entry": 100.0, "exit": 98.5, "pnl_gross": -1.5, "pnl_net": -1.80,
            "result": "LOSS", "reason": "Stop-Loss", "tf": "5m",
        }
        msg = main._format_close_msg(trade)
        assert "CIERRE LOSS" in msg
        assert "-1.80%" in msg
        assert "Stop-Loss" in msg


class TestCooldown:
    """Fix 3: mark_notified activa el cooldown de should_notify."""

    def test_should_notify_true_then_false_after_mark(self):
        import notifier
        sym = "BTCUSDT_TEST"
        notifier._last_notified.pop(sym, None)
        assert notifier.should_notify(sym) is True
        notifier.mark_notified(sym)
        assert notifier.should_notify(sym) is False
        notifier._last_notified.pop(sym, None)


class TestSendCloseAlert:
    def test_sends_once_per_close(self, monkeypatch):
        calls = []
        monkeypatch.setattr(main, "send_telegram", lambda m: calls.append(m) or True)

        trade = {
            "sym": "BTCUSDT", "name": "BTC", "type": "crypto",
            "entry": 100.0, "exit": 103.0, "pnl_gross": 3.0, "pnl_net": 2.70,
            "result": "WIN", "reason": "Take-Profit", "tf": "5m",
        }
        main._send_close_alert(trade)
        assert len(calls) == 1
        assert "CIERRE WIN" in calls[0]

    def test_no_send_when_trade_none(self, monkeypatch):
        calls = []
        monkeypatch.setattr(main, "send_telegram", lambda m: calls.append(m) or True)
        main._send_close_alert(None)
        assert calls == []
