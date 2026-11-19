# Atlas v1.1

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

### Lo recomendado: el instalador

Descargue **[Atlas-Instalar.exe](https://github.com/pecerax/Atlas/releases/latest/download/Atlas-Instalar.exe)** (en [Releases](https://github.com/pecerax/Atlas/releases)) y ábralo. Copia Atlas en `%LOCALAPPDATA%\Atlas` y abre un asistente que hace todo lo demás. Descarga unos 8 GB, y cada paso se puede dejar para después:

1. **Revisa el computador:** espacio libre, memoria y tarjeta de video. Con tarjeta NVIDIA usa el modelo `qwen3.5:9b`, y sin ella el `qwen3.5:4b`.
2. **Componentes de Atlas:** Python 3.13 (con `uv`, sin tocar el Python del sistema), el núcleo OpenJarvis en el commit de `openjarvis/BASE.txt` con los cambios de Atlas (`openjarvis/atlas.patch` y `openjarvis/archivos/`), el entorno `src\.venv` con `instalador
equisitos.txt`, la extensión nativa `openjarvis_rust` y `Atlas.exe`. Crea también los datos en `%USERPROFILE%\.atlas` (`config.toml`, con `~\.openjarvis` apuntando ahí) y `hudjustes.json`.
3. **Ollama:** lo instala y lo deja corriendo.
4. **El cerebro de Atlas:** descarga el modelo elegido en el paso 1.
5. **Oído y voces en español:** el reconocimiento de voz Parakeet (`hud\install_parakeet.py`) y las voces Piper davefx, ald, claude y alan.
6. **Avisos del banco (Hermes):** instala Syncthing, lo deja corriendo oculto al iniciar Windows y protege su panel con un usuario y una contraseña al azar, guardados en el Administrador de credenciales.
7. **Acceso directo** en el escritorio y en el menú Inicio.
8. **Cuentas, al final y una por una:** U-Cursos y Canvas (se inicia sesión en una ventana del navegador), correo (Gmail con contraseña de aplicación), Google Calendar, Hermes (la macro de MacroDroid se pasa al celular con un QR y el celular se empareja con Syncthing) y Cronos (modo rutas de Maps o modo señales).

Al abrir Atlas por primera vez, la pantalla de primer inicio repasa lo que falta.

### A mano (para desarrollar)

Clonar el repositorio no basta: faltan el núcleo, el entorno, Ollama, el modelo, las voces y las cuentas. Lo más seguro es usar el mismo asistente:

1. Instale [uv](https://docs.astral.sh/uv/) y clone en `%LOCALAPPDATA%\Atlas`:
   ```
   git clone https://github.com/pecerax/Atlas.git "%LOCALAPPDATA%\Atlas"
   ```
2. Compile la extensión nativa, que no viene en el repositorio. Necesita [Rust](https://rustup.rs). Después de armar `src\` (el asistente lo hace en el paso 2, o hágalo a mano como dice `openjarvis/BASE.txt`), ejecute `uvx maturin build --release` en `src
ust\crates\openjarvis-python` y copie el `.whl` de `src
ust	arget\wheels` a `instalador
uedas\`. Si el asistente ya terminó sin él, instálelo después con `uv pip install --python src\.venv\Scripts\python.exe --no-deps instalador
uedas\*.whl`.
3. Abra el asistente, que hace los pasos 1 a 8 de arriba:
   ```
   uv run --no-project --python 3.13 instaladorsistente.py --atlas "%LOCALAPPDATA%\Atlas"
   ```
4. **Google Calendar:** el instalador trae la llave OAuth de Atlas, y el repositorio no. Desde una copia clonada, cree su propia credencial OAuth de escritorio en Google Cloud (con la API de Calendar activada) y conéctela desde Ajustes, o con `Conectar-Google-Calendar.cmd`.
5. Abra Atlas con `Atlas.cmd`.

Pruebas: `Probar-Atlas.cmd` (`hud\pruebas_atlas.py`), además de `hud\pruebas_historia.py` y `hud\pruebas_vigilancias.py`.
