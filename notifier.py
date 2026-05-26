# ══════════════════════════════════════════════════════════════════════════════
# notifier.py — Notificaciones Telegram para señales de trading
#
# Cuando el bot detecta un STRONG BUY, te manda un mensaje a Telegram
# con precio, stop-loss, take-profit y por qué entró.
#
# Setup:
#   1. Hablar con @BotFather en Telegram → crear bot → copiar token
#   2. Hablar con @userinfobot → te da tu chat_id
#   3. Poner ambos en .env:
#        TELEGRAM_BOT_TOKEN=123456:ABC-...
#        TELEGRAM_CHAT_ID=987654321
#   4. Ejecutar:  python notifier.py  (envía mensaje de prueba)
# ══════════════════════════════════════════════════════════════════════════════

import sys
import os
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

# Fix encoding Windows — necesario para emojis en consola
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv(override=True)  # override=True fuerza recarga aunque ya estén en env

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Cooldown por activo: no re-notificar el mismo símbolo dentro de N segundos
# 4h × 3600 = 14400 seg → evita spam si el bot corre cada 5 min
NOTIFY_COOLDOWN_SEC = 4 * 3600

# Diccionario en memoria: {symbol: timestamp_último_aviso}
_last_notified: dict[str, float] = {}


# ─── Envío básico a Telegram ──────────────────────────────────────────────────

def send_telegram(message: str) -> bool:
    """
    Envía un mensaje al chat configurado en .env.

    Returns:
        True si llegó OK, False si hubo error o no está configurado.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("  ⚠️  Telegram no configurado (revisar .env)")
        return False

    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "HTML",
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if not resp.ok:
            print(f"  ⚠️  Telegram error {resp.status_code}: {resp.text[:100]}")
        return resp.ok
    except requests.RequestException as e:
        print(f"  ⚠️  Telegram no disponible: {e}")
        return False


# ─── Formateo del mensaje ─────────────────────────────────────────────────────

def format_signal_alert(result: dict) -> str:
    """
    Genera el mensaje de Telegram para una señal STRONG BUY.

    Incluye precio, SL, TP con porcentajes y las razones del bot.
    """
    symbol      = result["symbol"]
    name        = result["name"]
    price       = result["price"]
    score       = result["score"]
    signal      = result["signal"]
    reason      = result["reason"]
    stop_loss   = result["stop_loss"]
    take_profit = result["take_profit"]
    rr          = result["risk_reward"]
    asset_type  = result.get("asset_type", "crypto")

    sl_pct  = (stop_loss   - price) / price * 100
    tp_pct  = (take_profit - price) / price * 100

    # Formato de precio según activo
    price_fmt = f"{price:,.2f}" if price > 1 else f"{price:.6f}"
    sl_fmt    = f"{stop_loss:,.2f}" if stop_loss > 1 else f"{stop_loss:.6f}"
    tp_fmt    = f"{take_profit:,.2f}" if take_profit > 1 else f"{take_profit:.6f}"

    asset_icon = "🪙" if asset_type == "crypto" else "📈"
    header_icon = "🚨" if signal == "STRONG BUY" else "📢"

    lines = [
        f"{header_icon} <b>{signal}</b> — {asset_icon} {name} ({symbol})",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 <b>Precio:</b>       <code>${price_fmt}</code>",
        f"📊 <b>Score:</b>        <code>+{score}</code>",
        f"",
        f"🔎 <b>Por qué entró:</b>",
    ]

    for part in reason.split(" | ")[:3]:
        lines.append(f"   • {part.strip()}")

    lines += [
        f"",
        f"⚡ <b>Niveles operativos:</b>",
        f"   Entrada:     <code>${price_fmt}</code>",
        f"   Stop-Loss:   <code>${sl_fmt}</code>  (<b>{sl_pct:.1f}%</b>)",
        f"   Take-Profit: <code>${tp_fmt}</code>  (<b>+{tp_pct:.1f}%</b>)",
        f"   R:R:         <code>1 : {rr}</code>",
        f"",
        f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}",
    ]

    return "\n".join(lines)


# ─── Lógica principal de notificación ─────────────────────────────────────────

def should_notify(symbol: str) -> bool:
    """Verifica si ya mandamos aviso de este activo recientemente."""
    last = _last_notified.get(symbol, 0)
    return (time.time() - last) >= NOTIFY_COOLDOWN_SEC


def notify_strong_signals(results: list) -> int:
    """
    Manda notificación Telegram por cada STRONG BUY que no esté en cooldown.

    Args:
        results: lista de dicts de analyze_crypto / analyze_stock

    Returns:
        Cantidad de mensajes enviados.
    """
    sent = 0

    for result in results:
        if result.get("signal") != "STRONG BUY":
            continue

        symbol = result["symbol"]

        if not should_notify(symbol):
            print(f"  ⏸️  {symbol}: cooldown activo (evitando spam)")
            continue

        msg = format_signal_alert(result)
        ok  = send_telegram(msg)

        if ok:
            _last_notified[symbol] = time.time()
            sent += 1
            print(f"  📱 Telegram enviado: {symbol} STRONG BUY (score {result['score']})")
        else:
            print(f"  ✗  Error notificando {symbol}")

    return sent


# ─── Mensaje de resumen del ciclo ─────────────────────────────────────────────

def notify_cycle_summary(results: list, cycle_num: int) -> None:
    """
    Envía resumen breve de todos los activos analizados (solo si hay cambios).
    Se puede llamar cada N ciclos para no saturar el chat.
    Llamar solo cuando cycle_num % 12 == 0 (ej: cada hora si corre c/5min).
    """
    if not results:
        return

    lines = [
        f"📋 <b>Resumen de mercado</b> — {datetime.now().strftime('%H:%M')}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    icons = {
        "STRONG BUY":  "🟢🟢",
        "BUY":         "🟢",
        "NEUTRAL":     "🟡",
        "SELL":        "🔴",
        "STRONG SELL": "🔴🔴",
    }

    for r in sorted(results, key=lambda x: x["score"], reverse=True):
        icon   = icons.get(r["signal"], "⚪")
        symbol = r["symbol"]
        score  = r["score"]
        price  = r["price"]
        p_fmt  = f"{price:,.2f}" if price > 1 else f"{price:.4f}"
        lines.append(f"{icon} <b>{symbol}</b>  score <code>{score:+}</code>  ${p_fmt}")

    send_telegram("\n".join(lines))


# ─── Test de configuración ────────────────────────────────────────────────────

def test_connection() -> bool:
    """Envía un mensaje de prueba para verificar que el bot está bien configurado."""
    msg = (
        "✅ <b>Bot de trading conectado</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Las notificaciones de STRONG BUY llegarán aquí.\n\n"
        f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )
    ok = send_telegram(msg)
    if ok:
        print("✅ Telegram configurado correctamente.")
    else:
        print("❌ Error. Verificar TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env")
    return ok


# ─── Ejecutar como script (test) ──────────────────────────────────────────────

if __name__ == "__main__":
    print("Probando conexion con Telegram...")
    print(f"  Token cargado:   {'SI' if TELEGRAM_TOKEN else 'NO — verificar .env'}")
    print(f"  Chat ID cargado: {'SI' if TELEGRAM_CHAT_ID else 'NO — verificar .env'}")
    if TELEGRAM_TOKEN:
        partes = TELEGRAM_TOKEN.split(":")
        print(f"  Token formato:   {'OK (num:letras)' if len(partes) == 2 else 'MAL — debe ser 123456:ABC-xxx'}")
    print()
    test_connection()
