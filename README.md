# Atlas v1.0

Asistente personal de voz para Windows que corre en local con Ollama. Lee correo, notas de U-Cursos y Canvas, mensajería y agenda, e incluye Hermes (finanzas), Fortuna (inversiones) y Cronos (historia diaria).

Atlas está construido sobre [OpenJarvis](https://github.com/open-jarvis/OpenJarvis) (Apache-2.0). Este repositorio no copia OpenJarvis: `openjarvis/` trae solo los cambios de Atlas sobre él (ver `openjarvis/BASE.txt`).

## Qué hay aquí

| Carpeta | Qué es |
|---|---|
| `*.cmd`, `bin/` | Lanzadores de Windows (abrir Atlas, pruebas, conectar cuentas) |
| `hud/` | La pantalla de Atlas (`hud.html`), su servidor (`hud_server.py`), los módulos `atlas_*.py` y las pruebas `pruebas_*.py` |
| `apps/cronos/` | Cronos, la historia diaria, con la sincronización de la cronología de Google Maps |
| `apps/hermes/` | Hermes, finanzas personales a partir de cartolas |
| `apps/fortuna/` | Fortuna, seguimiento de fondos mutuos con datos públicos de la CMF |
| `instalador/` | Instalador de Windows y asistente de primer inicio |
| `docs/` | Página de inicio y política de privacidad (GitHub Pages) |
| `openjarvis/` | Parche y archivos nuevos de Atlas sobre OpenJarvis |

## Datos personales

Nada personal vive en este repositorio. Contactos, cuentas, agenda, historial, movimientos, cartolas, tokens y claves quedan solo en el PC (las claves en el Administrador de credenciales de Windows). Los archivos de datos se crean al usar Atlas; los `*.ejemplo.json` muestran su forma. Los nombres, correos y teléfonos que aparecen en las pruebas son inventados.

## Instalar

1. Armar `src\` con OpenJarvis y el parche (ver `openjarvis/BASE.txt`) y crear `src\.venv`.
2. Copiar `hud\ajustes.ejemplo.json` como `hud\ajustes.json` y `hud\accesos.ejemplo.json` como `hud\accesos.json`.
3. Abrir con `Atlas.cmd`. El panel «qué falta» del HUD guía el resto (voz, correo, Telegram, calendario).

Pruebas: `Probar-Atlas.cmd` (`hud\pruebas_atlas.py`), además de `hud\pruebas_historia.py` y `hud\pruebas_vigilancias.py`.
