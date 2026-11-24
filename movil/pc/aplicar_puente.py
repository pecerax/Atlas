"""Instala el Puente Atlas en una copia de Atlas ya instalada, sin pisar otros cambios de hud_server.py.

    python aplicar_puente.py <carpeta del repositorio con la rama claude/atlas-movil> [carpeta de Atlas]

Copia los archivos nuevos y agrega tres bloques a hud_server.py junto a líneas que ya existen. Si alguna de esas
líneas no está exactamente una vez, no toca nada. Deja un respaldo hud_server.py.antes_puente.bak. Se puede correr
de nuevo: si el puente ya está, no cambia hud_server.py.
"""
import os
import py_compile
import shutil
import sys
from pathlib import Path

NUEVOS = ["hud/atlas_puente.py", "hud/puente.html", "hud/pruebas_puente.py", "Vincular-celular.cmd", "Permitir-celular-firewall.cmd"]
BLOQUES = [('        if self.path == "/api/credencial/hermes-pdf":   # solo si está guardada; nunca el valor\n', '        if self.path.split("?")[0] in ("/puente", "/puente/qrcode.js", "/api/puente"):   # «Vincular celular» (atlas_puente.py)\n            local = (self.headers.get("Host") or "").split(":")[0] in ("127.0.0.1", "localhost")\n            if not local:   # la página trae el token y el QR: solo hacia este PC\n                self._json({"error": "forbidden"}, 403)\n            elif self.path == "/puente":\n                html = (HERE / "puente.html").read_text(encoding="utf-8").replace("__ATLAS_TOKEN__", TOKEN)\n                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")\n            elif self.path == "/puente/qrcode.js":\n                self._send(200, (HERE.parent / "instalador" / "qrcode.js").read_bytes(), "text/javascript; charset=utf-8")\n            elif not self._authorized():\n                self._json({"error": "forbidden"}, 403)\n            else:\n                import atlas_puente\n\n                self._json(atlas_puente.vista())\n            return\n'), ('            elif self.path == "/api/speak":\n', '            elif self.path == "/api/puente":  # «Vincular celular»: prender/apagar, pedir el QR, desvincular (solo este PC)\n                import atlas_puente\n\n                op = str(data.get("op", ""))\n                if not self._mismo_origen():\n                    self._json({"error": "forbidden"}, 403)\n                elif op in ("activar", "apagar"):\n                    atlas_puente.activar(op == "activar")\n                    log(f"  puente {\'activado\' if op == \'activar\' else \'apagado\'} desde Vincular celular")\n                    self._json(atlas_puente.vista())\n                elif op == "codigo":\n                    if not atlas_puente.corriendo():\n                        self._json({"error": "El puente está apagado."})\n                    else:\n                        self._json(atlas_puente.nuevo_codigo())\n                elif op == "desvincular":\n                    atlas_puente.desvincular(str(data.get("id", "")))\n                    self._json(atlas_puente.vista())\n                else:\n                    self._json({"error": "Operación desconocida."})\n'), ('    try:  # Baco: mide el tiempo de los juegos del PC que no son de Steam (mira los procesos cada 30 s)\n', '    try:  # Puente Atlas: la puerta de la app del celular. Solo se abre si el usuario lo activó en «Vincular celular»\n        import atlas_puente\n\n        atlas_puente.iniciar(sys.modules[__name__], log=log)\n    except Exception as exc:  # noqa: BLE001\n        log(f"Puente: no pude iniciarlo ({type(exc).__name__}: {exc})")\n')]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    repo = Path(sys.argv[1]).resolve()
    atlas = Path(sys.argv[2] if len(sys.argv) > 2 else Path(os.environ["LOCALAPPDATA"]) / "Atlas").resolve()
    srv = atlas / "hud" / "hud_server.py"
    if not srv.exists() or not (repo / "hud" / "atlas_puente.py").exists():
        print("No encuentro Atlas o el repositorio:", atlas, repo)
        return 1
    texto = srv.read_text(encoding="utf-8")
    marca = srv.stat().st_mtime_ns
    if "atlas_puente" in texto:
        print("hud_server.py ya tiene el puente: no lo cambio.")
        nuevo = None
    else:
        nuevo = texto
        for ancla, bloque in BLOQUES:
            if nuevo.count(ancla) != 1:
                print("No toqué nada: no encontré exactamente una vez esta línea de hud_server.py:\n  " + ancla.strip())
                return 1
            nuevo = nuevo.replace(ancla, bloque + ancla, 1)
    for rel in NUEVOS:
        dst = atlas / rel
        if dst.exists() and dst.read_bytes() != (repo / rel).read_bytes():
            shutil.copy2(dst, dst.with_name(dst.name + ".antes_puente.bak"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / rel, dst)
        print("copiado:", rel)
    if nuevo is not None:
        if srv.stat().st_mtime_ns != marca or srv.read_text(encoding="utf-8") != texto:
            print("hud_server.py cambió mientras trabajaba (otro lo está editando). No lo toqué: vuelva a correr este script.")
            return 1
        bak = srv.with_name("hud_server.py.antes_puente.bak")
        shutil.copy2(srv, bak)
        tmp = srv.with_name("hud_server.py.puente.tmp")
        crlf = b"\r\n" in srv.read_bytes()   # se conserva el fin de línea que ya tenía el archivo
        tmp.write_text(nuevo, encoding="utf-8", newline="\r\n" if crlf else "\n")
        try:
            py_compile.compile(str(tmp), doraise=True)
        except py_compile.PyCompileError as exc:
            tmp.unlink()
            print("No toqué hud_server.py: el resultado no compila.", exc)
            return 1
        os.replace(tmp, srv)
        print("hud_server.py actualizado (respaldo:", bak.name + ")")
    print("Listo. Reinicie Atlas y abra Vincular-celular.cmd.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
