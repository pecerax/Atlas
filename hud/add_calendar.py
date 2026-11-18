"""Agrega un calendario (enlace iCal) a Atlas. El enlace queda solo en este PC, en hud/calendarios.json.

Google Calendar: Configuración -> (su calendario) -> "Integrar el calendario" ->
"Dirección secreta en formato iCal". Ese enlace es privado: no lo comparta.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass
import atlas_agenda as agenda  # noqa: E402


def main() -> None:
    print("=== Agregar un calendario a Atlas ===\n")
    print("Pegue el enlace iCal del calendario (en Google Calendar se llama")
    print("'Direccion secreta en formato iCal'). Clic derecho pega en esta ventana.\n")
    url = input("Enlace iCal: ").strip().strip('"')
    if not url:
        print("No se ingreso ningun enlace.")
        return
    url = url.replace("webcal://", "https://")
    if not url.lower().startswith("https://"):
        print("El enlace debe empezar con https:// (o webcal://).")
        return
    name = input("Nombre para este calendario (ej. Personal, Trabajo) [Google]: ").strip() or "Google"
    print("\nProbando el enlace...")
    try:
        text, _ = agenda._fetch({"nombre": "_prueba_" + name, "url": url})
        events = agenda.parse_ics(text, name)
    except Exception as exc:  # noqa: BLE001
        print(f"\nNo pude leer el calendario: {exc}")
        print("Revise que copio la 'direccion secreta en formato iCal' completa.")
        return
    finally:
        for f in HERE.glob("agenda__prueba_*.ics"):
            f.unlink(missing_ok=True)
    data = {"calendarios": []}
    if agenda.CONFIG.exists():
        try:
            data = json.loads(agenda.CONFIG.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    cals = [c for c in data.get("calendarios", []) if c.get("nombre", "").lower() != name.lower() and c.get("url") != url]
    cals.append({"nombre": name, "url": url})
    data["calendarios"] = cals
    agenda.CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nListo: calendario '{name}' agregado ({len(events)} eventos leidos).")
    print("Calendarios conectados: " + ", ".join(c.get("nombre", "?") for c in cals))
    print("Cierre Atlas y vuelva a abrirlo. Pruebe: 'que tengo manana?'")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
