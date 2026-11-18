"""Aviso 1 hora antes de cada actividad del calendario (pedido del usuario, 15-11-2026):
«Cuando esté a 1 hora de una actividad, quiero que me mande un recordatorio, por voz (con la campanita antes de
hablar) y por Telegram».

Solo lógica, sin sonido ni red: hud_server.previo_loop() trae los eventos (atlas_agenda.upcoming) cada pocos minutos,
llama a pendientes() cada pocos segundos y avisa lo que devuelva. Lo ya avisado queda en hud/eventos_avisados.json
para no repetirlo al reiniciar Atlas.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "eventos_avisados.json"
ANTES = timedelta(hours=1)  # predeterminado; ajustes.json avisos.antes_min lo cambia (ver antes())


def antes() -> timedelta:
    try:
        import atlas_ajustes as AJ
        return timedelta(minutes=AJ.num("avisos.antes_min", 60, minimo=6))
    except Exception:  # noqa: BLE001
        return ANTES
MIN_RESTANTE = timedelta(minutes=5)  # si Atlas abrió con menos de 5 min, ya no tiene sentido avisar


def key(ev: dict) -> str:
    return f"{ev.get('summary', '')}|{ev['when'].isoformat(timespec='minutes')}"


def load_sent() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def save_sent(sent: dict, now: datetime) -> None:
    # se olvida lo de hace más de 2 días (el archivo no crece)
    keep = {k: v for k, v in sent.items() if v >= (now - timedelta(days=2)).isoformat()}
    try:
        STATE.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def cuenta(ev: dict) -> bool:
    """¿Es una actividad que se avisa? Solo los EVENTOS con hora (Google Calendar, reuniones, citas…).
    Uso real 17-11-2026: avisó «en 1 hora tiene Cátedra de Redes» y el usuario dijo «me está tomando como reuniones
    las cátedras, los eventos son los únicos que debería notificarme». Así que no se avisan las clases de U-Cursos
    (cátedras, auxiliares, laboratorios), ni las evaluaciones ni las entregas."""
    import atlas_agenda as A

    if ev.get("allday") or ev.get("tramo") in ("fin", "todo"):
        return False
    if A.is_class(ev) and clase_avisada(ev):
        return True  # p. ej. las auxiliares de Intro a la Programación, que él dicta (pedido del usuario, 17-11-2026)
    if A.is_class(ev) or A.is_evaluation(ev) or A.is_delivery(ev):
        return False
    return True


def clase_avisada(ev: dict) -> bool:
    """Clases que sí se avisan 1 hora antes: ramos.json -> "avisar_antes": ["auxiliar"] en el ramo. Hoy solo las
    auxiliares de Introducción a la Programación (las dicta el usuario); sus cátedras y los demás ramos, no."""
    import atlas_agenda as A

    c, k = A._plain(ev.get("course", "")), A._plain(ev.get("kind", ""))
    for r in A.load_ramos():
        full = A._plain(r.get("ramo", ""))
        tipos = r.get("avisar_antes") or []
        if tipos and full and (c.startswith(full[:28]) or full.startswith(c[:28]) and len(c) >= 12):
            return any(A._plain(t) in k for t in tipos)
    return False


def _cuanto(delta: timedelta) -> str:
    m = max(1, round(delta.total_seconds() / 60))
    if m >= 55:
        return "1 hora"
    return f"{m} minutos"


def texto(evs: list[dict], now: datetime) -> str:
    """«Señor, en 1 hora tiene Reunión para Empresa, a las 21:30.» (varios a la misma hora van en una sola frase)."""
    import atlas_agenda as A

    names = [A._event_name(e) + (f" en {e['location']}" if e.get("location") else "") for e in evs]
    lista = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]
    w = evs[0]["when"]
    return f"Señor, en {_cuanto(w - now)} tiene {lista}, a las {w.hour}:{w.minute:02d}."


def etiqueta(text: str) -> str:
    """Lo que sale en el recuadro amarillo, sin decir de qué es (pedido del usuario): «Reunión próxima: 21:30 horas».
    La hora se toma del texto completo («…, a las 21:30.»)."""
    import re

    m = re.search(r"a las (\d{1,2}:\d{2})\.?\s*$", text)
    return f"Reunión próxima: {m.group(1)} horas" if m else "Reunión próxima"


def pendientes(events: list[dict], now: datetime, sent: dict) -> list[tuple[list[str], str]]:
    """-> [(claves, texto)] de lo que hay que avisar ahora: empieza en 1 hora o menos y no se avisó todavía.
    Marca en `sent` lo devuelto (quien llama guarda con save_sent)."""
    due: dict[datetime, list[dict]] = {}
    for ev in events:
        left = ev["when"] - now
        if not (MIN_RESTANTE <= left <= antes()) or key(ev) in sent or not cuenta(ev):
            continue
        due.setdefault(ev["when"], []).append(ev)
    out = []
    for when in sorted(due):
        evs = due[when]
        ks = [key(e) for e in evs]
        for k in ks:
            sent[k] = now.isoformat()
        out.append((ks, texto(evs, now)))
    return out
