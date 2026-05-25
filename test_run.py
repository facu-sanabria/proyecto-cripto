"""Script de prueba — corre 1 solo ciclo con 3 cryptos para verificar que todo funciona."""
from fetcher import fetch_all
from analyzer import analyze_crypto
from excel_writer import update_excel
from config import CRYPTOS, TIMEFRAME

print("Descargando datos (3 cryptos)...")
data = fetch_all(CRYPTOS[:3], TIMEFRAME, 200)
print(f"Descargadas: {len(data)}\n")

if not data:
    print("ERROR: no se obtuvieron datos. Revisar conexión a internet.")
    exit(1)

results = []
for d in data:
    r = analyze_crypto(d)
    results.append(r)
    print(f"  {r['symbol']:6}  score={r['score']:+d}  signal={r['signal']}")
    print(f"         razón: {r['reason']}")
    print(f"         precio: ${r['price']:,.4f}  SL: ${r['stop_loss']:,.4f}  TP: ${r['take_profit']:,.4f}  R/R: {r['risk_reward']}x")
    print()

results.sort(key=lambda x: x["score"], reverse=True)
update_excel(results, "crypto_signals.xlsx")
print("\nPRUEBA EXITOSA — crypto_signals.xlsx generado.")
