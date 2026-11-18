"""Envoltorio de transición: las pruebas ahora viven en pruebas_atlas.py (Jarvis pasó a llamarse Atlas).
Se deja este archivo para que los scripts y trabajos que aún usan el nombre viejo sigan funcionando."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "pruebas_atlas.py"), run_name="__main__")
else:
    import pruebas_atlas as _m
    sys.modules[__name__] = _m
