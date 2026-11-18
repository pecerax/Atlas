"""Sesiones de audio de Windows (qué programa está sonando o usando el micrófono), con comtypes y sin librerías extra.

sessions() -> [(flujo, dispositivo, pid, estado)], flujo "salida"/"entrada", estado 0 inactiva, 1 activa, 2 vencida.
Lo usa atlas_llamadas: cuando entra una llamada al celular, Enlace Móvil abre audio (el timbre, y Windows baja el
volumen del resto) aunque no muestre ninguna ventana.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, byref, c_int, c_uint, c_void_p
from ctypes.wintypes import DWORD, LPWSTR

import comtypes
from comtypes import CLSCTX_ALL, COMMETHOD, GUID, HRESULT, IUnknown


class IAudioSessionControl(IUnknown):
    _iid_ = GUID("{F4B1A599-7266-4319-A8CA-E70ACB11E8CD}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(c_int), "state")),
        COMMETHOD([], HRESULT, "GetDisplayName", (["out"], POINTER(LPWSTR), "name")),
        COMMETHOD([], HRESULT, "SetDisplayName", (["in"], LPWSTR), (["in"], c_void_p)),
        COMMETHOD([], HRESULT, "GetIconPath", (["out"], POINTER(LPWSTR), "path")),
        COMMETHOD([], HRESULT, "SetIconPath", (["in"], LPWSTR), (["in"], c_void_p)),
        COMMETHOD([], HRESULT, "GetGroupingParam", (["out"], POINTER(GUID), "g")),
        COMMETHOD([], HRESULT, "SetGroupingParam", (["in"], POINTER(GUID)), (["in"], c_void_p)),
        COMMETHOD([], HRESULT, "RegisterAudioSessionNotification", (["in"], c_void_p)),
        COMMETHOD([], HRESULT, "UnregisterAudioSessionNotification", (["in"], c_void_p)),
    ]


class IAudioSessionControl2(IAudioSessionControl):
    _iid_ = GUID("{bfb7ff88-7239-4fc9-8fa2-07c950be9c6d}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetSessionIdentifier", (["out"], POINTER(LPWSTR), "id")),
        COMMETHOD([], HRESULT, "GetSessionInstanceIdentifier", (["out"], POINTER(LPWSTR), "id")),
        COMMETHOD([], HRESULT, "GetProcessId", (["out"], POINTER(DWORD), "pid")),
        COMMETHOD([], HRESULT, "IsSystemSoundsSession"),
        COMMETHOD([], HRESULT, "SetDuckingPreference", (["in"], c_int)),
    ]


class IAudioSessionEnumerator(IUnknown):
    _iid_ = GUID("{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_int), "n")),
        COMMETHOD([], HRESULT, "GetSession", (["in"], c_int, "i"), (["out"], POINTER(POINTER(IAudioSessionControl)), "s")),
    ]


class IAudioSessionManager2(IUnknown):
    _iid_ = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetAudioSessionControl", (["in"], c_void_p), (["in"], DWORD), (["out"], POINTER(c_void_p))),
        COMMETHOD([], HRESULT, "GetSimpleAudioVolume", (["in"], c_void_p), (["in"], DWORD), (["out"], POINTER(c_void_p))),
        COMMETHOD([], HRESULT, "GetSessionEnumerator", (["out"], POINTER(POINTER(IAudioSessionEnumerator)), "e")),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Activate", (["in"], POINTER(GUID), "iid"), (["in"], DWORD, "ctx"),
                  (["in"], c_void_p, "params"), (["out"], POINTER(POINTER(IAudioSessionManager2)), "obj")),
        COMMETHOD([], HRESULT, "OpenPropertyStore", (["in"], DWORD), (["out"], POINTER(c_void_p))),
        COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(LPWSTR), "id")),
        COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(DWORD), "state")),
    ]


class IMMDeviceCollection(IUnknown):
    _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_uint), "n")),
        COMMETHOD([], HRESULT, "Item", (["in"], c_uint, "i"), (["out"], POINTER(POINTER(IMMDevice)), "d")),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], c_int, "flow"), (["in"], DWORD, "mask"),
                  (["out"], POINTER(POINTER(IMMDeviceCollection)), "c")),
    ]


CLSID_ENUM = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")


def sessions() -> list[tuple[str, str, int, int]]:
    """Todas las sesiones de audio de los dispositivos activos. Llamar desde un hilo con COM iniciado."""
    en = comtypes.CoCreateInstance(CLSID_ENUM, IMMDeviceEnumerator, CLSCTX_ALL)
    out = []
    for flow, label in ((0, "salida"), (1, "entrada")):
        col = en.EnumAudioEndpoints(flow, 1)  # DEVICE_STATE_ACTIVE
        for i in range(col.GetCount()):
            dev = col.Item(i)
            did = dev.GetId()
            mgr = dev.Activate(byref(IAudioSessionManager2._iid_), CLSCTX_ALL, None)
            se = mgr.GetSessionEnumerator()
            for k in range(se.GetCount()):
                s2 = se.GetSession(k).QueryInterface(IAudioSessionControl2)
                try:
                    pid = s2.GetProcessId()
                except Exception:  # noqa: BLE001  (la sesión de sonidos del sistema puede fallar aquí)
                    pid = 0
                out.append((label, did, int(pid), int(s2.GetState())))
    return out
