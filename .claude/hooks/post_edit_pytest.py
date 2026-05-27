"""
post_edit_pytest.py — PostToolUse hook: corre pytest cuando se editan archivos clave.

Claude Code pasa los detalles del tool use via stdin como JSON:
  { "tool_name": "Edit", "tool_input": {"file_path": "..."}, ... }

Archivos monitoreados: indicators.py, analyzer.py, backtester.py,
                       main.py, scalper.py, config.py

Exit 0 → OK (tests pasaron o archivo no monitoreado).
Exit 2 → Tests fallaron; Claude Code lo muestra como advertencia en la sesión.
"""

import json
import os
import subprocess
import sys

# Windows cp1252 can't encode emoji — force utf-8 for hook output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KEY_FILES = {
    "indicators.py",
    "analyzer.py",
    "backtester.py",
    "main.py",
    "scalper.py",
    "config.py",
}

PROJECT_DIR = r"C:\proyecto-cripto"

def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)  # sin datos → no hacer nada

    file_path = data.get("tool_input", {}).get("file_path", "")
    filename  = os.path.basename(file_path)

    if filename not in KEY_FILES:
        sys.exit(0)

    print(f"\n🧪 pytest — triggered by edit to {filename}", flush=True)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=short"],
        cwd=PROJECT_DIR,
        text=True,
    )

    if result.returncode != 0:
        print("❌ Tests FAILED — revisa los cambios antes de continuar.", flush=True)
        sys.exit(2)

    print("✅ All 28 tests passed.", flush=True)


if __name__ == "__main__":
    main()
