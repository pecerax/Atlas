"""Envoltorio de transición Jarvis -> Atlas: este módulo ahora se llama openjarvis.security.atlas_secretos.
Se deja para que el código que aún importa el nombre viejo (por ejemplo, Apolo) siga funcionando:
es el MISMO módulo (no una copia), así que comparten estado."""
import sys as _sys

from openjarvis.security import atlas_secretos as _m

_sys.modules[__name__] = _m
