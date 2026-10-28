# SPDX-License-Identifier: GPL-3.0-or-later
"""API keys in the OS credential store (D102 phase 3): Windows Credential Manager, macOS Keychain or the
Linux Secret Service. Keys never go into preferences.json or a project. If no store can be reached, the
assistant says so instead of falling back to a file."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys

SERVICE_PREFIX = "kimbim-assistant-"


class KeyStoreError(Exception):
    pass


def _target(provider: str) -> str:
    return SERVICE_PREFIX + (provider or "anthropic")


# ---------------------------------------------------------------- Windows

if os.name == "nt":
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class _CREDENTIALW(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", _FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    _advapi = ctypes.windll.advapi32
    _advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
    _advapi.CredReadW.restype = wintypes.BOOL
    _advapi.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    _advapi.CredWriteW.restype = wintypes.BOOL
    _advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _advapi.CredDeleteW.restype = wintypes.BOOL
    _advapi.CredFree.argtypes = [ctypes.c_void_p]


def _windows_get(provider: str) -> str:
    ptr = ctypes.POINTER(_CREDENTIALW)()
    if not _advapi.CredReadW(_target(provider), 1, 0, ctypes.byref(ptr)):
        return ""
    try:
        cred = ptr.contents
        if not cred.CredentialBlobSize:
            return ""
        data = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        return data.decode("utf-8", "replace")
    finally:
        _advapi.CredFree(ptr)


def _windows_set(provider: str, key: str) -> None:
    data = key.encode("utf-8")
    blob = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    cred = _CREDENTIALW(Type=1, TargetName=_target(provider), CredentialBlobSize=len(data),
                        CredentialBlob=ctypes.cast(blob, ctypes.POINTER(ctypes.c_byte)), Persist=2,
                        UserName="kimbim")
    if not _advapi.CredWriteW(ctypes.byref(cred), 0):
        raise KeyStoreError("Windows Credential Manager refused to store the key")


def _windows_delete(provider: str) -> None:
    _advapi.CredDeleteW(_target(provider), 1, 0)  # not there is fine


# ---------------------------------------------------------------- macOS / Linux

def _run(args: list[str], data: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, input=data, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as ex:
        raise KeyStoreError(f"cannot reach the credential store: {ex}") from None


def _mac_get(provider: str) -> str:
    out = _run(["security", "find-generic-password", "-s", _target(provider), "-w"])
    return out.stdout.strip() if out.returncode == 0 else ""


def _mac_set(provider: str, key: str) -> None:
    out = _run(["security", "add-generic-password", "-s", _target(provider), "-a", "kimbim", "-w", key, "-U"])
    if out.returncode != 0:
        raise KeyStoreError(out.stderr.strip() or "macOS Keychain refused to store the key")


def _mac_delete(provider: str) -> None:
    _run(["security", "delete-generic-password", "-s", _target(provider)])


def _linux_get(provider: str) -> str:
    out = _run(["secret-tool", "lookup", "service", _target(provider)])
    return out.stdout.strip() if out.returncode == 0 else ""


def _linux_set(provider: str, key: str) -> None:
    out = _run(["secret-tool", "store", "--label", "KimBim Assistant", "service", _target(provider)], key)
    if out.returncode != 0:
        raise KeyStoreError(out.stderr.strip() or "the Secret Service refused to store the key")


def _linux_delete(provider: str) -> None:
    _run(["secret-tool", "clear", "service", _target(provider)])


# ---------------------------------------------------------------- public

def get_key(provider: str) -> str:
    if os.name == "nt":
        return _windows_get(provider)
    if sys.platform == "darwin":
        return _mac_get(provider)
    return _linux_get(provider)


def set_key(provider: str, key: str) -> None:
    if not (key or "").strip():
        clear_key(provider)
        return
    if os.name == "nt":
        _windows_set(provider, key)
    elif sys.platform == "darwin":
        _mac_set(provider, key)
    else:
        _linux_set(provider, key)


def clear_key(provider: str) -> None:
    if os.name == "nt":
        _windows_delete(provider)
    elif sys.platform == "darwin":
        _mac_delete(provider)
    else:
        _linux_delete(provider)


def has_key(provider: str) -> bool:
    try:
        return bool(get_key(provider))
    except KeyStoreError:
        return False
