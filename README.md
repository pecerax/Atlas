# Atlas v1.1

Asistente personal de voz para Windows, en español, que corre en el propio computador con un modelo local ([Ollama](https://ollama.com)). Lee el correo, la agenda, las notas de U-Cursos y Canvas y la mensajería, avisa lo importante y responde por voz.

Trae además sus propias aplicaciones, que se abren dentro de la misma ventana:

| App | Para qué sirve |
|---|---|
| **Hermes** | Finanzas personales a partir de las cartolas y los avisos del banco |
| **Fortuna** | Seguimiento de fondos mutuos con datos públicos de la CMF |
| **Cronos** | La historia de cada día, con la cronología de Google Maps |
| **Baco** | Música y entretenimiento |
| **Atenea** | Educación |

Atlas está construido sobre [OpenJarvis](https://github.com/open-jarvis/OpenJarvis) (Apache-2.0). Este repositorio no copia OpenJarvis: `openjarvis/` trae solo los cambios de Atlas sobre él (ver [`openjarvis/BASE.txt`](openjarvis/BASE.txt)).

## Privacidad

Todo se procesa en el computador de quien lo usa. Nada personal vive en este repositorio: contactos, cuentas, agenda, historial, movimientos, cartolas, tokens y claves quedan solo en el PC (las claves, en el Administrador de credenciales de Windows). Los archivos de datos se crean al usar Atlas, y los `*.ejemplo.json` muestran su forma. Los nombres, correos y teléfonos que aparecen en las pruebas son inventados.

La política de privacidad está en [pecerax.github.io/Atlas/privacidad.html](https://pecerax.github.io/Atlas/privacidad.html).

## Qué hay aquí

| Carpeta | Qué es |
|---|---|
| `hud/` | La pantalla de Atlas (`hud.html`), su servidor (`hud_server.py`), los módulos `atlas_*.py` y las pruebas `pruebas_*.py` |
| `apps/` | Las aplicaciones: `hermes/`, `fortuna/`, `cronos/`, `baco/` y `atenea/` |
| `instalador/` | El asistente de instalación y lo necesario para armar el instalador de Windows |
| `openjarvis/` | Parche y archivos nuevos de Atlas sobre OpenJarvis |
| `docs/` | Página de inicio y política de privacidad (GitHub Pages) |
| `*.cmd`, `bin/` | Lanzadores de Windows. Quedan en la raíz porque Atlas los busca en `%LOCALAPPDATA%\Atlas` |

Los lanzadores más usados:

| Lanzador | Qué hace |
|---|---|
| `Atlas.cmd` | Abre Atlas |
| `Atlas-terminal.cmd` | Abre Atlas en la terminal, sin pantalla |
| `Atlas-diagnostico.cmd` | Revisa la instalación y dice qué falta |
| `Probar-Atlas.cmd` | Corre las pruebas |
| `Agregar-correo.cmd`, `Agregar-calendario.cmd`, `Agregar-telegram.cmd` | Conectan una cuenta |
| `Conectar-Google-Calendar.cmd` | Conecta Google Calendar |
| `Instalar-parakeet.cmd`, `Instalar-extras.cmd` | Instalan el reconocimiento de voz y los componentes opcionales |
| `Proteger-credenciales.cmd` | Pasa las claves al Administrador de credenciales de Windows |

## Requisitos

- Windows 10 u 11 de 64 bits.
- Unos 8 GB de descarga (Python, el núcleo, Ollama, el modelo y las voces).
- Con tarjeta de video NVIDIA usa el modelo `qwen3.5:9b`, y sin ella el `qwen3.5:4b`.

## Instalar

El instalador `Atlas-Instalar.exe` no se publica aquí. La instalación desde el repositorio usa el mismo asistente que trae el instalador.

1. Instale [uv](https://docs.astral.sh/uv/) y clone el repositorio en `%LOCALAPPDATA%\Atlas`:
   ```
   git clone https://github.com/pecerax/Atlas.git "%LOCALAPPDATA%\Atlas"
   ```
2. Abra el asistente:
   ```
   uv run --no-project --python 3.13 instalador\asistente.py --atlas "%LOCALAPPDATA%\Atlas"
   ```
3. Abra Atlas con `Atlas.cmd`. La pantalla de primer inicio repasa lo que falta.

### Qué hace el asistente

Cada paso se puede dejar para después y retomar en Ajustes › Instalación.

1. **Revisa el computador:** espacio libre, memoria y tarjeta de video.
2. **Componentes de Atlas:** Python 3.13 (con `uv`, sin tocar el Python del sistema), el núcleo OpenJarvis en el commit de `openjarvis/BASE.txt` con los cambios de Atlas (`openjarvis/atlas.patch` y `openjarvis/archivos/`), el entorno `src\.venv` con `instalador\requisitos.txt`, la extensión nativa `openjarvis_rust` y `Atlas.exe`. Crea también los datos en `%USERPROFILE%\.atlas` (`config.toml`) y `hud\ajustes.json`.
3. **Ollama:** lo instala y lo deja corriendo.
4. **El cerebro de Atlas:** descarga el modelo elegido en el paso 1.
5. **Oído y voces en español:** el reconocimiento de voz Parakeet (`hud\install_parakeet.py`) y las voces Piper.
6. **Avisos del banco (Hermes):** instala Syncthing, lo deja corriendo oculto al iniciar Windows y protege su panel con un usuario y una contraseña al azar, guardados en el Administrador de credenciales.
7. **Acceso directo** en el escritorio y en el menú Inicio.
8. **Cuentas, al final y una por una:** U-Cursos y Canvas (se inicia sesión en una ventana del navegador), correo (Gmail con contraseña de aplicación), Google Calendar, Hermes (la macro de MacroDroid se pasa al celular con un QR y el celular se empareja con Syncthing) y Cronos (modo rutas de Maps o modo señales).

### Lo que el repositorio no trae

- **La extensión nativa `openjarvis_rust`.** Hay que compilarla, y necesita [Rust](https://rustup.rs). Después de armar `src\` (el asistente lo hace en el paso 2, o a mano como dice `openjarvis/BASE.txt`), ejecute `uvx maturin build --release` en `src\rust\crates\openjarvis-python` y copie el `.whl` de `src\rust\target\wheels` a `instalador\ruedas\`. Si el asistente ya terminó sin ella, instálela después con:
  ```
  uv pip install --python src\.venv\Scripts\python.exe --no-deps instalador\ruedas\*.whl
  ```
- **La llave de Google Calendar.** Cree su propia credencial OAuth de escritorio en Google Cloud (con la API de Calendar activada) y conéctela desde Ajustes, o con `Conectar-Google-Calendar.cmd`.

## Pruebas

`Probar-Atlas.cmd` corre `hud\pruebas_atlas.py`. Las demás se corren con el Python del entorno (`src\.venv\Scripts\python.exe`): `hud\pruebas_baco.py`, `hud\pruebas_canvas.py`, `hud\pruebas_canvas_rutas.py`, `hud\pruebas_historia.py` y `hud\pruebas_vigilancias.py`.

## Créditos

- [OpenJarvis](https://github.com/open-jarvis/OpenJarvis), la base de Atlas (Apache-2.0).
- La exportación de la cronología de Google Maps usa código de terceros, con su licencia y sus cambios en [`apps/cronos/cronologia_maps/vendor_timeline_export/`](apps/cronos/cronologia_maps/vendor_timeline_export/).
