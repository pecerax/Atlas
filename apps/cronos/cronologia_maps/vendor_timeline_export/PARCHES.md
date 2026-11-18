# Copia fijada de timeline-export

Origen: https://github.com/ilbonte/timeline-export, commit 488d854 (19-oct-2026), licencia MIT (ver LICENSE).
Se copiaron solo geller_fetch.py, odlh_export.py y web_key.py. No se actualiza sola: cualquier cambio de versión se revisa a mano.

Cambios (marcados con "PARCHE cronologia_maps" en el código):
- web_key.py: `--master-token-file -` lee el token desde stdin y `-o -` devuelve la clave por stdout, para que ninguno de los dos se escriba en disco. Ruta de Chrome por defecto en Windows.
- odlh_export.py: `build()` acepta una conexión SQLite abierta (base en memoria) y un desfase horario por defecto (Chile en vez de +2 h).
