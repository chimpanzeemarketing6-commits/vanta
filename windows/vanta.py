"""Vanta - a game hub and performance toolkit for Windows handhelds, built around the Lenovo Legion Go.
(Formerly RAM//OPT Go.)

Windowed app (tkinter) built to be packaged as a single .exe with PyInstaller.
"""
import ctypes
import json
import math
import os
import colorsys
import contextlib
import queue
import re
import random
import subprocess
import sys
import threading
import time
from collections import deque
from ctypes import wintypes

if os.name != "nt":
    print("Vanta only works on Windows.")
    sys.exit(1)

import tkinter as tk
import tkinter.font as tkfont

# Two editions from one source: Vanta (any Windows PC or handheld) and Vanta Go (adds everything Legion Go:
# Legion buttons, TDP, fans, charge limit, lights, Gen 1 / Gen 2 presets, Legion Space). The entry script picks.
EDITION = "go" if os.environ.get("VANTA_EDITION") == "go" else "universal"
IS_GO = EDITION == "go"
APP_NAME = "Vanta Go" if IS_GO else "Vanta"
VERSION = "9.9.2"
# Preview build (Vanta-Preview.exe): no admin prompt, its own settings, and by default it changes nothing on the PC.
PREVIEW = os.environ.get("VANTA_PREVIEW") == "1"
FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
PORTABLE_FLAG = os.path.join(APP_DIR, "portable.ini")
_LOCALAPP = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
_ID = APP_NAME + (" Preview" if PREVIEW else "")          # "Vanta", "Vanta Preview", "Vanta Go", "Vanta Go Preview"
_SLUG = _ID.lower().replace(" ", "_")                      # vanta, vanta_preview, vanta_go, vanta_go_preview
LOCAL_CONFIG = os.path.join(_LOCALAPP, _ID, "config.json")
PORTABLE_CONFIG = os.path.join(APP_DIR, _SLUG + "_config.json")
# Vanta Go carries on from the Legion builds of Vanta 8.2 and older (and RAM//OPT Go before that), so an upgrade
# keeps every setting. The universal Vanta starts fresh.
if IS_GO:
    _old_id = "Vanta Preview" if PREVIEW else "Vanta"
    OLD_CONFIGS = [os.path.join(_LOCALAPP, _old_id, "config.json"),
                   os.path.join(APP_DIR, ("vanta_preview" if PREVIEW else "vanta") + "_config.json")]
    if not PREVIEW:
        OLD_CONFIGS += [os.path.join(_LOCALAPP, "RamOptimizer", "config_go.json"), os.path.join(APP_DIR, "ramopt_go_config.json")]
    OLD_TASK_NAMES = [_old_id] + ([] if PREVIEW else ["RAMOPT Go"])
else:
    OLD_CONFIGS, OLD_TASK_NAMES = [], []
CONFIG_PATH = PORTABLE_CONFIG if os.path.exists(PORTABLE_FLAG) else LOCAL_CONFIG
TASK_NAME = _ID
INSTANCE = _SLUG.upper()


def escape(text):
    """XML-escape (instead of importing xml.sax, which drags in urllib/http/email at start-up)."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def resource(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


# =====================================================================  Win32

ntdll = ctypes.WinDLL("ntdll")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
shell32 = ctypes.WinDLL("shell32")
user32 = ctypes.WinDLL("user32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi")
except OSError:
    dwmapi = None

SystemMemoryListInformation = 80
SystemFileCacheInformationEx = 81
SystemCombinePhysicalMemoryInformation = 130
MemoryEmptyWorkingSets = 2
MemoryFlushModifiedList = 3
MemoryPurgeStandbyList = 4
MemoryPurgeLowPriorityStandbyList = 5


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class SYSTEM_MEMORY_LIST_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("ZeroPageCount", ctypes.c_size_t), ("FreePageCount", ctypes.c_size_t),
        ("ModifiedPageCount", ctypes.c_size_t), ("ModifiedNoWritePageCount", ctypes.c_size_t),
        ("BadPageCount", ctypes.c_size_t), ("PageCountByPriority", ctypes.c_size_t * 8),
        ("RepurposedPagesByPriority", ctypes.c_size_t * 8), ("ModifiedPageCountPageFile", ctypes.c_size_t),
    ]


class SYSTEM_FILECACHE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("CurrentSize", ctypes.c_size_t), ("PeakSize", ctypes.c_size_t), ("PageFaultCount", wintypes.ULONG),
        ("MinimumWorkingSet", ctypes.c_size_t), ("MaximumWorkingSet", ctypes.c_size_t),
        ("CurrentSizeIncludingTransitionInPages", ctypes.c_size_t), ("PeakSizeIncludingTransitionInPages", ctypes.c_size_t),
        ("TransitionRePurposeCount", wintypes.ULONG), ("Flags", wintypes.ULONG),
    ]


class MEMORY_COMBINE_INFORMATION_EX(ctypes.Structure):
    _fields_ = [("Handle", wintypes.HANDLE), ("PagesCombined", ctypes.c_size_t), ("Flags", wintypes.ULONG)]


class SYSTEM_INFO(ctypes.Structure):
    _fields_ = [
        ("wProcessorArchitecture", wintypes.WORD), ("wReserved", wintypes.WORD), ("dwPageSize", wintypes.DWORD),
        ("lpMinimumApplicationAddress", wintypes.LPVOID), ("lpMaximumApplicationAddress", wintypes.LPVOID),
        ("dwActiveProcessorMask", ctypes.c_size_t), ("dwNumberOfProcessors", wintypes.DWORD),
        ("dwProcessorType", wintypes.DWORD), ("dwAllocationGranularity", wintypes.DWORD),
        ("wProcessorLevel", wintypes.WORD), ("wProcessorRevision", wintypes.WORD),
    ]


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]


class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", wintypes.BYTE), ("BatteryFlag", wintypes.BYTE), ("BatteryLifePercent", wintypes.BYTE),
        ("SystemStatusFlag", wintypes.BYTE), ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD), ("bLeftTrigger", wintypes.BYTE), ("bRightTrigger", wintypes.BYTE),
        ("sThumbLX", wintypes.SHORT), ("sThumbLY", wintypes.SHORT), ("sThumbRX", wintypes.SHORT), ("sThumbRY", wintypes.SHORT),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XINPUT_GAMEPAD)]


class XINPUT_VIBRATION(ctypes.Structure):
    _fields_ = [("wLeftMotorSpeed", wintypes.WORD), ("wRightMotorSpeed", wintypes.WORD)]


ntdll.NtSetSystemInformation.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
ntdll.NtSetSystemInformation.restype = ctypes.c_long
ntdll.NtQuerySystemInformation.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
ntdll.NtQuerySystemInformation.restype = ctypes.c_long
ntdll.RtlNtStatusToDosError.argtypes = [ctypes.c_long]
ntdll.RtlNtStatusToDosError.restype = ctypes.c_ulong
kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
kernel32.GetSystemInfo.argtypes = [ctypes.POINTER(SYSTEM_INFO)]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.GetTickCount64.restype = ctypes.c_ulonglong
kernel32.GetSystemPowerStatus.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]
kernel32.GetPhysicallyInstalledSystemMemory.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenEventW.restype = wintypes.HANDLE
kernel32.SetEvent.argtypes = [wintypes.HANDLE]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.GetCurrentProcessId.restype = wintypes.DWORD
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(LUID)]
advapi32.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(TOKEN_PRIVILEGES), wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetMessageExtraInfo.restype = ctypes.c_size_t
user32.GetAncestor.restype = wintypes.HWND
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
if dwmapi:
    dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]


def set_dpi_awareness():
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)  # per-monitor: sharp text on the 2560x1600 panel
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def is_admin():
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def enable_privileges():
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0020 | 0x0008, ctypes.byref(token)):
        return
    try:
        for name in ("SeProfileSingleProcessPrivilege", "SeIncreaseQuotaPrivilege", "SeDebugPrivilege"):
            luid = LUID()
            if not advapi32.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
                continue
            tp = TOKEN_PRIVILEGES()
            tp.PrivilegeCount = 1
            tp.Privileges[0].Luid = luid
            tp.Privileges[0].Attributes = 0x00000002
            advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
    finally:
        kernel32.CloseHandle(token)


def _page_size():
    si = SYSTEM_INFO()
    kernel32.GetSystemInfo(ctypes.byref(si))
    return si.dwPageSize or 4096


PAGE = _page_size()


# =====================================================================  memory operations

def memory_status():
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m


def memory_lists():
    info = SYSTEM_MEMORY_LIST_INFORMATION()
    if ntdll.NtQuerySystemInformation(SystemMemoryListInformation, ctypes.byref(info), ctypes.sizeof(info), None) != 0:
        return None
    standby = [info.PageCountByPriority[i] * PAGE for i in range(8)]
    return {
        "free": (info.ZeroPageCount + info.FreePageCount) * PAGE,
        "standby": sum(standby),
        "standby_by_priority": standby,
        "modified": (info.ModifiedPageCount + info.ModifiedNoWritePageCount) * PAGE,
    }


def nt_check(status):
    if status != 0:
        code = ntdll.RtlNtStatusToDosError(status)
        raise OSError(ctypes.FormatError(code).strip() or f"NTSTATUS 0x{status & 0xFFFFFFFF:08X}")


def memory_command(cmd):
    value = ctypes.c_int(cmd)
    nt_check(ntdll.NtSetSystemInformation(SystemMemoryListInformation, ctypes.byref(value), ctypes.sizeof(value)))


def flush_file_cache():
    info = SYSTEM_FILECACHE_INFORMATION()
    info.MinimumWorkingSet = ctypes.c_size_t(-1).value
    info.MaximumWorkingSet = ctypes.c_size_t(-1).value
    nt_check(ntdll.NtSetSystemInformation(SystemFileCacheInformationEx, ctypes.byref(info), ctypes.sizeof(info)))


def combine_pages():
    info = MEMORY_COMBINE_INFORMATION_EX()
    nt_check(ntdll.NtSetSystemInformation(SystemCombinePhysicalMemoryInformation, ctypes.byref(info), ctypes.sizeof(info)))


def free_now():
    lists = memory_lists()
    return lists["free"] if lists else memory_status().ullAvailPhys


def list_processes():
    snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    result = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            pid = entry.th32ProcessID
            if pid > 4:
                h = kernel32.OpenProcess(0x1000, False, pid)
                if h:
                    pmc = PROCESS_MEMORY_COUNTERS()
                    pmc.cb = ctypes.sizeof(pmc)
                    if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                        result.append((pid, entry.szExeFile, pmc.WorkingSetSize))
                    kernel32.CloseHandle(h)
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    result.sort(key=lambda p: p[2], reverse=True)
    return result


def working_set(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return 0
    try:
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(pmc)
        return pmc.WorkingSetSize if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb) else 0
    finally:
        kernel32.CloseHandle(h)


def empty_working_set(pid):
    h = kernel32.OpenProcess(0x0400 | 0x0100, False, pid)
    if not h:
        return False
    try:
        return bool(psapi.EmptyWorkingSet(h))
    finally:
        kernel32.CloseHandle(h)


def trim_process(pid):
    before = working_set(pid)
    ok = empty_working_set(pid)
    return ok, max(0, before - working_set(pid)) if ok else 0


# Never trimmed by Game Boost: core Windows pieces whose trimming causes stutter, plus
# overlays and the Legion Go's own software (Legion Space drives the controllers & quick settings).
BOOST_PROTECT = {"csrss.exe", "dwm.exe", "audiodg.exe", "smss.exe", "wininit.exe", "winlogon.exe", "lsass.exe",
                 "services.exe", "fontdrvhost.exe", "textinputhost.exe", "ctfmon.exe", "registry", "memcompression"}
BOOST_PROTECT_PARTS = ("legion", "lenovo", "steam", "gamebar", "xbox", "rtss", "afterburner", "radeon", "amdrs",
                       "amdow", "handheldcompanion", "ramopt", "vanta")
# Full-screen apps that aren't games (for "Game Boost when a game starts").
NOT_GAMES = {"explorer.exe", "applicationframehost.exe", "msedge.exe", "chrome.exe", "firefox.exe", "brave.exe",
             "opera.exe", "vlc.exe", "mpc-hc64.exe", "wmplayer.exe", "textinputhost.exe", "lockapp.exe",
             "searchhost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe", "mstsc.exe", "powerpnt.exe",
             "playnite.fullscreenapp.exe", "video.ui.exe", "python.exe", "pythonw.exe"}
NOT_GAME_PARTS = ("legion", "steam", "xbox", "gamebar", "epicgameslauncher", "galaxyclient", "eadesktop",
                  "ubisoftconnect", "battle.net", "handheldcompanion", "rtss", "ramopt", "vanta")


def foreground_pid():
    pid = wintypes.DWORD()
    hwnd = user32.GetForegroundWindow()
    if hwnd:
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def game_boost():
    """Trim background apps (not the game in front, overlays or Legion software), flush, gentle purge."""
    started = time.time()
    before = free_now()
    own = os.getpid()
    fg = foreground_pid()
    trimmed = 0
    for pid, name, _ in list_processes():
        low = name.lower()
        if pid in (own, fg) or low in BOOST_PROTECT or any(p in low for p in BOOST_PROTECT_PARTS):
            continue
        if empty_working_set(pid):
            trimmed += 1
    memory_command(MemoryFlushModifiedList)
    memory_command(MemoryPurgeLowPriorityStandbyList)
    time.sleep(0.2)
    return max(0, free_now() - before), time.time() - started, trimmed


def run_action(action):
    started = time.time()
    before = free_now()
    if action == "workingsets":
        memory_command(MemoryEmptyWorkingSets)
    elif action == "standby":
        memory_command(MemoryPurgeStandbyList)
    elif action == "standbylow":
        memory_command(MemoryPurgeLowPriorityStandbyList)
    elif action == "modified":
        memory_command(MemoryFlushModifiedList)
    elif action == "filecache":
        flush_file_cache()
    elif action == "combine":
        combine_pages()
    elif action == "all":
        memory_command(MemoryEmptyWorkingSets)
        flush_file_cache()
        memory_command(MemoryFlushModifiedList)
        memory_command(MemoryPurgeStandbyList)
    time.sleep(0.15)
    return max(0, free_now() - before), time.time() - started


ACTIONS = {
    "boost": ("Game Boost", "Free RAM before you play"),
    "all": ("Optimize all", "Strongest clean-up"),
    "standbylow": ("Gentle clean", "Low-priority cache only"),
    "standby": ("Purge standby", "All cached memory"),
    "workingsets": ("Working sets", "Idle memory of every app"),
    "modified": ("Flush modified", "Write changed pages to disk"),
    "filecache": ("File cache", "Shrink the system file cache"),
    "combine": ("Combine pages", "Merge identical pages"),
}
TILE_ORDER = ["boost", "all", "standbylow", "standby", "workingsets", "modified", "filecache", "combine"]
TILE_PAD = {"boost": "X", "all": "Y"}
AUTO_ACTIONS = ["standbylow", "boost", "standby", "all", "workingsets"]


# =====================================================================  device info

def device_info():
    """Read the model from the BIOS strings, e.g. 'Legion Go 8APU1' (machine type 83E1)."""
    vals = {}
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS")
        for n in ("SystemFamily", "SystemVersion", "SystemProductName", "SystemManufacturer"):
            try:
                vals[n] = str(winreg.QueryValueEx(key, n)[0]).strip()
            except OSError:
                vals[n] = ""
    except Exception:
        pass
    blob = " ".join(vals.values()).lower()
    legion = "legion go" in blob
    name = ""
    for k in ("SystemFamily", "SystemVersion"):
        if "legion" in vals.get(k, "").lower():
            name = vals[k]
            break
    name = name or vals.get("SystemProductName") or "Windows PC"
    variant = ""
    if legion:
        variant = "go2" if "go 2" in blob else "gos" if "go s" in blob else "go"
    return {"name": name, "legion": legion, "variant": variant}


def installed_ram():
    kb = ctypes.c_ulonglong()
    try:
        if kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(kb)):
            return kb.value * 1024
    except Exception:
        pass
    return 0


def power_status():
    s = SYSTEM_POWER_STATUS()
    if not kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return None
    flag = s.BatteryFlag & 0xFF
    return {"ac": s.ACLineStatus == 1, "pct": s.BatteryLifePercent & 0xFF,
            "battery": flag != 255 and not flag & 128, "charging": bool(flag & 8)}


def process_name(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(h)
    return ""


def fullscreen_app(own_hwnd):
    """(pid, exe) of the full-screen app in front if it looks like a game, else None."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd or hwnd == own_hwnd:
        return None
    cls = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, cls, 128)
    if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Windows.UI.Core.CoreWindow"):
        return None
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(mi)):
        return None
    m = mi.rcMonitor
    if not (r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom):
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = process_name(pid.value)
    low = name.lower()
    if not name or low in NOT_GAMES or any(p in low for p in NOT_GAME_PARTS) or pid.value == os.getpid():
        return None
    return pid.value, name


# =====================================================================  start with Windows

TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Starts Vanta in the tray at sign-in.</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId><Delay>PT15S</Delay></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>{cmd}</Command><Arguments>{args}</Arguments></Exec></Actions>
</Task>
"""


def _schtasks(*args):
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, creationflags=0x08000000)


def startup_enabled():
    try:
        if _schtasks("/query", "/tn", TASK_NAME).returncode == 0:
            return True
        for old in OLD_TASK_NAMES:
            if _schtasks("/query", "/tn", old).returncode == 0:
                # upgrade from an older name: point the sign-in task at this exe under the new name
                if set_startup(True):
                    _schtasks("/delete", "/f", "/tn", old)
                    return True
        return False
    except Exception:
        return False


def set_startup(on):
    """A scheduled task (not the Run key) so it starts elevated without a UAC prompt, and on battery."""
    if not on:
        return _schtasks("/delete", "/f", "/tn", TASK_NAME).returncode == 0
    if FROZEN:
        cmd, args = sys.executable, "--tray"
    else:
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        cmd = pyw if os.path.exists(pyw) else sys.executable
        args = f'"{os.path.abspath(sys.argv[0])}" --tray'
    user = "\\".join(p for p in (os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", "")) if p)
    path = os.path.join(os.environ.get("TEMP") or os.environ.get("TMP") or os.path.expanduser("~"), "vanta_task.xml")
    with open(path, "w", encoding="utf-16") as f:
        f.write(TASK_XML.format(user=escape(user), cmd=escape(cmd), args=escape(args)))
    try:
        return _schtasks("/create", "/f", "/tn", TASK_NAME, "/xml", path).returncode == 0
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# =====================================================================  controller

PAD_BUTTONS = [
    (0x0001, "up"), (0x0002, "down"), (0x0004, "left"), (0x0008, "right"), (0x0010, "start"), (0x0020, "back"),
    (0x0040, "ls"), (0x0080, "rs"), (0x0100, "lb"), (0x0200, "rb"), (0x1000, "a"), (0x2000, "b"), (0x4000, "x"), (0x8000, "y"),
    (0x10000, "lt"), (0x20000, "rt"),
]
PAD_REPEAT = {"up", "down", "left", "right", "lt", "rt"}


class Gamepad:
    """XInput: the Legion Go's attached controllers show up as an Xbox pad."""

    @staticmethod
    def create():
        for name in ("xinput1_4", "xinput9_1_0", "xinput1_3"):
            try:
                return Gamepad(ctypes.WinDLL(name))
            except (OSError, AttributeError):
                continue
        return None

    def __init__(self, dll):
        self.get = dll.XInputGetState
        self.get.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_STATE)]
        self.get.restype = wintypes.DWORD
        self.set = dll.XInputSetState
        self.set.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_VIBRATION)]
        try:
            self.getbat = dll.XInputGetBatteryInformation
            self.getbat.argtypes = [wintypes.DWORD, ctypes.c_ubyte, ctypes.POINTER(ctypes.c_ubyte * 2)]
        except AttributeError:
            self.getbat = None
        self.slot = None
        self.prev = 0
        self.next_scan = 0.0
        self.repeat_at = {}
        self.hid = None  # the Legion listener: its report works when XInput can't see the controllers (DirectInput mode)
        self.axis_seen_center = [False, False]  # a stick axis only counts once it has been seen resting near the middle
        self.held_since = {}   # bit -> when it went down
        self.stuck = 0         # bits ignored because they never let go (a drifting stick or a misread report)
        self.stick_nav = True

    def hid_state(self):
        st = getattr(self.hid, "pad_state", None) if self.hid else None
        return st if st and time.time() - st[0] < 1.0 else None

    @property
    def connected(self):
        return self.slot is not None or self.hid_state() is not None

    def _read(self, i):
        st = XINPUT_STATE()
        return st if self.get(i, ctypes.byref(st)) == 0 else None

    def hid_bits(self):
        """XInput-style bits from the Legion controller's own report (works in every controller mode)."""
        hs = self.hid_state()
        if not hs:
            return None
        _, b, lx, ly, lt, rt = hs
        # The left stick moves the selection only when the Xbox (XInput) pad can't be seen (it reads the sticks better),
        # and only once each axis has been seen resting near the middle: a byte that sits at an extreme (or a stick that
        # drifts a lot) would otherwise hold "up" or "left" down forever.
        for i, v in enumerate((lx, ly)):
            if abs(v) < 0.2:
                self.axis_seen_center[i] = True
        if self.stick_nav and self.slot is None:
            if self.axis_seen_center[1]:
                if ly < -0.6:
                    b |= 0x0001
                elif ly > 0.6:
                    b |= 0x0002
            if self.axis_seen_center[0]:
                if lx < -0.6:
                    b |= 0x0004
                elif lx > 0.6:
                    b |= 0x0008
        if lt > 128:
            b |= 0x10000
        if rt > 128:
            b |= 0x20000
        return b

    def poll(self):
        """Presses from the Xbox (XInput) pad and from the Legion controller's own report, merged, so whichever one
        actually carries your presses works (a virtual or silent XInput pad can't hide the real controller)."""
        now = time.time()
        hb = self.hid_bits()
        xb = self._xinput_bits(now)
        self.last_src = (xb, hb)
        if xb is None and hb is None:
            if self.prev:
                self.prev = 0
            return []
        return self._events(self._unstick((xb or 0) | (hb or 0), now), now)

    def _unstick(self, b, now):
        """Directions held without a break for 8 seconds are almost never a person: ignore them until they let go."""
        for mask in (0x0001, 0x0002, 0x0004, 0x0008):
            if b & mask:
                t0 = self.held_since.setdefault(mask, now)
                if now - t0 > 8 and not self.stuck & mask:
                    self.stuck |= mask
            else:
                self.held_since.pop(mask, None)
                self.stuck &= ~mask
        return b & ~self.stuck

    def _xinput_bits(self, now):
        if self.slot is None:
            if now < self.next_scan:
                return None
            self.next_scan = now + 2.0
            for i in range(4):
                if self._read(i):
                    self.slot, self.prev = i, 0x3FFFF
                    break
            if self.slot is None:
                return None
        st = self._read(self.slot)
        if st is None:
            self.slot = None
            return None
        g = st.Gamepad
        b = g.wButtons
        if self.stick_nav:
            if g.sThumbLY > 20000:
                b |= 0x0001
            elif g.sThumbLY < -20000:
                b |= 0x0002
            if g.sThumbLX < -20000:
                b |= 0x0004
            elif g.sThumbLX > 20000:
                b |= 0x0008
        if g.bLeftTrigger & 0xFF > 128:
            b |= 0x10000
        if g.bRightTrigger & 0xFF > 128:
            b |= 0x20000
        return b

    def _events(self, b, now):
        events = []
        for mask, name in PAD_BUTTONS:
            if not b & mask:
                continue
            if not self.prev & mask:
                events.append(name)
                self.repeat_at[name] = now + 0.42
            elif name in PAD_REPEAT and now >= self.repeat_at.get(name, now + 1):
                events.append(name)
                self.repeat_at[name] = now + 0.085
        self.prev = b
        return events

    def battery(self):
        """'FULL' / 'MED' / 'LOW' / 'EMPTY' for battery-powered pads, None when wired or unknown."""
        if self.slot is None or not self.getbat:
            return None
        info = (ctypes.c_ubyte * 2)()
        if self.getbat(self.slot, 0, ctypes.byref(info)) != 0 or info[0] not in (2, 3):
            return None
        return ("EMPTY", "LOW", "MED", "FULL")[min(3, info[1])]

    def rumble(self, strength=0.35, ms=140):
        slot = self.slot
        if slot is None:
            return

        def run():
            v = int(65535 * strength)
            self.set(slot, ctypes.byref(XINPUT_VIBRATION(v, v)))
            time.sleep(ms / 1000)
            self.set(slot, ctypes.byref(XINPUT_VIBRATION(0, 0)))

        threading.Thread(target=run, daemon=True).start()


# =====================================================================  themes & config

THEMES = {
    # Vanta's signature look: graphite, neutral type, one quiet accent, art-led Play tab ("premium").
    "Vanta": dict(bg="#0a0b0f", panel="#12141a", panel2="#1a1d25", line="#242833", text="#f3f5fa", muted="#8b92a5",
                  accent="#8b7bff", accent_text="#ffffff", accent2="#4fd1ff", warn="#ffb84d", danger="#ff5c6c", good="#3ddc97",
                  dark=True, premium=True),
    "Vanta OLED": dict(bg="#000000", panel="#0c0d10", panel2="#15171d", line="#202330", text="#f3f5fa", muted="#878ea1",
                       accent="#8b7bff", accent_text="#ffffff", accent2="#4fd1ff", warn="#ffb84d", danger="#ff5c6c", good="#3ddc97",
                       dark=True, premium=True),
    "Midnight": dict(bg="#0b0f17", panel="#131a28", panel2="#1b2436", line="#27324a", text="#e9eef8", muted="#8e9ab0",
                     accent="#3d8bff", accent_text="#ffffff", accent2="#8a6cff", warn="#ffb547", danger="#ff5d6c", good="#35d49a", dark=True),
    "OLED Black": dict(bg="#000000", panel="#0b0b0b", panel2="#151515", line="#262626", text="#f2f2f2", muted="#8a8a8a",
                       accent="#00c8ff", accent_text="#001018", accent2="#b36bff", warn="#ffbf3c", danger="#ff4d5e", good="#2ee59d", dark=True),
    "Phosphor": dict(bg="#020a04", panel="#06150a", panel2="#0b2212", line="#14432a", text="#b4ffc8", muted="#56a872",
                     accent="#3cff78", accent_text="#00160a", accent2="#78ffd2", warn="#ffd23c", danger="#ff5a50", good="#3cff78", dark=True),
    "Amber": dict(bg="#0d0800", panel="#1a1100", panel2="#251800", line="#4a3200", text="#ffd98a", muted="#a8823a",
                  accent="#ffb000", accent_text="#1a1000", accent2="#ffe680", warn="#ff8c1a", danger="#ff5a3c", good="#d6ff6a", dark=True),
    "Cyberpunk": dict(bg="#0d0221", panel="#170536", panel2="#230a4c", line="#3c1b70", text="#f4ecff", muted="#9d89c4",
                      accent="#ff2bd6", accent_text="#ffffff", accent2="#00e5ff", warn="#ffe600", danger="#ff3b5c", good="#00ffa3", dark=True),
    "Glacier": dict(bg="#0d1922", panel="#132533", panel2="#1a3143", line="#284a62", text="#e6f5ff", muted="#8fb1c9",
                    accent="#7fd6ff", accent_text="#04131d", accent2="#a8b8ff", warn="#ffd27f", danger="#ff7f8f", good="#7fffcf", dark=True),
    "Ember": dict(bg="#140806", panel="#200e0a", panel2="#2c140e", line="#4f2318", text="#ffe8de", muted="#bb8d7f",
                  accent="#ff5a1f", accent_text="#ffffff", accent2="#ffb020", warn="#ffd03c", danger="#ff3048", good="#9be564", dark=True),
    "Daylight": dict(bg="#eef1f6", panel="#ffffff", panel2="#f3f5f9", line="#d6dce7", text="#10141c", muted="#5b6578",
                     accent="#0a5cff", accent_text="#ffffff", accent2="#7a3cff", warn="#b86e00", danger="#d01e36", good="#0f8a55", dark=False),
    "Synthwave": dict(bg="#1a0b2e", panel="#241040", panel2="#2f1652", line="#4a2370", text="#fbe9ff", muted="#b392c9",
                      accent="#ff6ad5", accent_text="#1a0b2e", accent2="#29d6ff", warn="#ffd166", danger="#ff4f79", good="#3cf5c5", dark=True),
    "Forest": dict(bg="#0c140f", panel="#132019", panel2="#1a2b21", line="#2a4434", text="#e4f2e7", muted="#8fae98",
                   accent="#5fd38d", accent_text="#06140b", accent2="#c3e88d", warn="#f2c14e", danger="#f0605d", good="#5fd38d", dark=True),
    "Ocean": dict(bg="#06141f", panel="#0b1f2e", panel2="#112a3d", line="#1d4260", text="#e2f2ff", muted="#85a8c2",
                  accent="#2ec4ff", accent_text="#021018", accent2="#36e2c8", warn="#ffc857", danger="#ff6b6b", good="#36e2a0", dark=True),
    "Rose": dict(bg="#170a10", panel="#22101a", panel2="#2e1623", line="#4c2539", text="#ffe9f1", muted="#c08da3",
                 accent="#ff6f9f", accent_text="#1a0710", accent2="#ffb38a", warn="#ffd27a", danger="#ff4d4d", good="#7fe0b0", dark=True),
    "Mono": dict(bg="#0e0e0e", panel="#181818", panel2="#232323", line="#363636", text="#eeeeee", muted="#8c8c8c",
                 accent="#f2f2f2", accent_text="#000000", accent2="#a8a8a8", warn="#d4b25c", danger="#e06666", good="#9ccc9c", dark=True),
    "High Contrast": dict(bg="#000000", panel="#000000", panel2="#141414", line="#ffffff", text="#ffffff", muted="#e8e8e8",
                          accent="#ffff00", accent_text="#000000", accent2="#00ffff", warn="#ffbf00", danger="#ff4040", good="#00ff7f", dark=True),
    "Sandstone": dict(bg="#f4efe6", panel="#fffaf2", panel2="#f1e9db", line="#dccfb8", text="#2b2116", muted="#7a6a55",
                      accent="#c2581b", accent_text="#ffffff", accent2="#2f7d6d", warn="#a66a00", danger="#b3261e", good="#2e7d32", dark=False),
    "Lavender": dict(bg="#f3f0fb", panel="#ffffff", panel2="#f2eefb", line="#dcd3f0", text="#1e1633", muted="#6b5f8a",
                     accent="#6c47ff", accent_text="#ffffff", accent2="#e0457b", warn="#a86b00", danger="#c9184a", good="#1b8a5a", dark=False),
}
# Optional theme keys: grad (colour stops) + angle, fx (animated background), glass (see-through cards),
# outline (flat outlined cards), round (corner radius factor), scale (density), mono (monospace font).
_D = dict(warn="#ffd166", danger="#ff5d73", good="#5eead4", dark=True)
THEMES.update({
    # ---- gradient
    "Sunset": dict(_D, grad=["#1b0f2e", "#4a1a3f", "#7a2f2f"], angle=120, bg="#2f1438", panel="#1c0f24", panel2="#2a1733",
                   line="#4a2a52", text="#fff0ea", muted="#c9a3b0", accent="#ff8a5c", accent_text="#1b0f2e", accent2="#ffc15e",
                   good="#7ee8a7", glass=True),
    "Deep Sea": dict(_D, grad=["#020617", "#0b2747", "#04303a"], angle=100, fx="bubbles", bg="#071a33", panel="#06142a",
                     panel2="#0b1f3a", line="#163a5c", text="#e0f4ff", muted="#7fa6c2", accent="#22d3ee", accent_text="#02141c",
                     accent2="#60a5fa", glass=True),
    "Twilight": dict(_D, grad=["#0f172a", "#312e81", "#4c1d95"], angle=140, bg="#22205a", panel="#111735", panel2="#1a2048",
                     line="#323a75", text="#eef2ff", muted="#a5b0db", accent="#a5b4fc", accent_text="#111735", accent2="#f0abfc",
                     glass=True),
    "Emerald": dict(_D, grad=["#021a12", "#064e3b", "#022c22"], angle=110, bg="#053b2c", panel="#03221a", panel2="#073326",
                    line="#145a45", text="#e7fff5", muted="#86c9b0", accent="#34d399", accent_text="#022019", accent2="#a3e635",
                    glass=True),
    "Peach": dict(_D, grad=["#fff4e6", "#ffe3e3", "#f3e8ff"], angle=125, bg="#fff0ee", panel="#ffffff", panel2="#fff6f2",
                  line="#f1d9d4", text="#2a1a1f", muted="#8a6b70", accent="#ff6b4a", accent_text="#ffffff", accent2="#8b5cf6",
                  warn="#b45309", danger="#dc2626", good="#15803d", dark=False, glass=True),
    "Mint": dict(_D, grad=["#ecfdf5", "#e0f2fe"], angle=135, bg="#e6f8f8", panel="#ffffff", panel2="#f3fbf8", line="#cfe8de",
                 text="#0f2a22", muted="#5b7b70", accent="#10b981", accent_text="#ffffff", accent2="#0ea5e9",
                 warn="#b45309", danger="#dc2626", good="#059669", dark=False, glass=True),
    # ---- animated
    "Flow": dict(_D, grad=["#0f1d4a", "#3b1c7a", "#6b1747", "#0f1d4a"], angle=135, fx="flow", bg="#241a5a", panel="#0d1230",
                 panel2="#161b42", line="#2c3168", text="#eef0ff", muted="#9aa3d6", accent="#7dd3fc", accent_text="#06122a",
                 accent2="#f0abfc", glass=True),
    "Starfield": dict(_D, grad=["#07021a", "#24093f", "#0a1a3a"], angle=120, fx="stars", bg="#140630", panel="#0e0624",
                      panel2="#180b34", line="#2e1a55", text="#f1e9ff", muted="#a493c9", accent="#c084fc", accent_text="#14062a",
                      accent2="#60a5fa", glass=True),
    "Aurora": dict(_D, grad=["#03191a", "#0a2f33", "#140f38"], angle=110, fx="aurora", bg="#082426", panel="#071d22",
                   panel2="#0c2a30", line="#1d4a50", text="#e6fffa", muted="#86b8b0", accent="#34f5c5", accent_text="#02201a",
                   accent2="#a78bfa", glass=True),
    "Matrix": dict(_D, bg="#000500", fx="rain", panel="#010d03", panel2="#03170a", line="#0c3a18", text="#b6ffc8",
                   muted="#4f9f63", accent="#22ff66", accent_text="#001a08", accent2="#9dffb8", warn="#e6ff4d", danger="#ff5050",
                   good="#22ff66", glass=True, mono=True, round=0.4),
    "Retro Grid": dict(_D, grad=["#0d0221", "#2d0a4e", "#3a0b45"], angle=90, fx="grid", bg="#1d0638", panel="#140433",
                       panel2="#1f0a47", line="#3c1a70", text="#fdf0ff", muted="#b392c9", accent="#ff2bd6", accent_text="#ffffff",
                       accent2="#29d6ff", good="#3cf5c5", glass=True),
    "Lava": dict(_D, grad=["#1a0400", "#3a0c02", "#120200"], angle=95, fx="embers", bg="#2a0801", panel="#1a0703",
                 panel2="#2a0e06", line="#4f1d0e", text="#ffe9dc", muted="#c28b74", accent="#ff6a1a", accent_text="#1a0400",
                 accent2="#ffc23d", good="#a3e635", glass=True),
    "Snowfall": dict(_D, grad=["#0b1622", "#14283b"], angle=90, fx="snow", bg="#0f1f2f", panel="#0f1e2d", panel2="#16283a",
                     line="#26405a", text="#eef6ff", muted="#94aec6", accent="#9fd8ff", accent_text="#08131d", accent2="#c7b8ff",
                     glass=True),
    "CRT": dict(_D, bg="#020a04", fx="scan", panel="#06150a", panel2="#0b2212", line="#14432a", text="#b4ffc8", muted="#56a872",
                accent="#3cff78", accent_text="#00160a", accent2="#78ffd2", warn="#ffd23c", danger="#ff5a50", good="#3cff78",
                glass=True, mono=True, round=0.3),
    # ---- minimal & compact
    "Minimal Dark": dict(_D, bg="#0f0f10", panel="#0f0f10", panel2="#18181b", line="#2c2c31", text="#f4f4f5", muted="#8b8b94",
                         accent="#f4f4f5", accent_text="#0f0f10", accent2="#a1a1aa", warn="#e0b04a", danger="#f87171",
                         good="#86efac", outline=True, round=0.35, scale=0.86),
    "Minimal Light": dict(_D, bg="#fafafa", panel="#fafafa", panel2="#f1f1f2", line="#dcdce0", text="#18181b", muted="#71717a",
                          accent="#18181b", accent_text="#fafafa", accent2="#52525b", warn="#a16207", danger="#dc2626",
                          good="#15803d", dark=False, outline=True, round=0.35, scale=0.86),
    "Terminal": dict(_D, bg="#000000", panel="#000000", panel2="#0a120b", line="#1f3a24", text="#c8ffd4", muted="#5f9a6b",
                     accent="#3cff78", accent_text="#000000", accent2="#7ff0ff", warn="#ffd23c", danger="#ff5a50", good="#3cff78",
                     outline=True, round=0.0, scale=0.84, mono=True),
    "Fjord": dict(_D, bg="#2e3440", panel="#2e3440", panel2="#3b4252", line="#4c566a", text="#eceff4", muted="#a3acbd",
                  accent="#88c0d0", accent_text="#2e3440", accent2="#b48ead", warn="#ebcb8b", danger="#bf616a", good="#a3be8c",
                  outline=True, round=0.5, scale=0.88),
    "Paper": dict(_D, bg="#f6f1e7", panel="#f6f1e7", panel2="#ece5d6", line="#d6ccb8", text="#2b2620", muted="#7a7062",
                  accent="#2b2620", accent_text="#f6f1e7", accent2="#9c4221", warn="#a16207", danger="#b42318", good="#2f6b3a",
                  dark=False, outline=True, round=0.2, scale=0.9),
})
_L = dict(warn="#a16207", danger="#dc2626", good="#15803d", dark=False)
THEMES.update({
    # ---- 9.7: accessibility
    "High Contrast": dict(bg="#000000", panel="#000000", panel2="#121212", line="#ffffff", text="#ffffff", muted="#e6e6e6",
                          accent="#ffd400", accent_text="#000000", accent2="#00e5ff", warn="#ffd400", danger="#ff4d4d", good="#3dff7a",
                          dark=True, outline=True),
    "High Contrast Light": dict(bg="#ffffff", panel="#ffffff", panel2="#f0f0f0", line="#000000", text="#000000", muted="#1a1a1a",
                                accent="#0033cc", accent_text="#ffffff", accent2="#8a0099", warn="#7a4a00", danger="#b00000",
                                good="#006b1f", dark=False, outline=True),
    # ---- 8.7: more animated
    "Fireflies": dict(_D, grad=["#06120c", "#0c2418", "#14140a"], angle=100, fx="fireflies", bg="#0b1d14", panel="#0a1a12",
                      panel2="#10261b", line="#1f4030", text="#f2ffe9", muted="#9ab8a2", accent="#c8f560", accent_text="#0a1a12",
                      accent2="#ffd166", warn="#ffd166", glass=True),
    "Sakura": dict(_D, grad=["#1c0a1a", "#3a1430", "#1a0f2a"], angle=125, fx="petals", bg="#2a0f26", panel="#1d0b1b",
                   panel2="#2a1127", line="#4a2142", text="#fff0f7", muted="#d0a3bd", accent="#ff8fc7", accent_text="#2a0f26",
                   accent2="#ffd1e8", glass=True),
    "Sakura Day": dict(_L, grad=["#fff1f6", "#fde4ef", "#f3e8ff"], angle=130, fx="petals", bg="#fdeef4", panel="#ffffff",
                       panel2="#fff5f9", line="#f2d3e1", text="#2b1622", muted="#8a6577", accent="#e0458a", accent_text="#ffffff",
                       accent2="#8b5cf6", glass=True),
    "Confetti": dict(_D, grad=["#0e0b24", "#1d1240", "#0b1630"], angle=120, fx="confetti", bg="#160f33", panel="#120c2a",
                     panel2="#1b1438", line="#30285e", text="#f5f3ff", muted="#a7a2cf", accent="#ffcc33", accent_text="#1a1200",
                     accent2="#ff5fa2", good="#4ade80", warn="#ffcc33", glass=True),
    "Tide": dict(_D, grad=["#031524", "#06304a", "#03202f"], angle=95, fx="waves", bg="#05263a", panel="#04192a",
                 panel2="#082438", line="#14415f", text="#e3f6ff", muted="#86aec6", accent="#38bdf8", accent_text="#03131f",
                 accent2="#2dd4bf", glass=True),
    "Lagoon": dict(_D, grad=["#022424", "#04403d", "#0b2a3a"], angle=100, fx="waves", bg="#033532", panel="#032523",
                   panel2="#073330", line="#145550", text="#e6fffb", muted="#86c2b9", accent="#5eead4", accent_text="#022321",
                   accent2="#93c5fd", glass=True),
    "Nebula": dict(_D, grad=["#07051a", "#160b33", "#070f26"], angle=125, fx="orbs", bg="#0f0a26", panel="#0c0820",
                   panel2="#150f30", line="#2a2152", text="#f1edff", muted="#a49ccc", accent="#a78bfa", accent_text="#120a2a",
                   accent2="#38bdf8", good="#f472b6", glass=True),
    "Lava Lamp": dict(_D, grad=["#1a0505", "#2a0a0f", "#1a0a02"], angle=110, fx="orbs", bg="#240809", panel="#1a0607",
                      panel2="#280c0d", line="#4a1a1c", text="#fff0e8", muted="#c9968a", accent="#ff6b3d", accent_text="#1a0505",
                      accent2="#ffb02e", good="#ff3d7f", glass=True),
    "Northern Lights": dict(_D, grad=["#020b14", "#04202a", "#12082a"], angle=115, fx="aurora", bg="#04141d", panel="#041119",
                            panel2="#081c26", line="#173847", text="#eafff8", muted="#89b3aa", accent="#4ade80", accent_text="#022012",
                            accent2="#e879f9", good="#22d3ee", glass=True),
    "Blizzard": dict(_D, grad=["#e8f1f8", "#d6e6f3"], angle=90, fx="snow", bg="#dde9f3", panel="#ffffff", panel2="#f2f7fb",
                     line="#c7d8e6", text="#0f1d2a", muted="#5a6f82", accent="#2563eb", accent_text="#ffffff", accent2="#0891b2",
                     warn="#a16207", danger="#dc2626", good="#15803d", dark=False, glass=True),
    "Monsoon": dict(_D, grad=["#0a121c", "#122133", "#0b1622"], angle=95, fx="rain", bg="#0f1b29", panel="#0c1622",
                    panel2="#132233", line="#24384f", text="#e6f0fb", muted="#8ea3ba", accent="#60a5fa", accent_text="#071425",
                    accent2="#a5b4fc", glass=True),
    "Galaxy": dict(_D, grad=["#02030a", "#0a0f2e", "#170a2e"], angle=135, fx="stars", bg="#070a1f", panel="#080b20",
                   panel2="#0f1430", line="#222a55", text="#eef1ff", muted="#9aa2cc", accent="#818cf8", accent_text="#070a1f",
                   accent2="#f472b6", glass=True),
    "Prism": dict(_D, grad=["#3a0d4a", "#0d2f5c", "#0b4a45", "#4a3a0b", "#4a0d2a", "#3a0d4a"], angle=135, fx="flow",
                  bg="#1f1a3a", panel="#120f24", panel2="#1b1733", line="#332d5c", text="#f6f4ff", muted="#aaa6cf",
                  accent="#f0abfc", accent_text="#1f0a24", accent2="#67e8f9", glass=True),
    "Ocean Flow": dict(_D, grad=["#031a33", "#05445e", "#0a2a5c", "#031a33"], angle=120, fx="flow", bg="#062a48",
                       panel="#04182c", panel2="#08223a", line="#17405f", text="#e3f4ff", muted="#88aac4", accent="#22d3ee",
                       accent_text="#02141c", accent2="#818cf8", glass=True),
    "Vaporwave": dict(_D, grad=["#1a0633", "#3d0f5c", "#0f3a5c"], angle=90, fx="grid", bg="#2a0b4a", panel="#1c0838",
                      panel2="#260d48", line="#45207a", text="#fff0fb", muted="#c39bd6", accent="#2ef2ff", accent_text="#0a1a2a",
                      accent2="#ff71ce", good="#05ffa1", glass=True),
    # ---- 8.7: more gradients
    "Dusk": dict(_D, grad=["#141e30", "#35234a", "#5c2a3a"], angle=110, bg="#2a2240", panel="#151a2c", panel2="#1e2238",
                 line="#363a5a", text="#f3efff", muted="#a9a4c6", accent="#fb923c", accent_text="#1a0f05", accent2="#c084fc", glass=True),
    "Citrus": dict(_L, grad=["#fffbe6", "#ecfccb", "#fff1e0"], angle=125, bg="#fbf8e4", panel="#ffffff", panel2="#fbfaf0",
                   line="#e7e3c3", text="#1f2410", muted="#6b6f4f", accent="#65a30d", accent_text="#ffffff", accent2="#ea580c",
                   glass=True),
    "Berry": dict(_D, grad=["#1a0620", "#3b0a3a", "#200a33"], angle=130, bg="#2c0a33", panel="#1c0721", panel2="#280d2e",
                  line="#4a1a50", text="#ffeefa", muted="#c79bc0", accent="#f43f9e", accent_text="#ffffff", accent2="#a78bfa", glass=True),
    "Steel": dict(_D, grad=["#111418", "#1f252d", "#14181d"], angle=100, bg="#1a1f26", panel="#13171c", panel2="#1c2128",
                  line="#2f3640", text="#eef2f6", muted="#94a0ae", accent="#7dd3fc", accent_text="#071520", accent2="#cbd5e1", glass=True),
    # ---- 8.7: more classic
    "Nightshade": dict(bg="#191a21", panel="#21222c", panel2="#2a2c38", line="#3a3c4e", text="#f8f8f2", muted="#9ea2bd",
                       accent="#bd93f9", accent_text="#191a21", accent2="#ff79c6", warn="#f1fa8c", danger="#ff5555", good="#50fa7b", dark=True),
    "Solar Dark": dict(bg="#002b36", panel="#073642", panel2="#0b3f4c", line="#1d5563", text="#eee8d5", muted="#93a1a1",
                       accent="#2aa198", accent_text="#002b36", accent2="#b58900", warn="#cb4b16", danger="#dc322f", good="#859900", dark=True),
    "Campfire": dict(bg="#1d2021", panel="#282828", panel2="#32302f", line="#504945", text="#ebdbb2", muted="#a89984",
                     accent="#fe8019", accent_text="#1d2021", accent2="#fabd2f", warn="#fabd2f", danger="#fb4934", good="#b8bb26", dark=True),
    "Coffee": dict(bg="#1b1411", panel="#251c18", panel2="#2f2420", line="#4a3a33", text="#f3e7dc", muted="#b09a8a",
                   accent="#d4a373", accent_text="#1b1411", accent2="#e9c46a", warn="#e9c46a", danger="#e76f51", good="#90be6d", dark=True),
    "Matcha": dict(_L, bg="#f1f5ea", panel="#fbfdf7", panel2="#eef3e4", line="#d5dfc3", text="#1c2614", muted="#5f6d52",
                   accent="#4d7c0f", accent_text="#ffffff", accent2="#b45309"),
    "Latte": dict(_L, bg="#eff1f5", panel="#ffffff", panel2="#e6e9ef", line="#ccd0da", text="#4c4f69", muted="#7c7f93",
                  accent="#8839ef", accent_text="#ffffff", accent2="#fe640b"),
    "Neon Night": dict(bg="#0a0a12", panel="#12121e", panel2="#1a1a2b", line="#2b2b45", text="#e9e9ff", muted="#8f8fb8",
                       accent="#39ff14", accent_text="#03120a", accent2="#ff2079", warn="#ffe600", danger="#ff3355", good="#39ff14", dark=True),
})
THEME_NAMES = list(THEMES)
MY_THEME = "My theme"
EDIT_SLOTS = [("bg", "Back"), ("panel", "Cards"), ("accent", "Accent"), ("accent2", "Accent 2"), ("text", "Text")]
EDIT_FX = ["none", "stars", "aurora", "snow", "bubbles", "embers", "grid", "rain", "scan", "fireflies", "petals", "confetti", "waves", "orbs"]


def _luma(hexc):
    h = hexc.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def build_custom_theme(spec):
    """A full theme from a few picked colors on top of a base theme."""
    base = THEMES.get(spec.get("base"), THEMES["Midnight"])
    if spec.get("base") == MY_THEME:
        base = THEMES["Midnight"]
    c = spec["colors"]
    d = {k: v for k, v in base.items() if k not in ("grad", "angle", "fx", "glass")}
    bg, panel, text = c["bg"], c["panel"], c["text"]
    d.update(bg=bg, panel=panel, panel2=mix(panel, text, 0.07), line=mix(panel, text, 0.15), text=text, muted=mix(text, bg, 0.42),
             accent=c["accent"], accent_text=text_on_hex(c["accent"]), accent2=c["accent2"], dark=_luma(bg) < 0.5)
    if spec.get("grad"):
        d["grad"] = [bg, mix(bg, c["accent"], 0.32), mix(bg, c["accent2"], 0.28)]
        d["angle"] = 125
    if spec.get("fx") and spec["fx"] != "none":
        d["fx"] = spec["fx"]
    d["outline"] = bool(spec.get("outline"))
    return d


def theme_kind(t):
    return "animated" if t.get("fx") else "gradient" if t.get("grad") else "minimal" if t.get("outline") else "classic"


def grad_color(stops, t):
    t = max(0.0, min(1.0, t))
    seg = t * (len(stops) - 1)
    i = min(int(seg), len(stops) - 2)
    return mix(stops[i], stops[i + 1], seg - i)
# Optional accent colour on top of any theme ("" = the theme's own).
ACCENTS = ["", "#3d8bff", "#00c8ff", "#2ee59d", "#c6ff3d", "#ffb000", "#ff5a1f", "#ff4d5e", "#ff2bd6", "#8a6cff"]


def hx(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def text_on_hex(c):
    r, g, b = hx(c)
    return "#000000" if 0.299 * r + 0.587 * g + 0.114 * b > 150 else "#ffffff"


def mix(a, b, t):
    A, B = hx(a), hx(b)
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(A[i] + (B[i] - A[i]) * t))) for i in range(3))


class Config:
    DEFAULTS = {"auto": False, "free_below_mb": 1024, "used_above": 0, "interval_min": 0, "cooldown_s": 120,
                "action": "standbylow", "theme": "", "ui_scale": 100, "game_boost_auto": False,
                "close_to_tray": True, "rumble": True, "fullscreen": False, "tray_hint_shown": False,
                "clean_sel": ["temp", "wintemp", "recycle", "dumps", "delivery"],
                "accent": "", "follow_windows": False, "light_theme": "Daylight",
                "overlay": False, "overlay_corner": "tr", "overlay_opacity": 85, "overlay_size": 100, "pad_combo": True,
                "game_perf_auto": False, "game_restore": True, "sessions": [], "proc_sort": "mem",
                "stats": {"ram": 0, "disk": 0, "boosts": 0, "cleanups": 0},
                "profile": "", "profile_battery": "", "profile_ac": "", "batt_alert": 15,
                "auto_clean_days": 0, "last_auto_clean": 0,
                "tdp": 15, "tdp_ack": False, "game_profiles": {}, "close_list": [], "game_close_on": False,
                "fps_counter": False, "leak_alert": True, "animations": "on", "smooth_scroll": True,
                "start_tab": "home", "favorites": [], "custom_games": [], "lib_filter": "all", "lib_sort": "recent",
                "focus_min": True, "focus_eco": True, "focus_close": True, "focus_boost": True, "focus_on_play": True,
                "focus_off_after": True, "focus_restore_windows": True, "return_to_hub": True, "hub_minimize": True,
                "focus_keep": ["discord.exe", "obs64.exe", "spotify.exe"], "game_tune": {},
                "legion_buttons": True, "legion_l": "hub", "legion_r": "quick", "legion_l_hold": "taskview",
                "legion_r_hold": "keyboard", "rgb_mode": "keep", "rgb_color": "#00c8ff", "rgb_brightness": 80,
                "game_priority": True, "welcomed": False,
                "discord_presence": False, "discord_app_id": "", "discord_idle": False, "discord_webhook": "",
                "discord_recaps": True, "preview_safe": True, "preview_legion": True, "preview_samples": True,
                "auto_tdp": False, "auto_tdp_target": 60, "auto_tdp_min": 6, "back_map": {}, "back_map_game": {},
                "game_lights": {}, "batt_hist": [], "rom_dirs": [], "save_auto": False,
                "console_mode": False, "osk_style": "vanta", "ui_sounds": False, "sound_volume": 25, "haptics": 2,
                "wallpaper": "", "wallpaper_dim": 55, "update_repo": "", "update_auto": True,
                "pointer_mode": "off", "pointer_sens": 100, "pointer_side": "right", "pointer_axis": "yaw",
                "pointer_invert_x": False, "pointer_invert_y": False, "gyro_hold": True,
                "frametime_graph": True, "bench_results": {}, "sleep_log": [], "topup": False,
                "game_quiet": False, "quiet_pending": None, "lists": {}, "sgdb_key": "", "steam_key": "", "steam_id": "",
                "custom_theme": None, "art_fetch": True, "art_ids": {}, "remote_on": False, "remote_port": 8642, "remote_pin": "", "sync_on": False, "sync_last": 0,
                "preset_gen": "auto", "community_presets": True, "pcgw_info": True,
                "detach_profile": False, "detach_tdp": 0, "detach_hz": 0, "detach_scale": True, "detach_pointer_off": True,
                "deal_alerts": True, "deals_seen": [], "deals_last": 0, "ra_user": "", "ra_key": "", "stream_hosts": [],
                "updates_last": 0, "light_footprint": True, "ls_keep_closed": True, "ls_svc_modes": {}, "ls_svc_off": False, "legion_seen": False, "legion_map": {}, "legion_gyro": {},
                "automations": [], "padmouse_layout": "desktop", "padmouse_sens": 100, "sizes": {}, "lang": "en",
                "net_paused": False, "motion": True, "look_v8": False, "prev_theme": "", "ambient": True, "game_recap": True, "batt_goal": 0, "notes": {}, "genres": {}, "known_games": {}, "gone_games": {}, "launch_args": {}, "people": {}, "person": "", "game_volume": {}, "quiet_others": 100, "sort_caps_auto": False, "batt_warned": "", "stick_nav": True, "plain_pad_v991": False, "game_news": True, "news_seen": {}, "dock_auto": False, "dock_scale": 150, "dock_profile": "", "dock_switch": False, "close_stores": [], "queue": [], "finished": {}, "wol": {}, "launch_extras": {}, "batt_log": [], "weather_place": None, "weather_f": True, "phone_input": True, "game_colors": False, "daynight": False, "day_theme": "Daylight", "night_theme": "Midnight", "day_start": 7, "night_start": 19, "dn_period": "", "home_tools": ["boost", "quick", "focus", "find", "checkup", "menu"], "guest": False, "guest_pin": "", "guest_shelf": "fav", "sleep_after_game": False, "play_days": None, "badges_seen": None, "home_row": "recent", "wrap_told": "", "theme_daily": False, "theme_day": "", "break_every": 0, "daily_limit": 0, "limit_day": "", "limit_warn": "", "layout": "console", "layout_v86": False, "go_hint": False}

    def __init__(self):
        self.data = dict(self.DEFAULTS)
        sources = [CONFIG_PATH] + ([] if os.path.exists(CONFIG_PATH) else OLD_CONFIGS)
        for path in sources:
            try:
                with open(path, encoding="utf-8") as f:
                    self.data.update(json.load(f))
                self.migrated = path != CONFIG_PATH
                break
            except Exception:
                continue
        if getattr(self, "migrated", False):
            self.save()

    def save(self):
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass


def set_portable(on, data):
    """Portable mode keeps settings next to the exe (e.g. on a USB stick)."""
    global CONFIG_PATH
    try:
        if on:
            with open(PORTABLE_FLAG, "w") as f:
                f.write("Vanta keeps its settings in this folder.\n")
            CONFIG_PATH = PORTABLE_CONFIG
        else:
            os.remove(PORTABLE_FLAG)
            CONFIG_PATH = LOCAL_CONFIG
            os.makedirs(os.path.dirname(LOCAL_CONFIG), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except OSError:
        return False


def fmt_bytes(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.0f} {unit}" if unit == "MB" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_ago(ts):
    if not ts:
        return "never"
    d = time.time() - ts
    if d < 90:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    if d < 86400 * 60:
        n = int(d // 86400)
        return "1 day ago" if n == 1 else f"{n} days ago"
    if d < 86400 * 730:
        return f"{int(d // (86400 * 30))} months ago"
    return f"{int(d // (86400 * 365))} years ago"


def fmt_duration(sec):
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m {sec % 60:02d}s" if sec % 60 else f"{sec // 60} min"
    return f"{sec // 3600}h {sec % 3600 // 60:02d}m"


# The Vanta mark: two blades forming a V, in unit coordinates (0..1).
MARK_LEFT = [(0.06, 0.14), (0.31, 0.14), (0.56, 0.88), (0.43, 0.88)]
MARK_RIGHT = [(0.69, 0.14), (0.94, 0.14), (0.66, 0.70), (0.53, 0.70)]


def tray_image(theme, size=64):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=size * 0.22, fill=hx(theme["bg"] if theme["dark"] else "#101418"))
    for pts, col in ((MARK_LEFT, theme["accent"]), (MARK_RIGHT, theme["accent2"])):
        d.polygon([(4 + x * (size - 8), 4 + y * (size - 8)) for x, y in pts], fill=hx(col))
    return img


class Tray:
    def __init__(self, ui):
        import pystray
        self.ui = ui
        call = ui.call
        menu = pystray.Menu(
            pystray.MenuItem("Open Vanta", lambda: call(ui.show), default=True),
            pystray.MenuItem("Quick settings", lambda: call(ui.toggle_quick)),
            pystray.MenuItem("Checkup", lambda: call(lambda: (ui.show(), ui.open_checkup()))),
            pystray.MenuItem("Discord: toggle mute", lambda: call(lambda: ui.discord_voice("mute"))),
            pystray.MenuItem("Game Boost", lambda: call(lambda: ui.run("boost"))),
            pystray.MenuItem("Optimize all", lambda: call(lambda: ui.run("all"))),
            pystray.MenuItem("Auto optimize", lambda: call(lambda: ui.adjust("auto", 1)), checked=lambda item: ui.cfg["auto"]),
            pystray.MenuItem("Mini monitor", lambda: call(ui.toggle_overlay), checked=lambda item: ui.cfg["overlay"]),
            pystray.MenuItem("Profile", pystray.Menu(*[
                pystray.MenuItem(name, (lambda i: (lambda: call(lambda: ui.apply_profile(i))))(pid),
                                 checked=(lambda i: (lambda item: ui.cfg["profile"] == i))(pid), radio=True)
                for pid, name, *_ in systools.PROFILES])),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: call(ui.quit)),
        )
        self.icon = pystray.Icon("vanta", tray_image(ui.t), APP_NAME, menu)
        self.icon.run_detached()

    def notify(self, text):
        try:
            self.icon.notify(text, APP_NAME)
        except Exception:
            pass

    def retheme(self, theme):
        try:
            self.icon.icon = tray_image(theme)
        except Exception:
            pass

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass


# =====================================================================  UI

import systools

ICONS = {"menu": ("", "≡"), "back": ("", "‹"), "search": ("", "⌕"), "checkup": ("", "+"), "themes": ("", "T"), "settings": ("", "S"), "help": ("", "?"),
         "full": ("", "F"), "unfull": ("", "F"), "hide": ("", "_"), "close": ("", "X")}
# ---- languages: the main interface (tabs, menu, settings categories, page titles, common buttons). Anything not
# listed stays in English.
LANG_NAMES = {"en": "English", "es": "Español", "de": "Deutsch", "fr": "Français", "ja": "日本語"}
LANG = {"code": "en"}
STRINGS = {
    "es": {"PLAY": "JUGAR", "MEMORY": "MEMORIA", "CLEAN": "LIMPIAR", "TOOLS": "HERRAMIENTAS", "GAMING": "JUEGO", "STATS": "ESTADÍSTICAS",
           "SYSTEM": "SISTEMA", "STARTUP": "INICIO", "Settings": "Ajustes", "Menu": "Menú", "Themes": "Temas", "Checkup": "Revisión",
           "Help": "Ayuda", "Quick settings": "Ajustes rápidos", "Search settings": "Buscar en ajustes", "Games & library": "Juegos y biblioteca",
           "Performance": "Rendimiento", "Controller & lights": "Mando y luces", "Motion controls": "Controles de movimiento",
           "Power & battery": "Energía y batería", "Mini monitor": "Minimonitor", "Remote & sync": "Remoto y sincronización",
           "Look & feel": "Aspecto", "App & updates": "App y actualizaciones", "Automations": "Automatizaciones",
           "What should I play?": "¿A qué juego?", "Clips & screenshots": "Clips y capturas", "Storage cleanup": "Liberar espacio",
           "Network check": "Revisión de red", "Stream & cloud": "Streaming y nube", "Free games & deals": "Juegos gratis y ofertas",
           "Driver & BIOS updates": "Controladores y BIOS", "Activity log": "Registro", "Keyboard": "Teclado", "Best TDP": "Mejor TDP",
           "Make a theme": "Crear un tema", "Back buttons": "Botones traseros", "Every option, by category": "Todas las opciones, por categoría",
           "When something happens, Vanta does something": "Cuando pasa algo, Vanta actúa", "Search": "Buscar", "CLEAR": "BORRAR",
           "Language": "Idioma", "PLAY NOW": "JUGAR AHORA", "Game settings": "Ajustes del juego"},
    "de": {"PLAY": "SPIELEN", "MEMORY": "SPEICHER", "CLEAN": "BEREINIGEN", "TOOLS": "WERKZEUGE", "GAMING": "GAMING", "STATS": "STATISTIK",
           "SYSTEM": "SYSTEM", "STARTUP": "AUTOSTART", "Settings": "Einstellungen", "Menu": "Menü", "Themes": "Designs", "Checkup": "Check-up",
           "Help": "Hilfe", "Quick settings": "Schnelleinstellungen", "Search settings": "Einstellungen durchsuchen",
           "Games & library": "Spiele & Bibliothek", "Performance": "Leistung", "Controller & lights": "Controller & Licht",
           "Motion controls": "Bewegungssteuerung", "Power & battery": "Energie & Akku", "Mini monitor": "Mini-Monitor",
           "Remote & sync": "Fernsteuerung & Sync", "Look & feel": "Aussehen", "App & updates": "App & Updates",
           "Automations": "Automationen", "What should I play?": "Was spiele ich?", "Clips & screenshots": "Clips & Screenshots",
           "Storage cleanup": "Speicher aufräumen", "Network check": "Netzwerk-Check", "Stream & cloud": "Streaming & Cloud",
           "Free games & deals": "Gratisspiele & Angebote", "Driver & BIOS updates": "Treiber & BIOS", "Activity log": "Protokoll",
           "Keyboard": "Tastatur", "Best TDP": "Beste TDP", "Make a theme": "Design erstellen", "Back buttons": "Rücktasten",
           "Every option, by category": "Alle Optionen nach Kategorie",
           "When something happens, Vanta does something": "Wenn etwas passiert, handelt Vanta", "Search": "Suche", "CLEAR": "LEEREN",
           "Language": "Sprache", "PLAY NOW": "JETZT SPIELEN", "Game settings": "Spieleinstellungen"},
    "fr": {"PLAY": "JOUER", "MEMORY": "MÉMOIRE", "CLEAN": "NETTOYER", "TOOLS": "OUTILS", "GAMING": "JEU", "STATS": "STATS",
           "SYSTEM": "SYSTÈME", "STARTUP": "DÉMARRAGE", "Settings": "Paramètres", "Menu": "Menu", "Themes": "Thèmes", "Checkup": "Bilan",
           "Help": "Aide", "Quick settings": "Réglages rapides", "Search settings": "Rechercher un paramètre",
           "Games & library": "Jeux et bibliothèque", "Performance": "Performances", "Controller & lights": "Manette et lumières",
           "Motion controls": "Détection de mouvement", "Power & battery": "Énergie et batterie", "Mini monitor": "Mini-moniteur",
           "Remote & sync": "À distance et synchro", "Look & feel": "Apparence", "App & updates": "Appli et mises à jour",
           "Automations": "Automatisations", "What should I play?": "À quoi jouer ?", "Clips & screenshots": "Clips et captures",
           "Storage cleanup": "Libérer de l'espace", "Network check": "Test réseau", "Stream & cloud": "Streaming et cloud",
           "Free games & deals": "Jeux gratuits et promos", "Driver & BIOS updates": "Pilotes et BIOS", "Activity log": "Journal",
           "Keyboard": "Clavier", "Best TDP": "Meilleur TDP", "Make a theme": "Créer un thème", "Back buttons": "Boutons arrière",
           "Every option, by category": "Toutes les options, par catégorie",
           "When something happens, Vanta does something": "Quand il se passe quelque chose, Vanta agit", "Search": "Recherche",
           "CLEAR": "EFFACER", "Language": "Langue", "PLAY NOW": "JOUER", "Game settings": "Réglages du jeu"},
    "ja": {"PLAY": "プレイ", "MEMORY": "メモリ", "CLEAN": "クリーン", "TOOLS": "ツール", "GAMING": "ゲーム", "STATS": "統計",
           "SYSTEM": "システム", "STARTUP": "スタートアップ", "Settings": "設定", "Menu": "メニュー", "Themes": "テーマ", "Checkup": "診断",
           "Help": "ヘルプ", "Quick settings": "クイック設定", "Search settings": "設定を検索", "Games & library": "ゲームとライブラリ",
           "Performance": "パフォーマンス", "Controller & lights": "コントローラーとライト", "Motion controls": "モーション操作",
           "Power & battery": "電源とバッテリー", "Mini monitor": "ミニモニター", "Remote & sync": "リモートと同期", "Look & feel": "外観",
           "App & updates": "アプリと更新", "Automations": "オートメーション", "What should I play?": "何をプレイする？",
           "Clips & screenshots": "クリップとスクリーンショット", "Storage cleanup": "ストレージ整理", "Network check": "ネットワーク診断",
           "Stream & cloud": "ストリーミングとクラウド", "Free games & deals": "無料ゲームとセール", "Driver & BIOS updates": "ドライバーとBIOS",
           "Activity log": "ログ", "Keyboard": "キーボード", "Best TDP": "最適なTDP", "Make a theme": "テーマを作る",
           "Back buttons": "背面ボタン", "Every option, by category": "すべての設定をカテゴリー別に",
           "When something happens, Vanta does something": "何かが起きたら、Vantaが自動で実行", "Search": "検索", "CLEAR": "クリア",
           "Language": "言語", "PLAY NOW": "今すぐプレイ", "Game settings": "ゲーム設定"},
}


def tr(text):
    """The current language's version of a main-interface string (English if there isn't one)."""
    return STRINGS.get(LANG["code"], {}).get(text, text)


# ---- automations: "when this happens, do that"
AUTO_TRIGGERS = {"game_start": "A game starts", "game_end": "A game closes", "plugged": "The charger is plugged in",
                 "unplugged": "The charger is unplugged", "batt_low": "Battery drops below", "detached": "The controllers come off",
                 "attached": "The controllers go back on", "time": "It's"}
AUTO_DAYS = ["every day", "weekdays", "weekends"]
AUTO_ACTIONS = {"tdp": "Set wattage", "hz": "Set refresh rate", "brightness": "Set brightness", "thermal": "Set power mode",
                "fan": "Full fan speed", "padmouse": "Controller as mouse", "hdr": "HDR", "downloads": "Pause downloads",
                "open": "Open a game", "mute": "Toggle Discord mute"}
AUTO_TEMPLATES = [
    {"trigger": "unplugged", "action": "tdp", "value": 12, "note": "Save battery when you unplug"},
    {"trigger": "plugged", "action": "tdp", "value": 25, "note": "Full power on the charger"},
    {"trigger": "batt_low", "arg": 20, "action": "hz", "value": 60, "note": "Stretch the last 20%"},
    {"trigger": "detached", "action": "padmouse", "value": "off", "note": "No mouse mode at the desk"},
    {"trigger": "game_start", "action": "downloads", "value": "on", "note": "Quiet network while you play"},
    {"trigger": "time", "arg": 1380, "days": "every day", "action": "brightness", "value": 40, "note": "Dimmer screen late at night"},
]


# Settings are grouped into categories. Each section of settings_items() lands in one category; a few
# single settings are moved by key. (id, title, icon glyph, fallback letter, one-line description)
SETTINGS_CATS = [
    ("preview", "Preview", "\ue890", "P", "Options for the no-admin Preview build"),
    ("games", "Games & library", "\ue8f1", "G", "The hub, game art, ROMs and save backups"),
    ("perf", "Performance", "\ue945", "⚡", "Presets for Gen 1 / Gen 2, focus mode and auto-optimizing"),
    ("legion", "Controller & lights", "\ue7fc", "C", "Legion buttons, back buttons, Auto TDP and RGB"),
    ("motion", "Motion controls", "\ue7c2", "M", "Gyro mouse and the Wii-style pointer"),
    ("power", "Power & battery", "\ue83f", "B", "Power plans, alerts and battery care"),
    ("monitor", "Mini monitor", "\ue7f4", "O", "The always-on-top stats overlay"),
    ("discord", "Discord", "\ue8bd", "D", "Rich Presence, recaps and voice"),
    ("connect", "Remote & sync", "\ue895", "R", "Phone remote and OneDrive sync"),
    ("look", "Look & feel", "\ue790", "L", "Themes, wallpaper, sounds and console mode"),
    ("app", "App & updates", "\ue713", "A", "Startup, tray, portable mode and updates"),
]
SETTINGS_SECTION_CAT = {"PREVIEW": "preview", "HUB & GAMES": "games", "FOCUS MODE": "perf", "AUTO OPTIMIZE": "perf",
                        "WHILE GAMING": "perf", "POWER & BATTERY": "power", "MINI MONITOR": "monitor", "APP": "app",
                        "LEGION BUTTONS & LIGHTS": "legion", "DISCORD": "discord", "MOTION CONTROLS": "motion",
                        "PHONE REMOTE": "connect", "SYNC": "connect", "CONSOLE & FEEL": "look", "UPDATES": "app",
                        "WINDOW & FEEL": "look"}
SETTINGS_KEY_CAT = {"frametime_graph": ("monitor", "MINI MONITOR"), "preset_gen": ("perf", "RECOMMENDED PRESETS"), "community_presets": ("perf", "RECOMMENDED PRESETS"),
                    "pcgw_info": ("perf", "RECOMMENDED PRESETS"), "light_footprint": ("app", "VANTA ITSELF"),
                    "backup": ("app", "BACKUP"), "restore": ("app", "BACKUP"), "theme_code": ("look", "THEME"),
                    "theme_paste": ("look", "THEME"), "lang": ("look", "LANGUAGE"), "motion": ("look", "THEME"), "fan_full": ("power", "COOLING"), "deal_alerts": ("games", "STORES & DEALS"),
                    "ra_user": ("games", "RETROACHIEVEMENTS"), "ra_key": ("games", "RETROACHIEVEMENTS"), "game_priority": ("perf", "WHILE GAMING"),
                    "game_quiet": ("perf", "WHILE GAMING"), "animations": ("look", "THEME"), "follow_windows": ("look", "THEME"),
                    "theme_editor": ("look", "THEME"), "rumble": ("look", "CONSOLE & FEEL"), "ui_scale": ("look", "WINDOW & FEEL")}
TABS = [("home", "HOME"), ("play", "PLAY"), ("memory", "MEMORY"), ("clean", "CLEAN"), ("tools", "TOOLS"), ("games", "GAMING"),
        ("stats", "STATS"), ("system", "SYSTEM"), ("startup", "STARTUP")]
SYSTEM_APPS = {"runtimebroker.exe", "searchhost.exe", "searchindexer.exe", "shellexperiencehost.exe", "startmenuexperiencehost.exe",
               "wmiprvse.exe", "conhost.exe", "dllhost.exe", "taskhostw.exe", "securityhealthsystray.exe", "securityhealthservice.exe",
               "smartscreen.exe", "applicationframehost.exe", "systemsettings.exe", "lockapp.exe", "widgets.exe", "widgetservice.exe",
               "phoneexperiencehost.exe", "crossdeviceservice.exe", "nissrv.exe", "sgrmbroker.exe", "wudfhost.exe", "useroobebroker.exe",
               "backgroundtaskhost.exe", "msedgewebview2.exe", "python.exe", "pythonw.exe", "presentmon.exe", "taskmgr.exe",
               "mpdefendercoreservice.exe", "searchprotocolhost.exe", "searchfilterhost.exe", "audiodg.exe", "rtkauduservice64.exe"}
TAB_IDS = [t[0] for t in TABS]
# the console layout: four sections in the top bar; Tune and Insights hold several tabs, shown as chips
SECTIONS = [("home", "Home", ["home"]), ("library", "Library", ["play"]), ("tune", "Tune", ["memory", "clean", "tools", "games"]),
            ("insights", "Insights", ["stats", "system", "startup"])]
LAYOUTS = {"console": "Console home", "rail": "Side rail", "tabs": "Top tabs"}
# the side rail: groups, icons (Segoe Fluent / MDL2 glyph, letter fallback), page titles and one-line blurbs
RAIL_GROUPS = [(None, ["home", "play"]), ("PERFORMANCE", ["memory", "clean", "tools", "games"]), ("INSIGHTS", ["stats", "system", "startup"])]
RAIL_ICONS = {"home": ("\ue80f", "H"), "play": ("\ue7fc", "P"), "memory": ("\ue950", "M"), "clean": ("\ue74d", "C"), "tools": ("\ue90f", "T"),
              "games": ("\ue945", "G"), "stats": ("\ue9d2", "S"), "system": ("\ue770", "Y"), "startup": ("\ue7e8", "U"),
              "menu": ("\ue700", "≡"), "settings": ("\ue713", "⚙")}
TAB_TITLES = {"home": "Home", "play": "Library", "memory": "Memory", "clean": "Clean up", "tools": "Tools", "games": "Gaming",
              "stats": "Stats", "system": "System", "startup": "Startup"}
TAB_BLURBS = {"home": "Your last game, recent games and one-tap tools",
              "play": "Every game on this PC, ready to play",
              "memory": "What's using your RAM, and one tap to free it",
              "clean": "Clear caches and junk to get storage back",
              "tools": "Profiles, display, sound and performance mode",
              "games": "Per-game profiles and what happens when a game starts",
              "stats": "Your week, battery health and most played",
              "system": "Graphics, battery, processor and the mini monitor",
              "startup": "What starts with Windows"}
LEGION_ACTIONS = {"hub": "Open the hub", "quick": "Quick settings", "overlay": "Mini monitor", "focus": "Focus mode",
                  "boost": "Game Boost", "taskview": "Task view", "desktop": "Show desktop", "keyboard": "On-screen keyboard",
                  "padmouse": "Controller as mouse", "clip": "Save a clip", "none": "Nothing"}
LEGION_ACTION_ORDER = list(LEGION_ACTIONS)
RGB_MODE_LABELS = {"keep": "Leave as is", "off": "Off", "solid": "Solid", "pulse": "Pulse", "dynamic": "Rainbow", "spiral": "Spiral"}
RGB_COLORS = ["#00c8ff", "#7b5cff", "#ff3b6b", "#ff8a00", "#ffd400", "#3fd16b", "#ffffff"]
BACK_ORDER = ["y1", "y2", "y3", "m2", "m3"]
BACK_LABELS = {"y1": "Y1 · left back, top", "y2": "Y2 · left back, bottom", "y3": "Y3 · right back", "m2": "M2 · right", "m3": "M3 · right"}
BACK_ACTS = {"quick": "Quick settings", "hub": "Open the hub", "screenshot": "Screenshot", "boost": "Game Boost",
             "play": "Play / pause music", "keyboard": "On-screen keyboard", "suspend": "Suspend / resume game",
             "mute": "Discord mute", "clip": "Save a clip", "padmouse": "Controller as mouse on/off", "fan": "Full fan speed on/off"}
BACK_ACTIONS = (["none"] + [f"key:{k}" for k in ("F5", "F9", "F12", "Esc", "Tab", "Enter", "Space", "M", "I", "J", "Q", "E", "R", "F",
                                                   "G", "Shift", "Ctrl", "Alt", "Alt+Tab")] + [f"act:{a}" for a in BACK_ACTS])
AUTO_TDP_TARGETS = [30, 40, 45, 60, 90]


def back_label(a):
    if not a or a == "none":
        return "Nothing"
    kind, _, v = a.partition(":")
    return f"Key {v}" if kind == "key" else BACK_ACTS.get(v, v)


QUICK_STATE = ("c", "regions", "k", "layer", "focus_id", "focus_visible", "press", "pressed", "page")


def _flat(args):
    out = []
    for a in args:
        if isinstance(a, (list, tuple)):
            out.extend(_flat(a))
        else:
            out.append(float(a))
    return out


def _clip_poly(pts, y0, y1):
    """Sutherland–Hodgman against the horizontal band y0..y1 (pts is a flat x,y list)."""
    poly = list(zip(pts[0::2], pts[1::2]))
    for edge, inside in ((y0, lambda p: p[1] >= y0), (y1, lambda p: p[1] <= y1)):
        if not poly:
            break
        out = []
        prev = poly[-1]
        for cur in poly:
            ci, pi = inside(cur), inside(prev)
            if ci != pi:
                t = (edge - prev[1]) / ((cur[1] - prev[1]) or 1e-9)
                out.append((prev[0] + (cur[0] - prev[0]) * t, edge))
            if ci:
                out.append(cur)
            prev = cur
        poly = out
    return [v for p in poly for v in p]


_ANCHOR_DX = {"nw": 0, "w": 0, "sw": 0, "n": 0.5, "center": 0.5, "s": 0.5, "ne": 1, "e": 1, "se": 1}
_ANCHOR_DY = {"nw": 0, "n": 0, "ne": 0, "w": 0.5, "center": 0.5, "e": 0.5, "sw": 1, "s": 1, "se": 1}


class ClipCanvas(tk.Canvas):
    """A canvas that can clip what's drawn to a horizontal band, so scrolling lists can show rows
    that are only partly on screen (no rows popping in and out at the edges). Every item is also
    tagged with the current layer, so a page can be redrawn without redrawing the hub under it."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.clip = None
        self.layer_tag = "main"
        self.extra_tag = None  # e.g. "libgrid": lets one part of the screen be redrawn on its own
        self._crops = {}
        self._lines = {}

    def _kw(self, kw):
        t = kw.get("tags")
        kw["tags"] = (self.layer_tag,) + ((self.extra_tag,) if self.extra_tag else ()) + ((t,) if isinstance(t, str) else tuple(t or ()))
        return kw

    def _band(self, top, bottom):
        """0 = fully inside the clip, 1 = partly, 2 = fully outside."""
        y0, y1 = self.clip
        if bottom <= y0 or top >= y1:
            return 2
        return 0 if top >= y0 - 0.5 and bottom <= y1 + 0.5 else 1

    def create_rectangle(self, *a, **kw):
        if self.clip:
            x0, y0, x1, y1 = _flat(a)
            b = self._band(min(y0, y1), max(y0, y1))
            if b == 2:
                return None
            if b == 1:
                y0, y1 = max(min(y0, y1), self.clip[0]), min(max(y0, y1), self.clip[1])
            a = (x0, y0, x1, y1)
        return super().create_rectangle(*a, **self._kw(kw))

    def create_polygon(self, *a, **kw):
        if self.clip:
            pts = _flat(a)
            ys = pts[1::2]
            b = self._band(min(ys), max(ys))
            if b == 2:
                return None
            if b == 1:
                pts = _clip_poly(pts, *self.clip)
                if len(pts) < 6:
                    return None
            a = (pts,)
        return super().create_polygon(*a, **self._kw(kw))

    def create_oval(self, *a, **kw):
        if self.clip:
            x0, y0, x1, y1 = _flat(a)
            b = self._band(y0, y1)
            if b == 2:
                return None
            if b == 1:
                cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
                pts = [v for i in range(32) for v in (cx + rx * math.cos(i * math.pi / 16), cy + ry * math.sin(i * math.pi / 16))]
                kw.pop("start", None)
                return self.create_polygon(pts, **kw)
        return super().create_oval(*a, **self._kw(kw))

    def create_line(self, *a, **kw):
        if self.clip:
            pts = _flat(a)
            ys = pts[1::2]
            b = self._band(min(ys), max(ys))
            if b == 2:
                return None
            if b == 1:
                if len(pts) != 4:
                    return None
                x0, y0_, x1, y1_ = pts
                lo, hi = self.clip
                if y0_ == y1_:
                    return None
                def at(y):
                    return x0 + (x1 - x0) * (y - y0_) / (y1_ - y0_)
                ya, yb = max(min(y0_, y1_), lo), min(max(y0_, y1_), hi)
                a = (at(ya), ya, at(yb), yb)
        return super().create_line(*a, **self._kw(kw))

    def create_arc(self, *a, **kw):
        if self.clip:
            x0, y0, x1, y1 = _flat(a)
            if self._band(y0, y1):
                return None
        return super().create_arc(*a, **self._kw(kw))

    def _linespace(self, font):
        key = str(font)
        v = self._lines.get(key)
        if v is None:
            try:
                v = font.metrics("linespace")
            except Exception:
                v = tkfont.Font(root=self, font=font).metrics("linespace")
            self._lines[key] = v
        return v

    def create_text(self, *a, **kw):
        if self.clip:
            x, y = _flat(a)[:2]
            h = self._linespace(kw.get("font", "TkDefaultFont")) * (str(kw.get("text", "")).count("\n") + 1)
            top = y - h * _ANCHOR_DY.get(kw.get("anchor", "center"), 0.5)
            # text can't be cut, so it shows once nearly all of it is inside
            if top < self.clip[0] - h * 0.15 or top + h > self.clip[1] + h * 0.15:
                return None
        return super().create_text(*a, **self._kw(kw))

    def create_image(self, *a, **kw):
        img = kw.get("image")
        if self.clip and img is not None:
            x, y = _flat(a)[:2]
            try:
                w, h = img.width(), img.height()
            except Exception:
                w = h = 0
            anc = kw.get("anchor", "center")
            left, top = x - w * _ANCHOR_DX.get(anc, 0.5), y - h * _ANCHOR_DY.get(anc, 0.5)
            b = self._band(top, top + h) if h else 0
            if b == 2:
                return None
            if b == 1:
                c0, c1 = int(max(0, self.clip[0] - top)), int(min(h, self.clip[1] - top))
                if c1 - c0 < 1:
                    return None
                key = (str(img), c0, c1)
                crop = self._crops.get(key)
                if crop is None:
                    if len(self._crops) > 96:
                        self._crops.clear()
                    crop = tk.PhotoImage(master=self, width=w, height=c1 - c0)
                    crop.tk.call(crop, "copy", str(img), "-from", 0, c0, w, c1)
                    self._crops[key] = crop
                kw["image"], kw["anchor"] = crop, "nw"
                a = (left, top + c0)
        return super().create_image(*a, **self._kw(kw))

    def create_window(self, *a, **kw):
        return super().create_window(*a, **self._kw(kw))


class Nudge:
    """A reminder card at the top of the screen for a few seconds. On top of windowed and borderless games,
    never takes focus and lets clicks through."""

    def __init__(self, ui, title, body, secs=9):
        T, k = ui.t, ui.k
        self.top = tk.Toplevel(ui.root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        fr = tk.Frame(self.top, bg=T["panel"], highlightthickness=max(1, int(2 * k)), highlightbackground=T["accent"])
        fr.pack(fill="both", expand=True)
        tk.Label(fr, text=title, bg=T["panel"], fg=T["text"], font=ui.font(17 * k, True), anchor="w").pack(
            fill="x", padx=int(22 * k), pady=(int(16 * k), int(2 * k)))
        tk.Label(fr, text=body, bg=T["panel"], fg=T["muted"], font=ui.font(13 * k), anchor="w", justify="left",
                 wraplength=int(520 * k)).pack(fill="x", padx=int(22 * k), pady=(0, int(16 * k)))
        self.top.update_idletasks()
        w, h = self.top.winfo_reqwidth(), self.top.winfo_reqheight()
        sw = self.top.winfo_screenwidth()
        self.top.geometry(f"{w}x{h}+{(sw - w) // 2}+{int(40 * k)}")
        try:
            systools.make_click_through(self.top)
        except Exception:
            pass
        try:
            self.top.attributes("-alpha", 0.96)
        except Exception:
            pass
        self.top.after(int(secs * 1000), self.destroy)

    def destroy(self):
        try:
            self.top.destroy()
        except Exception:
            pass


class MiniMonitor:
    """A small always-on-top, click-through window with live stats. Shows over windowed and
    borderless-fullscreen games (exclusive fullscreen games draw over everything)."""

    def __init__(self, ui):
        self.ui = ui
        self.top = tk.Toplevel(ui.root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.c = ClipCanvas(self.top, highlightthickness=0, bd=0)
        self.c.pack(fill="both", expand=True)
        self.top.geometry("10x10+0+0")
        self.top.update_idletasks()
        try:
            systools.make_click_through(self.top)
        except Exception:
            pass
        self.apply_opacity()

    def apply_opacity(self):
        self.top.attributes("-alpha", self.ui.cfg["overlay_opacity"] / 100)

    def destroy(self):
        self.top.destroy()

    def rows(self):
        ui, T = self.ui, self.ui.t
        st = ui.status
        frac = (st.ullTotalPhys - st.ullAvailPhys) / max(1, st.ullTotalPhys)
        load = T["accent"] if frac < 0.7 else T["warn"] if frac < 0.88 else T["danger"]
        out = [("RAM", f"{frac * 100:.0f}%  {fmt_bytes(st.ullTotalPhys - st.ullAvailPhys)}", load)]
        if ui.fps_stats:
            fps, low = ui.fps_stats
            out.insert(0, ("FPS", f"{fps:.0f}" + (f"  1% {low:.0f}" if low else ""), T["accent2"]))
        if ui.cpu is not None:
            out.append(("CPU", f"{ui.cpu:.0f}%", T["accent"] if ui.cpu < 80 else T["warn"]))
        if ui.gpu is not None:
            out.append(("GPU", f"{ui.gpu:.0f}%", T["accent"] if ui.gpu < 90 else T["warn"]))
        b, p = ui.batt, ui.power
        if b and p and p["pct"] <= 100:
            if b["discharging"] and b["rate_mw"]:
                w = abs(b["rate_mw"]) / 1000
                left = b["remaining_mwh"] / abs(b["rate_mw"]) * 3600
                out.append(("BAT", f"{p['pct']}%  {w:.1f} W  {fmt_duration(left)}", T["danger"] if p["pct"] < 20 else T["good"]))
            else:
                out.append(("BAT", f"{p['pct']}%  " + ("charging" if b["charging"] else "plugged in"), T["good"]))
        if ui.game:
            out.append(("GAME", fmt_duration(time.time() - ui.game["start"]), T["accent2"]))
        out.append(("TIME", time.strftime("%H:%M"), T["muted"]))
        return out

    def update(self):
        ui, T = self.ui, self.ui.t
        try:
            sw, sh = self.top.winfo_screenwidth(), self.top.winfo_screenheight()
        except tk.TclError:
            return
        # Not needed while Vanta itself is in front (and it would cover the window's buttons).
        if ui.focused():
            if self.top.state() != "withdrawn":
                self.top.withdraw()
            return
        if self.top.state() == "withdrawn":
            self.top.deiconify()
            try:
                systools.make_click_through(self.top)
            except Exception:
                pass
            self.apply_opacity()
        px = max(11, int(min(sw, sh) / 64 * ui.cfg["overlay_size"] / 100))
        lf, vf = ui.font(px * 0.82, True, mono=True), ui.font(px, True, mono=True)
        rows = self.rows()
        pad, lh = px * 0.7, vf.metrics("linespace") + px * 0.15
        lw = max(lf.measure(r[0]) for r in rows) + px * 0.8
        w = int(pad * 2 + lw + max(vf.measure(r[1]) for r in rows))
        frames = list(ui.fps.frames)[-160:] if ui.fps and ui.cfg["frametime_graph"] else []
        gh = int(px * 3.2) if len(frames) > 10 else 0
        w = max(w, int(px * 13)) if gh else w
        h = int(pad * 2 + lh * len(rows)) + gh
        m = px
        corner = ui.cfg["overlay_corner"]
        x = m if corner in ("tl", "bl") else sw - w - m
        y = m if corner in ("tl", "tr") else sh - h - m * 4
        self.top.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
        c = self.c
        c.configure(bg=T["bg"])
        c.delete("all")
        c.create_rectangle(0, 0, 3, h, fill=T["accent"], width=0)
        if gh:  # frame times, newest on the right: flat is smooth, spikes are stutter
            gx0, gx1, gy1 = pad, w - pad * 0.6, h - pad * 0.5
            gy0 = gy1 - gh + px * 0.4
            top = max(40.0, max(ms for _, ms in frames))
            for ms_line in (16.7, 33.3):
                ly = gy1 - (gy1 - gy0) * ms_line / top
                c.create_line(gx0, ly, gx1, ly, fill=mix(T["bg"], T["muted"], 0.35), dash=(2, 3))
            pts = []
            n = len(frames)
            for i, (_, ms) in enumerate(frames):
                pts += [gx0 + (gx1 - gx0) * i / (n - 1), gy1 - (gy1 - gy0) * min(ms, top) / top]
            spike = max(ms for _, ms in frames[-30:]) > 2.2 * (sum(ms for _, ms in frames) / n)
            c.create_line(*pts, fill=T["warn"] if spike else T["accent2"], width=max(1, px // 9))
        for i, (label, value, col) in enumerate(rows):
            cy = pad + lh * i + lh / 2
            c.create_text(pad, cy, text=label, font=lf, fill=T["muted"], anchor="w")
            c.create_text(pad + lw, cy, text=value, font=vf, fill=col, anchor="w")
        self.top.attributes("-topmost", True)


SAMPLE_GAMES = ["ELDEN RING", "Cyberpunk 2077", "Baldur's Gate 3", "Hades II", "Forza Horizon 5", "Hollow Knight",
                "Stardew Valley", "Balatro", "Helldivers 2", "Marvel Rivals", "Celeste", "Dead Cells"]


def sample_library():
    now = time.time()
    return [{"id": f"sample:{i}", "source": "Steam" if i % 4 else "Epic", "name": n, "size": int((i % 6 + 1) * 9.5e9),
             "last": now - i * 86400 * 2 if i < 8 else 0, "minutes": (12 - i) * 170 if i < 9 else 0, "cover": None,
             "launch": "", "exe": ""} for i, n in enumerate(SAMPLE_GAMES)]


# Everything that changes the PC, and what it returns when Preview skips it.
PREVIEW_GUARDED = {
    "systools": {"clean_category": 0, "empty_recycle_bin": 0, "set_power_mode": False, "set_thermal_mode": False,
                 "set_cpu_boost_dc": False, "set_service": False, "set_tweak": False, "set_startup_item": False, "restart_pc": None,
                 "end_process": False, "recycle": False, "set_display_mode": False, "apply_profile": [], "set_tdp": False,
                 "set_charge_limit": False, "set_brightness": False, "close_apps": [], "close_processes": 0,
                 "throttle_background": [], "set_priority": False, "set_features": False, "set_radio": False, "toggle_hdr": None,
                 "suspend_process": False, "move_steam_game": (False, "Preview: nothing was moved"),
                 "ludusavi": (False, "Preview: saves weren't touched", 0),
                 "install_update": False, "set_cpu_max": False, "sleep_now": False, "restart_now": None, "shutdown_now": None,
                 "set_notifications": False, "pause_updates": False, "resume_updates": False, "clear_shader_cache": 0,
                 "set_button_service": (False, {})},
    "vanta": {"run_action": (0, 0.0), "game_boost": (0, 0.0, 0), "flush_file_cache": None, "trim_process": (False, 0),
              "empty_working_set": False, "set_startup": False},
}


def install_preview_guard(ui):
    """In Preview, with "Don't change this PC" on, system-changing calls are skipped and a note is shown."""
    import functools
    mods = {"systools": systools, "vanta": sys.modules[__name__]}
    for mod_name, funcs in PREVIEW_GUARDED.items():
        mod = mods[mod_name]
        for name, fail in funcs.items():
            orig = getattr(mod, name, None)
            if not orig or getattr(orig, "_preview", False):
                continue

            def make(orig=orig, name=name, fail=fail):
                @functools.wraps(orig)
                def guarded(*a, **k):
                    if ui.cfg["preview_safe"]:
                        ui.call(lambda: ui.preview_skip(name))
                        return fail
                    return orig(*a, **k)
                guarded._preview = True
                return guarded

            setattr(mod, name, make())
    adlx_apply = systools.ADLX.apply

    def apply(settings):
        if ui.cfg["preview_safe"]:
            ui.call(lambda: ui.preview_skip("amd"))
            return []
        return adlx_apply(settings)

    systools.ADLX.apply = apply
    launch = systools.launch_game

    def launch_game(g, *a, **k):
        if str(g.get("id", "")).startswith("sample:"):
            ui.call(lambda: ui.show_toast(f"{g['name']} is a sample game in Preview"))
            return False
        return launch(g, *a, **k)

    systools.launch_game = launch_game
    lib = systools.game_library

    def game_library(*a, **k):
        games = lib(*a, **k)
        return games + sample_library() if ui.cfg["preview_samples"] else games

    systools.game_library = game_library


OSK_ROWS = [list("1234567890"), list("qwertyuiop"), list("asdfghjkl'"), list("zxcvbnm,.?")]
OSK_SHIFT = {"1": "!", "2": "@", "3": "#", "4": "$", "5": "%", "6": "^", "7": "&", "8": "*", "9": "(", "0": ")", "'": '"', ",": ";",
             ".": ":", "?": "/"}
OSK_BOTTOM = [("shift", "⇧", 1.5), ("space", "SPACE", 4.5), ("bksp", "⌫", 1.5), ("enter", "ENTER", 1.5), ("close", "✕", 1.0)]


POINTER_MODES = {"off": "Off", "vanta": "Wii pointer in Vanta", "mouse": "Gyro mouse (aim in games)"}


class Pointer:
    """Point the Legion Go controller at the screen, Wii-remote style. The gyro arrives on the listener thread;
    the UI thread picks up the movement ~60 times a second."""

    def __init__(self, ui):
        self.ui = ui
        self.lock = threading.Lock()
        self.dx = self.dy = 0.0
        self.bias = [0.0, 0.0, 0.0]
        self.calib = 0
        self.t = None
        self.rem = [0.0, 0.0]
        self.x = self.y = None
        self.trail = []
        self.scale = 1500.0
        self.refresh_settings()

    def refresh_settings(self):
        c = self.ui.cfg
        self.mode = c["pointer_mode"]
        self.sens = c["pointer_sens"] / 100
        self.sx = -1 if c["pointer_invert_x"] else 1
        self.sy = -1 if c["pointer_invert_y"] else 1
        self.horiz = 1 if c["pointer_axis"] == "yaw" else 2
        self.hold = c["gyro_hold"]
        self.scale = self.ui.root.winfo_screenwidth() / 0.75  # about 43 degrees of turn sweeps the screen, like a Wii remote

    def recalibrate(self):
        self.calib = 0
        self.calib_t0 = 0.0
        self.bias = [0.0, 0.0, 0.0]

    def feed(self, pitch, yaw, roll, lt, rt, t):  # listener thread
        if self.t is None:
            self.t = t
            return
        dt = min(0.05, max(0.0, t - self.t))
        self.t = t
        r = (pitch, yaw, roll)
        if self.calib == 0:
            self.calib_t0 = t
        if t - self.calib_t0 < 0.5:  # first half second after switching on: learn the resting offset (hold still)
            self.calib += 1
            for i in range(3):
                self.bias[i] += (r[i] - self.bias[i]) / self.calib
            return
        v = [r[i] - self.bias[i] for i in range(3)]
        if max(abs(a) for a in v) < 0.025:  # still: keep tracking drift slowly, don't move
            for i in range(3):
                self.bias[i] += (r[i] - self.bias[i]) * 0.02
            return
        hx, hy = -v[self.horiz] * dt * self.sx, -v[0] * dt * self.sy
        if self.mode == "mouse":
            if self.hold and lt < 40:
                return
            k = 1100 * self.sens
            self.rem[0] += hx * k
            self.rem[1] += hy * k
            ix, iy = int(self.rem[0]), int(self.rem[1])
            if ix or iy:
                self.rem[0] -= ix
                self.rem[1] -= iy
                systools.mouse_move(ix, iy)
        else:
            with self.lock:
                self.dx += hx * self.scale * self.sens
                self.dy += hy * self.scale * self.sens

    def take(self):
        with self.lock:
            d = (self.dx, self.dy)
            self.dx = self.dy = 0.0
        return d


class Keyboard:
    """A controller-friendly keyboard that never takes focus: it types into the app you were in.
    D-pad/stick moves, A types, X backspace, Y space, LB shift, Start enter, B closes."""

    def __init__(self, ui, target=None):
        self.ui = ui
        self.target = target  # None: type into the app in front; otherwise target(kind, text) inside Vanta
        self.shift = False
        self.cur = (1, 0)
        self.keys = []
        sw, sh = ui.root.winfo_screenwidth(), ui.root.winfo_screenheight()
        self.k = max(0.6, min(3.0, min(sh / 800, sw / 1280) * ui.cfg["ui_scale"] / 100))
        w, h = int(min(sw, 900 * self.k)), int(330 * self.k)
        self.win = tk.Toplevel(ui.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(f"{w}x{h}+{(sw - w) // 2}+{sh - h - int(12 * self.k)}")
        self.c = ClipCanvas(self.win, highlightthickness=0, bd=0, bg=ui.t["panel"])
        self.c.pack(fill="both", expand=True)
        self.c.bind("<ButtonPress-1>", self.tap)
        self.c.bind("<Configure>", lambda e: self.draw())
        self.win.update_idletasks()
        hwnd = user32.GetAncestor(self.win.winfo_id(), 2) or self.win.winfo_id()
        try:
            ex = systools._get_ex(hwnd, -20)
            systools._set_ex(hwnd, -20, ex | 0x08000000 | 0x80)  # WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW: keep focus in the game/app
        except Exception:
            pass
        self.draw()

    def rows(self):
        rows = [[(ch, (OSK_SHIFT.get(ch, ch.upper()) if self.shift else ch), 1.0) for ch in r] for r in OSK_ROWS]
        return rows + [OSK_BOTTOM]

    def draw(self):
        T, c, k = self.ui.t, self.c, self.k
        W, H = max(c.winfo_width(), 100), max(c.winfo_height(), 100)
        c.delete("all")
        c.create_rectangle(0, 0, W, H, fill=T["panel"], outline=T["accent"], width=max(2, 2 * k))
        P, gap = 12 * k, 7 * k
        rows = self.rows()
        rh = (H - 2 * P - gap * (len(rows) - 1)) / len(rows)
        self.keys = []
        f = self.ui.font(20 * k, True)
        for ri, row in enumerate(rows):
            units = sum(u for _, _, u in row)
            uw = (W - 2 * P - gap * (len(row) - 1)) / units
            x = P
            y = P + ri * (rh + gap)
            for ci, (kid, label, u) in enumerate(row):
                w = uw * u + gap * (u - 1) if u > 1 else uw
                sel = self.cur == (ri, ci)
                on = kid == "shift" and self.shift
                fill = T["accent"] if sel else mix(T["panel2"], T["accent"], 0.3) if on else T["panel2"]
                c.create_rectangle(x, y, x + w, y + rh, fill=fill, outline="", width=0)
                c.create_text(x + w / 2, y + rh / 2, text=label, font=f, fill=T["accent_text"] if sel else T["text"])
                self.keys.append((ri, ci, kid, label, x, y, x + w, y + rh))
                x += w + gap

    def press(self, kid, label):
        if self.target and kid != "shift":
            if kid == "close":
                self.ui.close_keyboard()
                return
            self.target(kid, label)
            if self.shift and kid not in ("bksp", "space"):
                self.shift = False
            self.ui.sound("move")
            if kid == "enter":
                self.ui.close_keyboard()
                return
            self.draw()
            return
        if kid == "shift":
            self.shift = not self.shift
        elif kid == "space":
            systools.type_text(" ")
        elif kid == "bksp":
            systools.key_combo("Backspace")
        elif kid == "enter":
            systools.key_combo("Enter")
        elif kid == "close":
            self.ui.close_keyboard()
            return
        else:
            systools.type_text(label)
            if self.shift:
                self.shift = False
        self.ui.sound("move")
        self.draw()

    def tap(self, e):
        for ri, ci, kid, label, x0, y0, x1, y1 in self.keys:
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                self.cur = (ri, ci)
                self.press(kid, label)
                return

    def pad(self, b):
        rows = self.rows()
        r, ci = self.cur
        if b in ("up", "down"):
            nr = max(0, min(len(rows) - 1, r + (-1 if b == "up" else 1)))
            # keep roughly the same horizontal position when the row has different key widths
            frac = (ci + 0.5) / len(rows[r])
            self.cur = (nr, min(len(rows[nr]) - 1, int(frac * len(rows[nr]))))
        elif b in ("left", "right"):
            self.cur = (r, (ci + (-1 if b == "left" else 1)) % len(rows[r]))
        elif b == "a":
            kid, label, _ = rows[r][ci]
            return self.press(kid, label)
        elif b == "x":
            return self.press("bksp", "")
        elif b == "y":
            return self.press("space", "")
        elif b == "lb":
            return self.press("shift", "")
        elif b == "start":
            return self.press("enter", "")
        elif b == "b":
            return self.ui.close_keyboard()
        self.ui.sound("move")
        self.draw()

    def destroy(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class QuickPanel:
    """Legion R: a touch and controller panel on the right edge, over the game (the job Legion Space's quick menu does)."""

    def __init__(self, ui):
        self.ui = ui
        self.prev = user32.GetForegroundWindow()
        self.opened = time.time()
        self.win = tk.Toplevel(ui.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        sw, sh = ui.root.winfo_screenwidth(), ui.root.winfo_screenheight()
        self.k = max(0.5, min(3.0, min(sh / 800, sw / 640) * ui.cfg["ui_scale"] / 100))
        w = int(min(sw, 470 * self.k))
        self.win.geometry(f"{w}x{sh}+{sw - w}+0")
        self.c = ClipCanvas(self.win, highlightthickness=0, bd=0, bg=ui.t["bg"])
        self.c.pack(fill="both", expand=True)
        for ev, fn in (("<ButtonPress-1>", ui.on_press), ("<B1-Motion>", ui.on_motion),
                       ("<ButtonRelease-1>", ui.on_release), ("<MouseWheel>", ui.on_wheel)):
            self.c.bind(ev, lambda e, f=fn: ui.quick_event(f, e))
        self.win.bind("<Key>", lambda e: ui.quick_event(ui.quick_key, e))
        self.c.bind("<Configure>", lambda e: ui.request_draw())
        self.state = {"c": self.c, "regions": [], "k": self.k, "layer": "main", "focus_id": None,
                      "focus_visible": ui.pad_on, "press": None, "pressed": None, "page": None}
        self.win.update_idletasks()
        self.hwnd = user32.GetAncestor(self.win.winfo_id(), 2) or self.win.winfo_id()
        try:
            systools.force_foreground(self.hwnd)
        except Exception:
            pass
        self.win.focus_force()

    def destroy(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class UI:
    def __init__(self, start_hidden=False, show_event=None):
        self.cfg = Config()
        self.light_mode = systools.windows_light_mode()
        self._theme_cache = (None, None)
        if self.cfg["custom_theme"]:
            try:
                THEMES[MY_THEME] = build_custom_theme(self.cfg["custom_theme"])
                if MY_THEME not in THEME_NAMES:
                    THEME_NAMES.append(MY_THEME)
            except Exception:
                pass
        self.device = device_info()
        self.on_legion = self.device["legion"]  # the hardware, whichever edition this is
        if not IS_GO:
            self.device = dict(self.device, legion=False, variant="")
        if IS_GO and PREVIEW and self.cfg["preview_legion"] and not self.device["legion"]:
            self.device = {"name": "Legion Go (preview)", "legion": True, "variant": "go"}
        if PREVIEW:
            install_preview_guard(self)
        self.preview_note = 0.0
        if self.cfg["theme"] not in THEMES:
            # Legion Go 2 has an OLED panel: true black pixels are off and save battery.
            self.cfg["theme"] = "Vanta OLED" if self.device["variant"] == "go2" else "Vanta"
        if not self.cfg["plain_pad_v991"]:
            # 9.9.1: the Legion controllers are treated as a normal Xbox controller. Vanta stops listening to the
            # controller's own report (Legion buttons, back buttons, the View+Menu combo), so nothing it misreads can
            # move windows or open Vanta. Lenovo's own button service is put back if Vanta had stopped it.
            self.cfg["plain_pad_v991"] = True
            self.cfg["legion_buttons"] = False
            self.cfg["pad_combo"] = False
            self.cfg["ls_keep_closed"] = False
            self.plain_pad_migrated = True
        if not self.cfg["layout_v86"]:
            self.cfg["layout_v86"] = True
            self.cfg["layout"] = "console"
            if self.cfg["start_tab"] == "play":
                self.cfg["start_tab"] = "home"
        if not self.cfg["look_v8"]:
            # 8.1 introduced the signature look: switch to it once (any theme can be picked again in Themes)
            self.cfg["look_v8"] = True
            if self.cfg["theme"] not in ("Vanta", "Vanta OLED", MY_THEME):
                self.cfg["prev_theme"] = self.cfg["theme"]
                self.cfg["theme"] = "Vanta OLED" if self.device["variant"] == "go2" else "Vanta"
                self.cfg["accent"] = ""
                self.startup_toast = "New look: the Vanta theme. Your old theme is one tap away in Themes"
        self.admin = is_admin()
        if self.admin:
            enable_privileges()
        self.pad = Gamepad.create()
        self.power = power_status()
        self.installed = installed_ram()
        self.status = memory_status()
        self.lists = memory_lists() if self.admin else None
        self.history = deque(maxlen=180)
        self.log = deque(maxlen=80)
        self.procs = []
        self.proc_time = 0.0
        self.sel = 0
        self.scrolls = {}
        self.detach_saved = None
        self.ls_user_until = 0.0
        self.padmouse = None
        self.batt_armed = {}
        self.thumbs = {}
        self.pick_time = 60
        self.net_state = None
        self.rule_hz_cache = None
        self.fan_full = None
        self.fan_loading = False
        self.motions = {}
        self.hovered = None
        self.hover_fill = None
        self.btntest = None
        self.recap = None
        self.recap_new = False
        self.bgoal = None
        self.nudge_win = None
        self.events = deque(maxlen=20)
        self.news = {}
        self.reviews = {}
        self.dock_saved = None
        self.event_n = 0
        self.cfg["batt_goal"] = 0  # a battery goal lasts for one run
        self.cfg["sleep_after_game"] = False
        self.sleep_at = None
        self.sleep_mins = 0
        self.bar_ind = None
        self.bar_target = None
        self.home_sel = None
        self.sec_last = {}
        self.find_q = ""
        self.last_input = 0.0
        self.fx_cost = 0.02
        self.legion_seen_now = set()   # hover is an overlay now (see draw_hover); kept so old checks stay valid
        self.slides = {}         # name -> slide in progress (moved, never redrawn)
        self.tick_on = False
        self.tick_t = 0.0
        self.rail_target = None
        self.ring_target = None
        self._libgrid = None
        self._lib_base = None
        self.motion_pending = False
        self.shown_page = None
        self.tab_dir = 1
        self.tab_ind = None
        self.rail_ind = None
        self.ring_pos = None
        self.glide_t = time.perf_counter()
        self.backup_seen = (0, "")
        self.ls_press_t = 0.0
        self.ls_auto_closed = 0
        self.ls_service = "?"
        self.ls_service_t = 0.0
        self.started_at = time.time()
        self.stale = False
        self.hidden_since = None
        self.eco = False
        self.trimmed = False
        self.pcgw = {}  # PCGamingWiki lookups per game: {"status", "data"}
        self.dv = {}  # Deck Verified lookups per game: {"status": loading|ok|none|offline, "data": ...}
        self.set_cat = None
        self.set_query = ""
        self.set_typing = False
        self.set_drill = False
        self.set_narrow = False
        self.kinetic = None
        self.anims = {}
        self.anim_on = False
        self.draw_scope = None
        self._last_draw = 0.0
        self._base = None
        self.tab = "memory"
        # hub state
        self.library = None
        self.lib_loading = False
        self.lib_sel = None
        self.focus = None
        self.focus_busy = False
        self.hub_launch = None
        self.combo_t = None
        self.tune_target = None
        self.amd_state = None
        self.tune_modes = None
        from collections import OrderedDict
        self.covers = OrderedDict()
        self.cover_pending = set()
        self.cover_q = queue.Queue()
        threading.Thread(target=self.cover_worker, daemon=True).start()
        self.page = None
        self.regions = []
        self.layer = "main"
        self.focus_id = None
        self.focus_visible = False
        self.press = None
        self.pressed = None
        self.busy = None
        self.busy_action = None
        self.busy_started = 0.0
        self.jobq = queue.Queue()
        self.runs = 0
        self.freed_total = 0.0
        self.disk_freed = 0
        self.last_auto = 0.0
        self.last_interval = time.time()
        self.last_power = time.time()
        self.toast = None
        self.armed = None
        self.boosted = set()
        self.hidden = False
        self.draw_pending = False
        self.startup = None
        self.show_event = show_event
        self.k = 1.0
        self.fonts = {}
        self._mcache = {}
        # data for the extra tabs, loaded on first visit
        self.clean_sizes = {}
        self.clean_scanning = False
        self.drive_info = []
        self.tools = None
        self.tools_busy = set()
        self.needs_restart = False
        self.startup_items = None
        self.legion_apps = []
        self.startup_busy = set()
        # PC & battery, games, mini monitor
        self.cpu_prev = systools.system_times()
        self.cpu = None
        self.cpu_hist = deque(maxlen=180)
        self.proc_cpu = {}
        self.proc_cpu_prev = (0.0, {})
        self.batt = systools.battery_state()
        self.batt_static = None
        self.batt_hist = deque(maxlen=180)
        self.game = None
        self.overlay = None
        self.clean_view = "caches"
        self.steam = None
        self.bigfiles = None
        self.list_loading = set()
        self.report_busy = False
        self.winver = systools.windows_build()
        self.profile_busy = False
        self.last_ac = self.batt["ac"] if self.batt else None
        self.batt_alerted = False
        self.last_clean_check = time.time()
        self.gpu_meter = None
        try:
            self.gpu_meter = systools.GpuMeter()
        except Exception:
            self.gpu_meter = None
        self.gpu = None
        self.gpu_hist = deque(maxlen=180)
        self.fps = None
        self.fps_stats = None
        self.pm_busy = False
        self.leak = {}
        self.leak_warned = set()
        self.last_leak = time.time()
        self.pad_batt = None
        self.dupes = None
        self.brightness = None
        self.charge_limit = None
        self.charge_busy = False
        self.tdp_busy = False
        # Legion Space replacement: Legion L/R buttons, quick panel, controller lights
        self.quick = None
        self.quick_amd = None
        self.quick_autoclose = True
        self.in_panel = False
        self.legion = None
        self.legion_rgb_sent = False
        self.ls_info = None
        self.ls_time = 0.0
        self.ls_busy = False
        self.disk_c = None
        self.discord = None
        self.radios = None
        self.atdp_t = 0.0
        self.atdp_up = 0.0
        self.atdp_w = None
        self.atdp_start = None
        self.atdp_busy = False
        self.back_scope = "all"
        self.suspended = None
        self.save_busy = None
        self.osk = None
        self.wall_cache = None
        self.pointer = None
        self.pointer_sent = False
        self.bench = None
        self.steam_state = {}
        self.steam_state_t = 0.0
        self.shader_sizes = {}
        self.lib_query = ""
        self.ach = {}
        self.sgdb_started = False
        self.lists_game = None
        self.ed_slot = "accent"
        self.remote = None
        self.sync_status = ""
        self.sync_t = 0.0
        self.sync_hash = None
        self.cpu_max_now = None
        self.last_sample = None
        self.update_info = None
        self.update_busy = False
        self.move_busy = None
        self.ludusavi_busy = False
        self.radio_busy = set()
        self.net = None
        self.net_busy = False
        self.np = None
        self.np_time = 0.0
        self.share_busy = False
        self.hook_busy = False
        self.app_start = time.time()
        self.checkup_busy = False
        self.welcome_sel = {"startup", "recommended"}

        self.root = tk.Tk()
        if not IS_GO and self.on_legion and not self.cfg["go_hint"]:
            self.cfg["go_hint"] = True
            self.root.after(4000, lambda: self.show_toast("On a Legion Go? Vanta Go adds Legion buttons, TDP, fans and lights"))
        if getattr(self, "startup_toast", None):
            self.root.after(2500, lambda: self.show_toast(self.startup_toast))
        self.root.title(_ID)
        self.root.minsize(640, 400)
        try:
            ico = resource("vanta.ico")
            if os.path.exists(ico):
                self.root.iconbitmap(default=ico)
        except Exception:
            pass
        fams = set(tkfont.families(self.root))
        self.ui_family = next((f for f in ("Segoe UI Variable Text", "Segoe UI", "Tahoma", "DejaVu Sans") if f in fams), "TkDefaultFont")
        self.mono_family = next((f for f in ("Cascadia Mono", "Consolas", "Courier New") if f in fams), "TkFixedFont")
        self.icon_family = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in fams), None)
        # titles and big numbers use Windows 11's display cut of Segoe when it's there
        self.display_family = next((f for f in ("Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI") if f in fams),
                                   self.ui_family)
        self.c = ClipCanvas(self.root, highlightthickness=0, bd=0, bg=self.t["bg"])
        self.c.pack(fill="both", expand=True)
        self.c.bind("<Configure>", lambda e: self.request_draw())
        self.c.bind("<ButtonPress-1>", self.on_press)
        self.c.bind("<B1-Motion>", self.on_motion)
        self.c.bind("<Motion>", self.on_hover)
        self.c.bind("<Leave>", lambda e: self.set_hover(None))
        self.c.bind("<ButtonRelease-1>", self.on_release)
        self.c.bind("<MouseWheel>", self.on_wheel)
        self.root.bind("<Key>", self.on_key)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.update_idletasks()
        self.hwnd = user32.GetAncestor(self.root.winfo_id(), 2) or self.root.winfo_id()
        self.apply_titlebar()

        self.tray = None
        try:
            self.tray = Tray(self)
        except Exception:
            self.tray = None

        self.add_log("BOOT", f"{APP_NAME} {VERSION} on {self.device['name']}. "
                     + ("Administrator mode." if self.admin else "Limited mode: run as administrator for memory actions."))
        if self.cfg["auto"]:
            self.add_log("AUTO", "Auto optimize is armed.")
        threading.Thread(target=lambda: self.jobq.put(("startup_state", startup_enabled())), daemon=True).start()

        if start_hidden and self.cfg["console_mode"]:
            start_hidden = False  # console mode: come up fullscreen on the hub at sign-in
            if not self.cfg["fullscreen"]:
                self.root.after(300, self.toggle_fullscreen)
        if start_hidden and self.tray:
            self.root.withdraw()
            self.hidden = True
        else:
            self.show()
            self.root.after(900, self.grab_front)  # Windows often leaves the taskbar in front at sign-in
        if self.cfg["overlay"]:
            self.root.after(800, self.ensure_overlay)
        self.set_tab(self.cfg["start_tab"] if self.cfg["start_tab"] in TAB_IDS else "play")
        self.root.after(50, self.sample_loop)
        self.root.after(100, self.ui_loop)
        self.root.after(200, self.pad_loop)
        self.root.after(2000, self.game_loop)
        self.root.after(300, self.fx_loop)
        if getattr(self, "plain_pad_migrated", False):
            self.root.after(2500, lambda: self.give_back_buttons(then=lambda: self.add_log(
                "PAD", "Controllers now work like a normal Xbox controller: Vanta no longer remaps any buttons")))
        self.root.after(1200, self.start_legion_buttons)
        self.root.after(900, self.maybe_welcome)
        self.root.after(2500, self.presence_tick)
        if self.cfg["remote_on"]:
            self.root.after(1500, self.start_remote)
        if self.cfg["quiet_pending"]:  # Vanta closed mid-game last time: put notifications and updates back
            self.root.after(4000, lambda: self.game or self.quiet_off())
        if self.cfg["ui_sounds"]:
            self.background(lambda: systools.prepare_sounds(self.cfg["sound_volume"] / 100))
        if self.cfg["update_auto"] and self.cfg["update_repo"] and FROZEN:
            self.root.after(8000, lambda: self.check_updates(quiet=True))

    # -------------------------------------------------------------- basics
    @property
    def theme_name(self):
        name = self.cfg["theme"] if self.cfg["theme"] in THEMES else "Midnight"
        if self.cfg["follow_windows"] and self.light_mode and THEMES[name]["dark"]:
            name = self.cfg["light_theme"] if self.cfg["light_theme"] in THEMES else "Daylight"
        return name

    @property
    def t(self):
        name, acc = self.theme_name, self.cfg["accent"]
        if self.cfg["game_colors"] and self.__dict__.get("game_acc"):
            acc = self.__dict__["game_acc"]
        if not acc:
            return THEMES[name]
        if self._theme_cache[0] != (name, acc):
            d = dict(THEMES[name])
            d["accent"], d["accent_text"] = acc, text_on_hex(acc)
            self._theme_cache = ((name, acc), d)
        return self._theme_cache[1]

    @property
    def pad_on(self):
        return bool(self.pad and self.pad.connected)

    @property
    def on_battery(self):
        p = self.power
        return bool(p and p["battery"] and not p["ac"])

    def call(self, fn):
        self.jobq.put(("call", fn))

    def background(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def add_log(self, tag, text):
        self.log.append((time.strftime("%H:%M:%S"), tag, text))
        self.request_draw()

    def show_toast(self, text):
        if not (self.toast and self.toast[0] == text and time.time() - self.toast[1] < 2.6):
            self.begin_slide("toast", "toastfx", 0, 34 * self.k, 0.3)
        self.toast = (text, time.time())
        self.request_draw()

    def confirm(self, cid, fn, prompt):
        """Second tap within 3 s runs fn; the first one just shows prompt."""
        if self.armed and self.armed[0] == cid and time.time() - self.armed[1] < 3:
            self.armed = None
            fn()
        else:
            self.armed = (cid, time.time())
            self.show_toast(prompt)

    def is_armed(self, cid):
        return bool(self.armed and self.armed[0] == cid and time.time() - self.armed[1] < 3)

    def font(self, px, bold=False, mono=False, icon=False, display=False):
        mono = mono or bool(self.t.get("mono"))
        if not display and not icon and not mono and px >= 22 * self.k and self.t.get("premium"):
            display = True  # headings and big numbers
        key = (max(6, int(px)), bold, mono, icon, display)
        f = self.fonts.get(key)
        if f is None:
            fam = self.icon_family if icon else self.mono_family if mono else self.display_family if display else self.ui_family
            f = tkfont.Font(root=self.root, family=fam, size=-key[0], weight="bold" if bold else "normal")
            self.fonts[key] = f
        return f

    def apply_titlebar(self):
        if not dwmapi:
            return
        v = ctypes.c_int(1 if self.t["dark"] else 0)
        for attr in (20, 19):
            try:
                if dwmapi.DwmSetWindowAttribute(self.cur_hwnd(), attr, ctypes.byref(v), 4) == 0:
                    break
            except Exception:
                break

    def show(self):
        self.root.deiconify()
        if self.cfg["fullscreen"]:
            self.root.attributes("-fullscreen", True)
        else:
            try:
                self.root.state("zoomed")
            except tk.TclError:
                pass
        self.root.lift()
        self.root.focus_force()
        self.hidden = False
        self.proc_time = 0
        self.request_draw()

    def hide(self):
        self.root.withdraw()
        self.hidden = True
        if self.tray and not self.cfg["tray_hint_shown"]:
            self.cfg["tray_hint_shown"] = True
            self.tray.notify("Still running in the tray. Auto optimize keeps working.")

    def on_close(self):
        if self.tray and self.cfg["close_to_tray"]:
            self.hide()
        else:
            self.quit()

    def quit(self):
        self.quiet_off(wait=True)
        if self.remote:
            self.remote.stop()
        if self.cfg["sync_on"]:
            self.sync_tick(force=True)
        if self.bench:
            self.stop_bench()
        if self.pointer:
            self.set_pointer_mode("off")
        if self.osk:
            self.osk.destroy()
        if self.suspended:
            systools.suspend_process(self.suspended, resume=True)
        if self.discord:
            self.discord.stop()
        if self.legion:
            self.legion.stop()
        if self.quick:
            self.quick.destroy()
            self.quick = None
        if self.focus:  # never leave other apps throttled after we exit
            try:
                systools.unthrottle(self.focus["throttled"])
                if self.cfg["focus_restore_windows"]:
                    systools.restore_windows(self.focus["hwnds"])
            except Exception:
                pass
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def toggle_fullscreen(self):
        on = not self.cfg["fullscreen"]
        self.cfg["fullscreen"] = on
        self.root.attributes("-fullscreen", on)
        self.root.after(400, self.grab_front)
        if not on:
            try:
                self.root.state("zoomed")
            except tk.TclError:
                pass
        self.request_draw()

    def front_window(self):
        """(top-level window in front, its process id, its window class)."""
        fg = user32.GetForegroundWindow()
        if not fg:
            return None, None, ""
        root = user32.GetAncestor(fg, 2) or fg
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(root, ctypes.byref(pid))
        cls = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(root, cls, 128)
        return root, pid.value, cls.value

    def grab_front(self):
        """Bring the main window to the front if nothing else is (so the controller works right away)."""
        if self.hidden or self.game:
            return
        root, pid, cls = self.front_window()
        if pid != os.getpid() and cls in ("", "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            try:
                systools.force_foreground(self.cur_hwnd())
            except Exception:
                pass

    def cur_hwnd(self):
        """The main window's handle right now (it can change, e.g. after going full screen)."""
        try:
            h = user32.GetAncestor(self.root.winfo_id(), 2)
        except Exception:
            h = None
        if h:
            self.hwnd = h
        return self.hwnd

    def quick_hwnd(self):
        q = self.quick
        if not q:
            return None
        try:
            return user32.GetAncestor(q.win.winfo_id(), 2) or q.hwnd
        except Exception:
            return q.hwnd

    def focused(self):
        """Is the main window the one you're using? Checked by process, not by a saved window handle: Windows can
        give the window a new handle (full screen, DPI or display changes), and a stale one made Vanta ignore the
        controller and freeze animated themes."""
        if self.hidden:
            return False
        root, pid, cls = self.front_window()
        if pid == os.getpid():
            return root != self.quick_hwnd()
        if not self.game and cls in ("", "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd") and \
                self.root.state() != "iconic":
            return True  # nothing in front (desktop or taskbar) while Vanta is showing: the controller is yours
        return False

    def panel_focused(self):
        if not self.quick:
            return False
        root, pid, cls = self.front_window()
        return root is not None and root == self.quick_hwnd()

    def set_tab(self, tab):
        order = [t for t, _ in TABS]
        if tab != self.tab and tab in order and self.tab in order:
            self.tab_dir = 1 if order.index(tab) > order.index(self.tab) else -1
            if self.cfg["layout"] == "rail":
                self.begin_slide("tab", "content", 0, 46 * self.k * self.tab_dir, 0.3)
            elif self.cfg["layout"] == "console":
                self.begin_slide("tab", "content", 60 * self.k * self.tab_dir, 0, 0.28)
            else:
                self.begin_slide("tab", "content", 70 * self.k * self.tab_dir, 0, 0.3)
            self.request_draw()
        self.tab = tab
        self.focus_id = None
        sec = self.section_of(tab)
        if sec:
            self.sec_last[sec[0]] = tab
        if tab in ("play", "home") and self.library is None and not self.lib_loading:
            self.load_library()
        if tab == "clean" and not self.clean_sizes and not self.clean_scanning:
            self.scan_clean()
        elif tab == "tools" and self.tools is None:
            self.load_tools()
        elif tab == "startup" and self.startup_items is None:
            self.load_startup()
        elif tab == "system" and self.batt_static is None:
            self.load_battery_static()
            if self.device["legion"]:
                self.background(lambda: (lambda v: self.call(lambda: (setattr(self, "charge_limit", v), self.request_draw())))(
                    systools.get_charge_limit()))
        elif tab == "games":
            self.refresh_procs()
        self.request_draw()

    def sections(self):
        return SECTIONS[:2] if self.cfg["guest"] else SECTIONS

    def section_of(self, tab):
        return next((sec for sec in SECTIONS if tab in sec[2]), None)

    def step_tab(self, d):
        if self.cfg["layout"] == "console":  # LB / RB: the next section (back where you were in it)
            secs = self.sections()
            ids = [sec[0] for sec in secs]
            cur = self.section_of(self.tab)
            i = ids.index(cur[0]) if cur and cur[0] in ids else 0
            sec = secs[(i + d) % len(secs)]
            return self.set_tab(self.sec_last.get(sec[0], sec[2][0]))
        ids_ = ["home", "play"] if self.cfg["guest"] else TAB_IDS
        self.set_tab(ids_[((ids_.index(self.tab) if self.tab in ids_ else 0) + d) % len(ids_)])

    def step_subtab(self, d):
        """LT / RT in the console layout: the next tab inside Tune or Insights. True if it moved."""
        sec = self.section_of(self.tab)
        if self.cfg["layout"] != "console" or not sec or len(sec[2]) < 2:
            return False
        tabs = sec[2]
        self.set_tab(tabs[(tabs.index(self.tab) + d) % len(tabs)])
        return True

    # -------------------------------------------------------------- memory jobs
    def preview_blocks(self, what):
        """True (and a note) when the Preview build is set not to change this PC."""
        if PREVIEW and self.cfg["preview_safe"]:
            self.preview_skip(what)
            return True
        return False

    def run(self, action, source="USER"):
        if source == "USER" and self.preview_blocks(action):
            return
        if action not in ("trim", "trimall") and not self.admin:
            self.add_log("DENY", "Memory actions need administrator rights.")
            self.show_toast("Run as administrator for this")
            return
        if self.busy:
            self.show_toast("Busy, hold on…")
            return
        if action == "trim":
            if not self.procs:
                return
            pid, name, _ = self.procs[min(self.sel, len(self.procs) - 1)]
            label, fn = f"Trimming {name}", (lambda: (pid, name, trim_process(pid)))
        elif action == "trimall":
            def fn():
                count, total = 0, 0
                for pid, _, _ in list_processes():
                    ok, freed = trim_process(pid)
                    count += ok
                    total += freed
                return count, total
            label = "Trimming all apps"
        elif action == "boost":
            label, fn = "Game Boost", game_boost
        else:
            label, fn = ACTIONS[action][0], (lambda: run_action(action))
        self.busy, self.busy_action, self.busy_started = label, action, time.time()

        def work():
            try:
                self.jobq.put(("done", action, source, fn()))
            except Exception as ex:
                self.jobq.put(("fail", action, source, str(ex)))

        self.background(work)
        self.request_draw()

    def add_stat(self, key, value):
        st = dict(self.cfg["stats"])
        st[key] = st.get(key, 0) + value
        self.cfg["stats"] = st

    def job_done(self, action, source, result):
        before = self.freed_total
        if action == "trim":
            pid, name, (ok, freed) = result
            msg = f"{name}: freed {fmt_bytes(freed)}" if ok else f"{name}: access denied"
            self.freed_total += freed
            self.add_log("TRIM", msg)
        elif action == "trimall":
            count, total = result
            self.freed_total += total
            msg = f"Trimmed {count} apps, freed {fmt_bytes(total)}"
            self.add_log("TRIM", msg)
        elif action == "boost":
            freed, took, trimmed = result
            self.runs += 1
            self.freed_total += freed
            msg = f"Game Boost: trimmed {trimmed} apps, {fmt_bytes(freed)} free now"
            self.add_log(source, f"{msg} ({took:.1f}s)")
        else:
            freed, took = result
            self.runs += 1
            self.freed_total += freed
            msg = f"{ACTIONS[action][0]}: freed {fmt_bytes(freed)}"
            self.add_log(source, f"{msg} in {took:.2f}s")
        self.add_stat("ram", self.freed_total - before)
        if action == "boost":
            self.add_stat("boosts", 1)
        self.show_toast(msg)
        self.buzz()
        if self.hidden and self.tray and source in ("AUTO", "GAME"):
            self.tray.notify(msg)

    def buzz(self, strong=False):
        lvl = self.cfg["haptics"]
        if self.cfg["rumble"] and lvl and self.pad_on and (self.focused() or self.quick):
            self.pad.rumble(strength=(0.18, 0.35, 0.6)[min(lvl, 3) - 1] * (1.4 if strong else 1), ms=90 if lvl == 1 else 140)
        self.sound("select")

    def sound(self, name):
        if self.cfg["ui_sounds"]:
            systools.play_sound(name)

    def auto_tick(self):
        cfg = self.cfg
        if not cfg["auto"] or not self.admin or self.busy or time.time() - self.last_auto < cfg["cooldown_s"]:
            return
        st, lists = self.status, self.lists
        used = (st.ullTotalPhys - st.ullAvailPhys) / max(1, st.ullTotalPhys) * 100
        reasons = []
        if cfg["used_above"] > 0 and used >= cfg["used_above"]:
            reasons.append(f"in use {used:.0f}% ≥ {cfg['used_above']}%")
        if cfg["free_below_mb"] > 0 and lists and lists["free"] < cfg["free_below_mb"] * 1048576 and lists["standby"] > 256 * 1048576:
            reasons.append(f"free {fmt_bytes(lists['free'])} < {cfg['free_below_mb']} MB")
        if cfg["interval_min"] > 0 and time.time() - self.last_interval >= cfg["interval_min"] * 60:
            reasons.append(f"every {cfg['interval_min']} min")
            self.last_interval = time.time()
        if reasons:
            self.last_auto = time.time()
            self.add_log("AUTO", "Triggered: " + ", ".join(reasons))
            self.run(cfg["action"], "AUTO")

    # -------------------------------------------------------------- clean-up jobs
    def scan_clean(self):
        self.clean_scanning = True
        self.clean_sizes = {}

        def work():
            d = systools.drives()
            self.call(lambda: setattr(self, "drive_info", d))
            for cid, *_ in systools.CLEAN_CATEGORIES:
                size = systools.scan_category(cid)
                self.call(lambda c=cid, s=size: (self.clean_sizes.__setitem__(c, s), self.request_draw()))
            self.call(lambda: (setattr(self, "clean_scanning", False), self.request_draw()))

        self.background(work)
        self.request_draw()

    def clean_selection(self):
        sel = self.cfg["clean_sel"]
        return [cid for cid, *_ in systools.CLEAN_CATEGORIES if cid in sel]

    def toggle_clean(self, cid):
        sel = list(self.cfg["clean_sel"])
        sel.remove(cid) if cid in sel else sel.append(cid)
        self.cfg["clean_sel"] = sel
        self.request_draw()

    def run_clean(self):
        cats = self.clean_selection()
        if not cats:
            self.show_toast("Pick something to clean first")
            return
        if self.busy:
            self.show_toast("Busy, hold on…")
            return
        self.busy, self.busy_action, self.busy_started = "Cleaning up", "clean", time.time()

        def work():
            total = 0
            for cid in cats:
                try:
                    total += systools.clean_category(cid)
                except Exception:
                    pass
            self.call(lambda: self.clean_done(total))

        self.background(work)

    def clean_done(self, total):
        self.busy = self.busy_action = None
        self.disk_freed += total
        self.add_stat("disk", total)
        self.add_stat("cleanups", 1)
        msg = f"Clean up: freed {fmt_bytes(total)} of disk space"
        self.add_log("CLEAN", msg)
        self.show_toast(msg)
        self.buzz()
        self.scan_clean()

    # -------------------------------------------------------------- game tools jobs
    def load_tools(self):
        self.tools = self.tools or {}
        if self.startup_items is None:
            self.load_startup()  # also finds the Legion Space shortcut

        def work():
            data = {"power": systools.get_power_mode(), "tweaks": systools.read_tweaks(), "thermal": None,
                    "display": systools.display_modes()}
            br = systools.get_brightness()
            self.call(lambda: setattr(self, "brightness", br))
            self.call(lambda: (self.tools.update(data), self.request_draw()))
            if self.device["legion"]:
                th = systools.get_thermal_mode()
                tdp = systools.get_tdp()
                self.call(lambda: (self.tools.__setitem__("thermal", th), self.tools.__setitem__("thermal_read", True),
                                   self.tools.__setitem__("tdp", tdp), self.request_draw()))

        self.background(work)

    def set_power_mode(self, mid):
        if systools.set_power_mode(mid):
            self.tools["power"] = systools.get_power_mode() or mid
            self.add_log("TOOL", f"Power mode: {next(n for i, n, _ in systools.POWER_MODES if i == mid)}")
        else:
            self.show_toast("Couldn't change the power mode")
        self.request_draw()

    def set_thermal(self, value):
        if "thermal" in self.tools_busy:
            return
        self.tools_busy.add("thermal")

        def work():
            ok = systools.set_thermal_mode(value)
            now = systools.get_thermal_mode()

            def done():
                self.tools_busy.discard("thermal")
                self.tools["thermal"] = now
                name = dict(systools.THERMAL_MODES).get(value, value)
                if ok:
                    self.add_log("TOOL", f"Legion thermal mode: {name}")
                    self.show_toast(f"Thermal mode: {name}")
                    self.buzz()
                else:
                    self.show_toast("Couldn't change the thermal mode")
                self.request_draw()

            self.call(done)

        self.background(work)
        self.request_draw()

    def toggle_tweak(self, tid, want=None):
        tw = next(t for t in systools.TWEAKS if t[0] == tid)
        cur = (self.tools or {}).get("tweaks", {}).get(tid)
        if cur is None and want is None:
            return
        want = (not cur) if want is None else want
        if tw[7] and not want and cur:
            # Memory integrity: ask twice, it's a security feature.
            if not self.is_armed(f"tw_{tid}"):
                self.confirm(f"tw_{tid}", lambda: None, "Tap again to turn off Memory integrity (less secure)")
                return
            self.armed = None
        if systools.set_tweak(tid, want):
            self.tools["tweaks"] = systools.read_tweaks()
            self.add_log("TOOL", f"{tw[1]}: {'on' if want else 'off'}" + (" (restart to apply)" if tw[6] else ""))
            if tw[6]:
                self.needs_restart = True
        else:
            self.show_toast(f"Couldn't change {tw[1]}")
        self.request_draw()

    def apply_recommended(self):
        cur = (self.tools or {}).get("tweaks", {})
        changed = 0
        for tid, label, _, _, _, rec, restart, needs_confirm in systools.TWEAKS:
            if rec is None or needs_confirm or cur.get(tid) is None or cur.get(tid) == rec:
                continue
            if systools.set_tweak(tid, rec):
                changed += 1
                self.needs_restart |= restart
        self.tools["tweaks"] = systools.read_tweaks()
        self.add_log("TOOL", f"Applied {changed} recommended setting(s)")
        self.show_toast(f"Applied {changed} setting(s)" if changed else "Already set the recommended way")
        self.request_draw()

    # -------------------------------------------------------------- startup jobs
    def load_startup(self):
        self.startup_items = None

        def work():
            items, apps = systools.startup_items()
            self.call(lambda: (setattr(self, "startup_items", items), setattr(self, "legion_apps", apps), self.request_draw()))

        self.background(work)
        self.request_draw()

    def toggle_startup_item(self, item):
        if item.get("locked") or item["key"] in self.startup_busy:
            if item.get("locked"):
                self.show_toast("Managed by your organization's policy")
            return
        if item["kind"] == "service" and item["enabled"] and not self.is_armed("svc_" + item["key"]):
            self.confirm("svc_" + item["key"], lambda: None, "Tap again: Legion features may stop working until you start it")
            return
        self.armed = None
        want = not item["enabled"]
        self.startup_busy.add(item["key"])

        def work():
            ok = systools.set_startup_item(item, want)

            def done():
                self.startup_busy.discard(item["key"])
                if ok:
                    item["enabled"] = want
                    self.add_log("BOOT", f"{item['name']}: {'starts' if want else 'no longer starts'} with Windows")
                else:
                    self.show_toast(f"Couldn't change {item['name']}")
                self.request_draw()

            self.call(done)

        self.background(work)
        self.request_draw()

    def legion_startup_state(self):
        items = [i for i in (self.startup_items or []) if i["legion"] and i["kind"] != "service"]
        if not items:
            return None
        return any(i["enabled"] for i in items)

    def set_legion_startup(self, on):
        items = [i for i in (self.startup_items or []) if i["legion"] and i["kind"] != "service" and not i.get("locked")]
        if not items:
            return
        for i in items:
            self.startup_busy.add(i["key"])

        def work():
            results = [(i, systools.set_startup_item(i, on)) for i in items]

            def done():
                ok = 0
                for i, r in results:
                    self.startup_busy.discard(i["key"])
                    if r:
                        i["enabled"] = on
                        ok += 1
                msg = ("Legion Space will start with Windows again" if on else "Legion Space won't start with Windows anymore") \
                    if ok == len(results) else f"Changed {ok} of {len(results)} Legion entries"
                self.add_log("BOOT", msg)
                self.show_toast(msg)
                self.buzz()
                self.request_draw()

            self.call(done)

        self.background(work)
        self.request_draw()

    # -------------------------------------------------------------- Legion buttons & quick panel (Legion Space replacement)
    def start_legion_buttons(self):
        if not self.cfg["legion_buttons"] or self.legion:
            return
        if not self.device["legion"] and not os.environ.get("VANTA_FORCE_LEGION"):
            return
        m = self.cfg["legion_map"]
        if m and m.get("pid") in systools.NEW_FW_PIDS or m and (m.get("key_l") or m.get("key_r") or m.get("kind") == "keys"):
            # maps learned on 2025 firmware before Vanta knew its layout (some read Lenovo's own key presses): not needed
            self.cfg["legion_map"] = m = {}
            self.add_log("BOOT", "Legion buttons: using the built-in layout for the 2025 controller firmware")
        self.legion = systools.LegionButtons(lambda ev: self.jobq.put(("legion", ev)), m or None)
        self.legion.gmap = None
        if self.pad:
            self.pad.hid = self.legion
        self.cfg["pointer_mode"] = "off"
        self.legion.start()
        if self.cfg["ls_svc_off"] and not self.cfg["legion_seen"]:
            # Lenovo's services were stopped, but Vanta has never actually received a Legion press: put them back,
            # so the buttons keep working (8.4.1 stopped them too early on some controllers)
            self.root.after(1500, lambda: self.give_back_buttons(then=lambda: (self.close_ls_soon(), self.show_toast(
                "Legion buttons: Lenovo's service is back on. Settings › Controller & lights › Legion button test lets Vanta take over"))))
        else:
            self.root.after(3000, self.take_over_buttons)

    def take_over_buttons(self, force=False):
        """Vanta answers the Legion buttons, so Lenovo's services must not: they'd open Legion Space on every press.
        Stops and disables them (Lenovo's updates can turn them back on, so this is checked again at every start).
        Turning off "Keep Legion Space closed" puts them back exactly as they were."""
        if not (self.device["legion"] and self.cfg["legion_buttons"] and self.cfg["ls_keep_closed"] and self.admin) and not force:
            return
        if not self.cfg["legion_seen"]:
            return  # only once Vanta has really received a Legion press: otherwise the buttons would do nothing

        def work():
            st = systools.button_service_state()
            if st in (None, "disabled"):
                self.call(lambda: setattr(self, "ls_service", st))
                return
            ok, prev = systools.set_button_service(False)
            after = systools.button_service_state()

            def done():
                self.ls_service = after
                if ok:
                    if prev:  # keep the very first modes we saw, for an exact undo
                        self.cfg["ls_svc_modes"] = {**prev, **self.cfg["ls_svc_modes"]}
                    first = not self.cfg["ls_svc_off"]
                    self.cfg["ls_svc_off"] = True
                    self.add_log("BOOT", "Stopped Lenovo's button service (" + ", ".join(systools.button_services()) +
                                 "): the Legion buttons won't open Legion Space")
                    if first:
                        self.show_toast("The Legion buttons won't open Legion Space any more")
                else:
                    self.add_log("BOOT", "Couldn't stop Lenovo's button service, so Legion Space may still pop up "
                                         "(Vanta closes it again)")
                self.request_draw()
            self.call(done)
        self.background(work)

    def give_back_buttons(self, then=None):
        """Put Lenovo's button services back the way they were (then run `then`)."""
        if not self.cfg["ls_svc_off"]:
            if then:
                then()
            return

        def work():
            ok, _ = systools.set_button_service(True, self.cfg["ls_svc_modes"])
            st = systools.button_service_state()

            def done():
                self.ls_service = st
                if ok:
                    self.cfg["ls_svc_off"] = False
                    self.cfg["ls_svc_modes"] = {}
                self.add_log("BOOT", "Lenovo's button service is back on" if ok else "Couldn't restart Lenovo's button service")
                self.request_draw()
                if then:
                    then()
            self.call(done)
        self.background(work)

    def stop_legion_buttons(self):
        if self.legion:
            self.legion.stop()
            self.legion = None

    def legion_status(self):
        """(text, color) for the button listener."""
        T = self.t
        if not self.cfg["legion_buttons"]:
            return "Off", T["muted"]
        if not self.legion:
            return ("Starting…", T["muted"]) if self.device["legion"] else ("Only on a Legion Go", T["muted"])
        if self.legion.error and not self.legion.connected:
            return "Not working: " + self.legion.error, T["danger"]
        if self.legion.connected:
            return "Connected", T["good"]
        return "Looking for the controllers…", T["warn"]

    def legion_action(self, ev):
        if ev == "attach_change":
            return self.on_attach_change()
        if self.btntest and self.btntest.get("probe") and self.btntest["probe"].running:
            return  # the button test is listening: don't act on presses
        if ev.startswith("legion_"):
            self.watch_legion_space()
            self.legion_seen_now.add(ev.replace("_hold", ""))
            if not self.cfg["legion_seen"] and {"legion_l", "legion_r"} <= self.legion_seen_now:
                # proof the reader gets both buttons: now Lenovo's services can be stopped
                self.cfg["legion_seen"] = True
                self.add_log("BOOT", "Vanta is receiving both Legion buttons")
                self.root.after(500, self.take_over_buttons)
        if ev.startswith("back_"):
            _, name, edge = ev.split("_")
            return self.back_event(name, edge == "down")
        act = self.cfg[ev] if ev in Config.DEFAULTS else "none"
        if self.quick:  # any Legion button closes the panel; Legion R again just closes it
            self.close_quick(restore=act != "hub")
            if act == "quick":
                return
        self.do_action(act)

    def do_action(self, act):
        if act == "hub":
            if self.focused():
                self.hide() if self.tray else self.root.iconify()  # back to the game
            else:
                self.open_hub()
        elif act == "quick":
            self.toggle_quick()
        elif act == "overlay":
            self.toggle_overlay()
        elif act == "focus":
            self.focus_toggle()
        elif act == "boost":
            self.run("boost")
        elif act == "padmouse":
            self.toggle_padmouse()
        elif act == "clip":
            self.save_clip()
        elif act == "taskview":
            systools.send_keys(0x5B, 0x09)
        elif act == "desktop":
            systools.send_keys(0x5B, 0x44)
        elif act == "pointer":
            self.set_pointer_mode("off" if self.cfg["pointer_mode"] == "vanta" else "vanta")
        elif act == "gyromouse":
            self.set_pointer_mode("off" if self.cfg["pointer_mode"] == "mouse" else "mouse")
        elif act == "keyboard":
            if self.cfg["osk_style"] == "vanta":
                self.toggle_keyboard()
            elif not systools.touch_keyboard():
                self.show_toast("Couldn't open the on-screen keyboard")

    def toggle_quick(self):
        if self.quick:
            self.close_quick()
        else:
            self.open_quick()

    def open_quick(self):
        if self.quick:
            return
        if self.cfg["guest"]:
            self.show_toast("Quick settings are locked in guest mode")
            return
        try:
            self.quick = QuickPanel(self)
        except Exception as ex:
            self.quick = None
            self.add_log("FAIL", f"Quick settings: {ex}")
            return
        self.set_off("qp", 0) if "qp" in self.scrolls else None
        if self.tools is None:
            self.load_tools()
        if self.device["legion"] and self.charge_limit is None:
            self.background(lambda: (lambda v: self.call(lambda: (setattr(self, "charge_limit", v), self.request_draw())))(
                systools.get_charge_limit()))
        self.load_quick_amd()
        self.load_radios()
        self.background(lambda: (lambda v: self.call(lambda: setattr(self, "cpu_max_now", v[1] if self.on_battery else v[0])))(
            systools.get_cpu_max()))
        self.ls_time = 0
        self.load_ls_info()
        self.buzz()
        self.request_draw()
        self.root.after(400, self.quick_tick)

    def load_quick_amd(self):
        def work():
            st = systools.ADLX.read() if systools.ADLX.available() else {}
            self.call(lambda: (setattr(self, "quick_amd", st), self.request_draw()))
        self.background(work)

    def close_quick(self, restore=True):
        q, self.quick = self.quick, None
        if not q:
            return
        prev = q.prev
        q.destroy()
        if restore and prev and prev != self.cur_hwnd():
            try:
                systools.force_foreground(prev)
            except Exception:
                pass
        self.request_draw()

    def quick_tick(self):
        q = self.quick
        if not q:
            return
        if self.quick_autoclose and time.time() - q.opened > 0.8:
            fg = user32.GetForegroundWindow()
            fg = (user32.GetAncestor(fg, 2) or fg) if fg else fg
            if fg and fg != self.quick_hwnd():  # you tapped the game, switched apps or went back to the main window
                self.close_quick(restore=False)
                return
        if time.time() - self.np_time > 3:
            self.np_time = time.time()
            self.background(lambda: (lambda t: self.call(lambda: setattr(self, "np", t)))(systools.now_playing()))
        self.request_draw()
        self.root.after(500, self.quick_tick)

    @contextlib.contextmanager
    def quick_ctx(self):
        """Point the drawing and input helpers at the quick panel's canvas while inside the block."""
        q = self.quick
        saved = {a: getattr(self, a) for a in QUICK_STATE}
        for a in QUICK_STATE:
            setattr(self, a, q.state[a])
        self.in_panel = True
        try:
            yield
        finally:
            for a in QUICK_STATE:
                q.state[a] = getattr(self, a)
            for a, v in saved.items():
                setattr(self, a, v)
            self.in_panel = False

    def quick_event(self, fn, e):
        if not self.quick or self.in_panel:
            return
        with self.quick_ctx():
            fn(e)
        self.request_draw()

    def quick_key(self, e):
        ks = e.keysym
        nav = {"Up": "up", "Down": "down", "Left": "left", "Right": "right"}
        if ks in nav:
            self.nav(nav[ks])
        elif ks in ("Return", "KP_Enter", "space"):
            self.activate()
        elif ks == "Escape":
            self.root.after(1, self.close_quick)

    def quick_pad(self, b):
        if b == "b":
            self.close_quick()
            return
        if not self.quick:
            return
        with self.quick_ctx():
            if b in ("up", "down", "left", "right"):
                self.nav(b)
            elif b == "a":
                self.activate()
        self.request_draw()

    def later(self, fn):
        """Run fn outside the quick panel's drawing context (for things that change the main window)."""
        self.root.after(1, fn)

    def draw_quick(self):
        with self.quick_ctx():
            self._draw_quick()

    def _draw_quick(self):
        T = self.t
        c = self.c
        W, H = max(c.winfo_width(), 200), max(c.winfo_height(), 200)
        k = self.k = self.quick.k
        c.delete("all")
        c.configure(bg=T["bg"])
        self.regions = []
        self.layer = "main"
        c.create_rectangle(0, 0, W, H, fill=T["bg"], width=0)
        P = 18 * k
        top = 100 * k
        s = self.scrolls.setdefault("qp", {"off": 0.0, "max": 0.0, "y0": top, "h": H - top})
        off = s["off"]
        y = self.quick_body(P, top + 10 * k - off, W - P - 8 * k)
        content = y + off - top + 30 * k
        keep = []
        for r in self.regions:  # rows scrolled under the header or off the bottom can't be tapped
            if r["y0"] >= top - 1 and r["y1"] <= H + 1:
                r["sid"] = r["sid"] or "qp"
                keep.append(r)
        self.regions = keep
        self.scroll_area("qp", 0, top, W, H, content)
        self.regions.insert(0, self.regions.pop())
        # header last, so it covers rows scrolled under it
        c.create_rectangle(0, 0, W, top, fill=T["bg"], width=0)
        c.create_line(0, top, W, top, fill=T["line"], width=max(1, k))
        sf = self.font(12.5 * k, True)
        self.text(P, 18 * k, "QUICK SETTINGS", sf, T["accent"])
        title = self.game["name"] if self.game else time.strftime("%H:%M")
        sub = []
        if self.game:
            sub.append(f"playing {fmt_duration(time.time() - self.game['start'])}")
            sub.append(time.strftime("%H:%M"))
        p = self.power
        if p and p.get("pct", 255) <= 100:
            sub.append(f"{p['pct']}%" + (" charging" if self.batt and self.batt.get("charging") else ""))
        cs = 48 * k
        self.text(P, 40 * k, title, self.font(22 * k, True), T["text"], maxw=W - 2 * P - cs - 10 * k)
        self.text(P, 72 * k, " · ".join(sub), self.font(12.5 * k), T["muted"], maxw=W - 2 * P - cs - 10 * k)
        self.icon_button("q_close", W - P - cs, 26 * k, cs, "close", lambda: self.later(self.close_quick))
        c.create_rectangle(0, 0, max(2, 3 * k), H, fill=T["accent"], width=0)
        self.scrollbar("qp", W - 5 * k, top, H - top)
        if self.toast and time.time() - self.toast[1] < 2.6:
            f = self.font(15 * k, True)
            tw = min(f.measure(self.toast[0]) + 40 * k, W - 2 * P)
            ty = H - P - 46 * k
            self.rr(W / 2 - tw / 2, ty, W / 2 + tw / 2, ty + 46 * k, 23 * k, T["text"])
            self.text(W / 2, ty + 23 * k, self.toast[0], f, T["bg"], anchor="center", maxw=tw - 20 * k)
        if self.focus_visible:
            cur, _ = self.current_focus()
            if cur:
                g = 3 * k
                self.rr(cur["x0"] - g, cur["y0"] - g, cur["x1"] + g, cur["y1"] + g, 14 * k, "", outline=T["accent"], width=max(2, 3 * k))

    # quick panel building blocks: each takes the top y and returns the next y
    def q_label(self, x0, y, text):
        self.text(x0, y + 12 * self.k, text, self.font(12 * self.k, True), self.t["muted"])
        return y + 38 * self.k

    def q_toggle(self, rid, x0, y, x1, label, on, tap, sub="", pending=False):
        T, k = self.t, self.k
        h = (64 if sub else 56) * k
        if self.pressed == rid:
            self.rr(x0 - 6 * k, y, x1 + 6 * k, y + h, 12 * k, T["panel2"])
        cy = y + h / 2
        lf = self.font(15.5 * k, True)
        mw = x1 - x0 - 80 * k
        if sub:
            self.text(x0, cy - 1 * k, label, lf, T["text"], anchor="sw", maxw=mw)
            self.text(x0, cy + 2 * k, sub, self.font(12 * k), T["muted"], anchor="nw", maxw=mw)
        else:
            self.text(x0, cy, label, lf, T["text"], anchor="w", maxw=mw)
        self.toggle_switch(x1, cy, on, pending=pending)
        self.region(rid, x0, y, x1, y + h - 4 * k, tap=tap)
        return y + h

    def q_stepper(self, rid, x0, y, x1, label, value, step, extra=None, vw=None):
        T, k, c = self.t, self.k, self.c
        h = 58 * k
        cy = y + h / 2
        bs = 46 * k
        ew = 104 * k if extra else 0
        cx1 = x1 - (ew + 10 * k if extra else 0)
        vw = (vw or 92) * k
        self.text(x0, cy, label, self.font(15.5 * k, True), T["text"], anchor="w", maxw=cx1 - x0 - 2 * bs - vw - 10 * k)
        self.region(rid, cx1 - 2 * bs - vw, y, cx1, y + h - 4 * k, adjust=step)
        for sign, bx0 in ((-1, cx1 - 2 * bs - vw), (1, cx1 - bs)):
            bid = f"{rid}{'+' if sign > 0 else '-'}"
            fill = mix(T["panel2"], T["accent"], 0.35) if self.pressed == bid else T["panel2"]
            self.rr(bx0, cy - bs / 2, bx0 + bs, cy + bs / 2, 10 * k, fill)
            c.create_text(bx0 + bs / 2, cy, text="+" if sign > 0 else "−", font=self.font(bs * 0.55, True), fill=T["text"])
            self.region(bid, bx0, cy - bs / 2, bx0 + bs, cy + bs / 2, tap=lambda s_=sign: step(s_), focus=False)
        self.text(cx1 - bs - vw / 2, cy, value, self.font(16 * k, True), T["text"], anchor="center", maxw=vw - 6 * k)
        if extra:
            self.button(f"{rid}_x", x1 - ew, cy - bs / 2, x1, cy + bs / 2, extra[0], extra[1], style=extra[2] if len(extra) > 2 else "normal",
                        size=13 * k)
        return y + h

    def q_seg(self, rid, x0, y, x1, options, current, pick, busy=False):
        h = 54 * self.k
        if options:
            self.segmented(rid, x0, y, x1, y + h, options, current, pick, busy=busy)
        return y + h + 10 * self.k

    def quick_body(self, x0, y, x1):
        T, k, c = self.t, self.k, self.c
        legion = self.device["legion"]
        gap = 10 * k
        # live numbers
        st = self.status
        ram = (st.ullTotalPhys - st.ullAvailPhys) / max(1, st.ullTotalPhys) * 100
        tiles = [("FPS", f"{self.fps_stats[0]:.0f}" if self.fps_stats else "–"),
                 ("CPU", f"{self.cpu:.0f}%" if self.cpu is not None else "–"),
                 ("GPU", f"{self.gpu:.0f}%" if self.gpu is not None else "–"), ("RAM", f"{ram:.0f}%")]
        hz = ((self.tools or {}).get("display") or {}).get("hz") or 60
        fracs = [min(1.0, self.fps_stats[0] / hz) if self.fps_stats else 0.0, (self.cpu or 0) / 100, (self.gpu or 0) / 100, ram / 100]
        tw = (x1 - x0 - gap * 3) / 4
        d = min(tw - 14 * k, 84 * k)
        for i, ((lbl, val), frac) in enumerate(zip(tiles, fracs)):
            cx = x0 + i * (tw + gap) + tw / 2
            cy = y + d / 2 + 4 * k
            col = T["accent2"] if lbl == "FPS" else T["accent"] if frac < 0.8 else T["warn"] if frac < 0.93 else T["danger"]
            self.ring(cx, cy, d / 2, frac, col, max(4, 7 * k))
            self.text(cx, cy - 2 * k, val, self.font(min(19 * k, d * 0.26), True), T["text"], anchor="center", maxw=d - 18 * k)
            self.text(cx, cy + d * 0.2, lbl, self.font(10.5 * k, True), T["muted"], anchor="center")
        y += d + 16 * k
        b = self.batt
        if b and b.get("discharging") and b.get("rate_mw"):
            w = abs(b["rate_mw"]) / 1000
            left = b["remaining_mwh"] / abs(b["rate_mw"]) * 3600
            self.text(x0, y, f"Battery draw {w:.1f} W · about {fmt_duration(left)} left", self.font(12.5 * k), T["muted"], maxw=x1 - x0)
            y += 26 * k
        y += 6 * k
        if b:
            y = self.q_label(x0, y, "BATTERY GOAL")
            y = self.q_seg("q_bgoal", x0, y, x1, [(m, self.bgoal_label(m)) for m in self.BGOAL_OPTS], self.cfg["batt_goal"], self.set_bgoal)
            if self.cfg["batt_goal"]:
                self.text(x0, y - 4 * k, self.bgoal_status(), self.font(12.5 * k), T["muted"], maxw=x1 - x0)
                y += 26 * k
            y += 8 * k

        # performance
        y = self.q_label(x0, y, "PERFORMANCE")
        y = self.q_seg("q_prof", x0, y, x1, [(p[0], {"saver": "Saver", "balanced": "Balanced", "max": "Max"}[p[0]]) for p in systools.PROFILES],
                       self.cfg["profile"], self.apply_profile, busy=self.profile_busy)
        tools = self.tools or {}
        if legion:
            y = self.q_seg("q_therm", x0, y, x1, [(v, n) for v, n in systools.THERMAL_MODES], tools.get("thermal"), self.set_thermal,
                           busy="thermal" in self.tools_busy)
            now = tools.get("tdp")
            lo, hi = 5, self.tdp_max
            y = self.q_slider("q_tdp", x0, y, x1, "TDP" if not now or now == self.cfg["tdp"] else f"TDP · now {now} W",
                              (self.cfg["tdp"] - lo) / (hi - lo), f"{self.cfg['tdp']} W",
                              lambda f, final: self.cfg.__setitem__("tdp", int(round(lo + f * (hi - lo)))),
                              lambda d: self.step_tdp(d),
                              ("SETTING…" if self.tdp_busy else "APPLY", self.apply_tdp, "accent" if self.is_armed("tdp") else "normal"))
            y = self.q_toggle("q_atdp", x0, y, x1, "Auto TDP", self.cfg["auto_tdp"], self.toggle_auto_tdp,
                              sub=(f"Holding {self.cfg['auto_tdp_target']} FPS" + (f" at {self.atdp_w} W" if self.atdp_w else "") +
                                   ("" if self.game else " in your next game")) if self.cfg["auto_tdp"] else
                              "Finds the lowest wattage that holds your FPS target")
            if self.cfg["auto_tdp"]:
                y = self.q_seg("q_atdp_t", x0, y, x1, [(t, f"{t} FPS") for t in AUTO_TDP_TARGETS], self.cfg["auto_tdp_target"],
                               lambda t: (self.cfg.__setitem__("auto_tdp_target", t), self.request_draw()))
            if self.game:
                b = self.bench
                label = (f"TESTING {b['steps'][b['i']]} W · {b['i'] + 1}/{len(b['steps'])} · TAP TO STOP" if b else "FIND MY BEST TDP")
                self.button("q_bench", x0, y, x1, y + 54 * k, label, self.stop_bench if b else self.start_bench,
                            style="accent" if b else "normal", size=13 * k)
                y += 54 * k + gap
        cm = self.cpu_max_now
        if cm is not None:
            y = self.q_seg("q_cpumax", x0, y, x1, [(100, "CPU FULL"), (99, "NO BOOST"), (80, "80%"), (60, "60%")],
                           cm if cm in (100, 99, 80, 60) else None, self.set_cpu_max_now)
        y += 8 * k

        # display & sound
        y = self.q_label(x0, y, "SCREEN & SOUND")
        disp = tools.get("display")
        if disp:
            rates = disp["rates"][-4:]
            y = self.q_seg("q_hz", x0, y, x1, [(r, f"{r} Hz") for r in rates], disp["hz"], self.set_refresh)
            sizes = disp["sizes"][:4]
            y = self.q_seg("q_res", x0, y, x1, [(sz, f"{sz[1]}p") for sz in sizes], (disp["w"], disp["h"]), self.set_resolution)
        br = self.brightness
        y = self.q_slider("q_bright", x0, y, x1, "Brightness", (br or 0) / 100, "…" if br is None else f"{br}%",
                          self.drag_brightness,
                          lambda d: self.set_brightness(max(0, min(100, (br if br is not None else 50) + 10 * d))))
        y = self.q_stepper("q_vol", x0, y, x1, "Volume", "", lambda d: systools.volume_key("up" if d > 0 else "down", 2),
                           ("MUTE", lambda: systools.volume_key("mute")))
        y += 8 * k

        # media
        y = self.q_label(x0, y, "MEDIA")
        if self.np:
            self.text(x0, y, "♪  " + self.np, self.font(14 * k, True), T["text"], maxw=x1 - x0)
            y += 30 * k
        mw = (x1 - x0 - 2 * gap) / 3
        for i, (rid, label, what) in enumerate((("q_prev", "⏮  PREV", "prev"), ("q_play", "⏯  PLAY / PAUSE", "play"),
                                                ("q_next", "NEXT  ⏭", "next"))):
            bx = x0 + i * (mw + gap)
            self.button(rid, bx, y, bx + mw, y + 54 * k, label, lambda w=what: self.media(w), size=13 * k)
        y += 54 * k + 18 * k

        # connections
        y = self.q_label(x0, y, "CONNECTIONS")
        rad = self.radios
        for key, label in (("wifi", "Wi-Fi"), ("bluetooth", "Bluetooth")):
            if rad is None or key in rad:
                y = self.q_toggle(f"q_radio_{key}", x0, y, x1, label, bool(rad and rad.get(key)),
                                  lambda kk=key: self.toggle_radio(kk), pending=rad is None or key in self.radio_busy)
        n = self.net
        if self.net_busy:
            ntext, ncol = "Checking…", T["muted"]
        elif n:
            bits = ["no internet" if n["ms"] is None else f"ping {n['ms']:.0f} ms" + (f", {n['lost']} lost" if n["lost"] else "")]
            if n.get("signal") is not None:
                bits.append(f"Wi-Fi {n['signal']}%" + (f" ({n['ssid']})" if n.get("ssid") else ""))
            ncol = T["danger"] if n["ms"] is None else T["good"] if n["ms"] < 60 and not n["lost"] else T["warn"]
            ntext = " · ".join(bits)
        else:
            ntext, ncol = "Check your connection before an online match", T["muted"]
        bw2 = 120 * k
        self.text(x0, y + 27 * k, ntext, self.font(13.5 * k, True), ncol, anchor="w", maxw=x1 - x0 - bw2 - 10 * k)
        self.button("q_net", x1 - bw2, y, x1, y + 54 * k, "TESTING…" if self.net_busy else "TEST", self.check_network, size=13 * k)
        y += 54 * k + gap
        hw = (x1 - x0 - gap) / 2
        self.button("q_hdr", x0, y, x0 + hw, y + 54 * k, "HDR ON / OFF", self.toggle_hdr, size=13 * k)
        self.button("q_night", x0 + hw + gap, y, x1, y + 54 * k, "NIGHT LIGHT…",
                    lambda: self.later(lambda: (self.close_quick(restore=False), systools.open_settings("nightlight"))), size=13 * k)
        y += 54 * k + 18 * k

        # AMD
        amd = self.quick_amd
        if amd is None or amd:
            y = self.q_label(x0, y, "RADEON")
        if amd is None:
            self.text(x0, y, "Reading AMD settings…", self.font(13 * k), T["muted"])
            y += 40 * k
        elif amd:
            if "frtc" in amd:
                cap = amd["frtc"].get("fps") if amd["frtc"].get("on") else 0
                y = self.q_seg("q_cap", x0, y, x1, [(0, "No cap")] + [(n, str(n)) for n in (30, 40, 45, 60)], cap,
                               lambda n: self.quick_amd_set({"frtc": False} if not n else {"chill": False, "frtc": True, "frtc_fps": n}))
            for key, label in (("rsr", "Radeon Super Resolution"), ("afmf", "Fluid Motion Frames"), ("antilag", "Anti-Lag"),
                               ("ris", "Image Sharpening")):
                if key in amd:
                    on = bool(amd[key].get("on"))
                    y = self.q_toggle(f"q_amd_{key}", x0, y, x1, label, on, lambda kk=key, o=on: self.quick_amd_set({kk: not o}))
            y += 8 * k

        # toggles
        y = self.q_label(x0, y, "HELPERS")
        y = self.q_toggle("q_overlay", x0, y, x1, "Mini monitor", self.cfg["overlay"], self.toggle_overlay)
        y = self.q_toggle("q_focus", x0, y, x1, "Focus mode", bool(self.focus), self.focus_toggle, pending=self.focus_busy,
                          sub="Background apps paused and minimized")
        y = self.q_toggle("q_fps", x0, y, x1, "FPS counter", self.cfg["fps_counter"], self.toggle_fps)
        if legion:
            y = self.q_toggle("q_charge", x0, y, x1, "Stop charging at 80%", bool(self.charge_limit), self.toggle_charge_limit,
                              pending=self.charge_busy or self.charge_limit is None,
                              sub="Topping up to 100% once, then back to 80%" if self.cfg["topup"] else "")
            if self.charge_limit and not self.cfg["topup"]:
                self.button("q_topup", x0, y, x1, y + 50 * k, "TOP UP TO 100% ONCE (FOR A TRIP)", self.topup, size=12.5 * k)
                y += 50 * k + gap
        y += 8 * k

        # controller lights
        if legion:
            y = self.q_label(x0, y, "CONTROLLER LIGHTS")
            mode = self.cfg["rgb_mode"]
            y = self.q_seg("q_rgbm", x0, y, x1, [(m, RGB_MODE_LABELS[m]) for m in ("off", "solid", "pulse", "dynamic", "spiral")],
                           mode, lambda m: self.set_rgb(mode=m))
            n = len(RGB_COLORS)
            sw = min(52 * k, (x1 - x0 - (n - 1) * 8 * k) / n)
            for i, col in enumerate(RGB_COLORS):
                sx = x0 + i * (sw + 8 * k)
                sel = col == self.cfg["rgb_color"]
                if sel:
                    c.create_oval(sx - 3 * k, y - 3 * k, sx + sw + 3 * k, y + sw + 3 * k, outline=T["text"], width=max(2, 2.5 * k))
                c.create_oval(sx + 2 * k, y + 2 * k, sx + sw - 2 * k, y + sw - 2 * k, fill=col, outline="")
                self.region(f"q_rgbc{i}", sx, y, sx + sw, y + sw, tap=lambda cc=col: self.set_rgb(color=cc))
            y += sw + 12 * k
            y = self.q_stepper("q_rgbb", x0, y, x1, "Light brightness", f"{self.cfg['rgb_brightness']}%",
                               lambda d: self.set_rgb(brightness=max(10, min(100, self.cfg["rgb_brightness"] + 10 * d))))
            hw = (x1 - x0 - gap) / 2
            if self.game:
                gk = self.game_key(self.game)
                saved = gk in self.cfg["game_lights"]
                self.button("q_glights", x0, y, x0 + hw, y + 54 * k, "FORGET GAME LIGHTS" if saved else "SAVE FOR THIS GAME",
                            lambda: self.save_game_lights(not saved), size=12.5 * k)
            self.button("q_backbtn", x1 - hw if self.game else x0, y, x1, y + 54 * k, "BACK BUTTONS…",
                        lambda: self.later(lambda: (self.close_quick(restore=False), self.open_hub(), self.open_back_buttons())),
                        size=12.5 * k)
            y += 54 * k + gap
            y += 8 * k

        # discord
        disc = (self.ls_info or {}).get("discord")
        hook = systools.valid_webhook(self.cfg["discord_webhook"])
        if disc or hook:
            y = self.q_label(x0, y, "DISCORD")
            dacts = []
            if disc:
                dacts += [("q_dmute", "MUTE MIC", lambda: self.discord_voice("mute")),
                          ("q_ddeaf", "DEAFEN", lambda: self.discord_voice("deafen"))]
            dacts.append(("q_shot", "SCREENSHOT", lambda: self.later(self.quick_screenshot)))
            if hook:
                dacts.append(("q_share", "SHARING…" if self.share_busy else "SHARE LAST SHOT", self.share_screenshot))
            bh, bw = 58 * k, (x1 - x0 - gap) / 2
            for i, (rid, label, fn) in enumerate(dacts):
                bx = x0 + (i % 2) * (bw + gap)
                by = y + (i // 2) * (bh + gap)
                self.button(rid, bx, by, bx + bw, by + bh, label, fn, size=13.5 * k)
            y += ((len(dacts) + 1) // 2) * (bh + gap) + 8 * k

        # actions
        y = self.q_label(x0, y, "ACTIONS")
        acts = [("q_boost", "GAME BOOST", lambda: self.run("boost"), "normal"),
                ("q_hub", "OPEN THE HUB", lambda: self.later(lambda: (self.close_quick(restore=False), self.open_hub())), "normal"),
                ("q_kbd", "KEYBOARD", lambda: self.later(lambda: (self.close_quick(), self.do_action("keyboard"))), "normal"),
                ("q_tasks", "TASK VIEW", lambda: self.later(lambda: (self.close_quick(), self.do_action("taskview"))), "normal"),
                ("q_record", "STOP RECORDING" if getattr(self, "recording", False) else "RECORD", self.toggle_recording,
                 "accent" if getattr(self, "recording", False) else "normal")]
        if self.game:
            acts += [("q_suspend", "RESUME GAME" if self.suspended else "SUSPEND GAME", lambda: self.later(self.toggle_suspend), "normal")]
            acts += [("q_tune", "GAME SETTINGS", lambda: self.later(self.quick_game_settings), "normal"),
                     ("q_endgame", "TAP AGAIN TO CLOSE" if self.is_armed("q_endgame") else "CLOSE GAME",
                      lambda: self.confirm("q_endgame", self.quick_close_game, "Tap again to close the game"), "danger")]
        for rid, label, what in (("q_sleep", "SLEEP", "sleep"), ("q_restart", "RESTART", "restart"), ("q_shutdown", "SHUT DOWN", "shutdown")):
            armed = self.is_armed(rid)
            acts.append((rid, f"TAP AGAIN TO {label}" if armed else label,
                         lambda r=rid, w=what, l=label: self.confirm(r, lambda: self.power_action(w), f"Tap again to {l.lower()}"),
                         "danger" if armed else "normal"))
        bh = 58 * k
        bw = (x1 - x0 - gap) / 2
        for i, (rid, label, fn, style) in enumerate(acts):
            bx = x0 + (i % 2) * (bw + gap)
            by = y + (i // 2) * (bh + gap)
            self.button(rid, bx, by, bx + bw, by + bh, label, fn, style=style, size=13.5 * k)
        y += ((len(acts) + 1) // 2) * (bh + gap)
        return y

    def quick_amd_set(self, settings):
        def work():
            done = systools.ADLX.apply(settings)
            st = systools.ADLX.read()

            def fin():
                self.quick_amd = st
                self.show_toast(", ".join(done) if done else "The driver didn't take that")
                if done:
                    self.add_log("TOOL", "Quick settings: " + ", ".join(done))
                self.request_draw()

            self.call(fin)

        self.background(work)

    def quick_game_settings(self):
        g = self.game
        self.close_quick(restore=False)
        self.open_hub()
        if g:
            key = (g.get("hub") or {}).get("id") or os.path.splitext(g["exe"])[0].lower()
            self.open_tune(key, g["name"])

    def quick_close_game(self):
        g = self.game
        if not g:
            return
        ok = systools.end_process(g["pid"], g["exe"])
        self.add_log("GAME", f"{g['name']}: " + ("closed from quick settings" if ok else "couldn't be closed"))
        self.show_toast(f"Closed {g['name']}" if ok else "Couldn't close the game")
        if ok:
            self.later(lambda: self.close_quick(restore=False))

    def set_rgb(self, mode=None, color=None, brightness=None):
        if mode:
            self.cfg["rgb_mode"] = mode
        if color:
            self.cfg["rgb_color"] = color
            if self.cfg["rgb_mode"] in ("keep", "off", "dynamic"):
                self.cfg["rgb_mode"] = "solid"
        if brightness:
            self.cfg["rgb_brightness"] = brightness
        self.apply_rgb()
        self.request_draw()

    def apply_rgb(self, quiet=False, override=None):
        o = override or {}
        mode = o.get("mode", self.cfg["rgb_mode"])
        if mode == "keep":
            return
        if not self.legion or not self.legion.connected:
            if not quiet:
                self.show_toast("Controllers not found: attach them to the Legion Go")
            return
        packets = systools.rgb_packets(mode, o.get("color", self.cfg["rgb_color"]), o.get("brightness", self.cfg["rgb_brightness"]) / 100)

        def work():
            ok = self.legion.write(packets) if self.legion else False
            if not ok and not quiet:
                self.call(lambda: self.show_toast("The controllers didn't take the light setting"))

        self.background(work)

    def ring(self, cx, cy, r, frac, color, width):
        """A circular gauge: a faint track with an arc for frac (0..1), starting at the top."""
        T, c = self.t, self.c
        c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=mix(T["panel2"], T["line"], 0.5), width=width)
        frac = max(0.0, min(1.0, frac))
        if frac >= 0.999:
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=color, width=width)
        elif frac > 0.005:
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=-360 * frac, style="arc", outline=color, width=width)

    def q_slider(self, rid, x0, y, x1, label, frac, value, on_drag, step, extra=None):
        """Label + value on top, a draggable track below. on_drag(frac, final)."""
        T, k, c = self.t, self.k, self.c
        lf = self.font(15.5 * k, True)
        ew = 104 * k if extra else 0
        self.text(x0, y + 18 * k, label, lf, T["text"], anchor="w", maxw=(x1 - x0) * 0.55)
        self.text(x1 - (ew + 12 * k if extra else 0), y + 18 * k, value, self.font(15.5 * k, True), T["accent"], anchor="e")
        if extra:
            self.button(f"{rid}_x", x1 - ew, y, x1, y + 38 * k, extra[0], extra[1], style=extra[2] if len(extra) > 2 else "normal", size=12.5 * k)
        ty = y + 64 * k
        frac = max(0.0, min(1.0, frac))
        tx0, tx1 = x0 + 14 * k, x1 - 14 * k
        th = 8 * k
        self.rr(tx0, ty - th / 2, tx1, ty + th / 2, th / 2, T["panel2"])
        fx = tx0 + (tx1 - tx0) * frac
        if fx > tx0 + 1:
            self.rr(tx0, ty - th / 2, fx, ty + th / 2, th / 2, T["accent"])
        kr = 15 * k if self.pressed == rid or (self.press and self.press.get("r") and self.press["r"]["id"] == rid) else 13 * k
        c.create_oval(fx - kr, ty - kr, fx + kr, ty + kr, fill=T["text"], outline=T["accent"], width=max(2, 3 * k))
        self.region(rid, x0, ty - 26 * k, x1, ty + 26 * k, adjust=step)
        self.regions[-1]["drag"] = lambda ex, final: on_drag(max(0.0, min(1.0, (ex - tx0) / max(1, tx1 - tx0))), final)
        return y + 98 * k

    def drag_brightness(self, frac, final):
        pct = int(round(frac * 20)) * 5
        self.brightness = pct
        if final:
            self.set_brightness(pct)

    # -------------------------------------------------------------- checkup
    def open_checkup(self):
        self.page = "checkup"
        self.focus_id = None
        self.set_off("checkup", 0) if "checkup" in self.scrolls else None
        self.refresh_checkup()
        self.request_draw()

    def refresh_checkup(self):
        if self.tools is None or "tweaks" not in (self.tools or {}):
            self.load_tools()
        if self.startup_items is None:
            self.load_startup()
        self.ls_time = 0
        self.load_ls_info()
        self.checkup_busy = True

        def work():
            c = next((d for d in systools.drives() if d[0] == "C"), None)
            self.call(lambda: (setattr(self, "disk_c", c), setattr(self, "checkup_busy", False), self.request_draw()))

        self.background(work)

    def checkup_items(self):
        """Findings: (id, level 'bad'/'warn'/'tip', title, detail, fix label, fix, include in FIX ALL)."""
        out = []
        tools = self.tools or {}
        tw = tools.get("tweaks") or {}
        legion = self.device["legion"]
        ls = (self.ls_info or {}).get("procs") or []
        if ls:
            used = sum(p[2] for p in ls)
            out.append(("ls_run", "bad", f"Legion Space is running ({fmt_bytes(used)})",
                        "Vanta does its everyday jobs, so this RAM can go to your game", "CLOSE IT", self.close_legion_space, True))
        if self.legion_startup_state():
            out.append(("ls_start", "warn", "Legion Space starts with Windows", "It opens itself at every sign-in",
                        "STOP IT", lambda: self.set_legion_startup(False), True))
        if self.startup is False and (legion or ls):
            out.append(("v_start", "warn", "Vanta doesn't start with Windows", "The Legion buttons only work while Vanta runs",
                        "TURN ON", lambda: self.adjust("startup", 1), True))
        if tw.get("gamemode") is False:
            out.append(("gamemode", "warn", "Game Mode is off", "Windows won't put your game first", "TURN ON",
                        lambda: self.toggle_tweak("gamemode", True), True))
        if tw.get("dvr"):
            out.append(("dvr", "warn", "Background recording is on", "Game Bar keeps recording your games, which costs FPS",
                        "TURN OFF", lambda: self.toggle_tweak("dvr", False), True))
        st = self.status
        frac = (st.ullTotalPhys - st.ullAvailPhys) / max(1, st.ullTotalPhys)
        if frac > 0.8:
            out.append(("ram", "warn", f"Memory is {frac * 100:.0f}% full", "Games stutter when Windows runs out of RAM",
                        "GAME BOOST", lambda: self.run("boost"), True))
        if self.disk_c and self.disk_c[2] < self.disk_c[1] * 0.12:
            out.append(("disk", "warn", f"Drive C is almost full ({fmt_bytes(self.disk_c[2])} free)",
                        "Windows and shader caches need room to work smoothly", "CLEAN UP",
                        lambda: (setattr(self, "page", None), self.set_tab("clean")), False))
        if self.needs_restart:
            out.append(("restart", "warn", "Restart to finish applying settings", "Some changes only take effect after a restart",
                        "TAP AGAIN" if self.is_armed("restart") else "RESTART",
                        lambda: self.confirm("restart", systools.restart_pc, "Tap again to restart in 5 seconds"), False))
        if tw.get("diagtrack"):
            out.append(("diagtrack", "tip", "Telemetry service is running", "Sends usage data to Microsoft in the background",
                        "TURN OFF", lambda: self.toggle_tweak("diagtrack", False), True))
        if tw.get("bgapps"):
            out.append(("bgapps", "tip", "Store apps run in the background", "They wake up and sync even when closed",
                        "TURN OFF", lambda: self.toggle_tweak("bgapps", False), True))
        if tw.get("hvci"):
            out.append(("hvci", "tip", "Memory integrity is on", "Microsoft suggests turning it off for gaming. It's a security feature",
                        "REVIEW", lambda: (setattr(self, "page", None), self.set_tab("tools")), False))
        if self.on_battery:
            disp = tools.get("display")
            if disp and len(disp["rates"]) > 1 and disp["hz"] > disp["rates"][0]:
                low = disp["rates"][0]
                out.append(("hz", "tip", f"Screen runs at {disp['hz']} Hz on battery", f"{low} Hz uses noticeably less power",
                            f"USE {low} HZ", lambda: self.set_refresh(low), False))
            if tw.get("boost_dc"):
                out.append(("boost", "tip", "CPU boost is on while on battery", "Turning it off runs cooler and lasts longer",
                            "TURN OFF", lambda: self.toggle_tweak("boost_dc", False), False))
        many = [i for i in (self.startup_items or []) if i["enabled"] and not i["legion"]]
        if len(many) > 8:
            out.append(("startup", "tip", f"{len(many)} apps start with Windows", "Each one slows sign-in and uses RAM",
                        "REVIEW", lambda: (setattr(self, "page", None), self.set_tab("startup")), False))
        return out

    def checkup_score(self, items):
        pen = {"bad": 15, "warn": 8, "tip": 3}
        return max(0, 100 - sum(pen[i[1]] for i in items))

    def fix_all(self):
        items = [i for i in self.checkup_items() if i[6]]
        for it in items:
            try:
                it[5]()
            except Exception as ex:
                self.add_log("FAIL", f"Checkup fix {it[0]}: {ex}")
        self.add_log("TOOL", f"Checkup: fixed {len(items)} thing(s)")
        self.show_toast(f"Fixed {len(items)} thing(s)" if items else "Nothing to fix automatically")
        self.buzz()
        self.root.after(2500, self.refresh_checkup)
        self.request_draw()

    def draw_checkup(self, x0, y0, x1, y1):
        T, k, c = self.t, self.k, self.c
        items = self.checkup_items()
        loading = self.checkup_busy or self.ls_info is None or self.tools is None or "tweaks" not in (self.tools or {}) \
            or self.startup_items is None
        score = self.checkup_score(items)
        land = x1 - x0 > 620 * k
        lw = 250 * k if land else x1 - x0
        # score ring
        d = min(170 * k, lw - 40 * k)
        cx, cy = x0 + lw / 2, y0 + d / 2 + 6 * k
        col = T["good"] if score >= 85 else T["warn"] if score >= 60 else T["danger"]
        self.ring(cx, cy, d / 2, score / 100, col, max(6, 12 * k))
        self.text(cx, cy - 6 * k, "…" if loading and not items else str(score), self.font(d * 0.3, True), T["text"], anchor="center")
        self.text(cx, cy + d * 0.2, "SCORE", self.font(12 * k, True), T["muted"], anchor="center")
        yy = y0 + d + 22 * k
        verdict = "Checking…" if loading else "All set" if not items else "Looking good" if score >= 85 else \
            "A few things to fix" if score >= 60 else "Needs attention"
        self.text(cx, yy, verdict, self.font(18 * k, True), col if not loading else T["muted"], anchor="n", maxw=lw)
        yy += 36 * k
        n_auto = sum(1 for i in items if i[6])
        bh = 54 * k
        self.button("ck_fixall", x0 + 10 * k, yy, x0 + lw - 10 * k, yy + bh, f"FIX ALL ({n_auto})" if n_auto else "NOTHING TO FIX",
                    self.fix_all, style="accent" if n_auto else "ghost", size=14 * k)
        yy += bh + 10 * k
        self.button("ck_again", x0 + 10 * k, yy, x0 + lw - 10 * k, yy + bh, "CHECK AGAIN", self.refresh_checkup, size=14 * k)
        yy += bh + 14 * k
        if loading:
            self.spinner(cx, yy + 14 * k, 12 * k)
        # findings
        lx0, ly0 = (x0 + lw + 24 * k, y0) if land else (x0, yy + 30 * k)
        if ly0 > y1 - 80 * k:
            return
        rh = 86 * k
        if not items:
            self.text((lx0 + x1) / 2, (ly0 + y1) / 2, "Nothing to fix. Your Legion Go is set up for gaming." if not loading else "",
                      self.font(16 * k), T["muted"], anchor="center", maxw=x1 - lx0 - 20 * k)
            return
        off = self.scroll_area("checkup", lx0, ly0, x1, y1, rh * len(items))
        self.clip_to(ly0, y1)
        nf, df = self.font(15.5 * k, True), self.font(12.5 * k)
        levels = {"bad": T["danger"], "warn": T["warn"], "tip": T["accent"]}
        for i, (iid, level, title, detail, fix_label, fix, _) in enumerate(items):
            ry0 = ly0 + i * rh - off
            ry1 = ry0 + rh - 8 * k
            if ry1 < ly0 or ry0 > y1:
                continue
            self.rr(lx0, ry0, x1 - 10 * k, ry1, 14 * k, T["panel2"])
            self.rr(lx0, ry0, lx0 + 6 * k, ry1, 3 * k, levels[level])
            bw = 136 * k
            mid = (ry0 + ry1) / 2
            tx = lx0 + 22 * k
            maxw = x1 - 10 * k - bw - 24 * k - tx
            self.text(tx, mid - 2 * k, title, nf, T["text"], anchor="sw", maxw=maxw)
            self.text(tx, mid + 3 * k, detail, df, T["muted"], anchor="nw", maxw=maxw)
            self.button(f"ck_{iid}", x1 - 22 * k - bw, mid - 24 * k, x1 - 22 * k, mid + 24 * k, fix_label,
                        lambda f=fix: (f(), self.root.after(1500, self.refresh_checkup)),
                        style="danger" if level == "bad" else "normal", size=12.5 * k, sid="checkup")
        self.end_clip()
        self.scrollbar("checkup", x1 - 4 * k, ly0, y1 - ly0)

    # -------------------------------------------------------------- welcome (first run)
    def maybe_welcome(self):
        if not self.cfg["welcomed"] and not self.page:
            self.page = "welcome"
            self.focus_id = None
            if self.startup_items is None:
                self.load_startup()
            self.ls_time = 0
            self.load_ls_info()
            self.request_draw()

    def welcome_options(self):
        out = [("startup", f"Start {APP_NAME} with Windows", "In the tray, so the Legion buttons always work"
                if self.device["legion"] else "In the tray, ready when you are")]
        if self.device["legion"]:
            out += [("buttons", "Use the Legion L and R buttons (optional)", "L opens this hub, R opens quick settings. Off: the controllers work like a normal Xbox controller"),
                    ("ls_startup", "Stop Legion Space starting with Windows", "You can still open it yourself for firmware updates")]
            if (self.ls_info or {}).get("procs"):
                out.append(("ls_close", "Close Legion Space now",
                            f"Gives back {fmt_bytes(sum(p[2] for p in self.ls_info['procs']))} of RAM"))
        out.append(("recommended", "Use the recommended FPS settings", "Game Mode on, background recording off and other safe picks"))
        return out

    def finish_welcome(self, apply=True):
        self.cfg["welcomed"] = True
        self.page = None
        if apply:
            sel = self.welcome_sel
            done = []
            if "startup" in sel and self.startup is False:
                self.adjust("startup", 1)
                done.append("start with Windows")
            if "buttons" in sel and self.device["legion"] and not self.cfg["legion_buttons"]:
                self.adjust("legion_buttons", 1)
            if "buttons" not in sel and self.cfg["legion_buttons"] and self.device["legion"]:
                self.adjust("legion_buttons", 1)
            if "ls_startup" in sel and self.legion_startup_state():
                self.set_legion_startup(False)
                done.append("Legion Space startup off")
            if "ls_close" in sel and (self.ls_info or {}).get("procs"):
                self.close_legion_space()
                done.append("Legion Space closed")
            if "recommended" in sel:
                def work():
                    tw = systools.read_tweaks()

                    def fin():
                        self.tools = self.tools or {}
                        self.tools["tweaks"] = tw
                        self.apply_recommended()
                    self.call(fin)
                self.background(work)
            self.add_log("BOOT", "Welcome: " + (", ".join(done) if done else "set up"))
        self.buzz()
        self.request_draw()

    def draw_welcome(self, x0, y0, x1, y1):
        T, k, c = self.t, self.k, self.c
        df = self.font(14 * k)
        y = y0
        intro = ("Vanta Go can take over from Legion Space: the Legion buttons, quick settings, power modes and "
                 "controller lights, with no store and no ads. Pick what you'd like:") if self.device["legion"] else \
            ("Your games from every store in one place, plus one-tap tools to keep this PC fast. Pick what you'd like:")
        if PREVIEW:
            intro = ("This is the Preview build. It doesn't need admin, keeps its own settings, and won't change this PC "
                     "while \"Don't change this PC\" is on in Settings. " + intro)
        for ln in self.wrap(intro, df, x1 - x0):
            self.text(x0, y, ln, df, T["muted"])
            y += df.metrics("linespace")
        y += 12 * k
        rh = 66 * k
        nf, sf = self.font(16 * k, True), self.font(12.5 * k)
        for oid, title, sub in self.welcome_options():
            on = oid in self.welcome_sel
            rid = f"wel_{oid}"
            if self.pressed == rid:
                self.rr(x0 - 8 * k, y, x1 + 8 * k, y + rh - 6 * k, 12 * k, T["panel2"])
            cy = y + (rh - 6 * k) / 2
            self.checkbox(x0, cy, on)
            self.text(x0 + 44 * k, cy - 1 * k, title, nf, T["text"], anchor="sw", maxw=x1 - x0 - 50 * k)
            self.text(x0 + 44 * k, cy + 3 * k, sub, sf, T["muted"], anchor="nw", maxw=x1 - x0 - 50 * k)
            self.region(rid, x0 - 8 * k, y, x1 + 8 * k, y + rh - 6 * k,
                        tap=lambda o=oid: (self.welcome_sel.symmetric_difference_update({o}), self.request_draw()))
            y += rh
        y += 6 * k
        self.text(x0, y, "LOOK", self.font(12.5 * k, True), T["muted"])
        y += 26 * k
        picks = [n for n in ("OLED Black", "Midnight", "Aurora", "Daylight", "Synthwave", "Mint") if n in THEMES][:5]
        n = len(picks)
        sw = (x1 - x0 - (n - 1) * 10 * k) / max(1, n)
        sh = 60 * k
        for i, name in enumerate(picks):
            th = THEMES[name]
            sx = x0 + i * (sw + 10 * k)
            sel = self.cfg["theme"] == name
            self.rr(sx, y, sx + sw, y + sh, 12 * k, th["bg"], outline=th["accent"] if sel else T["line"], width=max(2, 3 * k) if sel else max(1, k))
            c.create_oval(sx + 12 * k, y + sh / 2 - 8 * k, sx + 28 * k, y + sh / 2 + 8 * k, fill=th["accent"], outline="")
            self.text(sx + 36 * k, y + sh / 2, name, self.font(13 * k, True), th["text"], anchor="w", maxw=sw - 44 * k)
            self.region(f"wel_t{i}", sx, y, sx + sw, y + sh, tap=lambda nm=name: self.set_theme(nm))
        y += sh + 18 * k
        bh = 60 * k
        by = max(y, y1 - bh)
        self.button("wel_skip", x0, by, x0 + (x1 - x0) * 0.32, by + bh, "SKIP", lambda: self.finish_welcome(False), style="ghost")
        self.button("wel_go", x0 + (x1 - x0) * 0.32 + 12 * k, by, x1, by + bh, "GET STARTED", self.finish_welcome, style="accent")

    # -------------------------------------------------------------- per-game helpers
    def game_key(self, g):
        if not g:
            return None
        return (g.get("hub") or {}).get("id") or os.path.splitext(g.get("exe") or g["name"])[0].lower()

    # -------------------------------------------------------------- auto TDP
    def toggle_auto_tdp(self):
        c = self.cfg
        if not c["auto_tdp"] and not systools.presentmon_installed():
            self.show_toast("Auto TDP needs the FPS counter: setting it up first")
            self.get_presentmon()
            return
        c["auto_tdp"] = not c["auto_tdp"]
        if c["auto_tdp"] and self.game and not self.fps:
            try:
                self.fps = systools.FpsReader(self.game["pid"])
            except Exception as ex:
                self.add_log("FAIL", f"FPS counter: {ex}")
        if not c["auto_tdp"] and self.atdp_w is not None and self.atdp_start:
            w0 = self.atdp_start
            self.background(lambda: systools.set_tdp(w0, self.tdp_max))
            self.atdp_w = None
        self.add_log("TOOL", f"Auto TDP {'on' if c['auto_tdp'] else 'off'}" + (f", target {c['auto_tdp_target']} FPS" if c["auto_tdp"] else ""))
        self.request_draw()

    def auto_tdp_step(self):
        """Every few seconds: below target, add watts; at or above target, try one watt less."""
        c = self.cfg
        if not (c["auto_tdp"] and self.game and self.device["legion"] and self.fps_stats) or self.atdp_busy or self.tdp_busy \
                or self.suspended or (self.bgoal and self.bgoal.get("end")):
            return
        now = time.time()
        if now - self.atdp_t < 4 or now - self.game["start"] < 20:  # let loading screens pass
            return
        self.atdp_t = now
        fps, tgt = self.fps_stats[0], c["auto_tdp_target"]
        cur = self.atdp_w or (self.tools or {}).get("tdp") or c["tdp"]
        lo, hi = max(5, c["auto_tdp_min"]), self.tdp_max
        if fps < tgt - 3:
            w = min(hi, cur + (3 if fps < tgt * 0.8 else 1))
            self.atdp_up = now
        elif fps >= tgt - 1 and now - self.atdp_up > 12:
            w = max(lo, cur - 1)
        else:
            return
        if w == cur:
            return
        self.atdp_busy = True

        def work():
            ok = systools.set_tdp(w, hi)

            def fin():
                self.atdp_busy = False
                if ok:
                    self.atdp_w = w
                    if self.tools is not None:
                        self.tools["tdp"] = w
                self.request_draw()

            self.call(fin)

        self.background(work)

    # -------------------------------------------------------------- back buttons
    def back_map(self):
        m = dict(self.cfg["back_map"])
        if self.game:
            m.update(self.cfg["back_map_game"].get(self.game_key(self.game), {}))
        return m

    def back_event(self, name, down):
        act = self.back_map().get(name, "none")
        kind, _, v = act.partition(":")
        if kind == "key":
            systools.key_combo(v, down=down, up=not down)  # held for as long as you hold the button
        elif kind == "act" and down:
            if v == "screenshot":
                systools.take_screenshot()
            elif v == "play":
                self.media("play")
            elif v == "suspend":
                self.toggle_suspend()
            elif v == "mute":
                self.discord_voice("mute")
            elif v == "clip":
                self.save_clip()
            elif v == "padmouse":
                self.toggle_padmouse()
            elif v == "fan":
                self.toggle_full_fan()
            else:
                self.do_action(v)

    # -------------------------------------------------------------- motion (eased UI animations)
    def start_motion(self, name):
        if self.cfg["motion"]:
            self.motions[name] = time.perf_counter()
            self.request_draw()

    def motion(self, name, dur=0.28):
        """Eased progress (0 → 1) of a running UI animation; keeps frames coming until it settles."""
        st = self.motions.get(name)
        if st is None:
            return 1.0
        t = (time.perf_counter() - st) / dur
        if t >= 1:
            self.motions.pop(name, None)
            return 1.0
        self.motion_frame("page" if name == "page" else "all")
        return 1 - (1 - t) ** 3  # ease-out cubic: quick start, soft landing

    def motion_frame(self, scope="all"):
        if not self.motion_pending:
            self.motion_pending = True

            def go():
                self.motion_pending = False
                self.request_draw(scope)
            self.root.after(12, go)

    def glide(self, cur, target, speed=20.0, eps=0.6):
        """Move each number of cur toward target (frame-rate independent); returns (new, still_moving)."""
        if cur is None or not self.cfg["motion"]:
            return list(target), False
        dt = min(0.05, max(0.001, time.perf_counter() - self.glide_t))
        a = 1 - math.exp(-dt * speed)
        out = [c_ + (t_ - c_) * a for c_, t_ in zip(cur, target)]
        moving = any(abs(t_ - o) > eps for o, t_ in zip(out, target))
        return (out if moving else list(target)), moving

    # ---- smooth motion: things are drawn once, then moved (moving items is far cheaper than redrawing them)
    def begin_slide(self, name, tag, dx, dy, dur):
        """Start sliding everything tagged `tag` in from (dx, dy). The next draw places it; the ticker moves it."""
        if not self.cfg["motion"]:
            return
        self.slides[name] = {"tag": tag, "dx": dx, "dy": dy, "t0": time.perf_counter(), "dur": dur, "ax": 0.0, "ay": 0.0,
                             "regs": None, "placed": False}

    def slide_offset(self, s_):
        t = (time.perf_counter() - s_["t0"]) / s_["dur"]
        e = 1.0 if t >= 1 else 1 - (1 - t) ** 3
        return (1 - e) * s_["dx"], (1 - e) * s_["dy"], t >= 1

    def place_slide(self, name, regs):
        """Called right after the slid things were (re)drawn at their final spot: put them where the slide is now."""
        s_ = self.slides.get(name)
        if not s_:
            return
        wx, wy, done = self.slide_offset(s_)
        if done:
            self.slides.pop(name, None)
            return
        s_["regs"], s_["ax"], s_["ay"], s_["placed"] = regs, wx, wy, True
        self.shift_layer(s_["tag"], wx, wy, regs)
        self.start_tick()

    def start_tick(self):
        if not self.tick_on:
            self.tick_on = True
            self.tick_t = time.perf_counter()
            self.root.after(8, self.anim_tick)

    def anim_tick(self):
        """One animation frame: move slides, glide the rail highlight and the focus ring. No redraws."""
        self.tick_on = False
        if self.hidden:
            self.slides.clear()
            return
        now = time.perf_counter()
        dt = min(0.05, max(0.001, now - self.tick_t))
        self.tick_t = now
        busy = False
        ended = False
        for name, s_ in list(self.slides.items()):
            if not s_["placed"]:
                busy = True
                continue
            wx, wy, done = self.slide_offset(s_)
            self.shift_layer(s_["tag"], wx - s_["ax"], wy - s_["ay"], s_["regs"])
            s_["ax"], s_["ay"] = wx, wy
            if done:
                self.slides.pop(name, None)
                ended = True
            else:
                busy = True
        a = 1 - math.exp(-dt * 18)
        if self.rail_target is not None and self.rail_ind:
            iy = self.rail_ind[0]
            if abs(self.rail_target - iy) > 0.5:
                ny = iy + (self.rail_target - iy) * a
                if abs(self.rail_target - ny) <= 0.5:
                    ny = self.rail_target
                self.c.move("railind", 0, ny - iy)
                self.rail_ind = [ny]
                busy = True
        if self.bar_target is not None and self.bar_ind:
            bx = self.bar_ind[0]
            if abs(self.bar_target[0] - bx) > 0.5:
                nx = bx + (self.bar_target[0] - bx) * a
                if abs(self.bar_target[0] - nx) <= 0.5:
                    nx = self.bar_target[0]
                self.c.move("barind", nx - bx, 0)
                self.bar_ind = [nx, self.bar_ind[1]]
                busy = True
        if self.ring_target is not None and self.ring_pos is not None and self.ring_pos != self.ring_target:
            b = 1 - math.exp(-dt * 24)
            self.ring_pos = [p_ + (q - p_) * b if abs(q - p_) > 0.6 else q for p_, q in zip(self.ring_pos, self.ring_target)]
            self.paint_ring()
            busy = True
        if ended:
            self.draw_hover()
        if busy:
            self.tick_on = True
            self.root.after(8, self.anim_tick)

    def paint_ring(self):
        self.c.delete("ringfx")
        if not self.focus_visible or self.ring_pos is None:
            return
        k = self.k
        c = self.c
        clip, lt, et = c.clip, c.layer_tag, c.extra_tag
        c.clip, c.layer_tag, c.extra_tag = None, ("page" if self.page else "main"), "ringfx"
        try:
            x0, y0, x1, y1 = self.ring_pos
            self.rr(x0, y0, x1, y1, 16 * k, "", outline=self.t["accent"], width=max(2, 3 * k))
        finally:
            c.clip, c.layer_tag, c.extra_tag = clip, lt, et

    def draw_press(self):
        """The pressed button lights up at once: a tinted overlay and an accent edge."""
        c = self.c
        c.delete("pressfx")
        r = next((r_ for r_ in self.active_regions() if r_["id"] == self.pressed), None) if self.pressed else None
        if not r:
            return
        c.delete("hoverfx")
        T, k = self.t, self.k
        clip, lt, et = c.clip, c.layer_tag, c.extra_tag
        c.clip, c.layer_tag, c.extra_tag = None, r["layer"], "pressfx"
        try:
            self.rr(r["x0"], r["y0"], r["x1"], r["y1"], 14 * k, T["accent"], stipple="gray25")
            self.rr(r["x0"], r["y0"], r["x1"], r["y1"], 14 * k, "", outline=T["accent"], width=max(2, 2 * k))
        finally:
            c.clip, c.layer_tag, c.extra_tag = clip, lt, et

    def draw_hover(self):
        """A soft outline around whatever the mouse is over: one item, no redraw."""
        c = self.c
        c.delete("hoverfx")
        rid = self.hovered
        if not rid or self.slides or self.press:
            return
        r = next((r_ for r_ in self.active_regions() if r_["id"] == rid and r_["kind"] not in ("scroll", "panel")), None)
        if not r:
            return
        T, k = self.t, self.k
        clip, lt, et = c.clip, c.layer_tag, c.extra_tag
        c.clip, c.layer_tag, c.extra_tag = None, r["layer"], "hoverfx"
        try:
            g = 2 * k
            # neutral, not the accent colour: the accent ring is the controller's cursor
            self.rr(r["x0"] - g, r["y0"] - g, r["x1"] + g, r["y1"] + g, 14 * k, "", outline=mix(T["bg"], T["text"], 0.3),
                    width=max(1, 1.5 * k))
        finally:
            c.clip, c.layer_tag, c.extra_tag = clip, lt, et

    def shift_layer(self, tag, dx, dy, regions=None):
        """Slide everything drawn with a tag (and its touch areas) by dx, dy."""
        if not dx and not dy:
            return
        self.c.move(tag, dx, dy)
        for r in (regions if regions is not None else [r for r in self.regions if r["layer"] == tag]):
            r["x0"] += dx
            r["x1"] += dx
            r["y0"] += dy
            r["y1"] += dy

    # -------------------------------------------------------------- controller as mouse & keyboard
    def toggle_padmouse(self, layout=None, quiet=False):
        if not self.pad:
            if not quiet:
                self.show_toast("No controller found")
            return
        if self.padmouse is None:
            self.padmouse = systools.DesktopControls(on_osk=lambda: self.call(self.toggle_keyboard))
        if self.padmouse.on and layout is None:
            self.padmouse.end()
            msg = "Controller is a controller again"
        else:
            lay = layout or self.cfg["padmouse_layout"]
            if self.padmouse.on:
                self.padmouse.end()
            self.padmouse.start(lay, self.cfg["padmouse_sens"] / 100)
            msg = f"Controller as mouse: {systools.PAD_LAYOUTS[lay]['name']} (hold View + Menu to open Vanta)"
        if not quiet:
            self.show_toast(msg)
        self.add_log("TOOL", msg)
        self.buzz()
        self.request_draw()

    # -------------------------------------------------------------- fan, clips
    def toggle_full_fan(self, on=None):
        if not self.device["legion"]:
            self.show_toast("Fan control needs a Legion Go")
            return

        def work():
            cur = systools.get_full_fan()
            want = (not cur) if on is None else on
            ok = systools.set_full_fan(want)
            self.call(lambda: (setattr(self, "fan_full", want if ok else cur),
                               self.show_toast(("Fans at full speed" if want else "Fans back to automatic") if ok else
                                               "Couldn't change the fans (Vanta needs administrator)"),
                               self.request_draw()))
        self.background(work)

    def save_clip(self):
        systools.save_clip()
        self.buzz()
        self.show_toast("Saving a clip (Game Bar must have background recording on)")
        self.add_log("GAME", "Saved a clip")

    # -------------------------------------------------------------- automations
    def fire(self, trigger, detail=None):
        for r in self.cfg["automations"]:
            if r.get("on") and r["trigger"] == trigger:
                self.run_rule(r, detail)

    def run_rule(self, r, detail=None):
        a, v = r["action"], r.get("value")
        label = self.rule_text(r)
        if self.preview_blocks("automations"):
            return
        try:
            if a == "tdp" and self.device["legion"]:
                self.background(lambda: systools.set_tdp(v, self.tdp_max))
            elif a == "hz":
                self.background(lambda: systools.set_display_mode(hz=v))
            elif a == "brightness":
                self.background(lambda: systools.set_brightness(v))
            elif a == "thermal" and self.device["legion"]:
                self.background(lambda: systools.set_thermal_mode({"quiet": 1, "balanced": 2, "performance": 3}[v]))
            elif a == "fan":
                self.toggle_full_fan(v == "on")
            elif a == "padmouse":
                if v == "off":
                    if self.padmouse and self.padmouse.on:
                        self.toggle_padmouse(quiet=True)
                else:
                    self.toggle_padmouse(v, quiet=True)
            elif a == "hdr":
                self.background(lambda: systools.set_hdr(v == "on"))
            elif a == "downloads":
                self.pause_downloads(v == "on")
            elif a == "open":
                g = next((g_ for g_ in self.library if g_["id"] == v), None)
                if g and not self.game:
                    self.play(g)
            elif a == "mute":
                self.discord_voice("mute")
        except Exception as ex:
            self.add_log("AUTO", f"Rule failed: {label} ({ex})")
            return
        self.add_log("AUTO", f"Rule: {label}")
        self.show_toast(f"⚡ {label}")

    def time_rules_tick(self, now):
        lt = time.localtime(now)
        mins = lt.tm_hour * 60 + lt.tm_min
        today = time.strftime("%Y-%m-%d", lt)
        fired = self.__dict__.setdefault("time_fired", {})
        for r in self.cfg["automations"]:
            if not r.get("on") or r["trigger"] != "time":
                continue
            at = r.get("arg", 1380)
            days = r.get("days", "every day")
            if (days == "weekdays" and lt.tm_wday >= 5) or (days == "weekends" and lt.tm_wday < 5):
                continue
            if at <= mins < at + 5 and fired.get(r["id"]) != today:
                fired[r["id"]] = today
                self.run_rule(r)

    def rule_value_text(self, r):
        a, v = r["action"], r.get("value")
        if a == "tdp":
            return f"{v} W"
        if a == "hz":
            return f"{v} Hz"
        if a == "brightness":
            return f"{v}%"
        if a in ("fan", "hdr", "downloads"):
            return "on" if v == "on" else "off"
        if a == "padmouse":
            return "off" if v == "off" else systools.PAD_LAYOUTS.get(v, {}).get("name", v)
        if a == "open":
            g = next((g_ for g_ in self.library if g_["id"] == v), None)
            return g["name"] if g else "pick a game"
        return str(v or "")

    @staticmethod
    def clock_text(mins):
        h, m = divmod(int(mins) % 1440, 60)
        return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"

    def rule_text(self, r):
        when = AUTO_TRIGGERS[r["trigger"]] + (f" {r.get('arg', 20)}%" if r["trigger"] == "batt_low" else "")
        if r["trigger"] == "time":
            when = f"It's {self.clock_text(r.get('arg', 1380))}" + ("" if r.get("days", "every day") == "every day" else f" on {r['days']}")
        do = AUTO_ACTIONS[r["action"]]
        val = self.rule_value_text(r)
        return f"When {when[0].lower() + when[1:]}: {do.lower()}" + (f" → {val}" if val and r["action"] != "mute" else "")

    def rule_values(self, action):
        if action == "tdp":
            return list(range(6, self.tdp_max + 1, 1))
        if action == "hz":
            modes = systools.display_modes() if not self.rule_hz_cache else None
            if modes and modes.get("rates"):
                self.rule_hz_cache = sorted(modes["rates"])
            return self.rule_hz_cache or [60, 144]
        if action == "brightness":
            return list(range(10, 101, 10))
        if action == "thermal":
            return ["quiet", "balanced", "performance"]
        if action in ("fan", "hdr", "downloads"):
            return ["on", "off"]
        if action == "padmouse":
            return list(systools.PAD_LAYOUTS) + ["off"]
        if action == "open":
            return [g["id"] for g in sorted(self.library, key=lambda g: -(g.get("last") or 0))[:40]] or [None]
        return [None]

    def rule_cycle(self, r, field, d=1):
        if field == "trigger":
            opts = list(AUTO_TRIGGERS)
        elif field == "action":
            opts = list(AUTO_ACTIONS)
        elif field == "arg" and r["trigger"] == "time":
            opts = list(range(0, 1440, 30))
        elif field == "days":
            opts = AUTO_DAYS
        elif field == "arg":
            opts = [10, 15, 20, 25, 30, 40, 50]
        else:
            opts = self.rule_values(r["action"])
        cur = r.get(field)
        i = opts.index(cur) if cur in opts else -1
        r[field] = opts[(i + d) % len(opts)]
        if field == "action":
            vals = self.rule_values(r["action"])
            r["value"] = vals[len(vals) // 2] if r["action"] in ("tdp", "brightness") else vals[0]
        if field == "trigger" and r["trigger"] == "batt_low":
            r["arg"] = r.get("arg") if r.get("arg") in (10, 15, 20, 25, 30, 40, 50) else 20
        if field == "trigger" and r["trigger"] == "time":
            r["arg"] = r.get("arg") if isinstance(r.get("arg"), int) and r["arg"] >= 60 else 1380
            r.setdefault("days", "every day")
        self.cfg["automations"] = list(self.cfg["automations"])
        self.request_draw()

    def add_rule(self, tpl=None):
        tpl = tpl or {"trigger": "unplugged", "action": "tdp", "value": 12}
        r = {"id": int(time.time() * 1000) % 10 ** 9, "on": True, **{k: v for k, v in tpl.items() if k != "note"}}
        self.cfg["automations"] = list(self.cfg["automations"]) + [r]
        self.show_toast("Rule added: " + self.rule_text(r))
        self.request_draw()

    def del_rule(self, r):
        self.cfg["automations"] = [x for x in self.cfg["automations"] if x["id"] != r["id"]]
        self.request_draw()

    def toggle_rule(self, r):
        r["on"] = not r.get("on")
        self.cfg["automations"] = list(self.cfg["automations"])
        self.request_draw()

    def cards_automations(self):
        cards = []
        rules = self.cfg["automations"]
        if not rules:
            cards.append({"id": "intro", "title": "MAKE VANTA RUN ITSELF", "buttons": [], "lines": [
                ("Rules change things for you: when something happens (you unplug, a game starts, the controllers come off), "
                 "Vanta does something (wattage, refresh rate, mouse mode, downloads…). Start from an idea below.", "text")]})
        for r in rules:
            on = r.get("on")
            btn = [("WHEN", lambda r_=r: self.rule_cycle(r_, "trigger"), "normal")]
            if r["trigger"] == "batt_low":
                btn.append((f"{r.get('arg', 20)}%", lambda r_=r: self.rule_cycle(r_, "arg"), "normal"))
            elif r["trigger"] == "time":
                btn.append((self.clock_text(r.get("arg", 1380)), lambda r_=r: self.rule_cycle(r_, "arg"), "normal"))
                btn.append((r.get("days", "every day").upper(), lambda r_=r: self.rule_cycle(r_, "days"), "normal"))
            btn += [("DO", lambda r_=r: self.rule_cycle(r_, "action"), "normal")]
            if r["action"] != "mute":
                btn.append((self.rule_value_text(r).upper()[:18], lambda r_=r: self.rule_cycle(r_, "value"), "accent"))
            btn += [("ON" if on else "OFF", lambda r_=r: self.toggle_rule(r_), "accent" if on else "normal"),
                    ("✕", lambda r_=r: self.confirm(f"del{r_['id']}", lambda: self.del_rule(r_), "Tap again to delete this rule"), "normal")]
            cards.append({"id": f"r{r['id']}", "title": ("● " if on else "○ ") + "RULE", "buttons": btn,
                          "lines": [(self.rule_text(r), "text" if on else "muted")]})
        ideas = [t for t in AUTO_TEMPLATES if not any(x["trigger"] == t["trigger"] and x["action"] == t["action"] for x in rules)]
        if ideas:
            cards.append({"id": "ideas", "title": "IDEAS", "lines": [(f"{i + 1}. {t['note']}: " + self.rule_text(t).split(': ', 1)[1], "muted")
                                                                    for i, t in enumerate(ideas[:4])],
                          "buttons": [(f"ADD {i + 1}", lambda t_=t: self.add_rule(t_), "normal") for i, t in enumerate(ideas[:4])]})
        cards.append({"id": "new", "title": "NEW RULE", "lines": [("Add a blank rule, then tap WHEN, DO and the value to change them.", "muted")],
                      "buttons": [("+ ADD A RULE", self.add_rule, "accent")]})
        return cards

    def fetch_automations(self):
        return True

    # -------------------------------------------------------------- downloads / network
    def pause_downloads(self, on):
        def work():
            done = []
            if on:
                if systools.pause_updates(4):
                    done.append("Windows Update")
                if systools.pause_onedrive():
                    done.append("OneDrive")
            else:
                if systools.resume_updates():
                    done.append("Windows Update")
                if systools.resume_onedrive():
                    done.append("OneDrive")

            def fin():
                self.cfg["net_paused"] = on
                msg = (("Paused: " if on else "Resumed: ") + ", ".join(done)) if done else "Nothing to pause"
                self.add_log("TOOL", msg)
                self.show_toast(msg)
                self.request_draw()
            self.call(fin)
        self.background(work)

    def fetch_network(self):
        gw = systools.default_gateway()
        rows = []
        for name, host in systools.NET_TARGETS:
            host = host or gw
            if not host:
                continue
            avg, jit, lost = systools.ping_stats(host, 6)
            rows.append({"name": name, "host": host, "avg": avg, "jit": jit, "lost": lost})
        return {"wifi": systools.wifi_details(), "rows": rows}

    def cards_network(self):
        data, cards = self.info_state("network")
        if cards:
            return cards
        w = data["wifi"]
        lines = []
        if w.get("ssid"):
            sig = w.get("signal")
            lines.append((f"{w['ssid']}  ·  {w.get('band') or '?'}  ·  signal {sig if sig is not None else '?'}%"
                          + (f"  ·  {w['rate']} Mbps" if w.get("rate") else ""), "text"))
            if w.get("band") == "2.4 GHz":
                lines.append(("You're on 2.4 GHz: switch to your router's 5 GHz network for lower lag if it reaches.", "accent"))
            elif sig is not None and sig < 55:
                lines.append(("Weak signal: move closer to the router, or use a USB-C ethernet adapter at home.", "accent"))
        else:
            lines.append(("Not on Wi-Fi (ethernet, or no connection).", "muted"))
        cards = [{"id": "wifi", "title": "WI-FI", "lines": lines, "buttons": []}]
        verdict = []
        for r_ in data["rows"]:
            if r_["avg"] is None:
                verdict.append((f"{r_['name']}: no reply", "muted"))
                continue
            grade = "great" if r_["avg"] < 30 and r_["jit"] < 5 else "good" if r_["avg"] < 60 and r_["jit"] < 12 else "laggy"
            verdict.append((f"{r_['name']}: {r_['avg']:.0f} ms, jitter {r_['jit']:.0f} ms" + (f", {r_['lost']} lost" if r_["lost"] else "")
                            + f"  ·  {grade}", "text" if grade != "laggy" else "accent"))
        cards.append({"id": "ping", "title": "LATENCY", "lines": verdict,
                      "buttons": [("TEST AGAIN", lambda: self.open_info("network", True), "normal")]})
        paused = self.cfg["net_paused"]
        cards.append({"id": "dl", "title": "DOWNLOADS WHILE YOU PLAY", "lines": [
            ("Windows Update and OneDrive are paused." if paused else
             "Pause Windows Update and OneDrive so they don't eat bandwidth during online games (Steam and other launchers: "
             "pause them in the launcher).", "text"),
            ("Tip: an automation can do this whenever a game starts.", "muted")],
            "buttons": [("RESUME" if paused else "PAUSE NOW", lambda: self.pause_downloads(not self.cfg["net_paused"]), "accent"),
                        ("AUTOMATE IT", lambda: (self.add_rule(AUTO_TEMPLATES[4]), self.open_info("automations")), "normal")]})
        return cards

    # -------------------------------------------------------------- Legion button test
    def start_btntest(self):
        if self.btntest and self.btntest.get("probe") and self.btntest["probe"].running:
            return
        probe = systools.HidProbe()
        self.btntest = {"probe": probe, "t0": time.time()}
        phases = [("idle", 4), ("l", 4.5), ("gap", 2), ("r", 4.5), ("end", 1.5)]
        self.btntest["ends"] = {}
        t = time.time()
        for name, secs in phases:
            t += secs
            self.btntest["ends"][name] = t
        self.background(lambda: probe.run(phases))
        self.btntest_tick()

    def btntest_tick(self):
        if self.page == "btntest":
            self.request_draw("page")
        bt = self.btntest
        if bt and bt["probe"].running:
            self.root.after(250, self.btntest_tick)
        elif bt and bt["probe"].result is not None and not bt.get("logged"):
            bt["logged"] = True
            summary = bt["probe"].summary()
            self.add_log("TOOL", "Legion button test: " + summary.replace("\n", " | ")[:900])
            # holding the buttons can open Legion Space or switch apps: come back, and tidy up after it
            self.open_page("btntest") if self.page != "btntest" else None
            self.show()
            t0 = bt["t0"]

            def tidy():
                if time.time() >= self.ls_user_until:
                    wins = systools.legion_space_windows(list_processes(), since=t0 - 1)
                    if wins:
                        systools.close_processes([p_[0] for p_ in wins])
                folder = systools.known_folder("b4bfcc3a-db2c-424c-b029-7fe99a87c641") or os.path.expanduser("~")
                path = os.path.join(folder, "Vanta button test.txt")
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(f"{APP_NAME} {VERSION} · Legion button test · {time.strftime('%Y-%m-%d %H:%M')}\n\n{summary}\n")
                    bt["file"] = path
                except OSError:
                    pass
                self.call(self.request_draw)
            self.background(tidy)

    def use_btntest_map(self):
        bt = self.btntest or {}
        res = bt.get("probe") and bt["probe"].result or {}
        m, g = res.get("map"), res.get("motion")
        if not m and not g:
            return
        if m and not bt.get("builtin"):
            self.cfg["legion_map"] = m
        if g:
            self.cfg["legion_gyro"] = g
        self.stop_legion_buttons()
        self.start_legion_buttons()
        self.show_toast("Saved" + (": motion controls are ready" if g else "") + (". Press a Legion button to try it" if m else ""))
        self.request_draw()

    def xinput_text(self):
        pid = getattr(self.legion, "pid", None)
        if pid in systools.DINPUT_PIDS:
            return "Your controllers are in DirectInput mode, so games and Windows don't see them as an Xbox pad"
        if pid in systools.NEW_FW_PIDS:
            return "They're in Xbox mode now (use this if games stop seeing them)"
        return "For Legion Go controllers on the 2025 firmware"

    def restore_xinput(self):
        if getattr(self.legion, "pid", None) not in systools.NEW_FW_PIDS:
            self.show_toast("Only for Legion Go controllers on the 2025 firmware")
            return

        def work():
            ok, msg = systools.restore_xinput_mode()
            self.call(lambda: (self.add_log("TOOL", "Restore Xbox controller mode: " + msg), self.show_toast(msg),
                               self.request_draw()))
        self.background(work)

    def btntest_page(self):
        self.open_page("btntest")

    def cards_btntest(self):
        bt = self.btntest
        lb = self.legion
        live = []
        if lb:
            live.append((f"Vanta's button reader: {'connected' if lb.connected else 'not connected'}, "
                         f"{lb.reports} reports read" + (", Legion press seen" if lb.seen_legion else ", no Legion press seen yet")
                         + (" (using a learned map)" if lb.bmap else
                            " (2025 firmware layout)" if getattr(lb, "pid", None) in systools.NEW_FW_PIDS else ""), "text"))
        pd = self.pad
        if pd:
            xb, hb = getattr(pd, "last_src", (None, None))
            names = lambda b: " ".join(n for m_, n in PAD_BUTTONS if b and b & m_) or "nothing"
            live.append(("Live: Xbox pad " + (f"#{pd.slot}: {names(xb)}" if xb is not None else "not found") +
                         " · controller report: " + (names(hb) if hb is not None else "none"), "accent"))
            hs = pd.hid_state()
            if hs and self.legion and getattr(self.legion, "last_raw", None):
                live.append(("Raw: " + " ".join(f"{b_:02x}" for b_ in self.legion.last_raw[12:24]), "muted"))
            if self.page == "btntest":
                self.root.after(150, lambda: self.page == "btntest" and self.request_draw("page"))
        svc = {"running": "running (opens Legion Space on a press)", "disabled": "stopped by Vanta", "stopped": "stopped",
               None: "not installed"}.get(self.ls_service, "checking…")
        if self.ls_service in (None, "?") and time.time() - self.ls_service_t > 60:
            self.load_ls_info()
        live.append((f"Lenovo's button service: {svc}", "muted"))
        cards = [{"id": "how", "title": "WHAT THIS DOES", "lines": [
            ("Finds where your controllers report Legion L and R, so Vanta can answer them. Keep the controllers attached "
             "and put the Go down on a table. When asked, press and HOLD Legion L for a few seconds, let go, then HOLD Legion R.",
             "text"),
            ("Legion Space may open or apps may switch while you hold the buttons: that's fine, keep holding. Vanta comes "
             "back with the result when the test ends.", "muted"),
            ("Nothing is sent to the controllers.", "muted")] + live,
            "buttons": ([("START THE TEST", self.start_btntest, "accent")] if not (bt and bt["probe"].running) else []) +
                       ([("RESTORE XBOX MODE", lambda: self.confirm("xinput", self.restore_xinput,
                                                                    "Tap again to switch the controllers back to Xbox mode"), "normal")]
                        if getattr(lb, "pid", None) in systools.DINPUT_PIDS else [])}]
        if bt:
            p_ = bt["probe"]
            if p_.running:
                left = max(0, bt["ends"].get(p_.phase, time.time()) - time.time())
                ask = {"idle": "Put it down and don't touch anything…", "l": "Press and HOLD Legion L (keep holding)",
                       "gap": "Let go", "r": "Press and HOLD Legion R (keep holding)", "end": "Let go",
                       "still": "Pick it up and hold it still, like you're aiming at the screen",
                       "turn": "Slowly turn it to the RIGHT (just right, then stop)", "rest": "Hold still again",
                       "tilt": "Slowly tilt it to aim UP (just up, then stop)"}
                cards.append({"id": "now", "title": f"LISTENING · {left:.0f} s", "lines": [(ask.get(p_.phase, "…"), "accent"),
                              (f"{sum(d['reports'] for d in p_.devices)} reports from {sum(d['opened'] for d in p_.devices)} "
                               f"of {len(p_.devices)} controller streams", "muted")], "buttons": []})
            elif p_.result is not None:
                r = p_.result
                ok = bool(r.get("map"))
                mp = r.get("map") or {}
                builtin = bool(self.legion and getattr(self.legion, "pid", None) in systools.NEW_FW_PIDS and mp.get("rid") == 4
                               and mp.get("l") and mp["l"][:2] == [16, 0x80] and mp.get("r") and mp["r"][:2] == [16, 0x40])
                bt["builtin"] = builtin
                ok = ok or bool(r.get("motion"))
                how = (" (one arrives as a keystroke: Vanta catches it so it doesn't reach other apps)"
                       if mp and (mp.get("key_l") or mp.get("key_r")) else "")
                parts = (["buttons (already read this way)" if builtin else "both buttons" + how] if mp else []) + \
                    (["the motion data"] if r.get("motion") else [])
                lines = [("Found " + " and ".join(parts) + ". Tap USE THIS and Vanta will use it." if ok else
                          "Couldn't find both Legion buttons in what the controllers send to Windows." if p_.devices else
                          "No Legion controllers found (are they attached?).", "accent" if ok else "text")]
                if bt.get("file"):
                    lines.append(("Saved to your Desktop as \"Vanta button test.txt\"", "text"))
                for ln in p_.summary().split("\n"):
                    lines.append((ln, "muted"))
                btns = ([("USE THIS", self.use_btntest_map, "accent")] if ok else []) + \
                    [("COPY DETAILS", lambda: (self.root.clipboard_clear(), self.root.clipboard_append(p_.summary()),
                                               self.show_toast("Copied: paste it to me in the chat")), "normal"),
                     ("TEST AGAIN", self.start_btntest, "normal")]
                cards.append({"id": "res", "title": "RESULT", "lines": lines, "buttons": btns})
        return cards

    # -------------------------------------------------------------- storage
    def fetch_storage(self):
        import shutil
        sizes = dict(self.cfg["sizes"])
        drives = {}
        for g in self.library:
            if g.get("source") in ("Sample",) or str(g.get("id", "")).startswith(("sample:", "rom:")):
                continue
            sz = g.get("size") or sizes.get(g["id"])
            if not sz and g.get("path") and os.path.isdir(g["path"]):
                sz = systools.folder_size(g["path"])
                if sz:
                    sizes[g["id"]] = sz
            if g.get("path"):
                drives.setdefault(os.path.splitdrive(g["path"])[0] or "C:", 0)
        for d in list(drives) or ["C:"]:
            try:
                u = shutil.disk_usage(d + "\\")
                drives[d] = (u.free, u.total)
            except OSError:
                drives.pop(d, None)
        self.call(lambda: self.cfg.__setitem__("sizes", sizes))
        return {"sizes": sizes, "drives": drives}

    def last_played(self, g):
        ses = [s_["start"] for s_ in self.cfg["sessions"] if s_.get("id") == g["id"] or s_.get("name", "").lower() == g["name"].lower()]
        return max([g.get("last") or 0] + ses)

    def cards_storage(self):
        data, cards = self.info_state("storage")
        if cards:
            return cards
        lines = [(f"{d}  {fmt_bytes(free)} free of {fmt_bytes(total)}", "text") for d, (free, total) in data["drives"].items()]
        cards = [{"id": "drives", "title": "SPACE", "lines": lines or [("Couldn't read the drives", "muted")], "buttons": []}]
        now = time.time()
        rows = []
        for g in self.library:
            sz = g.get("size") or data["sizes"].get(g["id"])
            if not sz or sz < 2 * 1024 ** 3:
                continue
            last = self.last_played(g)
            idle = (now - last) / 86400 if last else None
            rows.append((sz * (1 + min(idle if idle is not None else 400, 400) / 60), g, sz, idle))
        rows.sort(key=lambda r_: -r_[0])
        if not rows:
            cards.append({"id": "none", "title": "NOTHING BIG TO CLEAN", "buttons": [],
                          "lines": [("No installed game over 2 GB that Vanta knows the size of.", "muted")]})
        for _, g, sz, idle in rows[:20]:
            when = "never played here" if idle is None else "played today" if idle < 1 else f"last played {int(idle)} days ago"                 if idle < 60 else f"last played {int(idle // 30)} months ago"
            label, target = systools.uninstall_target(g)
            cards.append({"id": "s" + g["id"], "title": g["name"].upper(), "lines": [
                (f"{fmt_bytes(sz)}  ·  {g.get('source', '')}  ·  {when}", "accent" if idle is None or idle > 60 else "text")],
                "buttons": [(label.upper(), lambda t_=target: systools.open_target(t_), "normal")]})
        return cards

    # -------------------------------------------------------------- what should I play?
    def fetch_pick(self):
        return True

    def pick_games(self, minutes):
        now = time.time()
        b = self.batt or {}
        out = []
        for g in self.library:
            if str(g.get("id", "")).startswith("sample:") and not PREVIEW:
                continue
            ses = self.sessions_for(g["id"], g["name"])
            last = self.last_played(g)
            score, why = 0.0, []
            if ses:
                avg = sum(s_["dur"] for s_ in ses[:10]) / min(10, len(ses)) / 60
                fit = 1 - min(1, abs(avg - minutes) / max(minutes, 30))
                score += 2 * fit
                if fit > 0.6:
                    why.append(f"your sessions run about {avg:.0f} min")
            idle = (now - last) / 86400 if last else None
            if idle is not None and 2 < idle < 60:
                score += 1.2
                why.append(f"you haven't played it in {int(idle)} days")
            elif idle is not None and idle <= 2:
                score += 0.6
                why.append("you're in the middle of it")
            elif idle is None:
                score += 0.4
                why.append("you haven't started it yet")
            if b and not b.get("ac"):
                est = systools.battery_estimate(ses, b.get("full_mwh"), b.get("remaining_mwh"))
                if est and est[1]:
                    if est[1] * 60 >= minutes:
                        score += 0.8
                        why.append(f"battery lasts about {fmt_duration(est[1] * 3600)} in it")
                    else:
                        score -= 1.5
            if self.find_preset(g["name"]):
                score += 0.2
            out.append((score, g, why))
        out.sort(key=lambda x: -x[0])
        mood = getattr(self, "pick_genre", None)
        if mood:
            fit = [o for o in out if mood in self.genres_of(o[1])]
            if fit:
                return fit[:4]
        return out[:4]

    def cards_pick(self):
        cards = [{"id": "time", "title": "HOW LONG HAVE YOU GOT?", "lines": [(f"Picking for about {self.pick_time} minutes" +
                                                                          ("" if (self.batt or {}).get("ac") else ", on battery"), "text")],
                  "buttons": [(f"{m} MIN" if m < 120 else "2 H+", lambda m_=m: (setattr(self, "pick_time", m_), self.request_draw()),
                               "accent" if m == self.pick_time else "normal") for m in (20, 45, 60, 120)]}]
        gens = [n_ for n_, _ in self.genre_counts()[:6]]
        mood = getattr(self, "pick_genre", None)
        if gens:
            cards.append({"id": "mood", "title": "IN THE MOOD FOR", "lines": [(mood or "Anything", "text")],
                          "buttons": [("ANYTHING" + (" ✓" if not mood else ""), lambda: (setattr(self, "pick_genre", None), self.request_draw()),
                                       "accent" if not mood else "normal")] +
                                     [(n_.upper()[:14] + (" ✓" if n_ == mood else ""), lambda n__=n_: (setattr(self, "pick_genre", n__), self.request_draw()),
                                       "accent" if n_ == mood else "normal") for n_ in gens]})
        picks = self.pick_games(self.pick_time)
        if mood:
            picks = [p_ for p_ in picks if mood in self.genres_of(p_[1])] or picks
        if not picks:
            cards.append({"id": "empty", "title": "NO GAMES YET", "buttons": [], "lines": [("Vanta needs your library first.", "muted")]})
        for i, (sc, g, why) in enumerate(picks):
            cards.append({"id": "p" + g["id"], "title": ("★ " if i == 0 else "") + g["name"].upper(), "lines": [
                (("Because " + ", ".join(why[:3]) + ".") if why else "A good fit right now.", "text")],
                "buttons": [("PLAY", lambda g_=g: (setattr(self, "page", None), self.play(g_)), "accent" if i == 0 else "normal")]})
        return cards

    # -------------------------------------------------------------- captures gallery
    def fetch_gallery(self):
        return systools.list_captures()

    def thumb(self, path, w, h):
        """A small preview of a screenshot (loaded in the background)."""
        key = (path, int(w), int(h))
        if key in self.thumbs:
            return self.thumbs[key]
        self.thumbs[key] = None

        def work():
            try:
                from PIL import Image, ImageOps
                im = ImageOps.fit(Image.open(path).convert("RGB"), (int(w), int(h)))
            except Exception:
                return
            def done():
                from PIL import ImageTk
                if len(self.thumbs) > 80:
                    self.thumbs.clear()
                self.thumbs[key] = ImageTk.PhotoImage(im, master=self.root)
                self.request_draw(self.scope_for("gallery"))
            self.call(done)
        self.background(work)
        return None

    def draw_gallery(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        data, cards = self.info_state("gallery")
        if cards:
            return self.draw_card_list("gallery", cards, x0, y0, x1, y1)
        bar = 58 * k
        bw = 170 * k
        self.button("g_clip", x0, y0, x0 + bw, y0 + 44 * k, "SAVE A CLIP", self.save_clip, style="accent", size=12 * k)
        self.button("g_shot", x0 + bw + 10 * k, y0, x0 + 2 * bw + 10 * k, y0 + 44 * k, "SCREENSHOT",
                    lambda: (systools.save_screenshot(), self.buzz()), size=12 * k)
        self.button("g_folder", x0 + 2 * bw + 20 * k, y0, x0 + 3 * bw + 20 * k, y0 + 44 * k, "OPEN FOLDER",
                    lambda: systools.open_target(systools.captures_dir()), size=12 * k)
        top = y0 + bar
        if not data:
            self.text((x0 + x1) / 2, (top + y1) / 2, "No captures yet. Map “Save a clip” to a back button in Settings, "
                      "or press Win+Alt+G in a game.", self.font(14 * k), T["muted"], anchor="center", maxw=x1 - x0 - 40 * k)
            return
        cols = 4 if x1 - x0 > 900 * k else 3 if x1 - x0 > 600 * k else 2
        gap = 12 * k
        tw = (x1 - x0 - 12 * k - gap * (cols - 1)) / cols
        th = tw * 9 / 16 + 44 * k
        rows = math.ceil(len(data) / cols)
        off = self.scroll_area("gallery", x0, top, x1, y1, rows * (th + gap))
        self.clip_to(top, y1)
        f = self.font(12 * k, True)
        sf = self.font(11 * k)
        for i, c_ in enumerate(data):
            r_, cn = divmod(i, cols)
            tx0, ty0 = x0 + cn * (tw + gap), top + r_ * (th + gap) - off
            if ty0 + th < top or ty0 > y1:
                continue
            ih = tw * 9 / 16
            self.rr(tx0, ty0, tx0 + tw, ty0 + th, 12 * k, T["panel2"])
            img = self.thumb(c_["path"], tw, ih) if c_["kind"] == "shot" else None
            if img:
                self.c.create_image(tx0, ty0, image=img, anchor="nw")
            else:
                self.rr(tx0, ty0, tx0 + tw, ty0 + ih, 12 * k, mix(T["panel2"], T["accent"], 0.18))
                self.text(tx0 + tw / 2, ty0 + ih / 2, "▶" if c_["kind"] == "clip" else "◻", self.font(30 * k, True), T["accent"], anchor="center")
            self.text(tx0 + 10 * k, ty0 + ih + 12 * k, c_["name"], f, T["text"], maxw=tw - 20 * k)
            self.text(tx0 + 10 * k, ty0 + ih + 28 * k, time.strftime("%b %d, %H:%M", time.localtime(c_["time"])) + "  ·  " + fmt_bytes(c_["size"]),
                      sf, T["muted"], maxw=tw - 20 * k)
            self.region(f"cap{i}", tx0, ty0, tx0 + tw, ty0 + th, tap=lambda p_=c_["path"]: systools.open_target(p_), sid="gallery")
        self.end_clip()
        self.scrollbar("gallery", x1, top, y1 - top)

    # -------------------------------------------------------------- backup & theme codes
    def latest_backup_text(self):
        now = time.time()
        if now - self.backup_seen[0] > 10:
            b = systools.list_backups()
            self.backup_seen = (now, time.strftime("%b %d, %H:%M", time.localtime(b[0][1])) if b else "No backup yet")
        return self.backup_seen[1]

    def fan_state_loading(self):
        """Read the full-fan switch once (WMI, so in the background); True while it's being read."""
        if not self.device["legion"]:
            return False
        if self.fan_full is None and not self.fan_loading:
            self.fan_loading = True
            self.background(lambda: self.call(lambda v=systools.get_full_fan(): (setattr(self, "fan_full", bool(v)),
                                                                              setattr(self, "fan_loading", False), self.request_draw())))
        return self.fan_full is None

    def backup_now(self):
        def work():
            try:
                path = systools.make_backup(dict(self.cfg.data))
            except Exception:
                path = None
            self.backup_seen = (0, "")
            self.call(lambda: (self.show_toast(f"Backed up to Documents\\Vanta backups" if path else "Backup failed"),
                               self.add_log("TOOL", f"Settings backup: {path}" if path else "Settings backup failed")))
        self.background(work)

    def restore_latest(self):
        backups = systools.list_backups()
        if not backups:
            self.show_toast("No backups in Documents\\Vanta backups yet")
            return

        def do():
            try:
                data = systools.read_backup(backups[0][0])
            except Exception:
                self.show_toast("That backup couldn't be read")
                return
            n = 0
            for k_, v in data.items():
                if k_ in Config.DEFAULTS and (type(v) == type(Config.DEFAULTS[k_]) or Config.DEFAULTS[k_] is None):
                    self.cfg[k_] = v
                    n += 1
            self.retheme()
            self.show_toast(f"Restored {n} settings from {time.strftime('%b %d', time.localtime(backups[0][1]))}")
            self.add_log("TOOL", f"Restored settings from {backups[0][0]}")
        self.confirm("restore", do, "Tap again to restore your latest backup (your current settings are replaced)")

    def copy_theme_code(self):
        if self.cfg["custom_theme"]:
            payload = {"custom": json.dumps(self.cfg["custom_theme"], separators=(",", ":"))}
        else:
            payload = {"theme": self.cfg["theme"], "accent": self.cfg["accent"] or ""}
        code = systools.theme_to_code(payload)
        self.root.clipboard_clear()
        self.root.clipboard_append(code)
        self.show_toast("Theme code copied: paste it to a friend")

    def use_theme_code(self):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        d = systools.theme_from_code(text)
        if not d:
            self.show_toast("Copy a VANTA1-… theme code first")
            return
        if "custom" in d:
            try:
                spec = json.loads(d["custom"])
            except ValueError:
                spec = None
            if isinstance(spec, dict) and isinstance(spec.get("colors"), dict):
                self.cfg["custom_theme"] = spec
                self.apply_custom_theme()
                self.show_toast("Theme applied from code")
                return
        if d.get("theme") in THEMES:
            self.cfg["accent"] = d.get("accent") or ""
            self.set_theme(d["theme"])
            self.show_toast(f"Theme applied: {d['theme']}")
            return
        self.show_toast("That code is for a theme this Vanta doesn't have")

    # -------------------------------------------------------------- light footprint
    def light_tick(self):
        """Keep Vanta out of the way: low priority + Windows EcoQoS while a game runs or Vanta is hidden,
        and give image memory back to Windows once it has been hidden for a couple of minutes."""
        now = time.time()
        away = self.hidden or self.root.state() == "iconic"  # in the tray or minimized
        if not away:
            self.hidden_since = None
            if self.stale:
                self.request_draw()
        elif self.hidden_since is None:
            self.hidden_since = now
        aiming = self.pointer is not None and self.cfg["pointer_mode"] == "mouse"  # gyro aim needs full speed
        want = bool((self.game or away) and not aiming and self.cfg["light_footprint"])
        if want != self.eco:
            self.eco = want
            systools.set_self_efficiency(want)
        if self.hidden_since and now - self.hidden_since > 120 and not self.trimmed and self.cfg["light_footprint"]:
            self.trimmed = True
            self.release_memory()
        if not away:
            self.trimmed = False

    def release_memory(self):
        before = systools.self_memory_mb()
        self.covers.clear()
        self.hero_cache.clear() if hasattr(self, "hero_cache") else None
        self._mcache.clear()
        if getattr(self.c, "_crops", None) is not None:
            self.c._crops.clear()
        import gc
        gc.collect()
        systools.trim_self()
        after = systools.self_memory_mb()
        if before and after:
            self.add_log("TOOL", f"Hidden: gave {max(0, before - after):.0f} MB back to Windows ({after:.0f} MB in use)")

    # -------------------------------------------------------------- info pages: stream, deals, retro, updates
    def open_info(self, page, refresh=False):
        self.open_page(page)
        if self.page != page:
            return
        st = getattr(self, "info_" + page, None)
        if st and st.get("status") == "loading" or (st and not refresh and time.time() - st.get("at", 0) < 600):
            return
        setattr(self, "info_" + page, {"status": "loading", "at": time.time()})
        fetch = getattr(self, "fetch_" + page)

        def work():
            try:
                data = fetch()
                res = {"status": "ok", "data": data, "at": time.time()}
            except Exception as ex:
                res = {"status": "error", "error": str(ex)[:120], "at": time.time()}
            self.call(lambda: (setattr(self, "info_" + page, res), self.request_draw()))
        self.background(work)
        self.request_draw()

    def info_state(self, page):
        st = getattr(self, "info_" + page, None) or {"status": "loading"}
        if st["status"] == "loading":
            return None, [{"id": "ld", "title": "ONE MOMENT", "lines": [("Looking that up…", "muted")], "buttons": []}]
        if st["status"] == "error":
            return None, [{"id": "er", "title": "COULDN'T LOAD THIS", "lines": [(st.get("error") or "No connection?", "muted")],
                           "buttons": [("TRY AGAIN", lambda: self.open_info(page, refresh=True), "accent")]}]
        return st["data"], None

    def draw_card_list(self, sid, cards, x0, y0, x1, y1):
        k = self.k
        hs = [self.card_height(cd, x1 - x0 - 12 * k) for cd in cards]
        off = self.scroll_area(sid, x0, y0, x1, y1, sum(hs) + 14 * k * len(cards))
        self.clip_to(y0, y1)
        y = y0 - off
        for cd, h in zip(cards, hs):
            if y + h >= y0 and y <= y1:
                self.draw_card(cd, x0, y, x1 - 12 * k, sid)
            y += h + 14 * k
        self.end_clip()
        self.scrollbar(sid, x1, y0, y1 - y0)

    # stream
    def fetch_stream(self):
        hosts = {h["ip"]: h for h in systools.find_stream_hosts()}
        for ip in self.cfg["stream_hosts"]:
            if ip not in hosts:
                info = systools.stream_host_info(ip)
                hosts[ip] = info or {"name": ip, "ip": ip, "offline": True}
        for ip, h in hosts.items():  # remember each PC's network card while it's on, so it can be woken later
            if not h.get("offline"):
                try:
                    mac = systools.mac_for_ip(ip)
                except Exception:
                    mac = None
                if mac and self.cfg["wol"].get(ip) != mac:
                    self.call(lambda ip_=ip, m_=mac: self.cfg.__setitem__("wol", dict(self.cfg["wol"], **{ip_: m_})))
        return {"hosts": list(hosts.values()), "moonlight": systools.moonlight_path()}

    def cards_stream(self):
        data, cards = self.info_state("stream")
        if cards:
            return cards
        cards = []
        ml = data["moonlight"]
        if not ml:
            cards.append({"id": "ml", "title": "STREAM FROM YOUR GAMING PC", "buttons": [
                ("GET MOONLIGHT", lambda: systools.open_target("https://moonlight-stream.org"), "accent"),
                ("GET SUNSHINE", lambda: systools.open_target("https://github.com/LizardByte/Sunshine"), "normal")],
                "lines": [("Install Sunshine on your gaming PC and Moonlight here, pair them once, and Vanta lists your PCs below "
                           "so you can start streaming with one tap.", "text")]})
        for h in data["hosts"]:
            btn = [] if not ml else [
                ("DESKTOP", lambda ip=h["ip"]: self.start_stream(ip, "Desktop"), "accent"),
                ("STEAM BIG PICTURE", lambda ip=h["ip"]: self.start_stream(ip, "Steam Big Picture"), "normal")]
            if self.cfg["wol"].get(h["ip"]):
                btn.insert(0, ("WAKE", lambda ip=h["ip"]: self.wake_pc(ip), "accent" if h.get("offline") else "normal"))
            cards.append({"id": "h_" + h["ip"], "title": h["name"].upper(), "buttons": btn,
                          "lines": [(h["ip"] + ("  ·  not answering right now" if h.get("offline") else "  ·  ready to stream"),
                                     "muted" if h.get("offline") else "text")]})
        if not data["hosts"]:
            cards.append({"id": "none", "title": "NO PCS FOUND", "buttons": [],
                          "lines": [("No Sunshine host answered on this network. Check that Sunshine is running, or add the PC "
                                     "by its address below.", "muted")]})
        cards.append({"id": "add", "title": "ADD A PC BY ADDRESS", "lines": [
            ("Copy the PC's IP address (like 192.168.1.20), then tap PASTE.", "muted")],
            "buttons": [("PASTE ADDRESS", self.add_stream_host, "normal"), ("SCAN AGAIN", lambda: self.open_info("stream", True), "normal")]})
        gfn = [("GEFORCE NOW", lambda: systools.open_target(systools.GFN_APP if os.path.exists(systools.GFN_APP)
                                                             else "https://play.geforcenow.com"), "normal")]
        cards.append({"id": "cloud", "title": "CLOUD GAMING", "lines": [("Play in the cloud: needs a good Wi-Fi connection.", "muted")],
                      "buttons": [("XBOX CLOUD", lambda: systools.open_target(systools.CLOUD_SERVICES[0][1]), "normal")] + gfn})
        return cards

    def wake_pc(self, ip):
        mac = self.cfg["wol"].get(ip)
        if not mac:
            self.show_toast("Turn that PC on once with Vanta open, so it can learn how to wake it")
            return
        ok = systools.wake_on_lan(mac, ip)
        self.add_log("TOOL", f"Wake-on-LAN sent to {ip} ({mac})" if ok else f"Couldn't send Wake-on-LAN to {ip}")
        self.show_toast("Waking it up: give it 20–30 seconds" if ok else "Couldn't send the wake-up")
        if ok:
            self.root.after(30000, lambda: self.open_info("stream", True) if self.page == "stream" else None)

    def start_stream(self, ip, app):
        if systools.moonlight_stream(ip, app):
            self.show_toast(f"Starting Moonlight: {app}")
            self.add_log("GAME", f"Streaming {app} from {ip}")
        else:
            self.show_toast("Moonlight isn't installed")

    def add_stream_host(self):
        try:
            text = self.root.clipboard_get().strip()
        except tk.TclError:
            text = ""
        if re.fullmatch(r"[A-Za-z0-9.-]{3,64}", text):
            self.cfg["stream_hosts"] = list(dict.fromkeys(list(self.cfg["stream_hosts"]) + [text]))[-8:]
            self.open_info("stream", refresh=True)
        else:
            self.show_toast("Copy the PC's address first")

    # deals
    def fetch_deals(self):
        out = {"epic": systools.epic_free_games(), "steam": None, "steamid": None}
        sid = self.cfg["steam_id"] or systools.steam_user_id()
        if sid:
            out["steamid"] = sid
            try:
                out["steam"] = systools.steam_wishlist_deals(sid)
            except Exception:
                out["steam"] = None
        return out

    def cards_deals(self):
        data, cards = self.info_state("deals")
        if cards:
            return cards
        cards = []
        now_ = [g for g in data["epic"] if g["now"]]
        soon = [g for g in data["epic"] if not g["now"]]
        for g in now_:
            cards.append({"id": "e_" + g["title"], "title": "FREE ON EPIC NOW", "lines": [(g["title"], "text")] +
                          ([(f"Until {g['until'][:10]}", "muted")] if g.get("until") else []),
                          "buttons": [("CLAIM ON EPIC", lambda u=g["url"]: systools.open_target(u), "accent")]})
        if soon:
            cards.append({"id": "esoon", "title": "FREE ON EPIC NEXT", "buttons": [],
                          "lines": [(f"{g['title']}  ·  from {(g.get('from') or '')[:10]}", "text") for g in soon]})
        if data["steam"]:
            lines = [(f"{x['name']}  ·  −{x['pct']}%  ·  {x['price']}" + (f" (was {x['was']})" if x.get("was") else ""), "text")
                     for x in data["steam"][:15]]
            cards.append({"id": "wish", "title": "ON SALE FROM YOUR STEAM WISHLIST", "lines": lines,
                          "buttons": [("OPEN WISHLIST", lambda: systools.open_target("steam://openurl/https://store.steampowered.com/wishlist/"), "normal")]})
        elif data["steamid"]:
            cards.append({"id": "wish", "title": "YOUR STEAM WISHLIST", "buttons": [], "lines": [
                ("Nothing on sale right now, or your wishlist is private (Steam: Edit Profile > Privacy > Game details: Public).", "muted")]})
        else:
            cards.append({"id": "wish", "title": "YOUR STEAM WISHLIST", "buttons": [],
                          "lines": [("Sign in to Steam on this PC and Vanta will show sales on your wishlist.", "muted")]})
        return cards

    def check_deals(self, force=False):
        """Background check (every 6 hours) that toasts newly free Epic games and new wishlist sales."""
        if not self.cfg["deal_alerts"] or (not force and time.time() - self.cfg["deals_last"] < 6 * 3600):
            return
        self.cfg["deals_last"] = time.time()

        def work():
            try:
                data = self.fetch_deals()
            except Exception:
                return
            seen = set(self.cfg["deals_seen"])
            new = [f"Free on Epic: {g['title']}" for g in data["epic"] if g["now"] and "e:" + g["title"] not in seen]
            new += [f"{x['name']} is {x['pct']}% off" for x in (data["steam"] or []) if f"s:{x['appid']}:{x['pct']}" not in seen]
            keys = ["e:" + g["title"] for g in data["epic"] if g["now"]] + [f"s:{x['appid']}:{x['pct']}" for x in (data["steam"] or [])]

            def done():
                self.cfg["deals_seen"] = list(dict.fromkeys(list(self.cfg["deals_seen"]) + keys))[-200:]
                self.info_deals = {"status": "ok", "data": data, "at": time.time()}
                for msg in new[:5]:
                    self.add_log("TOOL", msg)
                if new:
                    self.show_toast(new[0] + (f" (+{len(new) - 1} more in the menu)" if len(new) > 1 else ""))
            self.call(done)
        self.background(work)

    # retro
    def fetch_retro(self):
        if not (self.cfg["ra_user"] and self.cfg["ra_key"]):
            return None
        return systools.ra_summary(self.cfg["ra_user"], self.cfg["ra_key"])

    def cards_retro(self):
        data, cards = self.info_state("retro")
        if cards:
            return cards
        if not data:
            return [{"id": "setup", "title": "CONNECT RETROACHIEVEMENTS", "lines": [
                ("RetroAchievements adds achievements to retro games in emulators like RetroArch, DuckStation and PCSX2.", "text"),
                ("Copy your username, then your web API key (retroachievements.org > Settings) and paste both in "
                 "Settings > Games & library.", "muted")],
                "buttons": [("OPEN SETTINGS", lambda: (self.open_page("settings"), self.pick_settings_cat("games")), "accent"),
                            ("GET A KEY", lambda: systools.open_target("https://retroachievements.org/settings"), "normal")]}]
        cards = [{"id": "me", "title": f"{self.cfg['ra_user'].upper()}", "lines": [
            (f"{data['points']:,} points (hardcore)  ·  {data['softcore']:,} softcore", "accent")],
            "buttons": [("PROFILE", lambda: systools.open_target(data["url"]), "normal")]}]
        for g in data["recent"]:
            pct = g["got"] / g["total"] * 100 if g["total"] else 0
            cards.append({"id": f"g{g['id']}", "title": g["title"].upper(), "lines": [
                (f"{g['console']}  ·  {g['got']} of {g['total']} achievements ({pct:.0f}%)", "text")],
                "buttons": [("OPEN", lambda u=g["url"]: systools.open_target(u), "normal")]})
        return cards

    # updates
    def fetch_updates(self):
        r = systools.update_report()
        self.cfg["updates_last"] = time.time()
        return r

    def cards_updates(self):
        data, cards = self.info_state("updates")
        if cards:
            return cards
        have = data["have"]
        cards = [{"id": "dev", "title": (data["model"] or "THIS PC").upper(), "buttons": [], "lines": [
            (f"BIOS {have.get('bios') or '?'}  ·  machine type {have.get('mtm') or '?'}", "text"),
            (f"{have.get('gpu') or 'Graphics'}: driver {have.get('drv') or '?'}" + (f" ({have['drvdate']})" if have.get("drvdate") else ""),
             "text")]}]
        for it in data["items"]:
            cards.append({"id": it["what"], "title": it["what"].upper(), "lines": [
                (f"You have {it['have'] or '?'}  ·  Lenovo's catalog: {it['latest']} ({it['date']})", "text"),
                ("Update available from Lenovo" if it["newer"] else "Up to date with Lenovo's catalog", "accent" if it["newer"] else "muted")],
                "buttons": [("LENOVO SUPPORT", lambda: systools.open_target(systools.LENOVO_SUPPORT), "accent" if it["newer"] else "normal")]})
        if not data["catalog_ok"]:
            cards.append({"id": "nocat", "title": "LENOVO'S CATALOG", "buttons": [],
                          "lines": [("Couldn't read Lenovo's update catalog for this machine type.", "muted")]})
        cards.append({"id": "amd", "title": "NEWER AMD DRIVERS", "buttons": [
            ("AMD DRIVERS", lambda: systools.open_target(systools.AMD_HANDHELD_DRIVERS), "normal")],
            "lines": [("Lenovo's catalog often lags behind AMD. AMD's own Adrenalin drivers for Ryzen Z1/Z2 handhelds are usually newer: "
                       "AMD Software also offers them under Driver & Software.", "muted")]})
        cards.append({"id": "again", "title": "CHECK AGAIN", "buttons": [("CHECK NOW", lambda: self.open_info("updates", True), "normal")],
                      "lines": [("Vanta only reports an update when Lenovo's catalog is newer than what's installed.", "muted")]})
        return cards

    # -------------------------------------------------------------- detached-controller profile
    def on_attach_change(self):
        """Controllers came off (or went back on): switch to / from the detached profile."""
        att = self.legion.attached if self.legion else None
        if not att:
            return
        off = [side for side, on in att.items() if not on]
        self.add_log("TOOL", "Controllers: " + ("both attached" if not off else " and ".join(off) + " detached"))
        self.fire("detached" if off else "attached")
        if not self.cfg["detach_profile"]:
            return
        if off and self.detach_saved is None:
            self.detach_apply()
        elif not off and self.detach_saved is not None:
            self.detach_restore()

    def detach_apply(self):
        c = self.cfg
        saved = {"ui_scale": c["ui_scale"], "pointer_mode": c["pointer_mode"]}
        modes = systools.display_modes() or {}
        saved["hz"] = modes.get("hz")
        self.detach_saved = saved
        what = []
        if c["detach_scale"]:
            c["ui_scale"] = min(200, c["ui_scale"] + 25)
            what.append("bigger touch targets")
        if c["detach_pointer_off"] and c["pointer_mode"] != "off":
            self.set_pointer_mode("off")
            what.append("motion controls off")
        if c["detach_hz"] and modes.get("rates") and c["detach_hz"] in modes["rates"] and c["detach_hz"] != modes.get("hz"):
            self.background(lambda hz=c["detach_hz"]: systools.set_display_mode(hz=hz))
            what.append(f"{c['detach_hz']} Hz")
        if c["detach_tdp"] and self.device["legion"] and not self.game:
            def work(w=c["detach_tdp"]):
                saved["tdp"] = systools.get_tdp()
                systools.set_tdp(w, self.tdp_max)
            self.background(work)
            what.append(f"{c['detach_tdp']} W")
        self.show_toast("Controllers off: " + (", ".join(what) or "detached profile on"))
        self.add_log("TOOL", "Detached profile on" + (f": {', '.join(what)}" if what else ""))
        self.request_draw()

    def detach_restore(self):
        saved, self.detach_saved = self.detach_saved, None
        c = self.cfg
        c["ui_scale"] = saved["ui_scale"]
        if saved["pointer_mode"] != c["pointer_mode"] and saved["pointer_mode"] != "off":
            self.set_pointer_mode(saved["pointer_mode"])
        if saved.get("hz") and c["detach_hz"]:
            self.background(lambda hz=saved["hz"]: systools.set_display_mode(hz=hz))
        if saved.get("tdp") and not self.game:
            self.background(lambda w=saved["tdp"]: systools.set_tdp(w, self.tdp_max))
        self.show_toast("Controllers back on: everything restored")
        self.add_log("TOOL", "Detached profile off")
        self.request_draw()

    def open_back_for_tune(self):
        key = self.tune_target[0] if self.tune_target else None
        self.page_from = "tune"
        self.page = "buttons"
        self.focus_id = None
        self.back_scope = key or "all"
        self.request_draw()

    def open_back_buttons(self):
        self.page = "buttons"
        self.focus_id = None
        self.back_scope = self.game_key(self.game) if self.game else "all"
        self.request_draw()

    def set_back(self, name, d):
        scope = self.back_scope
        if scope == "all":
            m = self.cfg["back_map"]
        else:
            m = self.cfg["back_map_game"].setdefault(scope, {})
        cur = m.get(name, self.cfg["back_map"].get(name, "none") if scope != "all" else "none")
        i = BACK_ACTIONS.index(cur) if cur in BACK_ACTIONS else 0
        m[name] = BACK_ACTIONS[(i + d) % len(BACK_ACTIONS)]
        self.request_draw()

    def draw_back_buttons(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        df = self.font(13.5 * k)
        y = y0
        if self.game:
            gk = self.game_key(self.game)
            y = self.q_seg("bk_scope", x0, y, x1, [("all", "ALL GAMES"), (gk, self.game["name"].upper()[:28])], self.back_scope,
                           lambda v: (setattr(self, "back_scope", v), self.request_draw()))
        scope = self.back_scope
        own = self.cfg["back_map_game"].get(scope, {}) if scope != "all" else self.cfg["back_map"]
        for name in BACK_ORDER:
            val = own.get(name)
            shown = back_label(val) if val else (back_label(self.cfg["back_map"].get(name)) + " (all games)" if scope != "all" else "Nothing")
            y = self.q_stepper(f"bk_{name}", x0, y, x1, BACK_LABELS[name], shown, lambda d, n=name: self.set_back(n, d),
                               vw=min(300, (x1 - x0) / k * 0.5))
            y += 4 * k
        y += 8 * k
        if scope != "all" and own:
            self.button("bk_reset", x0, y, x0 + 260 * k, y + 52 * k, "USE ALL-GAMES MAPPING",
                        lambda: (self.cfg["back_map_game"].pop(scope, None), self.request_draw()), style="ghost", size=13 * k)
            y += 64 * k
        st, col = self.legion_status()
        self.text(x0, y, f"Controllers: {st}", self.font(13.5 * k, True), col)
        y += 30 * k
        for ln in self.wrap("Keys stay pressed while you hold the button, so Shift or Ctrl work for sprinting or crouching. "
                            "If Legion Space also maps these buttons, clear its mapping or both will act.", df, x1 - x0):
            if y + 24 * k > y1:
                break
            self.text(x0, y, ln, df, T["muted"])
            y += df.metrics("linespace")

    # -------------------------------------------------------------- per-game lights
    def save_game_lights(self, on):
        gk = self.game_key(self.game)
        if not gk:
            return
        if on:
            self.cfg["game_lights"][gk] = {"mode": self.cfg["rgb_mode"] if self.cfg["rgb_mode"] != "keep" else "solid",
                                           "color": self.cfg["rgb_color"], "brightness": self.cfg["rgb_brightness"]}
            self.show_toast(f"These lights come on with {self.game['name']}")
        else:
            self.cfg["game_lights"].pop(gk, None)
            self.apply_rgb(quiet=True)
            self.show_toast("Back to your normal lights")
        self.request_draw()

    # -------------------------------------------------------------- suspend / resume
    def toggle_suspend(self):
        g = self.game
        if not g:
            return
        if self.suspended:
            ok = systools.suspend_process(g["pid"], resume=True)
            if ok:
                self.suspended = None
                self.add_log("GAME", f"{g['name']} resumed")
                wins = [h for h in systools.app_windows(set()) if systools._pid_of(h) == g["pid"]]
                if wins:
                    if self.tray:
                        self.hide()
                    systools.force_foreground(wins[0])
            else:
                self.show_toast("Couldn't resume the game")
        else:
            ok = systools.suspend_process(g["pid"])
            if ok:
                self.suspended = g["pid"]
                self.add_log("GAME", f"{g['name']} suspended")
                self.close_quick(restore=False)
                self.open_hub()
                self.show_toast(f"{g['name']} is paused. Resume it from the top of PLAY")
            else:
                self.show_toast("Couldn't suspend the game (some anti-cheat games block this)")
        self.request_draw()

    def draw_suspended_bar(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        self.surface(x0, y0, x1, y1, 14 * k, mix(T["panel"], T["warn"], 0.18))
        P = 16 * k
        bw = 220 * k
        self.text(x0 + P, (y0 + y1) / 2 - 2 * k, f"{self.game['name']} is suspended", self.font(17 * k, True), T["text"], anchor="sw",
                  maxw=x1 - x0 - bw - 3 * P)
        self.text(x0 + P, (y0 + y1) / 2 + 2 * k, "Frozen where you left it: no CPU or GPU use until you resume", self.font(12.5 * k),
                  T["muted"], anchor="nw", maxw=x1 - x0 - bw - 3 * P)
        self.button("resume_game", x1 - P - bw, y0 + 10 * k, x1 - P, y1 - 10 * k, "RESUME", self.toggle_suspend, style="accent", size=15 * k)

    # -------------------------------------------------------------- battery health history & stats
    def record_battery_health(self):
        b, st = self.batt, self.batt_static
        if self.batt_static is None and self.device:
            self.load_battery_static()
            return
        if not b or not st or not st.get("design") or not b.get("full_mwh"):
            return
        day = time.strftime("%Y-%m-%d")
        hist = list(self.cfg["batt_hist"])
        if hist and hist[-1][0] == day:
            return
        hist.append([day, int(b["full_mwh"]), int(st["design"]), st.get("cycles")])
        self.cfg["batt_hist"] = hist[-400:]

    def play_stats(self):
        ses = self.cfg["sessions"]
        now = time.time()
        today0 = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
        days = []
        for i in range(6, -1, -1):
            d0 = today0 - i * 86400
            hrs = sum(s_["dur"] for s_ in ses if d0 <= s_["start"] < d0 + 86400) / 3600
            days.append((time.strftime("%a", time.localtime(d0)), hrs))
        games = {}
        for s_ in ses:
            g = games.setdefault(s_["name"], {"name": s_["name"], "dur": 0, "n": 0, "fps": [], "last": 0, "batt": []})
            g["dur"] += s_["dur"]
            g["n"] += 1
            g["last"] = max(g["last"], s_["start"])
            if s_.get("fps"):
                g["fps"].append(s_["fps"])
            if s_.get("batt") is not None and s_["dur"] > 600:
                g["batt"].append(s_["batt"] / (s_["dur"] / 3600))
        top = sorted(games.values(), key=lambda g: -g["dur"])
        return {"days": days, "week": sum(h for _, h in days), "total": sum(s_["dur"] for s_ in ses) / 3600,
                "sessions": len(ses), "longest": max((s_["dur"] for s_ in ses), default=0), "top": top}

    def draw_tab_stats(self, x0, y0, x1, y1, land):
        T, k, c = self.t, self.k, self.c
        P = 14 * k
        st = self.play_stats()
        if land:
            lw = (x1 - x0 - P) * 0.42
            a = (x0, y0, x0 + lw, y0 + (y1 - y0) * 0.55)
            b = (x0, a[3] + P, x0 + lw, y1)
            cc = (x0 + lw + P, y0, x1, y0 + (y1 - y0) * 0.6)
            sl = (x0 + lw + P, cc[3] + P, x1, y1)
        else:
            h1 = (y1 - y0) * 0.24
            a = (x0, y0, x1, y0 + h1)
            b = (x0, a[3] + P, x1, a[3] + P + h1 * 0.85)
            cc = (x0, b[3] + P, x1, y1 - h1 * 0.9 - P)
            sl = (x0, cc[3] + P, x1, y1)
        self.draw_sleep_card(*sl)
        # this week
        top = self.card(*a, "THIS WEEK", f"{st['week']:.1f} h played")
        cx0, cx1, cy0, cy1 = a[0] + 18 * k, a[2] - 18 * k, top + 6 * k, a[3] - 40 * k
        mx = max([h for _, h in st["days"]] + [1])
        bw = (cx1 - cx0) / 7
        for i, (lbl, h) in enumerate(st["days"]):
            bx = cx0 + i * bw
            bh = (cy1 - cy0 - 24 * k) * h / mx
            if h > 0:
                self.rr(bx + bw * 0.18, cy1 - bh, bx + bw * 0.82, cy1, 6 * k, T["accent"] if i == 6 else mix(T["accent"], T["panel2"], 0.35))
                self.text(bx + bw / 2, cy1 - bh - 4 * k, f"{h:.1f}", self.font(11.5 * k, True), T["text"], anchor="s")
            else:
                c.create_line(bx + bw * 0.18, cy1, bx + bw * 0.82, cy1, fill=T["line"], width=max(2, 3 * k))
            self.text(bx + bw / 2, cy1 + 10 * k, lbl.upper(), self.font(11.5 * k, True), T["muted"], anchor="n")
        # battery health
        top = self.card(*b, "BATTERY HEALTH", "recorded once a day")
        hist = self.cfg["batt_hist"]
        if hist:
            vals = [min(100.0, f * 100 / max(1, d)) for _, f, d, _cy in hist]
            last = hist[-1]
            self.text(b[0] + 18 * k, top + 4 * k, f"{vals[-1]:.0f}%", self.font(30 * k, True), T["good"] if vals[-1] >= 85 else T["warn"])
            sub = f"{last[1] / 1000:.1f} of {last[2] / 1000:.1f} Wh" + (f" · {last[3]} cycles" if last[3] else "") + \
                f" · since {hist[0][0]}"
            self.text(b[0] + 18 * k, top + 46 * k, sub, self.font(12.5 * k), T["muted"], maxw=b[2] - b[0] - 36 * k)
            if len(vals) >= 2:
                self.chart(b[0] + 18 * k, top + 76 * k, b[2] - 18 * k, b[3] - 18 * k, vals, T["good"], lo=min(vals) - 2, hi=100)
            else:
                self.text(b[0] + 18 * k, top + 80 * k, "The chart fills in as days go by.", self.font(13 * k), T["muted"])
        else:
            self.text(b[0] + 18 * k, top + 10 * k, "Starts recording today." if self.device["legion"] or self.batt else
                      "No battery found.", self.font(14 * k), T["muted"])
        # most played
        top = self.card(*cc, "MOST PLAYED", f"{st['total']:.0f} h in {st['sessions']} sessions")
        rows = st["top"]
        if not rows:
            self.text((cc[0] + cc[2]) / 2, (top + cc[3]) / 2, "Play something from the PLAY tab and your stats show up here.",
                      self.font(14 * k), T["muted"], anchor="center", maxw=cc[2] - cc[0] - 40 * k)
            return
        rh = 64 * k
        off = self.scroll_area("stats", cc[0], top, cc[2], cc[3] - 10 * k, rh * len(rows))
        self.clip_to(top, cc[3] - 10 * k)
        nf, sf = self.font(15.5 * k, True), self.font(12.5 * k)
        best = rows[0]["dur"]
        for i, g in enumerate(rows):
            ry = top + i * rh - off
            if ry + rh < top or ry > cc[3] - 10 * k:
                continue
            rx0, rx1 = cc[0] + 18 * k, cc[2] - 22 * k
            self.text(rx0, ry + 8 * k, f"{i + 1}. {g['name']}", nf, T["text"], maxw=(rx1 - rx0) * 0.6)
            self.text(rx1, ry + 8 * k, f"{g['dur'] / 3600:.1f} h", nf, T["accent"], anchor="ne")
            bits = [f"{g['n']} session{'s' if g['n'] != 1 else ''}", f"last {fmt_ago(g['last'])}"]
            if g["fps"]:
                bits.append(f"{sum(g['fps']) / len(g['fps']):.0f} FPS avg")
            if g["batt"]:
                bits.append(f"{sum(g['batt']) / len(g['batt']):.0f}% battery/h")
            self.text(rx0, ry + 32 * k, " · ".join(bits), sf, T["muted"], maxw=rx1 - rx0)
            self.rr(rx0, ry + rh - 8 * k, rx0 + (rx1 - rx0) * g["dur"] / best, ry + rh - 4 * k, 2 * k, mix(T["accent"], T["panel"], 0.4))
        self.end_clip()
        self.scrollbar("stats", cc[2] - 6 * k, top, cc[3] - 10 * k - top)

    # -------------------------------------------------------------- save backups, moving games, ROM folders
    @property
    def retroarch(self):
        if not hasattr(self, "_ra"):
            self._ra = systools.find_retroarch()
        return self._ra

    def get_ludusavi(self, then=None):
        if self.ludusavi_busy:
            return

        def go():
            self.ludusavi_busy = True

            def work():
                try:
                    tag = systools.download_ludusavi()
                    ok, msg = True, f"Ludusavi {tag} downloaded"
                except Exception as ex:
                    ok, msg = False, f"Couldn't download Ludusavi: {ex}"

                def done():
                    self.ludusavi_busy = False
                    self.add_log("TOOL" if ok else "FAIL", msg)
                    self.show_toast("Save backups ready" if ok else "Download failed, see the log")
                    if ok and then:
                        then()
                    self.request_draw()

                self.call(done)

            self.background(work)
            self.request_draw()

        self.confirm("ludusavi", go, "Tap again to download Ludusavi (free, open source save backup tool)")

    def save_backup(self, g, restore=False):
        if not systools.ludusavi_installed():
            self.get_ludusavi(lambda: self.save_backup(g, restore))
            return
        if self.save_busy:
            return
        if restore and self.game and self.game["name"] == g["name"]:
            self.show_toast("Close the game before restoring its saves")
            return
        self.save_busy = g["id"]

        def work():
            ok, msg, size = systools.ludusavi("restore" if restore else "backup", g["name"])

            def done():
                self.save_busy = None
                what = "Restored" if restore else "Backed up"
                text = f"{what} {g['name']} saves ({fmt_bytes(size)})" if ok else msg
                self.add_log("GAME" if ok else "FAIL", text)
                self.show_toast(text)
                self.request_draw()

            self.call(done)

        self.background(work)
        self.request_draw()

    def move_target(self, g):
        """Another Steam library with the most free space (usually the microSD card). Cached: this runs while drawing."""
        memo = self.__dict__.setdefault("_mt", {})
        hit = memo.get(g["id"])
        if hit and time.time() - hit[0] < 30 and not self.move_busy:
            return hit[1]
        try:
            res = self._move_target(g)
        except OSError:
            res = None
        memo[g["id"]] = (time.time(), res)
        return res

    def _move_target(self, g):
        if not hasattr(self, "_libs") or time.time() - self._libs[0] > 60:
            self._libs = (time.time(), systools.steam_libraries())
        appid = g["id"].split(":", 1)[1]
        loc = getattr(self, "_locs", {}).get(appid)
        if loc is None:
            loc = systools.steam_game_location(appid)
            self._locs = {**getattr(self, "_locs", {}), appid: loc or False}
        if not loc:
            return None
        others = [lib for lib in self._libs[1] if os.path.normcase(lib) != os.path.normcase(loc[0]) and os.path.isdir(lib)]
        if not others:
            return None
        import shutil
        return max(others, key=lambda lib: shutil.disk_usage(lib).free)

    def move_game(self, g, target):
        if self.move_busy:
            return
        if self.game and self.game["name"] == g["name"]:
            self.show_toast("Close the game first")
            return
        if systools.steam_running():
            if self.is_armed("close_steam"):
                os.startfile("steam://exit")
                self.armed = None
                self.show_toast("Closing Steam… tap MOVE again in a moment")
            else:
                self.confirm("close_steam", lambda: None, "Steam must be closed to move games: tap again to close it")
            return
        if not self.is_armed(f"move_{g['id']}"):
            self.confirm(f"move_{g['id']}", lambda: None, f"Tap again to move {g['name']} to {target[:2]}")
            return
        self.armed = None
        appid = g["id"].split(":", 1)[1]
        self.move_busy = (g["id"], 0.0)

        def progress(done, total):
            self.move_busy = (g["id"], done * 100 / max(1, total))
            self.call(self.request_draw)

        def work():
            ok, msg = systools.move_steam_game(appid, target, progress)

            def fin():
                self.move_busy = None
                self._locs = {}
                self._mt = {}
                text = f"Moved {g['name']} to {target[:2]}. Open Steam to play." if ok else msg
                self.add_log("GAME" if ok else "FAIL", text)
                self.show_toast(text)
                self.load_library()

            self.call(fin)

        self.background(work)
        self.request_draw()

    def add_rom_folder(self):
        from tkinter import filedialog
        if not self.retroarch:
            self.show_toast("Install RetroArch first (retroarch.com or Steam)")
            return
        d = filedialog.askdirectory(parent=self.root, title="Pick a folder with ROMs")
        if not d:
            return
        d = os.path.normpath(d)
        if d not in self.cfg["rom_dirs"]:
            self.cfg["rom_dirs"] = self.cfg["rom_dirs"] + [d]
        self.show_toast("Scanning for games…")
        self.load_library()

    # -------------------------------------------------------------- theme editor
    def open_editor(self):
        if not self.cfg["custom_theme"]:
            base = self.theme_name if self.theme_name != MY_THEME else "Midnight"
            t = THEMES[base]
            self.cfg["custom_theme"] = {"base": base, "colors": {k: t[k] for k, _ in EDIT_SLOTS}, "grad": bool(t.get("grad")),
                                        "fx": t.get("fx") if t.get("fx") in EDIT_FX else "none", "outline": bool(t.get("outline"))}
        self.apply_custom_theme()
        self.page = "editor"
        self.focus_id = None
        self.request_draw()

    def apply_custom_theme(self):
        THEMES[MY_THEME] = build_custom_theme(self.cfg["custom_theme"])
        if MY_THEME not in THEME_NAMES:
            THEME_NAMES.append(MY_THEME)
        self.cfg["theme"] = MY_THEME
        self.cfg["accent"] = ""
        self.retheme()

    def edit_color(self, slot, h=None, l=None, s_=None):
        spec = self.cfg["custom_theme"]
        hexc = spec["colors"][slot].lstrip("#")
        r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4))
        hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
        hh = hh if h is None else h
        ll = ll if l is None else l
        ss = ss if s_ is None else s_
        r, g, b = colorsys.hls_to_rgb(hh, ll, ss)
        spec["colors"][slot] = "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
        self.apply_custom_theme()

    def draw_editor(self, x0, y0, x1, y1):
        T, k, c = self.t, self.k, self.c
        spec = self.cfg["custom_theme"]
        land = x1 - x0 > 760 * k
        lx1 = x0 + (x1 - x0) * (0.5 if land else 1) - (12 * k if land else 0)
        y = self.q_seg("ed_slot", x0, y0, lx1, [(sid, lbl.upper()) for sid, lbl in EDIT_SLOTS], self.ed_slot,
                       lambda v: (setattr(self, "ed_slot", v), self.request_draw()))
        cur = spec["colors"][self.ed_slot]
        hexc = cur.lstrip("#")
        hh, ll, ss = colorsys.rgb_to_hls(*(int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4)))
        slot = self.ed_slot
        y = self.q_slider("ed_h", x0, y, lx1, "Color", hh, cur.upper(), lambda f, fin: self.edit_color(slot, h=f), lambda d: self.edit_color(
            slot, h=(hh + d * 0.02) % 1))
        y = self.q_slider("ed_s", x0, y, lx1, "Strength", ss, f"{ss * 100:.0f}%", lambda f, fin: self.edit_color(slot, s_=f),
                          lambda d: self.edit_color(slot, s_=max(0, min(1, ss + d * 0.05))))
        y = self.q_slider("ed_l", x0, y, lx1, "Brightness", ll, f"{ll * 100:.0f}%", lambda f, fin: self.edit_color(slot, l=f),
                          lambda d: self.edit_color(slot, l=max(0, min(1, ll + d * 0.04))))
        sw = ["#0b0f17", "#000000", "#f4f6fa", "#3d8bff", "#00c8ff", "#2ee59d", "#ffb000", "#ff4d5e", "#ff2bd6", "#8a6cff"]
        n = len(sw)
        d_ = min(44 * k, (lx1 - x0 - (n - 1) * 8 * k) / n)
        for i, col in enumerate(sw):
            sx = x0 + i * (d_ + 8 * k)
            c.create_oval(sx, y, sx + d_, y + d_, fill=col, outline=T["line"], width=max(1, k))
            self.region(f"ed_sw{i}", sx, y, sx + d_, y + d_,
                        tap=lambda cc=col: (spec["colors"].__setitem__(slot, cc), self.apply_custom_theme()))
        y += d_ + 16 * k
        rx0, ry = (lx1 + 24 * k, y0) if land else (x0, y)
        bases = [n_ for n_ in THEME_NAMES if n_ != MY_THEME]

        def step_base(d):
            i = bases.index(spec["base"]) if spec["base"] in bases else 0
            nb = bases[(i + d) % len(bases)]
            t = THEMES[nb]
            spec.update(base=nb, colors={k_: t[k_] for k_, _ in EDIT_SLOTS}, grad=bool(t.get("grad")),
                        fx=t.get("fx") if t.get("fx") in EDIT_FX else "none", outline=bool(t.get("outline")))
            self.apply_custom_theme()

        ry = self.q_stepper("ed_base", rx0, ry, x1, "Start from", spec["base"], step_base, vw=170)
        ry = self.q_stepper("ed_fx", rx0, ry, x1, "Effect", spec.get("fx", "none").title(),
                            lambda d: (spec.__setitem__("fx", EDIT_FX[(EDIT_FX.index(spec.get("fx", "none")) + d) % len(EDIT_FX)]),
                                       self.apply_custom_theme()), vw=170)
        ry = self.q_toggle("ed_grad", rx0, ry, x1, "Gradient background", bool(spec.get("grad")),
                           lambda: (spec.__setitem__("grad", not spec.get("grad")), self.apply_custom_theme()))
        ry = self.q_toggle("ed_outline", rx0, ry, x1, "Outlined cards (minimal look)", bool(spec.get("outline")),
                           lambda: (spec.__setitem__("outline", not spec.get("outline")), self.apply_custom_theme()))
        ry += 10 * k
        # preview chips
        self.surface(rx0, ry, x1, ry + 96 * k, 14 * k, T["panel"])
        self.text(rx0 + 16 * k, ry + 18 * k, "Preview", self.font(16 * k, True), T["text"])
        self.text(rx0 + 16 * k, ry + 44 * k, "Muted text looks like this", self.font(12.5 * k), T["muted"])
        self.rr(x1 - 150 * k, ry + 24 * k, x1 - 16 * k, ry + 72 * k, 12 * k, T["accent"])
        self.text(x1 - 83 * k, ry + 48 * k, "BUTTON", self.font(13 * k, True), T["accent_text"], anchor="center")
        ry += 112 * k
        self.button("ed_done", rx0, max(ry, y1 - 54 * k) if land else ry, x1, (max(ry, y1 - 54 * k) if land else ry) + 54 * k,
                    "DONE", lambda: (setattr(self, "page", None), self.show_toast("Saved as My theme"), self.request_draw()),
                    style="accent", size=14 * k)

    # -------------------------------------------------------------- phone remote
    def remote_text(self):
        if not self.cfg["remote_on"]:
            return "Control Vanta from your phone's browser on the same Wi-Fi"
        if not self.remote:
            return "Couldn't start (another app may use the port)"
        return f"On your phone open  http://{systools.lan_ip()}:{self.cfg['remote_port']}  ·  PIN {self.cfg['remote_pin']}"

    def start_remote(self):
        if self.remote:
            return
        if not self.cfg["remote_pin"]:
            self.cfg["remote_pin"] = f"{random.SystemRandom().randint(0, 999999):06d}"
        try:
            self.remote = systools.RemoteServer(self.cfg["remote_port"], self.cfg["remote_pin"], self.remote_state, self.remote_action,
                                                 self.remote_cover, self.remote_shots)
            self.add_log("TOOL", f"Phone remote on: http://{systools.lan_ip()}:{self.cfg['remote_port']}")
        except OSError as ex:
            self.remote = None
            self.add_log("FAIL", f"Phone remote: {ex}")
        self.request_draw()

    def stop_remote(self):
        if self.remote:
            self.remote.stop()
            self.remote = None

    def remote_state(self):  # called on the server thread: read-only snapshot
        p, b, c = self.power, self.batt or {}, self.cfg
        tools = self.tools or {}
        disp = tools.get("display") or {}
        T = self.t
        now = time.time()
        lib = list(self.library or [])
        hub = (self.game or {}).get("hub") or {}
        g = None
        if self.game:
            gg = next((x for x in lib if x["id"] == hub.get("id")), None)
            g = {"name": self.game["name"], "id": gg["id"] if gg else "", "cover": bool(gg and gg.get("cover")),
                 "time": now - self.game["start"]}
        last = next(iter(c["sessions"]), None)
        last_g = next((x for x in lib if last and (x["id"] == last.get("id") or x["name"].lower() == last["name"].lower())), None)
        games = []
        for x in sorted(lib, key=lambda x: self.game_stats(x)[0] or 0, reverse=True)[:120]:
            if str(x["id"]).startswith("sample:") and not PREVIEW:
                continue
            games.append({"id": x["id"], "name": x["name"], "source": x.get("source", ""), "cover": bool(x.get("cover")),
                          "played": self.game_stats(x)[1]})
        draw = abs(b["rate_mw"]) / 1000 if b.get("discharging") and b.get("rate_mw") else None
        return {"app": APP_NAME, "version": VERSION, "device": os.environ.get("COMPUTERNAME", APP_NAME),
                "theme": {k: T[k] for k in ("bg", "panel", "panel2", "text", "muted", "accent", "accent2", "good", "warn", "danger") if k in T},
                "game": g, "last": last["name"] if last and not g else None, "last_id": last_g["id"] if last_g else None,
                "last_cover": bool(last_g and last_g.get("cover")),
                "fps": round(self.fps_stats[0]) if self.fps_stats else None,
                "cpu": round(self.cpu) if self.cpu is not None else None, "gpu": round(self.gpu) if self.gpu is not None else None,
                "cpu_hist": [round(v, 3) for v in list(self.cpu_hist)[-60:]],
                "bat": p["pct"] if p and p.get("pct", 255) <= 100 else None, "ac": bool(b.get("ac")), "charging": bool(b.get("charging")),
                "draw": draw, "left": b["remaining_mwh"] / abs(b["rate_mw"]) * 3600 if draw else None,
                "legion": bool(self.device["legion"]), "tdp_set": c["tdp"], "tdp_now": tools.get("tdp"), "tdp_max": self.tdp_max,
                "auto_tdp": c["auto_tdp"], "auto_tdp_target": c["auto_tdp_target"], "profile": c["profile"],
                "goal": c["batt_goal"], "goal_opts": self.BGOAL_OPTS, "goal_status": self.bgoal_status() if c["batt_goal"] else "",
                "bright": self.brightness, "hz": disp.get("hz"), "rates": (disp.get("rates") or [])[-4:],
                "np": self.np or "", "focus": bool(self.focus), "overlay": bool(c["overlay"]), "suspended": bool(self.suspended),
                "today": self.played_today(now), "week": sum(x["dur"] for x in c["sessions"] if x["start"] > now - 7 * 86400),
                "streak": self.streaks()[0], "sleep_label": self.sleep_label(), "events": list(self.events),
                "pad_ok": bool(c["phone_input"]) and not c["guest"],
                "sleep_sel": -1 if c["sleep_after_game"] else (getattr(self, "sleep_mins", 0) if self.sleep_left() is not None else 0),
                "brk": c["break_every"], "brk_opts": self.BREAK_OPTS, "limit": c["daily_limit"], "lim_opts": self.LIMIT_OPTS,
                "games": games}

    def remote_shots(self, i=None):  # server thread: newest screenshots (PNG/JPG only), listed at most every 15 s
        now = time.time()
        cache = getattr(self, "_shots", None)
        if not cache or now - cache[0] > 15:
            try:
                lst = [c_ for c_ in systools.list_captures(200) if c_["kind"] == "shot" and
                       os.path.splitext(c_["path"])[1].lower() in (".png", ".jpg", ".jpeg")][:40]
            except Exception:
                lst = []
            cache = self._shots = (now, lst)
        if i is None:
            return [{"i": n, "name": c_["name"], "time": c_["time"]} for n, c_ in enumerate(cache[1])]
        return cache[1][i]["path"] if 0 <= i < len(cache[1]) else None

    def remote_cover(self, gid):  # server thread: only covers of games in the library
        g = next((x for x in list(self.library or []) if x["id"] == gid), None)
        return g.get("cover") if g else None

    def remote_action(self, a, v=None):  # server thread: hand the work to the UI thread
        def num(lo, hi):
            try:
                n = int(float(v))
            except (TypeError, ValueError):
                return None
            return n if lo <= n <= hi else None
        if a == "profile" and v in ("saver", "balanced", "max"):
            self.call(lambda: self.apply_profile(v))
            return {"saver": "Battery saver", "balanced": "Balanced", "max": "Max performance"}[v]
        if a == "tdp_set" and self.device["legion"]:
            w = num(5, self.tdp_max)
            if w is None:
                return "TDP out of range"

            def go():
                self.cfg["tdp"] = w
                self.cfg["tdp_ack"] = True
                self.apply_tdp()
            self.call(go)
            return f"TDP {w} W"
        if a == "bright":
            n = num(0, 100)
            if n is None:
                return "Brightness out of range"
            self.call(lambda: self.set_brightness(n))
            return f"Brightness {n}%"
        if a == "hz":
            n = num(24, 500)
            if n is None or n not in (((self.tools or {}).get("display") or {}).get("rates") or []):
                return "That refresh rate isn't available"
            self.call(lambda: self.set_refresh(n))
            return f"{n} Hz"
        if a == "bgoal":
            n = num(0, 1000)
            if n not in self.BGOAL_OPTS:
                return "Unknown goal"
            self.call(lambda: self.set_bgoal(n))
            return "Battery goal off" if not n else f"Battery goal {self.bgoal_label(n)}"
        if a in ("break", "limit"):
            n = num(0, 1000)
            if n not in (self.BREAK_OPTS if a == "break" else self.LIMIT_OPTS):
                return "Unknown option"
            self.call(lambda: self.set_reminder("break_every" if a == "break" else "daily_limit", n))
            return "Saved"
        if a in ("mouse", "click", "scroll", "type", "key"):
            if not self.cfg["phone_input"] or self.cfg["guest"]:
                return "Touchpad and keyboard are off (Settings › Phone touchpad & keyboard)"
            try:
                if a == "mouse":
                    dx, dy = (max(-400, min(400, int(float(x)))) for x in str(v).split(",")[:2])
                    systools.mouse_move(dx, dy)
                    return ""
                if a == "click":
                    systools.mouse_click(right=v == "right")
                    return ""
                if a == "scroll":
                    systools.mouse_wheel(max(-1200, min(1200, int(float(v)))))
                    return ""
                if a == "type":
                    systools.type_text(str(v or "")[:500])
                    return "Typed"
                keys = {"enter": 0x0D, "back": 0x08, "esc": 0x1B, "tab": 0x09, "win": 0x5B, "space": 0x20,
                        "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27}
                if v in keys:
                    systools.tap_key(keys[v])
                    return ""
            except (TypeError, ValueError):
                pass
            return "Unknown input"
        if a == "sleep":
            n = num(-1, 1000)
            if n not in self.SLEEP_OPTS + [-1, 30, 60, 90]:
                return "Unknown option"
            self.call(lambda: self.set_sleep(n))
            return "Sleep timer off" if not n else "Sleeps after the game" if n == -1 else f"Sleeping in {n} min"
        if a == "launch":
            g = next((x for x in list(self.library or []) if x["id"] == v), None)
            if not g:
                return "Game not found"
            if self.game:
                return f"{self.game['name']} is still running"
            self.call(lambda: self.play(g))
            if self.cfg["guest"] and not self.guest_allows(g):
                return "Not on the guest shelf"
            return f"Starting {g['name']}"
        acts = {
            "profile_saver": (lambda: self.apply_profile("saver"), "Battery saver"),
            "profile_balanced": (lambda: self.apply_profile("balanced"), "Balanced"),
            "profile_max": (lambda: self.apply_profile("max"), "Max performance"),
            "tdp_up": (lambda: self.step_tdp(1), "TDP +1 W, tap APPLY"), "tdp_down": (lambda: self.step_tdp(-1), "TDP −1 W, tap APPLY"),
            "tdp_apply": (lambda: (self.cfg.__setitem__("tdp_ack", True), self.apply_tdp()), "Applying TDP"),
            "auto_tdp": (self.toggle_auto_tdp, "Auto TDP " + ("off" if self.cfg["auto_tdp"] else "on")),
            "focus": (self.focus_toggle, "Focus mode " + ("off" if self.focus else "on")),
            "overlay": (self.toggle_overlay, "Stats overlay " + ("off" if self.cfg["overlay"] else "on")),
            "boost": (lambda: self.run("boost"), "Game Boost"), "quick": (self.toggle_quick, "Quick settings"),
            "hub": (self.open_hub, "Opening the hub"),
            "prev": (lambda: self.media("prev"), "Previous"), "play": (lambda: self.media("play"), "Play / pause"),
            "next": (lambda: self.media("next"), "Next"),
            "vol_up": (lambda: systools.volume_key("up", 2), "Volume up"), "vol_down": (lambda: systools.volume_key("down", 2), "Volume down"),
            "mute": (lambda: systools.volume_key("mute"), "Mute"),
            "screenshot": (systools.take_screenshot, "Screenshot taken"),
            "record": (self.toggle_recording, "Recording " + ("stopped" if getattr(self, "recording", False) else "started")),
            "suspend": (self.toggle_suspend, "Suspend / resume"), "discord_mute": (lambda: self.discord_voice("mute"), "Discord mute"),
        }
        if a not in acts or (a == "auto_tdp" and not self.device["legion"]):
            return "Unknown action"
        fn, msg = acts[a]
        self.call(fn)
        return msg

    # -------------------------------------------------------------- settings sync
    SYNC_KEYS = ("theme", "accent", "custom_theme", "favorites", "lists", "game_tune", "game_profiles", "back_map", "back_map_game",
                 "game_lights", "rgb_mode", "rgb_color", "rgb_brightness", "legion_l", "legion_r", "legion_l_hold", "legion_r_hold",
                 "discord_app_id", "discord_webhook", "discord_recaps", "sgdb_key", "steam_key", "auto_tdp_target", "pointer_sens",
                 "pointer_invert_x", "pointer_invert_y", "pointer_axis", "wallpaper_dim", "ui_sounds", "haptics", "frametime_graph")

    def sync_tick(self, force=False):
        self.sync_t = time.time()
        folder = systools.sync_folder()
        if not folder:
            self.sync_status = "OneDrive isn't set up on this PC"
            return
        me = f"{os.environ.get('COMPUTERNAME', 'PC')} · {'Preview' if PREVIEW else 'Vanta'}"
        path = os.path.join(folder, "settings.json")
        c = self.cfg

        def work():
            remote = None
            try:
                with open(path, encoding="utf-8") as f:
                    remote = json.load(f)
            except (OSError, ValueError):
                pass
            applied = []
            if remote and remote.get("from") != me and remote.get("updated", 0) > c["sync_last"]:
                applied = [k for k, v in remote.get("data", {}).items() if k in self.SYNC_KEYS and c[k] != v]

                def apply():
                    for k_ in applied:
                        c[k_] = remote["data"][k_]
                    c["sync_last"] = remote["updated"]
                    if c["custom_theme"]:
                        THEMES[MY_THEME] = build_custom_theme(c["custom_theme"])
                        if MY_THEME not in THEME_NAMES:
                            THEME_NAMES.append(MY_THEME)
                    if applied:
                        self.retheme()
                        self.add_log("TOOL", f"Sync: {len(applied)} setting(s) from {remote.get('from')}")
                self.call(apply)
                time.sleep(0.3)
            data = {k: c[k] for k in self.SYNC_KEYS}
            h = json.dumps(data, sort_keys=True)
            wrote = False
            if force or h != self.sync_hash:
                try:
                    os.makedirs(folder, exist_ok=True)
                    now = time.time()
                    with open(path + ".part", "w", encoding="utf-8") as f:
                        json.dump({"from": me, "updated": now, "data": data}, f)
                    os.replace(path + ".part", path)
                    self.sync_hash = h
                    c["sync_last"] = now
                    wrote = True
                except OSError as ex:
                    msg = f"Couldn't write to OneDrive: {ex}"[:80]
                    self.call(lambda: setattr(self, "sync_status", msg))
                    return
            st = f"Synced {time.strftime('%H:%M')}" + (f" · got {len(applied)} from {remote.get('from')}" if applied else "") + \
                (" · sent" if wrote else "")
            self.call(lambda: (setattr(self, "sync_status", st), force and self.show_toast(st), self.request_draw()))

        self.background(work)

    # -------------------------------------------------------------- quiet while gaming
    def quiet_on(self, g):
        def work():
            notif = systools.notifications_enabled()
            user_paused = systools.updates_paused()
            if notif:
                systools.set_notifications(False)
            paused = False if user_paused else systools.pause_updates(12)
            state = {"notif": notif, "paused": paused}

            def done():
                self.cfg["quiet_pending"] = state
                parts = ", ".join(filter(None, ["notifications off" if notif else "", "Windows Update paused" if paused else ""]))
                self.add_log("GAME", "Quiet: " + (parts or "already quiet"))
            self.call(done)
        self.background(work)

    def quiet_off(self, wait=False):
        st = self.cfg["quiet_pending"]
        if not st:
            return
        self.cfg["quiet_pending"] = None

        def work():
            if st.get("notif"):
                systools.set_notifications(True)
            if st.get("paused"):
                systools.resume_updates()
        if wait:
            work()
        else:
            self.background(work)
            self.add_log("GAME", "Quiet off: notifications and updates are back")

    # -------------------------------------------------------------- search, lists, covers, achievements
    def search_library(self):
        self.set_tab("play")

        def typed(kid, label):
            if kid == "bksp":
                self.lib_query = self.lib_query[:-1]
            elif kid == "space":
                self.lib_query += " "
            elif kid not in ("enter",):
                self.lib_query += label
            self.set_off("lib", 0)
            view = self.lib_games()
            if view and self.lib_sel not in {g["id"] for g in view}:
                self.lib_sel = view[0]["id"]
            self.request_draw()
        if self.osk:
            self.close_keyboard()
        self.toggle_keyboard(target=typed)

    def open_lists(self, g):
        self.lists_game = g
        self.page = "lists"
        self.focus_id = None
        self.request_draw()

    def toggle_in_list(self, name, gid):
        ids = list(self.cfg["lists"].get(name, []))
        ids.remove(gid) if gid in ids else ids.append(gid)
        self.cfg["lists"][name] = ids
        self.request_draw()

    def new_list(self):
        self._new_name = ""

        def typed(kid, label):
            if kid == "bksp":
                self._new_name = self._new_name[:-1]
            elif kid == "space":
                self._new_name += " "
            elif kid == "enter":
                n = self._new_name.strip()[:30]
                if n:
                    self.cfg["lists"][n] = [self.lists_game["id"]] if self.lists_game else []
                    self.show_toast(f"Made the list {n}")
                self._new_name = None
            else:
                self._new_name += label
            self.request_draw()
        self.toggle_keyboard(target=typed)

    def draw_lists(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        g = self.lists_game
        y = y0
        if g:
            self.text(x0, y, f"Lists for {g['name']}", self.font(17 * k, True), T["text"], maxw=x1 - x0)
            y += 40 * k
        typing = getattr(self, "_new_name", None)
        if typing is not None:
            self.text(x0, y, f"New list: {typing}▌", self.font(17 * k, True), T["accent"], maxw=x1 - x0)
            y += 40 * k
        for name in sorted(self.cfg["lists"]):
            ids = self.cfg["lists"][name]
            on = bool(g) and g["id"] in ids
            y = self.q_toggle(f"lst_{name}", x0, y, x1, name, on, (lambda n=name: self.toggle_in_list(n, g["id"])) if g else None,
                              sub=f"{len(ids)} game{'s' if len(ids) != 1 else ''}")
        y += 10 * k
        hw = (x1 - x0 - 10 * k) / 2
        self.button("lst_new", x0, y, x0 + hw, y + 54 * k, "+ NEW LIST", self.new_list, style="accent", size=13.5 * k)
        lf = self.cfg["lib_filter"]
        if lf.startswith("list:") and lf[5:] in self.cfg["lists"]:
            nm = lf[5:]
            armed = self.is_armed("lst_del")
            self.button("lst_del", x0 + hw + 10 * k, y, x1, y + 54 * k, "TAP AGAIN" if armed else f"DELETE “{nm[:14]}”",
                        lambda: self.confirm("lst_del", lambda: (self.cfg["lists"].pop(nm, None), self.cfg.__setitem__("lib_filter", "all"),
                                                                 self.request_draw()), f"Tap again to delete the list {nm}"),
                        style="danger" if armed else "ghost", size=13 * k)

    def art_appid(self, g):
        """Steam appid whose art fits this game: its own for Steam games, otherwise found by name (cached)."""
        if g["source"] == "Steam":
            return g["id"].split(":", 1)[1]
        cached = self.cfg["art_ids"].get(g["id"])
        if cached is not None:
            return cached or None
        try:
            appid = systools.steam_appid_for(g["name"])
        except Exception:
            return None  # offline: try again next time
        self.call(lambda: self.cfg["art_ids"].__setitem__(g["id"], str(appid) if appid else ""))
        return str(appid) if appid else None

    def fetch_covers(self):
        key = self.cfg["sgdb_key"]
        if self.sgdb_started or not self.library or not (self.cfg["art_fetch"] or key):
            return
        self.sgdb_started = True
        todo = [g for g in self.library if not g.get("cover") and not str(g["id"]).startswith("rom:") and
                (PREVIEW or not str(g["id"]).startswith("sample:"))][:200]
        if not todo:
            return

        def work():
            got = 0
            for g in todo:
                path = None
                if key:
                    try:
                        path = systools.sgdb_cover(key, g["id"], g["name"])
                    except Exception:
                        path = None
                if not path and self.cfg["art_fetch"] and g["source"] == "Epic":
                    try:
                        path = systools.epic_cover(g.get("epic_item"), g["name"])
                    except Exception:
                        path = None
                if not path and self.cfg["art_fetch"]:
                    try:
                        appid = self.art_appid(g)
                        path = systools.steam_art(appid, "cover") if appid else None
                    except Exception:
                        path = None
                    time.sleep(0.25)  # be gentle with Steam's store
                if not path and self.cfg["art_fetch"] and g["source"] == "GOG":
                    try:
                        path = systools.gog_cover(g["id"].split(":", 1)[1])
                    except Exception:
                        path = None
                if not path and self.cfg["art_fetch"] and g["source"] not in ("Emulator", "Sample"):
                    try:
                        path = systools.pcgw_cover(g["name"])  # any store: Xbox, EA, Ubisoft, Battle.net, Amazon…
                    except Exception:
                        path = None
                    time.sleep(0.3)
                if path:
                    got += 1
                    self.call(lambda gg=g, pp=path: (gg.__setitem__("cover", pp), self.request_draw()))
            if got:
                self.call(lambda: self.add_log("TOOL", f"Game art: {got} cover(s) downloaded"))
        self.background(work)

    def hero(self, g, w, h):
        """Wide backdrop art for the selected game (downloaded once, then cached)."""
        if not self.cfg["art_fetch"] or str(g["id"]).startswith("rom:") or (str(g["id"]).startswith("sample:") and not PREVIEW):
            return None
        if g.get("hero") is None:
            g["hero"] = False  # asked once per session

            def work():
                try:
                    appid = self.art_appid(g)
                    path = systools.steam_art(appid, "hero") if appid else None
                except Exception:
                    path = None
                if path:
                    self.call(lambda: (g.__setitem__("hero", path), self.request_draw()))
            self.background(work)
            return None
        if not g["hero"]:
            return None
        key = ("hero:" + g["id"], int(w), int(h), bool(self.t.get("premium")))
        if key in self.covers:
            self.covers.move_to_end(key)
            return self.covers[key]
        if key not in self.cover_pending:
            self.cover_pending.add(key)
            self.cover_q.put((key, g["hero"]))
        return None

    def achievements_for(self, g):
        if g["source"] != "Steam" or not self.cfg["steam_key"]:
            return None
        appid = g["id"].split(":", 1)[1]
        hit = self.ach.get(appid)
        if hit and (hit[0] == "busy" or time.time() - hit[0] < 3600):
            return hit[1] if hit[0] != "busy" else None
        self.ach[appid] = ("busy", None)
        key = self.cfg["steam_key"]
        sid = self.cfg["steam_id"]

        def work():
            nonlocal sid
            try:
                sid = sid or systools.steam_user_id()
                res = systools.steam_achievements(key, sid, appid) if sid else None
            except Exception:
                res = None
            self.call(lambda: (sid and self.cfg.__setitem__("steam_id", sid), self.ach.__setitem__(appid, (time.time(), res)),
                               self.request_draw()))
        self.background(work)
        return None

    def clear_shaders(self, appid, name):
        if not self.is_armed(f"sh_{appid}"):
            self.confirm(f"sh_{appid}", lambda: None, f"Tap again to clear {name}'s shader cache (it rebuilds as you play)")
            return
        self.armed = None

        def work():
            freed = systools.clear_shader_cache(appid)
            self.call(lambda: (self.shader_sizes.__setitem__(appid, 0), self.show_toast(f"Cleared {fmt_bytes(freed)} of shaders"),
                               self.add_log("CLEAN", f"{name}: cleared {fmt_bytes(freed)} of shader cache"), self.request_draw()))
        self.background(work)

    # -------------------------------------------------------------- find my best TDP
    def start_bench(self):
        g = self.game
        if not g or not self.device["legion"]:
            return
        if not systools.presentmon_installed():
            self.show_toast("This needs the FPS counter: setting it up first")
            self.get_presentmon()
            return
        if not self.fps:
            try:
                self.fps = systools.FpsReader(g["pid"])
            except Exception as ex:
                self.show_toast(f"FPS counter didn't start: {ex}"[:80])
                return
        hi = self.tdp_max
        steps = sorted({w for w in (8, 11, 15, 20, 25, hi) if 5 <= w <= hi})
        self.bench = {"key": self.game_key(g), "name": g["name"], "steps": steps, "i": 0, "phase": "settle", "t": time.time(),
                      "samples": [], "results": [], "start_w": (self.tools or {}).get("tdp") or self.cfg["tdp"],
                      "auto": self.cfg["auto_tdp"]}
        self.cfg["auto_tdp"] = False
        self.bench_set(steps[0])
        self.add_log("TOOL", f"Finding the best TDP for {g['name']}: {', '.join(map(str, steps))} W")
        self.show_toast(f"Keep playing normally: testing {len(steps)} power levels (about {len(steps) * 28 // 60 + 1} min)")
        self.root.after(1000, self.bench_tick)
        self.request_draw()

    def bench_set(self, w):
        self.background(lambda: systools.set_tdp(w, self.tdp_max))

    def bench_tick(self):
        b = self.bench
        if not b:
            return
        if not self.game or self.game_key(self.game) != b["key"]:
            return self.stop_bench(reason="the game closed")
        now = time.time()
        if b["phase"] == "settle":
            if now - b["t"] >= 8:
                b["phase"], b["t"], b["samples"] = "measure", now, []
        else:
            if self.fps_stats and self.fps_stats[0] > 0 and not self.suspended:
                bat = self.batt
                watts = abs(bat["rate_mw"]) / 1000 if bat and bat.get("discharging") and bat.get("rate_mw") else None
                b["samples"].append((self.fps_stats[0], self.fps_stats[1] or self.fps_stats[0], watts))
            if now - b["t"] >= 20:
                sm = b["samples"]
                if sm:
                    ws = [x[2] for x in sm if x[2]]
                    b["results"].append({"w": b["steps"][b["i"]], "fps": sum(x[0] for x in sm) / len(sm),
                                         "low": sum(x[1] for x in sm) / len(sm), "watts": sum(ws) / len(ws) if ws else None})
                b["i"] += 1
                if b["i"] >= len(b["steps"]):
                    return self.finish_bench()
                self.bench_set(b["steps"][b["i"]])
                b["phase"], b["t"] = "settle", now
        self.request_draw()
        self.root.after(1000, self.bench_tick)

    def bench_pick(self, results):
        if not results:
            return None
        best_fps = max(r["fps"] for r in results)
        good = [r for r in results if r["fps"] >= 0.95 * best_fps]
        return min(good, key=lambda r: r["w"])

    def finish_bench(self):
        b, self.bench = self.bench, None
        self.cfg["auto_tdp"] = b["auto"]
        self.bench_set(b["start_w"])
        res = b["results"]
        self.cfg["bench_results"][b["key"]] = {"name": b["name"], "when": time.time(), "results": res}
        pick = self.bench_pick(res)
        if pick:
            self.add_log("TOOL", f"Best TDP for {b['name']}: {pick['w']} W ({pick['fps']:.0f} FPS)")
            self.show_toast(f"Best TDP for {b['name']}: {pick['w']} W. See the results in Vanta")
        self.bench_view = b["key"]
        self.page = "bench"
        self.request_draw()

    def stop_bench(self, reason=None):
        b, self.bench = self.bench, None
        if not b:
            return
        self.cfg["auto_tdp"] = b["auto"]
        self.bench_set(b["start_w"])
        self.show_toast("Stopped the TDP test" + (f": {reason}" if reason else ""))
        self.request_draw()

    def draw_bench(self, x0, y0, x1, y1):
        T, k, c = self.t, self.k, self.c
        key = getattr(self, "bench_view", None) or (self.game_key(self.game) if self.game else None)
        data = self.cfg["bench_results"].get(key) if key else None
        df = self.font(14 * k)
        if not data or not data["results"]:
            self.text((x0 + x1) / 2, (y0 + y1) / 2, "Start a game, open quick settings (Legion R) and tap FIND MY BEST TDP.",
                      df, T["muted"], anchor="center", maxw=x1 - x0)
            return
        res = data["results"]
        pick = self.bench_pick(res)
        top = max(r["fps"] for r in res)
        self.text(x0, y0, data["name"], self.font(20 * k, True), T["text"])
        y = y0 + 40 * k
        hi_r = max(res, key=lambda r: r["w"])
        if pick and hi_r is not pick:
            pw = pick["watts"] or pick["w"]
            hw = hi_r["watts"] or hi_r["w"]
            saving = (1 - pw / hw) * 100 if hw else 0
            msg = (f"{pick['w']} W gives {pick['fps'] / hi_r['fps'] * 100:.0f}% of the frame rate of {hi_r['w']} W "
                   f"while using about {saving:.0f}% less power.")
        else:
            msg = f"{pick['w']} W was the best balance." if pick else ""
        for ln in self.wrap(msg, df, x1 - x0):
            self.text(x0, y, ln, df, T["muted"])
            y += df.metrics("linespace")
        y += 14 * k
        ch1 = y1 - 80 * k
        n = len(res)
        bw = (x1 - x0) / n
        for i, r in enumerate(res):
            bx = x0 + i * bw
            bh = (ch1 - y - 40 * k) * r["fps"] / top
            col = T["accent"] if r is pick else mix(T["accent"], T["panel2"], 0.55)
            self.rr(bx + bw * 0.16, ch1 - bh, bx + bw * 0.84, ch1, 8 * k, col)
            self.text(bx + bw / 2, ch1 - bh - 6 * k, f"{r['fps']:.0f}", self.font(15 * k, True), T["text"], anchor="s")
            sub = f"{r['w']} W" + (f" · {r['watts']:.1f} W real" if r["watts"] else "")
            self.text(bx + bw / 2, ch1 + 8 * k, sub, self.font(12.5 * k, True), T["accent"] if r is pick else T["muted"], anchor="n")
        if pick:
            gk = key
            cur = (self.cfg["game_tune"].get(gk) or {}).get("tdp")
            label = f"USING {pick['w']} W FOR THIS GAME" if cur == pick["w"] else f"USE {pick['w']} W FOR {data['name'].upper()[:22]}"
            self.button("bench_use", x0, y1 - 54 * k, x0 + (x1 - x0) * 0.6, y1, label,
                        lambda: self.use_bench(gk, pick["w"], data["name"]), style="accent", size=13.5 * k)

    def use_bench(self, key, w, name):
        t = dict(self.cfg["game_tune"].get(key) or {})
        t["tdp"] = w
        self.cfg["game_tune"][key] = t
        self.show_toast(f"{name} now starts at {w} W")
        self.request_draw()

    # -------------------------------------------------------------- CPU limit, top-up, power menu, sleep drain
    def cpu_label(self, v):
        return "Keep" if not v else "No boost" if v == 99 else "Full" if v >= 100 else f"{v}%"

    def set_cpu_max_now(self, v):
        def work():
            ok = systools.set_cpu_max(v)
            self.call(lambda: (ok and setattr(self, "cpu_max_now", v),
                               self.show_toast(f"CPU {self.cpu_label(v).lower()}" if ok else "Windows didn't take the CPU limit"),
                               self.request_draw()))
        self.background(work)

    def topup(self):
        def work():
            ok = systools.set_charge_limit(False)

            def done():
                if ok:
                    self.cfg["topup"] = True
                    self.charge_limit = False
                    self.show_toast("Charging to 100% once. The 80% limit comes back after")
                    self.add_log("TOOL", "Top-up: charging to 100% once")
                else:
                    self.show_toast("The firmware didn't accept it")
                self.request_draw()

            self.call(done)

        self.background(work)

    def check_topup(self):
        if not self.cfg["topup"] or not self.power:
            return
        p = self.power
        full = p.get("pct", 0) >= 100
        if full or not p.get("ac"):
            def work():
                ok = systools.set_charge_limit(True)
                self.call(lambda: (ok and (self.cfg.__setitem__("topup", False), setattr(self, "charge_limit", True),
                                           self.add_log("TOOL", "Top-up done: back to stopping at 80%"))))
            if full or time.time() - getattr(self, "unplug_t", time.time()) > 60:
                self.cfg["topup"] = False
                self.background(work)
            elif not p.get("ac") and not hasattr(self, "unplug_t"):
                self.unplug_t = time.time()

    def power_action(self, what):
        self.close_quick(restore=False)
        if what == "sleep":
            self.root.after(400, systools.sleep_now)
        elif what == "restart":
            systools.restart_now()
        else:
            systools.shutdown_now()

    def track_sleep(self, now):
        """A long gap between samples means the PC slept: note how much battery it lost meanwhile."""
        p = self.power
        last, self.last_sample = self.last_sample, (now, p["pct"] if p and p.get("pct", 255) <= 100 else None,
                                                    bool(p and p.get("ac")))
        if last and now - last[0] >= 120 and systools.ADLX.ready:
            # after sleep AMD's settings objects can go stale: start the library over quietly
            self.background(systools.ADLX.restart)
        if not last or now - last[0] < 120 or last[1] is None or last[2]:
            return
        fresh = power_status()  # read again: self.power is still from before the sleep
        pct_now = fresh["pct"] if fresh else None
        if pct_now is None or pct_now > 100 or fresh.get("ac"):
            return
        entry = {"start": last[0], "end": now, "from": last[1], "to": pct_now, "woke": None}
        self.cfg["sleep_log"] = (list(self.cfg["sleep_log"]) + [entry])[-60:]
        hrs = (now - last[0]) / 3600
        self.add_log("BATT", f"Slept {fmt_duration(now - last[0])}, lost {max(0, last[1] - pct_now)}%" +
                     (f" ({max(0, last[1] - pct_now) / hrs:.1f}%/h)" if hrs > 0.2 else ""))

        def work():
            w = systools.last_wake()
            self.call(lambda: entry.__setitem__("woke", w))
        self.background(work)

    def draw_sleep_card(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        top = self.card(x0, y0, x1, y1, "SLEEP DRAIN", "battery lost while asleep")
        log = [e for e in self.cfg["sleep_log"] if e["end"] - e["start"] > 600][-30:]
        P = 18 * k
        if not log:
            self.text(x0 + P, top + 6 * k, "Put the Legion Go to sleep on battery and Vanta shows here how much it drained.",
                      self.font(13.5 * k), T["muted"], maxw=x1 - x0 - 2 * P)
            return
        rates = [max(0, e["from"] - e["to"]) / ((e["end"] - e["start"]) / 3600) for e in log]
        avg = sum(rates) / len(rates)
        col = T["good"] if avg < 1 else T["warn"] if avg < 2.5 else T["danger"]
        self.text(x0 + P, top + 2 * k, f"{avg:.1f}% per hour", self.font(24 * k, True), col)
        self.text(x0 + P, top + 38 * k, "average while asleep" + (" · normal is under 1%" if avg >= 1 else " · that's good"),
                  self.font(12.5 * k), T["muted"])
        y = top + 66 * k
        sf = self.font(12.5 * k)
        for e in reversed(log[-4:]):
            if y + 22 * k > y1 - 10 * k:
                break
            when = time.strftime("%a %H:%M", time.localtime(e["start"]))
            line = f"{when} · {fmt_duration(e['end'] - e['start'])} · lost {max(0, e['from'] - e['to'])}%" + \
                (f" · woke by {e['woke']}" if e.get("woke") else "")
            self.text(x0 + P, y, line, sf, T["text"], maxw=x1 - x0 - 2 * P)
            y += 24 * k

    # -------------------------------------------------------------- Wii pointer / gyro mouse
    def pointing(self):
        return bool(self.pointer) and self.cfg["pointer_mode"] == "vanta"

    def set_pointer_mode(self, mode):
        if mode != "off":
            # motion controls were removed in 8.4.9: the gyro commands they need can switch 2025-firmware
            # controllers into another mode, where Windows no longer sees them as a gamepad
            mode = "off"
        old = self.cfg["pointer_mode"]
        self.cfg["pointer_mode"] = mode
        if mode == "off":
            if self.pointer and self.legion:
                side = self.cfg["pointer_side"]
                self.legion.on_gyro = None
                self.background(lambda: self.legion and self.legion.write(systools.gyro_packets(side, False)))
            self.pointer = None
            self.pointer_sent = False
            if old != "off":
                self.show_toast("Motion pointer off")
        else:
            if not self.legion or not self.legion.connected:
                self.cfg["pointer_mode"] = "off"
                self.show_toast("Attach the controllers to use motion controls")
                self.request_draw()
                return
            if not self.pointer:
                self.pointer = Pointer(self)
                self.pointer_sent = False  # ui_loop switches the gyro on
            self.pointer.refresh_settings()
            self.pointer.recalibrate()
            self.show_toast("Hold still a moment… then point at the screen. A clicks" if mode == "vanta" else
                            "Gyro mouse on" + (": hold LT and tilt to aim" if self.cfg["gyro_hold"] else ": tilt to aim"))
            if mode == "vanta":
                self.root.after(16, self.pointer_tick)
        self.add_log("TOOL", f"Motion pointer: {POINTER_MODES.get(mode, mode)}")
        self.request_draw()

    def pointer_tick(self):
        p = self.pointer
        if not p or self.cfg["pointer_mode"] != "vanta":
            return
        dx, dy = p.take()
        if not self.hidden:
            W, H = self.c.winfo_width(), self.c.winfo_height()
            if p.x is None:
                p.x, p.y = W / 2, H / 2
            p.x = max(0, min(W, p.x + dx))
            p.y = max(0, min(H, p.y + dy))
            if dx or dy:
                p.trail = (p.trail + [(p.x, p.y)])[-6:]
                hit = self.hit(p.x, p.y)
                fid = hit["id"] if hit and hit.get("focus", True) else None
                if fid and fid != self.focus_id:
                    self.focus_id = fid
                    self.focus_visible = True
                    self.sound("move")
                    self.request_draw()
                self.draw_pointer()
            elif p.trail:
                p.trail = p.trail[1:]
                self.draw_pointer()
        self.root.after(16, self.pointer_tick)

    def draw_pointer(self):
        p = self.pointer
        c = self.c
        c.delete("pointer")
        if not p or p.x is None or self.cfg["pointer_mode"] != "vanta" or self.hidden:
            return
        T, k = self.t, self.k
        for i, (tx, ty) in enumerate(p.trail[:-1]):
            r = (4 + i * 1.6) * k
            c.create_oval(tx - r, ty - r, tx + r, ty + r, fill=mix(T["bg"], T["accent"], 0.25 + i * 0.1), outline="", tags="pointer")
        r = 19 * k
        c.create_oval(p.x - r * 1.7, p.y - r * 1.7, p.x + r * 1.7, p.y + r * 1.7, outline=mix(T["bg"], T["accent"], 0.45),
                      width=max(2, 3 * k), tags="pointer")
        c.create_oval(p.x - r, p.y - r, p.x + r, p.y + r, fill="#ffffff", outline=T["accent"], width=max(3, 4 * k), tags="pointer")
        c.create_oval(p.x - r * 0.35, p.y - r * 0.35, p.x + r * 0.35, p.y + r * 0.35, fill=T["accent"], outline="", tags="pointer")
        c.tag_raise("pointer")

    def pointer_click(self):
        p = self.pointer
        if not p or p.x is None:
            return
        import types as _t
        e = _t.SimpleNamespace(x=int(p.x), y=int(p.y), delta=0)
        self.on_press(e)
        self.on_release(e)
        if self.cfg["rumble"] and self.pad_on:
            self.pad.rumble(strength=0.25, ms=60)

    # -------------------------------------------------------------- keyboard, wallpaper, updates
    def toggle_keyboard(self, target=None):
        if self.osk:
            self.close_keyboard()
            return
        try:
            self.osk = Keyboard(self, target)
        except Exception as ex:
            self.osk = None
            self.add_log("FAIL", f"Keyboard: {ex}")

    def close_keyboard(self):
        if self.osk:
            self.osk.destroy()
            self.osk = None
            self.sound("back")

    def pick_wallpaper(self):
        self._pick_wallpaper()

    def _pick_wallpaper(self):
        from tkinter import filedialog
        f = filedialog.askopenfilename(parent=self.root, title="Pick a wallpaper",
                                       filetypes=[("Pictures", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")])
        if f:
            self.cfg["wallpaper"] = os.path.normpath(f)
            self.wall_cache = None
            self.request_draw()

    def wallpaper_image(self, W, H):
        key = (self.cfg["wallpaper"], W, H, self.cfg["wallpaper_dim"], self.t["bg"])
        if self.wall_cache and self.wall_cache[0] == key:
            return self.wall_cache[1]
        try:
            from PIL import Image, ImageTk, ImageOps
            im = Image.open(self.cfg["wallpaper"]).convert("RGB")
            im = ImageOps.fit(im, (max(1, W), max(1, H)), Image.LANCZOS)
            bg = Image.new("RGB", im.size, self.t["bg"])
            im = Image.blend(im, bg, self.cfg["wallpaper_dim"] / 100)
            tkimg = ImageTk.PhotoImage(im)
        except Exception as ex:
            self.add_log("FAIL", f"Wallpaper: {ex}")
            self.cfg["wallpaper"] = ""
            return None
        self.wall_cache = (key, tkimg)
        return tkimg

    def update_text(self):
        u = self.update_info
        if self.update_busy:
            return "Checking…" if not (u and u.get("installing")) else "Downloading the update…"
        if not self.cfg["update_repo"]:
            return f"You're on {VERSION}. Add an update source first"
        if not u:
            return f"You're on {VERSION}"
        if u.get("error"):
            return u["error"]
        if u.get("newer"):
            return f"{u['tag']} is available: tap to install" if u.get("url") else f"{u['tag']} is out, but has no {self.exe_asset()} attached"
        return f"Up to date ({VERSION})"

    def exe_asset(self):
        return "Vanta-Preview.exe" if PREVIEW else "Vanta.exe"

    def check_updates(self, quiet=False):
        repo = self.cfg["update_repo"]
        if not repo:
            if not quiet:
                self.show_toast("Add an update source first")
            return
        if self.update_busy:
            return
        self.update_busy = True

        def work():
            try:
                newer, tag, url, notes = systools.check_update(repo, VERSION, self.exe_asset())
                info = {"newer": newer, "tag": tag, "url": url, "notes": notes}
            except Exception as ex:
                info = {"error": f"Couldn't check: {ex}"[:90]}

            def done():
                self.update_busy = False
                self.update_info = info
                if info.get("newer") and info.get("url"):
                    self.show_toast(f"Vanta {info['tag']} is available: Settings → Updates")
                    self.add_log("TOOL", f"Update available: {info['tag']}")
                elif not quiet:
                    self.show_toast(self.update_text())
                self.request_draw()

            self.call(done)

        self.background(work)
        self.request_draw()

    def install_update(self):
        u = self.update_info or {}
        if not FROZEN:
            self.show_toast("Updates install into the built exe only")
            return
        if not u.get("url") or self.update_busy:
            return
        if not self.is_armed("update"):
            self.confirm("update", lambda: None, f"Tap again to install {u['tag']} (Vanta restarts)")
            return
        self.armed = None
        self.update_busy = True
        u["installing"] = True

        def work():
            try:
                systools.install_update(u["url"], sys.executable)
                self.call(lambda: (self.add_log("TOOL", f"Installing {u['tag']}…"), self.quit()))
            except Exception as ex:
                err = f"Update failed: {ex}"[:90]
                self.call(lambda: (setattr(self, "update_busy", False), self.update_info.update(error=err),
                                   self.show_toast("Update failed, see Settings"), self.request_draw()))

        self.background(work)
        self.request_draw()

    # -------------------------------------------------------------- media, radios, network
    def media(self, what):
        systools.media_key(what)
        self.buzz()
        self.np_time = time.time() - 2.5  # re-read the track name shortly

    def load_radios(self):
        def work():
            r = systools.get_radios()
            self.call(lambda: (setattr(self, "radios", r), self.request_draw()))
        self.background(work)

    def toggle_radio(self, kind):
        if kind in self.radio_busy or self.radios is None:
            return
        want = not self.radios.get(kind)
        self.radio_busy.add(kind)

        def work():
            ok = systools.set_radio(kind, want)
            r = systools.get_radios()

            def fin():
                self.radio_busy.discard(kind)
                self.radios = r or self.radios
                name = "Wi-Fi" if kind == "wifi" else "Bluetooth"
                self.show_toast(f"{name} {'on' if want else 'off'}" if ok else f"Windows didn't allow changing {name}")
                self.request_draw()

            self.call(fin)

        self.background(work)
        self.request_draw()

    def check_network(self):
        if self.net_busy:
            return
        self.net_busy = True

        def work():
            ms, lost = systools.ping("1.1.1.1", 5)
            w = systools.wifi_info()

            def fin():
                self.net_busy = False
                self.net = {"ms": ms, "lost": lost, **w}
                self.add_log("TOOL", "Network: " + ("no internet" if ms is None else f"{ms:.0f} ms, {lost} lost") +
                             (f", Wi-Fi {w['signal']}%" if w.get("signal") is not None else ""))
                self.request_draw()

            self.call(fin)

        self.background(work)
        self.request_draw()

    def toggle_hdr(self):
        systools.toggle_hdr()
        self.show_toast("HDR switched (Win+Alt+B)")
        self.buzz()

    # -------------------------------------------------------------- preview build
    def preview_skip(self, what):
        self.add_log("TOOL", f"Preview: skipped {what.replace('_', ' ')}")
        if time.time() - self.preview_note > 2.5:
            self.preview_note = time.time()
            self.show_toast("Preview: this PC wasn't changed")

    # -------------------------------------------------------------- Discord
    def start_discord(self):
        if not self.discord:
            self.discord = systools.DiscordPresence()
        self.discord.start(self.cfg["discord_app_id"])
        self.presence_tick(once=True)

    def stop_discord(self):
        if self.discord:
            self.discord.set(None)
            self.discord.stop()
            self.discord = None

    def presence_activity(self):
        g = self.game
        where = "on a Legion Go" if self.device["legion"] else "on " + self.device["name"]
        if g:
            bits = [where]
            if self.device["legion"] and (self.tools or {}).get("tdp"):
                bits.append(f"{self.tools['tdp']} W")
            if self.fps_stats and self.fps_stats[0] > 0:
                bits.append(f"~{int(round(self.fps_stats[0] / 5) * 5)} FPS")
            return {"details": g["name"][:120], "state": " · ".join(bits)[:120], "timestamps": {"start": int(g["start"])}}
        if self.cfg["discord_idle"]:
            return {"details": "Picking a game", "state": where[:120], "timestamps": {"start": int(self.app_start)}}
        return None

    def presence_tick(self, once=False):
        if self.cfg["discord_presence"] and self.cfg["discord_app_id"]:
            if not self.discord:
                self.start_discord()
                return
            self.discord.set(self.presence_activity())
        if not once:
            self.root.after(15000, self.presence_tick)

    def discord_status(self):
        T = self.t
        if not self.cfg["discord_presence"]:
            return "Off", T["muted"]
        if not self.cfg["discord_app_id"]:
            return "Needs your Application ID", T["warn"]
        d = self.discord
        if not d:
            return "Starting…", T["muted"]
        if d.connected and not d.error:
            return ("Showing: " + (self.game["name"] if self.game else "Picking a game")) if self.presence_activity() else \
                "Connected, nothing to show right now", T["good"]
        if d.error:
            return d.error, T["warn"] if d.error == "Discord isn't running" else T["danger"]
        return "Connecting…", T["muted"]

    def open_discord(self):
        self.page = "discord"
        self.focus_id = None
        self.ls_time = 0
        self.load_ls_info()
        self.request_draw()

    def paste_setting(self, key):
        try:
            text = self.root.clipboard_get().strip()
        except tk.TclError:
            text = ""
        if key == "discord_app_id":
            m = re.search(r"\d{17,20}", text)
            if not m:
                self.show_toast("Copy the Application ID first (a long number)")
                return
            self.cfg[key] = m.group(0)
            self.show_toast("Application ID saved")
            if self.cfg["discord_presence"]:
                self.start_discord()
        else:
            if not systools.valid_webhook(text):
                self.show_toast("Copy the webhook URL in Discord first")
                return
            self.cfg[key] = text
            self.show_toast("Webhook saved. Tap TEST to check it")
        self.request_draw()

    def webhook_post(self, payload, file_path=None, done_msg=None, busy_attr="hook_busy"):
        if getattr(self, busy_attr):
            return
        setattr(self, busy_attr, True)
        url = self.cfg["discord_webhook"]

        def work():
            ok, msg = systools.discord_webhook(url, payload, file_path)

            def fin():
                setattr(self, busy_attr, False)
                self.show_toast(done_msg if ok and done_msg else msg)
                self.add_log("TOOL" if ok else "FAIL", "Discord: " + (done_msg or msg if ok else msg))
                self.request_draw()

            self.call(fin)

        self.background(work)
        self.request_draw()

    def test_webhook(self):
        self.webhook_post({"content": f"{APP_NAME} is connected. Game recaps and screenshots from "
                                      f"{'my Legion Go' if self.device['legion'] else 'my handheld'} will show up here."},
                          done_msg="Sent a test message to your channel")

    def post_recap(self, g, dur):
        fields = [{"name": "Played", "value": fmt_duration(dur), "inline": True}]
        if g.get("fps_n"):
            fields.append({"name": "Average FPS", "value": f"{g['fps_sum'] / g['fps_n']:.0f}", "inline": True})
        p = self.power
        if g.get("batt0") is not None and p and p.get("pct", 255) <= 100:
            fields.append({"name": "Battery", "value": f"{g['batt0']}% → {p['pct']}%", "inline": True})
        fields.append({"name": "Peak RAM", "value": f"{g['peak'] * 100:.0f}%", "inline": True})
        if self.device["legion"] and (self.tools or {}).get("tdp"):
            fields.append({"name": "TDP", "value": f"{self.tools['tdp']} W", "inline": True})
        accent = int(self.t["accent"].lstrip("#"), 16)
        embed = {"title": g["name"][:250], "description": f"Session on {'a Legion Go' if self.device['legion'] else self.device['name']}",
                 "color": accent, "fields": fields, "footer": {"text": APP_NAME},
                 "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        self.webhook_post({"embeds": [embed]}, done_msg=f"Posted your {g['name']} recap to Discord")

    def share_screenshot(self):
        shot = systools.latest_screenshot()
        if not shot:
            self.show_toast("No screenshots yet: take one first")
            return
        path, t = shot
        game = self.game["name"] if self.game else None
        text = (f"{game}, " if game else "") + ("on my Legion Go" if self.device["legion"] else "")
        self.webhook_post({"content": text.strip(", ") or None}, path, done_msg="Screenshot shared to Discord", busy_attr="share_busy")

    def quick_screenshot(self):
        self.close_quick()
        self.root.after(450, lambda: (systools.take_screenshot(), self.buzz()))

    def discord_voice(self, what):
        systools.send_keys(0x11, 0x10, 0x4D if what == "mute" else 0x44)  # Discord's global Ctrl+Shift+M / Ctrl+Shift+D
        self.show_toast("Discord: mic mute toggled" if what == "mute" else "Discord: deafen toggled")
        self.buzz()

    def trim_discord(self):
        disc = (self.ls_info or {}).get("discord") or []
        if not disc:
            return

        def work():
            freed = 0
            for pid, _, _ in disc:
                ok, f = trim_process(pid)
                freed += f if ok else 0
            self.call(lambda: (self.show_toast(f"Trimmed Discord: {fmt_bytes(freed)} back"), self.add_log("RAM", f"Trimmed Discord, {fmt_bytes(freed)}"),
                               setattr(self, "ls_time", 0), self.load_ls_info()))

        self.background(work)

    def draw_discord(self, x0, y0, x1, y1):
        T, k, c = self.t, self.k, self.c
        land = x1 - x0 > 700 * k
        gap = 28 * k
        cw = (x1 - x0 - gap) / 2 if land else x1 - x0
        df, mf = self.font(13 * k), self.font(13 * k, True)
        bh = 52 * k

        def para(x, y, w, text, color=None):
            for ln in self.wrap(text, df, w):
                self.text(x, y, ln, df, color or T["muted"])
                y += df.metrics("linespace")
            return y

        # ---- Rich Presence
        ax0, ax1 = x0, x0 + cw
        y = self.q_label(ax0, y0, "RICH PRESENCE")
        y = self.q_toggle("set_discord_presence", ax0, y, ax1, "Show what I'm playing", self.cfg["discord_presence"],
                          lambda: self.adjust("discord_presence", 1), sub="Game, time played and FPS on your profile")
        y = self.q_toggle("set_discord_idle", ax0, y, ax1, "Also while I'm in the hub", self.cfg["discord_idle"],
                          lambda: self.adjust("discord_idle", 1))
        aid = self.cfg["discord_app_id"]
        self.text(ax0, y + 14 * k, "Application ID", mf, T["text"])
        self.text(ax1, y + 14 * k, aid or "not added", mf, T["text"] if aid else T["warn"], anchor="ne")
        y += 44 * k
        hw = (cw - 10 * k) / 2
        self.button("dc_paste_id", ax0, y, ax0 + hw, y + bh, "PASTE ID", lambda: self.paste_setting("discord_app_id"), size=13 * k)
        self.button("dc_portal", ax0 + hw + 10 * k, y, ax1, y + bh, "GET AN ID",
                    lambda: os.startfile("https://discord.com/developers/applications"), size=13 * k)
        y += bh + 12 * k
        st, col = self.discord_status()
        self.text(ax0, y, st, mf, col, maxw=cw)
        y += 30 * k
        ya = para(ax0, y, cw, "One-time setup: at discord.com/developers, create an application and name it what you want people "
                              "to see, like \"Legion Go\". Copy its Application ID, then tap PASTE ID.")

        # ---- webhook
        bx0, bx1 = (x0 + cw + gap, x1) if land else (x0, x1)
        y = self.q_label(bx0, y0 if land else ya + 18 * k, "SHARE TO A CHANNEL")
        hook = self.cfg["discord_webhook"]
        ok = systools.valid_webhook(hook)
        self.text(bx0, y + 14 * k, "Webhook", mf, T["text"])
        self.text(bx1, y + 14 * k, f"set (…{hook.rstrip('/').split('/')[-2][-4:]})" if ok else "not added", mf,
                  T["text"] if ok else T["warn"], anchor="ne")
        y += 44 * k
        tw3 = (bx1 - bx0 - 20 * k) / 3
        self.button("dc_paste_hook", bx0, y, bx0 + tw3, y + bh, "PASTE LINK", lambda: self.paste_setting("discord_webhook"), size=13 * k)
        if ok:
            self.button("dc_test", bx0 + tw3 + 10 * k, y, bx0 + 2 * tw3 + 10 * k, y + bh, "SENDING…" if self.hook_busy else "TEST",
                        self.test_webhook, size=13 * k)
            self.button("dc_remove", bx0 + 2 * tw3 + 20 * k, y, bx1, y + bh,
                        "TAP AGAIN" if self.is_armed("dc_remove") else "REMOVE",
                        lambda: self.confirm("dc_remove", lambda: (self.cfg.__setitem__("discord_webhook", ""), self.request_draw()),
                                             "Tap again to remove the webhook"), style="ghost", size=13 * k)
        y += bh + 8 * k
        y = self.q_toggle("set_discord_recaps", bx0, y, bx1, "Post a recap when a game ends", self.cfg["discord_recaps"],
                          lambda: self.adjust("discord_recaps", 1), sub="Time played, average FPS, battery used (games over 2 minutes)")
        shot = systools.latest_screenshot()
        self.button("dc_share", bx0, y, bx1, y + bh, "SHARING…" if self.share_busy else "SHARE MY LAST SCREENSHOT",
                    self.share_screenshot if ok else lambda: self.show_toast("Add a webhook first"),
                    style="accent" if ok and shot else "normal", size=13 * k)
        y += bh + 6 * k
        self.text(bx0, y, (f"{os.path.basename(shot[0])} · {fmt_ago(shot[1])}" if shot else
                           "Take one with Win+PrtScn or the SCREENSHOT button in quick settings"), df, T["muted"], maxw=bx1 - bx0)
        y += 28 * k
        yb = para(bx0, y, bx1 - bx0, "In Discord: Server settings → Integrations → Webhooks → New webhook → Copy webhook URL. "
                                     "Then tap PASTE LINK.")

        # ---- voice & app
        vy = max(ya, yb) + 22 * k
        if vy + 38 * k + bh > y1:
            return
        vy = self.q_label(x0, vy, "VOICE & APP")
        disc = (self.ls_info or {}).get("discord") or []
        used = sum(p[2] for p in disc)
        items = [("dc_mute", "MUTE MIC", lambda: self.discord_voice("mute")),
                 ("dc_deaf", "DEAFEN", lambda: self.discord_voice("deafen")),
                 ("dc_trim", f"TRIM DISCORD ({fmt_bytes(used)})" if disc else "DISCORD ISN'T OPEN", self.trim_discord)]
        w4 = (x1 - x0 - 20 * k) / 3
        for i, (rid, label, fn) in enumerate(items):
            bx = x0 + i * (w4 + 10 * k)
            self.button(rid, bx, vy, bx + w4, vy + bh, label, fn if disc else (lambda: self.show_toast("Open Discord first")),
                        style="normal" if disc else "ghost", size=13 * k)
        vy += bh + 10 * k
        if vy + 20 * k < y1:
            self.text(x0, vy, "Mute and deafen press Discord's own shortcuts (Ctrl+Shift+M and Ctrl+Shift+D), so they work over any game.",
                      df, T["muted"], maxw=x1 - x0)

    # -------------------------------------------------------------- Legion Space footprint
    def load_ls_info(self):
        if self.ls_busy:
            return
        self.ls_busy = True
        self.ls_time = time.time()

        check_svc = time.time() - self.ls_service_t > 60
        if check_svc:
            self.ls_service_t = time.time()

        def work():
            allp = list_processes()
            procs = systools.legion_space_windows(allp)
            mine = {p[0] for p in procs}
            services = [p for p in systools.legion_space_processes(allp) if p[0] not in mine]
            disc = systools.discord_running(allp)
            own = systools.own_memory()
            svc = systools.button_service_state() if check_svc and self.device["legion"] else self.ls_service

            def done():
                self.ls_busy = False
                self.ls_info = {"procs": procs, "services": services, "own": own, "discord": disc}
                self.ls_service = svc
                self.request_draw()

            self.call(done)

        self.background(work)

    def watch_legion_space(self):
        """Lenovo's button service opens Legion Space whenever a Legion button is pressed, even with its startup off.
        If that happens, close the copy that just opened (one you open yourself, at any other time, is left alone)."""
        if not self.cfg["ls_keep_closed"] or not self.device["legion"] or time.time() < self.ls_user_until:
            return
        pressed = time.time()
        self.ls_press_t = pressed
        for delay in (250, 600, 1100, 2000, 3500, 6000, 9000):
            self.root.after(delay, lambda p=pressed: self.background(lambda: self._close_new_legion_space(p)))

    def _close_new_legion_space(self, pressed):
        if pressed != self.ls_press_t or time.time() < self.ls_user_until:
            return  # a newer press is being watched, or you opened it yourself
        wins = systools.legion_space_windows(list_processes(), since=pressed - 1.5)
        if not wins:
            return
        n = systools.close_processes([p[0] for p in wins])

        def done():
            if n:
                self.ls_auto_closed += 1
                self.add_log("BOOT", f"Legion Space opened from a Legion button (Lenovo's button service): closed it")
                if self.ls_auto_closed <= 2:
                    self.show_toast("Legion Space popped up from the Legion button: closed it")
                self.ls_time = 0
        self.call(done)

    def close_ls_soon(self):
        """Starting Lenovo's services can open Legion Space: close a copy that appears in the next few seconds
        (not one you open yourself)."""
        t0 = time.time()

        def check():
            if time.time() < self.ls_user_until:
                return
            wins = systools.legion_space_windows(list_processes(), since=t0 - 1)
            if wins:
                systools.close_processes([p_[0] for p_ in wins])
                self.call(lambda: self.add_log("BOOT", "Legion Space opened when Lenovo's services restarted: closed it"))
        for ms in (1000, 2000, 3500, 6000, 9000, 13000, 18000):
            self.root.after(ms, lambda: self.background(check))

    def open_legion_space_myself(self, target):
        """You asked for Legion Space: don't auto-close it for the next 30 minutes."""
        self.ls_user_until = time.time() + 1800
        if self.cfg["ls_svc_off"]:
            # Legion Space needs Lenovo's services: put them back for now (they're stopped again at Vanta's next start)
            self.show_toast("Starting Lenovo's services for Legion Space…")
            self.give_back_buttons(then=lambda: systools.open_target(target))
            return
        systools.open_target(target)

    def close_legion_space(self):
        procs = (self.ls_info or {}).get("procs") or []
        if not procs:
            return

        def work():
            # only the app itself: killing Lenovo's background services makes Windows restart them, and they reopen it
            wins = systools.legion_space_windows(list_processes())
            total = sum(p[2] for p in wins)
            n = systools.close_processes([p[0] for p in wins]) if wins else 0
            procs[:] = wins

            def done():
                msg = "Legion Space's window wasn't open (only Lenovo's background services were)" if not procs else \
                    f"Closed Legion Space, {fmt_bytes(total)} back" if n == len(procs) else \
                    f"Closed {n} of {len(procs)} Legion Space processes" if n else "Couldn't close Legion Space (run Vanta as administrator)"
                self.add_log("BOOT", msg)
                self.show_toast(msg)
                self.buzz()
                self.ls_time = 0
                self.load_ls_info()

            self.call(done)

        self.background(work)

    # -------------------------------------------------------------- loops
    def sample_loop(self):
        now = time.time()
        self.track_sleep(now)
        self.status = memory_status()
        self.lists = memory_lists() if self.admin else None
        frac = (self.status.ullTotalPhys - self.status.ullAvailPhys) / max(1, self.status.ullTotalPhys)
        self.history.append(frac)
        cur = systools.system_times()
        self.cpu = systools.cpu_percent(self.cpu_prev, cur)
        self.cpu_prev = cur
        if self.cpu is not None:
            self.cpu_hist.append(self.cpu / 100)
        self.batt = systools.battery_state()
        if self.batt:
            self.batt_hist.append(self.batt["rate_mw"] / 1000)
        if self.batt and self.batt.get("discharging") and self.batt.get("pct") is not None:
            for r in self.cfg["automations"]:
                if r.get("on") and r["trigger"] == "batt_low":
                    armed = self.batt_armed.setdefault(r["id"], True)
                    if armed and self.batt["pct"] <= r.get("arg", 20):
                        self.batt_armed[r["id"]] = False
                        self.call(lambda r_=r: self.run_rule(r_))
                    elif not armed and self.batt["pct"] > r.get("arg", 20) + 3:
                        self.batt_armed[r["id"]] = True
        if self.game:
            self.game["peak"] = max(self.game["peak"], frac)
            if self.batt and self.batt.get("discharging") and self.batt.get("rate_mw", 0) < 0:
                self.game["w_sum"] = self.game.get("w_sum", 0) - self.batt["rate_mw"] / 1000
                self.game["w_n"] = self.game.get("w_n", 0) + 1
        self.power_events()
        if self.gpu_meter:
            try:
                self.gpu = self.gpu_meter.read()
            except Exception:
                self.gpu = None
            if self.gpu is not None:
                self.gpu_hist.append(self.gpu / 100)
        if self.fps:
            self.fps_stats = self.fps.stats()
            if self.game and self.fps_stats and self.fps_stats[0] > 0:
                self.game["fps_sum"] = self.game.get("fps_sum", 0) + self.fps_stats[0]
                self.game["fps_n"] = self.game.get("fps_n", 0) + 1
                if len(self.fps_stats) > 1 and self.fps_stats[1]:
                    self.game["low_sum"] = self.game.get("low_sum", 0) + self.fps_stats[1]
                    self.game["low_n"] = self.game.get("low_n", 0) + 1
                self.auto_tdp_step()
            if self.fps.error:
                self.add_log("FAIL", f"FPS counter: {self.fps.error}")
                self.fps.stop()
                self.fps = None
        if now - self.started_at > 45:
            self.check_deals()  # returns at once unless 6 hours have passed
        if self.pad_on and int(now) % 30 < 2:
            self.pad_batt = self.pad.battery()
        if now - self.last_leak > 60:
            self.last_leak = now
            self.leak_tick()
        if now - self.last_clean_check > 60:
            self.last_clean_check = now
            self.auto_clean_tick()
        if now - self.last_power > 15:
            self.last_power = now
            self.power = power_status()
            light = systools.windows_light_mode()
            if light != self.light_mode:
                self.light_mode = light
                if self.cfg["follow_windows"]:
                    self.retheme()
        self.auto_tick()
        self.bgoal_tick(now)
        self.remind_tick(now)
        self.theme_day_tick(now)
        self.time_rules_tick(now)
        self.sleep_tick(now)
        self.daynight_tick(now)
        self.weather_tick()
        self.news_tick()
        if now - getattr(self, "dock_t", 0) >= 3:
            self.dock_t = now
            self.dock_tick()
        if now - getattr(self, "badge_t", 0) > 60 and self.library is not None:
            self.badge_t = now
            self.check_badges(self.cfg["badges_seen"] is not None)
            self.wrap_tick()
        visible = not self.hidden and self.root.state() != "iconic"
        if visible and self.tab in ("memory", "games") and now - self.proc_time > (5 if self.on_battery or self.tab == "games" else 3) \
                and not self.press and not self.kinetic:
            self.refresh_procs(now)
        if self.overlay:
            self.overlay.update()
        if visible:
            self.request_draw()
        delay = 1000 if visible and not self.on_battery else 2000 if visible or self.overlay else 5000
        self.root.after(delay, self.sample_loop)

    def refresh_procs(self, now=None):
        now = now or time.time()
        keep = self.procs[self.sel][0] if self.procs and self.sel < len(self.procs) else None
        self.proc_time = now
        procs = list_processes()
        times = systools.process_cpu_times([p[0] for p in procs])
        t0, prev = self.proc_cpu_prev
        if prev and now > t0:
            scale = 100 / (1e7 * (now - t0) * systools.CPU_COUNT)
            self.proc_cpu = {pid: max(0.0, (v - prev[pid]) * scale) for pid, v in times.items() if pid in prev}
        self.proc_cpu_prev = (now, times)
        if self.cfg["proc_sort"] == "cpu":
            procs.sort(key=lambda p: (self.proc_cpu.get(p[0], 0), p[2]), reverse=True)
        self.procs = procs
        ids = [p[0] for p in procs]
        self.sel = ids.index(keep) if keep in ids else min(self.sel, max(0, len(procs) - 1))

    def ui_loop(self):
        while True:
            try:
                item = self.jobq.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            try:
                if kind == "call":
                    item[1]()
                elif kind == "done":
                    self.busy = self.busy_action = None
                    self.proc_time = 0
                    self.job_done(*item[1:])
                elif kind == "fail":
                    self.busy = self.busy_action = None
                    self.add_log("FAIL", f"{ACTIONS.get(item[1], (item[1],))[0]}: {item[3]}")
                    self.show_toast("That didn't work, see the log")
                elif kind == "cover":
                    self.cover_ready(*item[1:])
                elif kind == "startup_state":
                    self.startup = item[1]
                    self.request_draw()
                elif kind == "legion":
                    self.legion_action(item[1])
            except Exception as ex:
                self.add_log("FAIL", str(ex))
        if self.show_event and kernel32.WaitForSingleObject(self.show_event, 0) == 0:
            self.show()
        if self.busy or self.clean_scanning or self.tools_busy or self.startup_busy or self.list_loading or \
                (self.tab == "startup" and self.startup_items is None):
            self.request_draw()
        if self.toast and 2.6 < time.time() - self.toast[1] < 3.0:
            self.request_draw()
        self.check_topup()
        if self.cfg["sync_on"] and time.time() - self.sync_t > 60:
            self.sync_tick()
        if self.tab == "play" and not self.hidden and time.time() - self.steam_state_t > 15:
            self.steam_state_t = time.time()
            self.background(lambda: (lambda st: self.call(lambda: (setattr(self, "steam_state", st), self.request_draw())))(
                systools.steam_states()))
        if time.time() - getattr(self, "bh_t", 0) > 3600:
            self.bh_t = time.time()
            self.record_battery_health()
        if self.legion:
            if self.legion.connected and getattr(self.legion, "pid", None) in systools.DINPUT_PIDS and \
                    getattr(self.legion, "pid", None) in systools.NEW_FW_PIDS and not getattr(self, "dinput_told", False):
                self.dinput_told = True
                self.show_toast("Controllers are in DirectInput mode: Settings › Controller & lights › Restore Xbox mode")
                self.add_log("BOOT", "The controllers are in DirectInput mode (games may not see them). Vanta reads them directly.")
            if self.legion.connected and not self.legion_rgb_sent:
                self.legion_rgb_sent = True
                if self.cfg["rgb_mode"] != "keep":
                    self.root.after(600, lambda: self.apply_rgb(quiet=True))
            elif not self.legion.connected:
                self.legion_rgb_sent = False
            if self.pointer and self.legion.connected and not self.pointer_sent:
                self.pointer_sent = True
                self.legion.on_gyro = self.pointer.feed
                self.legion.gyro_side = self.cfg["pointer_side"]
                self.background(lambda: self.legion.write(systools.gyro_packets(self.cfg["pointer_side"], True)))
            elif not self.legion.connected:
                self.pointer_sent = False
        self.light_tick()
        self.root.after(80 if self.busy else 150 if not self.hidden else 400, self.ui_loop)

    def pad_loop(self):
        if self.pad:
            self.pad.stick_nav = self.cfg["stick_nav"]
            stuck0 = self.pad.stuck
            buttons = self.pad.poll()
            if self.pad.stuck and self.pad.stuck != stuck0:
                names = [n for m, n in ((1, "up"), (2, "down"), (4, "left"), (8, "right")) if self.pad.stuck & m]
                self.add_log("PAD", "Ignoring " + " and ".join(names) + ": held for 8 seconds without a break "
                             "(stick drift or a stuck button). It works again once released.")
            both = (self.pad.prev & 0x30) == 0x30 and self.cfg["pad_combo"]
            now = time.time()
            if both and self.combo_t is None and ("back" in buttons or "start" in buttons):
                self.combo_t = now
                if self.focused() and self.page in ("help", "settings"):
                    self.page = None
            elif self.combo_t is not None:
                if both and now - self.combo_t >= 0.7:
                    self.combo_t = -1.0  # used: wait for release
                    self.open_hub()
                elif not both:
                    if self.combo_t > 0:
                        self.toggle_overlay()
                    self.combo_t = None
            elif self.padmouse and self.padmouse.on:
                self.padmouse.paused = bool(self.osk)
                if self.osk and buttons:
                    for b in buttons:
                        self.osk.pad(b)
            elif buttons and self.osk:
                for b in buttons:
                    self.osk.pad(b)
            elif buttons and self.quick and not (self.focused() and not self.panel_focused()):
                for b in buttons:
                    self.quick_pad(b)
            elif buttons and self.quick and self.focused():
                # you're back in the main window: Quick settings must not keep taking the controller
                self.close_quick(restore=False)
                for b in buttons:
                    self.on_pad(b)
            elif buttons and not self.focused():
                if now - getattr(self, "pad_ignored_t", 0) > 30 and not self.game:
                    self.pad_ignored_t = now
                    root, pid, cls = self.front_window()
                    self.add_log("PAD", f"Controller ignored: another window is in front ({cls or 'none'}, process {pid})")
            elif buttons and self.focused():
                for b in buttons:
                    if self.pointing() and b == "a":
                        self.pointer_click()
                    elif self.pointing() and b in ("ls", "rs"):
                        self.pointer.x = self.pointer.y = None
                        self.pointer.recalibrate()
                    else:
                        self.on_pad(b)
        self.root.after((33 if not self.hidden else 100) if self.pad_on else 500, self.pad_loop)

    def open_hub(self):
        self.show()
        self.set_tab("play")
        try:
            systools.force_foreground(self.cur_hwnd())
        except Exception:
            pass
        self.buzz()

    def game_loop(self):
        try:
            if self.game:
                if not systools.process_alive(self.game["pid"]):
                    self.end_game()
            else:
                found = fullscreen_app(self.cur_hwnd())
                if found and found[0] not in self.boosted:
                    self.boosted.add(found[0])
                    self.start_game(*found)
        except Exception as ex:
            self.add_log("FAIL", f"Game watch: {ex}")
        self.root.after(2000, self.game_loop)

    def start_game(self, pid, exe):
        name = os.path.splitext(exe)[0]
        hub = self.hub_launch if self.hub_launch and time.time() - self.hub_launch["time"] < 300 else None
        self.hub_launch = None
        self.game = {"pid": pid, "name": hub["name"] if hub else name, "exe": exe, "start": time.time(), "peak": 0.0,
                     "saved": None, "hub": hub, "fps_sum": 0.0, "fps_n": 0,
                     "batt0": self.power["pct"] if self.power and self.power.get("pct", 255) <= 100 else None}
        self.add_log("GAME", f"Game started: {self.game['name']}" + (f" ({exe})" if hub else ""))
        self.root.after(8000, self.apply_game_audio)
        cfg = self.cfg
        focused_already = bool(hub and self.focus)
        if cfg["game_priority"]:
            self.background(lambda: systools.set_priority(pid, "above") and
                            self.call(lambda: self.add_log("GAME", f"{exe} gets above-normal CPU priority")))
        if cfg["game_boost_auto"] and self.admin and not focused_already:
            self.run("boost", "GAME")
        if cfg["game_close_on"] and cfg["close_list"] and not focused_already:
            picks = [n for n in cfg["close_list"] if n.lower() != exe.lower()]

            def close_work():
                closed = systools.close_apps(picks)
                self.call(lambda: self.add_log("GAME", "Closed " + (", ".join(closed) if closed else "nothing (none were running)")))

            self.background(close_work)
        if (cfg["fps_counter"] or (cfg["auto_tdp"] and self.device["legion"])) and systools.presentmon_installed():
            try:
                self.fps = systools.FpsReader(pid)
            except Exception as ex:
                self.add_log("FAIL", f"FPS counter: {ex}")
        self.atdp_start = (self.tools or {}).get("tdp") or None
        if cfg["game_quiet"]:
            self.quiet_on(self.game)
        if cfg["save_auto"] and systools.ludusavi_installed():
            gname = self.game["name"]
            self.background(lambda: (lambda r: self.call(lambda: self.add_log("GAME", f"Saves of {gname}: " + (
                f"backed up ({fmt_bytes(r[2])})" if r[0] else r[1]))))(systools.ludusavi("backup", gname)))
        self.atdp_w = None
        _, gt = self.game_tune_of(self.game)
        if gt.get("padmouse") in systools.PAD_LAYOUTS and not (self.padmouse and self.padmouse.on):
            self.game["padmouse_auto"] = True
            self.toggle_padmouse(gt["padmouse"], quiet=True)
            self.add_log("GAME", f"Controller as mouse for {self.game['name']}: {systools.PAD_LAYOUTS[gt['padmouse']]['name']}")
        self.fire("game_start", self.game["name"])
        if gt.get("gyro") in POINTER_MODES and gt["gyro"] != cfg["pointer_mode"]:
            self.game["gyro_prev"] = cfg["pointer_mode"]
            self.set_pointer_mode(gt["gyro"])
            self.add_log("GAME", f"Motion controls for {self.game['name']}: {POINTER_MODES[gt['gyro']]}")
        if self.device["legion"]:  # the wattage the game started with (WMI, so off the UI thread)
            holder = self.game
            self.background(lambda: holder.__setitem__("tdp0", systools.get_tdp()))
        lights = cfg["game_lights"].get(self.game_key(self.game))
        if lights:
            self.apply_rgb(quiet=True, override=lights)
            self.add_log("GAME", f"Lights for {self.game['name']}: {RGB_MODE_LABELS.get(lights['mode'], lights['mode'])}")
        if hub:  # modes were already switched when you pressed Play
            return self.request_draw()
        profile = cfg["game_profiles"].get(name.lower())
        tune = cfg["game_tune"].get(name.lower())
        if profile or cfg["game_perf_auto"] or tune:
            holder = self.game
            self.switch_modes(profile, name, lambda saved: holder.__setitem__("saved", saved), tune)
        self.request_draw()

    def switch_modes(self, profile, name, on_saved, tune=None):
        """Remember the current state, then apply a game's profile (or performance modes) and its own settings."""
        if self.preview_blocks("game modes"):
            return
        legion = self.device["legion"]
        tdp_w, max_w = self.cfg["tdp"], self.tdp_max
        perf = self.cfg["game_perf_auto"]
        tune = dict(tune or {})

        def work():
            saved = {"power": systools.get_power_mode(), "thermal": systools.get_thermal_mode() if legion else None}
            modes = systools.display_modes()
            saved["hz"] = modes["hz"] if modes else None
            saved["res"] = (modes["w"], modes["h"]) if modes else None
            if legion and saved["thermal"] == 255:
                saved["tdp"] = systools.get_tdp()
            what = []
            if profile == "custom" and legion:
                systools.set_tdp(tdp_w, max_w)
                what.append(f"custom TDP {tdp_w} W")
            elif profile:
                systools.apply_profile(profile, legion)
                what.append(next(p[1] for p in systools.PROFILES if p[0] == profile) + " profile")
            elif perf and not tune.get("tdp"):
                systools.set_power_mode("performance")
                if legion:
                    systools.set_thermal_mode(3)
                what.append("performance modes")
            if tune.get("tdp") and legion:
                if systools.set_tdp(tune["tdp"], max_w):
                    what.append(f"{tune['tdp']} W")
            if tune.get("hdr") in ("on", "off"):
                sup, now_on = systools.hdr_state()
                if sup and now_on != (tune["hdr"] == "on"):
                    saved["hdr"] = now_on
                    if systools.set_hdr(tune["hdr"] == "on"):
                        what.append("HDR " + tune["hdr"])
            res, hz = tune.get("res"), tune.get("hz")
            if res or hz:
                if systools.set_display_mode(res[0] if res else None, res[1] if res else None, hz):
                    what.append(" ".join(filter(None, [f"{res[0]}×{res[1]}" if res else "", f"{hz} Hz" if hz else ""])))
            if tune.get("cpu_max"):
                saved["cpu"] = systools.get_cpu_max()
                if systools.set_cpu_max(tune["cpu_max"]):
                    what.append(f"CPU {self.cpu_label(tune['cpu_max']).lower()}")
            amd = tune.get("amd") or {}
            if amd:
                feats = [k for k in amd if k in systools.AMD_FEATURES]
                saved["amd"] = systools.ADLX.snapshot(feats)
                done_amd = systools.ADLX.apply(amd)
                if done_amd:
                    what.append(", ".join(done_amd))

            def done():
                on_saved(saved)
                if what:
                    self.add_log("GAME", f"{name}: " + "; ".join(what))
                if self.tools is not None:
                    self.load_tools()

            self.call(done)

        self.background(work)

    def game_tune_of(self, g):
        """(key, tune) for a running game: library games are keyed by id, others by name."""
        hub = g.get("hub") if g else None
        for k in ([hub["id"]] if hub else []) + [g["name"].lower()] if g else []:
            if k in self.cfg["game_tune"]:
                return k, self.cfg["game_tune"][k]
        return (hub["id"] if hub else (g["name"].lower() if g else None)), {}

    def end_game(self):
        g, self.game = self.game, None
        hub = g.get("hub")
        if hub:
            self.run_launch_extras(hub, "after")
            self.after_game_stores(hub)
        self.restore_game_audio(g)
        if self.cfg["sort_caps_auto"]:
            self.root.after(20000, lambda gg=dict(g): self.sort_captures([{"name": gg["name"], "start": gg["start"],
                                                                          "dur": time.time() - gg["start"]}], quiet=True))
        tkey, tune_now = self.game_tune_of(g)
        tdp_used = self.atdp_w or tune_now.get("tdp") or g.get("tdp0")
        cap_used = ((tune_now.get("amd") or {}).get("frtc_fps") if (tune_now.get("amd") or {}).get("frtc") else None)
        if g.get("gyro_prev") is not None:
            self.set_pointer_mode(g["gyro_prev"])
        if g.get("padmouse_auto") and self.padmouse and self.padmouse.on:
            self.toggle_padmouse(quiet=True)
        self.fire("game_end", g["name"])
        self.suspended = None
        self.quiet_off()
        if self.atdp_w is not None and self.atdp_start and self.device["legion"]:
            w0, self.atdp_w = self.atdp_start, None
            self.background(lambda: systools.set_tdp(w0, self.tdp_max))
            self.add_log("TOOL", f"Auto TDP: back to {w0} W")
        self.atdp_w = self.atdp_start = None
        if self.game_key(g) in self.cfg["game_lights"]:
            self.apply_rgb(quiet=True)
        if hub and not g["saved"]:
            g["saved"] = hub.get("saved")
        if self.fps:
            self.fps.stop()
            self.fps = None
            self.fps_stats = None
        dur = time.time() - g["start"]
        if dur >= 60:
            p = self.power
            sessions = [{"name": g["name"], "start": g["start"], "dur": dur, "peak": g["peak"],
                         "id": hub["id"] if hub else None,
                         "fps": round(g["fps_sum"] / g["fps_n"], 1) if g.get("fps_n") else None,
                         "batt": (g["batt0"] - p["pct"]) if g.get("batt0") is not None and p and p.get("pct", 255) <= 100 else None,
                         "low": round(g["low_sum"] / g["low_n"], 1) if g.get("low_n") else None,
                         "w": round(g["w_sum"] / g["w_n"], 2) if g.get("w_n", 0) >= 60 else None,
                         "tdp": tdp_used, "cap": cap_used, "key": tkey}
                        ] + list(self.cfg["sessions"])
            self.cfg["sessions"] = sessions[:500]
            self.recap = sessions[0]
            self.recap_new = True
            pd = dict(self.play_days())
            dk = time.strftime("%Y-%m-%d", time.localtime(g["start"]))
            pd[dk] = round(pd.get(dk, 0) + dur / 60, 1)
            self.cfg["play_days"] = dict(sorted(pd.items())[-800:])
            self.call(lambda: self.check_badges(True))
        if self.cfg["sleep_after_game"]:
            self.cfg["sleep_after_game"] = False
            self.sleep_at = time.time() + 60
            self.sleep_mins = 1
            self.sleep_warned = False
            self.call(lambda: self.sleep_tick(time.time()))
        self.add_log("GAME", f"{g['name']} closed after {fmt_duration(dur)} (peak RAM {g['peak'] * 100:.0f}%)")
        if dur >= 60:
            self.push_event(f"{g['name']} closed", f"Played {fmt_duration(dur)}")
        if dur >= 120 and self.cfg["discord_recaps"] and systools.valid_webhook(self.cfg["discord_webhook"]):
            self.post_recap(g, dur)
        saved = g["saved"]
        if saved and self.cfg["game_restore"]:
            def work():
                if saved.get("power"):
                    systools.set_power_mode(saved["power"])
                if saved.get("thermal") in (1, 2, 3):
                    systools.set_thermal_mode(saved["thermal"])
                elif saved.get("thermal") == 255 and saved.get("tdp"):
                    systools.set_tdp(saved["tdp"], self.tdp_max)
                modes = systools.display_modes()
                res = tuple(saved["res"]) if saved.get("res") else None
                if modes and ((res and (modes["w"], modes["h"]) != res) or (saved.get("hz") and modes["hz"] != saved["hz"])):
                    systools.set_display_mode(res[0] if res else None, res[1] if res else None, saved.get("hz"))
                if saved.get("amd"):
                    systools.ADLX.apply(saved["amd"])
                if saved.get("hdr") is not None:
                    systools.set_hdr(saved["hdr"])
                if saved.get("cpu") and saved["cpu"][0] is not None:
                    systools.set_cpu_max(*saved["cpu"])

                def done():
                    self.add_log("GAME", "Restored your power modes")
                    if self.tools is not None:
                        self.load_tools()

                self.call(done)

            self.background(work)
        if hub:
            if self.focus and self.cfg["focus_off_after"]:
                self.focus_stop()
            if self.cfg["return_to_hub"]:
                self.root.after(1500, self.open_hub)
        if self.recap_new and self.cfg["game_recap"]:
            self.root.after(1700 if hub and self.cfg["return_to_hub"] else 300, self.show_recap_soon)
        self.request_draw()

    # -------------------------------------------------------------- hub: library, focus mode, play
    def load_library(self):
        self.lib_loading = True

        def work():
            games = systools.game_library(self.cfg["custom_games"], self.cfg["rom_dirs"])

            def done():
                self.library = games
                self.lib_loading = False
                try:
                    self.track_library(games)
                except Exception:
                    pass
                self.fetch_covers()
                self.fetch_genres()
                if self.lib_sel not in {g["id"] for g in games}:
                    view = self.lib_games()
                    self.lib_sel = view[0]["id"] if view else None
                self.request_draw()

            self.call(done)

        self.background(work)
        self.request_draw()

    def game_stats(self, g):
        """(last played, minutes played) merging the launcher's numbers with sessions seen by this app."""
        last, mins = g.get("last", 0), g.get("minutes", 0)
        own = 0
        for sx in self.cfg["sessions"]:
            if sx.get("id") == g["id"] or sx["name"].lower() == g["name"].lower():
                last = max(last, sx["start"])
                own += sx["dur"] / 60
        return last, max(mins, int(own))

    def lib_games(self):
        if self.cfg["lib_filter"] in ("__store", "__list", "__clear"):
            self.cfg["lib_filter"] = "all"
        games = list(self.library or [])
        if self.lib_query:
            q = self.lib_query.lower()
            games = [g for g in games if q in g["name"].lower()]
        lf = self.cfg["lib_filter"]
        if lf.startswith("smart:"):
            ids = self.smart_ids(lf[6:])
            games = [g for g in games if g["id"] in ids]
        elif lf.startswith("genre:"):
            games = [g for g in games if lf[6:] in self.genres_of(g)]
        elif lf.startswith("list:"):
            ids = set(self.cfg["lists"].get(lf[5:], []))
            games = [g for g in games if g["id"] in ids]
        f = self.cfg["lib_filter"]
        favs = set(self.cfg["favorites"])
        if f == "fav":
            games = [g for g in games if g["id"] in favs]
        elif f != "all" and not f.startswith(("list:", "smart:", "genre:")):
            games = [g for g in games if g["source"].lower() == f]
        sort = self.cfg["lib_sort"]
        if sort == "name":
            games.sort(key=lambda g: g["name"].lower())
        elif sort == "size":
            games.sort(key=lambda g: g["size"], reverse=True)
        elif sort == "time":
            games.sort(key=lambda g: self.game_stats(g)[1], reverse=True)
        else:
            games.sort(key=lambda g: (self.game_stats(g)[0], g["name"].lower() < "m"), reverse=True)
        games.sort(key=lambda g: g["id"] not in favs)  # favourites first (stable sort keeps the order inside)
        if self.cfg["guest"]:
            ids_ = self.guest_ids()
            if ids_ is not None:
                games = [g for g in games if g["id"] in ids_]
        return games

    def selected_game(self):
        return next((g for g in (self.library or []) if g["id"] == self.lib_sel), None)

    def tap_game(self, gid):
        if self.lib_sel == gid:
            self.play(self.selected_game())
        else:
            self.lib_sel = gid
            self.request_draw()

    def toggle_favorite(self, gid):
        favs = list(self.cfg["favorites"])
        favs.remove(gid) if gid in favs else favs.append(gid)
        self.cfg["favorites"] = favs
        self.request_draw()

    def set_lib(self, key, value):
        v = value
        if key == "lib_filter" and v == "__smart":
            self.open_page("collections")
            return
        if key == "lib_filter" and v == "__clear":
            self.lib_query = ""
            self.request_draw()
            return
        if key == "lib_filter" and v == "__genre":
            names = [n_ for n_, _ in self.genre_counts()[:12]]
            cur = self.cfg["lib_filter"][6:] if self.cfg["lib_filter"].startswith("genre:") else None
            v = "genre:" + (names[(names.index(cur) + 1) % len(names)] if cur in names else names[0]) if names else "all"
        if key == "lib_filter" and v == "__list":
            names = sorted(self.cfg["lists"])
            cur = self.cfg["lib_filter"][5:] if self.cfg["lib_filter"].startswith("list:") else None
            v = "list:" + (names[(names.index(cur) + 1) % len(names)] if cur in names else names[0]) if names else "all"
        if key == "lib_filter" and v == "__store":
            srcs = sorted({g["source"].lower() for g in self.library or []})
            cur = self.cfg["lib_filter"]
            v = srcs[(srcs.index(cur) + 1) % len(srcs)] if cur in srcs else (srcs[0] if srcs else "all")
        value = v
        self.cfg[key] = value
        self.set_off("lib", 0)
        self.request_draw()

    def add_game(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, title="Pick the game's .exe",
                                          filetypes=[("Programs", "*.exe"), ("Shortcuts", "*.lnk *.url")])
        if not path:
            return
        path = os.path.normpath(path)
        name = os.path.splitext(os.path.basename(path))[0]
        custom = [c for c in self.cfg["custom_games"] if c["exe"].lower() != path.lower()] + [{"name": name, "exe": path}]
        self.cfg["custom_games"] = custom
        self.lib_sel = f"custom:{path.lower()}"
        self.add_log("TOOL", f"Added {name} to your library")
        self.load_library()

    def remove_game(self, g):
        def do():
            self.cfg["custom_games"] = [c for c in self.cfg["custom_games"] if f"custom:{c['exe'].lower()}" != g["id"]]
            self.lib_sel = None
            self.load_library()

        self.confirm(f"rm_{g['id']}", do, f"Tap again to remove {g['name']} from the list (nothing is uninstalled)")

    def play(self, g):
        if not g:
            return
        if self.game:
            self.show_toast(f"{self.game['name']} is still running")
            return
        if self.cfg["guest"] and not self.guest_allows(g):
            self.show_toast("Not on the guest shelf")
            return
        note = self.note_of(g["id"])
        if note:
            self.root.after(14000, lambda: self.nudge(f"Your note for {g['name']}", note))
        self.run_launch_extras(g, "with")
        cfg = self.cfg
        self.hub_launch = {"id": g["id"], "name": g["name"], "time": time.time(), "saved": None}
        hub = self.hub_launch
        profile = cfg["game_profiles"].get(g["id"])
        tune = cfg["game_tune"].get(g["id"]) or cfg["game_tune"].get(g["name"].lower())
        if profile or cfg["game_perf_auto"] or tune:
            self.switch_modes(profile, g["name"], lambda saved: hub.__setitem__("saved", saved), tune)
        if cfg["focus_on_play"] and not self.focus:
            self.focus_start(quiet=True)
        if systools.launch_game(self.with_launch_args(g)):
            self.add_log("GAME", f"Launching {g['name']}…")
            self.show_toast(f"Launching {g['name']}")
            self.buzz()
            if cfg["hub_minimize"]:
                self.root.after(2500, lambda: self.root.iconify() if not self.hidden else None)
        else:
            self.hub_launch = None
            self.show_toast(f"Couldn't start {g['name']}")
            self.add_log("FAIL", f"Couldn't launch {g['name']} ({g['launch']})")
        self.request_draw()

    def focus_toggle(self):
        self.focus_stop() if self.focus else self.focus_start()

    def focus_start(self, quiet=False):
        if self.focus_busy:
            return
        self.focus_busy = True
        cfg = self.cfg
        keep = {os.getpid()} | ({self.game["pid"]} if self.game else set())

        def work():
            hwnds = systools.minimize_windows(keep) if cfg["focus_min"] else []
            throttled = systools.throttle_background(list_processes(), keep, cfg["focus_keep"]) if cfg["focus_eco"] else []
            closed = systools.close_apps(cfg["close_list"]) if cfg["focus_close"] and cfg["close_list"] else []

            def done():
                self.focus_busy = False
                self.focus = {"hwnds": hwnds, "throttled": throttled, "closed": closed, "start": time.time()}
                parts = [f"{len(hwnds)} windows minimized", f"{len(throttled)} apps in efficiency mode"]
                if closed:
                    parts.append(f"closed {', '.join(closed)}")
                self.add_log("FOCUS", "Focus mode on: " + ", ".join(parts))
                if not quiet:
                    self.show_toast("Focus mode on")
                if cfg["focus_boost"] and self.admin:
                    if self.busy:
                        self.root.after(1500, lambda: self.run("boost", "FOCUS") if not self.busy else None)
                    else:
                        self.run("boost", "FOCUS")
                self.buzz()
                self.request_draw()

            self.call(done)

        self.background(work)
        self.request_draw()

    def focus_stop(self):
        f, self.focus = self.focus, None
        if not f:
            return
        restore = self.cfg["focus_restore_windows"]

        def work():
            systools.unthrottle(f["throttled"])
            if restore:
                systools.restore_windows(f["hwnds"])
            self.call(lambda: (self.add_log("FOCUS", f"Focus mode off after {fmt_duration(time.time() - f['start'])}: "
                                                      f"{len(f['throttled'])} apps back to normal"), self.request_draw()))

        self.background(work)
        self.show_toast("Focus mode off")
        self.request_draw()

    # covers: decoded and resized off the UI thread, turned into Tk images on it
    def cover_worker(self):
        while True:
            key, path = self.cover_q.get()
            try:
                img = self.render_art(key, path)
                self.jobq.put(("cover", key, img))
            except Exception:
                self.jobq.put(("cover", key, None))

    @staticmethod
    def round_mask(w, h, r, fade=None):
        """An anti-aliased rounded-rectangle alpha mask (drawn 3x and scaled down). fade=(start fraction) fades
        the bottom out to transparent, so a banner melts into whatever is under it."""
        from PIL import Image, ImageDraw
        s_ = 3
        m = Image.new("L", (w * s_, h * s_), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, w * s_ - 1, h * s_ - 1), radius=int(r * s_), fill=255)
        m = m.resize((w, h), Image.LANCZOS)
        if fade is not None:
            grad = Image.new("L", (1, h), 0)
            start = int(h * fade)
            for y in range(h):
                t = 0.0 if y < start else (y - start) / max(1, h - start)
                grad.putpixel((0, y), int(255 * (1 - t) ** 1.6))
            from PIL import ImageChops
            m = ImageChops.multiply(m, grad.resize((w, h)))
        return m

    def render_art(self, key, path):
        """Covers, banners, backdrops and generated art, prepared off the UI thread."""
        from PIL import Image, ImageOps, ImageEnhance, ImageFilter
        kind = next((p_ for p_ in ("amb", "gen", "hero") if str(key[0]).startswith(p_ + ":")), "cover")
        w, h = key[1], key[2]
        prem = len(key) > 3 and key[3]
        if kind == "amb":
            # the selected game's art, blurred and darkened behind the whole Play tab
            bg = key[4]
            with Image.open(path) as im:
                small = ImageOps.fit(im.convert("RGB"), (max(8, w // 10), max(8, h // 10)), Image.BILINEAR)
            small = small.filter(ImageFilter.GaussianBlur(3))
            img = small.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(4))
            img = ImageEnhance.Color(img).enhance(1.15)
            img = ImageEnhance.Brightness(img).enhance(0.34)
            base = Image.new("RGB", (w, h), bg)
            # fade to the theme background towards the bottom and the right, so text stays easy to read
            m = Image.new("L", (w, h), 0)
            from PIL import ImageDraw
            d = ImageDraw.Draw(m)
            for y in range(0, h, 4):
                v = int(255 * max(0.0, 1 - (y / h) ** 1.4 * 0.85))
                d.rectangle((0, y, w, y + 4), fill=v)
            return Image.composite(img, base, m)
        if kind == "gen":
            # a smooth two-tone gradient with a soft glow: art for games without a cover
            import colorsys
            hue = key[4]
            c1 = tuple(int(v * 255) for v in colorsys.hsv_to_rgb(hue, 0.55, 0.42))
            c2 = tuple(int(v * 255) for v in colorsys.hsv_to_rgb((hue + 0.08) % 1, 0.6, 0.12))
            gw, gh = max(2, w // 6), max(2, h // 6)
            g_ = Image.new("RGB", (gw, gh))
            for y in range(gh):
                for x in range(gw):
                    t = min(1.0, max(0.0, (x / gw) * 0.35 + (y / gh) * 0.85))
                    g_.putpixel((x, y), tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
            img = g_.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(2))
            glow = Image.new("L", (w, h), 0)
            from PIL import ImageDraw
            ImageDraw.Draw(glow).ellipse((-w * 0.3, -h * 0.25, w * 0.9, h * 0.45), fill=38)
            glow = glow.filter(ImageFilter.GaussianBlur(max(4, w // 6)))
            img = Image.composite(Image.new("RGB", (w, h), (255, 255, 255)), img, glow)
            bgc = key[5] if len(key) > 5 else "#000000"
            return Image.composite(img, Image.new("RGB", (w, h), bgc), self.round_mask(w, h, max(6, w * 0.05)))
        with Image.open(path) as im:
            img = ImageOps.fit(im.convert("RGB"), (w, h), Image.LANCZOS, centering=(0.5, 0.35))
        if kind == "hero":
            if prem:  # a banner that fades into the page
                img = ImageEnhance.Brightness(img).enhance(0.8).convert("RGBA")
                img.putalpha(self.round_mask(w, h, max(10, w * 0.03), fade=0.35))
                return img
            return ImageEnhance.Brightness(img).enhance(0.42)
        if prem:
            # bake the rounded corners onto the page colour: an opaque image draws much faster than a blended one
            bgc = key[4] if len(key) > 4 else "#000000"
            img = Image.composite(img, Image.new("RGB", (w, h), bgc), self.round_mask(w, h, max(6, w * 0.05)))
        return img

    def shadow(self, w, h, r):
        """A soft drop shadow image for a w×h card (cached per size)."""
        k = self.k
        pad = int(18 * k)
        key = ("shadow", int(w), int(h), self.t["bg"])
        img = self.covers.get(key)
        if img is not None or key in self.covers:
            return img, pad
        try:
            from PIL import Image, ImageDraw, ImageFilter, ImageTk
            W_, H_ = int(w) + 2 * pad, int(h) + 2 * pad
            a = Image.new("L", (W_, H_), 0)
            ImageDraw.Draw(a).rounded_rectangle((pad, pad + int(6 * k), pad + int(w), pad + int(h) + int(6 * k)), radius=int(r), fill=150)
            a = a.filter(ImageFilter.GaussianBlur(max(4, pad // 2)))
            im = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
            im.putalpha(a)
            img = ImageTk.PhotoImage(im, master=self.root)
        except Exception:
            img = None
        self.covers[key] = img
        return img, pad

    def art(self, key, path):
        """Any prepared image by key: from the cache, or queued for the worker (None until it's ready)."""
        if key in self.covers:
            self.covers.move_to_end(key)
            return self.covers[key]
        if key not in self.cover_pending:
            self.cover_pending.add(key)
            self.cover_q.put((key, path))
        return None

    def ambient(self, g, W, H):
        """The selected game's art as a blurred backdrop (hero art if there is one, else the cover)."""
        if not g or not self.t.get("premium") or not self.cfg["ambient"]:
            return None
        src = g.get("hero") or g.get("cover")
        if not src:
            if g.get("hero") is None:
                self.hero(g, 10, 10)  # starts the download
            return None
        return self.art(("amb:" + g["id"], int(W), int(H), True, self.t["bg"]), src)

    def gen_art(self, g, w, h):
        hue = sum(ord(ch) * (i + 1) for i, ch in enumerate(g["name"])) % 360 / 360
        return self.art(("gen:" + g["id"], int(w), int(h), True, hue, self.t["bg"]), None)

    def cover_ready(self, key, img):
        self.cover_pending.discard(key)
        if img is None:
            self.covers[key] = None
        else:
            try:
                from PIL import ImageTk
                self.covers[key] = ImageTk.PhotoImage(img, master=self.root)
            except Exception:
                self.covers[key] = None
        while len(self.covers) > 120:
            self.covers.popitem(last=False)
        self.request_draw()

    def cover(self, g, w, h):
        if not g.get("cover"):
            return None
        key = (g["id"], int(w), int(h), bool(self.t.get("premium")), self.t["bg"])
        if key in self.covers:
            self.covers.move_to_end(key)
            return self.covers[key]
        if key not in self.cover_pending:
            self.cover_pending.add(key)
            self.cover_q.put((key, g["cover"]))
        return None

    # -------------------------------------------------------------- per-game settings (TDP, display, AMD)
    def open_tune(self, key, name):
        self.tune_target = (key, name)
        self.amd_state = None
        self.page = "tune"
        self.focus_id = None
        self.set_off("tune", 0)

        def work():
            state = systools.ADLX.read() if systools.ADLX.available() else {}
            modes = systools.display_modes()
            self.call(lambda: (setattr(self, "amd_state", state), setattr(self, "tune_modes", modes), self.request_draw()))

        self.background(work)
        self.lookup_community(key, name)
        self.lookup_pcgw(key, name)
        self.request_draw()

    def lookup_community(self, key, name, force=False):
        """Fetch player-reported settings for this game from Deck Verified (cached for 3 days)."""
        if not self.cfg["community_presets"] or (key in self.dv and not force and self.dv[key]["status"] != "offline"):
            return
        self.dv[key] = {"status": "loading", "data": None, "appid": None}
        g = next((g_ for g_ in self.library if g_["id"] == key), None)

        def work():
            appid = None
            try:
                if key.startswith("steam:"):
                    appid = key.split(":", 1)[1]
                elif g and not str(key).startswith(("sample:", "rom:")):
                    appid = self.art_appid(g)
                data = systools.dv_game(appid=appid, name=None if appid else name, max_age=0 if force else 3 * 86400)
            except Exception:
                data = None
            st = "offline" if data is None else "ok" if data.get("reports") else "none"
            self.call(lambda: (self.dv.__setitem__(key, {"status": st, "data": data, "appid": appid}), self.request_draw()))

        self.background(work)

    def lookup_pcgw(self, key, name):
        """What PCGamingWiki says this game supports (upscalers, frame generation, HDR...). Cached two weeks."""
        if not self.cfg["pcgw_info"] or key in self.pcgw:
            return
        self.pcgw[key] = {"status": "loading", "data": None}
        g = next((g_ for g_ in self.library if g_["id"] == key), None)

        def work():
            try:
                appid = key.split(":", 1)[1] if key.startswith("steam:") else (self.art_appid(g) if g and not key.startswith(("sample:", "rom:")) else None)
                data = systools.pcgw_support(appid=appid, name=None if appid else name)
            except Exception:
                data = None
            st = "offline" if data is None else "ok" if data.get("items") else "none"
            self.call(lambda: (self.pcgw.__setitem__(key, {"status": st, "data": data}), self.request_draw()))
        self.background(work)

    def sessions_for(self, key, name):
        nl = (name or "").lower()
        return [s_ for s_ in self.cfg["sessions"] if s_.get("key") == key or s_.get("id") == key or s_.get("name", "").lower() == nl]

    def insight_cards(self, key, name, t):
        """Cards for the game settings page: what your own play says, and what the game supports."""
        cards = []
        ses = self.sessions_for(key, name)
        if ses:
            lines, buttons = [], []
            learn = systools.learn_from_sessions(ses, self.tdp_max)
            if learn:
                lines.append((learn["why"], "text"))
                if learn["kind"] != "keep" and learn["tdp"] != t.get("tdp"):
                    buttons.append((f"USE {learn['tdp']} W", lambda w=learn["tdp"]: self.tune_set("tdp", w), "accent"))
            else:
                need = 15 - sum(s_["dur"] for s_ in ses if s_.get("fps") and s_.get("tdp")) / 60
                lines.append((f"Play about {max(1, round(need))} more minutes with the FPS counter on and Vanta will suggest a wattage",
                              "muted"))
            b = self.batt or {}
            est = systools.battery_estimate(ses, b.get("full_mwh"), b.get("remaining_mwh") if not b.get("ac") else None)
            if est:
                full_h, now_h, w = est
                lines.append((f"Battery: about {fmt_duration(full_h * 3600)} on a full charge" +
                              (f", {fmt_duration(now_h * 3600)} from where you are now" if now_h else "") +
                              f" (your sessions drew {w:.1f} W)", "accent"))
            else:
                lines.append(("Play on battery for 5+ minutes and Vanta will estimate how long a charge lasts in this game", "muted"))
            fps_s = [s_ for s_ in ses if s_.get("fps")]
            if fps_s:
                last = fps_s[0]
                lines.append((f"Last time: {last['fps']:.0f} FPS average" + (f", {last['low']:.0f} 1% low" if last.get("low") else "") +
                              (f" at {last['tdp']} W" if last.get("tdp") else "") + f" for {fmt_duration(last['dur'])}", "muted"))
                buttons.append(("SHARE MY SETTINGS", lambda: self.share_settings(key, name), "normal"))
            cards.append({"id": "play", "title": "FROM YOUR PLAY", "lines": lines, "buttons": buttons})
        if self.cfg["pcgw_info"]:
            st = self.pcgw.get(key, {"status": "loading"})
            data = st.get("data") or {}
            if st["status"] == "ok":
                items = data["items"]
                lines = [("   ·   ".join(f"{a}: {v}" for a, v in items[i:i + 3]), "text") for i in range(0, len(items), 3)]
                tip = self.support_tip(items)
                if tip:
                    lines.append((tip, "accent"))
                cards.append({"id": "pcgw", "title": "WHAT THIS GAME SUPPORTS", "lines": lines,
                              "buttons": [("PCGAMINGWIKI", lambda u=data["url"]: systools.open_target(u), "normal")]})
            elif st["status"] in ("loading", "offline"):
                cards.append({"id": "pcgw", "title": "WHAT THIS GAME SUPPORTS", "buttons": [],
                              "lines": [("Checking PCGamingWiki…" if st["status"] == "loading" else
                                         "Couldn't reach PCGamingWiki right now", "muted")]})
        return cards

    def support_tip(self, items):
        d = {a: v.lower() for a, v in items}
        up = d.get("Upscalers", "")
        if "fsr" in up or "xess" in up:
            return "Tip: use the game's own FSR/XeSS instead of RSR: it looks sharper, and keep the game at the screen's resolution"
        if d.get("Frame generation") in ("no", "false"):
            return "No built-in frame generation: AMD Fluid Motion Frames (below) can add it"
        if not up:
            return "No upscaler listed: set a lower resolution in the game and turn on RSR below"
        return ""

    def share_settings(self, key, name):
        """Open a Deck Verified report with what Vanta knows already filled in (you check it and submit)."""
        ses = [s_ for s_ in self.sessions_for(key, name) if s_.get("fps")]
        t = self.tune()
        last = ses[0] if ses else {}
        appid = key.split(":", 1)[1] if key.startswith("steam:") else (self.dv.get(key) or {}).get("appid")
        tdp = last.get("tdp") or t.get("tdp")
        cap = last.get("cap") or ((t.get("amd") or {}).get("frtc_fps") if (t.get("amd") or {}).get("frtc") else None)
        summary = ", ".join(x for x in (f"{tdp} W" if tdp else "", f"{last['fps']:.0f} FPS avg" if last.get("fps") else "",
                                       f"capped at {cap}" if cap else "") if x) or "My settings"
        notes = f"Average {last['fps']:.0f} FPS" + (f", 1% low {last['low']:.0f}" if last.get("low") else "") + \
            (f" over {fmt_duration(last['dur'])}" if last.get("dur") else "") if last else ""
        url = systools.dv_share_url(name, appid, self.preset_gen(), summary, tdp, cap, last.get("fps"), last.get("w"),
                                    notes=notes)
        systools.open_target(url)
        self.show_toast("Opened a pre-filled report: add your in-game settings, then submit")

    def card_buttons(self, card, w):
        """Lay the card's buttons out in rows that fit: [(x offset, width, button)], rows."""
        k = self.k
        f = self.font(12 * k, True)
        out, x, row = [], 0.0, 0
        for b in card["buttons"]:
            bw = max(110 * k, self.measure(f, b[0]) + 40 * k)
            if x and x + bw > w - 32 * k:
                x, row = 0.0, row + 1
            out.append((x, row, bw, b))
            x += bw + 10 * k
        return out, (row + 1 if card["buttons"] else 0)

    def card_height(self, card, w):
        k = self.k
        ls = self.font(13 * k).metrics("linespace")
        n = sum(len(self.wrap(tx, self.font(13 * k), w - 32 * k)) for tx, _ in card["lines"])
        _, rows = self.card_buttons(card, w)
        return 50 * k + n * ls + card.get("extra", 0) + (rows * 48 * k + 10 * k if rows else 10 * k)

    def draw_card(self, card, x0, y, x1, sid):
        T, k = self.t, self.k
        h = self.card_height(card, x1 - x0)
        f = self.font(13 * k)
        ls = f.metrics("linespace")
        self.rr(x0, y, x1, y + h, 14 * k, T["panel2"])
        self.text(x0 + 16 * k, y + 26 * k, card["title"], self.font(13 * k, True), T["accent"], anchor="w")
        yy = y + 46 * k
        for tx, col in card["lines"]:
            for ln in self.wrap(tx, f, x1 - x0 - 32 * k):
                self.text(x0 + 16 * k, yy, ln, f, T[col] if col in T else T["text"])
                yy += ls
        if card.get("paint"):
            card["paint"](x0 + 16 * k, yy + 4 * k, x1 - 16 * k)
        lay, rows = self.card_buttons(card, x1 - x0)
        for i, (bx, row, bw, (label, fn, style)) in enumerate(lay):
            by = y + h - 10 * k - (rows - row) * 48 * k
            self.button(f"card_{card['id']}_{i}", x0 + 16 * k + bx, by, x0 + 16 * k + bx + bw, by + 38 * k, label, fn, style=style,
                        size=12 * k, sid=sid)
        return h

    def community_for(self, key):
        d = self.dv.get(key)
        if not d or d["status"] != "ok":
            return []
        return systools.community_presets(d["data"], self.preset_gen(), self.tdp_max)

    def tune(self):
        key = self.tune_target[0] if self.tune_target else None
        return dict(self.cfg["game_tune"].get(key, {})) if key else {}

    def save_tune(self, t):
        key = self.tune_target[0]
        gt = dict(self.cfg["game_tune"])
        clean = {k: v for k, v in t.items() if v not in (None, {}, "")}
        if clean.get("amd") == {}:
            clean.pop("amd")
        if clean and clean != {"preset": "custom"}:
            gt[key] = clean
        else:
            gt.pop(key, None)
        self.cfg["game_tune"] = gt
        self.request_draw()

    def tune_set(self, field, value):
        t = self.tune()
        t[field] = value
        t["preset"] = "custom" if t.get("preset") else None
        self.save_tune(t)

    def tune_cycle(self, field, options, d):
        cur = self.tune().get(field)
        cur = tuple(cur) if isinstance(cur, list) else cur
        opts = [tuple(o) if isinstance(o, list) else o for o in options]
        i = opts.index(cur) if cur in opts else 0
        v = opts[(i + d) % len(opts)]
        self.tune_set(field, list(v) if isinstance(v, tuple) else v)

    def amd_cycle(self, feat, d):
        t = self.tune()
        amd = dict(t.get("amd") or {})
        order = [None, True, False]
        cur = amd.get(feat)
        nxt = order[(order.index(cur) + d) % 3 if cur in order else 0]
        if nxt is None:
            amd.pop(feat, None)
            for pname, _, _ in systools.AMD_PARAMS.get(feat, []):
                amd.pop(f"{feat}_{pname}", None)
        else:
            amd[feat] = nxt
            if nxt:
                for pname, _, default in systools.AMD_PARAMS.get(feat, []):
                    amd.setdefault(f"{feat}_{pname}", default)
        t["amd"] = amd
        t["preset"] = "custom" if t.get("preset") else None
        self.save_tune(t)

    def amd_param(self, feat, pname, d):
        t = self.tune()
        amd = dict(t.get("amd") or {})
        k = f"{feat}_{pname}"
        default = next(dv for pn, _, dv in systools.AMD_PARAMS[feat] if pn == pname)
        lo, hi, step = {"sharp": (0, 100, 5), "res": (50, 90, 5), "min": (10, 144, 5), "max": (10, 144, 5), "fps": (20, 144, 5)}[pname]
        rng = ((self.amd_state or {}).get(feat) or {}).get("range")
        if rng:
            lo, hi = max(lo, rng[0]), min(hi, rng[1]) if rng[1] else hi
        amd[k] = max(lo, min(hi, amd.get(k, default) + step * d))
        t["amd"] = amd
        self.save_tune(t)

    def retry_amd(self):
        """Start AMD's settings library over and read again (the RETRY button)."""
        self.amd_state = None
        self.show_toast("Checking AMD settings again…")

        def work():
            ok = systools.ADLX.restart()
            state = systools.ADLX.read() if ok else {}
            self.add_log("TOOL", "AMD settings: " + (f"ready on {systools.ADLX.gpu_name or 'the Radeon GPU'}" if state else
                                                      f"still unavailable: {systools.ADLX.error} [{systools.ADLX.detail}]"))
            self.call(lambda: (setattr(self, "amd_state", state), self.request_draw()))
        self.background(work)
        self.request_draw()

    def preset_gen(self):
        g = self.cfg["preset_gen"]
        if g in ("go1", "go2"):
            return g
        return "go2" if self.device.get("variant") == "go2" else "go1"

    def find_preset(self, name):
        return systools.find_preset(name, self.preset_gen())

    def apply_preset(self, preset):
        t = {"preset": preset["id"], "preset_gen": preset.get("gen", self.preset_gen())}
        for f in ("tdp", "hz", "res"):
            if preset.get(f):
                t[f] = preset[f]
        if t.get("tdp"):
            t["tdp"] = min(t["tdp"], self.tdp_max)
        if preset.get("amd"):
            t["amd"] = dict(preset["amd"])
        if preset.get("community"):
            t["preset_title"] = preset["title"]
            t["preset_src"] = preset["source"][1]
        self.save_tune(t)
        self.add_log("TOOL", f"{self.tune_target[1]}: applied the {preset['title']} preset")
        self.show_toast(f"{preset['title']} preset saved for this game")
        self.buzz()

    def set_preset_gen(self, g):
        self.cfg["preset_gen"] = g
        self.show_toast(f"Recommended presets: {systools.GENS[g]}")
        self.request_draw()

    def reset_tune(self):
        key = self.tune_target[0]
        self.confirm(f"rt_{key}", lambda: (self.save_tune({}), self.show_toast("Back to default for this game")),
                     "Tap again to clear this game's settings")

    def tune_label(self, key, name):
        t = self.cfg["game_tune"].get(key) or self.cfg["game_tune"].get(name.lower())
        if t:
            if str(t.get("preset", "")).startswith("dv:"):
                return "⚙ COMMUNITY PRESET"
            p = systools.preset_by_id(t.get("preset"), self.preset_gen())
            return f"⚙ {p['title'].upper()}" if p else "⚙ CUSTOM"
        return "⚙ PRESET READY" if self.find_preset(name) else "⚙ GAME SETTINGS"

    # -------------------------------------------------------------- mini monitor
    def ensure_overlay(self):
        if self.cfg["overlay"] and not self.overlay:
            try:
                self.overlay = MiniMonitor(self)
                self.overlay.update()
            except Exception as ex:
                self.overlay = None
                self.add_log("FAIL", f"Mini monitor: {ex}")

    def toggle_overlay(self):
        on = not self.cfg["overlay"]
        self.cfg["overlay"] = on
        if on:
            self.ensure_overlay()
        elif self.overlay:
            self.overlay.destroy()
            self.overlay = None
        self.show_toast("Mini monitor " + ("on" if on else "off"))
        self.buzz()

    # -------------------------------------------------------------- PC, games & files
    def load_battery_static(self):
        self.batt_static = {}

        def work():
            data = systools.battery_static() or {}
            self.call(lambda: (setattr(self, "batt_static", data), self.log_battery(data), self.request_draw()))

        self.background(work)

    def end_task(self):
        if not self.procs:
            return
        pid, name, _ = self.procs[min(self.sel, len(self.procs) - 1)]
        if pid == os.getpid() or name.lower() in systools.END_TASK_PROTECT:
            self.show_toast(f"Windows needs {name}, it can't be closed here")
            return

        def do():
            ok = systools.end_process(pid, name)
            self.add_log("TRIM", f"{name}: {'closed' if ok else 'could not be closed'}")
            self.show_toast(f"Closed {name}" if ok else f"Couldn't close {name}")
            self.refresh_procs()
            self.request_draw()

        self.confirm(f"end_{pid}", do, f"Tap END TASK again to close {name}. Unsaved work is lost.")

    def set_proc_sort(self, how):
        self.cfg["proc_sort"] = how
        self.refresh_procs()
        self.set_off("procs", 0)
        self.request_draw()

    def load_list(self, which):
        if which in self.list_loading:
            return
        self.list_loading.add(which)

        def work():
            data = {"steam": systools.steam_games, "files": systools.big_files, "dupes": systools.find_duplicates}[which]()
            if which == "steam":
                sizes = {g[0]: systools.shader_cache(g[0])[1] for g in data}
                self.call(lambda: setattr(self, "shader_sizes", sizes))

            def done():
                setattr(self, {"steam": "steam", "files": "bigfiles", "dupes": "dupes"}[which], data)
                self.list_loading.discard(which)
                self.request_draw()

            self.call(done)

        self.background(work)

    def set_clean_view(self, view):
        self.clean_view = view
        if view == "steam" and self.steam is None:
            self.load_list("steam")
        elif view == "files" and self.bigfiles is None:
            self.load_list("files")
        elif view == "dupes" and self.dupes is None:
            self.load_list("dupes")
        self.focus_id = None
        self.request_draw()

    def uninstall_game(self, appid, name):
        self.confirm(f"un_{appid}", lambda: (systools.open_target(f"steam://uninstall/{appid}"),
                                              self.add_log("CLEAN", f"Asked Steam to uninstall {name}")),
                     f"Tap again: Steam will ask to uninstall {name}")

    def delete_big_file(self, path):
        name = os.path.basename(path)

        def do():
            size = 0
            try:
                size = os.path.getsize(path)
            except OSError:
                pass
            if systools.recycle(path):
                self.bigfiles = [f for f in (self.bigfiles or []) if f[0] != path]
                self.add_log("CLEAN", f"Moved {name} to the Recycle Bin ({fmt_bytes(size)})")
                self.show_toast(f"{name} is in the Recycle Bin")
                self.buzz()
            else:
                self.show_toast(f"Couldn't delete {name} (in use?)")
            self.request_draw()

        self.confirm(f"del_{path}", do, f"Tap DELETE again to move {name} to the Recycle Bin")

    # -------------------------------------------------------------- profiles, display, battery events
    def apply_profile(self, pid, source="USER"):
        if self.preview_blocks("profile"):
            return
        if self.profile_busy:
            self.show_toast("Still switching, hold on…")
            return
        self.profile_busy = True
        name = next(p[1] for p in systools.PROFILES if p[0] == pid)
        legion = self.device["legion"]

        def work():
            changed = systools.apply_profile(pid, legion)

            def done():
                self.profile_busy = False
                self.cfg["profile"] = pid
                what = ", ".join(changed) if changed else "nothing needed changing"
                self.add_log("TOOL" if source == "USER" else "AUTO", f"Profile {name}: {what}")
                self.show_toast(f"{name} profile on")
                self.buzz()
                if self.hidden and self.tray and source != "USER":
                    self.tray.notify(f"{name} profile on")
                if self.tools is not None:
                    self.load_tools()

            self.call(done)

        self.background(work)
        self.request_draw()

    def set_refresh(self, hz):
        if systools.set_display_mode(hz=hz):
            self.add_log("TOOL", f"Refresh rate: {hz} Hz")
            self.show_toast(f"{hz} Hz")
        else:
            self.show_toast("Couldn't change the refresh rate")
        if self.tools is not None:
            self.tools["display"] = systools.display_modes()
        self.request_draw()

    def set_resolution(self, size):
        w, h = size
        cur = (self.tools or {}).get("display") or {}
        if systools.set_display_mode(w, h, cur.get("hz")):
            self.add_log("TOOL", f"Resolution: {w} × {h}")
            self.show_toast(f"{w} × {h}")
        else:
            self.show_toast("Couldn't change the resolution")
        if self.tools is not None:
            self.tools["display"] = systools.display_modes()
        self.request_draw()

    def power_events(self):
        b = self.batt
        if not b:
            return
        if self.last_ac is not None and b["ac"] != self.last_ac:
            target = self.cfg["profile_ac"] if b["ac"] else self.cfg["profile_battery"]
            self.add_log("AUTO", "Plugged in" if b["ac"] else "Unplugged")
            self.fire("plugged" if b["ac"] else "unplugged")
            if target:
                self.apply_profile(target, "AUTO")
        self.last_ac = b["ac"]
        pct = int(b["remaining_mwh"] * 100 / max(1, b["full_mwh"]))
        limit = self.cfg["batt_alert"]
        if limit and b["discharging"] and pct <= limit and not self.batt_alerted:
            self.batt_alerted = True
            left = b["remaining_mwh"] / abs(b["rate_mw"]) * 3600 if b.get("rate_mw") else None
            msg = f"Battery at {pct}%" + (f": about {fmt_duration(left)} left at this rate" if left else "") + ". Plug in soon."
            self.add_log("AUTO", msg)
            if self.game:
                self.nudge(f"Battery at {pct}%", (f"About {fmt_duration(left)} left at this rate. " if left else "") +
                           ("Plug in, or set a battery goal in Quick settings." if not self.cfg["batt_goal"] else "Plug in soon."))
            else:
                self.show_toast(msg)
                self.push_event(f"Battery at {pct}%", msg)
            if self.tray:
                self.tray.notify(msg)
            if self.cfg["rumble"] and self.pad_on:
                self.pad.rumble(0.6, 220)
                self.root.after(400, lambda: self.pad.rumble(0.6, 220))
        elif self.batt_alerted and (not b["discharging"] or pct > limit + 5):
            self.batt_alerted = False

    def auto_clean_tick(self):
        days = self.cfg["auto_clean_days"]
        if not days or self.busy or self.game or time.time() - self.cfg["last_auto_clean"] < days * 86400:
            return
        cats = [c for c in self.clean_selection() if c != "recycle"]  # never empty the Recycle Bin by itself
        if not cats:
            return
        self.cfg["last_auto_clean"] = time.time()

        def work():
            total = 0
            for cid in cats:
                try:
                    total += systools.clean_category(cid)
                except Exception:
                    pass

            def done():
                self.disk_freed += total
                self.add_stat("disk", total)
                self.add_stat("cleanups", 1)
                self.add_log("CLEAN", f"Scheduled clean-up freed {fmt_bytes(total)}")
                if self.hidden and self.tray and total > 100 * 1048576:
                    self.tray.notify(f"Scheduled clean-up freed {fmt_bytes(total)}")
                self.clean_sizes = {}

            self.call(done)

        self.background(work)

    # -------------------------------------------------------------- 3.3 features
    @property
    def tdp_max(self):
        return 35 if self.device["variant"] == "go2" else 30

    def step_tdp(self, d):
        self.cfg["tdp"] = max(5, min(self.tdp_max, self.cfg["tdp"] + d))
        self.request_draw()

    def apply_tdp(self):
        if self.tdp_busy:
            return
        if not self.cfg["tdp_ack"] and not self.is_armed("tdp"):
            self.confirm("tdp", lambda: None, "Experimental: tap APPLY again to set a custom TDP")
            return
        self.armed = None
        self.tdp_busy = True
        w = self.cfg["tdp"]

        def work():
            ok = systools.set_tdp(w, self.tdp_max)
            now = systools.get_tdp()
            th = systools.get_thermal_mode()

            def done():
                self.tdp_busy = False
                if self.tools is not None:
                    self.tools.update(tdp=now, thermal=th)
                if ok:
                    self.cfg["tdp_ack"] = True
                    self.cfg["profile"] = ""
                    self.add_log("TOOL", f"Custom TDP: {w} W" + (f" (reads back {now} W)" if now is not None and now != w else ""))
                    self.show_toast(f"TDP set to {w} W")
                    self.buzz()
                else:
                    self.add_log("FAIL", "Custom TDP: the firmware didn't accept it")
                    self.show_toast("Couldn't set the TDP on this firmware")
                self.request_draw()

            self.call(done)

        self.background(work)
        self.request_draw()

    def toggle_charge_limit(self):
        if self.charge_busy or self.charge_limit is None:
            return
        want = not self.charge_limit
        self.charge_busy = True

        def work():
            ok = systools.set_charge_limit(want)
            now = systools.get_charge_limit()

            def done():
                self.charge_busy = False
                self.charge_limit = now if now is not None else (want if ok else self.charge_limit)
                msg = ("Battery will stop charging at about 80%" if want else "Battery charges to 100% again") if ok \
                    else "Couldn't change the charge limit"
                self.add_log("TOOL" if ok else "FAIL", msg)
                self.show_toast(msg)
                self.request_draw()

            self.call(done)

        self.background(work)
        self.request_draw()

    def set_brightness(self, pct):
        self.brightness = pct
        self.background(lambda: systools.set_brightness(pct) or self.call(lambda: self.show_toast("Couldn't change brightness")))
        self.request_draw()

    def get_presentmon(self):
        if self.pm_busy:
            return

        def go():
            self.pm_busy = True

            def work():
                try:
                    tag = systools.download_presentmon()
                    msg, ok = f"PresentMon {tag} downloaded. FPS shows in the mini monitor during games.", True
                except Exception as ex:
                    msg, ok = f"Couldn't download PresentMon: {ex}", False

                def done():
                    self.pm_busy = False
                    if ok:
                        self.cfg["fps_counter"] = True
                    self.add_log("TOOL" if ok else "FAIL", msg)
                    self.show_toast("FPS counter ready" if ok else "Download failed, see the log")
                    self.request_draw()

                self.call(done)

            self.background(work)
            self.request_draw()

        self.confirm("pm", go, "Tap again to download PresentMon (Intel, free, about 1 MB)")

    def toggle_fps(self):
        if not systools.presentmon_installed():
            self.get_presentmon()
            return
        self.cfg["fps_counter"] = not self.cfg["fps_counter"]
        if self.cfg["fps_counter"] and self.game and not self.fps:
            try:
                self.fps = systools.FpsReader(self.game["pid"])
            except Exception as ex:
                self.add_log("FAIL", f"FPS counter: {ex}")
        elif not self.cfg["fps_counter"] and self.fps:
            self.fps.stop()
            self.fps, self.fps_stats = None, None
        self.request_draw()

    def toggle_close_app(self, name):
        lst = list(self.cfg["close_list"])
        low = [n.lower() for n in lst]
        if name.lower() in low:
            lst.pop(low.index(name.lower()))
        else:
            lst.append(name)
        self.cfg["close_list"] = lst
        self.request_draw()

    def cycle_game_profile(self, key, d=1):
        order = [""] + [p[0] for p in systools.PROFILES] + (["custom"] if self.device["legion"] else [])
        gp = dict(self.cfg["game_profiles"])
        cur = gp.get(key, "")
        nxt = order[(order.index(cur) + d) % len(order) if cur in order else 0]
        if nxt:
            gp[key] = nxt
        else:
            gp.pop(key, None)
        self.cfg["game_profiles"] = gp
        self.request_draw()

    def profile_label(self, pid):
        if pid == "custom":
            return f"TDP {self.cfg['tdp']} W"
        return next((p[1] for p in systools.PROFILES if p[0] == pid), "Default")

    def leak_tick(self):
        if not self.cfg["leak_alert"]:
            return
        now = time.time()
        procs = list_processes()[:40]
        alive = set()
        for pid, name, ws in procs:
            alive.add(pid)
            h = self.leak.setdefault(pid, deque(maxlen=45))
            h.append((now, ws))
            low = name.lower()
            if pid in self.leak_warned or (self.game and pid == self.game["pid"]) or low in BOOST_PROTECT or low in SYSTEM_APPS:
                continue
            window = [w for t, w in h if now - t <= 1800]
            if now - h[0][0] >= 1200 and ws > 1.5 * 1024 ** 3 and ws - min(window) > 1024 ** 3 and ws >= max(window) * 0.95:
                self.leak_warned.add(pid)
                msg = f"{name} grew {fmt_bytes(ws - min(window))} in {fmt_duration(now - h[0][0])} and keeps growing. Restarting it may stop stutter."
                self.add_log("AUTO", msg)
                self.show_toast(f"{name} keeps using more memory")
                if self.tray and (self.hidden or self.game):
                    self.tray.notify(msg)
        for pid in list(self.leak):
            if pid not in alive:
                self.leak.pop(pid, None)

    def delete_dupes(self, group):
        size, files = group
        extra = files[1:]  # keep the oldest copy

        def do():
            gone = sum(1 for path, _ in extra if systools.recycle(path))
            self.dupes = [g for g in (self.dupes or []) if g is not group]
            self.add_log("CLEAN", f"Moved {gone} duplicate(s) of {os.path.basename(files[0][0])} to the Recycle Bin ({fmt_bytes(size * gone)})")
            self.show_toast(f"Freed {fmt_bytes(size * gone)}")
            self.buzz()
            self.request_draw()

        self.confirm(f"dup_{files[0][0]}", do, f"Tap again: keeps the oldest copy, moves {len(extra)} to the Recycle Bin")

    def save_report(self):
        if self.report_busy:
            return
        self.report_busy = True
        snap = {"settings": dict(self.cfg.data), "log": list(self.log), "device": self.device, "winver": self.winver,
                "tools": dict(self.tools or {}), "batt": self.batt, "batt_static": self.batt_static, "power": self.power,
                "startup": [(i["name"], i["source"], i["enabled"]) for i in (self.startup_items or [])],
                "mem": (self.status.ullTotalPhys, self.status.ullAvailPhys), "installed": self.installed,
                "cpu": self.cpu, "gpu": self.gpu, "admin": self.admin}

        def work():
            lines = [f"Vanta {VERSION} report, {time.strftime('%Y-%m-%d %H:%M')}", "",
                     f"Device: {snap['device']['name']} ({snap['device']['variant'] or 'not a Legion Go'})",
                     f"Windows: {snap['winver']}", f"Administrator: {snap['admin']}",
                     f"RAM: {fmt_bytes(snap['mem'][0])} usable, {fmt_bytes(snap['mem'][1])} available, {fmt_bytes(snap['installed'])} installed",
                     f"CPU: {snap['cpu']}%   GPU: {snap['gpu']}%", f"Power: {snap['power']}", f"Battery: {snap['batt']}",
                     f"Battery details: {snap['batt_static']}", f"Display: {systools.display_modes()}",
                     f"Power mode: {systools.get_power_mode()}", f"Settings tweaks: {systools.read_tweaks()}",
                     f"AMD settings: {'ready' if systools.ADLX.available() else 'not available'} ({systools.ADLX.gpu_name or '-'}) "
                     f"{systools.ADLX.error} [{systools.ADLX.detail}]",
                     f"Drives: {[(d, fmt_bytes(t), fmt_bytes(f)) for d, t, f in systools.drives()]}", "", "Startup items:"]
            lines += [f"  {'on ' if on else 'off'} {n} ({src})" for n, src, on in snap["startup"]] or ["  (open the Startup tab to include)"]
            lines += ["", "Settings:", json.dumps({k: v for k, v in snap["settings"].items() if k != "sessions"}, indent=2), "", "Log:"]
            lines += [f"  {ts} [{tag}] {msg}" for ts, tag, msg in snap["log"]]
            folder = systools.known_folder("b4bfcc3a-db2c-424c-b029-7fe99a87c641") or os.path.expanduser("~")
            path = os.path.join(folder, f"Vanta report {time.strftime('%Y-%m-%d %H%M')}.txt")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
                ok = True
            except OSError:
                ok = False

            def done():
                self.report_busy = False
                if ok:
                    self.add_log("TOOL", f"Saved report to {path}")
                    self.show_toast("Report saved to your Desktop")
                    systools.show_in_explorer(path)
                else:
                    self.show_toast("Couldn't save the report")

            self.call(done)

        self.background(work)

    def toggle_portable(self):
        on = not os.path.exists(PORTABLE_FLAG)
        if set_portable(on, self.cfg.data):
            self.add_log("TOOL", "Portable mode " + ("on: settings are kept next to the exe" if on else "off"))
            self.show_toast("Portable mode " + ("on" if on else "off"))
        else:
            self.show_toast("This folder isn't writable (move the exe somewhere else first)")
        self.request_draw()

    # -------------------------------------------------------------- settings
    LEGION_ROWS = {"#LEGION BUTTONS & LIGHTS", "legion_buttons", "legion_l", "legion_l_hold", "legion_r", "legion_r_hold",
                   "back_page", "btntest_page", "auto_tdp", "auto_tdp_target", "rgb_mode", "rgb_color", "rgb_brightness", "ls_keep_closed",
                   "preset_gen", "preview_legion"}

    def settings_items(self):
        rows = self._settings_items()
        if getattr(self.legion, "pid", None) in systools.NEW_FW_PIDS:  # lights use commands Vanta won't send to this firmware
            rows = [r for r in rows if r[0] not in ("rgb_mode", "rgb_color", "rgb_brightness")]
        if self.device["legion"]:
            return rows
        if not IS_GO:
            rows = [r for r in rows if r[0] != "preview_legion"]
        return [r for r in rows if r[0] not in self.LEGION_ROWS or (IS_GO and r[0] == "preview_legion")]

    def _settings_items(self):
        c = self.cfg
        su = "…" if self.startup is None else ("ON" if self.startup else "OFF")
        on = lambda key: "ON" if c[key] else "OFF"
        corners = {"tl": "Top left", "tr": "Top right", "bl": "Bottom left", "br": "Bottom right"}
        pname = lambda pid: next((p[1] for p in systools.PROFILES if p[0] == pid), "Don't switch")
        H = lambda title: ("#" + title, title, "", "header", "")
        pre = [H("PREVIEW"),
               ("preview_safe", "Don't change this PC", "Skips anything that changes settings, files, apps or startup", "toggle",
                on("preview_safe")),
               ("preview_legion", "Show Legion Go features", "Restart Preview to apply", "toggle", on("preview_legion")),
               ("preview_samples", "Sample games in the library", "", "toggle", on("preview_samples"))] if PREVIEW else []
        return pre + [
            H("HUB & GAMES"),
            ("start_tab", "Open on", "The tab you see when the app starts", "step", dict(TABS).get(c["start_tab"], "PLAY").title()),
            ("focus_on_play", "Focus mode when you press Play", "", "toggle", on("focus_on_play")),
            ("game_recap", "Recap after each game", "Time, FPS, battery and power, compared with last time", "toggle",
             on("game_recap")),
            ("break_every", "Break reminders", "A nudge over your game every so often", "step",
             f"Every {c['break_every']} min" if c["break_every"] else "Off"),
            ("daily_limit", "Daily play time limit", "A heads-up 10 minutes before, and when you reach it", "step",
             fmt_duration(c["daily_limit"] * 60) if c["daily_limit"] else "Off"),
            ("focus_off_after", "End focus mode when the game closes", "", "toggle", on("focus_off_after")),
            ("return_to_hub", "Come back to the hub after a game", "Hold View + Menu to open it during a game", "toggle", on("return_to_hub")),
            ("hub_minimize", "Minimize the hub while you play", "", "toggle", on("hub_minimize")),
            ("game_priority", "Games get more CPU time", "Above-normal priority when a game starts (safe for audio and input)",
             "toggle", on("game_priority")),
            ("game_quiet", "Quiet while gaming", "No notifications and no Windows Update downloads while a game runs",
             "toggle", on("game_quiet")),
            ("preset_gen", "Recommended presets for", {"auto": "Matches this device", "go1": "Ryzen Z1 Extreme · 2560×1600 · up to 30 W",
             "go2": "Ryzen Z2 Extreme · 1920×1200 OLED · up to 35 W"}[c["preset_gen"]], "step",
             {"auto": "Auto · " + systools.GENS[self.preset_gen()].split(" · ")[0], "go1": "Gen 1", "go2": "Gen 2"}[c["preset_gen"]]),
            ("community_presets", "Community presets from Deck Verified",
             "Player-reported settings for the game you open (deckverified.games)", "toggle",
             "ON" if c["community_presets"] else "OFF"),
            ("backup", "Back up settings", "Presets, mappings, rules, themes and lists to Documents\\Vanta backups (keys left out)",
             "link", "Back up"),
            ("restore", "Restore the latest backup", self.latest_backup_text(), "link", "Restore"),
            ("theme_code", "Share my theme as a code", "Copies a short VANTA1-… code a friend can paste", "link", "Copy"),
            ("theme_paste", "Use a theme code", "Copy a friend's code, then tap here", "link", "Paste"),
            ("lang", "Language", "Menus, tabs and main buttons (more text over time)", "step", LANG_NAMES[c["lang"]]),
            ("layout", "Layout", "Console home with sections up top, a side rail, or the classic tabs", "step",
             LAYOUTS.get(c["layout"], "Console home")),
            ("motion", "Smooth animations", "Pages slide in, the tab highlight and focus ring glide", "toggle", on("motion")),
            ("light_footprint", "Light footprint", "Low priority + Windows efficiency mode while you play or Vanta is hidden; "
             "frees image memory after 2 minutes hidden", "toggle", on("light_footprint")),
            ("pcgw_info", "What each game supports (PCGamingWiki)", "Upscalers, frame generation, HDR and more on game pages", "toggle",
             on("pcgw_info")),
            ("deal_alerts", "Free game and deal alerts", "Epic's free games and sales on your public Steam wishlist", "toggle",
             on("deal_alerts")),
            ("ra_user", "RetroAchievements username", c["ra_user"] or "Copy your username, then tap here", "link",
             c["ra_user"] or "Paste"),
            ("ra_key", "RetroAchievements web API key", "Set" if c["ra_key"] else "From retroachievements.org/settings: copy it, then tap here",
             "link", "Set" if c["ra_key"] else "Paste"),
            ("art_fetch", "Download missing game art", "Covers and backdrops from Steam's store, for every store's games",
             "toggle", on("art_fetch")),
            ("sgdb_key", "SteamGridDB key (covers)", "Set" if c["sgdb_key"] else "Free key from steamgriddb.com → Preferences → API. "
             "Copy it, then tap here", "link", ""),
            ("steam_key", "Steam Web API key (achievements)", "Set" if c["steam_key"] else "Free key from steamcommunity.com/dev/apikey. "
             "Copy it, then tap here", "link", ""),
            ("rom_add", "Add a ROM folder", f"{len(c['rom_dirs'])} folder(s) · " +
             ("RetroArch found" if self.retroarch else "needs RetroArch installed"), "link", ""),
            ("rom_clear", "Forget ROM folders", "Removes the folders from the library, not the files", "link", ""),
            ("save_auto", "Back up saves when a game starts", "Uses Ludusavi (free); backups go to Documents", "toggle", on("save_auto")),
            H("FOCUS MODE"),
            ("focus_min", "Focus: minimize open windows", "", "toggle", on("focus_min")),
            ("focus_eco", "Focus: efficiency mode for background apps", "Low priority and power saving, like Task Manager. "
             "Discord, OBS and Spotify are left alone", "toggle", on("focus_eco")),
            ("focus_close", "Focus: close my picked apps", "The list on the Gaming tab", "toggle", on("focus_close")),
            ("focus_boost", "Focus: free RAM (Game Boost)", "", "toggle", on("focus_boost")),
            ("focus_restore_windows", "Bring windows back when focus ends", "", "toggle", on("focus_restore_windows")),
            H("AUTO OPTIMIZE"),
            ("auto", "Auto optimize", "Runs while the app is open or in the tray", "toggle", on("auto")),
            ("free_below_mb", "When free memory drops below", "", "step", "Off" if c["free_below_mb"] <= 0 else f"{c['free_below_mb']:,} MB"),
            ("used_above", "Or when memory in use is above", "", "step", "Off" if c["used_above"] <= 0 else f"{c['used_above']}%"),
            ("interval_min", "Or every", "", "step", "Off" if c["interval_min"] <= 0 else f"{c['interval_min']} min"),
            ("cooldown_s", "Wait at least", "Between automatic runs", "step", fmt_duration(c["cooldown_s"])),
            ("action", "Auto runs", "", "step", ACTIONS[c["action"]][0]),
            H("WHILE GAMING"),
            ("game_boost_auto", "Game Boost when a game starts", "Watches for full-screen games", "toggle", on("game_boost_auto")),
            ("game_perf_auto", "Performance modes while gaming",
             "Best performance" + (" + Legion Performance" if self.device["legion"] else "") + " when a game starts", "toggle", on("game_perf_auto")),
            ("game_restore", "Restore modes when the game closes", "Puts back what you had before", "toggle", on("game_restore")),
            H("POWER & BATTERY"),
            ("profile_battery", "When you unplug, switch to", "A profile from Game Tools", "step", pname(c["profile_battery"])),
            ("profile_ac", "When you plug in, switch to", "", "step", pname(c["profile_ac"])),
            ("batt_alert", "Low battery alert", "Toast, tray note and a double buzz", "step", f"at {c['batt_alert']}%" if c["batt_alert"] else "Off"),
            ("auto_clean_days", "Clean caches automatically", "Uses your Clean Up picks, never the Recycle Bin", "step",
             {0: "Off", 1: "Daily", 7: "Weekly", 14: "Every 2 weeks", 30: "Monthly"}.get(c["auto_clean_days"], "Off")),
            H("MINI MONITOR"),
            ("overlay", "Mini monitor", "RAM, CPU and battery on top of your game", "toggle", on("overlay")),
            ("overlay_corner", "Mini monitor position", "", "step", corners.get(c["overlay_corner"], "Top right")),
            ("overlay_size", "Mini monitor size", "", "step", f"{c['overlay_size']}%"),
            ("overlay_opacity", "Mini monitor opacity", "", "step", f"{c['overlay_opacity']}%"),
            ("pad_combo", "View + Menu shortcuts", "Press: mini monitor. Hold: open the hub. Works during games", "toggle", on("pad_combo")),
            H("APP"),
            ("leak_alert", "Warn about apps that keep growing", "Spots memory leaks that cause stutter after a while", "toggle", on("leak_alert")),
            ("portable", "Portable mode", "Keep settings next to the exe, e.g. on a USB stick", "toggle",
             "ON" if os.path.exists(PORTABLE_FLAG) else "OFF"),
            ("sort_caps_auto", "Sort captures by game", "After each game, copy its screenshots and clips into Pictures › Vanta › Captures",
             "toggle", on("sort_caps_auto")),
            ("game_colors", "Game colors", "The accent color follows the art of the game you've picked", "toggle", on("game_colors")),
            ("theme_daily", "Theme of the day", "A different theme each morning, dark or light like the one you have now", "toggle",
             on("theme_daily")),
            ("animations", "Animated themes", "Moving backgrounds pause when the app is in the background" +
             (f"  ·  running at {self.fx_fps:.0f} fps" if self.t.get("fx") and getattr(self, "fx_fps", 0) else ""),
             "step", {"on": "Always", "ac": "Plugged in only", "off": "Off"}.get(c["animations"], "Always")),
            ("follow_windows", "Follow Windows light/dark mode", f"Uses {c['light_theme']} when Windows is in light mode", "toggle", on("follow_windows")),
            ("startup", "Start Vanta with Windows", "In the tray, no admin prompt, works on battery", "toggle", su),
            H("LEGION BUTTONS & LIGHTS"),
            ("legion_buttons", "Listen to the Legion L and R buttons", "So Legion Space can stay closed", "toggle", on("legion_buttons")),
            ("legion_l", "Legion L press", "", "step", LEGION_ACTIONS.get(c["legion_l"], "Nothing")),
            ("legion_l_hold", "Legion L hold", "", "step", LEGION_ACTIONS.get(c["legion_l_hold"], "Nothing")),
            ("legion_r", "Legion R press", "", "step", LEGION_ACTIONS.get(c["legion_r"], "Nothing")),
            ("legion_r_hold", "Legion R hold", "", "step", LEGION_ACTIONS.get(c["legion_r_hold"], "Nothing")),
            ("xinput_restore", "Restore Xbox controller mode", self.xinput_text(), "link", ""),
            ("btntest_page", "Legion button test", "Buttons not responding? Finds where your controllers report Legion L and R",
             "link", ""),
            ("back_page", "Back buttons", "Map Y1, Y2, Y3, M2 and M3 to keys or actions, per game", "link", ""),
            ("auto_tdp", "Auto TDP", "Lowest wattage that holds your FPS target (uses the FPS counter)", "toggle", on("auto_tdp")),
            ("auto_tdp_target", "Auto TDP target", "", "step", f"{c['auto_tdp_target']} FPS"),
            ("frametime_graph", "Frame-time graph in the mini monitor", "Spikes are stutters", "toggle", on("frametime_graph")),
            ("rgb_mode", "Controller lights", "Set whenever the controllers connect", "step", RGB_MODE_LABELS.get(c["rgb_mode"], "Leave as is")),
            ("rgb_color", "Light color", "", "step", c["rgb_color"].upper()),
            ("rgb_brightness", "Light brightness", "", "step", f"{c['rgb_brightness']}%"),
            H("DISCORD"),
            ("discord_page", "Discord", "Rich Presence, game recaps, screenshots, voice buttons", "link", ""),
            ("ls_keep_closed", "Keep Legion Space closed", "Stops Lenovo's button service so the Legion buttons only open Vanta. "
             "Opening Legion Space from Vanta (Tools > Shortcuts) turns the service back on until Vanta's next start", "toggle",
             on("ls_keep_closed")),
            ("ls_service", "Lenovo's button service (DAService)", "Stop it so Legion buttons never open Legion Space. Legion Space's own "
             "button shortcuts stop too; Vanta's keep working", "link",
             {"running": "Running · tap to stop", "stopped": "Stopped · tap to restore", "disabled": "Stopped · tap to restore",
              None: "Not installed", "?": "Checking…"}.get(self.ls_service, "?")),
            ("padmouse", "Controller as mouse & keyboard", "Right stick moves the mouse; hold View + Menu to get back to Vanta",
             "toggle", "ON" if (self.padmouse and self.padmouse.on) else "OFF"),
            ("padmouse_layout", "  · Layout", "Desktop: sticks mouse/scroll, A click. Game: WASD on the left stick", "step",
             systools.PAD_LAYOUTS[c["padmouse_layout"]]["name"]),
            ("padmouse_sens", "  · Mouse speed", "How fast the stick moves the pointer", "step", f"{c['padmouse_sens']}%"),
            ("fan_full", "Full fan speed", "Maximum cooling (loud). Uses the same Lenovo setting as Handheld Daemon", "toggle",
             "ON" if self.fan_full else "…" if self.fan_state_loading() else "OFF"),
            ("detach_profile", "Detached-controller profile", "Switch settings when the controllers come off, restore when they go back",
             "toggle", on("detach_profile")),
            ("detach_scale", "  · Bigger touch targets", "Vanta's UI 25% bigger while detached", "toggle", on("detach_scale")),
            ("detach_pointer_off", "  · Motion controls off", "Stops the gyro pointer while detached", "toggle", on("detach_pointer_off")),
            ("detach_tdp", "  · Wattage", "When not in a game", "step", f"{c['detach_tdp']} W" if c["detach_tdp"] else "Keep"),
            ("detach_hz", "  · Refresh rate", "60 Hz saves battery on a desk", "step", f"{c['detach_hz']} Hz" if c["detach_hz"] else "Keep"),
            H("PHONE REMOTE"),
            ("phone_input", "Phone touchpad & keyboard", "Lets the phone app move the mouse and type on this PC", "toggle",
             on("phone_input")),
            ("remote_on", "Phone remote", self.remote_text(), "toggle", on("remote_on")),
            ("remote_pin", "New PIN", "Phones need the new PIN after this", "link", ""),
            H("SYNC"),
            ("sync_on", "Sync settings through OneDrive", self.sync_status or "Themes, game settings, lists, mappings and keys, "
             "between Vanta and Vanta Preview on your PCs", "toggle", on("sync_on")),
            ("sync_now", "Sync now", "", "link", ""),
            H("CONSOLE & FEEL"),
            ("theme_editor", "Make your own theme", "Pick colors, a gradient and a background effect", "link", ""),
            ("console_mode", "Console mode", "Open fullscreen on the hub at sign-in, like a console (needs Start with Windows)",
             "toggle", on("console_mode")),
            ("osk_style", "On-screen keyboard", "", "step", "Vanta (controller)" if c["osk_style"] == "vanta" else "Windows"),
            ("ui_sounds", "UI sounds", "Soft clicks when you move and select", "toggle", on("ui_sounds")),
            ("sound_volume", "UI sound volume", "", "step", f"{c['sound_volume']}%"),
            ("haptics", "Controller haptics", "Rumble when you select things", "step", ["Off", "Light", "Medium", "Strong"][c["haptics"]]),
            ("wallpaper", "Wallpaper", os.path.basename(c["wallpaper"]) if c["wallpaper"] else "Use one of your pictures behind Vanta",
             "link", ""),
            ("wallpaper_rm", "Remove wallpaper", "Back to the theme's own background" if c["wallpaper"] else "No wallpaper set",
             "link", ""),
            ("wallpaper_dim", "Wallpaper dimming", "So text stays readable", "step", f"{c['wallpaper_dim']}%"),
            H("UPDATES"),
            ("update_repo", "Update source", c["update_repo"] or "Paste a GitHub repo (owner/name) that publishes Vanta.exe", "link", ""),
            ("update_check", "Check for updates", self.update_text(), "link", ""),
            ("update_auto", "Check when Vanta starts", "", "toggle", on("update_auto")),
            H("WINDOW & FEEL"),
            ("close_to_tray", "Close button hides to tray", "" if self.tray else "Tray isn't available", "toggle", on("close_to_tray")),
            ("rumble", "Controller rumble", "Short buzz when something finishes", "toggle", on("rumble")),
            ("stick_nav", "Left stick moves around", "Turn off if the selection drifts by itself: the D-pad still works", "toggle",
             on("stick_nav")),
            ("ui_scale", "Size of everything", "", "step", f"{c['ui_scale']}%"),
        ]

    def adjust(self, key, d):
        c = self.cfg
        if key == "overlay":
            self.toggle_overlay()
            return
        if key == "portable":
            self.toggle_portable()
            return
        if key == "leak_alert":
            c[key] = not c[key]
            self.request_draw()
            return
        if key == "legion_buttons":
            c[key] = not c[key]
            self.start_legion_buttons() if c[key] else (self.stop_legion_buttons(), self.give_back_buttons())
            self.request_draw()
            return
        if key in ("legion_l", "legion_r", "legion_l_hold", "legion_r_hold"):
            i = LEGION_ACTION_ORDER.index(c[key]) if c[key] in LEGION_ACTION_ORDER else 0
            c[key] = LEGION_ACTION_ORDER[(i + d) % len(LEGION_ACTION_ORDER)]
            self.request_draw()
            return
        if key == "rgb_mode":
            order = list(RGB_MODE_LABELS)
            c[key] = order[(order.index(c[key]) + d) % len(order) if c[key] in order else 0]
            self.apply_rgb(quiet=True)
            self.request_draw()
            return
        if key == "rgb_color":
            i = RGB_COLORS.index(c[key]) if c[key] in RGB_COLORS else -1
            self.set_rgb(color=RGB_COLORS[(i + d) % len(RGB_COLORS)])
            return
        if key == "rgb_brightness":
            self.set_rgb(brightness=max(10, min(100, c[key] + 10 * d)))
            return
        if key == "start_tab":
            i = TAB_IDS.index(c[key]) if c[key] in TAB_IDS else 0
            c[key] = TAB_IDS[(i + d) % len(TAB_IDS)]
            self.request_draw()
            return
        if key in ("preview_safe", "preview_legion", "preview_samples"):
            c[key] = not c[key]
            if key == "preview_samples":
                self.load_library()
            if key == "preview_safe":
                self.show_toast("Preview won't change this PC" if c[key] else "Careful: Preview can now change this PC")
            self.request_draw()
            return
        if key == "discord_page":
            self.open_discord()
            return
        if key == "pointer_mode":
            order = list(POINTER_MODES)
            self.set_pointer_mode(order[(order.index(c[key]) + d) % len(order)] if c[key] in order else "off")
            return
        if key == "pointer_sens":
            c[key] = max(25, min(300, c[key] + 25 * d))
            self.pointer and self.pointer.refresh_settings()
            self.request_draw()
            return
        if key in ("gyro_hold", "pointer_invert_x", "pointer_invert_y"):
            c[key] = not c[key]
            self.pointer and self.pointer.refresh_settings()
            self.request_draw()
            return
        if key in ("pointer_side", "pointer_axis"):
            c[key] = {"right": "left", "left": "right", "yaw": "roll", "roll": "yaw"}[c[key]]
            if self.pointer and key == "pointer_side":
                mode = c["pointer_mode"]
                self.set_pointer_mode("off")
                self.set_pointer_mode(mode)
            self.pointer and self.pointer.refresh_settings()
            self.request_draw()
            return
        if key == "theme_editor":
            self.open_editor()
            return
        if key == "remote_on":
            c[key] = not c[key]
            self.start_remote() if c[key] else self.stop_remote()
            self.request_draw()
            return
        if key == "remote_pin":
            c["remote_pin"] = ""
            if self.remote:
                self.stop_remote()
                self.start_remote()
            self.request_draw()
            return
        if key == "sync_on":
            c[key] = not c[key]
            if c[key]:
                self.sync_tick(force=True)
            self.request_draw()
            return
        if key == "sync_now":
            self.sync_tick(force=True)
            return
        if key == "community_presets":
            c[key] = not c[key]
            if not c[key]:
                self.dv.clear()
            self.request_draw()
            return
        if key == "preset_gen":
            opts = ["auto", "go1", "go2"]
            c[key] = opts[(opts.index(c[key]) + (1 if d >= 0 else -1)) % 3]
            self.request_draw()
            return
        if key == "art_fetch":
            c[key] = not c[key]
            if c[key]:
                self.sgdb_started = False
                self.fetch_covers()
            self.request_draw()
            return
        if key == "game_quiet":
            c[key] = not c[key]
            self.request_draw()
            return
        if key == "padmouse":
            self.toggle_padmouse()
            return
        if key == "padmouse_layout":
            opts = list(systools.PAD_LAYOUTS)
            c[key] = opts[(opts.index(c[key]) + d) % len(opts)]
            if self.padmouse and self.padmouse.on:
                self.toggle_padmouse(c[key], quiet=True)
            self.request_draw()
            return
        if key == "padmouse_sens":
            c[key] = max(30, min(250, c[key] + 10 * d))
            if self.padmouse:
                self.padmouse.sens = c[key] / 100
            self.request_draw()
            return
        if key == "fan_full":
            self.toggle_full_fan()
            return
        if key == "backup":
            self.backup_now()
            return
        if key == "restore":
            self.restore_latest()
            return
        if key == "theme_code":
            self.copy_theme_code()
            return
        if key == "theme_paste":
            self.use_theme_code()
            return
        if key == "motion":
            c[key] = not c[key]
            self.motions.clear()
            self.request_draw()
            return
        if key == "lang":
            opts = list(LANG_NAMES)
            c[key] = opts[(opts.index(c[key]) + d) % len(opts)]
            self.fonts.clear()
            self._mcache.clear()
            self.request_draw()
            return
        if key == "ls_keep_closed":
            c[key] = not c[key]
            if c[key]:
                self.take_over_buttons()
            else:
                self.give_back_buttons()
            self.request_draw()
            return
        if key == "ls_service":
            if self.ls_service in (None, "?"):
                return
            stop = self.ls_service == "running"

            def work():
                ok, prev = systools.set_button_service(not stop, self.cfg["ls_svc_modes"])
                st = systools.button_service_state()

                def done():
                    if stop and ok:
                        self.cfg["ls_svc_modes"] = {**prev, **self.cfg["ls_svc_modes"]}
                        self.cfg["ls_svc_off"] = True
                    elif ok:
                        self.cfg["ls_svc_off"], self.cfg["ls_svc_modes"] = False, {}
                    self.ls_service = st
                    msg = ("Stopped Lenovo's button service: Legion buttons won't open Legion Space" if stop else
                           "Lenovo's button service is back on") if ok else "Couldn't change the service (Vanta needs administrator)"
                    self.add_log("BOOT", msg)
                    self.show_toast(msg)
                    self.request_draw()
                self.call(done)
            if stop:
                self.confirm("ls_svc", lambda: self.background(work), "Tap again to stop Lenovo's button service (you can restore it here)")
            else:
                self.background(work)
            return
        if key == "light_footprint":
            c[key] = not c[key]
            if not c[key] and self.eco:
                self.eco = False
                systools.set_self_efficiency(False)
            self.request_draw()
            return
        if key in ("pcgw_info", "deal_alerts", "detach_profile", "detach_scale", "detach_pointer_off"):
            c[key] = not c[key]
            if key == "deal_alerts" and c[key]:
                self.check_deals(force=True)
            if key == "detach_profile" and not c[key] and self.detach_saved is not None:
                self.detach_restore()
            self.request_draw()
            return
        if key == "detach_tdp":
            opts = [0] + list(range(8, self.tdp_max + 1, 2))
            c[key] = opts[(opts.index(c[key]) + d) % len(opts) if c[key] in opts else 0]
            self.request_draw()
            return
        if key == "detach_hz":
            opts = [0, 60, 90, 120, 144]
            c[key] = opts[(opts.index(c[key]) + d) % len(opts) if c[key] in opts else 0]
            self.request_draw()
            return
        if key in ("ra_user", "ra_key"):
            try:
                text = self.root.clipboard_get().strip()
            except tk.TclError:
                text = ""
            ok = re.fullmatch(r"[A-Za-z0-9_.-]{2,32}", text) if key == "ra_user" else re.fullmatch(r"[A-Za-z0-9]{20,64}", text)
            if ok:
                c[key] = text
                self.ra = None
                self.show_toast("Saved")
            else:
                self.show_toast("Copy it first, then tap here")
            self.request_draw()
            return
        if key in ("sgdb_key", "steam_key"):
            try:
                text = self.root.clipboard_get().strip()
            except tk.TclError:
                text = ""
            ok = re.fullmatch(r"[0-9A-Fa-f]{32}", text) if key == "steam_key" else re.fullmatch(r"[0-9A-Za-z]{20,64}", text)
            if ok:
                c[key] = text
                self.show_toast("Key saved")
                if key == "sgdb_key":
                    self.sgdb_started = False
                    self.fetch_covers()
                else:
                    self.ach = {}
            else:
                self.show_toast("Copy the key first, then tap here")
            self.request_draw()
            return
        if key == "frametime_graph":
            c[key] = not c[key]
            self.request_draw()
            return
        if key in ("console_mode", "ui_sounds", "update_auto"):
            c[key] = not c[key]
            if key == "console_mode" and c[key] and self.startup is False:
                self.show_toast("Also turn on Start Vanta with Windows for console mode")
            if key == "ui_sounds" and c[key]:
                self.background(lambda: systools.prepare_sounds(c["sound_volume"] / 100))
            self.request_draw()
            return
        if key == "osk_style":
            c[key] = "windows" if c[key] == "vanta" else "vanta"
            self.request_draw()
            return
        if key == "sound_volume":
            c[key] = max(5, min(100, c[key] + 5 * d))
            vol = c[key] / 100
            self.background(lambda: (systools.prepare_sounds(vol), systools.play_sound("select")))
            self.request_draw()
            return
        if key == "haptics":
            c[key] = (c[key] + d) % 4
            self.buzz()
            self.request_draw()
            return
        if key == "wallpaper":
            self.pick_wallpaper()
            return
        if key == "wallpaper_rm":
            c["wallpaper"] = ""
            self.wall_cache = None
            self.request_draw()
            return
        if key == "wallpaper_dim":
            c[key] = max(0, min(90, c[key] + 5 * d))
            self.wall_cache = None
            self.request_draw()
            return
        if key == "update_repo":
            try:
                text = self.root.clipboard_get()
            except tk.TclError:
                text = ""
            repo = systools.parse_repo(text)
            if repo:
                c[key] = repo
                self.show_toast(f"Updates will come from {repo}")
            else:
                self.show_toast("Copy a GitHub link like github.com/you/vanta first")
            self.request_draw()
            return
        if key == "update_check":
            if self.update_info and self.update_info.get("newer"):
                self.install_update()
            else:
                self.check_updates()
            return
        if key == "rom_add":
            self.add_rom_folder()
            return
        if key == "rom_clear":
            c["rom_dirs"] = []
            self.load_library()
            self.show_toast("ROM folders removed from the library")
            return
        if key == "save_auto":
            if not c[key] and not systools.ludusavi_installed():
                self.get_ludusavi(lambda: (c.__setitem__("save_auto", True), self.request_draw()))
                return
            c[key] = not c[key]
            self.request_draw()
            return
        if key == "btntest_page":
            self.open_page("btntest")
            return
        if key == "xinput_restore":
            self.confirm("xinput", self.restore_xinput, "Tap again to switch the controllers back to Xbox (XInput) mode")
            return
        if key == "back_page":
            self.open_back_buttons()
            return
        if key == "auto_tdp":
            self.toggle_auto_tdp()
            return
        if key == "auto_tdp_target":
            i = AUTO_TDP_TARGETS.index(c[key]) if c[key] in AUTO_TDP_TARGETS else 3
            c[key] = AUTO_TDP_TARGETS[(i + d) % len(AUTO_TDP_TARGETS)]
            self.request_draw()
            return
        if key in ("discord_presence", "discord_idle", "discord_recaps"):
            c[key] = not c[key]
            if key == "discord_presence":
                if c[key] and not c["discord_app_id"]:
                    self.show_toast("Paste your Application ID to finish")
                self.start_discord() if c[key] else self.stop_discord()
            self.presence_tick(once=True)
            self.request_draw()
            return
        if key == "game_priority":
            c[key] = not c[key]
            self.request_draw()
            return
        if key in ("focus_on_play", "focus_off_after", "return_to_hub", "hub_minimize", "focus_min", "focus_eco", "focus_close",
                   "focus_boost", "focus_restore_windows"):
            c[key] = not c[key]
            self.request_draw()
            return
        if key in ("auto", "game_boost_auto", "close_to_tray", "rumble", "game_perf_auto", "game_restore", "pad_combo", "follow_windows"):
            c[key] = not c[key]
            if key == "follow_windows":
                self.light_mode = systools.windows_light_mode()
                self.retheme()
            if key == "auto":
                self.add_log("AUTO", "Auto optimize " + ("armed." if c["auto"] else "disarmed."))
            if key == "game_boost_auto" and c[key]:
                self.boosted = {foreground_pid()}
        elif key == "free_below_mb":
            c[key] = max(0, min(16384, c[key] + 256 * d))
        elif key == "used_above":
            v = c[key]
            v = (50 if d > 0 else 0) if v == 0 or (v == 50 and d < 0) else v + 5 * d
            c[key] = max(0, min(95, v))
        elif key == "interval_min":
            c[key] = max(0, min(240, c[key] + 5 * d))
        elif key == "cooldown_s":
            c[key] = max(30, min(1800, c[key] + 30 * d))
        elif key == "action":
            i = AUTO_ACTIONS.index(c[key]) if c[key] in AUTO_ACTIONS else 0
            c[key] = AUTO_ACTIONS[(i + d) % len(AUTO_ACTIONS)]
        elif key == "ui_scale":
            c[key] = max(70, min(170, c[key] + 10 * d))
            self.fonts.clear()
        elif key in ("profile_battery", "profile_ac"):
            order = [""] + [p[0] for p in systools.PROFILES]
            c[key] = order[(order.index(c[key]) + d) % len(order) if c[key] in order else 0]
        elif key in ("break_every", "daily_limit"):
            order = self.BREAK_OPTS if key == "break_every" else self.LIMIT_OPTS
            c[key] = order[(order.index(c[key]) + d) % len(order) if c[key] in order else 0]
        elif key == "batt_alert":
            order = [0, 10, 15, 20, 25, 30]
            c[key] = order[(order.index(c[key]) + d) % len(order) if c[key] in order else 2]
        elif key == "auto_clean_days":
            order = [0, 1, 7, 14, 30]
            c[key] = order[(order.index(c[key]) + d) % len(order) if c[key] in order else 0]
            if c[key]:
                c["last_auto_clean"] = time.time()
        elif key == "layout":
            order = list(LAYOUTS)
            c[key] = order[(order.index(c[key]) + d) % len(order) if c[key] in order else 0]
            self.rail_ind = self.bar_ind = None
        elif key == "animations":
            order = ["on", "ac", "off"]
            c[key] = order[(order.index(c[key]) + d) % 3 if c[key] in order else 0]
        elif key == "overlay_corner":
            order = ["tl", "tr", "bl", "br"]
            c[key] = order[(order.index(c[key]) + d) % 4 if c[key] in order else 1]
        elif key == "overlay_size":
            c[key] = max(70, min(200, c[key] + 10 * d))
        elif key == "overlay_opacity":
            c[key] = max(40, min(100, c[key] + 5 * d))
            if self.overlay:
                self.overlay.apply_opacity()
        elif key == "startup":
            if self.startup is None:
                return
            want = not self.startup
            self.startup = None

            def work():
                ok = set_startup(want)
                self.jobq.put(("startup_state", startup_enabled()))
                if not ok:
                    self.call(lambda: self.show_toast("Couldn't change the startup task"))

            self.background(work)
        if self.overlay and key.startswith("overlay"):
            self.overlay.update()
        self.request_draw()

    def set_theme(self, name):
        if self.cfg["follow_windows"] and not THEMES[name]["dark"]:
            self.cfg["light_theme"] = name
            if not self.light_mode:
                self.show_toast(f"{name} is used when Windows is in light mode")
        else:
            self.cfg["theme"] = name
        self.retheme()

    def set_accent(self, color):
        self.cfg["accent"] = color
        self.retheme()

    def retheme(self):
        self._theme_cache = (None, None)
        self.fx = None
        self.c.configure(bg=self.t["bg"])
        self.apply_titlebar()
        if self.tray:
            self.tray.retheme(self.t)
        if self.overlay:
            self.overlay.update()
        self.request_draw()

    def cycle_theme(self, d=1):
        i = THEME_NAMES.index(self.cfg["theme"]) if self.cfg["theme"] in THEME_NAMES else 0
        self.set_theme(THEME_NAMES[(i + d) % len(THEME_NAMES)])
        self.show_toast(f"Theme: {self.cfg['theme']}")

    def open_page(self, name):
        self.page_from = None
        self.page = None if self.page == name else name
        self.focus_id = None
        self.request_draw()

    # -------------------------------------------------------------- input
    def active_regions(self):
        layer = "page" if self.page else "main"
        return [r for r in self.regions if r["layer"] == layer]

    def hit(self, x, y, kind=None):
        for r in reversed(self.active_regions()):
            if r["x0"] <= x < r["x1"] and r["y0"] <= y < r["y1"] and (kind is None or r["kind"] == kind):
                return r
        return None

    def on_press(self, e):
        self.last_input = time.time()
        self.focus_visible = False
        self.kinetic = None
        r = self.hit(e.x, e.y)
        s = self.hit(e.x, e.y, "scroll")
        sid = s["sid"] if s else None
        # touching a gliding list stops it, and that touch doesn't count as a tap
        a_ = self.anims.get(sid) if sid else None
        fast = a_ and ((a_["mode"] == "kinetic" and abs(a_["vel"]) > 250 * self.k) or
                       (a_["mode"] == "target" and abs(a_["target"] - self.scrolls[sid]["off"]) > 40 * self.k))
        grabbed = [sid] if fast else []
        if a_ and a_["mode"] != "spring":
            del self.anims[sid]
        if r and r.get("drag"):  # sliders take the drag instead of the scroll area
            sid = None
            r["drag"](e.x, False)
        if sid in self.anims:  # catch a list that is still springing back
            s_ = self.scrolls[sid]
            s_["off"] = max(0.0, min(s_["max"], s_["off"] + s_.get("over", 0.0)))
            s_["over"] = 0.0
            del self.anims[sid]
        self.press = {"x": e.x, "y": e.y, "r": r, "sid": sid, "moved": bool(sid in grabbed),
                      "off": self.scrolls.get(sid, {}).get("off", 0.0), "samples": [(time.perf_counter(), e.y)]}
        self.pressed = r["id"] if r and r["kind"] not in ("scroll", "panel") and sid not in grabbed else None
        self.draw_press()  # instant feedback: one overlay item, not a repaint of the screen

    def on_hover(self, e):
        self.last_input = time.time()
        """Mouse or trackpad over something tappable: it lights up a little (touch never hovers)."""
        if self.press:
            return
        try:  # a finger on the touchscreen also moves the mouse: touch never hovers, or the last tap would stay lit
            if (user32.GetMessageExtraInfo() & 0xFFFFFF00) == 0xFF515700:
                self.set_hover(None)
                return
        except Exception:
            pass
        r = self.hit(e.x, e.y)
        self.set_hover(r["id"] if r and r["kind"] not in ("scroll", "panel") else None)

    def set_hover(self, rid):
        if rid != self.hovered:
            self.hovered = rid
            self.draw_hover()

    def on_motion(self, e):
        p = self.press
        if not p:
            return
        dy, dx = e.y - p["y"], e.x - p["x"]
        if p["r"] and p["r"].get("drag"):
            p["moved"] = True
            p["r"]["drag"](e.x, False)
            self.request_draw()
            return
        if not p["moved"] and max(abs(dx), abs(dy)) > 12 * self.k:
            p["moved"] = True
            self.pressed = None
            self.c.delete("pressfx")
        if p["moved"] and p["sid"]:
            self.drag_to(p["sid"], p["off"] - dy)
            p["samples"] = (p["samples"] + [(time.perf_counter(), e.y)])[-8:]
            self.request_draw(self.scope_for(p["sid"]))

    def on_release(self, e):
        p, self.press, self.pressed = self.press, None, None
        self.c.delete("pressfx")
        if self.hovered:
            self.set_hover(None)  # after a tap the spot under the finger shouldn't stay lit
        if not p:
            return
        page_before = self.page
        r = p["r"]
        if r and r.get("drag"):
            r["drag"](e.x, True)
            self.request_draw()
            return
        if p["moved"]:
            sid = p["sid"]
            if sid:
                s_ = self.scrolls.get(sid, {})
                vel = 0.0
                now = time.perf_counter()
                recent = [(t_, y_) for t_, y_ in p["samples"] if now - t_ < 0.1]
                if len(recent) >= 2 and now - recent[-1][0] < 0.06:
                    (t0, y0), (t1, y1) = recent[0], recent[-1]
                    if t1 - t0 > 0.004:
                        vel = -(y1 - y0) / (t1 - t0)
                if s_.get("over"):
                    self.anims[sid] = {"mode": "spring"}
                    self.run_anims()
                elif abs(vel) > 60 * self.k:
                    self.start_kinetic(sid, max(-9000 * self.k, min(9000 * self.k, vel)))
            self.request_draw(self.scope_for(sid))
            return
        elif r:
            if r.get("tap_y"):
                r["tap_y"](p["y"])
            elif r.get("tap"):
                r["tap"]()
        elif self.page:
            if self.page == "welcome":
                self.cfg["welcomed"] = True
            self.page = None
        # a tap inside an open page only needs that page redrawn (the full path runs if the page or theme changed)
        self.request_draw("page" if self.page and self.page == page_before and not self.in_panel else "all")

    def on_wheel(self, e):
        s = self.hit(e.x, e.y, "scroll")
        if s:
            self.scroll_by(s["sid"], -e.delta / 120 * 150 * self.k)

    def on_key(self, e):
        ks, ch = e.keysym, (e.char or "").lower()
        if ks.lower() == "k" and e.state & 0x4:
            return self.open_find(keyboard=False)
        if e.state & 0x4 and self.page not in ("find",) and not getattr(self, "_note_edit", None) and self.on_ctrl_key(ks):
            return
        if ks == "F1":
            return self.open_page("help") if self.page != "help" else None
        if self.page == "find" and not ks in ("Up", "Down", "Tab"):
            if ks == "BackSpace":
                self.find_q = self.find_q[:-1]
            elif ks == "Escape":
                return self.back()
            elif ks in ("Return", "KP_Enter"):
                cur, _ = self.current_focus()
                if cur and self.focus_visible:
                    return self.activate()
                res = self.find_results()
                if res and res[0][1]:
                    res[0][1][0][3]()
                return
            elif e.char and e.char.isprintable():
                self.find_q += e.char
            else:
                return
            self.set_off("find", 0)
            self.request_draw("page")
            return
        if self.page == "settings" and (self.set_typing or (e.char and e.char.isprintable() and e.char.strip()
                                                             and not e.state & 0x4)):
            # typing on a keyboard while settings are open searches them
            if ks == "BackSpace":
                self.set_query = self.set_query[:-1]
            elif ks in ("Return", "KP_Enter", "Escape"):
                self.set_typing = False
                if ks == "Escape":
                    self.set_query = ""
                self.osk and self.close_keyboard()
            elif e.char and e.char.isprintable():
                self.set_query += e.char
                self.set_typing = True
            else:
                self.set_typing = ks not in ("Up", "Down", "Tab") and self.set_typing
                if not self.set_typing:
                    return self.on_key(e)
            self.set_off("settings", 0)
            self.request_draw()
            return
        nav = {"Up": "up", "Down": "down", "Left": "left", "Right": "right"}
        if ks in nav:
            self.nav(nav[ks])
        elif ks in ("Return", "KP_Enter", "space"):
            self.activate()
        elif ks == "Escape":
            self.back()
        elif ks == "F11":
            self.toggle_fullscreen()
        elif ks in ("Prior", "Next"):
            self.page_list(-1 if ks == "Prior" else 1)
        elif ks == "Tab":
            self.step_tab(-1 if e.state & 1 else 1)
        elif self.page:
            return
        elif ch == "p" and self.tab == "play":
            self.play(self.selected_game())
        elif ch == "f":
            self.focus_toggle()
        elif ch == "o":
            self.run("all")
        elif ch == "b":
            self.run("boost")
        elif ch and ch in "123456":
            self.run(["workingsets", "standby", "standbylow", "modified", "filecache", "combine"][int(ch) - 1])
        elif ch == "t":
            self.run("trim")
        elif ch == "a":
            self.run("trimall")
        elif ch == "u":
            self.adjust("auto", 1)
        elif ch == "s":
            self.open_page("settings")
        elif ch == "c":
            self.cycle_theme()
        elif ch in ("h", "?"):
            self.open_page("help")
        elif ch == "l":
            self.open_page("log")
        elif ch == "q":
            self.quit()

    def on_pad(self, b):
        self.last_input = time.time()
        if self.hovered:
            self.set_hover(None)  # the controller's ring is the only highlight while you use it
        if self.tab == "home" and not self.page and b in ("x", "y"):
            if b == "x":
                g = self.home_game()
                g and self.play(g)
            else:
                self.open_find()
            return
        if self.tab == "play" and not self.page and b in ("x", "y"):
            if b == "x":
                self.play(self.selected_game())
            else:
                self.focus_toggle()
            return
        if b in ("up", "down", "left", "right"):
            self.nav(b)
        elif b == "a":
            self.activate()
        elif b == "b":
            self.back()
        elif b == "start":
            self.open_page("menu")
        elif b == "back":
            self.open_page("settings")
        elif self.page == "settings" and b in ("lb", "rb"):
            ids = [c_[0][0] for c_ in self.settings_categories()]
            i = ids.index(self.set_cat) if self.set_cat in ids else 0
            self.pick_settings_cat(ids[(i + (1 if b == "rb" else -1)) % len(ids)])
            self.focus_id = None
        elif self.page == "settings" and b == "y":
            self.settings_search()
        elif self.page and b in ("lt", "rt"):
            sid = next((r["sid"] for r in reversed(self.active_regions()) if r["kind"] == "scroll" and r["sid"] != "setcats"), None)
            if sid:
                self.scroll_by(sid, (1 if b == "rt" else -1) * self.scrolls[sid]["h"] * 0.8)
        elif self.page:
            return
        elif b in ("lb", "rb"):
            self.step_tab(-1 if b == "lb" else 1)
        elif b in ("lt", "rt"):
            if not self.step_subtab(-1 if b == "lt" else 1):
                self.page_list(-1 if b == "lt" else 1)
        elif b == "x":
            self.run("boost")
        elif b == "y":
            self.run("all")
        elif b == "ls":
            self.adjust("auto", 1)
        elif b == "rs":
            self.cycle_theme()

    def back(self):
        if self.page == "settings" and (self.set_query or self.set_typing or (self.set_drill and self.set_narrow)):
            return self.settings_back()
        if self.page:
            back_to = getattr(self, "page_from", None)
            self.page = back_to if back_to and back_to != self.page else None
            self.page_from = None
            self.focus_id = None
            self.request_draw()

    def current_focus(self):
        regs = [r for r in self.active_regions() if r["focus"]]
        for r in regs:
            if r["id"] == self.focus_id:
                return r, regs
        return None, regs

    def nav(self, d):
        self.sound("move")
        self.focus_visible = True
        cur, regs = self.current_focus()
        if not regs:
            return
        if cur is None:
            first = next((r for r in regs if r["id"] in ("home_play", f"g_{self.lib_sel}", "act_boost", "clean_go", "legion_btn")), None) or \
                    next((r for r in regs if not r["id"].startswith("tab_")), regs[0])
            self.focus_id = first["id"]
            self.request_draw()
            return
        if cur["id"] == "procs" and d in ("up", "down"):
            if not (d == "up" and self.sel == 0):
                self.select(self.sel + (1 if d == "down" else -1))
                return
        if cur.get("adjust") and d in ("left", "right"):
            cur["adjust"](1 if d == "right" else -1)
            return
        # rows inside a scroll area: scroll so the next row is drawn before searching
        sid = cur.get("sid")
        if sid and d in ("up", "down"):
            s = self.scrolls[sid]
            row_h = cur["y1"] - cur["y0"]
            if d == "down" and cur["y1"] + row_h > s["y0"] + s["h"]:
                self.set_off(sid, s["off"] + row_h * 1.1)
            elif d == "up" and cur["y0"] - row_h < s["y0"]:
                self.set_off(sid, s["off"] - row_h * 1.1)
            self._draw_quick() if self.in_panel else self.draw()
            cur, regs = self.current_focus()
            if cur is None:
                self.focus_id = None
                return self.nav(d)
        cx, cy = (cur["x0"] + cur["x1"]) / 2, (cur["y0"] + cur["y1"]) / 2
        best, best_score = None, None
        for r in regs:
            if r is cur:
                continue
            rx, ry = (r["x0"] + r["x1"]) / 2, (r["y0"] + r["y1"]) / 2
            dx, dy = rx - cx, ry - cy
            if d == "up" and dy >= -2 or d == "down" and dy <= 2 or d == "left" and dx >= -2 or d == "right" and dx <= 2:
                continue
            if d in ("up", "down"):
                overlap = r["x0"] < cur["x1"] and r["x1"] > cur["x0"]
                score = abs(dy) + (0 if overlap else abs(dx) * 2)
            else:
                overlap = r["y0"] < cur["y1"] and r["y1"] > cur["y0"]
                score = abs(dx) + (0 if overlap else abs(dy) * 2)
            if best_score is None or score < best_score:
                best, best_score = r, score
        if best:
            self.focus_id = best["id"]
            sc = self.scrolls.get(best.get("sid")) if best.get("sid") else None
            cut = sc and (best["y0"] <= sc["y0"] + 1 or best["y1"] >= sc["y0"] + sc["h"] - 1)
            if not cut and not self.in_panel:
                self.draw_focus_ring()  # nothing else changes: the ring just glides there (no repaint)
                return
        self.request_draw()

    def activate(self):
        self.focus_visible = True
        cur, _ = self.current_focus()
        if cur is None:
            self.nav("down")
        elif cur["id"] == "procs":
            self.run("trim")
        elif cur.get("tap"):
            page_before = self.page
            cur["tap"]()
            if self.page and self.page == page_before and not self.in_panel:
                self.request_draw("page")
                return
        self.request_draw()

    # -------------------------------------------------------------- scrolling
    @property
    def layer(self):
        return self.__dict__.get("_layer", "main")

    @layer.setter
    def layer(self, v):
        self._layer = v
        c = self.__dict__.get("c")
        if c is not None and hasattr(c, "layer_tag"):
            c.layer_tag = v

    def clip_to(self, y0, y1):
        """Clip drawing to a scrolling list's band until end_clip()."""
        self.c.clip = (y0, y1)

    def end_clip(self):
        self.c.clip = None

    def set_off(self, sid, off):
        s = self.scrolls.get(sid)
        if s:
            s["off"] = max(0.0, min(off, s["max"]))

    def scroll_area(self, sid, x0, y0, x1, y1, content_h, tap_y=None, focus=False):
        s = self.scrolls.setdefault(sid, {"off": 0.0})
        s.update(y0=y0, h=y1 - y0, max=max(0.0, content_h - (y1 - y0)), layer=self.layer)
        s["off"] = max(0.0, min(s["off"], s["max"]))
        self.regions.append({"id": sid, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "tap": None, "tap_y": tap_y,
                             "focus": focus, "adjust": None, "kind": "scroll", "sid": sid, "layer": self.layer})
        return s["off"] + s.get("over", 0.0)

    def scrollbar(self, sid, x, y0, h):
        s = self.scrolls.get(sid)
        if s and s["max"] > 0:
            k = self.k
            frac = h / (h + s["max"])
            over = abs(s.get("over", 0.0))
            sh = max(30 * k, h * frac - over)  # squashes while rubber-banding
            sy = y0 + (h - sh) * (s["off"] / s["max"])
            moving = sid in self.anims or bool(self.press and self.press.get("sid") == sid and self.press.get("moved"))
            self.rr(x - (5 if moving else 4) * k, sy, x, sy + sh, 2.5 * k, self.t["accent"] if moving else self.t["line"])

    def scope_for(self, sid):
        """Lists on an open page only need the page redrawn, not the hub underneath."""
        s = self.scrolls.get(sid) if sid else None
        if sid == "lib" and not self.page and not self.in_panel:
            return "lib"
        return "page" if self.page and not self.in_panel and (s is None or s.get("layer") == "page") else "all"

    def drag_to(self, sid, want):
        """Follow the finger; past either end the list stretches a little (rubber band)."""
        s = self.scrolls.get(sid)
        if not s:
            return
        lim = 140 * self.k
        if want < 0:
            s["off"], s["over"] = 0.0, -lim * (1 - math.exp(want / lim / 1.6))
        elif want > s["max"]:
            s["off"], s["over"] = s["max"], lim * (1 - math.exp(-(want - s["max"]) / lim / 1.6))
        else:
            s["off"], s["over"] = want, 0.0

    def scroll_by(self, sid, dy):
        """Eased scroll (mouse wheel, page keys, controller): glides to the new spot instead of jumping."""
        s = self.scrolls.get(sid)
        if not s:
            return
        a = self.anims.get(sid)
        base = a["target"] if a and a["mode"] == "target" else s["off"]
        self.scroll_to(sid, base + dy)

    def scroll_to(self, sid, target):
        s = self.scrolls.get(sid)
        if not s:
            return
        target = max(0.0, min(target, s["max"]))
        if abs(target - s["off"]) < 0.5:
            return
        if not self.cfg["smooth_scroll"]:
            self.set_off(sid, target)
            self.request_draw(self.scope_for(sid))
            return
        self.anims[sid] = {"mode": "target", "target": target}
        self.run_anims()

    def start_kinetic(self, sid, vel):
        if not self.cfg["smooth_scroll"]:
            return
        self.anims[sid] = {"mode": "kinetic", "vel": vel}
        self.run_anims()

    def run_anims(self):
        if not self.anim_on and self.anims:
            self.anim_on = True
            self._anim_last = time.perf_counter()
            self.root.after(1, self._anim_tick)

    def _anim_tick(self):
        now = time.perf_counter()
        dt = max(0.001, min(0.05, now - self._anim_last))
        self._anim_last = now
        scope = None
        for sid, a in list(self.anims.items()):
            s = self.scrolls.get(sid)
            if not s:
                del self.anims[sid]
                continue
            done = False
            if a["mode"] == "kinetic":
                nxt = s["off"] + a["vel"] * dt
                a["vel"] *= math.exp(-dt * 3.2)  # about 0.95 per 60 Hz frame
                if nxt < 0 or nxt > s["max"]:
                    s["off"] = 0.0 if nxt < 0 else s["max"]
                    s["over"] = max(-60 * self.k, min(60 * self.k, a["vel"] * 0.018))
                    a.clear()
                    a["mode"] = "spring"
                else:
                    s["off"] = nxt
                    done = abs(a["vel"]) < 20 * self.k
            elif a["mode"] == "target":
                s["off"] += (a["target"] - s["off"]) * (1 - math.exp(-dt * 16))
                if abs(a["target"] - s["off"]) < 0.6:
                    s["off"] = a["target"]
                    done = True
            elif a["mode"] == "spring":
                s["over"] = s.get("over", 0.0) * math.exp(-dt * 13)
                if abs(s["over"]) < 0.6:
                    s["over"] = 0.0
                    done = True
            if done:
                self.anims.pop(sid, None)
            sc = self.scope_for(sid)
            scope = sc if scope in (None, sc) else "all"
        if scope:
            self.request_draw(scope)
        if self.anims:
            self.root.after(8, self._anim_tick)
        else:
            self.anim_on = False

    def select(self, i):
        self.sel = max(0, min(i, len(self.procs) - 1))
        s = self.scrolls.get("procs")
        if s:
            row_h = s.get("row_h", 50 * self.k)
            top = self.sel * row_h
            if top < s["off"]:
                s["off"] = top
            elif top + row_h > s["off"] + s["h"]:
                s["off"] = top + row_h - s["h"]
            self.set_off("procs", s["off"])
        self.request_draw()

    def page_list(self, d):
        if self.tab != "memory":
            return
        s = self.scrolls.get("procs")
        rows = max(1, int(s["h"] // s.get("row_h", 50)) - 1) if s else 5
        self.select(self.sel + d * rows)

    def tap_proc(self, y):
        s = self.scrolls.get("procs")
        if s:
            i = int((y - s["y0"] + s["off"]) // s["row_h"])
            if 0 <= i < len(self.procs):
                self.sel = i
                self.request_draw()

    # -------------------------------------------------------------- drawing helpers
    def request_draw(self, scope="all"):
        # "page" redraws only an open page (the hub under it stays); anything else redraws everything
        if scope == "all" or self.draw_scope is None:
            self.draw_scope = "all" if scope == "all" else (self.draw_scope or scope)
        if not self.draw_pending:
            self.draw_pending = True
            # at most one frame every ~14 ms; input in between just updates the state the next frame shows
            wait = 0.014 - (time.perf_counter() - self._last_draw)
            if wait > 0.002:
                self.root.after(int(wait * 1000), self.draw)
            else:
                self.root.after_idle(self.draw)

    def region(self, rid, x0, y0, x1, y1, tap=None, focus=True, adjust=None, kind="button", sid=None):
        clip = getattr(self.c, "clip", None)
        if clip:  # only the on-screen part of a half-scrolled row can be tapped
            y0, y1 = max(y0, clip[0]), min(y1, clip[1])
            if y1 - y0 < 4:
                return
        self.regions.append({"id": rid, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "tap": tap, "tap_y": None, "focus": focus,
                             "adjust": adjust, "kind": kind, "sid": sid, "layer": self.layer})

    def rr(self, x0, y0, x1, y1, r, fill, outline="", width=1, stipple=""):
        r = max(0, min(r * self.t.get("round", 1), (x1 - x0) / 2, (y1 - y0) / 2))
        extra = {"stipple": stipple} if stipple and fill else {}
        if r < 1:
            return self.c.create_rectangle(x0, y0, x1, y1, fill=fill, outline=outline, width=width if outline else 0, **extra)
        rt = rb = r
        clip = getattr(self.c, "clip", None)
        if clip:
            if y1 <= clip[0] or y0 >= clip[1]:
                return None
            if y0 < clip[0] or y1 > clip[1]:
                # partly scrolled out: cut it at the edge, rounding off only the corners still on screen
                rt, rb = max(0.0, r - (clip[0] - y0)) if y0 < clip[0] else r, max(0.0, r - (y1 - clip[1])) if y1 > clip[1] else r
                y0, y1 = max(y0, clip[0]), min(y1, clip[1])
                rt, rb = min(rt, (y1 - y0) / 2), min(rb, (y1 - y0) / 2)
        pts = [x0 + rt, y0, x1 - rt, y0, x1, y0, x1, y0 + rt, x1, y1 - rb, x1, y1, x1 - rb, y1,
               x0 + rb, y1, x0, y1, x0, y1 - rb, x0, y0 + rt, x0, y0]
        if clip:
            self.c.clip = None
            try:
                return self.c.create_polygon(pts, smooth=True, fill=fill, outline=outline, width=width if outline else 0, **extra)
            finally:
                self.c.clip = clip
        if outline and not fill and width > 1.5:
            # rings (focus, selection, hover): true arcs and round joins, because a thick smoothed outline
            # spikes where its curves meet the straight edges
            arc = []
            for cx, cy, a0, rr_ in ((x1 - rt, y0 + rt, -90, rt), (x1 - rb, y1 - rb, 0, rb), (x0 + rb, y1 - rb, 90, rb),
                                     (x0 + rt, y0 + rt, 180, rt)):
                for j in range(7):
                    a_ = math.radians(a0 + j * 15)
                    arc += [cx + math.cos(a_) * rr_, cy + math.sin(a_) * rr_]
            return self.c.create_polygon(arc, fill="", outline=outline, width=width, joinstyle="round")
        return self.c.create_polygon(pts, smooth=True, fill=fill, outline=outline, width=width if outline else 0, **extra)

    def surface(self, x0, y0, x1, y1, r, fill):
        """A card or tile background in the current theme's style (solid, glass or outlined)."""
        T = self.t
        if T.get("glass"):
            # a fine dither reads as frosted glass on the high-density Legion Go screen
            return self.rr(x0, y0, x1, y1, r, fill, outline=mix(fill, T["text"], 0.12), width=max(1, self.k), stipple="gray75")
        if T.get("outline"):
            return self.rr(x0, y0, x1, y1, r, fill, outline=T["line"], width=max(1, self.k))
        if T.get("premium"):
            return self.rr(x0, y0, x1, y1, r, fill, outline=mix(fill, T["text"], 0.07), width=max(1, self.k))
        return self.rr(x0, y0, x1, y1, r, fill)

    def measure(self, font, text):
        # the cache lives on the font object itself (Tk font names can be reused once a font is freed)
        mc = font.__dict__.get("_vmc")
        if mc is None:
            mc = font.__dict__["_vmc"] = {}
        v = mc.get(text)
        if v is None:
            if len(mc) > 4000:
                mc.clear()
            v = mc[text] = font.measure(text)
        return v

    def fit(self, text, font, maxw):
        if maxw <= 0:
            return ""
        if self.measure(font, text) <= maxw:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.measure(font, text[:mid] + "…") <= maxw:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + "…" if lo else ""

    def text(self, x, y, s, font, fill, anchor="nw", maxw=None):
        if maxw is not None:
            s = self.fit(s, font, maxw)
        return self.c.create_text(x, y, text=s, font=font, fill=fill, anchor=anchor)

    def wrap(self, s, font, maxw):
        lines, line = [], ""
        for w in s.split():
            trial = (line + " " + w).strip()
            if self.measure(font, trial) > maxw and line:
                lines.append(line)
                line = w
            else:
                line = trial
        return lines + ([line] if line else [])

    def button(self, rid, x0, y0, x1, y1, label, tap, style="normal", badge="", focus=True, size=None, sid=None):
        T, k = self.t, self.k
        fill = {"normal": T["panel2"], "accent": T["accent"], "ghost": T["panel"], "danger": T["danger"]}[style]
        fg = T["accent_text"] if style == "accent" else "#ffffff" if style == "danger" else T["text"]
        ix0, iy0, ix1, iy1 = x0, y0, x1, y1
        if self.hover_fill == rid and self.pressed != rid:
            fill = mix(fill, "#ffffff" if style == "accent" else T["text"], 0.08 if style == "accent" else 0.06)
        if self.pressed == rid:
            fill = mix(fill, T["accent"] if style == "normal" else "#ffffff", 0.3)
            d_ = min(3 * k, (y1 - y0) * 0.06)  # pressed: sinks in a touch
            ix0, iy0, ix1, iy1 = x0 + d_, y0 + d_, x1 - d_, y1 - d_
        if T.get("premium"):
            if style == "accent" and self.pressed != rid:  # a soft glow around the main action
                self.rr(ix0 - 3 * k, iy0 - 3 * k, ix1 + 3 * k, iy1 + 3 * k, 15 * k, "", outline=mix(T["bg"], T["accent"], 0.35),
                        width=max(2, 3 * k))
            self.rr(ix0, iy0, ix1, iy1, 12 * k, fill, outline=mix(fill, T["text"], 0.08) if style in ("normal", "ghost") else "",
                    width=max(1, k))
        else:
            self.rr(ix0, iy0, ix1, iy1, 12 * k, fill, outline=T["line"] if style == "normal" else "", width=max(1, k))
        f = self.font(size or min(16 * k, (y1 - y0) * 0.36), True)
        self.text((x0 + x1) / 2, (y0 + y1) / 2, label, f, fg, anchor="center", maxw=x1 - x0 - (40 if badge and self.pad_on else 12) * k)
        if badge and self.pad_on:
            self.pad_badge(x1 - 16 * k, (y0 + y1) / 2, badge, 11 * k)
        self.region(rid, x0, y0, x1, y1, tap=tap, focus=focus, sid=sid)

    def segmented(self, rid, x0, y0, x1, y1, options, current, on_pick, busy=False):
        """A row of touch-sized choices; options = [(value, label)]."""
        T, k = self.t, self.k
        self.rr(x0, y0, x1, y1, 14 * k, T["panel2"])
        n = len(options)
        w = (x1 - x0 - 8 * k) / n
        longest = max(len(str(lbl)) for _, lbl in options) or 1
        f = self.font(min(15 * k, (y1 - y0) * 0.32, w / max(5.5, longest * 0.75)), True)
        for i, (val, label) in enumerate(options):
            bx0 = x0 + 4 * k + i * w
            bx1 = bx0 + w
            sel = val == current
            sid = f"{rid}_{val}"
            if sel or self.pressed == sid:
                fill = T["accent"] if sel else mix(T["panel2"], T["accent"], 0.3)
                self.rr(bx0 + 2 * k, y0 + 4 * k, bx1 - 2 * k, y1 - 4 * k, 11 * k, fill)
            fg = T["accent_text"] if sel else (T["muted"] if busy else T["text"])
            self.text((bx0 + bx1) / 2, (y0 + y1) / 2, label, f, fg, anchor="center", maxw=w - 10 * k)
            self.region(sid, bx0, y0, bx1, y1, tap=lambda v=val: on_pick(v))

    def toggle_switch(self, x1, cy, on, pending=False):
        T, k = self.t, self.k
        tw, th = 64 * k, 34 * k
        tx0 = x1 - tw
        fill = T["line"] if pending or on is None else T["accent"] if on else T["panel2"]
        self.rr(tx0, cy - th / 2, x1, cy + th / 2, th / 2, fill, outline=T["line"], width=max(1, k))
        kx = x1 - th / 2 if on else tx0 + th / 2
        r = th / 2 - 4 * k
        self.c.create_oval(kx - r, cy - r, kx + r, cy + r, fill=T["accent_text"] if on else T["muted"], outline="")
        return tw

    def checkbox(self, x0, cy, on):
        T, k = self.t, self.k
        s = 28 * k
        self.rr(x0, cy - s / 2, x0 + s, cy + s / 2, 7 * k, T["accent"] if on else T["panel2"], outline=T["line"], width=max(1, k))
        if on:
            self.c.create_line(x0 + s * 0.24, cy, x0 + s * 0.43, cy + s * 0.2, x0 + s * 0.78, cy - s * 0.22,
                               fill=T["accent_text"], width=max(2, 3 * k), capstyle="round", joinstyle="round")
        return s

    def spinner(self, cx, cy, r):
        a = (time.time() * 400) % 360
        self.c.create_arc(cx - r, cy - r, cx + r, cy + r, start=-a, extent=270, style="arc",
                          outline=self.t["accent"], width=max(2, r * 0.3))

    def pad_badge(self, cx, cy, letter, r):
        colors = {"A": "#3fb950", "B": "#f85149", "X": "#4c8dff", "Y": "#e3b341"}
        fill = colors.get(letter, mix(self.t["panel2"], self.t["text"], 0.3))
        self.c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline="")
        self.c.create_text(cx, cy, text=letter, font=self.font(r * (1.25 if len(letter) == 1 else 0.8), True),
                           fill="#ffffff" if letter in colors else text_on_hex(fill))

    def icon_button(self, rid, x0, y0, s, key, tap):
        T, k = self.t, self.k
        if T.get("premium"):  # quiet round buttons that light up when pressed
            fill = mix(T["panel2"], T["accent"], 0.35) if self.pressed == rid else \
                mix(T["panel2"], T["text"], 0.06) if self.hover_fill == rid else mix(T["bg"], T["panel"], 0.7)
            self.rr(x0 + 2 * k, y0 + 2 * k, x0 + s - 2 * k, y0 + s - 2 * k, (s - 4 * k) / 2, fill, outline=mix(fill, T["text"], 0.08),
                    width=max(1, k))
        else:
            fill = mix(T["panel2"], T["accent"], 0.3) if self.pressed == rid else T["panel2"]
            self.rr(x0, y0, x0 + s, y0 + s, 12 * k, fill)
        glyph, fallback = ICONS[key]
        if self.icon_family:
            self.c.create_text(x0 + s / 2, y0 + s / 2, text=glyph, font=self.font(s * 0.42, icon=True), fill=T["text"])
        else:
            self.c.create_text(x0 + s / 2, y0 + s / 2, text=fallback, font=self.font(s * 0.42, True), fill=T["text"])
        self.region(rid, x0, y0, x0 + s, y0 + s, tap=tap)

    def card(self, x0, y0, x1, y1, title, right=""):
        T, k = self.t, self.k
        P = 16 * k
        self.surface(x0, y0, x1, y1, 20 * k, T["panel"])
        tf = self.font(13 * k, True)
        self.text(x0 + P, y0 + P, title, tf, T["muted"], maxw=(x1 - x0) * 0.6)
        if right:
            self.text(x1 - P, y0 + P, right, self.font(13 * k), T["muted"], anchor="ne", maxw=(x1 - x0) * 0.4)
        return y0 + P + tf.metrics("linespace") + P * 0.6

    # -------------------------------------------------------------- animated & gradient backgrounds
    def fx_enabled(self):
        mode = self.cfg["animations"]
        return mode == "on" or (mode == "ac" and not self.on_battery)

    def gradient(self, W, H, stops, angle, phase=0.0, loop=False, n=40):
        a = math.radians(angle)
        dx, dy = math.cos(a), math.sin(a)
        nx, ny = -dy, dx
        cx, cy = W / 2, H / 2
        L = math.hypot(W, H) / 2 + 2
        ids = []
        for i in range(n):
            t0 = -L + 2 * L * i / n
            t1 = -L + 2 * L * (i + 1) / n + 1.5
            pts = [cx + dx * t0 + nx * L, cy + dy * t0 + ny * L, cx + dx * t0 - nx * L, cy + dy * t0 - ny * L,
                   cx + dx * t1 - nx * L, cy + dy * t1 - ny * L, cx + dx * t1 + nx * L, cy + dy * t1 + ny * L]
            ids.append(self.c.create_polygon(pts, fill=self.band_color(stops, (i + 0.5) / n, phase, loop), outline=""))
        return ids

    def grad_image(self, W, H, stops, angle, flow=False):
        """The theme gradient as one image (one blit to repaint instead of dozens of big polygons). A flowing gradient is
        drawn wider (or taller) by one period, and flows by sliding the image along."""
        key = (W, H, tuple(stops), angle, flow)
        cache = getattr(self, "_grad_cache", None)
        if cache and cache[0] == key:
            return cache[1]
        try:
            from PIL import Image, ImageTk
        except Exception:
            return None
        a = math.radians(angle)
        dx, dy = math.cos(a), math.sin(a)
        L = math.hypot(W, H) / 2 + 2
        if flow:
            P = L  # one colour cycle every half diagonal
            horiz = abs(dx) >= abs(dy)
            step = P / max(abs(dx) if horiz else abs(dy), 1e-3)
            iw, ih = (W + int(step) + 2, H) if horiz else (W, H + int(step) + 2)
            n = 1024
            strip = Image.new("RGB", (n * 6, 1))
            px = strip.load()
            for i in range(n * 6):
                h = grad_color(stops, (i / n) % 1.0).lstrip("#")
                px[i, 0] = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            sc = n / P
            off = n * 3 - sc * (dx * W / 2 + dy * H / 2)
        else:
            iw, ih = W, H
            n = 1024
            strip = Image.new("RGB", (n, 1))
            px = strip.load()
            for i in range(n):
                h = grad_color(stops, (i + 0.5) / n).lstrip("#")
                px[i, 0] = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            sc = n / (2 * L)
            off = n / 2 - sc * (dx * W / 2 + dy * H / 2)
            horiz, step = True, 0
        try:
            img = strip.transform((iw, ih), Image.AFFINE, (sc * dx, sc * dy, off, 0, 0, 0), resample=Image.BILINEAR)
            photo = ImageTk.PhotoImage(img)
        except Exception:
            return None
        self._grad_cache = (key, photo)
        self.flow_geo = (horiz, step)
        return photo

    def place_flow(self):
        """Slide the flowing gradient: moving it by one period looks identical, so it wraps without a seam."""
        if not self.grad_ids or not getattr(self, "flow_geo", None):
            return
        horiz, step = self.flow_geo
        o = -self.fx_phase() * step
        self.c.coords(self.grad_ids[0], (o, 0) if horiz else (0, o))

    @staticmethod
    def band_color(stops, t, phase, loop):
        if loop:
            return grad_color(stops, (t + phase) % 1.0)
        return grad_color(stops, t)

    def draw_background(self, W, H):
        T, c = self.t, self.c
        self.grad_ids, self.fx_items = [], []
        if self.cfg["wallpaper"] and not self.in_panel:
            img = self.wallpaper_image(int(W), int(H))
            if img:
                c.create_image(0, 0, image=img, anchor="nw")
                return
        if T.get("premium") and self.tab == "play" and not self.page and not self.in_panel and self.library:
            c.create_rectangle(0, 0, W, H, fill=T["bg"], width=0)
            amb = self.ambient(self.selected_game(), W, H)
            if amb:
                c.create_image(0, 0, image=amb, anchor="nw")
            return
        if T.get("grad"):
            flow = T.get("fx") == "flow"
            img = self.grad_image(int(W), int(H), T["grad"], T.get("angle", 125), flow)
            if img:
                self.grad_ids = [c.create_image(0, 0, image=img, anchor="nw")]
                if flow:
                    self.place_flow()
            else:
                self.grad_ids = self.gradient(W, H, T["grad"], T.get("angle", 125), self.fx_phase(), loop=flow)
        else:
            c.create_rectangle(0, 0, W, H, fill=T["bg"], width=0)
        if T.get("fx") and T["fx"] != "flow":
            self.draw_fx(W, H)

    def fx_phase(self):
        return (time.time() / (11.0 if self.t.get("fx") == "flow" else 40.0)) % 1.0 if self.fx_enabled() else 0.0

    def fx_state(self, W, H):
        T = self.t
        key = (self.theme_name, int(W), int(H))
        if getattr(self, "fx", None) and self.fx.get("key") == key:
            return self.fx
        rnd = random.Random(42)
        kind = T["fx"]
        parts = []
        if kind == "stars":
            parts = [dict(x=rnd.random() * W, y=rnd.random() * H, r=rnd.choice([1, 1, 1.5, 2, 2.5]) * self.k,
                          ph=rnd.random() * 6.28, sp=0.8 + rnd.random() * 2.2, vx=-(10 + rnd.random() * 26) * self.k) for _ in range(40)]
        elif kind in ("bubbles", "embers", "snow"):
            n = {"bubbles": 24, "embers": 34, "snow": 42}[kind]
            for _ in range(n):
                r = (rnd.random() * 5 + 2) * self.k if kind != "embers" else (rnd.random() * 2.5 + 1) * self.k
                v = (12 + rnd.random() * 30) * self.k
                parts.append(dict(x=rnd.random() * W, y=rnd.random() * H, r=r, vy=v if kind == "snow" else -v,
                                  ph=rnd.random() * 6.28, sway=(4 + rnd.random() * 14) * self.k))
        elif kind == "rain":
            parts = [dict(x=rnd.random() * W, y=rnd.random() * H, l=(30 + rnd.random() * 90) * self.k,
                          vy=(160 + rnd.random() * 260) * self.k, b=0.25 + rnd.random() * 0.5) for _ in range(45)]
        elif kind == "aurora":
            cols = ["accent", "accent2", "good", "accent"]
            parts = [dict(cx=W * (0.2 + 0.2 * i), cy=H * (0.3 + 0.12 * (i % 2)), rx=W * (0.28 + 0.06 * i), ry=H * (0.16 + 0.03 * i),
                          ph=i * 1.7, sp=0.22 + 0.06 * i, col=cols[i]) for i in range(4)]
        elif kind == "fireflies":
            parts = [dict(x=rnd.random() * W, y=rnd.random() * H, r=(1.5 + rnd.random() * 2.5) * self.k, ph=rnd.random() * 6.28,
                          sp=0.7 + rnd.random() * 1.6, vx=(rnd.random() - 0.5) * 30 * self.k, vy=-(4 + rnd.random() * 16) * self.k,
                          sway=(10 + rnd.random() * 26) * self.k) for _ in range(30)]
        elif kind == "petals":
            parts = [dict(x=rnd.random() * W, y=rnd.random() * H, r=(6 + rnd.random() * 7) * self.k, ph=rnd.random() * 6.28,
                          vx=(14 + rnd.random() * 26) * self.k, vy=(22 + rnd.random() * 34) * self.k, sway=(8 + rnd.random() * 20) * self.k,
                          spin=0.8 + rnd.random() * 2.2, col=rnd.choice(["accent", "accent", "accent2", "text"])) for _ in range(28)]
        elif kind == "confetti":
            parts = [dict(x=rnd.random() * W, y=rnd.random() * H, r=(3 + rnd.random() * 4) * self.k, ph=rnd.random() * 6.28,
                          vx=(rnd.random() - 0.5) * 20 * self.k, vy=(40 + rnd.random() * 60) * self.k, sway=(6 + rnd.random() * 16) * self.k,
                          spin=2 + rnd.random() * 5, col=rnd.choice(["accent", "accent2", "good", "warn", "danger"])) for _ in range(34)]
        elif kind == "waves":
            parts = [dict(i=i, amp=H * (0.03 + 0.012 * i), base=H * (0.62 + 0.09 * i), wl=W * (0.55 + 0.18 * i), sp=0.6 + 0.25 * i,
                          col=["accent2", "accent", "accent2", "accent"][i]) for i in range(4)]
        elif kind == "orbs":
            cols = ["accent", "accent2", "good", "accent2", "accent"]
            parts = [dict(cx=W * rnd.random(), cy=H * rnd.random(), R=min(W, H) * (0.22 + rnd.random() * 0.16), ax=W * (0.12 + rnd.random() * 0.12),
                          ay=H * (0.1 + rnd.random() * 0.12), ph=rnd.random() * 6.28, sp=0.12 + rnd.random() * 0.16, col=cols[i])
                     for i in range(5)]
        elif kind == "grid":
            parts = [dict(i=i) for i in range(16)]
        elif kind == "scan":
            parts = [dict(y=0.0)]
        self.fx = {"key": key, "kind": kind, "p": parts, "t": time.time(), "W": W, "H": H}
        return self.fx

    def fx_shapes(self, st, p):
        """(item type, coords, options) for one particle in its current state."""
        T, kind, k = self.t, st["kind"], self.k
        W, H = st["W"], st["H"]
        now = time.time()
        if kind == "stars":
            tw = 0.5 + 0.5 * math.sin(now * p["sp"] + p["ph"])
            r = p["r"]
            return "rect", (p["x"] - r, p["y"] - r, p["x"] + r, p["y"] + r), {"fill": mix(T["bg"], "#ffffff", 0.25 + 0.7 * tw)}
        if kind in ("bubbles", "embers", "snow"):
            x = p["x"] + math.sin(now * 0.8 + p["ph"]) * p["sway"]
            r = p["r"]
            if kind == "bubbles":
                return "oval", (x - r, p["y"] - r, x + r, p["y"] + r), {"fill": "", "outline": mix(T["bg"], T["accent"], 0.45),
                                                                       "width": max(1, k)}
            if kind == "embers":
                life = max(0.0, min(1.0, p["y"] / H))
                return "oval", (x - r, p["y"] - r, x + r, p["y"] + r), {"fill": mix(T["bg"], T["accent"] if life > 0.4 else T["accent2"], 0.35 + 0.6 * life)}
            return "oval", (x - r, p["y"] - r, x + r, p["y"] + r), {"fill": mix(T["bg"], "#ffffff", 0.55)}
        if kind == "fireflies":
            glow = 0.5 + 0.5 * math.sin(now * p["sp"] + p["ph"])
            x = p["x"] + math.sin(now * 0.6 + p["ph"]) * p["sway"]
            r = p["r"] * (0.7 + 0.5 * glow)
            return "oval", (x - r, p["y"] - r, x + r, p["y"] + r), {"fill": mix(T["bg"], T["warn"] if T.get("dark", True) else T["accent"], 0.2 + 0.8 * glow)}
        if kind in ("petals", "confetti"):
            x = p["x"] + math.sin(now * 0.9 + p["ph"]) * p["sway"]
            a = now * p["spin"] + p["ph"]
            r = p["r"]
            w_, h_ = r, r * (0.45 + 0.4 * abs(math.cos(a))) if kind == "petals" else r * abs(math.cos(a)) * 0.8 + 0.6 * k
            ca, sa = math.cos(a * 0.5), math.sin(a * 0.5)
            pts = []
            for ux, uy in ((-w_, 0), (0, -h_), (w_, 0), (0, h_)) if kind == "petals" else ((-w_, -h_), (w_, -h_), (w_, h_), (-w_, h_)):
                pts += [x + ux * ca - uy * sa, p["y"] + ux * sa + uy * ca]
            return "poly", pts, {"fill": mix(T["bg"], T[p["col"]], 0.75 if kind == "confetti" else 0.55), "outline": "",
                                 "smooth": kind == "petals"}
        if kind == "waves":
            pts = []
            n = 24
            for j in range(n + 1):
                x = W * j / n
                pts += [x, p["base"] + math.sin(x / p["wl"] * 6.2832 + now * p["sp"]) * p["amp"] +
                        math.sin(x / p["wl"] * 2.7 - now * p["sp"] * 0.7) * p["amp"] * 0.4]
            pts += [W, H, 0, H]
            return "poly", pts, {"fill": mix(T["bg"], T[p["col"]], 0.10 + 0.05 * p["i"]), "outline": "", "smooth": True}
        if kind == "orbs":
            a = now * p["sp"] + p["ph"]
            x, y = p["cx"] + math.sin(a) * p["ax"], p["cy"] + math.cos(a * 0.8) * p["ay"]
            return "img", (x, y), {}
        if kind == "rain":
            return "line", (p["x"], p["y"], p["x"], p["y"] + p["l"]), {"fill": mix(T["bg"], T["accent"], p["b"]), "width": max(1, 2 * k)}
        if kind == "aurora":
            a = now * p["sp"] + p["ph"]
            cx, cy = p["cx"] + math.sin(a) * W * 0.12, p["cy"] + math.cos(a * 1.3) * H * 0.08
            pts = []
            for j in range(14):
                t = j / 14 * 6.2832
                pts += [cx + math.cos(t) * p["rx"] * (1 + 0.15 * math.sin(3 * t + a)), cy + math.sin(t) * p["ry"]]
            return "poly", pts, {"fill": mix(T["bg"], T[p["col"]], 0.22), "outline": "", "smooth": True}
        if kind == "grid":
            hy = H * 0.6
            z = ((p["i"] + (now * 0.9 if self.fx_enabled() else 0)) % 16) / 16
            y = hy + (H - hy) * z * z
            return "line", (0, y, W, y), {"fill": mix(T["bg"], T["accent"], 0.25 + 0.5 * z), "width": max(1, 2 * k)}
        if kind == "scan":
            y = p["y"]
            return "poly", (0, y, W, y, W, y + 90 * k, 0, y + 90 * k), {"fill": mix(T["bg"], T["accent"], 0.6), "outline": "", "stipple": "gray25"}
        return None

    def orb_sprite(self, R, col):
        """A soft round glow (see-through PNG-style image) for the Orbs background, made once per size and colour."""
        cache = self.__dict__.setdefault("_orbs", {})
        key = (int(R), col, self.t["bg"])
        if key in cache:
            return cache[key]
        try:
            from PIL import Image, ImageDraw, ImageFilter, ImageTk
            n = int(R * 2)
            h = col.lstrip("#")
            rgb = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            m = Image.new("L", (n, n), 0)
            ImageDraw.Draw(m).ellipse((n * 0.22, n * 0.22, n * 0.78, n * 0.78), fill=int(255 * 0.42))
            m = m.filter(ImageFilter.GaussianBlur(n * 0.12))
            img = Image.new("RGBA", (n, n), rgb + (0,))
            img.putalpha(m)
            cache[key] = ImageTk.PhotoImage(img)
        except Exception:
            cache[key] = None
        return cache[key]

    def draw_fx(self, W, H):
        T, c, k = self.t, self.c, self.k
        st = self.fx_state(W, H)
        if st["kind"] == "grid":  # static parts: sun and the lines running to the horizon
            hy = H * 0.6
            r = H * 0.2
            c.create_arc(W / 2 - r, hy - r, W / 2 + r, hy + r, start=0, extent=180, style="chord", outline="",
                         fill=mix(T["warn"], T["accent"], 0.45))
            for i in range(1, 6):
                yy = hy - r * (1 - i / 6) ** 0.8 * 0.9
                c.create_rectangle(W / 2 - r, yy, W / 2 + r, yy + i * 2 * k, fill=T["bg"], width=0)
            c.create_rectangle(0, hy, W, H, fill=mix(T["bg"], "#000000", 0.35), width=0)
            line = mix(T["bg"], T["accent2"], 0.45)
            for i in range(-12, 13):
                c.create_line(W / 2, hy, W / 2 + i * W / 6, H, fill=line, width=max(1, k))
        ids = []
        for p in st["p"]:
            shape = self.fx_shapes(st, p)
            if not shape:
                continue
            typ, coords, opts = shape
            if typ == "img":
                spr = self.orb_sprite(p["R"], T[p["col"]])
                ids.append(c.create_image(*coords, image=spr, anchor="center") if spr else
                           c.create_oval(coords[0] - p["R"] * 0.6, coords[1] - p["R"] * 0.6, coords[0] + p["R"] * 0.6,
                                         coords[1] + p["R"] * 0.6, fill=mix(T["bg"], T[p["col"]], 0.18), outline=""))
                continue
            make = {"oval": c.create_oval, "line": c.create_line, "rect": c.create_rectangle, "poly": c.create_polygon}[typ]
            if typ in ("oval", "rect") and "outline" not in opts:
                opts = dict(opts, outline="")
            ids.append(make(*coords, **opts))
        self.fx_items = ids

    def fx_step(self):
        """Move the background one frame. Tk repaints one rectangle per flush (the union of everything that changed),
        so particles are flushed a few at a time in small clusters: many tiny repaints cost far less than one repaint
        of the whole window with every card and label on top. Big shapes take turns, one or two per frame."""
        st = getattr(self, "fx", None)
        T, c = self.t, self.c
        self.fx_frame = getattr(self, "fx_frame", 0) + 1
        if T.get("fx") == "flow":
            if len(self.grad_ids) == 1:
                self.place_flow()
                return
            ph = self.fx_phase()
            n = len(self.grad_ids)
            for i, iid in enumerate(self.grad_ids):
                c.itemconfigure(iid, fill=self.band_color(T["grad"], (i + 0.5) / n, ph, True))
            return
        if not st or st["key"][0] != self.theme_name or not self.fx_items:
            return
        now = time.time()
        dt = min(1.0, now - st["t"])  # real time: a slow PC shows fewer frames, never slow motion
        st["t"] = now
        W, H, kind = st["W"], st["H"], st["kind"]
        for p in st["p"]:
            if kind == "stars":
                p["x"] += p["vx"] * dt
                if p["x"] < -5:
                    p["x"] = W + 5
            elif kind in ("bubbles", "embers", "snow", "rain", "fireflies", "petals", "confetti"):
                p["y"] += p["vy"] * dt
                p["x"] += p.get("vx", 0) * dt
                if p["vy"] < 0 and p["y"] < -20:
                    p["y"], p["x"] = H + 20, random.random() * W
                elif p["vy"] > 0 and p["y"] > H + 20:
                    p["y"], p["x"] = -20 - p.get("l", 0), random.random() * W
                if p["x"] < -30 or p["x"] > W + 30:
                    p["x"] %= W
            elif kind == "scan":
                p["y"] = (p["y"] + 160 * self.k * dt) % (H + 100 * self.k) - 90 * self.k
        pairs = list(zip(self.fx_items, st["p"]))  # everything moves every frame: taking turns looked jerky
        for iid, p in pairs:
            shape = self.fx_shapes(st, p)
            if shape:
                typ, coords, opts = shape
                if typ == "img" and c.type(iid) == "oval":
                    r_ = p["R"] * 0.6
                    coords = (coords[0] - r_, coords[1] - r_, coords[0] + r_, coords[1] + r_)
                c.coords(iid, *coords)
                if "fill" in opts and typ != "poly":
                    c.itemconfigure(iid, fill=opts["fill"])

    def fx_loop(self):
        """Moves an animated theme's background, about 30 frames a second when this PC can afford it (at most ~40%
        of the time), and holds still while you touch or drag."""
        delay = 400
        try:
            in_front = self.focused()
            if self.t.get("fx") and self.fx_enabled() and not self.hidden and self.root.state() != "iconic" and (in_front or not self.game):
                busy = self.press or self.kinetic or self.slides  # hovering or a D-pad press no longer pauses it
                if busy:
                    delay = 100
                else:
                    t0 = time.perf_counter()
                    self.fx_step()
                    self.root.update_idletasks()
                    cost = time.perf_counter() - t0
                    self.fx_cost = self.fx_cost * 0.7 + cost * 0.3
                    now_ = time.perf_counter()
                    last_ = getattr(self, "fx_last", 0.0)
                    if 0 < now_ - last_ < 2:
                        self.fx_fps = getattr(self, "fx_fps", 0.0) * 0.9 + 0.1 / (now_ - last_)
                    self.fx_last = now_
                    # frame pacing: aim for a steady 30 (24 on battery) fps; when a frame costs more than that allows,
                    # rest for a bit less than the frame took so the app stays responsive (about 55% busy at most)
                    fps = (24 if self.on_battery else 30) if in_front else 12
                    delay = int(max(1.0 / fps - cost, self.fx_cost * 0.8, 0.004) * 1000)
            elif self.hidden:
                delay = 1500
        except Exception:
            pass
        self.root.after(max(4, min(1500, delay)), self.fx_loop)

    # -------------------------------------------------------------- drawing
    def draw(self):
        self.draw_pending = False
        if self.cfg["guest"]:
            if self.tab not in ("home", "play"):
                self.tab = "home"
                self.draw_scope = "all"
            if self.page and self.page not in self.GUEST_PAGES:
                self.page = "guest"
                self.draw_scope = "all"
        if self.hidden or self.root.state() == "iconic":
            self.draw_scope = None
            self.stale = True  # nothing to see: draw when the window comes back
            return
        self.stale = False
        LANG["code"] = self.cfg["lang"]
        if self.page != self.shown_page:
            if self.page and not self.shown_page:
                self.begin_slide("page", "page", 0, 54 * self.k, 0.32)
            self.shown_page = self.page
        scope, self.draw_scope = self.draw_scope, None
        self._last_draw = time.perf_counter()
        if self.in_panel:
            return self._draw_quick()
        if self.quick:
            self.draw_quick()
        if self.hidden:
            return
        self.root.after_idle(self.draw_pointer)
        c = self.c
        W, H = max(c.winfo_width(), 320), max(c.winfo_height(), 240)
        self.k = k = max(0.5, min(3.0, min(W / 1280, H / 800) * self.cfg["ui_scale"] / 100 * self.t.get("scale", 1)))
        T = self.t
        if scope == "lib" and not self.page and not self.slides and self._libgrid and \
                self._lib_base == (W, H, id(T), self.tab, self.cfg["layout"]):
            # fast path: only the library scrolled, so redraw just the tiles
            c.delete("libgrid")
            c.clip = None
            self.regions = [r for r in self.regions if r.get("sid") != "lib"]
            self.layer = "main"
            c.layer_tag, c.extra_tag = "content", "libgrid"
            try:
                self.draw_lib_grid(*self._libgrid)
            finally:
                c.layer_tag, c.extra_tag = "main", None
                c.clip = None
            c.tag_raise("toastfx")
            self.draw_focus_ring()
            return
        if scope == "lib":
            scope = "all"
        if scope == "page" and self.page and self._base == (W, H, self.page, self.t is T, id(self.t)):
            # fast path: only the open page changed (scrolling, a press), so keep the hub drawn under it
            c.delete("page")
            c.clip = None
            self.regions = [r for r in self.regions if r["layer"] != "page"]
            self.layer = "page"
            self.draw_page(W, H)
            self.slide_page()
            self.draw_toast(W, H)
            self.draw_focus_ring()
            self.glide_t = time.perf_counter()
            return
        self._base = (W, H, self.page, True, id(self.t)) if self.page else None
        c.delete("all")
        c.clip = None
        self.regions = []
        self._libgrid = None
        c.layer_tag = "bg"
        self.draw_background(W, H)
        self.layer = "main"
        if self.page:
            # pages are full sheets over the theme's background: the hub isn't drawn under them, which keeps
            # scrolling a page cheap (nothing hidden underneath has to be repainted)
            self.layer = "page"
            self.draw_page(W, H)
            self.slide_page()
            self.draw_toast(W, H)
            self.draw_focus_ring()
            self.glide_t = time.perf_counter()
            return
        P = 14 * k
        sh = 50 * k
        rail = self.cfg["layout"] == "rail"
        console = self.cfg["layout"] == "console"
        if console:
            cx0 = P
            hh = self.draw_consolebar(W)
            by0, by1 = hh, H - P - self.hint_h()
            land = W >= H * 1.15
        elif rail:
            rw = self.draw_rail(W, H)
            cx0 = rw + P
            hh = self.draw_topbar(cx0, W)
            by0, by1 = hh, H - P - self.hint_h()
            land = W - cx0 >= H * 1.05
        else:
            cx0 = P
            hh = self.draw_header(W)
            by0, by1 = hh, H - sh - P * 0.7
            land = W >= H * 1.15
        n_reg = len(self.regions)
        c.layer_tag = "content"
        {"home": self.draw_tab_home, "play": self.draw_tab_play, "memory": self.draw_tab_memory, "clean": self.draw_tab_clean, "tools": self.draw_tab_tools,
         "games": self.draw_tab_games, "stats": self.draw_tab_stats, "system": self.draw_tab_system, "startup": self.draw_tab_startup}[self.tab](cx0, by0, W - P, by1, land)
        c.layer_tag = "main"
        self._lib_base = (W, H, id(T), self.tab, self.cfg["layout"]) if self._libgrid else None
        self.place_slide("tab", self.regions[n_reg:])  # the new tab glides in from the direction you moved
        if not rail and not console:
            self.draw_status(W, H, sh)
        self.draw_toast(W, H)
        self.draw_focus_ring()
        self.glide_t = time.perf_counter()

    def slide_page(self):
        self.place_slide("page", [r for r in self.regions if r["layer"] == "page"])

    def pad_hints(self):
        """What the controller buttons do on this screen."""
        if self.page == "settings":
            return [("A", "Select"), ("B", "Back"), ("LB", "Category"), ("Y", "Search")]
        if self.page:
            return [("A", "Select"), ("B", "Back")]
        lb = ("LB", "Sections" if self.cfg["layout"] == "console" else "Tabs")
        if self.tab == "home":
            return [("A", "Select"), ("X", "Play"), ("Y", "Search"), lb]
        if self.tab == "play":
            return [("A", "Select"), ("X", "Play"), ("Y", "Focus"), lb]
        sec = self.section_of(self.tab)
        if self.cfg["layout"] == "console" and sec and len(sec[2]) > 1:
            return [("A", "Select"), ("LT", "Page"), lb]
        return [("A", "Select"), ("X", "Boost"), ("Y", "Optimize all"), lb]

    def hint_h(self):
        """Room kept at the bottom for the controller hints (only while a controller is connected)."""
        return 46 * self.k if self.pad_on and not self.in_panel else 0

    def draw_pad_hints(self, W, H):
        if not self.hint_h():
            return
        T, k = self.t, self.k
        f = self.font(12.5 * k, True)
        items = self.pad_hints()
        r = 11 * k
        widths = [2 * r + 8 * k + self.measure(f, tr(lbl)) + 16 * k for _, lbl in items]
        w = sum(widths) + 12 * k
        h = 38 * k
        x1, y1 = W - 16 * k, H - 8 * k
        x0, y0 = x1 - w, y1 - h
        self.rr(x0, y0, x1, y1, h / 2, mix(T["bg"], T["panel"], 0.9), outline=mix(T["panel"], T["text"], 0.1), width=max(1, k))
        x = x0 + 12 * k
        for (btn, lbl), bw in zip(items, widths):
            self.pad_badge(x + r, (y0 + y1) / 2, btn, r)
            self.text(x + 2 * r + 8 * k, (y0 + y1) / 2, tr(lbl), f, T["muted"], anchor="w")
            x += bw

    def draw_toast(self, W, H):
        if self.toast and time.time() - self.toast[1] < 2.6:
            T, k = self.t, self.k
            P, sh = 14 * k, 50 * k
            f = self.font(16 * k, True)
            tw = min(self.measure(f, self.toast[0]) + 48 * k, W - 4 * P)
            ty = H - sh - P - 56 * k
            bgc = T["text"]
            et = self.c.extra_tag
            self.c.extra_tag = "toastfx"
            self.rr(W / 2 - tw / 2, ty, W / 2 + tw / 2, ty + 48 * k, 24 * k, bgc)
            self.text(W / 2, ty + 24 * k, self.toast[0], f, T["bg"], anchor="center", maxw=tw - 24 * k)
            self.c.extra_tag = et
            self.place_slide("toast", [])

    def draw_focus_ring(self):
        self.c.delete("hintfx")
        try:
            et, lt = self.c.extra_tag, self.c.layer_tag
            self.c.extra_tag, self.c.layer_tag = "hintfx", ("page" if self.page else "main")
            W, H = max(self.c.winfo_width(), 320), max(self.c.winfo_height(), 240)
            self.draw_pad_hints(W, H)
        finally:
            self.c.extra_tag, self.c.layer_tag = et, lt
        if self.focus_visible:
            cur, _ = self.current_focus()
            if cur:
                k, g = self.k, 4 * self.k
                target = [cur["x0"] - g, cur["y0"] - g, cur["x1"] + g, cur["y1"] + g]
                far = self.ring_pos is None or abs(self.ring_pos[1] - target[1]) > 600 * k
                if far or not self.cfg["motion"]:
                    self.ring_pos = list(target)
                self.ring_target = target
                self.paint_ring()
                if self.ring_pos != target:
                    self.start_tick()
        else:
            self.ring_pos = self.ring_target = None
            self.c.delete("ringfx")
        self.draw_hover()

    def go_badge(self, x, cy):
        """The accent "GO" pill after the wordmark in Vanta Go. Returns its width."""
        T, k = self.t, self.k
        f = self.font(11.5 * k, True)
        w, h = self.measure(f, "GO") + 14 * k, 20 * k
        self.rr(x, cy - h / 2, x + w, cy + h / 2, 6 * k, T["accent"])
        self.text(x + w / 2, cy, "GO", f, T["accent_text"], anchor="center")
        return w

    def rail_glyph(self, key, cx, cy, size, col):
        glyph, fb = RAIL_ICONS[key]
        if self.icon_family:
            self.c.create_text(cx, cy, text=glyph, font=self.font(size, icon=True), fill=col)
        else:
            self.c.create_text(cx, cy, text=fb, font=self.font(size * 0.9, True), fill=col)

    def draw_rail(self, W, H):
        """The side rail: logo, the tabs in groups with a gliding highlight, and the app's controls at the bottom."""
        T, k, c = self.t, self.k, self.c
        compact = W < 1060 * k or H > W
        m = 12 * k
        rw = (92 if compact else 214) * k
        x0, y0, x1, y1 = m, m, rw, H - m
        fill = mix(T["bg"], T["panel"], 0.82)
        self.surface(x0, y0, x1, y1, 24 * k, fill)
        cx = (x0 + x1) / 2
        # logo
        ly = y0 + 44 * k
        ms = 34 * k
        mx = cx - ms / 2 if compact else x0 + 22 * k
        for pts, col in ((MARK_LEFT, T["accent"]), (MARK_RIGHT, T["accent2"])):
            c.create_polygon([v for px, py in pts for v in (mx + px * ms, ly - ms / 2 + py * ms)], fill=col, outline="")
        if not compact:
            f = self.font(21 * k if not IS_GO else 19 * k, True, display=True)
            x = mx + ms + 12 * k
            for ch in "VANTA":
                c.create_text(x, ly, text=ch, font=f, fill=T["text"], anchor="w")
                x += f.measure(ch) + (6 if not IS_GO else 4) * k
            if IS_GO:
                self.go_badge(x + 4 * k, ly)
        # nav items
        ih, gap_ = 52 * k, 4 * k
        y = y0 + 96 * k
        pos = {}
        gf = self.font(11 * k, True)
        for title, ids in (RAIL_GROUPS[:1] if self.cfg["guest"] else RAIL_GROUPS):
            if title:
                if compact:
                    c.create_line(x0 + 22 * k, y + 10 * k, x1 - 22 * k, y + 10 * k, fill=mix(fill, T["text"], 0.1))
                    y += 20 * k
                else:
                    self.text(x0 + 24 * k, y + 16 * k, tr(title), gf, mix(T["muted"], fill, 0.25), anchor="w")
                    y += 32 * k
            for tid in ids:
                pos[tid] = y
                y += ih + gap_
        nav_end = y
        target = pos.get(self.tab, pos["play"])
        if self.rail_ind is None or not self.cfg["motion"]:
            self.rail_ind = [target]
        self.rail_target = target
        iy = self.rail_ind[0]
        if abs(iy - target) > 0.5:
            self.start_tick()
        c.extra_tag = "railind"
        ix0, ix1 = x0 + 10 * k, x1 - 10 * k
        sel = mix(fill, T["accent"], 0.2)
        if T.get("premium"):
            self.rr(ix0 - 2 * k, iy - 2 * k, ix1 + 2 * k, iy + ih + 2 * k, 16 * k, "", outline=mix(fill, T["accent"], 0.35),
                    width=max(1, k))
        self.rr(ix0, iy, ix1, iy + ih, 14 * k, sel)
        self.rr(ix0, iy + 14 * k, ix0 + 4 * k, iy + ih - 14 * k, 2 * k, T["accent"])
        c.extra_tag = None
        lf = self.font(15 * k, True)
        for tid, ty in pos.items():
            on = tid == self.tab
            rid = f"tab_{tid}"
            if not on and (self.pressed == rid or self.hover_fill == rid):
                self.rr(ix0, ty, ix1, ty + ih, 14 * k, mix(fill, T["accent"] if self.pressed == rid else T["text"],
                                                          0.25 if self.pressed == rid else 0.05))
            col = T["accent"] if on else mix(T["muted"], T["text"], 0.25)
            icx = cx if compact else ix0 + 30 * k
            self.rail_glyph(tid, icx, ty + ih / 2, 19 * k, col)
            if not compact:
                self.text(ix0 + 56 * k, ty + ih / 2, tr(TAB_TITLES[tid]), lf, T["text"] if on else mix(T["muted"], T["text"], 0.35),
                          anchor="w", maxw=ix1 - ix0 - 64 * k)
            self.region(rid, ix0, ty, ix1, ty + ih, tap=lambda t=tid: self.set_tab(t))
        if self.pad_on:
            self.pad_badge(x1 - 26 * k if not compact else cx, y0 + 96 * k - 14 * k if compact else y0 + 80 * k, "LB", 12 * k)
            self.pad_badge(x1 - 26 * k if not compact else cx, nav_end + 10 * k, "RB", 12 * k)
        # bottom: auto, then menu + settings
        yb = y1 - 14 * k
        bs = 50 * k
        if compact:
            for rid, key, fn in (("hdr_settings", "settings", lambda: self.open_page("settings")),
                                 ("hdr_menu", "menu", lambda: self.open_page("menu"))):
                self.rail_button(rid, cx - bs / 2, yb - bs, cx + bs / 2, yb, key, None, fn, fill)
                yb -= bs + 8 * k
        else:
            self.rail_button("hdr_menu", ix0, yb - bs, ix1 - bs - 8 * k, yb, "menu", "Menu", lambda: self.open_page("menu"), fill)
            self.rail_button("hdr_settings", ix1 - bs, yb - bs, ix1, yb, "settings", None, lambda: self.open_page("settings"), fill)
            yb -= bs + 10 * k
        # auto-optimize switch
        on = self.cfg["auto"]
        ah = 50 * k
        rid = "auto"
        af = mix(fill, T["accent"] if self.pressed == rid else T["text"], 0.2 if self.pressed == rid else 0.04)
        if compact:
            self.rr(cx - bs / 2, yb - ah, cx + bs / 2, yb, 14 * k, af)
            self.text(cx, yb - ah / 2, "AUTO", self.font(10.5 * k, True), T["good"] if on else T["muted"], anchor="center")
            self.region(rid, cx - bs / 2, yb - ah, cx + bs / 2, yb, tap=lambda: self.adjust("auto", 1))
        else:
            self.rr(ix0, yb - ah, ix1, yb, 14 * k, af)
            self.text(ix0 + 16 * k, yb - ah / 2 - 8 * k, tr("Auto optimize"), self.font(14 * k, True), T["text"], anchor="w")
            self.text(ix0 + 16 * k, yb - ah / 2 + 10 * k, tr("On") if on else tr("Off"), self.font(12 * k),
                      T["good"] if on else T["muted"], anchor="w")
            tw, th_ = 46 * k, 26 * k
            sx1, scy = ix1 - 12 * k, yb - ah / 2
            self.rr(sx1 - tw, scy - th_ / 2, sx1, scy + th_ / 2, th_ / 2, T["good"] if on else mix(fill, T["text"], 0.12))
            kr = th_ / 2 - 4 * k
            kx = sx1 - th_ / 2 if on else sx1 - tw + th_ / 2
            c.create_oval(kx - kr, scy - kr, kx + kr, scy + kr, fill="#ffffff" if on else T["muted"], outline="")
            self.region(rid, ix0, yb - ah, ix1, yb, tap=lambda: self.adjust("auto", 1))
        yb -= ah + 12 * k
        # device card
        if not compact and yb - nav_end > 86 * k:
            dh = 70 * k
            dy0 = yb - dh
            c.create_line(ix0 + 6 * k, dy0 - 8 * k, ix1 - 6 * k, dy0 - 8 * k, fill=mix(fill, T["text"], 0.08))
            name = self.device["name"] if self.device["legion"] else "This PC"
            self.text(ix0 + 6 * k, dy0 + 14 * k, name, self.font(13 * k, True), T["text"], anchor="w", maxw=ix1 - ix0 - 12 * k)
            bits = []
            if PREVIEW:
                bits.append(("PREVIEW", T["warn"]))
            bits.append(("ADMIN" if self.admin else "LIMITED", T["good"] if self.admin else T["warn"]))
            if self.pad_on:
                pb = self.pad_batt
                bits.append((f"PAD {pb}" if pb else "PAD", T["danger"] if pb in ("LOW", "EMPTY") else T["muted"]))
            bx = ix0 + 6 * k
            bf = self.font(11 * k, True)
            for label, col in bits:
                w = self.chip(bx, dy0 + 32 * k, label, bf, fg=col, fill=mix(fill, T["text"], 0.05))
                bx += w + 6 * k
                if bx > ix1 - 40 * k:
                    break
        return rw

    def rail_button(self, rid, x0, y0, x1, y1, key, label, fn, fill):
        T, k = self.t, self.k
        f_ = mix(fill, T["accent"], 0.3) if self.pressed == rid else mix(fill, T["text"], 0.09 if self.hover_fill == rid else 0.05)
        self.rr(x0, y0, x1, y1, 14 * k, f_)
        if label:
            self.rail_glyph(key, x0 + 22 * k, (y0 + y1) / 2, 16 * k, T["text"])
            self.text(x0 + 40 * k, (y0 + y1) / 2, tr(label), self.font(13.5 * k, True), T["text"], anchor="w", maxw=x1 - x0 - 46 * k)
        else:
            self.rail_glyph(key, (x0 + x1) / 2, (y0 + y1) / 2, 18 * k, T["text"])
        self.region(rid, x0, y0, x1, y1, tap=fn)

    # ---------------------------------------------------------------- console layout
    def draw_consolebar(self, W):
        """Logo, the four sections, status and controls; Tune and Insights add a row of chips for their pages."""
        T, k, c = self.t, self.k, self.c
        P = 14 * k
        row = 70 * k
        cy = 12 * k + row / 2
        x = P + 10 * k
        ms = 30 * k
        for pts, col in ((MARK_LEFT, T["accent"]), (MARK_RIGHT, T["accent2"])):
            c.create_polygon([v for px, py in pts for v in (x + px * ms, cy - ms / 2 + py * ms)], fill=col, outline="")
        x += ms + 18 * k
        # right side: window buttons, clock, battery, settings, menu, search
        s_, gap = 44 * k, 6 * k
        xr = W - P
        for rid, key, fn in (("hdr_close", "close", self.on_close),
                             ("hdr_hide", "hide", (self.hide if self.tray else self.root.iconify)),
                             ("hdr_full", "unfull" if self.cfg["fullscreen"] else "full", self.toggle_fullscreen)):
            xr -= s_
            self.icon_button(rid, xr, cy - s_ / 2, s_, key, fn)
            xr -= gap
        xr -= 10 * k
        cf = self.font(15 * k, True)
        clock = time.strftime("%H:%M")
        self.text(xr, cy, clock, cf, T["text"], anchor="e")
        xr -= self.measure(cf, clock) + 16 * k
        p = self.power
        if p and p["battery"] and p["pct"] <= 100:
            low = p["pct"] < 20 and not p["ac"]
            label = ("⚡" if p["ac"] else "") + f"{p['pct']}%"
            self.text(xr, cy, label, cf, T["danger"] if low else T["good"] if p["ac"] else T["text"], anchor="e")
            xr -= self.measure(cf, label) + 18 * k
        for rid, key, label, fn in (("hdr_settings", "settings", None, lambda: self.open_page("settings")),
                                    ("hdr_menu", "menu", None, lambda: self.open_page("menu"))):
            xr -= s_
            self.rail_button(rid, xr, cy - s_ / 2, xr + s_, cy + s_ / 2, key, label, fn, mix(T["bg"], T["panel"], 0.6))
            xr -= gap
        sw = min(260 * k, max(120 * k, xr - x - 520 * k))
        xr -= 8 * k
        rid = "hdr_find"
        self.rr(xr - sw, cy - 22 * k, xr, cy + 22 * k, 22 * k,
                mix(T["panel"], T["accent"], 0.3) if self.pressed == rid else mix(T["bg"], T["panel"], 0.8),
                outline=mix(T["panel"], T["text"], 0.1), width=max(1, k))
        self.text(xr - sw + 18 * k, cy, "⌕  " + tr("Search"), self.font(14 * k), T["muted"], anchor="w", maxw=sw - 30 * k)
        self.region(rid, xr - sw, cy - 22 * k, xr, cy + 22 * k, tap=self.open_find)
        # the sections
        sf = self.font(17 * k, True)
        secs = self.sections()
        cur = self.section_of(self.tab) or secs[0]
        if cur not in secs:
            cur = secs[0]
        th = 46 * k
        xs, ws = [], []
        for sid_, label, tabs in secs:
            w = self.measure(sf, tr(label)) + 40 * k
            xs.append(x)
            ws.append(w)
            x += w + 6 * k
        ai = next(i for i, sec in enumerate(secs) if sec[0] == cur[0])
        target = [xs[ai], ws[ai]]
        if self.bar_ind is None or not self.cfg["motion"] or abs(self.bar_ind[1] - target[1]) > 0.5:
            self.bar_ind = list(target)
        self.bar_target = target
        if abs(self.bar_ind[0] - target[0]) > 0.5:
            self.start_tick()
        c.extra_tag = "barind"
        bx, bw = self.bar_ind
        self.rr(bx, cy - th / 2, bx + bw, cy + th / 2, th / 2, T["accent"])
        c.extra_tag = None
        for (sid_, label, tabs), x_, w in zip(secs, xs, ws):
            on = sid_ == cur[0]
            rid = f"sec_{sid_}"
            if not on and self.pressed == rid:
                self.rr(x_, cy - th / 2, x_ + w, cy + th / 2, th / 2, mix(T["panel"], T["accent"], 0.3))
            self.text(x_ + w / 2, cy, tr(label), sf, T["accent_text"] if on else mix(T["muted"], T["text"], 0.35),
                      anchor="center")
            self.region(rid, x_, cy - th / 2, x_ + w, cy + th / 2,
                        tap=lambda sec=(sid_, label, tabs): self.set_tab(self.sec_last.get(sec[0], sec[2][0])))
        if self.pad_on:
            self.pad_badge(xs[0] - 4 * k, cy - th / 2, "LB", 10 * k)
            self.pad_badge(xs[-1] + ws[-1] + 4 * k, cy - th / 2, "RB", 10 * k)
        y = 12 * k + row
        # chips for the pages inside a section
        if len(cur[2]) > 1:
            cf2 = self.font(14 * k, True)
            ch = 38 * k
            cyc = y + ch / 2 + 2 * k
            x_ = P + 10 * k
            if self.pad_on:
                self.pad_badge(x_ + 12 * k, cyc, "LT", 10 * k)
                x_ += 30 * k
            for tid in cur[2]:
                label = tr(TAB_TITLES[tid])
                w = self.measure(cf2, label) + 30 * k
                on = tid == self.tab
                rid = f"tab_{tid}"
                fill = mix(T["panel2"], T["accent"], 0.25) if on else mix(T["accent"], T["panel2"], 0.7) if self.pressed == rid \
                    else mix(T["bg"], T["panel"], 0.7)
                self.rr(x_, cyc - ch / 2, x_ + w, cyc + ch / 2, ch / 2, fill,
                        outline=T["accent"] if on else mix(T["panel"], T["text"], 0.08), width=max(1, k))
                self.text(x_ + w / 2, cyc, label, cf2, T["text"] if on else T["muted"], anchor="center")
                self.region(rid, x_, cyc - ch / 2, x_ + w, cyc + ch / 2, tap=lambda t=tid: self.set_tab(t))
                x_ += w + 8 * k
            if self.pad_on:
                self.pad_badge(x_ + 10 * k, cyc, "RT", 10 * k)
                x_ += 30 * k
            if self.busy:
                self.spinner(x_ + 20 * k, cyc, 8 * k)
                self.text(x_ + 36 * k, cyc, self.busy + "…", self.font(13 * k), T["text"], anchor="w", maxw=W - x_ - 60 * k)
            y += ch + 12 * k
        elif self.busy:
            self.spinner(P + 24 * k, y + 6 * k, 7 * k)
            self.text(P + 38 * k, y + 6 * k, self.busy + "…", self.font(12.5 * k), T["muted"], anchor="w")
            y += 14 * k
        return y + 6 * k

    def home_game(self):
        """The game the Home banner shows: the one you picked there, else the one you played last."""
        lib = self.library or []
        if self.cfg["guest"] and self.guest_ids() is not None:
            ids_ = self.guest_ids()
            lib = [g for g in lib if g["id"] in ids_]
        if self.home_sel:
            g = next((g for g in lib if g["id"] == self.home_sel), None)
            if g:
                return g
        played = [g for g in lib if not str(g["id"]).startswith("sample:") or self.cfg["guest"]]
        if not played:
            return lib[0] if lib else None
        return max(played, key=lambda g: (self.game_stats(g)[0] or 0, g["id"] == self.lib_sel))

    def draw_tab_home(self, x0, y0, x1, y1, land):
        T, k, c = self.t, self.k, self.c
        if self.library is None:
            return self.draw_skeleton(x0, y0, x1, y1) if T.get("premium") else self.spinner((x0 + x1) / 2, (y0 + y1) / 2, 20 * k)
        g = self.home_game()
        self.update_game_colors(g)
        avail = y1 - y0
        gap = 18 * k
        card_h = 96 * k
        tile_h = max(110 * k, min(190 * k, avail * 0.27))
        hero_h = max(170 * k, avail - card_h - tile_h - 3 * gap - 34 * k)
        W_ = x1 - x0
        # --- the banner
        hx1, hy1 = x1, y0 + hero_h
        self.rr(x0, y0, hx1, hy1, 22 * k, mix(T["bg"], T["panel2"], 0.8))
        if g:
            img = self.hero(g, int(W_), int(hero_h))
            if img:
                c.create_image(x0, y0, image=img, anchor="nw")
            else:
                cov = self.cover(g, hero_h * 0.62, hero_h * 0.93)
                if cov:
                    c.create_image(x1 - 30 * k - hero_h * 0.62, y0 + hero_h * 0.035, image=cov, anchor="nw")
            px = x0 + 34 * k
            tf = self.font(min(40 * k, hero_h * 0.16), True, display=True)
            ty = hy1 - 128 * k
            for dx_, col in ((2 * k, "#000000"), (0, "#ffffff")):  # a soft shadow keeps it readable on any art
                self.text(px + dx_, ty + dx_, g["name"], tf, col, anchor="sw", maxw=W_ * 0.6)
            note = self.note_of(g["id"])
            if note:
                ny = ty - tf.metrics("linespace") - 4 * k
                for dx_, col in ((1.5 * k, "#000000"), (0, mix("#ffffff", T["accent"], 0.45))):
                    self.text(px + dx_, ny + dx_, "✎  " + note.splitlines()[0], self.font(14 * k, True), col, anchor="sw", maxw=W_ * 0.6)
            last, mins = self.game_stats(g)
            bits = [f"{mins // 60}h {mins % 60}m played" if mins else "Not played yet", g.get("source", "")]
            pre = self.find_preset(g["name"])
            if pre:
                bits.append(f"{pre['title']} preset ready")
            for dx_, col in ((1.5 * k, "#000000"), (0, mix("#ffffff", T["bg"], 0.15))):
                self.text(px + dx_, ty + 10 * k + dx_, "  ·  ".join(b for b in bits if b), self.font(14 * k, True), col,
                          anchor="nw", maxw=W_ * 0.6)
            running = self.game and self.game.get("hub", {}).get("id") == g["id"]
            bw_, bh_ = 230 * k, 56 * k
            by_ = hy1 - 34 * k - bh_
            self.button("home_play", px, by_, px + bw_, by_ + bh_, "● PLAYING" if running else "▶   PLAY",
                        (lambda: None) if running else (lambda gg=g: self.play(gg)), style="accent", badge="X", size=18 * k)
            self.button("home_open", px + bw_ + 12 * k, by_, px + bw_ + 12 * k + 190 * k, by_ + bh_, "GAME PAGE",
                        lambda gg=g: (setattr(self, "lib_sel", gg["id"]), self.set_tab("play")), size=13 * k)
        else:
            self.text((x0 + x1) / 2, y0 + hero_h / 2, "Add a game to see it here", self.font(18 * k), T["muted"], anchor="center")
        fy = [] if self.cfg["guest"] else self.for_you()
        if fy:
            txt, fn = fy[int(time.time() / 20) % len(fy)]
            pf = self.font(13 * k, True)
            pw_ = min(W_ * 0.55, self.measure(pf, "✦  " + txt) + 30 * k)
            rid = "home_tip"
            self.rr(x0 + 22 * k, y0 + 20 * k, x0 + 22 * k + pw_, y0 + 54 * k, 17 * k,
                    mix(T["accent"], "#000000", 0.25) if self.pressed == rid else mix(T["bg"], "#000000", 0.35))
            self.text(x0 + 37 * k, y0 + 37 * k, "✦  " + txt, pf, "#ffffff", anchor="w", maxw=pw_ - 30 * k)
            self.region(rid, x0 + 22 * k, y0 + 20 * k, x0 + 22 * k + pw_, y0 + 54 * k, tap=fn)
        if self.cfg["people"] and not self.cfg["guest"]:
            pf_ = self.font(13 * k, True)
            ptxt = "●  " + self.person_name() + "  ›"
            pw2 = self.measure(pf_, ptxt) + 30 * k
            py2 = y0 + (62 if fy else 20) * k
            rid = "home_person"
            self.rr(x0 + 22 * k, py2, x0 + 22 * k + pw2, py2 + 34 * k, 17 * k,
                    mix(T["accent"], "#000000", 0.25) if self.pressed == rid else mix(T["bg"], "#000000", 0.35))
            self.text(x0 + 37 * k, py2 + 17 * k, ptxt, pf_, "#ffffff", anchor="w")
            self.region(rid, x0 + 22 * k, py2, x0 + 22 * k + pw2, py2 + 34 * k, tap=lambda: self.open_page("people"))
        chips = []
        if self.sleep_left() is not None or self.cfg["sleep_after_game"]:
            chips.append("Sleep " + self.sleep_label())
        if self.cfg["guest"]:
            chips.append("Guest mode")
        if self.cfg["daily_limit"] or self.cfg["break_every"]:
            played = self.played_today()
            chips.append(f"Today {fmt_duration(played)}" + (f" of {fmt_duration(self.cfg['daily_limit'] * 60)}" if self.cfg["daily_limit"] else ""))
        if self.cfg["batt_goal"]:
            chips.append("Battery goal " + self.bgoal_label(self.cfg["batt_goal"]))
        st_ = self.streaks()[0]
        if st_ >= 2:
            chips.insert(0, f"{st_}-day streak")
        if chips:
            ct = "   ·   ".join(chips)
            cf = self.font(13 * k, True)
            cw_ = self.measure(cf, ct) + 28 * k
            self.rr(hx1 - 22 * k - cw_, y0 + 20 * k, hx1 - 22 * k, y0 + 54 * k, 17 * k, mix(T["bg"], "#000000", 0.35))
            self.text(hx1 - 22 * k - cw_ / 2, y0 + 37 * k, ct, cf, "#ffffff", anchor="center")
        # --- jump back in
        y = hy1 + gap
        row, row_title, lib = self.home_row_games()
        hf = self.font(12 * k, True)
        self.text(x0 + 4 * k, y + 12 * k, row_title, hf, T["muted"], anchor="w")
        if (self.cfg["favorites"] or self.cfg["lists"]) and not self.cfg["guest"]:
            nxt = self.home_row_next()
            cx_ = x0 + 4 * k + self.measure(hf, row_title) + 14 * k
            lab = "SHOW " + nxt[1] + "  ›"
            cw_ = self.measure(self.font(11.5 * k, True), lab) + 22 * k
            rid = "home_row"
            self.rr(cx_, y, cx_ + cw_, y + 24 * k, 12 * k, mix(T["panel2"], T["accent"], 0.35 if self.pressed == rid else 0.12))
            self.text(cx_ + cw_ / 2, y + 12 * k, lab, self.font(11.5 * k, True), T["accent"], anchor="center")
            self.region(rid, cx_, y - 4 * k, cx_ + cw_, y + 28 * k, tap=lambda: self.set_home_row(nxt[0]))
        y += 30 * k
        tw = tile_h * 2 / 3
        n = max(1, int((W_ + 12 * k) // (tw + 12 * k)) - 1)
        x = x0
        for gg in lib[:n]:
            rid = f"home_g_{gg['id']}"
            sel = g and gg["id"] == g["id"]
            if sel:
                bw_ = tw * 0.36
                self.rr(x + (tw - bw_) / 2, y + tile_h + 5 * k, x + (tw + bw_) / 2, y + tile_h + 10 * k, 3 * k, T["accent"])
            img = self.cover(gg, tw, tile_h)
            if img:
                c.create_image(x, y, image=img, anchor="nw")
            elif T.get("premium"):
                self.premium_cover(gg, x, y, x + tw, y + tile_h)
            else:
                self.generated_cover(gg, x, y, x + tw, y + tile_h)

            def pick(gid=gg["id"]):
                self.home_sel = gid
                self.focus_id = "home_play" if self.focus_visible else self.focus_id
                self.request_draw()
            self.region(rid, x, y, x + tw, y + tile_h, tap=pick)
            x += tw + 12 * k
        rid = "home_all"
        self.surface(x, y, x + tw, y + tile_h, 14 * k, mix(T["panel2"], T["accent"], 0.3) if self.pressed == rid else T["panel2"])
        self.text(x + tw / 2, y + tile_h / 2 - 10 * k, "▦", self.font(26 * k), T["accent"], anchor="center")
        self.text(x + tw / 2, y + tile_h / 2 + 22 * k, tr("All games"), self.font(13 * k, True), T["text"], anchor="center")
        self.region(rid, x, y, x + tw, y + tile_h, tap=lambda: self.set_tab("play"))
        # --- one-tap tools
        y += tile_h + gap
        cards = self.home_tool_cards()
        cols = 6 if W_ > 1000 * k else 3
        cw = (W_ - 12 * k * (cols - 1)) / cols
        ch = card_h if cols == 6 else (y1 - y - 12 * k) / 2
        for i, (rid, glyph, fb, title, sub, fn) in enumerate(cards):
            r_, cn = divmod(i, cols)
            cx0, cy0 = x0 + cn * (cw + 12 * k), y + r_ * (ch + 12 * k)
            if cy0 + 40 * k > y1:
                break
            on = rid == "home_focus" and self.focus
            self.surface(cx0, cy0, cx0 + cw, min(y1, cy0 + ch), 18 * k, T["accent"] if on else T["panel2"])
            isz = 38 * k
            self.cat_icon((rid, title, glyph, fb, sub), cx0 + 14 * k + isz / 2, cy0 + 14 * k + isz / 2, isz, on)
            self.text(cx0 + 14 * k + isz + 12 * k, cy0 + 14 * k + isz / 2, tr(title), self.font(15 * k, True),
                      T["accent_text"] if on else T["text"], anchor="w", maxw=cw - isz - 40 * k)
            self.text(cx0 + 16 * k, min(y1, cy0 + ch) - 18 * k, tr(sub), self.font(12 * k),
                      mix(T["accent_text"], T["accent"], 0.3) if on else T["muted"], anchor="w", maxw=cw - 30 * k)
            self.region(rid, cx0, cy0, cx0 + cw, min(y1, cy0 + ch), tap=fn)

    def draw_topbar(self, x0, W):
        """Big page title and a one-line blurb on the left; activity, battery, clock and window buttons on the right."""
        T, k, c = self.t, self.k, self.c
        P = 14 * k
        top = 12 * k
        row = 84 * k
        cy = top + row / 2
        # window buttons
        s, gap = 44 * k, 6 * k
        xr = W - P
        for rid, key, fn in (("hdr_close", "close", self.on_close),
                             ("hdr_hide", "hide", (self.hide if self.tray else self.root.iconify)),
                             ("hdr_full", "unfull" if self.cfg["fullscreen"] else "full", self.toggle_fullscreen)):
            xr -= s
            self.icon_button(rid, xr, cy - s / 2, s, key, fn)
            xr -= gap
        xr -= 8 * k
        # clock and battery
        cf = self.font(15 * k, True)
        clock = time.strftime("%H:%M")
        cw = self.measure(cf, clock)
        self.text(xr, cy, clock, cf, T["text"], anchor="e")
        xr -= cw + 16 * k
        p = self.power
        if p and p["battery"] and p["pct"] <= 100:
            low = p["pct"] < 20 and not p["ac"]
            bw_, bh_ = 30 * k, 15 * k
            label = f"{p['pct']}%"
            lw_ = self.measure(cf, label)
            self.text(xr, cy, label, cf, T["danger"] if low else T["text"], anchor="e")
            bx1 = xr - lw_ - 8 * k
            bx0 = bx1 - bw_
            col = T["danger"] if low else T["good"] if p["ac"] else T["text"]
            self.rr(bx0, cy - bh_ / 2, bx1, cy + bh_ / 2, 4 * k, "", outline=mix(T["bg"], T["text"], 0.6), width=max(1, 1.5 * k))
            c.create_rectangle(bx1 + 1 * k, cy - 3 * k, bx1 + 3 * k, cy + 3 * k, fill=mix(T["bg"], T["text"], 0.6), outline="")
            fw = max(2 * k, (bw_ - 6 * k) * p["pct"] / 100)
            self.rr(bx0 + 3 * k, cy - bh_ / 2 + 3 * k, bx0 + 3 * k + fw, cy + bh_ / 2 - 3 * k, 2 * k, col)
            if p["ac"]:
                self.text(bx0 - 6 * k, cy, "⚡", self.font(13 * k), T["good"], anchor="e")
                bx0 -= 18 * k
            xr = bx0 - 18 * k
        # Focus mode lives here now
        if self.tab == "play":
            on = bool(self.focus)
            label = "FOCUSING…" if self.focus_busy else ("FOCUS ON" if on else "FOCUS MODE")
            ff = self.font(13.5 * k, True)
            fw_ = self.measure(ff, label) + 40 * k
            self.button("focus_btn", xr - fw_, cy - 22 * k, xr, cy + 22 * k, label, self.focus_toggle,
                        style="accent" if on else "normal", size=13.5 * k)
            if self.pad_on and not self.focus_busy:
                self.pad_badge(xr - fw_ - 16 * k, cy, "Y", 12 * k)
                xr -= 30 * k
            xr -= fw_ + 16 * k
            bs_ = 44 * k
            for rid, glyph, fn, sz in (("lib_reload", "↻", self.load_library, 18), ("lib_add", "+", self.add_game, 21),
                                       ("lib_search", "⌕", self.open_find, 21)):
                self.button(rid, xr - bs_, cy - bs_ / 2, xr, cy + bs_ / 2, glyph, fn, size=sz * k)
                xr -= bs_ + 8 * k
            xr -= 8 * k
        # title, then blurb / what's happening
        tx = x0 + 6 * k
        title = tr(TAB_TITLES[self.tab])
        if self.tab == "play" and self.library:
            n = len(self.library)
        else:
            n = None
        tf = self.font(32 * k, True, display=True)
        self.text(tx, cy - 6 * k, title, tf, T["text"], anchor="sw", maxw=xr - tx - P)
        if n:
            nx = tx + self.measure(tf, title) + 12 * k
            self.text(nx, cy - 10 * k, f"{n}", self.font(16 * k, True), T["muted"], anchor="sw")
        sf = self.font(13.5 * k)
        if self.busy:
            r = 8 * k
            self.spinner(tx + r, cy + 14 * k, r)
            self.text(tx + 2 * r + 10 * k, cy + 14 * k, self.busy + "…", sf, T["text"], anchor="w", maxw=xr - tx - 3 * P)
        else:
            blurb = tr(TAB_BLURBS[self.tab])
            if self.focus and self.tab == "play":
                f = self.focus
                blurb = (f"Focus on · {len(f['hwnds'])} windows minimized · {len(f['throttled'])} apps slowed"
                         f" · {fmt_duration(time.time() - f['start'])}")
            self.text(tx, cy + 14 * k, blurb, sf, T["muted"], anchor="w", maxw=xr - tx - P)
            if self.log:
                ts, tag, msg = self.log[-1]
                bw2 = self.measure(sf, blurb) + 40 * k
                lx = tx + bw2
                if xr - lx > 200 * k:
                    self.c.create_oval(lx - 18 * k, cy + 11 * k, lx - 12 * k, cy + 17 * k, fill=mix(T["bg"], T["muted"], 0.7), outline="")
                    self.text(lx, cy + 14 * k, f"{msg}", sf, mix(T["muted"], T["bg"], 0.25), anchor="w", maxw=xr - lx - P)
                    self.region("log", lx, cy, xr - P, cy + 28 * k, tap=lambda: self.open_page("log"), focus=False)
        return top + row + 8 * k

    def draw_header(self, W):
        T, k, c = self.t, self.k, self.c
        P = 14 * k
        row = 70 * k
        cy = row / 2
        x = P + 4 * k
        m = 36 * k  # the V mark
        for pts, col in ((MARK_LEFT, T["accent"]), (MARK_RIGHT, T["accent2"])):
            c.create_polygon([v for px, py in pts for v in (x + px * m, cy - m / 2 + py * m)], fill=col, outline="")
        x += m + 12 * k
        prem = bool(T.get("premium"))
        f = self.font(25 * k if prem else 27 * k, True, display=prem)
        for ch in "VANTA":  # letter-spaced wordmark
            c.create_text(x, cy, text=ch, font=f, fill=T["text"], anchor="w")
            x += f.measure(ch) + (7 if prem else 5) * k
        if IS_GO:
            x += self.go_badge(x + 4 * k, cy) + 8 * k
        left_end = x + P
        s, gap = 48 * k, 8 * k
        buttons = [("close", "close", self.on_close), ("hide", "hide", (self.hide if self.tray else self.root.iconify)),
                   ("full", "unfull" if self.cfg["fullscreen"] else "full", self.toggle_fullscreen),
                   ("settings", "settings", lambda: self.open_page("settings")), ("menu", "menu", lambda: self.open_page("menu"))]
        xr = W - P
        for rid, key, fn in buttons:
            xr -= s
            self.icon_button(f"hdr_{rid}", xr, cy - s / 2, s, key, fn)
            xr -= gap
        # tabs: next to the logo when they fit, otherwise on their own row
        tf = self.font(13.5 * k, True)
        LANG["code"] = self.cfg["lang"]
        widths = [self.measure(tf, tr(label)) + 26 * k for _, label in TABS]
        total = sum(widths) + 8 * k
        if total <= xr - P - left_end:
            tx0, ty, hh = left_end + (xr - P - left_end - total) / 2, cy, row
        else:
            total = min(total, W - 2 * P)
            scale = (W - 2 * P - 8 * k) / (sum(widths)) if sum(widths) + 8 * k > W - 2 * P else 1
            widths = [w * scale for w in widths]
            tx0, ty, hh = (W - total) / 2, row + 26 * k, row + 58 * k
        th = 48 * k
        if T.get("premium"):
            rail = mix(T["bg"], T["panel"], 0.75)
            self.rr(tx0, ty - th / 2, tx0 + total, ty + th / 2, th / 2, rail, outline=mix(rail, T["text"], 0.07), width=max(1, k))
        else:
            self.rr(tx0, ty - th / 2, tx0 + total, ty + th / 2, th / 2, T["panel"])
        x = tx0 + 4 * k
        xs = [tx0 + 4 * k + sum(widths[:i]) for i in range(len(widths))]
        ai = next((i for i, (tid, _) in enumerate(TABS) if tid == self.tab), 0)
        self.tab_ind, moving = self.glide(self.tab_ind, [xs[ai], widths[ai]], speed=18)
        if moving:
            self.motion_frame("all")
        ix, iw = self.tab_ind
        self.rr(ix, ty - th / 2 + 4 * k, ix + iw, ty + th / 2 - 4 * k, th / 2 - 4 * k, T["accent"])
        for (tid, label), w in zip(TABS, widths):
            on = tid == self.tab and not moving
            rid = f"tab_{tid}"
            if self.pressed == rid and tid != self.tab:
                self.rr(x, ty - th / 2 + 4 * k, x + w, ty + th / 2 - 4 * k, th / 2 - 4 * k, mix(T["panel"], T["accent"], 0.3))
            if tid == self.tab and moving:
                on = abs(ix - x) < w * 0.5
            self.text(x + w / 2, ty, tr(label), tf, T["accent_text"] if on else (T["muted"] if T.get("premium") else T["text"]),
                      anchor="center", maxw=w - 8 * k)
            self.region(rid, x, ty - th / 2, x + w, ty + th / 2, tap=lambda t=tid: self.set_tab(t))
            x += w
        if self.pad_on:
            self.pad_badge(tx0 - 18 * k, ty, "LB", 13 * k)
            self.pad_badge(tx0 + total + 18 * k, ty, "RB", 13 * k)
        return hh

    # ---- play tab (hub)
    def draw_tab_play(self, x0, y0, x1, y1, land):
        k = self.k
        P = 14 * k
        if land:
            dw = min(520 * k, (x1 - x0) * (0.38 if self.cfg["layout"] == "rail" else 0.33))
            self.draw_library(x0, y0, x1 - dw - P, y1)
            self.draw_game_detail(x1 - dw, y0, x1, y1, tall=True)
        else:
            dh = min(330 * k, (y1 - y0) * 0.3)
            self.draw_game_detail(x0, y0, x1, y0 + dh, tall=False)
            self.draw_library(x0, y0 + dh + P, x1, y1)

    def draw_focus_bar(self, x0, y0, x1, y1):
        T, k, c = self.t, self.k, self.c
        f = self.focus
        on = bool(f)
        rid = "focus_btn"
        fill = T["accent"] if on else T["panel"]
        if self.pressed == rid:
            fill = mix(fill, "#ffffff" if on else T["accent"], 0.3)
        if on:
            self.rr(x0, y0, x1, y1, 18 * k, fill)
        else:
            self.surface(x0, y0, x1, y1, 18 * k, fill)
        fg = T["accent_text"] if on else T["text"]
        sub = mix(fg, fill, 0.3) if on else T["muted"]
        P = 18 * k
        cy = (y0 + y1) / 2
        bf = self.font(min(20 * k, (y1 - y0) * 0.32), True)
        title = "FOCUS MODE ON" if on else "FOCUS MODE"
        if self.focus_busy:
            title = "FOCUSING…"
            self.spinner(x1 - P - 12 * k, cy, 12 * k)
        self.text(x0 + P, cy - 1 * k, title, bf, fg, anchor="sw")
        if on:
            detail = (f"{len(f['hwnds'])} windows minimized · {len(f['throttled'])} apps in efficiency mode"
                      + (f" · closed {len(f['closed'])}" if f["closed"] else "") + f" · {fmt_duration(time.time() - f['start'])}")
        else:
            detail = "One tap: minimize windows, slow down background apps and free RAM. Tap again to undo."
        self.text(x0 + P, cy + 1 * k, detail, self.font(min(13 * k, (y1 - y0) * 0.22)), sub, anchor="nw", maxw=x1 - x0 - 2 * P - 40 * k)
        if self.pad_on and not self.focus_busy:
            self.pad_badge(x1 - P - 12 * k, cy, "Y", 13 * k)
        self.region(rid, x0, y0, x1, y1, tap=self.focus_toggle)

    def draw_library(self, x0, y0, x1, y1):
        T, k, c = self.t, self.k, self.c
        P = 14 * k
        fh = 76 * k
        if self.suspended and self.game:
            self.draw_suspended_bar(x0, y0, x1, y0 + fh)
            y = y0 + fh + P
        elif self.cfg["layout"] in ("rail", "console"):
            y = y0
        else:
            self.draw_focus_bar(x0, y0, x1, y0 + fh)
            y = y0 + fh + P
        th = 46 * k
        sources = sorted({g["source"] for g in self.library or []})
        filters = [("all", "ALL"), ("fav", "★ FAVORITES")] + [(s_.lower(), s_.upper()) for s_ in sources]
        if self.cfg["lists"]:
            cur = self.cfg["lib_filter"]
            filters.insert(2, ("__list", (cur[5:].upper()[:14] if cur.startswith("list:") else "LISTS") + "  ›"))
        cur = self.cfg["lib_filter"]
        sm = dict((c_, t_) for c_, t_, _ in self.SMART)
        filters.insert(2, ("__smart", (sm.get(cur[6:], "SMART").upper()[:14] if cur.startswith("smart:") else "SMART") + "  ›"))
        if self.cfg["genres"]:
            filters.insert(3, ("__genre", (cur[6:].upper()[:14] if cur.startswith("genre:") else "GENRE") + "  ›"))
        if len(filters) > 6:  # many stores: one chip that steps through them
            cur = self.cfg["lib_filter"]
            label = cur.upper() if cur not in ("all", "fav") and not cur.startswith(("list:", "smart:", "genre:")) else "STORE"
            keep = 4 if self.cfg["lists"] else 3
            filters = filters[:keep] + [("__store", f"{label}  ›")]
        if self.lib_query:
            filters = [("__clear", f"“{self.lib_query[:12]}”  ✕")] + filters[:5]
        bw = 52 * k
        rail = self.cfg["layout"] == "rail"
        sort_w = min(360 * k, (x1 - x0) * (0.4 if rail else 0.36))
        fx1 = x1 - sort_w - 3 * bw - 4 * 10 * k if not rail else x1 - sort_w - 10 * k
        self.segmented("lfilter", x0, y, fx1, y + th, filters[:6], self.cfg["lib_filter"], lambda v: self.set_lib("lib_filter", v))
        self.segmented("lsort", fx1 + 10 * k, y, fx1 + 10 * k + sort_w, y + th,
                       [("recent", "RECENT"), ("name", "A–Z"), ("time", "PLAYED"), ("size", "SIZE")], self.cfg["lib_sort"],
                       lambda v: self.set_lib("lib_sort", v))
        if not rail:
            self.button("lib_search", x1 - 3 * bw - 20 * k, y, x1 - 2 * bw - 20 * k, y + th, "⌕", self.search_library, size=22 * k)
            self.button("lib_add", x1 - 2 * bw - 10 * k, y, x1 - bw - 10 * k, y + th, "+", self.add_game, size=22 * k)
            self.button("lib_reload", x1 - bw, y, x1, y + th, "↻", self.load_library, size=20 * k)
        y += th + P
        games = self.lib_games()
        if self.library is None or (self.lib_loading and not games):
            if T.get("premium"):
                self.draw_skeleton(x0, y, x1, y1)
                return
            self.spinner((x0 + x1) / 2, (y + y1) / 2, 20 * k)
            self.text((x0 + x1) / 2, (y + y1) / 2 + 40 * k, "Finding your games…", self.font(15 * k), T["muted"], anchor="center")
            return
        if not games:
            msg = ("No favorites yet. Pick a game and tap ★." if self.cfg["lib_filter"] == "fav" else
                   "No games found from Steam, Epic or GOG. Tap + to add any game's .exe.")
            self.text((x0 + x1) / 2, y + 60 * k, msg, self.font(15 * k), T["muted"], anchor="center", maxw=x1 - x0 - 2 * P)
            return
        self._libgrid = (x0, y, x1, y1, games)
        c.extra_tag = "libgrid"
        try:
            self.draw_lib_grid(x0, y, x1, y1, games)
        finally:
            c.extra_tag = None

    def draw_lib_grid(self, x0, y, x1, y1, games):
        T, k, c = self.t, self.k, self.c
        gap = 12 * k
        cols = max(3, int((x1 - x0 + gap) // ({"rail": 150, "console": 165}.get(self.cfg["layout"], 200) * k + gap)))
        tw = (x1 - x0 - gap * (cols - 1)) / cols
        tile_h = tw * 1.5
        rows = math.ceil(len(games) / cols)
        off = self.scroll_area("lib", x0, y, x1, y1, rows * (tile_h + gap))
        self.clip_to(y, y1)
        favs = set(self.cfg["favorites"])
        playing = (self.game or {}).get("hub", {}) or {}
        for i, g in enumerate(games):
            r_, cn = divmod(i, cols)
            gx0 = x0 + cn * (tw + gap)
            gy0 = y + r_ * (tile_h + gap) - off
            gy1 = gy0 + tile_h
            if gy1 < y or gy0 > y1:
                continue
            sel = g["id"] == self.lib_sel
            prem = bool(T.get("premium"))
            if prem:
                if sel:  # the selected tile lifts a little
                    lift = 6 * k
                    gy0 -= lift
                    gy1 -= lift
                drop = (12 if sel else 6) * k
                rad = max(6, tw * 0.05)
                self.rr(gx0 + 3 * k, gy0 + drop, gx0 + tw - 3 * k, gy1 + drop, rad, mix(T["bg"], "#000000", 0.55))
            img = self.cover(g, tw, tile_h)
            if img:
                c.create_image(gx0, gy0, image=img, anchor="nw")
            elif prem:
                self.premium_cover(g, gx0, gy0, gx0 + tw, gy1)
            else:
                self.generated_cover(g, gx0, gy0, gx0 + tw, gy1)
            if self.find_preset(g["name"]) and g["id"] not in self.cfg["game_tune"]:
                bf = self.font(11 * k, True)
                if prem:
                    self.rr(gx0 + 10 * k, gy0 + 10 * k, gx0 + 28 * k + bf.measure("PRESET"), gy0 + 34 * k, 12 * k, T["accent"])
                    c.create_text(gx0 + 19 * k, gy0 + 22 * k, text="PRESET", font=bf, fill=T["accent_text"], anchor="w")
                else:
                    c.create_rectangle(gx0 + 8 * k, gy0 + 8 * k, gx0 + 16 * k + bf.measure("PRESET"), gy0 + 30 * k, fill=T["accent"], width=0)
                    c.create_text(gx0 + 12 * k, gy0 + 19 * k, text="PRESET", font=bf, fill=T["accent_text"], anchor="w")
            if g["id"] in favs:
                self.c.create_text(gx0 + tw - 14 * k, gy0 + 14 * k, text="★", font=self.font(20 * k, True),
                                   fill=T["warn"], anchor="ne")
            st = self.steam_state.get(g["id"].split(":", 1)[1]) if g["source"] == "Steam" else None
            if st and playing.get("id") != g["id"] and prem:
                label = st[0] + (f" {st[1]:.0f}%" if st[1] is not None else "")
                self.rr(gx0 + 10 * k, gy1 - 40 * k, gx0 + tw - 10 * k, gy1 - 12 * k, 14 * k, T["warn"])
                if st[1] is not None:
                    self.rr(gx0 + 10 * k, gy1 - 16 * k, gx0 + 10 * k + (tw - 20 * k) * st[1] / 100, gy1 - 12 * k, 2 * k, T["good"])
                self.c.create_text(gx0 + tw / 2, gy1 - 26 * k, text=label, font=self.font(11.5 * k, True), fill=text_on_hex(T["warn"]))
            elif st and playing.get("id") != g["id"]:
                label = st[0] + (f" {st[1]:.0f}%" if st[1] is not None else "")
                self.c.create_rectangle(gx0, gy1 - 30 * k, gx0 + tw, gy1, fill=T["warn"], width=0)
                if st[1] is not None:
                    self.c.create_rectangle(gx0, gy1 - 4 * k, gx0 + tw * st[1] / 100, gy1, fill=T["good"], width=0)
                self.c.create_text(gx0 + tw / 2, gy1 - 15 * k, text=label, font=self.font(12 * k, True), fill=text_on_hex(T["warn"]))
            if playing.get("id") == g["id"] and prem:
                self.rr(gx0 + 10 * k, gy1 - 40 * k, gx0 + tw - 10 * k, gy1 - 12 * k, 14 * k, T["accent2"])
                self.c.create_text(gx0 + tw / 2, gy1 - 26 * k, text="● PLAYING", font=self.font(12 * k, True), fill=text_on_hex(T["accent2"]))
            elif playing.get("id") == g["id"]:
                self.c.create_rectangle(gx0, gy1 - 30 * k, gx0 + tw, gy1, fill=T["accent2"], width=0)
                self.c.create_text(gx0 + tw / 2, gy1 - 15 * k, text="PLAYING", font=self.font(13 * k, True), fill=text_on_hex(T["accent2"]))
            if sel:
                # the picked game gets a small bar underneath, not a ring: rings belong to the controller's cursor only,
                # so the two can't be mistaken for each other
                bw_ = tw * 0.36
                self.rr(gx0 + (tw - bw_) / 2, gy1 + 6 * k, gx0 + (tw + bw_) / 2, gy1 + 11 * k, 3 * k, T["accent"])
            if self.pressed == f"g_{g['id']}":
                self.rr(gx0, gy0, gx0 + tw, gy1, 10 * k, "", outline=T["text"], width=max(2, 2 * k))
            elif self.hover_fill == f"g_{g['id']}":
                self.rr(gx0 - 3 * k, gy0 - 3 * k, gx0 + tw + 3 * k, gy1 + 3 * k, max(6, tw * 0.05) + 3 * k, "",
                        outline=mix(T["bg"], T["text"], 0.45), width=max(2, 2 * k))
            self.region(f"g_{g['id']}", gx0, gy0, gx0 + tw, gy1, tap=lambda gid=g["id"]: self.tap_game(gid), sid="lib")
        self.end_clip()
        self.scrollbar("lib", x1 + 6 * k, y, y1 - y)

    def draw_skeleton(self, x0, y0, x1, y1):
        """Placeholder tiles with a light sweep while the library loads."""
        T, k = self.t, self.k
        gap = 12 * k
        cols = max(3, int((x1 - x0 + gap) // ((150 if self.cfg["layout"] == "rail" else 200) * k + gap)))
        tw = (x1 - x0 - gap * (cols - 1)) / cols
        th = tw * 1.5
        sweep = (time.time() * 0.8) % 1.6 - 0.3
        base = mix(T["bg"], T["panel2"], 0.75)
        for i in range(cols * 2):
            r_, cn = divmod(i, cols)
            tx0, ty0 = x0 + cn * (tw + gap), y0 + r_ * (th + gap)
            if ty0 > y1:
                break
            pos = (cn + r_ * 0.5) / (cols + 1)
            glow = max(0.0, 1 - abs(pos - sweep) * 3.5)
            self.rr(tx0, ty0, tx0 + tw, min(y1, ty0 + th), max(6, tw * 0.05), mix(base, T["text"], 0.05 * glow))
            self.rr(tx0 + 14 * k, ty0 + th - 50 * k, tx0 + tw * 0.7, ty0 + th - 38 * k, 6 * k, mix(base, T["text"], 0.08 + 0.05 * glow))
        f_ = self.font(14 * k)
        lab = tr("Finding your games…")
        pw_ = self.measure(f_, lab) + 64 * k
        cx_, cy_ = (x0 + x1) / 2, min(y1 - 34 * k, y0 + th + gap / 2)
        self.rr(cx_ - pw_ / 2, cy_ - 18 * k, cx_ + pw_ / 2, cy_ + 18 * k, 18 * k, T["panel"], outline=T["line"], width=max(1, k))
        self.spinner(cx_ - pw_ / 2 + 22 * k, cy_, 7 * k)
        self.text(cx_ + 12 * k, cy_, lab, f_, T["text"], anchor="center")
        self.motion_frame("all")

    def premium_cover(self, g, x0, y0, x1, y1):
        """Art for games without a cover in the premium look: a soft gradient, a monogram and the title."""
        T, k, c = self.t, self.k, self.c
        w, h = x1 - x0, y1 - y0
        img = self.gen_art(g, w, h)
        if img:
            c.create_image(x0, y0, image=img, anchor="nw")
        else:
            self.rr(x0, y0, x1, y1, max(6, w * 0.05), T["panel2"])
        words = [w_ for w_ in re.split(r"[\s:_\-]+", g["name"]) if w_]
        initials = "".join(w_[0] for w_ in words[:2]).upper() or "?"
        c.create_text(x0 + w * 0.1, y0 + h * 0.1, text=initials, font=self.font(w * 0.26, True, display=True),
                      fill=mix("#ffffff", T["bg"], 0.12), anchor="nw")
        tf = self.font(max(10, w * 0.082), True, display=True)
        lines = self.wrap(g["name"], tf, w * 0.8)[:3]
        ls = tf.metrics("linespace")
        for j, ln in enumerate(lines):
            c.create_text(x0 + w * 0.1, y1 - h * 0.1 - (len(lines) - j) * ls - 14 * k, text=ln, font=tf, fill="#ffffff", anchor="nw")
        c.create_text(x0 + w * 0.1, y1 - h * 0.08, text=g["source"].upper(), font=self.font(10 * k, True),
                      fill=mix("#ffffff", T["bg"], 0.45), anchor="sw")

    def generated_cover(self, g, x0, y0, x1, y1):
        """Art for games without a cover: a colour from the name, its initials and title."""
        T, k, c = self.t, self.k, self.c
        h = sum(ord(ch) * (i + 1) for i, ch in enumerate(g["name"])) % 360 / 360
        r1, g1, b1 = colorsys.hsv_to_rgb(h, 0.55, 0.55 if T["dark"] else 0.85)
        r2, g2, b2 = colorsys.hsv_to_rgb((h + 0.12) % 1, 0.65, 0.3 if T["dark"] else 0.65)
        top, bot = "#%02x%02x%02x" % (int(r1 * 255), int(g1 * 255), int(b1 * 255)), "#%02x%02x%02x" % (int(r2 * 255), int(g2 * 255), int(b2 * 255))
        n = 10
        for i in range(n):
            c.create_rectangle(x0, y0 + (y1 - y0) * i / n, x1, y0 + (y1 - y0) * (i + 1) / n + 1, fill=mix(top, bot, i / (n - 1)), width=0)
        words = [w for w in re.split(r"[\s:_\-]+", g["name"]) if w]
        initials = "".join(w[0] for w in words[:2]).upper() or "?"
        w = x1 - x0
        c.create_text((x0 + x1) / 2, y0 + (y1 - y0) * 0.38, text=initials, font=self.font(w * 0.32, True), fill="#ffffff")
        tf = self.font(max(10, w * 0.085), True)
        for j, ln in enumerate(self.wrap(g["name"], tf, w - 20 * k)[:3]):
            c.create_text((x0 + x1) / 2, y0 + (y1 - y0) * 0.68 + j * tf.metrics("linespace"), text=ln, font=tf, fill="#ffffff")
        c.create_text(x0 + 10 * k, y1 - 10 * k, text=g["source"].upper(), font=self.font(10 * k, True), fill=mix("#ffffff", bot, 0.3),
                      anchor="sw")

    def draw_game_detail(self, x0, y0, x1, y1, tall):
        if self.t.get("premium") and tall:
            return self.draw_game_detail_premium(x0, y0, x1, y1)
        T, k, c = self.t, self.k, self.c
        P = 18 * k
        self.surface(x0, y0, x1, y1, 20 * k, T["panel"])
        g = self.selected_game()
        if not g:
            self.text((x0 + x1) / 2, (y0 + y1) / 2, "Pick a game", self.font(18 * k, True), T["muted"], anchor="center")
            return
        last, mins = self.game_stats(g)
        prof = self.cfg["game_profiles"].get(g["id"], "")
        running = bool(self.game and (self.game.get("hub") or {}).get("id") == g["id"])
        play_h = 70 * k
        if tall:
            cw = x1 - x0 - 2 * P
            ch = min(cw * 1.5, (y1 - y0) * 0.45)
            cw = ch / 1.5
            cx0 = (x0 + x1 - cw) / 2
            hw, hh = int(x1 - x0 - 4 * k), int(ch + 2 * P)
            hero = self.hero(g, hw, hh)
            if hero:
                c.create_image(x0 + 2 * k, y0 + 2 * k, image=hero, anchor="nw")
            img = self.cover(g, cw, ch)
            if img:
                c.create_image(cx0, y0 + P, image=img, anchor="nw")
            else:
                self.generated_cover(g, cx0, y0 + P, cx0 + cw, y0 + P + ch)
            y = y0 + P + ch + P
            tx0, tx1 = x0 + P, x1 - P
        else:
            ch = y1 - y0 - 2 * P
            cw = ch / 1.5
            img = self.cover(g, cw, ch)
            if img:
                c.create_image(x0 + P, y0 + P, image=img, anchor="nw")
            else:
                self.generated_cover(g, x0 + P, y0 + P, x0 + P + cw, y0 + P + ch)
            y = y0 + P
            tx0, tx1 = x0 + 2 * P + cw, x1 - P
        nf = self.font(min(24 * k, (tx1 - tx0) / 12), True)
        for ln in self.wrap(g["name"], nf, tx1 - tx0)[:2]:
            self.text(tx0, y, ln, nf, T["text"], maxw=tx1 - tx0)
            y += nf.metrics("linespace")
        df = self.font(13.5 * k)
        bits = [g["source"]]
        if g["size"]:
            bits.append(fmt_bytes(g["size"]))
        bits.append(f"played {fmt_duration(mins * 60)}" if mins else "not played yet")
        ach = self.achievements_for(g)
        if ach:
            bits.append(f"🏆 {ach[0]}/{ach[1]}")
        if last:
            bits.append(f"last {fmt_ago(last)}")
        self.text(tx0, y + 4 * k, " · ".join(bits), df, T["muted"], maxw=tx1 - tx0)
        y += df.metrics("linespace") + 12 * k
        bh = 50 * k
        gap = 10 * k
        pw = (tx1 - tx0 - 2 * gap) / 3
        tuned = bool(self.cfg["game_tune"].get(g["id"]) or prof)
        self.button("d_prof", tx0, y, tx0 + pw, y + bh, self.tune_label(g["id"], g["name"]),
                    lambda: self.open_tune(g["id"], g["name"]), style="accent" if tuned else "normal", size=12 * k)
        fav = g["id"] in self.cfg["favorites"]
        self.button("d_fav", tx0 + pw + gap, y, tx0 + 2 * pw + gap, y + bh, "★ FAVORITE" if fav else "☆ FAVORITE",
                    lambda: self.toggle_favorite(g["id"]), size=12.5 * k)
        if g["source"] == "Added":
            armed = self.is_armed(f"rm_{g['id']}")
            self.button("d_extra", tx1 - pw, y, tx1, y + bh, "TAP AGAIN" if armed else "REMOVE", lambda: self.remove_game(g),
                        style="danger" if armed else "normal", size=12.5 * k)
        elif g.get("store"):
            self.button("d_extra", tx1 - pw, y, tx1, y + bh, "STEAM PAGE", lambda: systools.open_target(g["store"]), size=12.5 * k)
        y += bh + 12 * k
        room = (y1 - P - play_h - 12 * k) - y if tall else 0
        if room >= bh and not str(g["id"]).startswith(("sample:", "rom:")):
            busy = self.save_busy == g["id"]
            self.button("d_backup", tx0, y, tx0 + pw, y + bh, "BACKING UP…" if busy else "BACK UP SAVES", lambda: self.save_backup(g),
                        size=12 * k)
            armed = self.is_armed(f"restore_{g['id']}")
            self.button("d_restore", tx0 + pw + gap, y, tx0 + 2 * pw + gap, y + bh, "TAP AGAIN" if armed else "RESTORE SAVES",
                        lambda: self.confirm(f"restore_{g['id']}", lambda: self.save_backup(g, restore=True),
                                             f"Tap again to put back the last backup of {g['name']}'s saves"),
                        style="danger" if armed else "normal", size=12 * k)
            if g["source"] == "Steam":
                target = self.move_target(g)
                if self.move_busy and self.move_busy[0] == g["id"]:
                    mlabel = f"MOVING {self.move_busy[1]:.0f}%"
                elif target:
                    mlabel = "TAP AGAIN" if self.is_armed(f"move_{g['id']}") else f"MOVE TO {target[:2].upper()}"
                else:
                    mlabel = None
                if mlabel:
                    self.button("d_move", tx1 - pw, y, tx1, y + bh, mlabel, lambda: self.move_game(g, target), size=12 * k)
            else:
                self.button("d_lists", tx1 - pw, y, tx1, y + bh, "+ LISTS", lambda: self.open_lists(g), size=12 * k)
            y += bh + 12 * k
            if g["source"] == "Steam" and (y1 - P - play_h - 12 * k) - y >= bh:
                self.button("d_lists", tx0, y, tx0 + pw, y + bh, "+ LISTS", lambda: self.open_lists(g), size=12 * k)
                y += bh + 12 * k
        py0 = y1 - P - play_h if tall else y
        py1 = py0 + play_h if tall else min(y1 - P, y + play_h)
        label = "PLAYING" if running else ("PLAY" + ("  ·  FOCUS" if self.cfg["focus_on_play"] and not self.focus else ""))
        self.button("d_play", tx0, py0, tx1, py1, label, (lambda: None) if running else (lambda: self.play(g)), style="accent",
                    badge="X", size=min(22 * k, (py1 - py0) * 0.38))
        if tall and py0 - y > 60 * k:
            note = ("Press Play: " + ", ".join(filter(None, [
                "focus mode" if self.cfg["focus_on_play"] else "",
                ("its own profile" if prof else "performance modes") if (prof or self.cfg["game_perf_auto"]) else "",
                "FPS counter" if self.cfg["fps_counter"] else ""])) + " start with the game, and stop when it closes.")
            if note.startswith("Press Play:  start"):
                note = "Press Play to start. Turn on focus mode or a profile for extra speed."
            for i, ln in enumerate(self.wrap(note, df, tx1 - tx0)[:4]):
                self.text(tx0, y + i * df.metrics("linespace"), ln, df, T["muted"])

    def chip(self, x, y, text, f, fg=None, fill=None):
        """A small rounded label; returns its width."""
        T, k = self.t, self.k
        w = self.measure(f, text) + 22 * k
        h = f.metrics("linespace") + 10 * k
        fill = fill or mix(T["bg"], T["panel2"], 0.85)
        self.rr(x, y, x + w, y + h, h / 2, fill, outline=mix(fill, T["text"], 0.08), width=max(1, k))
        self.text(x + w / 2, y + h / 2, text, f, fg or T["text"], anchor="center")
        return w

    def draw_game_detail_premium(self, x0, y0, x1, y1):
        """The selected game, art first: a banner that fades into the backdrop, the cover, title, chips and a big Play."""
        T, k, c = self.t, self.k, self.c
        P = 18 * k
        g = self.selected_game()
        if not g:
            self.text((x0 + x1) / 2, (y0 + y1) / 2, "Pick a game", self.font(18 * k, True, display=True), T["muted"], anchor="center")
            return
        self.update_game_colors(g)
        last, mins = self.game_stats(g)
        prof = self.cfg["game_profiles"].get(g["id"], "")
        running = bool(self.game and (self.game.get("hub") or {}).get("id") == g["id"])
        W_ = x1 - x0
        # banner
        bh = min(W_ * 0.62, (y1 - y0) * 0.36)
        hero = self.hero(g, int(W_), int(bh))
        if hero:
            c.create_image(x0, y0, image=hero, anchor="nw")
        # cover overlapping the bottom of the banner
        cw = min(W_ * 0.32, 150 * k)
        ch = cw * 1.5
        cx0, cy0 = x0 + P, y0 + bh - ch * 0.55 if hero else y0 + P
        sh, pad = self.shadow(cw, ch, max(6, cw * 0.05))
        if sh:
            c.create_image(cx0 - pad, cy0 - pad, image=sh, anchor="nw")
        img = self.cover(g, cw, ch)
        if img:
            c.create_image(cx0, cy0, image=img, anchor="nw")
        else:
            self.premium_cover(g, cx0, cy0, cx0 + cw, cy0 + ch)
        # title beside the cover
        tx0, tx1 = cx0 + cw + 16 * k, x1 - P
        nf = self.font(min(26 * k, (tx1 - tx0) / 9), True, display=True)
        lines = self.wrap(g["name"], nf, tx1 - tx0)[:3]
        ty = cy0 + ch - len(lines) * nf.metrics("linespace") - 30 * k
        for ln in lines:
            self.text(tx0, ty, ln, nf, T["text"], maxw=tx1 - tx0)
            ty += nf.metrics("linespace")
        sub = g["source"] + (f"  ·  {fmt_bytes(g['size'])}" if g.get("size") else "")
        self.text(tx0, ty + 6 * k, sub, self.font(13 * k), T["muted"], maxw=tx1 - tx0)
        y = cy0 + ch + 16 * k
        # chips
        cf = self.font(12 * k, True)
        chips = [f"⏱ {fmt_duration(mins * 60)}" if mins else "New", f"Last played {fmt_ago(last)}" if last else None]
        ach = self.achievements_for(g)
        if ach:
            chips.append(f"🏆 {ach[0]}/{ach[1]}")
        if self.find_preset(g["name"]):
            chips.append("Preset ready")
        if prof or self.cfg["game_tune"].get(g["id"]):
            chips.append("Tuned")
        rv = self.review_chip(g)
        if rv:
            chips.insert(1, rv)
        if g["id"] in self.cfg["finished"]:
            chips.insert(1, "✓ Finished")
        cx = x0 + P
        for t_ in [t_ for t_ in chips if t_]:
            w_ = self.measure(cf, t_) + 22 * k
            if cx + w_ > x1 - P:
                break
            cx += self.chip(cx, y, t_, cf, fg=T["accent"] if t_ in ("Preset ready", "Tuned") else T["text"]) + 8 * k
        y += cf.metrics("linespace") + 10 * k + 18 * k
        # actions
        bh_ = 46 * k
        gap = 10 * k
        bw = (x1 - x0 - 2 * P - 3 * gap) / 4
        bx = x0 + P
        tuned = bool(self.cfg["game_tune"].get(g["id"]) or prof)
        fav = g["id"] in self.cfg["favorites"]
        acts = [("d_prof", self.tune_label(g["id"], g["name"]).replace("⚙ ", ""), lambda: self.open_tune(g["id"], g["name"]),
                 "accent" if tuned else "normal"),
                ("d_fav", "★ FAVORITE" if fav else "☆ FAVORITE", lambda: self.toggle_favorite(g["id"]), "normal")]
        if g["source"] == "Added":
            armed = self.is_armed(f"rm_{g['id']}")
            acts.append(("d_extra", "TAP AGAIN" if armed else "REMOVE", lambda: self.remove_game(g), "danger" if armed else "normal"))
        elif g.get("store"):
            acts.append(("d_extra", "STORE PAGE", lambda: systools.open_target(g["store"]), "normal"))
        else:
            acts.append(("d_lists", "+ LISTS", lambda: self.open_lists(g), "normal"))
        has_note = bool(self.note_of(g["id"]))
        acts.append(("d_info", ("✎ " if has_note else "") + ("NOTES & STATS" if bw > 150 * k else "INFO"),
                     lambda: self.open_gameinfo(g), "normal"))
        for i, (rid, label, fn, st) in enumerate(acts):
            self.button(rid, bx + i * (bw + gap), y, bx + i * (bw + gap) + bw, y + bh_, label, fn, style=st if st != "accent" else "normal",
                        size=11.5 * k)
        y += bh_ + gap
        play_h = 64 * k
        py0 = y1 - P - play_h
        if py0 - y >= bh_ and not str(g["id"]).startswith(("sample:", "rom:")):
            busy = self.save_busy == g["id"]
            armed = self.is_armed(f"restore_{g['id']}")
            row = [("d_backup", "BACKING UP…" if busy else "BACK UP SAVES", lambda: self.save_backup(g), "normal"),
                   ("d_restore", "TAP AGAIN" if armed else "RESTORE SAVES",
                    lambda: self.confirm(f"restore_{g['id']}", lambda: self.save_backup(g, restore=True),
                                         f"Tap again to put back the last backup of {g['name']}'s saves"), "danger" if armed else "normal")]
            if g["source"] == "Steam":
                target = self.move_target(g)
                if self.move_busy and self.move_busy[0] == g["id"]:
                    row.append(("d_move", f"MOVING {self.move_busy[1]:.0f}%", lambda: None, "normal"))
                elif target:
                    row.append(("d_move", "TAP AGAIN" if self.is_armed(f"move_{g['id']}") else f"MOVE TO {target[:2].upper()}",
                                lambda: self.move_game(g, target), "normal"))
                else:
                    row.append(("d_lists", "+ LISTS", lambda: self.open_lists(g), "normal"))
            for i, (rid, label, fn, st) in enumerate(row):
                self.button(rid, bx + i * (bw + gap), y, bx + i * (bw + gap) + bw, y + bh_, label, fn, style=st, size=11.5 * k)
            y += bh_ + gap
        # stat tiles in the space above Play
        th_ = 78 * k
        if py0 - 12 * k - y >= th_:
            ses = [s_ for s_ in self.sessions_for(g["id"], g["name"]) if s_.get("fps")]
            b = self.batt or {}
            est = systools.battery_estimate(self.sessions_for(g["id"], g["name"]), b.get("full_mwh"))
            tiles = [("PLAYED", fmt_duration(mins * 60) if mins else "—"),
                     ("LAST SESSION", f"{ses[0]['fps']:.0f} FPS" if ses else "—"),
                     ("ON A CHARGE", f"~{fmt_duration(est[0] * 3600)}" if est else "—")]
            tw_ = (x1 - x0 - 2 * P - 2 * gap) / 3
            ty_ = py0 - 14 * k - th_
            lf_, vf_ = self.font(10.5 * k, True), self.font(20 * k, True, display=True)
            for i, (lab, val) in enumerate(tiles):
                tx_ = x0 + P + i * (tw_ + gap)
                fill = mix(T["bg"], T["panel2"], 0.8)
                self.rr(tx_, ty_, tx_ + tw_, ty_ + th_, 14 * k, fill, outline=mix(fill, T["text"], 0.07), width=max(1, k))
                self.text(tx_ + 14 * k, ty_ + 14 * k, lab, lf_, T["muted"], maxw=tw_ - 24 * k)
                self.text(tx_ + 14 * k, ty_ + th_ - 14 * k, val, vf_, T["text"] if val != "—" else T["muted"], anchor="sw", maxw=tw_ - 24 * k)
        # play
        label = "PLAYING" if running else ("▶   PLAY" + ("  ·  FOCUS" if self.cfg["focus_on_play"] and not self.focus else ""))
        self.button("d_play", x0 + P, py0, x1 - P, py0 + play_h, label, (lambda: None) if running else (lambda: self.play(g)),
                    style="accent", badge="X", size=min(21 * k, play_h * 0.34))

    # ---- memory tab
    def draw_tab_memory(self, x0, y0, x1, y1, land):
        k = self.k
        P = 14 * k
        if land:
            lw = (x1 - x0 - P) * 0.57
            mh = (y1 - y0) * 0.46
            self.draw_memory(x0, y0, x0 + lw, y0 + mh)
            self.draw_tiles(x0, y0 + mh + P, x0 + lw, y1, 4)
            self.draw_processes(x0 + lw + P, y0, x1, y1)
        else:
            mh = max(230 * k, (y1 - y0) * 0.27)
            th = min(2 * 104 * k + P, (y1 - y0) * 0.3)
            self.draw_memory(x0, y0, x1, y0 + mh)
            self.draw_tiles(x0, y0 + mh + P, x1, y0 + mh + P + th, 4)
            self.draw_processes(x0, y0 + mh + 2 * P + th, x1, y1)

    def draw_memory(self, x0, y0, x1, y1):
        T, k, c = self.t, self.k, self.c
        P = 16 * k
        st, lists = self.status, self.lists
        total, avail = st.ullTotalPhys, st.ullAvailPhys
        used = total - avail
        frac = used / max(1, total)
        load = T["accent"] if frac < 0.7 else T["warn"] if frac < 0.88 else T["danger"]
        top = self.card(x0, y0, x1, y1, "MEMORY", f"{fmt_bytes(avail)} available")
        ch, cw = y1 - P - top, x1 - x0 - 2 * P
        D = max(60 * k, min(ch, cw * 0.34, 240 * k))
        gx, gy = x0 + P, top + (ch - D) / 2
        th = max(6, D * 0.1)
        c.create_oval(gx + th / 2, gy + th / 2, gx + D - th / 2, gy + D - th / 2, outline=T["panel2"], width=th)
        if frac > 0.003:
            c.create_arc(gx + th / 2, gy + th / 2, gx + D - th / 2, gy + D - th / 2, start=90, extent=-359.9 * frac,
                         style="arc", outline=load, width=th)
        c.create_text(gx + D / 2, gy + D / 2 - D * 0.06, text=f"{frac * 100:.0f}%", font=self.font(D * 0.25, True), fill=T["text"])
        c.create_text(gx + D / 2, gy + D / 2 + D * 0.16, text="in use", font=self.font(max(9, D * 0.085)), fill=T["muted"])
        rx0, rx1 = gx + D + P * 1.3, x1 - P
        rw = rx1 - rx0
        y = top
        big = self.font(min(30 * k, rw / 8), True)
        small = self.font(min(15 * k, rw / 16))
        used_s = fmt_bytes(used)
        self.text(rx0, y, used_s, big, T["text"])
        self.text(rx0 + big.measure(used_s + " "), y + big.metrics("ascent") - small.metrics("ascent"),
                  f"of {fmt_bytes(total)} used", small, T["muted"], maxw=rw - big.measure(used_s + " "))
        y += big.metrics("linespace") + P * 0.5
        if lists:
            other = max(0, total - lists["free"] - lists["standby"] - lists["modified"])
            segs = [("In use", other, T["accent2"]), ("Modified", lists["modified"], T["warn"]),
                    ("Standby", lists["standby"], T["accent"]), ("Free", lists["free"], T["good"])]
        else:
            segs = [("In use", used, load), ("Available", avail, T["good"])]
        bh = 16 * k
        if y + bh <= y1 - P:
            self.rr(rx0, y, rx1, y + bh, bh / 2, T["panel2"])
            x = rx0
            for _, val, col in segs:
                w = rw * val / max(1, total)
                if w >= 1:
                    self.rr(x, y, x + w, y + bh, min(bh / 2, w / 2), col)
                x += w
            y += bh + P * 0.6
        lf = self.font(min(13.5 * k, rw / 22))
        lx, lh = rx0, lf.metrics("linespace")
        if y + lh <= y1 - P:
            for name, val, col in segs:
                label = f"{name} {fmt_bytes(val)}"
                w = lh * 0.9 + lf.measure(label) + P
                if lx + w > rx1 and lx > rx0:
                    lx, y = rx0, y + lh + 4 * k
                    if y + lh > y1 - P:
                        break
                r = lh * 0.28
                c.create_oval(lx, y + lh / 2 - r, lx + 2 * r, y + lh / 2 + r, fill=col, outline="")
                self.text(lx + lh * 0.75, y, label, lf, T["text"])
                lx += w
            y += lh + P * 0.6
        commit = st.ullTotalPageFile - st.ullAvailPageFile
        if y + lh <= y1 - P:
            self.text(rx0, y, f"Commit {fmt_bytes(commit)} of {fmt_bytes(st.ullTotalPageFile)}", lf, T["muted"], maxw=rw)
            y += lh + 2 * k
        reserved = self.installed - total if self.installed else 0
        if reserved > 128 * 1048576 and y + lh <= y1 - P:
            where = " (UMA frame buffer, set in BIOS)" if self.device["legion"] else ""
            self.text(rx0, y, f"Graphics reserves {fmt_bytes(reserved)} of {fmt_bytes(self.installed)}{where}", lf, T["muted"], maxw=rw)
            y += lh + P * 0.5
        hist = list(self.history)
        if len(hist) > 2 and y1 - P - y >= 34 * k:
            gx0, gy0, gx1, gy1 = rx0, y, rx1, y1 - P
            lo, hi = max(0.0, min(hist) - 0.05), min(1.0, max(hist) + 0.05)
            n = len(hist)
            pts = []
            for i, v in enumerate(hist):
                pts += [gx0 + (gx1 - gx0) * i / max(1, n - 1), gy1 - (gy1 - gy0) * (v - lo) / max(0.01, hi - lo)]
            c.create_polygon([gx0, gy1] + pts + [gx1, gy1], fill=mix(T["panel"], T["accent"], 0.16), outline="")
            c.create_line(pts, fill=T["accent"], width=max(1.5, 2 * k))
            self.text(gx1, gy0, f"{hi * 100:.0f}%", self.font(11 * k), T["muted"], anchor="ne")

    def draw_tiles(self, x0, y0, x1, y1, cols):
        T, k = self.t, self.k
        rows = math.ceil(len(TILE_ORDER) / cols)
        gap = 12 * k
        tw = (x1 - x0 - gap * (cols - 1)) / cols
        th = (y1 - y0 - gap * (rows - 1)) / rows
        for i, aid in enumerate(TILE_ORDER):
            r, cn = divmod(i, cols)
            tx0, ty0 = x0 + cn * (tw + gap), y0 + r * (th + gap)
            tx1, ty1 = tx0 + tw, ty0 + th
            hero = aid == "boost"
            fill = T["accent"] if hero else T["panel"]
            if self.pressed == f"act_{aid}":
                fill = mix(fill, "#ffffff" if hero else T["accent"], 0.28)
            if self.busy_action == aid:
                fill = mix(fill, T["accent2"], 0.35)
            fg = T["accent_text"] if hero else T["text"]
            sub = mix(fg, fill, 0.3) if hero else T["muted"]
            if not self.admin:
                fg = sub = mix(T["muted"], fill, 0.2)
            if hero:
                self.rr(tx0, ty0, tx1, ty1, 18 * k, fill)
            else:
                self.surface(tx0, ty0, tx1, ty1, 18 * k, fill)
            pad = 14 * k
            title, desc = ACTIONS[aid]
            tf = self.font(min(18 * k, tw / 7.5, th / 3.6), True)
            df = self.font(min(13 * k, tw / 11, th / 5.5))
            tlh, dlh = tf.metrics("linespace"), df.metrics("linespace")
            # titles and descriptions wrap to two lines when the tile has the height for it
            two = th - 2 * pad >= tlh * 2 + dlh
            tlines = self.wrap(title.upper(), tf, tw - 2 * pad)
            tlines = tlines[:2] if two and len(tlines) > 1 else [" ".join(tlines)]
            y = ty0 + pad
            for ln in tlines:
                self.text(tx0 + pad, y, ln, tf, fg, maxw=tw - 2 * pad)
                y += tlh
            if th > 74 * k:
                status = "Working…" if self.busy_action == aid else desc
                dw = tw - 2 * pad - (26 * k if self.pad_on and aid in TILE_PAD else 0)
                dlines = self.wrap(status, df, dw)
                room = int((ty1 - pad - y - 2 * k) // dlh)
                if len(dlines) > max(1, room):
                    dlines = dlines[:max(1, room) - 1] + [" ".join(dlines[max(1, room) - 1:])]
                for ln in dlines[:max(1, room)]:
                    self.text(tx0 + pad, y + 2 * k, ln, df, sub, maxw=dw)
                    y += dlh
            if self.pad_on and aid in TILE_PAD:
                self.pad_badge(tx1 - pad - 10 * k, ty1 - pad - 10 * k, TILE_PAD[aid], 12 * k)
            self.region(f"act_{aid}", tx0, ty0, tx1, ty1, tap=lambda a=aid: self.run(a))

    def draw_processes(self, x0, y0, x1, y1):
        T, k, c = self.t, self.k, self.c
        P = 16 * k
        top = self.card(x0, y0, x1, y1, f"APPS & PROCESSES · {len(self.procs)}")
        sw = min(220 * k, (x1 - x0) * 0.42)
        self.segmented("sort", x1 - P - sw, y0 + P * 0.5, x1 - P, y0 + P * 0.5 + 34 * k,
                       [("mem", "MEMORY"), ("cpu", "CPU")], self.cfg["proc_sort"], self.set_proc_sort)
        top = max(top, y0 + P * 0.5 + 34 * k + P * 0.5)
        bh = 56 * k
        by1 = y1 - P
        by0 = by1 - bh
        gap = 10 * k
        bw = (x1 - x0 - 2 * P - 2 * gap) / 3
        armed = bool(self.armed and self.armed[0].startswith("end_") and self.is_armed(self.armed[0]))
        self.button("trim", x0 + P, by0, x0 + P + bw, by1, "TRIM APP", lambda: self.run("trim"), badge="A")
        self.button("trimall", x0 + P + bw + gap, by0, x0 + P + 2 * bw + gap, by1, "TRIM ALL", lambda: self.run("trimall"))
        self.button("endtask", x1 - P - bw, by0, x1 - P, by1, "TAP AGAIN" if armed else "END TASK", self.end_task,
                    style="danger" if armed else "normal")
        lx0, lx1 = x0 + P * 0.6, x1 - P * 0.6
        ly0, ly1 = top, by0 - P * 0.6
        row_h = 50 * k
        h = max(row_h, ly1 - ly0)
        procs = self.procs
        off = self.scroll_area("procs", lx0, ly0, lx1, ly0 + h, len(procs) * row_h, tap_y=self.tap_proc, focus=True)
        self.scrolls["procs"]["row_h"] = row_h
        by_cpu = self.cfg["proc_sort"] == "cpu"
        biggest = max(1, procs[0][2]) if procs else 1
        top_cpu = max([self.proc_cpu.get(p[0], 0) for p in procs[:1]] + [1.0])
        first = int(off // row_h)
        nf, nfb = self.font(16 * k), self.font(16 * k, True)
        mf = self.font(15 * k, mono=True)
        cf = self.font(13 * k, mono=True)
        pf = self.font(12 * k)
        for i in range(first, min(len(procs), first + int(h // row_h) + 2)):
            ry0 = ly0 + i * row_h - off
            ry1 = ry0 + row_h - 4 * k
            cy0, cy1 = max(ry0, ly0), min(ry1, ly1)
            if cy1 <= cy0:
                continue
            pid, name, ws = procs[i]
            cpu = self.proc_cpu.get(pid)
            sel = i == self.sel
            fill = mix(T["panel"], T["accent"], 0.28) if sel else T["panel2"]
            if cy0 == ry0 and cy1 == ry1:
                self.rr(lx0, ry0, lx1, ry1, 10 * k, fill)
            else:
                c.create_rectangle(lx0, cy0, lx1, cy1, fill=fill, width=0)
            share = (cpu or 0) / top_cpu if by_cpu else ws / biggest
            barw = (lx1 - lx0 - 24 * k) * min(1.0, share)
            if ry1 - 7 * k >= cy0 and ry1 - 3 * k <= cy1:
                c.create_rectangle(lx0 + 12 * k, ry1 - 7 * k, lx0 + 12 * k + barw, ry1 - 4 * k,
                                   fill=mix(fill, T["accent2"] if by_cpu else T["accent"], 0.7 if sel else 0.45), width=0)
            if sel:
                c.create_rectangle(lx0, cy0 + 6 * k if cy0 == ry0 else cy0, lx0 + 4 * k, cy1 - 6 * k if cy1 == ry1 else cy1,
                                   fill=T["accent"], width=0)
            mid = (ry0 + ry1) / 2 - 2 * k
            if ly0 <= mid - 10 * k and mid + 10 * k <= ly1:
                size_s = fmt_bytes(ws)
                sw_ = mf.measure("000.0 MB")
                self.text(lx1 - 14 * k, mid, size_s, mf, T["text"], anchor="e")
                cpu_s = "" if cpu is None else f"{cpu:4.1f}%"
                cx = lx1 - 14 * k - sw_ - 18 * k
                self.text(cx, mid, cpu_s, cf, T["accent2"] if by_cpu else T["muted"], anchor="e")
                f = nfb if sel else nf
                nm = self.fit(name, f, cx - cf.measure("00.0%") - lx0 - 90 * k)
                self.text(lx0 + 16 * k, mid, nm, f, T["text"], anchor="w")
                self.text(lx0 + 16 * k + f.measure(nm) + 10 * k, mid + 1 * k, str(pid), pf, T["muted"], anchor="w")
        self.scrollbar("procs", x1 - 3 * k, ly0, h)

    def draw_tab_clean(self, x0, y0, x1, y1, land):
        T, k = self.t, self.k
        P = 14 * k
        if land:
            lw = (x1 - x0 - P) * 0.38
            self.draw_storage(x0, y0, x0 + lw, y1)
            self.draw_clean_list(x0 + lw + P, y0, x1, y1)
        else:
            sh = min(380 * k, (y1 - y0) * 0.36)
            self.draw_storage(x0, y0, x1, y0 + sh)
            self.draw_clean_list(x0, y0 + sh + P, x1, y1)

    def draw_storage(self, x0, y0, x1, y1):
        T, k, c = self.t, self.k, self.c
        P = 16 * k
        y = self.card(x0, y0, x1, y1, "STORAGE", f"freed {fmt_bytes(self.disk_freed)} this session" if self.disk_freed else "")
        lf, bf = self.font(15 * k, True), self.font(13 * k)
        btn_h = 54 * k
        bottom = y1 - P - 2 * btn_h - 10 * k
        for letter, total, free in self.drive_info[:3]:
            if y + 60 * k > bottom:
                break
            frac = (total - free) / max(1, total)
            col = T["accent"] if frac < 0.85 else T["warn"] if frac < 0.95 else T["danger"]
            self.text(x0 + P, y, f"{letter}:", lf, T["text"])
            self.text(x1 - P, y, f"{fmt_bytes(free)} free of {fmt_bytes(total)}", bf, T["muted"], anchor="ne")
            y += lf.metrics("linespace") + 6 * k
            self.rr(x0 + P, y, x1 - P, y + 14 * k, 7 * k, T["panel2"])
            self.rr(x0 + P, y, x0 + P + (x1 - x0 - 2 * P) * frac, y + 14 * k, 7 * k, col)
            y += 14 * k + P
        if not self.drive_info:
            self.text(x0 + P, y, "Reading drives…", bf, T["muted"])
        tip = "Clean-up only deletes caches and leftovers. Your games, saves and files are never touched."
        tf = self.font(13 * k)
        for ln in self.wrap(tip, tf, x1 - x0 - 2 * P):
            if y + tf.metrics("linespace") > bottom:
                break
            self.text(x0 + P, y, ln, tf, T["muted"])
            y += tf.metrics("linespace")
        bw = (x1 - x0 - 2 * P - 10 * k) / 2
        by = y1 - P - 2 * btn_h - 10 * k
        self.button("open_storage", x0 + P, by, x0 + P + bw, by + btn_h, "STORAGE SETTINGS",
                    lambda: systools.open_target("ms-settings:storagesense"), size=13 * k)
        self.button("open_cleanmgr", x1 - P - bw, by, x1 - P, by + btn_h, "DISK CLEANUP",
                    lambda: systools.open_target("cleanmgr.exe"), size=13 * k)
        by += btn_h + 10 * k
        self.button("clean_scan", x0 + P, by, x1 - P, by + btn_h, "SCANNING…" if self.clean_scanning else "SCAN AGAIN",
                    (lambda: None) if self.clean_scanning else self.scan_clean)

    def draw_clean_list(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        titles = {"caches": "FREE UP SPACE", "steam": "STEAM GAMES BY SIZE", "files": "BIG FILES IN YOUR FOLDERS",
                  "dupes": "DUPLICATE FILES"}
        top = self.card(x0, y0, x1, y1, titles[self.clean_view])
        sh = 50 * k
        self.segmented("cview", x0 + P, top, x1 - P, top + sh,
                       [("caches", "JUNK"), ("steam", "STEAM GAMES"), ("files", "BIG FILES"), ("dupes", "DUPLICATES")],
                       self.clean_view, self.set_clean_view)
        top += sh + P * 0.6
        {"caches": self.draw_clean_caches, "steam": self.draw_clean_steam, "files": self.draw_clean_files,
         "dupes": self.draw_clean_dupes}[self.clean_view](x0, top, x1, y1)

    def draw_clean_dupes(self, x0, top, x1, y1):
        T, k = self.t, self.k
        nf, df, sf = self.font(16 * k, True), self.font(12.5 * k), self.font(15 * k, True, mono=True)
        bw = 120 * k

        def row(i, g, rx0, ry0, rx1, ry1):
            size, files = g
            cy = (ry0 + ry1) / 2
            rid = f"dup_{files[0][0]}"
            armed = self.is_armed(rid)
            self.button(rid, rx1 - bw, cy - 22 * k, rx1, cy + 22 * k, "AGAIN" if armed else "DELETE COPIES",
                        lambda g_=g: self.delete_dupes(g_), style="danger" if armed else "normal", size=12 * k, sid="dupes")
            self.button(f"dshow_{i}", rx1 - 2 * bw - 10 * k, cy - 22 * k, rx1 - bw - 10 * k, cy + 22 * k, "SHOW",
                        lambda p_=files[0][0]: systools.show_in_explorer(p_), size=13 * k, sid="dupes")
            waste = size * (len(files) - 1)
            self.text(rx1 - 2 * bw - 26 * k, cy, fmt_bytes(waste), sf, T["text"], anchor="e")
            maxw = rx1 - 2 * bw - 150 * k - rx0
            self.text(rx0, cy - 2 * k, os.path.basename(files[0][0]), nf, T["text"], anchor="sw", maxw=maxw)
            folders = sorted({os.path.basename(os.path.dirname(f[0])) for f in files})
            self.text(rx0, cy + 2 * k, f"{len(files)} copies of {fmt_bytes(size)} · in " + ", ".join(folders), df, T["muted"],
                      anchor="nw", maxw=maxw)

        groups = self.dupes
        waste = sum(g[0] * (len(g[1]) - 1) for g in groups or [])
        note = f"{len(groups)} sets of identical files waste {fmt_bytes(waste)}. The oldest copy is always kept." if groups else ""
        self.list_rows("dupes", x0, top, x1, y1, groups, ("SCAN AGAIN", lambda: self.load_list("dupes"), note), row,
                       "No duplicate files over 20 MB in your folders.")

    def draw_clean_caches(self, x0, top, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        sel = self.clean_selection()
        total_sel = sum(self.clean_sizes.get(cid, 0) for cid in sel)
        bh = 60 * k
        busy = self.busy_action == "clean"
        label = "CLEANING…" if busy else f"CLEAN {fmt_bytes(total_sel)}" if total_sel else "CLEAN SELECTED"
        self.button("clean_go", x0 + P, y1 - P - bh, x1 - P, y1 - P, label, (lambda: None) if busy else self.run_clean, style="accent")
        ly0, ly1 = top, y1 - P - bh - P * 0.6
        cats = systools.CLEAN_CATEGORIES
        row_h = 70 * k
        off = self.scroll_area("clean", x0, ly0, x1, ly1, len(cats) * row_h)
        self.clip_to(ly0, ly1)
        nf, df, sf = self.font(16 * k, True), self.font(12.5 * k), self.font(15 * k, True, mono=True)
        for i, (cid, name, desc, _) in enumerate(cats):
            ry0 = ly0 + i * row_h - off
            ry1 = ry0 + row_h - 6 * k
            if ry1 < ly0 or ry0 > ly1:
                continue
            on = cid in sel
            rid = f"clean_{cid}"
            fill = mix(T["panel2"], T["accent"], 0.25) if self.pressed == rid else T["panel2"]
            self.rr(x0 + P * 0.6, ry0, x1 - P * 0.6, ry1, 12 * k, fill)
            cy = (ry0 + ry1) / 2
            cb = self.checkbox(x0 + P * 1.4, cy, on)
            size = self.clean_sizes.get(cid)
            if size is None and self.clean_scanning:
                self.spinner(x1 - P * 2 - 10 * k, cy, 10 * k)
            else:
                self.text(x1 - P * 1.6, cy, fmt_bytes(size) if size is not None else "", sf, T["text"] if size else T["muted"], anchor="e")
            tx = x0 + P * 1.4 + cb + 14 * k
            maxw = x1 - P * 1.6 - tx - 110 * k
            self.text(tx, cy - 2 * k, name, nf, T["text"], anchor="sw", maxw=maxw)
            self.text(tx, cy + 2 * k, desc, df, T["muted"], anchor="nw", maxw=maxw)
            self.region(rid, x0 + P * 0.6, ry0, x1 - P * 0.6, ry1, tap=lambda c_=cid: self.toggle_clean(c_), sid="clean")
        self.end_clip()
        self.scrollbar("clean", x1 - 4 * k, ly0, ly1 - ly0)

    def list_rows(self, sid, x0, top, x1, y1, items, footer, row_fn, empty):
        """Shared scroll list for Steam games and big files: footer = (label, tap, note)."""
        T, k = self.t, self.k
        P = 16 * k
        bh = 54 * k
        label, tap, note = footer
        nf = self.font(13 * k)
        ny = y1 - P - bh
        if note:
            self.text(x0 + P, ny - nf.metrics("linespace") - 6 * k, note, nf, T["muted"], maxw=x1 - x0 - 2 * P)
            ny -= nf.metrics("linespace") + 10 * k
        self.button(f"{sid}_reload", x0 + P, y1 - P - bh, x1 - P, y1 - P, label, tap, size=14 * k)
        ly0, ly1 = top, ny - P * 0.4
        if items is None:
            self.spinner((x0 + x1) / 2, (ly0 + ly1) / 2, 18 * k)
            self.text((x0 + x1) / 2, (ly0 + ly1) / 2 + 36 * k, "Looking…", nf, T["muted"], anchor="center")
            return
        if not items:
            self.text((x0 + x1) / 2, ly0 + 40 * k, empty, nf, T["muted"], anchor="center", maxw=x1 - x0 - 2 * P)
        row_h = 74 * k
        off = self.scroll_area(sid, x0, ly0, x1, ly1, len(items) * row_h)
        self.clip_to(ly0, ly1)
        for i, it in enumerate(items):
            ry0 = ly0 + i * row_h - off
            ry1 = ry0 + row_h - 6 * k
            if ry1 < ly0 or ry0 > ly1:
                continue
            self.rr(x0 + P * 0.6, ry0, x1 - P * 0.6, ry1, 12 * k, T["panel2"])
            row_fn(i, it, x0 + P * 1.4, ry0, x1 - P * 1.4, ry1)
        self.end_clip()
        self.scrollbar(sid, x1 - 4 * k, ly0, ly1 - ly0)

    def draw_clean_steam(self, x0, top, x1, y1):
        T, k = self.t, self.k
        games = self.steam
        nf, df, sf = self.font(16 * k, True), self.font(12.5 * k), self.font(15 * k, True, mono=True)
        bw = 140 * k

        def row(i, g, rx0, ry0, rx1, ry1):
            appid, name, size, last, lib = g
            cy = (ry0 + ry1) / 2
            rid = f"un_{appid}"
            armed = self.is_armed(rid)
            self.button(rid, rx1 - bw, cy - 22 * k, rx1, cy + 22 * k, "TAP AGAIN" if armed else "UNINSTALL",
                        lambda a=appid, n=name: self.uninstall_game(a, n), style="danger" if armed else "normal", size=13 * k, sid="steam")
            self.text(rx1 - bw - 16 * k, cy, fmt_bytes(size), sf, T["text"], anchor="e")
            sh = self.shader_sizes.get(appid, 0)
            extra = 0
            if sh > 30 * 1024 ** 2:
                sb = 170 * k
                extra = sb + 10 * k
                self.button(f"sh_{appid}", rx1 - bw - 140 * k - sb, cy - 22 * k, rx1 - bw - 140 * k, cy + 22 * k,
                            f"SHADERS {fmt_bytes(sh)}", lambda a=appid, n=name: self.clear_shaders(a, n), size=12 * k, sid="steam")
            maxw = rx1 - bw - 140 * k - extra - rx0
            self.text(rx0, cy - 2 * k, name, nf, T["text"], anchor="sw", maxw=maxw)
            self.text(rx0, cy + 2 * k, f"Last played {fmt_ago(last)} · {lib[:3]}", df, T["muted"], anchor="nw", maxw=maxw)

        total = sum(g[2] for g in games or [])
        note = f"{len(games)} games use {fmt_bytes(total)}. Uninstalling goes through Steam; saves in Steam Cloud stay." if games else ""
        self.list_rows("steam", x0, top, x1, y1, games, ("REFRESH", lambda: self.load_list("steam"), note), row,
                       "No Steam games found on this PC.")

    def draw_clean_files(self, x0, top, x1, y1):
        T, k = self.t, self.k
        nf, df, sf = self.font(16 * k, True), self.font(12.5 * k), self.font(15 * k, True, mono=True)
        bw = 110 * k

        def row(i, f, rx0, ry0, rx1, ry1):
            path, size, mtime, label = f
            cy = (ry0 + ry1) / 2
            rid = f"del_{path}"
            armed = self.is_armed(rid)
            self.button(rid, rx1 - bw, cy - 22 * k, rx1, cy + 22 * k, "AGAIN" if armed else "DELETE",
                        lambda p_=path: self.delete_big_file(p_), style="danger" if armed else "normal", size=13 * k, sid="files")
            self.button(f"show_{i}", rx1 - 2 * bw - 10 * k, cy - 22 * k, rx1 - bw - 10 * k, cy + 22 * k, "SHOW",
                        lambda p_=path: systools.show_in_explorer(p_), size=13 * k, sid="files")
            self.text(rx1 - 2 * bw - 26 * k, cy, fmt_bytes(size), sf, T["text"], anchor="e")
            maxw = rx1 - 2 * bw - 150 * k - rx0
            self.text(rx0, cy - 2 * k, os.path.basename(path), nf, T["text"], anchor="sw", maxw=maxw)
            self.text(rx0, cy + 2 * k, f"{label} · {fmt_ago(mtime).replace('ago', 'old')}", df, T["muted"], anchor="nw", maxw=maxw)

        files = self.bigfiles
        total = sum(f[1] for f in files or [])
        note = f"{len(files)} files over 150 MB, {fmt_bytes(total)} in total. DELETE moves them to the Recycle Bin." if files else ""
        self.list_rows("files", x0, top, x1, y1, files, ("SCAN AGAIN", lambda: self.load_list("files"), note), row,
                       "No files over 150 MB in Downloads, Videos, Desktop, Documents or Pictures.")

    def draw_tab_tools(self, x0, y0, x1, y1, land):
        k = self.k
        P = 14 * k
        if land:
            w = x1 - x0 - 2 * P
            c1, c2 = x0 + w * 0.33, x0 + w * 0.33 + P + w * 0.3
            ph = (y1 - y0) * 0.44
            self.draw_profiles(x0, y0, c1, y0 + ph)
            self.draw_power_card(x0, y0 + ph + P, c1, y1)
            dh = (y1 - y0) * 0.5
            self.draw_display(c1 + P, y0, c2, y0 + dh)
            self.draw_shortcuts(c1 + P, y0 + dh + P, c2, y1)
            self.draw_tweaks(c2 + P, y0, x1, y1)
        else:
            mid = x0 + (x1 - x0 - P) / 2
            r1 = (y1 - y0) * 0.27
            r2 = (y1 - y0) * 0.27
            self.draw_profiles(x0, y0, mid, y0 + r1)
            self.draw_display(mid + P, y0, x1, y0 + r1)
            self.draw_power_card(x0, y0 + r1 + P, mid, y0 + r1 + P + r2)
            self.draw_shortcuts(mid + P, y0 + r1 + P, x1, y0 + r1 + P + r2)
            self.draw_tweaks(x0, y0 + r1 + r2 + 2 * P, x1, y1)

    def draw_profiles(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        top = self.card(x0, y0, x1, y1, "PROFILES", "one tap")
        n = len(systools.PROFILES)
        gap = 10 * k
        bh = (y1 - P - top - gap * (n - 1)) / n
        nf, df = self.font(min(17 * k, bh * 0.3), True), self.font(min(12.5 * k, bh * 0.22))
        plain = {"saver": "Efficiency power · lowest refresh rate", "balanced": "Balanced power",
                 "max": "Best performance · highest refresh"}
        for i, (pid, name, desc, *_r) in enumerate(systools.PROFILES):
            if not self.device["legion"]:
                desc = plain.get(pid, desc)
            by0 = top + i * (bh + gap)
            by1 = by0 + bh
            on = self.cfg["profile"] == pid
            rid = f"prof_{pid}"
            fill = T["accent"] if on else T["panel2"]
            if self.pressed == rid:
                fill = mix(fill, "#ffffff" if on else T["accent"], 0.3)
            self.rr(x0 + P, by0, x1 - P, by1, 14 * k, fill)
            fg = T["accent_text"] if on else T["text"]
            sub = mix(fg, fill, 0.3) if on else T["muted"]
            cy = (by0 + by1) / 2
            if bh > 52 * k:
                self.text(x0 + P * 2, cy - 1 * k, name, nf, fg, anchor="sw", maxw=x1 - x0 - 4 * P)
                self.text(x0 + P * 2, cy + 1 * k, desc, df, sub, anchor="nw", maxw=x1 - x0 - 4 * P)
            else:
                self.text(x0 + P * 2, cy, name, nf, fg, anchor="w", maxw=x1 - x0 - 4 * P)
            if self.profile_busy and on:
                self.spinner(x1 - P * 2 - 10 * k, cy, 10 * k)
            self.region(rid, x0 + P, by0, x1 - P, by1, tap=lambda p_=pid: self.apply_profile(p_))

    def draw_display(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        y = self.card(x0, y0, x1, y1, "DISPLAY & SOUND")
        d = (self.tools or {}).get("display")
        lf = self.font(14 * k, True)
        lw = min(120 * k, (x1 - x0) * 0.28)
        seg_h = max(34 * k, min(52 * k, (y1 - P - y - 3 * 8 * k) / 4))

        def label(text):
            self.text(x0 + P, y + seg_h / 2, text, lf, T["text"], anchor="w", maxw=lw - 8 * k)

        sx = x0 + P + lw
        if d:
            label("Refresh")
            self.segmented("hz", sx, y, x1 - P, y + seg_h, [(r, f"{r} Hz") for r in d["rates"][-4:]], d["hz"], self.set_refresh)
            y += seg_h + 8 * k
            label("Resolution")
            self.segmented("res", sx, y, x1 - P, y + seg_h, [(sz, f"{sz[0]}×{sz[1]}") for sz in d["sizes"][:3]],
                           (d["w"], d["h"]), self.set_resolution)
            y += seg_h + 8 * k
        else:
            self.text(x0 + P, y, "Reading the screen modes…", self.font(12.5 * k), T["muted"])
            y += seg_h + 8 * k
        label("Brightness")
        levels = [10, 30, 50, 75, 100]
        cur = min(levels, key=lambda v: abs(v - self.brightness)) if self.brightness is not None else None
        self.segmented("bright", sx, y, x1 - P, y + seg_h, [(v, f"{v}%") for v in levels], cur, self.set_brightness)
        y += seg_h + 8 * k
        label("Volume")
        bw = (x1 - P - sx - 16 * k) / 3
        for i, (lbl, key, times) in enumerate((("− 10", "down", 5), ("MUTE", "mute", 1), ("+ 10", "up", 5))):
            bx = sx + i * (bw + 8 * k)
            self.button(f"vol_{key}", bx, y, bx + bw, y + seg_h, lbl, lambda k_=key, n=times: systools.volume_key(k_, n),
                        size=min(14 * k, seg_h * 0.34))

    def draw_power_card(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        y = self.card(x0, y0, x1, y1, "PERFORMANCE MODE")
        tools = self.tools or {}
        legion = self.device["legion"]
        lf, df = self.font(14 * k, True), self.font(12.5 * k)
        rows = 3 if legion else 1
        seg_h = max(36 * k, min(52 * k, (y1 - P - y - rows * 8 * k - (24 * k if legion else 0)) / rows))
        lw = min(150 * k, (x1 - x0) * 0.32)

        def row(label, sub=""):
            cy = y + seg_h / 2
            self.text(x0 + P, cy - (1 * k if sub else 0), label, lf, T["text"], anchor="sw" if sub else "w", maxw=lw - 8 * k)
            if sub:
                self.text(x0 + P, cy + 1 * k, sub, df, T["muted"], anchor="nw", maxw=lw - 8 * k)

        row("Windows", "power mode")
        opts = [(mid, {"efficiency": "Efficiency", "balanced": "Balanced", "performance": "Best"}[mid]) for mid, _, _ in systools.POWER_MODES]
        self.segmented("pmode", x0 + P + lw, y, x1 - P, y + seg_h, opts, tools.get("power"), self.set_power_mode)
        y += seg_h + 8 * k
        if not legion:
            return
        thermal = tools.get("thermal")
        row("Legion", "thermal mode")
        topts = [(v, {"Performance": "Perform."}.get(n, n)) for v, n in systools.THERMAL_MODES] + [(255, "Custom")]
        self.segmented("thermal", x0 + P + lw, y, x1 - P, y + seg_h, topts, thermal,
                       lambda v: self.apply_tdp() if v == 255 else self.set_thermal(v), busy="thermal" in self.tools_busy)
        if "thermal" in self.tools_busy or ("thermal_read" not in tools and self.tools is not None):
            self.spinner(x0 + P + lw - 14 * k, y + seg_h / 2, 8 * k)
        y += seg_h + 8 * k
        cur = tools.get("tdp")
        row("Custom TDP", f"now {cur} W" if thermal == 255 and cur else "experimental")
        bs = seg_h
        bx = x0 + P + lw
        for sign, label in ((-1, "−"), (1, "+")):
            rid = f"tdp{'+' if sign > 0 else '-'}"
            fill = mix(T["panel2"], T["accent"], 0.35) if self.pressed == rid else T["panel2"]
            xx = bx if sign < 0 else bx + bs + 100 * k
            self.rr(xx, y, xx + bs, y + bs, 12 * k, fill)
            self.c.create_text(xx + bs / 2, y + bs / 2, text=label, font=self.font(bs * 0.5, True), fill=T["text"])
            self.region(rid, xx, y, xx + bs, y + bs, tap=lambda s_=sign: self.step_tdp(s_), adjust=lambda d: self.step_tdp(d))
        self.text(bx + bs + 50 * k, y + bs / 2, f"{self.cfg['tdp']} W", self.font(min(20 * k, bs * 0.45), True), T["text"], anchor="center")
        ax = bx + 2 * bs + 110 * k
        armed = self.is_armed("tdp")
        self.button("tdp_apply", ax, y, x1 - P, y + bs, "WORKING…" if self.tdp_busy else ("TAP AGAIN" if armed else "APPLY"),
                    self.apply_tdp, style="danger" if armed else "accent", size=min(14 * k, bs * 0.32))
        y += seg_h + 6 * k
        note = f"5–{self.tdp_max} W. Quiet/Balanced/Performance are about 8/15/20 W on the original Legion Go."
        if y + df.metrics("linespace") <= y1 - P * 0.5:
            self.text(x0 + P, y, note, df, T["muted"], maxw=x1 - x0 - 2 * P)

    def draw_tweaks(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        top = self.card(x0, y0, x1, y1, "FPS SETTINGS", "recommended for gaming in green")
        tools = self.tools or {}
        tweaks = tools.get("tweaks", {})
        bh = 56 * k
        foot = y1 - P - bh
        if self.needs_restart:
            armed = self.is_armed("restart")
            self.button("restart", x0 + P, foot, x0 + (x1 - x0) / 2 - 5 * k, y1 - P, "TAP AGAIN" if armed else "RESTART NOW",
                        lambda: self.confirm("restart", systools.restart_pc, "Tap again to restart in 5 seconds"),
                        style="danger" if armed else "normal", size=14 * k)
            self.button("recommend", x0 + (x1 - x0) / 2 + 5 * k, foot, x1 - P, y1 - P, "APPLY RECOMMENDED", self.apply_recommended,
                        style="accent", size=14 * k)
        else:
            self.button("recommend", x0 + P, foot, x1 - P, y1 - P, "APPLY RECOMMENDED", self.apply_recommended, style="accent")
        ly0, ly1 = top, foot - P * 0.6
        n = len(systools.TWEAKS)
        row_h = max(60 * k, min(84 * k, (ly1 - ly0) / n))
        off = self.scroll_area("tweaks", x0, ly0, x1, ly1, n * row_h)
        self.clip_to(ly0, ly1)
        nf, df = self.font(16 * k, True), self.font(12.5 * k)
        for i, (tid, label, desc, _, _, rec, restart, _) in enumerate(systools.TWEAKS):
            ry0 = ly0 + i * row_h - off
            ry1 = ry0 + row_h - 6 * k
            if ry1 < ly0 or ry0 > ly1:
                continue
            cur = tweaks.get(tid)
            rid = f"tw_{tid}"
            fill = mix(T["panel2"], T["accent"], 0.25) if self.pressed == rid else T["panel2"]
            self.rr(x0 + P * 0.6, ry0, x1 - P * 0.6, ry1, 12 * k, fill)
            cy = (ry0 + ry1) / 2
            tw = self.toggle_switch(x1 - P * 1.4, cy, cur, pending=self.tools is None or "tweaks" not in tools)
            good = rec is not None and cur == rec
            dot = T["good"] if good else T["warn"] if rec is not None and cur is not None else T["line"]
            r = 6 * k
            tx = x0 + P * 1.4
            self.c.create_oval(tx, cy - r, tx + 2 * r, cy + r, fill=dot, outline="")
            tx += 2 * r + 12 * k
            maxw = x1 - P * 1.4 - tw - 16 * k - tx
            extra = []
            if rec is not None:
                extra.append(f"Best: {'On' if rec else 'Off'}")
            if restart:
                extra.append("restart needed")
            self.text(tx, cy - 2 * k, label + (f"  ·  {', '.join(extra)}" if extra else ""), nf, T["text"], anchor="sw", maxw=maxw)
            self.text(tx, cy + 2 * k, desc, df, T["muted"], anchor="nw", maxw=maxw)
            self.region(rid, x0 + P * 0.6, ry0, x1 - P * 0.6, ry1, tap=lambda t_=tid: self.toggle_tweak(t_), sid="tweaks",
                        adjust=lambda d, t_=tid: self.toggle_tweak(t_, d > 0))
        self.end_clip()
        self.scrollbar("tweaks", x1 - 4 * k, ly0, ly1 - ly0)

    def draw_shortcuts(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        top = self.card(x0, y0, x1, y1, "SHORTCUTS")
        items = systools.shortcuts(self.legion_apps)
        if not self.device["legion"]:
            items = [it for it in items if "legion" not in it[0].lower()]
        cols = 2
        rows = math.ceil(len(items) / cols)
        gap = 10 * k
        bh = min(56 * k, (y1 - P - top - gap * (rows - 1)) / max(1, rows))
        bw = (x1 - x0 - 2 * P - gap) / cols
        for i, (label, target) in enumerate(items):
            r, cn = divmod(i, cols)
            bx0, by0 = x0 + P + cn * (bw + gap), top + r * (bh + gap)
            if by0 + bh > y1 - P + 1:
                break
            self.button(f"sc_{i}", bx0, by0, bx0 + bw, by0 + bh, label.upper(),
                        (lambda t_=target: self.open_legion_space_myself(t_)) if "legion" in label.lower() else (lambda t_=target: systools.open_target(t_)),
                        size=min(13 * k, bh * 0.3))

    # ---- games tab
    def draw_tab_games(self, x0, y0, x1, y1, land):
        k = self.k
        P = 14 * k
        ah = min(5 * 66 * k + 70 * k, (y1 - y0) * (0.55 if land else 0.32))
        if land:
            lw = (x1 - x0 - P) * 0.54
            self.draw_game_list(x0, y0, x0 + lw, y1)
            self.draw_game_auto(x0 + lw + P, y0, x1, y0 + ah)
            self.draw_close_list(x0 + lw + P, y0 + ah + P, x1, y1)
        else:
            gh = (y1 - y0) * 0.36
            self.draw_game_list(x0, y0, x1, y0 + gh)
            self.draw_game_auto(x0, y0 + gh + P, x1, y0 + gh + P + ah)
            self.draw_close_list(x0, y0 + gh + ah + 2 * P, x1, y1)

    def games_summary(self):
        games = {}
        for sx in self.cfg["sessions"]:
            key = sx["name"].lower()
            g = games.setdefault(key, {"name": sx["name"], "last": 0, "total": 0, "peak": 0, "count": 0})
            g["last"] = max(g["last"], sx["start"])
            g["total"] += sx["dur"]
            g["peak"] = max(g["peak"], sx.get("peak", 0.0))
            g["count"] += 1
        for key in self.cfg["game_profiles"]:
            games.setdefault(key, {"name": key, "last": 0, "total": 0, "peak": 0, "count": 0})
        out = sorted(games.values(), key=lambda g: g["last"], reverse=True)
        if self.game:
            key = self.game["name"].lower()
            out = [g for g in out if g["name"].lower() != key]
            live = games.get(key, {"name": self.game["name"], "last": 0, "total": 0, "peak": 0, "count": 0})
            out.insert(0, dict(live, live=True))
        return out

    def draw_game_list(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        top = self.card(x0, y0, x1, y1, "YOUR GAMES", "tap the right button to give a game its own profile")
        games = self.games_summary()
        nf, df = self.font(16 * k, True), self.font(12.5 * k)
        if not games:
            for i, ln in enumerate(self.wrap("Play a full-screen game and it shows up here. Then you can give it its own profile "
                                             "(for example Battery saver for indie games, Max performance for big ones).", df, x1 - x0 - 2 * P)):
                self.text(x0 + P, top + i * df.metrics("linespace"), ln, df, T["muted"])
            return
        row_h = 74 * k
        off = self.scroll_area("glist", x0, top, x1, y1 - P, len(games) * row_h)
        self.clip_to(top, y1 - P)
        bw = min(200 * k, (x1 - x0) * 0.36)
        for i, g in enumerate(games):
            ry0 = top + i * row_h - off
            ry1 = ry0 + row_h - 6 * k
            if ry1 < top or ry0 > y1 - P:
                continue
            live = g.get("live")
            self.rr(x0 + P * 0.6, ry0, x1 - P * 0.6, ry1, 12 * k, mix(T["panel2"], T["accent2"], 0.2) if live else T["panel2"])
            cy = (ry0 + ry1) / 2
            key = g["name"].lower()
            prof = self.cfg["game_profiles"].get(key, "")
            self.button(f"gp_{key}", x1 - P * 1.4 - bw, cy - 24 * k, x1 - P * 1.4, cy + 24 * k, self.profile_label(prof).upper(),
                        lambda k_=key: self.cycle_game_profile(k_), style="accent" if prof else "normal", size=13 * k, sid="glist")
            self.regions[-1]["adjust"] = lambda d, k_=key: self.cycle_game_profile(k_, d)
            maxw = x1 - P * 1.4 - bw - 20 * k - (x0 + P * 1.4)
            title = g["name"]
            if live:
                st = self.fps_stats
                title += "  ·  playing" + (f"  ·  {st[0]:.0f} FPS" if st else "")
            self.text(x0 + P * 1.4, cy - 1 * k, title, nf, T["text"], anchor="sw", maxw=maxw)
            bits = []
            if g["last"]:
                bits.append(f"last played {fmt_ago(g['last'])}")
            if g["total"]:
                bits.append(f"{fmt_duration(g['total'])} total")
            if g["peak"]:
                bits.append(f"peak RAM {g['peak'] * 100:.0f}%")
            self.text(x0 + P * 1.4, cy + 1 * k, " · ".join(bits) or "profile only", df, T["muted"], anchor="nw", maxw=maxw)
            self.region(f"gl_{key}", x0 + P * 0.6, ry0, x1 - P * 1.4 - bw - 10 * k, ry1,
                        tap=lambda k_=key, n=g["name"]: self.open_tune(k_, n), sid="glist")
        self.end_clip()
        self.scrollbar("glist", x1 - 4 * k, top, y1 - P - top)

    def draw_game_auto(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        top = self.card(x0, y0, x1, y1, "WHEN A GAME STARTS")
        cfg = self.cfg
        pm = systools.presentmon_installed()
        fps_desc = ("Shows in the mini monitor (PresentMon by Intel)" if pm else
                    ("Downloading PresentMon…" if self.pm_busy else "Tap to download PresentMon by Intel (about 1 MB)"))
        items = [
            ("game_boost_auto", "Game Boost", "Free RAM from background apps", cfg["game_boost_auto"], lambda: self.adjust("game_boost_auto", 1)),
            ("game_perf_auto", "Performance modes", "For games without their own profile", cfg["game_perf_auto"], lambda: self.adjust("game_perf_auto", 1)),
            ("game_restore", "Put my modes back after", "When the game closes", cfg["game_restore"], lambda: self.adjust("game_restore", 1)),
            ("game_close_on", "Close my picked apps", f"{len(cfg['close_list'])} picked below", cfg["game_close_on"],
             lambda: (cfg.__setitem__("game_close_on", not cfg["game_close_on"]), self.request_draw())),
            ("fps", "FPS counter", fps_desc, cfg["fps_counter"] and pm, self.toggle_fps),
        ]
        rh = min(66 * k, (y1 - P - top) / len(items))
        nf, df = self.font(min(15.5 * k, rh * 0.28), True), self.font(min(12.5 * k, rh * 0.22))
        for i, (rid, label, desc, on, fn) in enumerate(items):
            ry0 = top + i * rh
            ry1 = ry0 + rh - 4 * k
            cy = (ry0 + ry1) / 2
            if self.pressed == f"ga_{rid}":
                self.rr(x0 + P * 0.5, ry0, x1 - P * 0.5, ry1, 12 * k, T["panel2"])
            tw = self.toggle_switch(x1 - P, cy, on, pending=rid == "fps" and self.pm_busy)
            self.text(x0 + P, cy - 1 * k, label, nf, T["text"], anchor="sw", maxw=x1 - x0 - 2 * P - tw - 10 * k)
            self.text(x0 + P, cy + 1 * k, desc, df, T["muted"], anchor="nw", maxw=x1 - x0 - 2 * P - tw - 10 * k)
            self.region(f"ga_{rid}", x0 + P * 0.5, ry0, x1 - P * 0.5, ry1, tap=fn, adjust=lambda d, f_=fn: f_())

    def close_candidates(self):
        game_exe = (self.game or {}).get("exe", "").lower()
        seen, out = set(), []
        for pid, name, ws in self.procs:
            low = name.lower()
            if low in seen or low == game_exe or low in SYSTEM_APPS or low in systools.END_TASK_PROTECT or low in BOOST_PROTECT \
                    or any(p_ in low for p_ in BOOST_PROTECT_PARTS) or not low.endswith(".exe"):
                continue
            seen.add(low)
            out.append((name, ws))
        out = out[:30]
        for n in self.cfg["close_list"]:
            if n.lower() not in seen:
                out.append((n, None))
        return out

    def draw_close_list(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        top = self.card(x0, y0, x1, y1, "APPS TO CLOSE", "force-closed, so save your work first")
        apps = self.close_candidates()
        picked = {n.lower() for n in self.cfg["close_list"]}
        row_h = 60 * k
        off = self.scroll_area("close", x0, top, x1, y1 - P, max(1, len(apps)) * row_h)
        self.clip_to(top, y1 - P)
        nf, sf = self.font(15 * k, True), self.font(14 * k, mono=True)
        if not apps:
            self.text(x0 + P, top, "No apps to pick right now. Open the ones you want closed, then come back.", self.font(13 * k),
                      T["muted"], maxw=x1 - x0 - 2 * P)
        for i, (name, ws) in enumerate(apps):
            ry0 = top + i * row_h - off
            ry1 = ry0 + row_h - 6 * k
            if ry1 < top or ry0 > y1 - P:
                continue
            rid = f"cl_{name.lower()}"
            fill = mix(T["panel2"], T["accent"], 0.25) if self.pressed == rid else T["panel2"]
            self.rr(x0 + P * 0.6, ry0, x1 - P * 0.6, ry1, 12 * k, fill)
            cy = (ry0 + ry1) / 2
            cb = self.checkbox(x0 + P * 1.4, cy, name.lower() in picked)
            self.text(x1 - P * 1.6, cy, fmt_bytes(ws) if ws is not None else "not running", sf, T["muted"], anchor="e")
            self.text(x0 + P * 1.4 + cb + 14 * k, cy, name, nf, T["text"], anchor="w", maxw=x1 - x0 - 280 * k)
            self.region(rid, x0 + P * 0.6, ry0, x1 - P * 0.6, ry1, tap=lambda n=name: self.toggle_close_app(n), sid="close")
        self.end_clip()
        self.scrollbar("close", x1 - 4 * k, top, y1 - P - top)

    # ---- PC & battery tab
    def draw_tab_system(self, x0, y0, x1, y1, land):
        k = self.k
        P = 14 * k
        mh = 150 * k
        if land:
            lw = (x1 - x0 - P) * 0.44
            self.draw_battery(x0, y0, x0 + lw, y1)
            rx = x0 + lw + P
            ch = (y1 - y0 - mh - 2 * P) / 2
            self.draw_cpu(rx, y0, x1, y0 + ch)
            self.draw_gpu(rx, y0 + ch + P, x1, y0 + 2 * ch + P)
            self.draw_monitor_card(rx, y1 - mh, x1, y1)
        else:
            bh = (y1 - y0) * 0.4
            ch = (y1 - y0 - bh - mh - 3 * P) / 2
            self.draw_battery(x0, y0, x1, y0 + bh)
            self.draw_cpu(x0, y0 + bh + P, x1, y0 + bh + P + ch)
            self.draw_gpu(x0, y0 + bh + ch + 2 * P, x1, y0 + bh + 2 * ch + 2 * P)
            self.draw_monitor_card(x0, y1 - mh, x1, y1)

    def draw_gpu(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        top = self.card(x0, y0, x1, y1, "GRAPHICS", "3D engine use")
        bf = self.font(min(40 * k, (y1 - top) * 0.45), True)
        val = "n/a" if not self.gpu_meter else "…" if self.gpu is None else f"{self.gpu:.0f}%"
        self.text(x0 + P, top, val, bf, T["text"])
        info = self.font(13 * k)
        ix = x0 + P + bf.measure("100%") + P
        reserved = self.installed - self.status.ullTotalPhys if self.installed else 0
        if reserved > 128 * 1048576:
            self.text(ix, top + 4 * k, f"{fmt_bytes(reserved)} of RAM reserved for graphics", info, T["muted"], maxw=x1 - P - ix)
        if self.fps_stats:
            fps, low = self.fps_stats
            self.text(ix, top + 4 * k + info.metrics("linespace"), f"{fps:.0f} FPS" + (f" · 1% low {low:.0f}" if low else ""),
                      self.font(13 * k, True), T["accent2"], maxw=x1 - P - ix)
        self.chart(x0 + P, top + bf.metrics("linespace") + 6 * k, x1 - P, y1 - P, list(self.gpu_hist), T["accent"], lo=0, hi=1,
                   label="last 3 min")

    def chart(self, x0, y0, x1, y1, values, color, lo=None, hi=None, label=""):
        T, c = self.t, self.c
        if len(values) < 2 or y1 - y0 < 20:
            return
        lo = min(values) if lo is None else lo
        hi = max(values) if hi is None else hi
        hi = max(hi, lo + 1e-6)
        pts = []
        for i, v in enumerate(values):
            pts += [x0 + (x1 - x0) * i / (len(values) - 1), y1 - (y1 - y0) * (v - lo) / (hi - lo)]
        c.create_polygon([x0, y1] + pts + [x1, y1], fill=mix(T["panel"], color, 0.16), outline="")
        c.create_line(pts, fill=color, width=max(1.5, 2 * self.k))
        if label:
            self.text(x1, y0, label, self.font(11 * self.k), T["muted"], anchor="ne")

    def draw_battery(self, x0, y0, x1, y1):
        T, k, c = self.t, self.k, self.c
        P = 16 * k
        top = self.card(x0, y0, x1, y1, "BATTERY")
        b, p, s_ = self.batt, self.power, self.batt_static or {}
        if not b or not p:
            self.text(x0 + P, top, "No battery found.", self.font(16 * k), T["muted"])
            return
        pct = p["pct"] if p["pct"] <= 100 else int(b["remaining_mwh"] * 100 / max(1, b["full_mwh"]))
        col = T["danger"] if pct < 20 else T["warn"] if pct < 40 else T["good"]
        D = min(200 * k, (x1 - x0) * 0.4, (y1 - top) * 0.45)
        gx, gy = x0 + P, top
        th = max(6, D * 0.1)
        c.create_oval(gx + th / 2, gy + th / 2, gx + D - th / 2, gy + D - th / 2, outline=T["panel2"], width=th)
        c.create_arc(gx + th / 2, gy + th / 2, gx + D - th / 2, gy + D - th / 2, start=90, extent=-359.9 * pct / 100,
                     style="arc", outline=col, width=th)
        c.create_text(gx + D / 2, gy + D / 2, text=f"{pct}%", font=self.font(D * 0.26, True), fill=T["text"])
        rate = b["rate_mw"] / 1000
        if b["discharging"] and rate:
            state, sub = f"{abs(rate):.1f} W", "being used right now"
            left = b["remaining_mwh"] / abs(b["rate_mw"]) * 3600
            extra = f"About {fmt_duration(left)} left at this rate"
        elif b["charging"]:
            state, sub = f"+{abs(rate):.1f} W" if rate else "Charging", "charging"
            extra = f"Full in about {fmt_duration((b['full_mwh'] - b['remaining_mwh']) / abs(b['rate_mw']) * 3600)}" if rate else ""
        else:
            state, sub, extra = "Plugged in", "not charging", ""
        rx = gx + D + P * 1.2
        bf = self.font(min(30 * k, (x1 - rx) / 7), True)
        self.text(rx, gy + D * 0.18, state, bf, T["text"], maxw=x1 - P - rx)
        sf = self.font(14 * k)
        self.text(rx, gy + D * 0.18 + bf.metrics("linespace"), sub, sf, T["muted"], maxw=x1 - P - rx)
        if extra:
            self.text(rx, gy + D * 0.18 + bf.metrics("linespace") + sf.metrics("linespace") + 6 * k, extra, sf, T["accent"], maxw=x1 - P - rx)
        y = gy + D + P
        full, design = b["full_mwh"], s_.get("design") or 0
        rows = [("Capacity now", f"{b['remaining_mwh'] / 1000:.1f} of {full / 1000:.1f} Wh")]
        if design:
            rows.append(("Battery health", f"{min(100, full * 100 / design):.0f}%  ({full / 1000:.1f} of {design / 1000:.1f} Wh new)"))
        if s_.get("cycles"):
            rows.append(("Charge cycles", str(s_["cycles"])))
        if not s_ and self.batt_static is not None:
            rows.append(("Battery health", "reading…"))
        lf, vf = self.font(14 * k), self.font(14 * k, True)
        lh = lf.metrics("linespace") + 8 * k
        for label, val in rows:
            if y + lh > y1 - P:
                break
            self.text(x0 + P, y, label, lf, T["muted"])
            self.text(x1 - P, y, val, vf, T["text"], anchor="ne", maxw=(x1 - x0) * 0.6)
            y += lh
        if self.device["legion"] and y + 50 * k <= y1 - P:
            cy = y + 24 * k
            self.text(x0 + P, cy - 1 * k, "Stop charging at 80%", self.font(15 * k, True), T["text"], anchor="sw", maxw=x1 - x0 - 120 * k)
            self.text(x0 + P, cy + 1 * k, "Slows battery wear when you play plugged in", self.font(12.5 * k), T["muted"], anchor="nw",
                      maxw=x1 - x0 - 120 * k)
            self.toggle_switch(x1 - P, cy, self.charge_limit, pending=self.charge_busy or self.charge_limit is None)
            self.region("charge", x0 + P * 0.5, y, x1 - P * 0.5, y + 48 * k, tap=self.toggle_charge_limit,
                        adjust=lambda d: self.toggle_charge_limit())
            y += 60 * k
        hist = [v for v in self.batt_hist]
        if y1 - P - y > 60 * k and len(hist) > 2:
            draw = [max(0.0, -v) for v in hist]
            y += 6 * k
            self.text(x0 + P, y, "POWER DRAW", self.font(12 * k, True), T["muted"])
            self.chart(x0 + P, y + 22 * k, x1 - P, y1 - P, draw, T["warn"], lo=0, hi=max(draw + [5]) * 1.15,
                       label=f"peak {max(draw):.1f} W")

    def draw_cpu(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        top = self.card(x0, y0, x1, y1, "PROCESSOR", f"{systools.CPU_COUNT} threads")
        bf = self.font(min(40 * k, (y1 - top) * 0.45), True)
        val = "…" if self.cpu is None else f"{self.cpu:.0f}%"
        self.text(x0 + P, top, val, bf, T["text"])
        info = self.font(13 * k)
        ix = x0 + P + bf.measure("100%") + P
        self.text(ix, top + 4 * k, f"Up {fmt_duration(kernel32.GetTickCount64() / 1000)}", info, T["muted"], maxw=x1 - P - ix)
        self.text(ix, top + 4 * k + info.metrics("linespace"), self.winver, info, T["muted"], maxw=x1 - P - ix)
        cy0 = top + bf.metrics("linespace") + 6 * k
        self.chart(x0 + P, cy0, x1 - P, y1 - P, list(self.cpu_hist), T["accent2"], lo=0, hi=1, label="last 3 min")

    def draw_monitor_card(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        top = self.card(x0, y0, x1, y1, "MINI MONITOR", "View + Menu toggles it" if self.cfg["pad_combo"] else "")
        bh = min(56 * k, y1 - P - top)
        on = self.cfg["overlay"]
        bw = (x1 - x0 - 2 * P) * 0.34
        self.button("mon_toggle", x0 + P, top, x0 + P + bw, top + bh, "ON" if on else "OFF", self.toggle_overlay,
                    style="accent" if on else "normal")
        corners = [("tl", "TOP LEFT"), ("tr", "TOP RIGHT"), ("bl", "BOTTOM L"), ("br", "BOTTOM R")]
        self.segmented("corner", x0 + P + bw + 10 * k, top, x1 - P, top + bh, corners, self.cfg["overlay_corner"],
                       lambda v: (self.cfg.__setitem__("overlay_corner", v), self.overlay and self.overlay.update(), self.request_draw()))

    def draw_games(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        st = self.cfg["stats"]
        top = self.card(x0, y0, x1, y1, "RECENT GAMES", f"all time: {fmt_bytes(st.get('ram', 0))} RAM, "
                        f"{fmt_bytes(st.get('disk', 0))} disk freed, {st.get('boosts', 0)} boosts")
        sessions = list(self.cfg["sessions"])
        rows = []
        if self.game:
            g = self.game
            rows.append((g["name"], "playing now", fmt_duration(time.time() - g["start"]), f"{g['peak'] * 100:.0f}%", True))
        for sx in sessions:
            rows.append((sx["name"], time.strftime("%b %d, %H:%M", time.localtime(sx["start"])), fmt_duration(sx["dur"]),
                         f"{sx['peak'] * 100:.0f}%", False))
        df = self.font(13 * k)
        if not rows:
            for i, ln in enumerate(self.wrap("Play a full-screen game and it shows up here with how long you played "
                                             "and its peak RAM use.", df, x1 - x0 - 2 * P)):
                self.text(x0 + P, top + i * df.metrics("linespace"), ln, df, T["muted"])
            return
        row_h = 58 * k
        off = self.scroll_area("games", x0, top, x1, y1 - P, len(rows) * row_h)
        self.clip_to(top, y1 - P)
        nf, mf = self.font(15 * k, True), self.font(14 * k, True, mono=True)
        for i, (name, when, dur, peak, live) in enumerate(rows):
            ry0 = top + i * row_h - off
            ry1 = ry0 + row_h - 6 * k
            if ry1 < top or ry0 > y1 - P:
                continue
            fill = mix(T["panel2"], T["accent2"], 0.2) if live else T["panel2"]
            self.rr(x0 + P * 0.6, ry0, x1 - P * 0.6, ry1, 12 * k, fill)
            cy = (ry0 + ry1) / 2
            self.text(x1 - P * 1.4, cy, f"{dur}  ·  peak {peak}", mf, T["text"], anchor="e")
            maxw = x1 - P * 1.4 - mf.measure(f"{dur}  ·  peak {peak}") - 20 * k - (x0 + P * 1.4)
            self.text(x0 + P * 1.4, cy - 1 * k, name, nf, T["text"], anchor="sw", maxw=maxw)
            self.text(x0 + P * 1.4, cy + 1 * k, when, df, T["accent2"] if live else T["muted"], anchor="nw", maxw=maxw)
            self.region(f"game_{i}", x0 + P * 0.6, ry0, x1 - P * 0.6, ry1, sid="games")
        self.end_clip()
        self.scrollbar("games", x1 - 4 * k, top, y1 - P - top)

    # ---- startup tab
    def draw_tab_startup(self, x0, y0, x1, y1, land):
        k = self.k
        P = 14 * k
        if not self.device["legion"]:
            return self.draw_startup_list(x0, y0, x1, y1)
        if land:
            lw = (x1 - x0 - P) * 0.4
            self.draw_legion_card(x0, y0, x0 + lw, y1)
            self.draw_startup_list(x0 + lw + P, y0, x1, y1)
        else:
            lh = 470 * k
            self.draw_legion_card(x0, y0, x1, y0 + lh)
            self.draw_startup_list(x0, y0 + lh + P, x1, y1)

    def draw_legion_card(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        if time.time() - self.ls_time > 4 and not self.ls_busy:
            self.load_ls_info()
        y = self.card(x0, y0, x1, y1, "LEGION SPACE REPLACEMENT")
        info = self.ls_info
        procs = (info or {}).get("procs") or []
        used = sum(p[2] for p in procs)
        state = self.legion_startup_state()
        loading = self.startup_items is None
        busy = any(i["key"] in self.startup_busy for i in (self.startup_items or []) if i["legion"])
        bf = self.font(min(23 * k, (x1 - x0) / 15), True)
        df = self.font(13.5 * k)
        lf = self.font(13.5 * k, True)
        w = x1 - x0 - 2 * P
        if info is None:
            headline, color = "Checking Legion Space…", T["muted"]
        elif procs:
            headline, color = f"Legion Space is using {fmt_bytes(used)}", T["warn"]
        else:
            headline, color = "Legion Space isn't running", T["good"]
        self.text(x0 + P, y, headline, bf, color, maxw=w - 30 * k)
        if loading or busy or info is None:
            self.spinner(x1 - P - 12 * k, y + bf.metrics("linespace") / 2, 11 * k)
        y += bf.metrics("linespace") + 4 * k
        if info:
            svcs = info.get("services") or []
            self.text(x0 + P, y, f"Vanta itself: {fmt_bytes(info['own'])}" + (f" · {len(procs)} Legion processes" if procs else "") +
                      (f" · Lenovo services {fmt_bytes(sum(p[2] for p in svcs))}" if svcs else ""), df, T["muted"], maxw=w)
            y += df.metrics("linespace") + P * 0.7
        # status rows
        st_text, st_color = self.legion_status()
        rows = [("Legion L / R buttons", st_text, st_color),
                ("Legion L", LEGION_ACTIONS.get(self.cfg["legion_l"], "Nothing"), T["text"]),
                ("Legion R", LEGION_ACTIONS.get(self.cfg["legion_r"], "Nothing"), T["text"]),
                ("Legion Space at sign-in", "…" if loading else "not set up" if state is None else "starts" if state else "off",
                 T["muted"] if loading or state is None else T["warn"] if state else T["good"]),
                ("Vanta at sign-in", "…" if self.startup is None else "starts" if self.startup else "off",
                 T["good"] if self.startup else T["warn"])]
        n_btn = (1 if procs else 0) + (1 if state else 0) + (0 if self.startup else 1)
        bh = 56 * k
        btn_top = y1 - P - max(1, n_btn) * (bh + 10 * k) + 10 * k
        rh = df.metrics("linespace") + 10 * k
        for label, value, col in rows:
            if y + rh > btn_top - P * 0.5:
                break
            self.text(x0 + P, y, label, df, T["muted"], maxw=w * 0.5)
            self.text(x1 - P, y, value, lf, col, anchor="ne", maxw=w * 0.52)
            y += rh
        y += P * 0.4
        if procs and self.cfg["legion_buttons"]:
            body = "While Legion Space is open, it reacts to the Legion buttons too. Close it to let Vanta handle them alone."
        elif self.cfg["ls_keep_closed"] and self.device["legion"] and self.ls_service == "running":
            body = ("Lenovo's button service opens Legion Space when you press a Legion button. Vanta stops it when it runs "
                    "as administrator; until then it closes Legion Space again right away.")
        else:
            body = ("Legion L opens this hub and Legion R opens quick settings over your game: power, TDP, refresh rate, "
                    "AMD settings and controller lights. No store, no ads.")
        for ln in self.wrap(body, df, w):
            if y + df.metrics("linespace") > btn_top - P * 0.5:
                break
            self.text(x0 + P, y, ln, df, T["muted"])
            y += df.metrics("linespace")
        if procs and y + 3 * rh < btn_top:
            y += P * 0.8
            self.text(x0 + P, y, "RUNNING NOW", self.font(12 * k, True), T["muted"])
            y += rh
            for pid, name, ws in procs:
                if y + rh > btn_top - P * 0.5:
                    break
                self.text(x0 + P, y, name, df, T["text"], maxw=w * 0.7)
                self.text(x1 - P, y, fmt_bytes(ws), lf, T["warn"], anchor="ne")
                y += rh
        by = btn_top
        if procs:
            armed = self.is_armed("ls_close")
            self.button("ls_close", x0 + P, by, x1 - P, by + bh, "TAP AGAIN TO CLOSE IT" if armed else f"CLOSE IT NOW ({fmt_bytes(used)})",
                        lambda: self.confirm("ls_close", self.close_legion_space, "Tap again to close Legion Space"),
                        style="accent", size=14 * k)
            by += bh + 10 * k
        if state:
            self.button("legion_btn", x0 + P, by, x1 - P, by + bh, "STOP IT STARTING WITH WINDOWS", lambda: self.set_legion_startup(False),
                        style="normal" if procs else "accent", size=14 * k)
            by += bh + 10 * k
        if not self.startup and self.startup is not None:
            self.button("ls_vanta", x0 + P, by, x1 - P, by + bh, "START VANTA WITH WINDOWS", lambda: self.adjust("startup", 1), size=14 * k)
            by += bh + 10 * k
        elif n_btn == 0 and state is False:
            self.button("legion_btn", x0 + P, by, x1 - P, by + bh, "LET LEGION SPACE START AGAIN", lambda: self.set_legion_startup(True),
                        style="ghost", size=13 * k)

    def draw_startup_list(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        P = 16 * k
        items = self.startup_items
        n_on = sum(1 for i in items or [] if i["enabled"])
        top = self.card(x0, y0, x1, y1, "STARTS WITH WINDOWS", "" if items is None else f"{n_on} of {len(items)} on")
        if items is None:
            self.spinner((x0 + x1) / 2, (top + y1) / 2, 18 * k)
            return
        bh = 52 * k
        foot = y1 - P - bh
        self.button("startup_reload", x0 + P, foot, x1 - P, y1 - P, "REFRESH", self.load_startup, size=14 * k)
        ly0, ly1 = top, foot - P * 0.6
        row_h = 70 * k
        off = self.scroll_area("startup", x0, ly0, x1, ly1, max(1, len(items)) * row_h)
        self.clip_to(ly0, ly1)
        nf, df = self.font(16 * k, True), self.font(12.5 * k)
        if not items:
            self.text((x0 + x1) / 2, ly0 + 40 * k, "Nothing found", df, T["muted"], anchor="center")
        for i, it in enumerate(items):
            ry0 = ly0 + i * row_h - off
            ry1 = ry0 + row_h - 6 * k
            if ry1 < ly0 or ry0 > ly1:
                continue
            rid = f"su_{i}"
            fill = T["panel2"]
            if it["legion"]:
                fill = mix(T["panel2"], T["accent2"], 0.18)
            if self.pressed == rid:
                fill = mix(fill, T["accent"], 0.25)
            self.rr(x0 + P * 0.6, ry0, x1 - P * 0.6, ry1, 12 * k, fill)
            cy = (ry0 + ry1) / 2
            pending = it["key"] in self.startup_busy
            tw = self.toggle_switch(x1 - P * 1.4, cy, it["enabled"], pending=pending or it.get("locked"))
            tx = x0 + P * 1.4
            maxw = x1 - P * 1.4 - tw - 16 * k - tx
            sub = it["source"] + (f" · {it['detail']}" if it["detail"] else "")
            if it["kind"] == "service":
                sub = "Service (Legion) · turning off sets it to Manual"
            self.text(tx, cy - 2 * k, it["name"], nf, T["text"], anchor="sw", maxw=maxw)
            self.text(tx, cy + 2 * k, sub, df, T["muted"], anchor="nw", maxw=maxw)
            self.region(rid, x0 + P * 0.6, ry0, x1 - P * 0.6, ry1, tap=lambda it_=it: self.toggle_startup_item(it_), sid="startup")
        self.end_clip()
        self.scrollbar("startup", x1 - 4 * k, ly0, ly1 - ly0)

    # ---- status bar
    def draw_status(self, W, H, sh):
        T, k, c = self.t, self.k, self.c
        P = 14 * k
        y0 = H - sh
        cy = y0 + sh / 2
        c.create_rectangle(0, y0, W, H, fill=T["panel"], width=0, **({"stipple": "gray75"} if T.get("glass") else {}))
        c.create_line(0, y0, W, y0, fill=T["line"])
        f = self.font(13 * k, True)
        label = "AUTO ON" if self.cfg["auto"] else "AUTO OFF"
        w = f.measure(label) + 28 * k
        on = self.cfg["auto"]
        fill = T["good"] if on else T["panel2"]
        if self.pressed == "auto":
            fill = mix(fill, T["accent"], 0.3)
        self.rr(P, cy - 16 * k, P + w, cy + 16 * k, 16 * k, fill)
        c.create_text(P + w / 2, cy, text=label, font=f, fill="#000000" if on else T["text"])
        self.region("auto", P, y0 + 4 * k, P + w, H - 4 * k, tap=lambda: self.adjust("auto", 1), focus=False)
        x = P + w + P
        # chips on the right
        chips = [(time.strftime("%H:%M"), T["panel2"], T["text"])]
        p = self.power
        if p and p["battery"] and p["pct"] <= 100:
            low = p["pct"] < 20 and not p["ac"]
            chips.append((f"{p['pct']}%" + (" charging" if p["ac"] else ""), T["danger"] if low else T["panel2"],
                          "#ffffff" if low else T["text"]))
        if self.pad_on:
            pb = self.pad_batt
            chips.append((f"PAD {pb}" if pb else "CONTROLLER", T["danger"] if pb in ("LOW", "EMPTY") else T["panel2"],
                          "#ffffff" if pb in ("LOW", "EMPTY") else T["text"]))
        chips.append(("ADMIN" if self.admin else "LIMITED", T["panel2"] if self.admin else T["warn"], T["good"] if self.admin else "#000000"))
        if self.device["legion"]:
            chips.append((self.device["name"].upper(), T["panel2"], T["muted"]))
        if PREVIEW:
            chips.insert(0, ("PREVIEW" + (" · SAFE" if self.cfg["preview_safe"] else ""), T["warn"], T["bg"]))
        xr = W - P
        cf = self.font(12.5 * k, True)
        for label, cfill, fg in chips:
            cw = cf.measure(label) + 20 * k
            if xr - cw < x + 260 * k:
                break
            self.rr(xr - cw, cy - 15 * k, xr, cy + 15 * k, 15 * k, cfill)
            c.create_text(xr - cw / 2, cy, text=label, font=cf, fill=fg)
            xr -= cw + 8 * k
        if self.busy:
            r = 10 * k
            self.spinner(x + r, cy, r)
            self.text(x + 2 * r + 10 * k, cy, self.busy + "…", f, T["text"], anchor="w", maxw=xr - x - 3 * P)
        elif self.log:
            ts, tag, msg = self.log[-1]
            self.text(x, cy, f"{ts}  {msg}", self.font(13 * k), T["muted"], anchor="w", maxw=xr - x - P)
            self.region("log", x, y0, xr, H, tap=lambda: self.open_page("log"), focus=False)

    # -------------------------------------------------------------- pages
    def draw_page(self, W, H):
        T, k, c = self.t, self.k, self.c
        P = 20 * k
        sheet = self.page in ("settings", "menu")
        pw = W - 2 * 14 * k if sheet else min(W - 2 * 14 * k, 900 * k)
        if sheet:
            pw = min(pw, 1500 * k)
        title = {"settings": "Settings", "menu": "Menu", "themes": "Themes", "help": "Help", "log": "Log", "checkup": "Checkup", "discord": "Discord", "buttons": "Back buttons", "bench": "Best TDP", "lists": "Lists", "editor": "Make your own theme",
                 "stream": "Stream & cloud", "deals": "Free games & deals", "retro": "RetroAchievements", "updates": "Driver & BIOS updates",
                 "automations": "Automations", "network": "Network check", "storage": "Storage cleanup", "pick": "What should I play?",
                 "gallery": "Clips & screenshots", "about": f"About {APP_NAME}", "btntest": "Legion button test",
                 "find": "Search", "recap": "Game recap", "collections": "Collections", "bgoal": "Battery goal", "playtime": "Play reminders", "calendar": "Play calendar", "badges": "Streaks & badges", "gameinfo": "Game notes & stats", "sleeptimer": "Sleep timer", "daynight": "Day & night themes", "hometools": "Customize Home", "guest": "Guest mode", "guestsetup": "Guest mode", "battery": "Battery health", "leftovers": "Leftovers & duplicates", "friends": "Steam friends", "weather": "Weather", "news": "Game news & patches", "padtest": "Controller tester", "dock": "Dock mode", "storeclose": "Close store apps", "queue": "Up next", "shortcuts": "Keyboard shortcuts", "bootreport": "Startup speed", "reinstall": "Reinstall a game", "people": "Who's playing",
                 "welcome": f"Welcome to {APP_NAME} {VERSION}",
                 "tune": "Game settings: " + (self.tune_target[1] if self.tune_target else "")}[self.page]
        avail = H - 2 * 14 * k - 80 * k - P
        if self.page == "menu":
            content = self.menu_height(pw - 2 * P)
        elif sheet:
            content = H
        elif self.page == "themes":
            cols = 4 if pw > 640 * k else 2
            content = self.themes_height(cols)
        elif self.page == "tune":
            content = avail
        elif self.page == "welcome":
            content = 66 * k * len(self.welcome_options()) + 300 * k
        else:
            content = avail
        hint = self.hint_h()
        ph = min(H - 28 * k - hint, 80 * k + content + P)
        x0, y0 = (W - pw) / 2, (H - hint - ph) / 2
        x1, y1 = x0 + pw, y0 + ph
        self.rr(x0, y0, x1, y1, 24 * k, T["panel"], outline=T["line"], width=max(1, k))
        self.region("panel", x0, y0, x1, y1, focus=False, kind="panel")
        tf = self.font(26 * k, True)
        self.text(x0 + P, y0 + 40 * k, tr(title), tf, T["text"], anchor="w", maxw=pw - 2 * P - 60 * k)
        if self.page == "settings":
            crumb = (tr("Search") if self.set_query else next((tr(c_[1]) for c_ in SETTINGS_CATS if c_[0] == self.set_cat), "")) \
                if (self.set_drill or not self.set_narrow or self.set_query) else ""
            if crumb:
                cx_ = x0 + P + self.measure(tf, tr(title)) + 14 * k
                self.text(cx_, y0 + 42 * k, "›  " + crumb, self.font(18 * k), T["muted"], anchor="w", maxw=x1 - cx_ - 100 * k)
        self.icon_button("page_close", x1 - P - 48 * k, y0 + 16 * k, 48 * k, "close", self.back)
        if self.page == "help":
            self.button("report", x1 - P - 48 * k - 230 * k, y0 + 16 * k, x1 - P - 58 * k, y0 + 64 * k,
                        "SAVING…" if self.report_busy else "SAVE A REPORT", self.save_report, size=13 * k)
        by0 = y0 + 80 * k
        if self.page == "settings":
            self.draw_settings(x0 + P, by0, x1 - P, y1 - P * 0.6)
        elif self.page == "menu":
            self.draw_menu(x0 + P, by0, x1 - P, y1 - P * 0.6)
        elif self.page == "themes":
            self.draw_themes(x0 + P, by0, x1 - P, y1 - P * 0.6, cols)
        elif self.page == "help":
            self.draw_help(x0 + P, by0, x1 - P, y1 - P)
        elif self.page == "about":
            self.draw_about(x0 + P, by0, x1 - P, y1 - P)
        elif self.page == "find":
            self.draw_find(x0 + P, by0, x1 - P, y1 - P)
        elif self.page == "tune":
            self.draw_tune(x0 + P, by0, x1 - P, y1 - P * 0.6)
        elif self.page == "checkup":
            self.draw_checkup(x0 + P, by0, x1 - P, y1 - P)
        elif self.page == "discord":
            self.draw_discord(x0 + P, by0, x1 - P, y1 - P)
        elif self.page == "buttons":
            self.draw_back_buttons(x0 + P, by0, x1 - P, y1 - P)
        elif self.page == "bench":
            self.draw_bench(x0 + P, by0, x1 - P, y1 - P)
        elif self.page == "lists":
            self.draw_lists(x0 + P, by0, x1 - P, y1 - P)
        elif self.page == "editor":
            self.draw_editor(x0 + P, by0, x1 - P, y1 - P)
        elif self.page == "gallery":
            self.draw_gallery(x0 + P, by0, x1 - P, y1 - P)
        elif self.page in ("stream", "deals", "retro", "updates", "automations", "network", "storage", "pick", "btntest",
                           "recap", "collections", "bgoal", "playtime", "calendar", "badges", "gameinfo", "sleeptimer", "daynight", "hometools", "guest", "guestsetup", "battery", "leftovers", "friends", "weather", "news", "padtest", "dock", "storeclose", "queue", "shortcuts", "bootreport", "reinstall", "people"):
            self.draw_card_list(self.page, getattr(self, "cards_" + self.page)(), x0 + P, by0, x1 - P, y1 - P)
        elif self.page == "welcome":
            self.draw_welcome(x0 + P, by0, x1 - P, y1 - P)
        else:
            self.draw_log(x0 + P, by0, x1 - P, y1 - P)

    def tune_rows(self):
        """Rows for the game settings page: (id, label, description, value text, adjust(d) or None, tap or None)."""
        t = self.tune()
        key, name = self.tune_target
        rows = [("head", "POWER", "", "", None, None)]
        tdps = [None] + list(range(5, self.tdp_max + 1))
        rows.append(("tdp", "Power limit (TDP)", "Only on the Legion Go" if not self.device["legion"] else "Sets a custom TDP while this game runs",
                     f"{t['tdp']} W" if t.get("tdp") else "Keep", (lambda d: self.tune_cycle("tdp", tdps, d)) if self.device["legion"] else None, None))
        cpus = [None, 99, 90, 80, 70, 60]
        rows.append(("cpu_max", "CPU limit", "Lower = cooler and longer battery; most handheld games don't need full CPU",
                     self.cpu_label(t.get("cpu_max")), lambda d: self.tune_cycle("cpu_max", cpus, d), None))
        prof = self.cfg["game_profiles"].get(key, "")
        rows.append(("profile", "Profile", "Power mode, thermal mode and refresh in one", self.profile_label(prof) if prof else "Auto",
                     lambda d: self.cycle_game_profile(key, d), None))
        modes = self.tune_modes or {}
        rows.append(("head", "DISPLAY", "", "", None, None))
        sizes = [None] + [list(s_) for s_ in modes.get("sizes", [])[:5]]
        res = t.get("res")
        rows.append(("res", "Resolution while playing", "Lower desktop resolution helps borderless games", f"{res[0]}×{res[1]}" if res else "Keep",
                     lambda d: self.tune_cycle("res", sizes, d), None))
        rates = [None] + list(modes.get("rates", []))
        rows.append(("hz", "Refresh rate while playing", "60 Hz saves battery", f"{t['hz']} Hz" if t.get("hz") else "Keep",
                     lambda d: self.tune_cycle("hz", rates, d), None))
        rows.append(("head", "CONTROLS", "", "", None, None))
        gyro_opts = [None] + list(POINTER_MODES)
        rows.append(("gyro", "Motion controls while playing", "Turns the gyro mode on or off just for this game",
                     POINTER_MODES.get(t.get("gyro"), "Keep") if t.get("gyro") else "Keep",
                     lambda d: self.tune_cycle("gyro", gyro_opts, d), None))
        pm_opts = [None] + list(systools.PAD_LAYOUTS)
        rows.append(("padmouse", "Controller as mouse & keyboard", "For games without controller support: on while this game runs",
                     systools.PAD_LAYOUTS[t["padmouse"]]["name"] if t.get("padmouse") in systools.PAD_LAYOUTS else "Off",
                     lambda d: self.tune_cycle("padmouse", pm_opts, d), None))
        rows.append(("hdr", "HDR while playing", "Switches Windows HDR for this game and back afterwards",
                     {"on": "On", "off": "Off"}.get(t.get("hdr"), "Keep"), lambda d: self.tune_cycle("hdr", [None, "on", "off"], d), None))
        own = self.cfg["back_map_game"].get(self.tune_target[0] if self.tune_target else "", {})
        rows.append(("backbtn", "Back buttons for this game", f"{len(own)} button{'s' if len(own) != 1 else ''} mapped just for this game"
                     if own else "Uses your everyday mapping", "EDIT", None, self.open_back_for_tune))
        rows.append(("head", "AMD GRAPHICS", "", "", None, None))
        state = self.amd_state
        amd = t.get("amd") or {}
        if state is not None and not state:
            rows.append(("amd_na", "AMD settings aren't available here yet", systools.ADLX.error or "AMD's settings library didn't answer",
                         "RETRY", None, self.retry_amd))
            if os.path.exists(systools.AMD_SOFTWARE):
                rows.append(("amd_app", "Open AMD Software", "Change these settings in AMD's own app meanwhile", "OPEN", None,
                             lambda: systools.open_target(systools.AMD_SOFTWARE)))
            return rows
        for feat in ("rsr", "afmf", "antilag", "chill", "ris", "frtc", "boost", "esync", "integer", "gpu_scaling"):
            label, desc = systools.AMD_LABELS[feat]
            supported = state is None or feat in state
            if not supported:
                continue
            now = ""
            if state and feat in state:
                now = f" · now {'on' if state[feat]['on'] else 'off'}"
            v = amd.get(feat)
            rows.append((f"amd_{feat}", label, desc + now, "Keep" if v is None else ("On" if v else "Off"),
                         lambda d, f=feat: self.amd_cycle(f, d), None))
            if v:
                for pname, plabel, default in systools.AMD_PARAMS.get(feat, []):
                    pv = amd.get(f"{feat}_{pname}", default)
                    unit = "%" if pname in ("sharp", "res") else " FPS"
                    rows.append((f"amd_{feat}_{pname}", "      " + plabel, "", f"{pv}{unit}",
                                 lambda d, f=feat, pn=pname: self.amd_param(f, pn, d), None))
        return rows

    def draw_tune(self, x0, y0, x1, y1):
        T, k, c = self.t, self.k, self.c
        key, name = self.tune_target
        t = self.tune()
        gen = self.preset_gen()
        preset = self.find_preset(name)
        rows = self.tune_rows()
        rh, hh = 62 * k, 44 * k
        df, nf, lf = self.font(13 * k), self.font(15 * k, True), self.font(16 * k, True)
        notes = list(preset["notes"]) if preset else []
        if preset and preset["tested"] != gen:
            notes.append(f"These numbers were tested on the {systools.GENS[preset['tested']].split(' · ')[1]}, "
                         f"so treat them as a starting point on the {systools.GENS[gen].split(' · ')[1]}")
        if preset and preset.get("tdp", 0) > self.tdp_max:
            notes.append(f"Vanta caps the TDP at {self.tdp_max} W on this device")
        note_lines = sum(len(self.wrap("•  " + n_, df, x1 - x0 - 40 * k)) for n_ in notes)
        card_h = (60 * k + note_lines * df.metrics("linespace") + 70 * k) if preset else 70 * k
        chips_h = 60 * k
        gen_h = 58 * k
        comm = self.community_layout(key, x1 - x0) if self.cfg["community_presets"] else None
        comm_h = comm["h"] + 14 * k if comm else 0
        icards = self.insight_cards(key, name, t)
        comm_h += sum(self.card_height(cd, x1 - x0) + 14 * k for cd in icards)
        content = gen_h + card_h + 14 * k + chips_h + 14 * k + comm_h + sum(hh if r_[0] == "head" else rh for r_ in rows) + 80 * k
        off = self.scroll_area("tune", x0 - 8 * k, y0, x1 + 8 * k, y1, content)
        self.clip_to(y0, y1)
        y = y0 - off

        def visible(a, b):
            return b >= y0 - 1 and a <= y1 + 1

        # which Legion Go the presets are for
        if visible(y, y + gen_h):
            self.text(x0, y + gen_h / 2 - 5 * k, "PRESETS FOR", self.font(12.5 * k, True), T["muted"], anchor="w")
            gx = x0 + 130 * k
            gw_ = min(250 * k, (x1 - gx - 20 * k) / 2)
            for i, (gid, glabel) in enumerate(systools.GENS.items()):
                bx = gx + i * (gw_ + 10 * k)
                on = gid == gen
                self.button(f"t_gen_{gid}", bx, y, bx + gw_, y + gen_h - 12 * k, ("✓ " if on else "") + glabel.upper(),
                            lambda g_=gid: self.set_preset_gen(g_), style="accent" if on else "normal", size=12 * k, sid="tune")
        y += gen_h

        # suggested preset
        if visible(y, y + card_h):
            self.rr(x0, y, x1, y + card_h, 16 * k, mix(T["panel2"], T["accent"], 0.12), outline=T["line"], width=max(1, k))
            yy = y + 16 * k
            if preset:
                applied = t.get("preset") == preset["id"]
                self.text(x0 + 18 * k, yy, ("✓ " if applied else "") + f"{systools.GENS[gen].split(' · ')[1]} preset: {preset['title']}", lf, T["text"],
                          maxw=x1 - x0 - 340 * k)
                bits = []
                if preset.get("tdp"):
                    bits.append(f"{preset['tdp']} W")
                if preset.get("hz"):
                    bits.append(f"{preset['hz']} Hz")
                bits += [systools.AMD_LABELS[f_][0] + (" on" if v_ else " off") for f_, v_ in (preset.get("amd") or {}).items()
                         if f_ in systools.AMD_LABELS]
                self.text(x0 + 18 * k, yy + lf.metrics("linespace") + 2 * k, "Vanta sets: " + (", ".join(bits) or "nothing (in-game settings only)"),
                          self.font(12.5 * k), T["accent"], maxw=x1 - x0 - 340 * k)
                bw = 150 * k
                self.button("t_apply", x1 - 2 * bw - 28 * k, yy, x1 - bw - 28 * k, yy + 46 * k, "APPLIED" if applied else "APPLY PRESET",
                            lambda: self.apply_preset(preset), style="accent", size=12.5 * k, sid="tune")
                self.button("t_src", x1 - bw - 18 * k, yy, x1 - 18 * k, yy + 46 * k, "OPEN SOURCE",
                            lambda: systools.open_target(preset["source"][1]), size=12.5 * k, sid="tune")
                yy += 58 * k
                self.text(x0 + 18 * k, yy, "In the game's own settings:", df, T["muted"])
                yy += df.metrics("linespace") + 2 * k
                for n_ in notes:
                    for ln in self.wrap("•  " + n_, df, x1 - x0 - 40 * k):
                        self.text(x0 + 18 * k, yy, ln, df, T["text"])
                        yy += df.metrics("linespace")
                self.text(x0 + 18 * k, y + card_h - 14 * k, f"Source: {preset['source'][0]}", self.font(12 * k), T["muted"], anchor="sw")
            else:
                self.text(x0 + 18 * k, y + card_h / 2, "No tested preset for this game yet. Try a general one below, or set things yourself.",
                          df, T["muted"], anchor="w", maxw=x1 - x0 - 36 * k)
        y += card_h + 14 * k
        # general presets
        if visible(y, y + chips_h):
            gp = systools.general_presets(gen)
            gw = (x1 - x0 - 10 * k * (len(gp) - 1)) / len(gp)
            for i, p_ in enumerate(gp):
                bx = x0 + i * (gw + 10 * k)
                on = t.get("preset") == p_["id"]
                self.button(f"t_gp_{p_['id']}", bx, y, bx + gw, y + chips_h - 10 * k, ("✓ " if on else "") + p_["title"].upper(),
                            lambda p2=p_: self.apply_preset(p2), style="accent" if on else "normal", size=12 * k, sid="tune")
        y += chips_h + 14 * k
        for cd in icards:
            ch_ = self.card_height(cd, x1 - x0)
            if visible(y, y + ch_):
                self.draw_card(cd, x0, y, x1, "tune")
            y += ch_ + 14 * k
        if comm:
            if visible(y, y + comm["h"]):
                self.draw_community(comm, key, name, t, x0, y, x1)
            y += comm_h
        # rows
        for rid, label, desc, value, adj, tap in rows:
            if rid == "head":
                if visible(y, y + hh):
                    self.text(x0, y + hh - 10 * k, label, self.font(13 * k, True), T["accent"], anchor="sw")
                y += hh
                continue
            ry0, ry1 = y, y + rh - 6 * k
            if visible(ry0, ry1):
                cy = (ry0 + ry1) / 2
                ctrl_w = 260 * k
                if desc:
                    self.text(x0, cy - 1 * k, label, nf, T["text"] if adj else T["muted"], anchor="sw", maxw=x1 - x0 - ctrl_w - 16 * k)
                    self.text(x0, cy + 1 * k, desc, self.font(12.5 * k), T["muted"], anchor="nw", maxw=x1 - x0 - ctrl_w - 16 * k)
                else:
                    self.text(x0, cy, label, nf, T["text"], anchor="w", maxw=x1 - x0 - ctrl_w - 16 * k)
                if adj:
                    bs = 44 * k
                    for sign, bx0 in ((-1, x1 - ctrl_w), (1, x1 - bs)):
                        bid = f"t_{rid}{'+' if sign > 0 else '-'}"
                        fill = mix(T["panel2"], T["accent"], 0.35) if self.pressed == bid else T["panel2"]
                        self.rr(bx0, cy - bs / 2, bx0 + bs, cy + bs / 2, 10 * k, fill)
                        c.create_text(bx0 + bs / 2, cy, text="+" if sign > 0 else "−", font=self.font(bs * 0.55, True), fill=T["text"])
                        self.region(bid, bx0, cy - bs / 2, bx0 + bs, cy + bs / 2, tap=lambda a=adj, s_=sign: a(s_), focus=False, sid="tune")
                    vcol = T["muted"] if value == "Keep" else T["accent"] if value in ("On",) else T["text"]
                    self.text(x1 - ctrl_w / 2, cy, value, self.font(15 * k, True), vcol, anchor="center", maxw=ctrl_w - 2 * bs - 8 * k)
                    self.region(f"t_{rid}", x0, ry0, x1, ry1, tap=lambda a=adj: a(1), adjust=adj, sid="tune")
                elif tap:
                    self.button(f"t_{rid}", x1 - 180 * k, cy - 22 * k, x1, cy + 22 * k, value, tap, style="accent", size=13 * k, sid="tune")
            y += rh
        if visible(y + 10 * k, y + 64 * k):
            armed = self.is_armed(f"rt_{key}")
            self.button("t_reset", x0, y + 10 * k, x0 + 280 * k, y + 64 * k, "TAP AGAIN" if armed else "RESET THIS GAME", self.reset_tune,
                        style="danger" if armed else "normal", size=13 * k, sid="tune")
            self.text(x0 + 300 * k, y + 37 * k, "Applied when the game starts, undone when it closes.", df, T["muted"], anchor="w",
                      maxw=x1 - x0 - 300 * k)
        self.end_clip()
        self.scrollbar("tune", x1 + 6 * k, y0, y1 - y0)

    # -------------------------------------------------------------- community presets (Deck Verified)
    def community_layout(self, key, w):
        """Measure the community section once per frame: heights of the header, summary and each report card."""
        k = self.k
        df = self.font(12.5 * k)
        ls = df.metrics("linespace")
        st = self.dv.get(key, {"status": "loading"})
        lay = {"status": st["status"], "cards": [], "summary": []}
        h = 58 * k
        if st["status"] == "ok":
            summ = (st["data"] or {}).get("summary") or ""
            lay["summary"] = self.wrap(summ, df, w - 40 * k)[:4] if summ else []
            if lay["summary"]:
                h += 26 * k + len(lay["summary"]) * ls + 10 * k
            presets = self.community_for(key)
            lay["none_here"] = not presets
            for p in presets:
                game_notes = [n for n in p["notes"] if n != systools.DV_OS_NOTE and not n.startswith(("Reported on", "Same Ryzen", "Legion Go 2 report", "Z1 Extreme report", "Steam Deck report"))][:5]
                ch = 112 * k + len(game_notes) * ls + 34 * k
                lay["cards"].append((p, game_notes, ch))
                h += ch + 10 * k
            if not presets:
                h += 50 * k
            h += 34 * k  # the SteamOS note
        else:
            h += 50 * k
        lay["h"] = h
        return lay

    def draw_community(self, lay, key, name, t, x0, y, x1):
        T, k = self.t, self.k
        df, sf = self.font(12.5 * k), self.font(12 * k)
        ls = df.metrics("linespace")
        st = self.dv.get(key, {})
        self.text(x0, y + 22 * k, "COMMUNITY PRESETS", self.font(13 * k, True), T["accent"], anchor="w")
        self.text(x0, y + 44 * k, "Settings players shared on Deck Verified, closest match to your Legion Go first", sf, T["muted"],
                  anchor="w", maxw=x1 - x0 - 330 * k)
        bw = 150 * k
        self.button("dv_all", x1 - 2 * bw - 10 * k, y + 8 * k, x1 - bw - 10 * k, y + 48 * k, "SEE ALL",
                    lambda: systools.open_target(systools.dv_game_page(st.get("appid"), name)), size=12 * k, sid="tune")
        has_play = any(s_.get("fps") for s_ in self.sessions_for(key, name))
        self.button("dv_share", x1 - bw, y + 8 * k, x1, y + 48 * k, "SHARE YOURS",
                    (lambda: self.share_settings(key, name)) if has_play else (lambda: systools.open_target(systools.DV_NEW_REPORT)),
                    size=12 * k, sid="tune")
        yy = y + 58 * k
        status = lay["status"]
        if status != "ok":
            msg = {"loading": "Looking up player reports…", "none": "No player reports for this game yet. Be the first: tap SHARE YOURS.",
                   "offline": "Couldn't reach Deck Verified. Check the connection and tap to try again."}.get(status, "")
            self.rr(x0, yy, x1, yy + 40 * k, 12 * k, T["panel2"])
            self.text(x0 + 16 * k, yy + 20 * k, msg, df, T["muted"], anchor="w", maxw=x1 - x0 - 32 * k)
            if status == "offline":
                self.region("dv_retry", x0, yy, x1, yy + 40 * k, tap=lambda: self.lookup_community(key, name, force=True), sid="tune")
            return
        if lay["summary"]:
            self.text(x0, yy + 4 * k, "What players say (Deck Verified's summary of every report):", sf, T["muted"])
            yy += 26 * k
            for ln in lay["summary"]:
                self.text(x0, yy, ln, df, T["text"])
                yy += ls
            yy += 10 * k
        if lay.get("none_here"):
            self.rr(x0, yy, x1, yy + 40 * k, 12 * k, T["panel2"])
            self.text(x0 + 16 * k, yy + 20 * k, "No reports from a Legion Go, a Z1 Extreme handheld or a Steam Deck yet. SEE ALL shows the rest.",
                      df, T["muted"], anchor="w", maxw=x1 - x0 - 32 * k)
            yy += 50 * k
        for p, notes, ch in lay["cards"]:
            applied = t.get("preset") == p["id"]
            self.rr(x0, yy, x1, yy + ch, 14 * k, T["panel2"], outline=T["accent"] if applied else T["line"],
                    width=max(1, (2 if applied else 1) * k))
            cx = x0 + 16 * k
            tf = self.font(11 * k, True)
            tw = self.measure(tf, p["tag"]) + 18 * k
            near = p["tier"] == 0
            self.rr(cx, yy + 14 * k, cx + tw, yy + 38 * k, 12 * k, T["accent"] if near else mix(T["panel"], T["accent"], 0.25))
            self.text(cx + tw / 2, yy + 26 * k, p["tag"], tf, T["accent_text"] if near else T["text"], anchor="center")
            votes = f"  ▲ {p['votes']}" if p["votes"] > 0 else ""
            self.text(cx + tw + 10 * k, yy + 26 * k, ("✓ " if applied else "") + p["title"] + votes, self.font(15 * k, True), T["text"],
                      anchor="w", maxw=x1 - cx - tw - 2 * bw - 50 * k)
            bits = []
            if p.get("tdp"):
                bits.append(f"{p['tdp']} W")
            if (p.get("amd") or {}).get("frtc"):
                bits.append(f"FPS cap {p['amd']['frtc_fps']}")
            self.text(cx, yy + 54 * k, "Vanta sets: " + (", ".join(bits) or "nothing (in-game settings only)"), df, T["accent"], anchor="w",
                      maxw=x1 - cx - 2 * bw - 40 * k)
            self.text(cx, yy + 76 * k, p["device"] + " · " + next((n for n in p["notes"] if n.startswith(("Reported on", "Same Ryzen", "Legion Go 2 report", "Z1 Extreme report",
                                                                                  "Steam Deck report"))), ""),
                      sf, T["muted"], anchor="w", maxw=x1 - cx - 2 * bw - 40 * k)
            self.button(f"dv_apply_{p['id']}", x1 - 2 * bw - 26 * k, yy + 12 * k, x1 - bw - 26 * k, yy + 54 * k,
                        "APPLIED" if applied else "APPLY", lambda p_=p: self.apply_preset(p_), style="accent", size=12 * k, sid="tune")
            self.button(f"dv_open_{p['id']}", x1 - bw - 16 * k, yy + 12 * k, x1 - 16 * k, yy + 54 * k, "REPORT",
                        lambda u=p["source"][1]: systools.open_target(u), size=12 * k, sid="tune")
            ny = yy + 100 * k
            for n_ in notes:
                self.text(cx, ny, "•  " + n_, df, T["text"], maxw=x1 - cx - 20 * k)
                ny += ls
            self.text(cx, yy + ch - 12 * k, p["source"][0], sf, T["muted"], anchor="sw", maxw=x1 - cx - 20 * k)
            yy += ch + 10 * k
        self.text(x0, yy + 14 * k, systools.DV_OS_NOTE + ".", sf, T["muted"], anchor="w", maxw=x1 - x0)

    # -------------------------------------------------------------- settings: categories, search, rows
    def settings_categories(self):
        """[(cat, rows)] where rows keep sub-headers ("header" rows) only when a category mixes sections."""
        groups = {}
        section = None
        for row in self.settings_items():
            if row[3] == "header":
                section = row[1]
                continue
            cat, sub = SETTINGS_KEY_CAT.get(row[0], (SETTINGS_SECTION_CAT.get(section, "app"), section))
            groups.setdefault(cat, {}).setdefault(sub, []).append(row)
        out = []
        for cat in SETTINGS_CATS:
            subs = groups.get(cat[0])
            if not subs:
                continue
            rows = []
            first = ("RECOMMENDED PRESETS", "THEME")
            for sub, items in sorted(subs.items(), key=lambda kv: kv[0] not in first):
                if len(subs) > 1:
                    rows.append(("#" + sub, sub, "", "header", ""))
                rows += items
            out.append((cat, rows))
        return out

    def settings_view(self):
        """What the right-hand pane shows: the current category, or search results from every category."""
        cats = self.settings_categories()
        q = self.set_query.strip().lower()
        if q:
            rows = []
            for cat, items in cats:
                hits = [r for r in items if r[3] != "header" and (q in r[1].lower() or q in r[2].lower())]
                if hits:
                    rows.append(("#" + cat[0], cat[1].upper(), "", "header", ""))
                    rows += hits
            return cats, None, rows
        ids = [c_[0][0] for c_ in cats]
        if self.set_cat not in ids:
            self.set_cat = ids[0]
        cat, rows = next(c_ for c_ in cats if c_[0][0] == self.set_cat)
        return cats, cat, rows

    def pick_settings_cat(self, cid):
        if self.set_cat != cid or self.set_query:
            self.set_off("settings", 0)
            self.scrolls.get("settings", {}).pop("over", None)
        self.set_cat = cid
        self.set_query = ""
        self.set_typing = False
        self.set_drill = True
        self.sound("move")
        self.request_draw()

    def settings_back(self):
        """B / Esc inside settings: leave search, then the category (narrow layout), then settings."""
        if self.set_query or self.set_typing:
            self.set_query, self.set_typing = "", False
        elif self.set_drill and self.set_narrow:
            self.set_drill = False
        else:
            self.page = None
        self.focus_id = None
        self.request_draw()

    def settings_search(self):
        self.set_typing = True
        self.set_drill = True

        def typed(kid, label):
            if kid == "bksp":
                self.set_query = self.set_query[:-1]
            elif kid == "space":
                self.set_query += " "
            elif kid == "enter":
                self.set_typing = False
                self.close_keyboard()
            else:
                self.set_query += label
            self.set_off("settings", 0)
            self.request_draw()
        if self.osk:
            self.close_keyboard()
        self.toggle_keyboard(target=typed)
        self.request_draw()

    def setting_row(self, key, label, desc, kind, value, x0, ry0, x1, ry1):
        T, k, c = self.t, self.k, self.c
        cy = (ry0 + ry1) / 2
        rid = f"set_{key}"
        if self.pressed == rid:
            self.rr(x0, ry0, x1, ry1, 14 * k, mix(T["panel2"], T["accent"], 0.18))
        elif self.hover_fill == rid:
            self.rr(x0, ry0, x1, ry1, 14 * k, mix(T["panel2"], T["text"], 0.05), outline=mix(T["panel2"], T["accent"], 0.35),
                    width=max(1, k))
        else:
            self.rr(x0, ry0, x1, ry1, 14 * k, T["panel2"])
        ix0, ix1 = x0 + 18 * k, x1 - 16 * k
        ctrl_w = 250 * k if kind == "step" else 76 * k if kind == "toggle" else 40 * k
        maxw = ix1 - ix0 - ctrl_w - 16 * k
        lf, df = self.font(16 * k, True), self.font(12.5 * k)
        if desc:
            self.text(ix0, cy - 1 * k, label, lf, T["text"], anchor="sw", maxw=maxw)
            self.text(ix0, cy + 3 * k, desc, df, T["muted"], anchor="nw", maxw=maxw)
        else:
            self.text(ix0, cy, label, lf, T["text"], anchor="w", maxw=maxw)
        adj = (lambda d, kk=key: self.adjust(kk, d))
        if kind == "link":
            c.create_text(ix1 - 10 * k, cy, text="›", font=self.font(28 * k, True), fill=T["accent"])
            self.region(rid, x0, ry0, x1, ry1, tap=lambda kk=key: self.adjust(kk, 1), sid="settings")
        elif kind == "toggle":
            self.toggle_switch(ix1, cy, value == "ON", pending=value == "…")
            self.region(rid, x0, ry0, x1, ry1, tap=lambda kk=key: self.adjust(kk, 1), adjust=adj, sid="settings")
        else:
            bs = 44 * k
            self.region(rid, x0, ry0, x1, ry1, tap=lambda kk=key: self.adjust(kk, 1), adjust=adj, sid="settings")
            for sign, bx0 in ((-1, ix1 - ctrl_w), (1, ix1 - bs)):
                bid = f"{rid}{'+' if sign > 0 else '-'}"
                fill = mix(T["panel"], T["accent"], 0.35) if self.pressed == bid else T["panel"]
                self.rr(bx0, cy - bs / 2, bx0 + bs, cy + bs / 2, 10 * k, fill)
                c.create_text(bx0 + bs / 2, cy, text="›" if sign > 0 else "‹", font=self.font(bs * 0.6, True), fill=T["text"])
                self.region(bid, bx0, cy - bs / 2, bx0 + bs, cy + bs / 2, tap=lambda kk=key, s_=sign: self.adjust(kk, s_),
                            focus=False, sid="settings")
            self.text(ix1 - ctrl_w / 2, cy, value, self.font(14.5 * k, True), T["accent"], anchor="center", maxw=ctrl_w - 2 * bs - 8 * k)

    def settings_rows_height(self, rows):
        k = self.k
        return sum(46 * k if r[3] == "header" else 78 * k for r in rows) + 24 * k

    def draw_settings_rows(self, rows, x0, y0, x1, y1):
        T, k = self.t, self.k
        off = self.scroll_area("settings", x0 - 6 * k, y0, x1 + 6 * k, y1, self.settings_rows_height(rows))
        self.clip_to(y0, y1)
        y = y0 - off
        hf = self.font(12.5 * k, True)
        if not rows:
            self.text((x0 + x1) / 2, y0 + 60 * k, f"Nothing matches “{self.set_query}”", self.font(15 * k), T["muted"], anchor="center")
        for key, label, desc, kind, value in rows:
            h = 46 * k if kind == "header" else 78 * k
            if y + h >= y0 and y <= y1:
                if kind == "header":
                    self.text(x0 + 4 * k, y + h - 12 * k, label, hf, T["accent"], anchor="sw")
                else:
                    self.setting_row(key, label, desc, kind, value, x0, y, x1, y + h - 8 * k)
            y += h
        self.end_clip()
        self.scrollbar("settings", x1 + 4 * k, y0, y1 - y0)

    def cat_icon(self, cat, cx, cy, size, on):
        T, k = self.t, self.k
        self.rr(cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2, 10 * k,
                T["accent"] if on else mix(T["panel2"], T["accent"], 0.18))
        col = T["accent_text"] if on else T["accent"]
        if self.icon_family:
            self.c.create_text(cx, cy, text=cat[2], font=self.font(size * 0.46, icon=True), fill=col)
        else:
            self.c.create_text(cx, cy, text=cat[3], font=self.font(size * 0.46, True), fill=col)

    def draw_settings_cats(self, cats, x0, y0, x1, y1, counts=None, full=False):
        """The category list: a sidebar in the wide layout, the whole page in the narrow one."""
        T, k = self.t, self.k
        rh = (84 if full else 64) * k
        off = self.scroll_area("setcats", x0, y0, x1, y1, rh * len(cats) + 10 * k)
        self.clip_to(y0, y1)
        nf, df = self.font((17 if full else 15) * k, True), self.font(12.5 * k)
        for i, (cat, rows) in enumerate(cats):
            ry0 = y0 + i * rh - off
            ry1 = ry0 + rh - 8 * k
            if ry1 < y0 or ry0 > y1:
                continue
            on = not full and not self.set_query and cat[0] == self.set_cat
            rid = f"cat_{cat[0]}"
            fill = mix(T["panel2"], T["accent"], 0.22) if on else mix(T["panel2"], T["accent"], 0.3) if self.pressed == rid else \
                T["panel2"] if full else T["panel"]
            self.rr(x0, ry0, x1, ry1, 14 * k, fill)
            if on:
                self.rr(x0, ry0 + 12 * k, x0 + 5 * k, ry1 - 12 * k, 2.5 * k, T["accent"])
            isz = (46 if full else 38) * k
            self.cat_icon(cat, x0 + 16 * k + isz / 2, (ry0 + ry1) / 2, isz, on)
            tx = x0 + 30 * k + isz
            right = ""
            if counts is not None:
                right = str(counts.get(cat[0], 0)) if counts.get(cat[0]) else ""
            elif full:
                right = "›"
            maxw = x1 - tx - 40 * k
            if full:
                self.text(tx, (ry0 + ry1) / 2 - 1 * k, tr(cat[1]), nf, T["text"], anchor="sw", maxw=maxw)
                self.text(tx, (ry0 + ry1) / 2 + 3 * k, cat[4], df, T["muted"], anchor="nw", maxw=maxw)
            else:
                self.text(tx, (ry0 + ry1) / 2, tr(cat[1]), nf, T["text"] if on or counts is None or counts.get(cat[0]) else T["muted"],
                          anchor="w", maxw=maxw)
            if right:
                self.text(x1 - 16 * k, (ry0 + ry1) / 2, right, self.font((24 if right == "›" else 13) * k, True),
                          T["accent"] if right != "›" else T["muted"], anchor="e")
            self.region(rid, x0, ry0, x1, ry1, tap=lambda c_=cat[0]: self.pick_settings_cat(c_), sid="setcats")
        self.end_clip()

    def draw_settings(self, x0, y0, x1, y1):
        T, k, c = self.t, self.k, self.c
        cats, cat, rows = self.settings_view()
        self.set_narrow = narrow = (x1 - x0) < 820 * k
        # search field across the top
        sh = 54 * k
        q = self.set_query
        active = self.set_typing
        sx1 = x1
        self.rr(x0, y0, sx1, y0 + sh, sh / 2, mix(T["panel2"], T["accent"], 0.12) if active else T["panel2"],
                outline=T["accent"] if active else T["line"], width=max(1, (2 if active else 1) * k))
        gx = x0 + 26 * k
        if self.icon_family:
            c.create_text(gx, y0 + sh / 2, text=ICONS["search"][0], font=self.font(18 * k, icon=True), fill=T["muted"])
        else:
            c.create_text(gx, y0 + sh / 2, text="⌕", font=self.font(20 * k, True), fill=T["muted"])
        caret = "▏" if active and int(time.time() * 2) % 2 == 0 else ""
        self.text(x0 + 50 * k, y0 + sh / 2, (q + caret) if (q or active) else tr("Search settings"), self.font(15.5 * k, bool(q)),
                  T["text"] if q else T["muted"], anchor="w", maxw=sx1 - x0 - 200 * k)
        if q:
            self.button("set_clear", sx1 - 110 * k, y0 + 7 * k, sx1 - 8 * k, y0 + sh - 7 * k, "CLEAR",
                        lambda: (setattr(self, "set_query", ""), setattr(self, "set_typing", False), self.request_draw()),
                        size=12 * k, focus=False)
        elif self.pad_on:
            self.pad_badge(sx1 - 28 * k, y0 + sh / 2, "Y", 12 * k)
        self.region("set_search", x0, y0, sx1 - (118 * k if q else 0), y0 + sh, tap=self.settings_search)
        top = y0 + sh + 16 * k
        counts = None
        if q:
            ql = q.strip().lower()
            counts = {c_[0][0]: sum(1 for r in c_[1] if r[3] != "header" and (ql in r[1].lower() or ql in r[2].lower()))
                      for c_ in cats}
        if narrow:
            if not self.set_drill and not q:
                self.draw_settings_cats(cats, x0, top, x1, y1, full=True)
                return
            if cat:
                hb = 48 * k
                self.button("set_up", x0, top, x0 + hb, top + hb, "‹", self.settings_back, size=24 * k, focus=False)
                self.cat_icon(cat, x0 + hb + 14 * k + 20 * k, top + hb / 2, 40 * k, True)
                self.text(x0 + hb + 74 * k, top + hb / 2, cat[1], self.font(20 * k, True), T["text"], anchor="w", maxw=x1 - x0 - 160 * k)
                top += hb + 14 * k
            self.draw_settings_rows(rows, x0, top, x1, y1)
            return
        sw = min(320 * k, (x1 - x0) * 0.34)
        self.draw_settings_cats(cats, x0, top, x0 + sw, y1, counts=counts)
        px0 = x0 + sw + 24 * k
        c.create_line(px0 - 12 * k, top, px0 - 12 * k, y1, fill=T["line"], width=max(1, k))
        if cat:
            self.text(px0, top + 2 * k, tr(cat[1]), self.font(22 * k, True), T["text"], maxw=x1 - px0)
            self.text(px0, top + 36 * k, cat[4], self.font(13 * k), T["muted"], maxw=x1 - px0)
            top += 70 * k
        else:
            n = sum(1 for r in rows if r[3] != "header")
            self.text(px0, top + 2 * k, f"{n} result{'s' if n != 1 else ''}", self.font(22 * k, True), T["text"], maxw=x1 - px0)
            top += 44 * k
        self.draw_settings_rows(rows, px0, top, x1 - 8 * k, y1)

    # -------------------------------------------------------------- the menu (everything that isn't a tab)
    def menu_items(self):
        items = [
            ("find", "Search everything", "\ue721", "/", "Games, settings and tools in one place  ·  Ctrl+K", self.open_find),
            ("settings", "Settings", "\ue713", "S", "Every option, by category", lambda: self.open_page("settings")),
            ("themes", "Themes", "\ue790", "T", "Colours, gradients and animated looks", lambda: self.open_page("themes")),
            ("checkup", "Checkup", "\ue95e", "+", "Find what's slowing this PC down", self.open_checkup),
            ("quick", "Quick settings", "\ue9e9", "Q", "Brightness, TDP, refresh rate and more", self.later_quick),
            ("discord", "Discord", "\ue8bd", "D", "Presence, recaps, mute and deafen", self.open_discord),
            ("buttons", "Back buttons", "\ue7fc", "B", "Map Y1–Y3 and M2/M3", self.open_back_buttons),
            ("bench", "Best TDP", "\uec4a", "W", "Find the lowest watts for smooth FPS", lambda: self.open_page("bench")),
            ("editor", "Make a theme", "\ue70f", "E", "Your own colours and wallpaper", self.open_editor),
            ("keyboard", "Keyboard", "\ue765", "K", "The controller-friendly keyboard", self.later_keyboard),
            ("automations", "Automations", "\ue945", "A", "When something happens, Vanta does something", lambda: self.open_info("automations")),
            ("recap", "Last game recap", "\ue9d9", "R", "How your last session went: FPS, battery and power",
             lambda: self.open_page("recap")),
            ("collections", "Collections", "\ue8f1", "C", "Your shelves and favorites, plus smart ones: unplayed, short sessions…",
             lambda: self.open_page("collections")),
            ("surprise", "Surprise me", "\ue790", "?", f"Switch to a random theme ({len(THEME_NAMES)} to pick from)",
             lambda: self.surprise_theme()),
            ("gameinfo", "Game notes & stats", "\ue70b", "N", "A note for where you left off, plus FPS, battery and sessions per game",
             lambda: self.open_gameinfo()),
            ("export", "Export play history", "\ue74e", "E", "Save every session to a spreadsheet file (CSV) in Documents",
             self.export_history),
            ("sleeptimer", "Sleep timer", "\ue708", "Z", "Sleep after 15 min to 2 h, or when the game closes",
             lambda: self.open_page("sleeptimer")),
            ("daynight", "Day & night themes", "\ue706", "N", "One theme for the day, another for the evening",
             lambda: self.open_page("daynight")),
            ("gamecolors", "Game colors", "\ue790", "A", "Accent color follows your game's art: " +
             ("on" if self.cfg["game_colors"] else "off"), self.toggle_game_colors),
            ("hometools", "Customize Home", "\ue80f", "H", "Pick the one-tap tools on Home", lambda: self.open_page("hometools")),
            ("guestsetup", "Guest mode", "\ue72e", "!", "Lend it out: only the games you pick, settings locked with a PIN",
             lambda: self.open_page("guestsetup")),
            ("reinstall", "Reinstall a game", "\ue896", "R", "Games you uninstalled, one tap from coming back", lambda: self.open_page("reinstall")),
            ("people", "Who's playing", "\ue77b", "P", "Profiles for each person: their own stats, notes, Up next and theme",
             lambda: self.open_page("people")),
            ("record", "Record a video", "\ue714", "R", "Start or stop a Game Bar recording", self.toggle_recording),
            ("sortcaps", "Sort captures by game", "\ue8b7", "S", "Copy screenshots and clips into a folder per game (Pictures › Vanta)",
             lambda: self.sort_captures()),
            ("news", "Game news & patches", "\ue789", "N", "Patch notes and news for the Steam games you play", self.open_news),
            ("padtest", "Controller tester", "\ue7fc", "C", "Every button, stick and trigger live, plus a drift check", self.open_padtest),
            ("dock", "Dock mode", "\ue7f4", "D", "Bigger on the TV, TV-only picture and a docked profile, undone when you unplug",
             lambda: self.open_page("dock")),
            ("storeclose", "Close store apps", "\ue711", "X", "Close Epic, EA, Ubisoft… a minute after their game closes",
             lambda: self.open_page("storeclose")),
            ("queue", "Up next", "\ue8fd", "U", "What you'll play next, in order, and the games you've finished", lambda: self.open_page("queue")),
            ("shortcuts", "Keyboard shortcuts", "\ue765", "K", "Ctrl+K search, Ctrl+1–4 sections and more", lambda: self.open_page("shortcuts")),
            ("bootreport", "Startup speed", "\ue916", "S", "How long Windows took to start, and what slowed it", self.open_bootreport),
            ("battery", "Battery health", "\ue83f", "B", "How worn the battery is, charge cycles, and its health over time",
             self.open_battery),
            ("leftovers", "Leftovers & duplicates", "\ue74d", "L", "Folders and caches uninstalled games left behind, and games installed twice",
             self.open_leftovers),
            ("friends", "Steam friends", "\ue716", "F", "Who's online and what they're playing", self.open_friends),
            ("weather", "Weather", "\ue753", "W", "Today's weather for Home", lambda: self.open_page("weather")),
            ("calendar", "Play calendar", "\ue787", "D", "The days you played, and a wrap of each month: top games, hours, best FPS",
             lambda: self.open_page("calendar")),
            ("badges", "Streaks & badges", "\ue7c1", "B", "Play streaks and milestones you've earned",
             lambda: self.open_page("badges")),
            ("bgoal", "Battery goal", "\ue83f", "G", "Pick how long to last: Vanta paces power and refresh to get there",
             lambda: self.open_page("bgoal")),
            ("playtime", "Play reminders", "\ue916", "P", "Break reminders and a daily play time limit",
             lambda: self.open_page("playtime")),
            ("pick", "What should I play?", "\ue7fc", "?", "A pick for the time and battery you've got", lambda: self.open_info("pick")),
            ("gallery", "Clips & screenshots", "\ue722", "C", "Your captures, newest first", lambda: self.open_info("gallery")),
            ("storage", "Storage cleanup", "\ue74d", "S", "Big games you haven't played in a while", lambda: self.open_info("storage")),
            ("network", "Network check", "\ue701", "N", "Ping, jitter, Wi-Fi band and quiet downloads", lambda: self.open_info("network")),
            ("stream", "Stream & cloud", "\ue7f4", "S", "Play from your gaming PC, Xbox Cloud or GeForce NOW", lambda: self.open_info("stream")),
            ("deals", "Free games & deals", "\ue719", "$", "Epic's free games and your Steam wishlist sales", lambda: self.open_info("deals")),
            ("retro", "RetroAchievements", "\ue734", "R", "Your retro achievements and points", lambda: self.open_info("retro")),
            ("updates", "Driver & BIOS updates", "\ue895", "U", "Check Lenovo's catalog for your Legion Go", lambda: self.open_info("updates")),
            ("log", "Activity log", "\ue81c", "L", "What Vanta did and when", lambda: self.open_page("log")),
            ("help", "Help", "\ue897", "?", "Controls, tips and saving a report", lambda: self.open_page("help")),
            ("about", f"About {APP_NAME}", "\ue946", "i", f"Version {VERSION} and what's new", lambda: self.open_page("about")),
        ]
        return items if self.device["legion"] else [m for m in items if m[0] not in ("buttons", "updates", "bench")]

    MENU_GROUPS = [("FIND & PLAY", ["find", "queue", "collections", "news", "pick", "reinstall", "gallery", "record", "sortcaps", "stream", "deals", "retro"]),
                   ("YOUR PLAY", ["calendar", "badges", "gameinfo", "recap", "export", "friends"]),
                   ("FAMILY & HABITS", ["people", "playtime", "guestsetup", "sleeptimer"]),
                   ("TUNE THIS PC", ["checkup", "quick", "bgoal", "battery", "leftovers", "bootreport", "storeclose", "bench", "automations", "storage", "network"]),
                   ("CONTROLS", ["buttons", "padtest", "dock", "keyboard", "shortcuts"]),
                   ("LOOK & FEEL", ["themes", "surprise", "daynight", "gamecolors", "hometools", "weather", "editor"]),
                   ("CONNECT", ["discord", "updates"]),
                   ("HELP & APP", ["settings", "log", "help", "about"])]

    def menu_sections(self):
        items = {m[0]: m for m in self.menu_items()}
        out, used = [], set()
        for title, ids in self.MENU_GROUPS:
            row = [items[i] for i in ids if i in items]
            used.update(i for i in ids if i in items)
            if row:
                out.append((title, row))
        rest = [m for mid, m in items.items() if mid not in used]
        if rest:
            out.append(("MORE", rest))
        return out

    def menu_height(self, w):
        k = self.k
        cols = self.menu_cols(w)
        return sum(40 * k + math.ceil(len(row) / cols) * (126 * k + 12 * k) for _, row in self.menu_sections())

    def menu_cols(self, w):
        k = self.k
        return 4 if w > 1500 * k else 3 if w > 660 * k else 2

    def menu_open(self, fn):
        self.sound("select")
        fn()
        # B on a page opened from the menu goes back to the menu
        self.page_from = "menu" if self.page and self.page != "menu" else None

    def later_quick(self):
        self.page = None
        self.request_draw()
        self.root.after(1, self.open_quick)

    def later_keyboard(self):
        self.page = None
        self.request_draw()
        self.root.after(1, self.toggle_keyboard)

    def draw_menu(self, x0, y0, x1, y1):
        """The menu in labelled sections, so related things sit together."""
        T, k = self.t, self.k
        cols = self.menu_cols(x1 - x0)
        gap = 12 * k
        tw = (x1 - x0 - gap * (cols - 1)) / cols
        th = 126 * k
        off = self.scroll_area("menu", x0, y0, x1, y1, self.menu_height(x1 - x0))
        self.clip_to(y0, y1)
        nf, df, gf = self.font(16 * k, True), self.font(12 * k), self.font(11.5 * k, True)
        y = y0 - off
        for title, row in self.menu_sections():
            if y + 40 * k >= y0 and y <= y1:
                self.text(x0 + 4 * k, y + 22 * k, tr(title), gf, T["muted"], anchor="w")
                self.c.create_line(x0 + 14 * k + self.measure(gf, tr(title)), y + 22 * k, x1, y + 22 * k,
                                   fill=mix(T["panel"], T["text"], 0.08))
            y += 40 * k
            for i, (mid, name, glyph, fb, desc, fn) in enumerate(row):
                r_, cn = divmod(i, cols)
                tx0, ty0 = x0 + cn * (tw + gap), y + r_ * (th + gap)
                tx1, ty1 = tx0 + tw, ty0 + th
                if ty1 < y0 or ty0 > y1:
                    continue
                rid = f"menu_{mid}"
                hot = mid == "find"
                self.surface(tx0, ty0, tx1, ty1, 18 * k, mix(T["panel2"], T["accent"], 0.16) if hot else T["panel2"])
                isz = 42 * k
                self.cat_icon((mid, name, glyph, fb, desc), tx0 + 16 * k + isz / 2, ty0 + 16 * k + isz / 2, isz, hot)
                self.text(tx0 + 16 * k, ty1 - 44 * k, tr(name), nf, T["text"], anchor="sw", maxw=tw - 32 * k)
                for j_, ln in enumerate(self.wrap(tr(desc), df, tw - 32 * k)[:2]):
                    self.text(tx0 + 16 * k, ty1 - 40 * k + j_ * df.metrics("linespace"), ln, df, T["muted"])
                self.region(rid, tx0, ty0, tx1, ty1, tap=lambda f=fn: self.menu_open(f), sid="menu")
            y += math.ceil(len(row) / cols) * (th + gap)
        self.end_clip()
        self.scrollbar("menu", x1 + 6 * k, y0, y1 - y0)

    def themes_height(self, cols):
        k = self.k
        rows = math.ceil(len(self.filtered_themes()) / cols)
        return 210 * k + rows * 122 * k

    def filtered_themes(self):
        f = getattr(self, "theme_filter", "all")
        return [n for n in THEME_NAMES if f == "all" or theme_kind(THEMES[n]) == f]

    def set_theme_filter(self, f):
        if f == "__edit":
            return self.open_editor()
        self.theme_filter = f
        self.set_off("themes", 0)
        self.request_draw()

    def draw_themes(self, x0, y0, x1, y1, cols):
        T, k, c = self.t, self.k, self.c
        cfg = self.cfg
        off = self.scroll_area("themes", x0, y0, x1, y1, self.themes_height(cols))
        if self.page != "themes":
            return
        y = y0 - off
        self.clip_to(y0, y1)
        lf, df = self.font(15 * k, True), self.font(12.5 * k)
        # accent colour row
        if y + 64 * k >= y0:
            self.text(x0, y + 4 * k, "Accent colour", lf, T["text"])
            r = 21 * k
            gap = 10 * k
            ax = x0 + 190 * k
            avail = x1 - ax
            r = min(r, (avail - gap * (len(ACCENTS) - 1)) / len(ACCENTS) / 2)
            for i, col in enumerate(ACCENTS):
                cx = ax + r + i * (2 * r + gap)
                cy = y + 4 * k + lf.metrics("linespace") / 2
                fill = col or THEMES[self.theme_name]["accent"]
                sel = cfg["accent"] == col
                if sel:
                    c.create_oval(cx - r - 5 * k, cy - r - 5 * k, cx + r + 5 * k, cy + r + 5 * k, outline=T["text"], width=max(2, 2 * k))
                c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline=T["line"])
                if not col:
                    c.create_text(cx, cy, text="A", font=self.font(r, True), fill=text_on_hex(fill))
                self.region(f"acc_{i}", cx - r - 4 * k, cy - r - 4 * k, cx + r + 4 * k, cy + r + 4 * k,
                            tap=lambda v=col: self.set_accent(v), sid="themes")
        y += 64 * k
        if y + 74 * k >= y0:
            cy = y + 26 * k
            self.text(x0, cy - 2 * k, "Follow Windows light/dark mode", lf, T["text"], anchor="sw", maxw=x1 - x0 - 100 * k)
            hint = (f"Tap a light theme to use it in light mode (now: {cfg['light_theme']})" if cfg["follow_windows"]
                    else "Switches to a light theme when Windows is in light mode")
            self.text(x0, cy + 2 * k, hint, df, T["muted"], anchor="nw", maxw=x1 - x0 - 100 * k)
            self.toggle_switch(x1, cy, cfg["follow_windows"])
            self.region("follow", x0, y, x1, y + 56 * k, tap=lambda: self.adjust("follow_windows", 1), sid="themes",
                        adjust=lambda d: self.adjust("follow_windows", 1))
        y += 74 * k
        if y + 62 * k >= y0:
            self.segmented("tfilter", x0, y, x1, y + 46 * k, [("all", "ALL"), ("classic", "CLASSIC"), ("gradient", "GRADIENT"),
                                                             ("animated", "ANIMATED"), ("minimal", "MINIMAL"), ("__edit", "+ MY THEME")],
                           getattr(self, "theme_filter", "all"), self.set_theme_filter)
            for r_ in self.regions[-6:]:
                r_["sid"] = "themes"
        y += 62 * k
        gap = 12 * k
        sw = (x1 - x0 - gap * (cols - 1)) / cols
        sh = 110 * k
        active = self.theme_name
        for i, name in enumerate(self.filtered_themes()):
            th = THEMES[name]
            r_, cn = divmod(i, cols)
            sx0, sy0 = x0 + cn * (sw + gap), y + r_ * (sh + gap)
            sx1, sy1 = sx0 + sw, sy0 + sh
            if sy1 < y0 or sy0 > y1:
                continue
            sel = name == active
            chosen = name in (cfg["theme"], cfg["light_theme"] if cfg["follow_windows"] else None)
            self.rr(sx0, sy0, sx1, sy1, 16 * k, th["bg"], outline=T["accent"] if sel else th["line"],
                    width=max(2, 3 * k) if sel else max(1, k))
            pad = 12 * k
            if th.get("grad"):
                stops = th["grad"]
                n = 12
                gw = (sx1 - sx0 - 2 * pad) / n
                for j in range(n):
                    c.create_rectangle(sx0 + pad + j * gw, sy0 + pad, sx0 + pad + (j + 1) * gw + 1, sy0 + sh * 0.5,
                                       fill=grad_color(stops, j / (n - 1)), width=0)
            else:
                self.rr(sx0 + pad, sy0 + pad, sx1 - pad, sy0 + sh * 0.5, 8 * k, th["panel"],
                        outline=th["line"] if th.get("outline") else "", width=max(1, k))
            kind = theme_kind(th)
            if kind != "classic":
                bf = self.font(10 * k, True)
                label = {"animated": "ANIMATED", "gradient": "GRADIENT", "minimal": "COMPACT"}[kind]
                bw_ = bf.measure(label) + 14 * k
                c.create_rectangle(sx1 - pad - bw_, sy1 - pad - 20 * k, sx1 - pad, sy1 - pad, fill=th["accent"], width=0)
                c.create_text(sx1 - pad - bw_ / 2, sy1 - pad - 10 * k, text=label, font=bf, fill=th["accent_text"])
            bw = (sx1 - sx0 - 2 * pad)
            for j, key in enumerate(("accent", "accent2", "good", "warn")):
                self.rr(sx0 + pad + 10 * k + j * bw * 0.2, sy0 + sh * 0.26, sx0 + pad + 10 * k + j * bw * 0.2 + bw * 0.16,
                        sy0 + sh * 0.38, 4 * k, th[key])
            nf = self.font(min(15 * k, sh * 0.15), True)
            tag = "" if th["dark"] else "  ☀"
            badge_w = (self.font(10 * k, True).measure("ANIMATED") + 22 * k) if theme_kind(th) != "classic" else 0
            self.text(sx0 + pad, sy1 - pad, ("✓ " if chosen else "") + name + tag, nf, th["text"], anchor="sw", maxw=sw - 2 * pad - badge_w)
            if self.pressed == f"theme_{name}":
                self.rr(sx0, sy0, sx1, sy1, 16 * k, "", outline=th["accent"], width=max(2, 4 * k))
            self.region(f"theme_{name}", sx0, sy0, sx1, sy1, tap=lambda n=name: self.set_theme(n), sid="themes")
        self.end_clip()
        self.scrollbar("themes", x1 + 6 * k, y0, y1 - y0)

    # ---------------------------------------------------------------- post-game recap
    def show_recap_soon(self):
        """Open the recap once you're back (it waits if a page is open or the window is hidden)."""
        if not self.recap_new:
            return
        if self.hidden or self.game or (self.page and self.page != "recap"):
            self.root.after(2000, self.show_recap_soon)
            return
        self.recap_new = False
        self.page_from = None
        self.page = "recap"
        self.focus_id = None
        self.set_off("recap", 0)
        self.request_draw()

    def cards_recap(self):
        r = self.recap or next(iter(self.cfg["sessions"]), None)
        if not r:
            return [{"id": "none", "title": "NO GAMES YET", "lines": [("Play a game for a minute or more and its recap shows up "
                                                                         "here when you close it.", "muted")], "buttons": []}]
        T = self.t
        name = r["name"]
        hours = r["dur"] / 3600
        prev = next((x for x in self.cfg["sessions"] if x is not r and x["start"] < r["start"] and
                     (x.get("id") and x.get("id") == r.get("id") or x["name"].lower() == name.lower())), None)
        when = time.strftime("%a %d %b, %H:%M", time.localtime(r["start"]))
        lines = [(f"Played {fmt_duration(r['dur'])}  ·  started {when}", "text")]
        rows = []
        if r.get("fps"):
            rows.append(("Average FPS", f"{r['fps']:.0f}" + (f"  (1% low {r['low']:.0f})" if r.get("low") else ""),
                         "fps", r["fps"], lambda x: x.get("fps"), 1))
        if r.get("batt") is not None and r["batt"] > 0:
            per_h = r["batt"] / max(hours, 0.05)
            rows.append(("Battery used", f"{r['batt']}%  ·  {per_h:.0f}% an hour", "batt", per_h,
                         lambda x: x["batt"] / max(x["dur"] / 3600, 0.05) if x.get("batt") else None, -1))
        if r.get("w"):
            rows.append(("Average power", f"{r['w']:.1f} W", "w", r["w"], lambda x: x.get("w"), -1))
        if r.get("tdp"):
            rows.append(("TDP", f"{r['tdp']} W" + (f"  ·  capped at {r['cap']} FPS" if r.get("cap") else ""), "tdp", None, None, 0))
        rows.append(("Peak RAM", f"{r['peak'] * 100:.0f}%", "ram", None, None, 0))
        for label, value, key, now_v, get_prev, better in rows:
            line = f"{label}:  {value}"
            col = "text"
            if prev and now_v is not None and get_prev and get_prev(prev):
                pv = get_prev(prev)
                diff = now_v - pv
                if abs(diff) >= (1 if key != "w" else 0.3):
                    unit = {"fps": " FPS", "batt": "%/h", "w": " W"}[key]
                    good = (diff > 0) == (better > 0)
                    line += f"   {'▲' if diff > 0 else '▼'} {abs(diff):.0f}{unit} vs last time" if key != "w" else \
                        f"   {'▲' if diff > 0 else '▼'} {abs(diff):.1f} W vs last time"
                    col = "good" if good else "warn"
            lines.append((line, col))
        if not prev:
            lines.append(("First recap for this game: the next one compares with it.", "muted"))
        tips = []
        if r.get("fps") and r["fps"] > 75 and r.get("batt"):
            tips.append("You ran well above 60 FPS on battery: a 60 FPS cap or Best TDP would stretch it further.")
        if r.get("batt") and r["batt"] / max(hours, 0.05) > 45:
            tips.append("Heavy on battery: try the Battery stretch preset in Game settings.")
        if r.get("fps") and r["fps"] < 35:
            tips.append("Below 35 FPS on average: a lower resolution, or 800p + RSR, usually helps most.")
        g = next((x for x in self.library or [] if x["id"] == r.get("id") or x["name"].lower() == name.lower()), None)
        buttons = []
        if g:
            buttons.append(("PLAY AGAIN", lambda g_=g: (setattr(self, "page", None), self.play(g_)), "accent"))
            buttons.append(("GAME SETTINGS", lambda g_=g: (setattr(self, "page", None), self.open_tune(g_["id"], g_["name"])), "normal"))
            buttons.append(("✎ EDIT NOTE" if self.note_of(g["id"]) else "✎ ADD A NOTE",
                            lambda g_=g: (self.open_gameinfo(g_), self.edit_note()), "normal"))
        if self.device["legion"]:
            buttons.append(("BEST TDP", lambda: self.open_page("bench"), "normal"))
        cards = [{"id": "sum", "title": name.upper(), "lines": lines, "buttons": buttons}]
        if tips:
            cards.append({"id": "tips", "title": "SUGGESTIONS", "lines": [(t_, "text") for t_ in tips], "buttons": []})
        recent = [x for x in self.cfg["sessions"] if x is not r and (x.get("id") == r.get("id") or x["name"].lower() == name.lower())][:5]
        if recent:
            hist = []
            for x in recent:
                bits = [time.strftime("%a %d %b", time.localtime(x["start"])), fmt_duration(x["dur"])]
                if x.get("fps"):
                    bits.append(f"{x['fps']:.0f} FPS")
                if x.get("batt"):
                    bits.append(f"{x['batt']}% battery")
                if x.get("w"):
                    bits.append(f"{x['w']:.1f} W")
                hist.append(("  ·  ".join(bits), "muted"))
            cards.append({"id": "hist", "title": "EARLIER SESSIONS", "lines": hist, "buttons": []})
        return cards

    # ---------------------------------------------------------------- smart collections
    SMART = [("unplayed", "Unplayed", "Installed but never started"),
             ("short", "Short sessions", "You usually play these for under 40 minutes"),
             ("battery", "Easy on battery", "A low-power preset, or under 12 W in your sessions"),
             ("lately", "Haven't played lately", "Played before, but not in the last 30 days"),
             ("presets", "Presets ready", "A tested Legion Go preset is waiting"),
             ("big", "Big installs", "Over 40 GB on disk")]

    def smart_ids(self, cid):
        lib = [g for g in self.library or [] if not str(g["id"]).startswith("sample:")]
        now = time.time()
        sess = {}
        for x in self.cfg["sessions"]:
            sess.setdefault(x.get("id") or x["name"].lower(), []).append(x)
        mine = lambda g: sess.get(g["id"], []) + sess.get(g["name"].lower(), [])
        out = set()
        for g in lib:
            last, mins = self.game_stats(g)
            ss = mine(g)
            if cid == "unplayed":
                hit = not last and not mins and not ss
            elif cid == "short":
                hit = len(ss) >= 2 and sum(x["dur"] for x in ss) / len(ss) < 2400
            elif cid == "battery":
                pre = self.find_preset(g["name"])
                ws = [x["w"] for x in ss if x.get("w")]
                hit = bool(pre and pre.get("tdp") and pre["tdp"] <= 15) or bool(ws and sum(ws) / len(ws) <= 12)
            elif cid == "lately":
                hit = bool(last) and now - last > 30 * 86400
            elif cid == "presets":
                hit = bool(self.find_preset(g["name"]))
            elif cid == "big":
                hit = (g.get("size") or 0) > 40e9
            else:
                hit = False
            if hit:
                out.add(g["id"])
        return out

    def show_collection(self, cid):
        self.page = None
        self.set_tab("play")
        self.cfg["lib_filter"] = "smart:" + cid
        self.set_off("lib", 0)
        view = self.lib_games()
        if view:
            self.lib_sel = view[0]["id"]
        self.request_draw()

    def cards_collections(self):
        if self.library is None:
            return [{"id": "ld", "title": "ONE MOMENT", "lines": [("Finding your games…", "muted")], "buttons": []}]
        cards = self.shelf_cards()
        tail = self.genre_cards()
        for cid, title, desc in self.SMART:
            ids = self.smart_ids(cid)
            names = [g["name"] for g in self.library if g["id"] in ids][:4]
            lines = [(desc, "muted")]
            if names:
                lines.append((", ".join(names) + ("…" if len(ids) > 4 else ""), "text"))
            cards.append({"id": cid, "title": f"{title.upper()}  ·  {len(ids)}", "lines": lines,
                          "buttons": [(f"SHOW {len(ids)}", lambda c_=cid: self.show_collection(c_), "accent")] if ids else []})
        return cards + tail

    # ---------------------------------------------------------------- game notes and per-game stats
    def note_of(self, gid):
        n = self.cfg["notes"].get(gid)
        return n["text"] if n else ""

    def open_gameinfo(self, g=None):
        g = g or self.selected_game() or self.home_game()
        if not g:
            self.show_toast("Pick a game first")
            return
        self.info_game = g
        self.info_caps = None
        self.page_from = None
        self.page = "gameinfo"
        self.focus_id = None
        sess = self.game_sessions(g)

        def work():
            try:
                caps = [c_ for c_ in systools.list_captures(400)
                        if any(x["start"] - 60 <= c_["time"] <= x["start"] + x["dur"] + 60 for x in sess)]
            except Exception:
                caps = []
            self.call(lambda: (setattr(self, "info_caps", caps), self.request_draw()))
        self.background(work)
        self.request_draw()

    def game_sessions(self, g):
        nm = g["name"].lower()
        return [x for x in self.cfg["sessions"] if x.get("id") == g["id"] or x["name"].lower() == nm]

    def edit_note(self):
        g = getattr(self, "info_game", None)
        if not g:
            return
        self._note_edit = self.note_of(g["id"])

        def typed(kid, label):
            if self._note_edit is None:
                return
            if kid == "bksp":
                self._note_edit = self._note_edit[:-1]
            elif kid == "space":
                self._note_edit += " "
            elif kid == "enter":
                self.save_note(g, self._note_edit)
                self._note_edit = None
                self.close_keyboard()
            else:
                self._note_edit = (self._note_edit + label)[:240]
            self.request_draw()
        if self.osk:
            self.close_keyboard()
        self.toggle_keyboard(target=typed)
        self.request_draw()

    def save_note(self, g, text):
        text = (text or "").strip()[:240]
        notes = dict(self.cfg["notes"])
        if text:
            notes[g["id"]] = {"text": text, "t": time.time(), "name": g["name"]}
            self.show_toast("Note saved")
        else:
            notes.pop(g["id"], None)
        self.cfg["notes"] = notes
        self.request_draw()

    def paste_note(self):
        g = self.info_game
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        if text.strip():
            self.save_note(g, " ".join(text.split()))
        else:
            self.show_toast("Copy some text first")

    def cards_gameinfo(self):
        g = getattr(self, "info_game", None)
        if not g:
            return [{"id": "none", "title": "NO GAME", "lines": [("Pick a game first.", "muted")], "buttons": []}]
        k = self.k
        cards = []
        editing = getattr(self, "_note_edit", None)
        note = self.cfg["notes"].get(g["id"])
        if editing is not None:
            lines = [((editing or "") + "▌", "accent"), ("Type with the keyboard below, then press Enter to save.", "muted")]
            btns = [("SAVE", lambda: (self.save_note(g, self._note_edit), setattr(self, "_note_edit", None), self.close_keyboard()), "accent"),
                    ("CANCEL", lambda: (setattr(self, "_note_edit", None), self.close_keyboard(), self.request_draw()), "normal")]
        elif note:
            lines = [(note["text"], "text"), (f"Written {time.strftime('%b %d, %H:%M', time.localtime(note['t']))}  ·  "
                                              "shows on Home and over the game when you start it", "muted")]
            armed = self.is_armed("note_clear")
            btns = [("EDIT", self.edit_note, "accent"), ("PASTE", self.paste_note, "normal"),
                    ("TAP AGAIN" if armed else "CLEAR", lambda: self.confirm("note_clear", lambda: self.save_note(g, ""), "Tap again to clear the note"),
                     "danger" if armed else "normal")]
        else:
            lines = [("Where did you leave off? A boss to beat, a quest to finish, the settings that worked… "
                      "It shows on Home and over the game when you start it.", "muted")]
            btns = [("WRITE A NOTE", self.edit_note, "accent"), ("PASTE", self.paste_note, "normal")]
        cards.append({"id": "note", "title": "✎ NOTE", "lines": lines, "buttons": btns})
        cards.append(self.finish_card(g))
        cards.append(self.guides_card(g))
        cards.append(self.extras_card(g))
        ac_ = self.args_card(g)
        if ac_:
            cards.append(ac_)
        cards.append(self.sound_card(g))
        for extra_ in (self.news_card(g), self.friends_card(g)):
            if extra_:
                cards.append(extra_)
        ss = self.game_sessions(g)
        last, mins = self.game_stats(g)
        if not ss:
            cards.append({"id": "stats", "title": "PLAY", "lines": [
                (f"{fmt_duration(mins * 60)} played in all." if mins else "Not played yet.", "text"),
                ("Play it with Vanta running to see FPS, battery and power here.", "muted")], "buttons": []})
            return cards
        tot = sum(x["dur"] for x in ss)
        fp = [(x["fps"], x["dur"]) for x in ss if x.get("fps")]
        avg_fps = sum(a * b for a, b in fp) / sum(b for _, b in fp) if fp else None
        bat = [(x["batt"], x["dur"]) for x in ss if x.get("batt") and x["batt"] > 0 and x["dur"] >= 900]
        per_h = sum(a for a, _ in bat) / (sum(b for _, b in bat) / 3600) if bat else None
        lines = [(f"{fmt_duration(max(mins * 60, tot))} in all  ·  {len(ss)} session{'s' if len(ss) != 1 else ''} with Vanta  ·  "
                  f"about {fmt_duration(tot / len(ss))} each", "text")]
        if avg_fps:
            best = max((x for x in ss if x.get("fps")), key=lambda x: x["fps"])
            lines.append((f"{avg_fps:.0f} FPS on average  ·  best {best['fps']:.0f} on {time.strftime('%b %d', time.localtime(best['start']))}", "text"))
        if per_h:
            lines.append((f"Uses about {per_h:.0f}% battery an hour: a full charge lasts around {fmt_duration(100 / per_h * 3600)}", "text"))
        by_tdp = {}
        for x in ss:
            if x.get("tdp") and x.get("fps") and x.get("w"):
                by_tdp.setdefault(x["tdp"], []).append((x["fps"], x["w"]))
        if len(by_tdp) >= 2:
            eff = max(by_tdp.items(), key=lambda kv: sum(f / w for f, w in kv[1]) / len(kv[1]))
            f_ = sum(f for f, _ in eff[1]) / len(eff[1])
            w_ = sum(w for _, w in eff[1]) / len(eff[1])
            lines.append((f"Best FPS per watt: {eff[0]} W TDP ({f_:.0f} FPS at {w_:.1f} W)", "good"))
        recent = list(reversed(ss[:14]))
        bh = 110 * k

        def paint(x0, y, x1, recent=recent):
            T = self.t
            fs = self.font(10 * k)
            n = len(recent)
            gap = 6 * k
            bw = min(46 * k, (x1 - x0 - gap * (n - 1)) / max(1, n))
            top = max(x["dur"] for x in recent) or 1
            for i, x in enumerate(recent):
                bx = x0 + i * (bw + gap)
                h = max(4 * k, (bh - 40 * k) * x["dur"] / top)
                by1 = y + bh - 22 * k
                self.rr(bx, by1 - h, bx + bw, by1, 5 * k, mix(T["panel2"], T["accent"], 0.85 if i == n - 1 else 0.55))
                if x.get("fps"):
                    self.text(bx + bw / 2, by1 - h - 3 * k, f"{x['fps']:.0f}", fs, T["muted"], anchor="s")
                self.text(bx + bw / 2, by1 + 4 * k, time.strftime("%d/%m" if self.cfg["lang"] not in ("en",) else "%m/%d",
                                                                    time.localtime(x["start"])), fs, T["muted"], anchor="n")
        cards.append({"id": "stats", "title": f"{g['name'].upper()}  ·  RECENT SESSIONS",
                      "lines": lines + [("Bars are session length; the number on top is the average FPS.", "muted")],
                      "buttons": [("GAME SETTINGS", lambda: (setattr(self, "page", None), self.open_tune(g["id"], g["name"])), "normal"),
                                  ("CALENDAR", lambda: self.open_page("calendar"), "normal")],
                      "extra": bh, "paint": paint})
        caps = getattr(self, "info_caps", None)
        if caps is None:
            cl = [("Looking for screenshots and clips…", "muted")]
        elif caps:
            nshot = sum(1 for c_ in caps if c_["kind"] == "shot")
            cl = [(f"{nshot} screenshot{'s' if nshot != 1 else ''} and {len(caps) - nshot} clip{'s' if len(caps) - nshot != 1 else ''} "
                   f"taken while playing", "text")]
        else:
            cl = [("None taken while playing yet. Quick settings › Screenshot, or Win+Alt+PrtScn.", "muted")]
        cards.append({"id": "caps", "title": "SCREENSHOTS & CLIPS", "lines": cl,
                      "buttons": [("OPEN GALLERY", lambda: self.open_page("gallery"), "normal")] if caps else []})
        return cards

    # ---------------------------------------------------------------- Steam review scores
    def review_of(self, g):
        appid = g["id"].split(":", 1)[1] if g["id"].startswith("steam:") else (self.cfg["art_ids"].get(g["id"]) or None)
        if not appid:
            return None
        r = self.reviews.get(appid)
        if r is None:
            self.reviews[appid] = "loading"

            def work():
                try:
                    res = systools.steam_reviews(appid)
                except Exception:
                    res = None
                self.call(lambda: (self.reviews.__setitem__(appid, res or "none"), self.request_draw()))
            self.background(work)
            return None
        return r if isinstance(r, dict) else None

    def review_chip(self, g):
        r = self.review_of(g)
        if not r or r.get("pct") is None:
            return None
        return f"Reviews {r['pct']}%"

    # ---------------------------------------------------------------- genres
    def genres_of(self, g):
        return self.cfg["genres"].get(g["id"]) or []

    def fetch_genres(self):
        if getattr(self, "genres_started", False) or not self.library:
            return
        self.genres_started = True
        todo = []
        for g in self.library:
            if g["id"] in self.cfg["genres"] or str(g["id"]).startswith(("rom:", "custom:")) or \
                    (str(g["id"]).startswith("sample:") and not PREVIEW):
                continue
            appid = g["id"].split(":", 1)[1] if g["id"].startswith("steam:") else self.cfg["art_ids"].get(g["id"])
            if appid:
                todo.append((g["id"], appid))
        if not todo:
            return

        def work():
            for gid, appid in todo[:150]:
                try:
                    gen = systools.steam_genres(appid)
                except Exception:
                    break  # offline or rate-limited: try again next start
                self.call(lambda gid_=gid, gen_=gen: self.cfg["genres"].__setitem__(gid_, gen_))
                time.sleep(1.3)  # Steam's store allows about 200 lookups per 5 minutes
            self.call(self.request_draw)
        self.background(work)

    def genre_counts(self):
        cnt = {}
        ids = {g["id"] for g in self.library or []}
        for gid, gens in self.cfg["genres"].items():
            if gid in ids:
                for x in gens:
                    cnt[x] = cnt.get(x, 0) + 1
        return sorted(cnt.items(), key=lambda kv: -kv[1])

    def genre_cards(self):
        cards = []
        for name, n in self.genre_counts()[:10]:
            names = [g["name"] for g in self.library if name in self.genres_of(g)][:4]
            cards.append({"id": "gen_" + name, "title": f"{name.upper()}  ·  {n}", "lines": [(", ".join(names) + ("…" if n > 4 else ""), "text")],
                          "buttons": [(f"SHOW {n}", lambda nm=name: self.show_shelf("genre:" + nm), "accent")]})
        return cards

    # ---------------------------------------------------------------- reinstall list
    def track_library(self, games):
        """Remember every game seen; ones that disappear (while their store still lists others) go on the reinstall list."""
        known = dict(self.cfg["known_games"])
        gone = dict(self.cfg["gone_games"])
        now_ids = {g["id"] for g in games}
        live_sources = {g["source"] for g in games}
        for gid, info in list(known.items()):
            if gid not in now_ids and info.get("source") in live_sources and gid not in gone:
                gone[gid] = dict(info, t=time.time())
        for g in games:
            if str(g["id"]).startswith(("sample:", "rom:")):
                continue
            known[g["id"]] = {"name": g["name"], "source": g["source"], "launch": g.get("launch", "")}
            gone.pop(g["id"], None)
        self.cfg["known_games"] = known
        self.cfg["gone_games"] = dict(sorted(gone.items(), key=lambda kv: -kv[1]["t"])[:60])

    def reinstall_target(self, gid, info):
        src = info.get("source")
        if gid.startswith("steam:"):
            return f"steam://install/{gid.split(':', 1)[1]}"
        if src == "Epic" and "action=launch" in (info.get("launch") or ""):
            return info["launch"].replace("action=launch", "action=install")
        if gid.startswith("gog:"):
            return f"goggalaxy://openGameView/{gid.split(':', 1)[1]}"
        return None

    def cards_reinstall(self):
        gone = self.cfg["gone_games"]
        if not gone:
            return [{"id": "none", "title": "NOTHING TO REINSTALL",
                     "lines": [("Games you uninstall show up here, so they're one tap away when you want them back.", "muted")],
                     "buttons": []}]
        cards = [{"id": "sum", "title": f"UNINSTALLED  ·  {len(gone)}",
                  "lines": [("Games that were installed before. Reinstalling opens the store's install screen.", "muted")], "buttons": []}]
        for gid, info in gone.items():
            tgt = self.reinstall_target(gid, info)
            btns = ([("REINSTALL", lambda t=tgt, n=info["name"]: (systools.open_target(t), self.add_log("GAME", f"Reinstalling {n}")), "accent")]
                    if tgt else []) + [("FORGET", lambda gid_=gid: self.forget_gone(gid_), "normal")]
            cards.append({"id": "g_" + gid, "title": info["name"].upper(),
                          "lines": [(f"{info.get('source', '')}  ·  gone since {time.strftime('%b %d', time.localtime(info['t']))}" +
                                     ("" if tgt else f"  ·  reinstall it from the {info.get('source', 'store')} app"), "muted")],
                          "buttons": btns})
        return cards

    def forget_gone(self, gid):
        gone = dict(self.cfg["gone_games"])
        gone.pop(gid, None)
        self.cfg["gone_games"] = gone
        self.request_draw()

    # ---------------------------------------------------------------- guides and launch options
    def guides_card(self, g):
        appid = g["id"].split(":", 1)[1] if g["id"].startswith("steam:") else self.cfg["art_ids"].get(g["id"])
        import urllib.parse as _up
        q = _up.quote(g["name"])
        btns = []
        if appid:
            btns.append(("STEAM GUIDES", lambda: systools.open_target(f"https://steamcommunity.com/app/{appid}/guides/"), "normal"))
        btns.append(("PCGAMINGWIKI", lambda: systools.open_target(f"https://www.pcgamingwiki.com/w/index.php?search={q}"), "normal"))
        btns.append(("SEARCH THE WEB", lambda: systools.open_target(f"https://duckduckgo.com/?q={q}+guide"), "normal"))
        r = self.review_of(g)
        lines = []
        if r and r.get("pct") is not None:
            lines.append((f"Steam reviews: {r['desc']}  ·  {r['pct']}% of {r['total']:,} positive", "good" if r["pct"] >= 80 else "text"))
        gens = self.genres_of(g)
        if gens:
            lines.append(("Genres: " + ", ".join(gens), "muted"))
        lines.append(("Walkthroughs, fixes and tips for this game.", "muted"))
        return {"id": "guides", "title": "GUIDES & REVIEWS", "lines": lines, "buttons": btns}

    def launch_args_of(self, g):
        return (self.cfg["launch_args"].get(g["id"]) or "").strip()

    def args_card(self, g):
        if not (g["source"] in ("Added", "GOG", "Ubisoft", "EA", "Battle.net") and g.get("exe")) and not g["id"].startswith("steam:"):
            return None
        cur = self.launch_args_of(g)
        typing = getattr(self, "_args_edit", None)
        if typing is not None:
            lines = [(typing + "▌", "accent"), ("Type the options, then press Enter. Example: -dx11 -windowed", "muted")]
            btns = [("SAVE", lambda: self.save_args(g, self._args_edit), "accent"),
                    ("CANCEL", lambda: (setattr(self, "_args_edit", None), self.close_keyboard(), self.request_draw()), "normal")]
        else:
            lines = [(cur or "None", "text" if cur else "muted"),
                     ("Extra options passed to the game when Vanta starts it (like -dx11, -windowed or -skipintro).", "muted")]
            btns = [("EDIT", lambda: self.edit_args(g), "normal")] + ([("CLEAR", lambda: self.save_args(g, ""), "normal")] if cur else [])
        return {"id": "args", "title": "LAUNCH OPTIONS", "lines": lines, "buttons": btns}

    def edit_args(self, g):
        self._args_edit = self.launch_args_of(g)

        def typed(kid, label):
            if self._args_edit is None:
                return
            if kid == "bksp":
                self._args_edit = self._args_edit[:-1]
            elif kid == "space":
                self._args_edit += " "
            elif kid == "enter":
                self.save_args(g, self._args_edit)
                return
            else:
                self._args_edit = (self._args_edit + label)[:200]
            self.request_draw()
        if self.osk:
            self.close_keyboard()
        self.toggle_keyboard(target=typed)
        self.request_draw()

    def save_args(self, g, text):
        la = dict(self.cfg["launch_args"])
        text = (text or "").strip()
        if text:
            la[g["id"]] = text
        else:
            la.pop(g["id"], None)
        self.cfg["launch_args"] = la
        self._args_edit = None
        if self.osk:
            self.close_keyboard()
        self.show_toast("Launch options saved" if text else "Launch options cleared")
        self.request_draw()

    def with_launch_args(self, g):
        args = self.launch_args_of(g)
        if not args:
            return g
        import shlex
        try:
            parts = shlex.split(args, posix=False)
        except ValueError:
            parts = args.split()
        if g["id"].startswith("steam:"):
            import urllib.parse as _up
            return dict(g, launch=f"steam://run/{g['id'].split(':', 1)[1]}//{_up.quote(args)}/")
        if g.get("exe") and "://" not in g.get("launch", "") and not g.get("launch", "").startswith("shell:"):
            return dict(g, args=list(g.get("args") or []) + parts)
        return g

    # ---------------------------------------------------------------- recording and sorting captures
    def toggle_recording(self):
        systools.toggle_recording()
        self.recording = not getattr(self, "recording", False)
        msg = "Recording… (Win+Alt+R or this button again to stop)" if self.recording else "Recording stopped: saved to Captures"
        self.show_toast(msg)
        self.add_log("TOOL", "Game Bar recording " + ("started" if self.recording else "stopped"))
        self.buzz()
        self.request_draw()

    def sort_captures(self, sessions=None, quiet=False):
        ss = sessions if sessions is not None else list(self.cfg["sessions"])
        base = os.path.join(os.path.expanduser("~"), "Pictures", APP_NAME, "Captures")

        def work():
            try:
                caps = systools.list_captures(1000)
            except Exception:
                caps = []
            n = 0
            for c_ in caps:
                hit = next((x for x in ss if x["start"] - 30 <= c_["time"] <= x["start"] + x["dur"] + 90), None)
                if not hit:
                    continue
                folder = os.path.join(base, re.sub(r'[<>:"/\\|?*]+', "", hit["name"]).strip() or "Game")
                try:
                    if systools.copy_capture(c_["path"], folder):
                        n += 1
                except OSError:
                    continue

            def fin():
                if n or not quiet:
                    self.show_toast(f"Sorted {n} new capture{'s' if n != 1 else ''} into Pictures › {APP_NAME} › Captures" if n
                                    else "Nothing new to sort")
                if n:
                    self.add_log("TOOL", f"Sorted {n} captures by game")
            self.call(fin)
        if not quiet:
            self.show_toast("Sorting captures by game…")
        self.background(work)

    # ---------------------------------------------------------------- profiles for different people
    PEOPLE_KEYS = ("notes", "queue", "finished", "sessions", "play_days", "badges_seen", "favorites", "lists", "home_tools", "home_row",
                   "theme", "accent", "news_seen", "break_every", "daily_limit", "limit_day", "limit_warn", "wrap_told", "game_volume")

    def person_name(self):
        return self.cfg["person"] or "Me"

    def switch_person(self, name):
        if name == self.person_name():
            return
        c = self.cfg
        people = dict(c["people"])
        people[self.person_name()] = {k: json.loads(json.dumps(c[k])) for k in self.PEOPLE_KEYS}
        nxt = people.pop(name, None)
        if nxt is None:
            nxt = {k: json.loads(json.dumps(Config.DEFAULTS[k])) for k in self.PEOPLE_KEYS if k in Config.DEFAULTS}
        for k, v in nxt.items():
            c[k] = v
        c["people"] = people
        c["person"] = name
        self.recap = None
        self.recap_new = False
        self.home_sel = None
        self.add_log("TOOL", f"Now playing as {name}")
        self.show_toast(f"Hi, {name}")
        self.request_draw()

    def new_person(self):
        self._person_new = ""

        def typed(kid, label):
            if self._person_new is None:
                return
            if kid == "bksp":
                self._person_new = self._person_new[:-1]
            elif kid == "space":
                self._person_new += " "
            elif kid == "enter":
                nm = self._person_new.strip()[:20]
                self._person_new = None
                self.close_keyboard()
                if nm and nm != self.person_name() and nm not in self.cfg["people"]:
                    if not self.cfg["person"]:
                        self.cfg["person"] = "Me"
                    self.switch_person(nm)
                elif nm:
                    self.show_toast("That name is taken")
            else:
                self._person_new = (self._person_new + label)[:20]
            self.request_draw()
        if self.osk:
            self.close_keyboard()
        self.toggle_keyboard(target=typed)
        self.request_draw()

    def delete_person(self, name):
        people = dict(self.cfg["people"])
        people.pop(name, None)
        self.cfg["people"] = people
        self.show_toast(f"Removed {name}")
        self.request_draw()

    def cards_people(self):
        me = self.person_name()
        typing = getattr(self, "_person_new", None)
        cards = [{"id": "p", "title": "WHO'S PLAYING?",
                  "lines": [("Each person gets their own notes, Up next, finished games, play stats, streaks, badges, favorites, "
                             "shelves, Home tiles, theme and reminders. Settings and per-game tuning are shared.", "muted")] +
                           ([(f"New person: {typing}▌", "accent")] if typing is not None else []),
                  "buttons": [("+ ADD SOMEONE", self.new_person, "accent")]}]
        cards.append({"id": "me", "title": f"● {me.upper()}  ·  PLAYING NOW", "lines": [(f"{len(self.cfg['sessions'])} sessions", "muted")],
                      "buttons": []})
        for name, data in sorted(self.cfg["people"].items()):
            armed = self.is_armed(f"pdel_{name}")
            cards.append({"id": "p_" + name, "title": name.upper(), "lines": [(f"{len(data.get('sessions') or [])} sessions", "muted")],
                          "buttons": [("SWITCH", lambda n=name: self.switch_person(n), "accent"),
                                      ("TAP AGAIN" if armed else "REMOVE",
                                       lambda n=name: self.confirm(f"pdel_{n}", lambda: self.delete_person(n), f"Tap again to remove {n} and their stats"),
                                       "danger" if armed else "normal")]})
        return cards

    # ---------------------------------------------------------------- per-game volume
    def game_proc_match(self):
        g = self.game
        if not g:
            return lambda pid: False
        exe = (g.get("exe") or "").lower()
        pids = {g["pid"]}
        try:
            for pid, name, _ in list_processes():
                if name.lower() == exe:
                    pids.add(pid)
        except Exception:
            pass
        return lambda pid: pid in pids

    def apply_game_audio(self, tries=0):
        g = self.game
        if not g:
            return
        hub = g.get("hub") or {}
        vol = self.cfg["game_volume"].get(hub.get("id")) if hub else None
        quiet = self.cfg["quiet_others"]
        if vol is None and quiet >= 100:
            return
        match = self.game_proc_match()

        def work():
            hit = 0
            try:
                if vol is not None:
                    hit = systools.set_app_volume(match, vol / 100)
                if quiet < 100 and g.get("audio_saved") is None:
                    saved = systools.quiet_other_apps(match, quiet / 100)
                    g["audio_saved"] = saved
            except Exception as ex:
                msg = str(ex)
                self.call(lambda: self.add_log("FAIL", f"Game volume: {msg}"))
                return
            if vol is not None and not hit and tries < 3:
                self.root.after(15000, lambda: self.apply_game_audio(tries + 1))  # the game hasn't made a sound yet
            elif vol is not None and hit:
                self.call(lambda: self.add_log("GAME", f"Game volume {vol}%"))
        self.background(work)

    def restore_game_audio(self, g):
        saved = g.get("audio_saved")
        if saved:
            self.background(lambda: systools.restore_app_volumes(saved))

    def set_game_volume(self, gid, v):
        gv = dict(self.cfg["game_volume"])
        if v is None:
            gv.pop(gid, None)
        else:
            gv[gid] = v
        self.cfg["game_volume"] = gv
        if self.game and (self.game.get("hub") or {}).get("id") == gid:
            self.apply_game_audio()
        self.request_draw()

    def sound_card(self, g):
        cur = self.cfg["game_volume"].get(g["id"])
        q = self.cfg["quiet_others"]
        lab = lambda v: "MUTED" if v == 0 else "NORMAL" if v >= 100 else f"{v}%"
        return {"id": "sound", "title": "SOUND",
                "lines": [(f"Game volume: {cur}%" if cur is not None else "Game volume: as Windows has it", "text"),
                          (f"Other apps while you play: {lab(q).lower()} (for every game)", "muted")],
                "buttons": [(("AS IS" if v is None else f"{v}%") + (" ✓" if v == cur else ""), lambda v_=v: self.set_game_volume(g["id"], v_),
                             "accent" if v == cur else "normal") for v in (None, 25, 50, 75, 100)] +
                           [("OTHERS: " + lab(v) + (" ✓" if v == q else ""), lambda v_=v: (self.cfg.__setitem__("quiet_others", v_), self.request_draw()),
                             "accent" if v == q else "normal") for v in (100, 30, 0)]}

    # ---------------------------------------------------------------- patch notes and news for your Steam games
    def news_games(self):
        lib = [g for g in (self.library or []) if g["source"] == "Steam" and str(g["id"]).startswith("steam:")]
        lib.sort(key=lambda g: self.game_stats(g)[0] or 0, reverse=True)
        return lib[:12]

    def news_tick(self, force=False):
        if not self.cfg["game_news"] or self.library is None:
            return
        if not force and time.time() - getattr(self, "news_t", 0) < 1800:
            return
        self.news_t = time.time()
        todo = [g for g in self.news_games() if force or time.time() - self.news.get(g["id"], (0, None))[0] > 6 * 3600]
        if not todo:
            return

        def work():
            for g in todo:
                try:
                    items = systools.steam_news(g["id"].split(":", 1)[1], 4)
                except Exception:
                    continue
                self.call(lambda gid=g["id"], it=items: (self.news.__setitem__(gid, (time.time(), it)), self.request_draw()))
                time.sleep(0.4)
        self.background(work)

    def fresh_patch(self, g, days=3):
        it = (self.news.get(g["id"]) or (0, []))[1] or []
        p = next((x for x in it if x["patch"] and time.time() - x["date"] < days * 86400), None)
        return p

    def open_news(self):
        self.news_tick(True)
        if self.page != "news":
            self.open_page("news")

    def cards_news(self):
        if not self.cfg["game_news"]:
            return [{"id": "off", "title": "GAME NEWS IS OFF", "lines": [("Turn it on to see patch notes for your Steam games.", "muted")],
                     "buttons": [("TURN ON", lambda: (self.cfg.__setitem__("game_news", True), self.news_tick(True), self.request_draw()),
                                  "accent")]}]
        games = self.news_games()
        if not games:
            return [{"id": "none", "title": "NO STEAM GAMES", "lines": [("News comes from Steam, so it covers your Steam games.", "muted")],
                     "buttons": []}]
        rows = []
        for g in games:
            for it in (self.news.get(g["id"]) or (0, []))[1] or []:
                rows.append((it["date"], g, it))
        rows.sort(key=lambda r: -r[0])
        if not rows:
            return [{"id": "ld", "title": "ONE MOMENT", "lines": [("Getting news from Steam…", "muted")],
                     "buttons": [("REFRESH", lambda: self.news_tick(True), "normal")]}]
        cards = []
        for i, (dt, g, it) in enumerate(rows[:24]):
            age = time.time() - dt
            when = "today" if age < 86400 else "yesterday" if age < 2 * 86400 else f"{int(age // 86400)} days ago"
            cards.append({"id": f"n{i}", "title": ("PATCH  ·  " if it["patch"] else "") + g["name"].upper() + f"  ·  {when}",
                          "lines": [(it["title"], "text"), (it["text"][:220] + ("…" if len(it["text"]) > 220 else ""), "muted")],
                          "buttons": [("READ", lambda u=it["url"]: systools.open_target(u), "normal")] if it["url"] else []})
        return cards

    def news_card(self, g):
        if not g["id"].startswith("steam:") or not self.cfg["game_news"]:
            return None
        it = (self.news.get(g["id"]) or (0, None))[1]
        if it is None:
            if g["id"] not in getattr(self, "news_asked", set()):
                self.__dict__.setdefault("news_asked", set()).add(g["id"])

                def work():
                    try:
                        items = systools.steam_news(g["id"].split(":", 1)[1], 4)
                    except Exception:
                        items = []
                    self.call(lambda: (self.news.__setitem__(g["id"], (time.time(), items)), self.request_draw()))
                self.background(work)
            return {"id": "news", "title": "LATEST NEWS", "lines": [("Getting news from Steam…", "muted")], "buttons": []}
        if not it:
            return {"id": "news", "title": "LATEST NEWS", "lines": [("No news posted for this game.", "muted")], "buttons": []}
        x = it[0]
        return {"id": "news", "title": "LATEST NEWS" + ("  ·  PATCH" if x["patch"] else ""),
                "lines": [(x["title"], "text"), (time.strftime("%b %d", time.localtime(x["date"])) + "  ·  " + x["text"][:180], "muted")],
                "buttons": ([("READ", lambda: systools.open_target(x["url"]), "normal")] if x["url"] else []) +
                           [("ALL NEWS", self.open_news, "normal")]}

    # ---------------------------------------------------------------- controller tester
    def pad_axes(self):
        """(source, buttons, lx, ly, rx, ry, lt, rt) right now, sticks -1…1 (up is +), triggers 0…1. None without a pad."""
        p = self.pad
        if not p:
            return None
        if p.slot is not None:
            st = p._read(p.slot)
            if st:
                g = st.Gamepad
                n = lambda v: max(-1.0, v / 32767)
                return ("Xbox (XInput)", g.wButtons, n(g.sThumbLX), n(g.sThumbLY), n(g.sThumbRX), n(g.sThumbRY),
                        (g.bLeftTrigger & 0xFF) / 255, (g.bRightTrigger & 0xFF) / 255)
        hs = p.hid_state()
        if hs:
            _, b, lx, ly, lt, rt = hs
            return ("Legion controller report", b, lx, -ly, None, None, lt / 255, rt / 255)
        return None

    def open_padtest(self):
        self.drift = None
        if self.page != "padtest":
            self.open_page("padtest")
        self.padtest_loop()

    def padtest_loop(self):
        if self.page != "padtest" or self.hidden:
            return
        st = getattr(self, "drift_run", None)
        if st:
            ax = self.pad_axes()
            if ax:
                st["l"] = max(st["l"], math.hypot(ax[2], ax[3]))
                if ax[4] is not None:
                    st["r"] = max(st["r"], math.hypot(ax[4], ax[5]))
            if time.time() >= st["end"]:
                self.drift_run = None
                self.drift = st
        self.request_draw("page")
        self.root.after(50, self.padtest_loop)

    def start_drift(self):
        self.drift = None
        self.drift_run = {"end": time.time() + 3, "l": 0.0, "r": 0.0}
        self.show_toast("Hands off the sticks for 3 seconds…")

    def cards_padtest(self):
        k = self.k
        ax = self.pad_axes()
        if not ax:
            return [{"id": "none", "title": "NO CONTROLLER", "lines": [("Attach the controllers (or plug one in) and they'll show up here.", "muted")],
                     "buttons": []}]
        src, b, lx, ly, rx, ry, lt, rt = ax
        hgt = 230 * k

        def paint(x0, y, x1):
            T = self.t
            R = 64 * k
            fs, fb = self.font(11 * k), self.font(12 * k, True)
            for i, (lab, sx, sy) in enumerate((("LEFT STICK", lx, ly), ("RIGHT STICK", rx, ry))):
                cx, cy = x0 + R + 10 * k + i * (2 * R + 40 * k), y + R + 10 * k
                self.c.create_oval(cx - R, cy - R, cx + R, cy + R, outline=mix(T["panel2"], T["text"], 0.25), width=max(1, 2 * k))
                dz = R * 7849 / 32767
                self.c.create_oval(cx - dz, cy - dz, cx + dz, cy + dz, outline=mix(T["panel2"], T["text"], 0.12), dash=(3, 3))
                if sx is None:
                    self.text(cx, cy, "not in this mode", fs, T["muted"], anchor="center")
                else:
                    px_, py_ = cx + sx * R, cy - sy * R
                    self.c.create_oval(px_ - 9 * k, py_ - 9 * k, px_ + 9 * k, py_ + 9 * k, fill=T["accent"], outline="")
                    self.text(cx, cy + R + 14 * k, f"{lab}  {math.hypot(sx, sy) * 100:.0f}%", fs, T["muted"], anchor="center")
            tx = x0 + 4 * R + 110 * k
            for j, (lab, v) in enumerate((("LT", lt), ("RT", rt))):
                bx = tx + j * 46 * k
                self.rr(bx, y + 10 * k, bx + 26 * k, y + 2 * R + 10 * k, 6 * k, mix(T["panel2"], T["text"], 0.08))
                h_ = (2 * R) * (v or 0)
                if h_ > 2:
                    self.rr(bx, y + 2 * R + 10 * k - h_, bx + 26 * k, y + 2 * R + 10 * k, 6 * k, T["accent"])
                self.text(bx + 13 * k, y + 2 * R + 24 * k, f"{lab} {int((v or 0) * 100)}", fs, T["muted"], anchor="center")
            gx = tx + 110 * k
            names = [("A", 0x1000), ("B", 0x2000), ("X", 0x4000), ("Y", 0x8000), ("LB", 0x0100), ("RB", 0x0200), ("VIEW", 0x0020),
                     ("MENU", 0x0010), ("LS", 0x0040), ("RS", 0x0080), ("↑", 0x0001), ("↓", 0x0002), ("←", 0x0004), ("→", 0x0008)]
            cols = 4
            bw = min(70 * k, (x1 - gx) / cols - 8 * k)
            for i, (lab, m) in enumerate(names):
                r_, c_ = divmod(i, cols)
                bx, by = gx + c_ * (bw + 8 * k), y + 10 * k + r_ * 42 * k
                on = bool(b & m)
                self.rr(bx, by, bx + bw, by + 34 * k, 10 * k, T["accent"] if on else mix(T["panel2"], T["text"], 0.08))
                self.text(bx + bw / 2, by + 17 * k, lab, fb, T["accent_text"] if on else T["text"], anchor="center")
        lines = [(f"Reading: {src}. Press anything: it lights up here. The dashed ring is Windows' usual dead zone.", "muted")]
        if self.pad and self.pad.stuck:
            names = [n for m, n in ((1, "up"), (2, "down"), (4, "left"), (8, "right")) if self.pad.stuck & m]
            lines.append(("Ignoring " + " and ".join(names) + ": held for 8 s without a break, so Vanta treats it as drift", "warn"))
        d = getattr(self, "drift", None)
        if getattr(self, "drift_run", None):
            lines.append(("Measuring… keep your hands off the sticks", "accent"))
        elif d:
            verdict = lambda v: "fine" if v < 0.05 else "slight drift (games' dead zones usually hide it)" if v < 0.1 else "drift: games may move on their own"
            lines.append((f"Left stick rests at {d['l'] * 100:.0f}% ({verdict(d['l'])})" +
                          (f"  ·  right stick {d['r'] * 100:.0f}% ({verdict(d['r'])})" if ax[4] is not None else ""),
                          "good" if max(d["l"], d["r"]) < 0.05 else "warn"))
        btns = [("CHECK FOR DRIFT", self.start_drift, "accent"),
                ("TEST VIBRATION", lambda: (self.pad.rumble(0.7, 450) if self.pad else None,
                                            self.show_toast("Buzz… (needs Xbox mode)" if self.pad and self.pad.slot is None else "Buzz…")),
                 "normal")]
        return [{"id": "pad", "title": "CONTROLLER TESTER", "lines": lines, "buttons": btns, "extra": hgt, "paint": paint}]

    # ---------------------------------------------------------------- dock mode
    def dock_tick(self):
        c = self.cfg
        if not c["dock_auto"]:
            return
        try:
            n = systools.monitor_count()
            size = systools.screen_size()
        except Exception:
            return
        on = getattr(self, "dock_saved", None) is not None
        if n <= 1 and not on:
            self.internal_size = size
        docked = n >= 2 or (on and getattr(self, "internal_size", None) not in (None, size))
        if docked and not on:
            self.dock_enter()
        elif not docked and on:
            self.dock_leave()

    def dock_enter(self):
        c = self.cfg
        self.dock_saved = {"ui_scale": c["ui_scale"], "profile": c["profile"]}
        what = []
        if c["dock_scale"] and c["dock_scale"] != c["ui_scale"]:
            c["ui_scale"] = c["dock_scale"]
            what.append(f"size {c['dock_scale']}%")
        if c["dock_profile"] and c["dock_profile"] != c["profile"]:
            self.apply_profile(c["dock_profile"], "AUTO")
            what.append({"saver": "Battery saver", "balanced": "Balanced", "max": "Max performance"}.get(c["dock_profile"], c["dock_profile"]))
        if c["dock_switch"]:
            self.background(lambda: systools.display_switch("external"))
            what.append("TV only")
        self.add_log("TOOL", "Docked" + (": " + ", ".join(what) if what else ""))
        self.show_toast("Docked" + (": " + ", ".join(what) if what else ""))
        self.push_event("Docked", ", ".join(what))
        self.request_draw()

    def dock_leave(self, manual=False):
        saved, self.dock_saved = self.dock_saved, None
        c = self.cfg
        if saved:
            c["ui_scale"] = saved["ui_scale"]
            if c["dock_profile"] and saved["profile"] and saved["profile"] != c["profile"]:
                self.apply_profile(saved["profile"], "AUTO")
        if manual and c["dock_switch"]:
            self.background(lambda: systools.display_switch("internal"))
        self.add_log("TOOL", "Undocked: back to handheld")
        self.show_toast("Undocked")
        self.request_draw()

    def cards_dock(self):
        c = self.cfg
        on = getattr(self, "dock_saved", None) is not None
        scales = [0, 125, 150, 175, 200]
        profs = [("", "KEEP"), ("balanced", "BALANCED"), ("max", "MAX"), ("saver", "SAVER")]
        cards = [{"id": "dock", "title": "DOCK MODE" + ("  ·  DOCKED NOW" if on else ""),
                  "lines": [("When you plug into a TV or monitor, Vanta makes everything bigger for the couch and can switch the "
                             "picture to the TV and change the performance profile. Unplug and it all goes back.", "muted"),
                            ("On" if c["dock_auto"] else "Off", "good" if c["dock_auto"] else "text")],
                  "buttons": [("TURN OFF" if c["dock_auto"] else "TURN ON",
                               lambda: (c.__setitem__("dock_auto", not c["dock_auto"]), self.dock_tick(), self.request_draw()),
                               "normal" if c["dock_auto"] else "accent")] +
                             ([("UNDOCK NOW", lambda: self.dock_leave(True), "normal")] if on else [])},
                 {"id": "dsize", "title": "SIZE ON THE TV", "lines": [("How big everything gets when docked.", "muted")],
                  "buttons": [(("KEEP" if v == 0 else f"{v}%") + (" ✓" if v == c["dock_scale"] else ""),
                               lambda v_=v: (c.__setitem__("dock_scale", v_), self.request_draw()),
                               "accent" if v == c["dock_scale"] else "normal") for v in scales]},
                 {"id": "dprof", "title": "PERFORMANCE WHEN DOCKED", "lines": [("Plugged in at the TV, Max is usually fine.", "muted")],
                  "buttons": [(lab + (" ✓" if v == c["dock_profile"] else ""), lambda v_=v: (c.__setitem__("dock_profile", v_), self.request_draw()),
                               "accent" if v == c["dock_profile"] else "normal") for v, lab in profs]},
                 {"id": "dsw", "title": "PICTURE", "lines": [
                     ("TV only: the handheld's screen turns off while docked, like Win+P › Second screen only. "
                      "Windows turns it back on when you unplug.", "muted")],
                  "buttons": [("TV ONLY ✓" if c["dock_switch"] else "TV ONLY", lambda: (c.__setitem__("dock_switch", True), self.request_draw()),
                               "accent" if c["dock_switch"] else "normal"),
                              ("LEAVE AS IS ✓" if not c["dock_switch"] else "LEAVE AS IS",
                               lambda: (c.__setitem__("dock_switch", False), self.request_draw()), "accent" if not c["dock_switch"] else "normal")]}]
        return cards

    # ---------------------------------------------------------------- close store apps after playing
    def after_game_stores(self, hub):
        src = (hub or {}).get("source")
        if src not in self.cfg["close_stores"] or src not in systools.STORE_APPS:
            return

        def later():
            if self.game:
                return
            names = systools.STORE_APPS[src]

            def work():
                closed = systools.close_apps(names)
                if closed:
                    self.call(lambda: self.add_log("GAME", f"Closed {src} after the game"))
            self.background(work)
        self.root.after(60000, later)

    def toggle_store_close(self, src):
        lst = list(self.cfg["close_stores"])
        lst.remove(src) if src in lst else lst.append(src)
        self.cfg["close_stores"] = lst
        self.request_draw()

    def cards_storeclose(self):
        have = sorted({g["source"] for g in self.library or []} & set(systools.STORE_APPS)) or sorted(systools.STORE_APPS)
        return [{"id": "sc", "title": "CLOSE STORE APPS AFTER PLAYING",
                 "lines": [("A minute after a game closes (and no other game is running), Vanta closes the store app that started "
                            "it, so it stops using memory and battery in the background.", "muted")],
                 "buttons": [(src.upper() + (" ✓" if src in self.cfg["close_stores"] else ""), lambda s_=src: self.toggle_store_close(s_),
                              "accent" if src in self.cfg["close_stores"] else "normal") for src in have]}]

    # ---------------------------------------------------------------- up next queue, finished games and ratings
    def queue_games(self):
        byid = {g["id"]: g for g in self.library or []}
        return [byid[i] for i in self.cfg["queue"] if i in byid]

    def queue_toggle(self, g):
        q = list(self.cfg["queue"])
        if g["id"] in q:
            q.remove(g["id"])
            self.show_toast(f"Took {g['name']} off Up next")
        else:
            q.append(g["id"])
            self.show_toast(f"{g['name']} is #{len(q)} in Up next")
        self.cfg["queue"] = q
        self.request_draw()

    def queue_move(self, gid, d):
        q = list(self.cfg["queue"])
        if gid in q:
            i = q.index(gid)
            j = max(0, min(len(q) - 1, i + d))
            q[i], q[j] = q[j], q[i]
            self.cfg["queue"] = q
        self.request_draw()

    def set_finished(self, g, done=True, stars=None):
        fin = dict(self.cfg["finished"])
        if done:
            cur = dict(fin.get(g["id"]) or {"t": time.time(), "name": g["name"]})
            if stars is not None:
                cur["stars"] = stars
            fin[g["id"]] = cur
            if g["id"] in self.cfg["queue"]:
                self.cfg["queue"] = [i for i in self.cfg["queue"] if i != g["id"]]
            if stars is None:
                self.show_toast(f"Finished {g['name']}!")
                self.push_event("Game finished", g["name"])
                self.add_log("GAME", f"Finished {g['name']}")
        else:
            fin.pop(g["id"], None)
        self.cfg["finished"] = fin
        self.request_draw()

    def finish_card(self, g):
        fin = self.cfg["finished"].get(g["id"])
        q = self.cfg["queue"]
        inq = g["id"] in q
        lines = []
        if fin:
            st = fin.get("stars")
            lines.append((f"Finished {time.strftime('%b %d, %Y', time.localtime(fin['t']))}" +
                          (f"  ·  {'★' * st}{'☆' * (5 - st)}" if st else "  ·  rate it below"), "good"))
            btns = [(("★" * n), lambda n_=n: self.set_finished(g, True, n_), "accent" if fin.get("stars") == n else "normal") for n in range(1, 6)]
            btns.append(("NOT FINISHED", lambda: self.set_finished(g, False), "normal"))
        else:
            lines.append((f"#{q.index(g['id']) + 1} in Up next" if inq else "Not in Up next", "text"))
            lines.append(("Up next is your list of what to play next, in order. It shows on Home.", "muted"))
            btns = [("TAKE OFF UP NEXT" if inq else "+ UP NEXT", lambda: self.queue_toggle(g), "normal" if inq else "accent"),
                    ("MARK FINISHED", lambda: self.set_finished(g, True), "normal")]
        return {"id": "finish", "title": "UP NEXT & FINISHED", "lines": lines, "buttons": btns}

    def cards_queue(self):
        qs = self.queue_games()
        cards = [{"id": "q", "title": f"UP NEXT  ·  {len(qs)}",
                  "lines": [("What you'll play next, in order. Add games with + UP NEXT on a game's NOTES & STATS page; marking one "
                             "finished takes it off.", "muted")], "buttons": []}]
        for i, g in enumerate(qs):
            btns = [("▶ PLAY", lambda g_=g: (setattr(self, "page", None), self.play(g_)), "accent" if i == 0 else "normal")]
            if i > 0:
                btns.append(("▲", lambda gid=g["id"]: self.queue_move(gid, -1), "normal"))
            if i < len(qs) - 1:
                btns.append(("▼", lambda gid=g["id"]: self.queue_move(gid, 1), "normal"))
            btns += [("✓ FINISHED", lambda g_=g: self.set_finished(g_, True), "normal"), ("✕", lambda g_=g: self.queue_toggle(g_), "normal")]
            mins = self.game_stats(g)[1]
            cards.append({"id": f"q{i}", "title": f"{i + 1}.  {g['name'].upper()}",
                          "lines": [(f"{fmt_duration(mins * 60)} played" if mins else "Not started yet", "muted")], "buttons": btns})
        fin = sorted(self.cfg["finished"].items(), key=lambda kv: -kv[1]["t"])
        if fin:
            cards.append({"id": "fin", "title": f"FINISHED  ·  {len(fin)}",
                          "lines": [(f"{v['name']}  ·  {time.strftime('%b %Y', time.localtime(v['t']))}" +
                                     (f"  ·  {'★' * v['stars']}" if v.get("stars") else ""), "text") for _, v in fin[:25]],
                          "buttons": []})
        return cards

    # ---------------------------------------------------------------- friends' playtime in one game
    def compare_friends(self, g):
        key, sid = self.cfg["steam_key"], self.cfg["steam_id"]
        self.friend_hours = {"gid": g["id"], "data": None}
        self.request_draw()

        def work():
            sid_ = sid or systools.steam_user_id()
            if not key or not sid_:
                res = "setup"
            else:
                try:
                    res = systools.friends_playtime(key, sid_, g["id"].split(":", 1)[1])
                except Exception:
                    res = "offline"
            self.call(lambda: (setattr(self, "friend_hours", {"gid": g["id"], "data": res}), self.request_draw()))
        self.background(work)

    def friends_card(self, g):
        if not g["id"].startswith("steam:"):
            return None
        fh = getattr(self, "friend_hours", None)
        mine = self.game_stats(g)[1] / 60
        if not fh or fh["gid"] != g["id"]:
            return {"id": "fh", "title": "YOU AND YOUR FRIENDS", "lines": [("How your hours compare with your Steam friends who own it.", "muted")],
                    "buttons": [("COMPARE", lambda: self.compare_friends(g), "normal")]}
        d = fh["data"]
        if d is None:
            lines = [("Asking Steam… (one moment per friend)", "muted")]
        elif d == "setup":
            lines = [("Needs your Steam Web API key (Settings › Stores & deals).", "muted")]
        elif d == "offline":
            lines = [("Couldn't reach Steam.", "muted")]
        elif not d:
            lines = [("None of your friends with public profiles own it.", "muted")]
        else:
            rows = sorted(d + [("You", round(mine, 1))], key=lambda x: -x[1])
            lines = [(f"{i + 1}.  {n}: {h:g} h", "good" if n == "You" else "text") for i, (n, h) in enumerate(rows[:10])]
        return {"id": "fh", "title": "YOU AND YOUR FRIENDS", "lines": lines,
                "buttons": [("REFRESH", lambda: self.compare_friends(g), "normal")] if isinstance(d, list) else []}

    # ---------------------------------------------------------------- keyboard shortcuts
    SHORTCUTS = [("Ctrl+K", "Search everything"), ("Ctrl+1 … Ctrl+4", "Home, Library, Tune, Insights"), ("Ctrl+,", "Settings"),
                 ("Ctrl+M", "Menu"), ("Ctrl+Q", "Quick settings"), ("Ctrl+N", "Notes & stats for the selected game"),
                 ("Ctrl+U", "Up next"), ("Ctrl+P", "Play the selected game"), ("F1", "Help"), ("F11", "Full screen"),
                 ("Esc", "Back"), ("Tab / Shift+Tab", "Next / previous section"), ("Arrows, Enter", "Move around and select")]

    def on_ctrl_key(self, ks):
        ks = ks.lower()
        secs = {"1": "home", "2": "play", "3": "memory", "4": "stats"}
        if ks in secs:
            sec = self.section_of(secs[ks])
            self.page = None
            self.set_tab(self.sec_last.get(sec[0], sec[2][0]) if sec else secs[ks])
        elif ks == "comma":
            self.open_page("settings") if self.page != "settings" else None
        elif ks == "m":
            self.open_page("menu") if self.page != "menu" else None
        elif ks == "q":
            self.toggle_quick()
        elif ks == "n":
            self.open_gameinfo()
        elif ks == "u":
            self.open_page("queue") if self.page != "queue" else None
        elif ks == "p":
            g = self.selected_game() if self.tab == "play" else self.home_game()
            self.play(g)
        else:
            return False
        self.request_draw()
        return True

    def cards_shortcuts(self):
        return [{"id": "sc", "title": "KEYBOARD SHORTCUTS", "lines": [(f"{a}   ·   {b}", "text") for a, b in self.SHORTCUTS] +
                 [("Without Ctrl, single letters also work on the main screen: B Game Boost, F focus mode, S settings, H help.", "muted")],
                 "buttons": []}]

    # ---------------------------------------------------------------- startup speed
    def open_bootreport(self):
        self.boot = None
        if self.page != "bootreport":
            self.open_page("bootreport")

        def work():
            try:
                r = systools.boot_report()
            except Exception:
                r = None
            self.call(lambda: (setattr(self, "boot", r if r is not None else "fail"), self.request_draw()))
        self.background(work)

    def cards_bootreport(self):
        r = getattr(self, "boot", None)
        if r is None:
            return [{"id": "ld", "title": "ONE MOMENT", "lines": [("Reading Windows' startup records…", "muted")], "buttons": []}]
        if r == "fail":
            return [{"id": "f", "title": "COULDN'T READ THEM", "lines": [("Windows didn't share its startup records.", "muted")],
                     "buttons": [("TRY AGAIN", self.open_bootreport, "normal")]}]
        cards = []
        last = r.get("last")
        up = f"Last started {time.strftime('%b %d, %H:%M', time.localtime(last))} (up {fmt_duration(time.time() - last)})" if last else ""
        boots = r.get("boots") or []
        if boots:
            t, tot, main, post = boots[0]
            avg = sum(b[1] for b in boots) / len(boots)
            lines = [(f"Last startup took {tot:.0f} s: {main:.0f} s to the desktop, then {post:.0f} s settling in" if main and post else
                      f"Last startup took {tot:.0f} s", "text"),
                     (f"Average of the last {len(boots)}: {avg:.0f} s  ·  " + ("quick" if avg < 30 else "OK" if avg < 60 else "slow"),
                      "good" if avg < 30 else "text" if avg < 60 else "warn")]
            if up:
                lines.append((up, "muted"))
            cards.append({"id": "boot", "title": "STARTUP SPEED", "lines": lines,
                          "buttons": [("STARTUP APPS", lambda: (setattr(self, "page", None), self.set_tab("startup")), "normal")]})
        else:
            cards.append({"id": "boot", "title": "STARTUP SPEED",
                          "lines": [(up or "No startup records yet.", "text"),
                                    ("Windows keeps detailed startup timings only when it runs its own diagnostics; "
                                     "they'll show here once it has some.", "muted")],
                          "buttons": [("STARTUP APPS", lambda: (setattr(self, "page", None), self.set_tab("startup")), "normal")]})
        slow = r.get("slow") or []
        if slow:
            cards.append({"id": "slow", "title": "WHAT SLOWED IT DOWN",
                          "lines": [(f"{n}: +{s_:.1f} s", "text") for n, s_ in slow] +
                                   [("Turning off startup apps you don't need (Insights › Startup) helps the most.", "muted")],
                          "buttons": []})
        return cards

    # ---------------------------------------------------------------- launch extras: programs with/after a game
    BROWSERS = ["chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "vivaldi.exe"]

    def extras_of(self, gid):
        return dict(self.cfg["launch_extras"].get(gid) or {})

    def set_extra(self, gid, key, val):
        ex = self.extras_of(gid)
        if val in (None, False, ""):
            ex.pop(key, None)
        else:
            ex[key] = val
        le = dict(self.cfg["launch_extras"])
        if ex:
            le[gid] = ex
        else:
            le.pop(gid, None)
        self.cfg["launch_extras"] = le
        self.request_draw()

    def pick_extra(self, gid, key):
        from tkinter import filedialog
        f = filedialog.askopenfilename(parent=self.root, title="Pick a program",
                                       filetypes=[("Programs", "*.exe *.bat *.cmd *.lnk *.url"), ("All files", "*.*")])
        if f:
            self.set_extra(gid, key, os.path.normpath(f))

    def run_launch_extras(self, g, when):
        ex = self.extras_of(g["id"])
        if not ex:
            return
        if when == "with":
            if ex.get("with"):
                self.add_log("GAME", f"Starting {os.path.basename(ex['with'])} with {g['name']}")
                self.background(lambda: systools.open_target(ex["with"]))
            if ex.get("browsers"):
                def work():
                    closed = systools.close_apps(self.BROWSERS)
                    if closed:
                        self.call(lambda: self.add_log("GAME", "Closed browsers for the game: " + ", ".join(closed)))
                self.background(work)
        elif when == "after" and ex.get("after"):
            self.add_log("GAME", f"Starting {os.path.basename(ex['after'])} after {g['name']}")
            self.background(lambda: systools.open_target(ex["after"]))

    def extras_card(self, g):
        ex = self.extras_of(g["id"])
        nm = lambda p_: os.path.basename(p_) if p_ else "nothing"
        lines = [(f"With the game: {nm(ex.get('with'))}  ·  after it closes: {nm(ex.get('after'))}", "text"),
                 ("Close browsers while playing: " + ("on" if ex.get("browsers") else "off") +
                  "  (Chrome, Edge, Firefox, Opera, Brave, Vivaldi: save your tabs first)", "muted")]
        btns = [("START WITH IT…", lambda: self.pick_extra(g["id"], "with"), "normal"),
                ("START AFTER…", lambda: self.pick_extra(g["id"], "after"), "normal"),
                ("CLOSE BROWSERS: " + ("ON" if ex.get("browsers") else "OFF"),
                 lambda: self.set_extra(g["id"], "browsers", not ex.get("browsers")), "accent" if ex.get("browsers") else "normal")]
        if ex.get("with") or ex.get("after"):
            btns.append(("CLEAR PROGRAMS", lambda: (self.set_extra(g["id"], "with", None), self.set_extra(g["id"], "after", None)), "normal"))
        return {"id": "extras", "title": "WHEN YOU PLAY IT", "lines": lines, "buttons": btns}

    # ---------------------------------------------------------------- battery health over time
    def batt_series(self):
        """One daily health record for the System tab and the Battery health page (older 9.7 entries included)."""
        rows = {d: (full, design, cyc) for d, full, design, cyc in (x[:4] for x in self.cfg["batt_hist"]) if design}
        for x in self.cfg["batt_log"]:
            rows.setdefault(x["d"], (x["full"], x["design"], x.get("cycles")))
        return [{"d": d, "full": v[0], "design": v[1], "cycles": v[2]} for d, v in sorted(rows.items())]

    def log_battery(self, data):
        self.record_battery_health()
        if not data or not data.get("full") or not data.get("design"):
            return
        log = self.batt_series()
        if len(log) >= 2:
            old = [x for x in log if x["d"] <= time.strftime("%Y-%m-%d", time.localtime(time.time() - 30 * 86400))]
            if old and self.cfg["batt_warned"] != log[-1]["d"]:
                drop = (old[-1]["full"] - log[-1]["full"]) * 100 / max(1, log[-1]["design"])
                if drop >= 3:
                    self.cfg["batt_warned"] = log[-1]["d"]
                    self.add_log("AUTO", f"Battery health fell {drop:.0f}% in a month")
                    self.show_toast(f"Battery health fell {drop:.0f}% in a month: see Battery health")

    def open_battery(self):
        if not self.batt_static:
            self.load_battery_static()
        if self.page != "battery":
            self.open_page("battery")

    def cards_battery(self):
        st, b = self.batt_static, self.batt or {}
        if not st:
            if self.batt_static == {} and not b:
                return [{"id": "none", "title": "NO BATTERY", "lines": [("This PC doesn't report a battery.", "muted")], "buttons": []}]
            return [{"id": "ld", "title": "ONE MOMENT", "lines": [("Reading the battery…", "muted")],
                     "buttons": [("CHECK AGAIN", self.load_battery_static, "normal")]}]
        k = self.k
        full, design, cycles = st.get("full"), st.get("design"), st.get("cycles")
        health = full * 100 / design if full and design else None
        lines = []
        if health:
            verdict = "like new" if health >= 95 else "good" if health >= 85 else "worn" if health >= 70 else "very worn"
            lines.append((f"Health {health:.0f}% ({verdict}): holds {full / 1000:.1f} of the {design / 1000:.1f} Wh it was made for",
                          "good" if health >= 85 else "warn"))
        if cycles:
            lines.append((f"{cycles} charge cycles", "text"))
        if st.get("maker"):
            lines.append((f"Made by {st['maker']}", "muted"))
        lines.append(("Stopping the charge at 80% when you play plugged in slows wear (Settings › Power).", "muted"))
        cards = [{"id": "health", "title": "BATTERY HEALTH", "lines": lines,
                  "buttons": [("CHECK AGAIN", self.load_battery_static, "normal")]}]
        log = self.batt_series()
        if len(log) >= 2:
            bh = 120 * k

            def paint(x0, y, x1, log=log):
                T = self.t
                fs = self.font(10 * k)
                vals = [x["full"] * 100 / x["design"] for x in log]
                lo, hi = min(min(vals) - 2, 80), 100
                n = len(vals)
                pts = []
                for i, v in enumerate(vals):
                    px = x0 + (x1 - x0 - 40 * k) * (i / max(1, n - 1))
                    py = y + 8 * k + (bh - 34 * k) * (hi - v) / max(1, hi - lo)
                    pts += [px, py]
                for gv in (hi, (hi + lo) / 2, lo):
                    gy = y + 8 * k + (bh - 34 * k) * (hi - gv) / max(1, hi - lo)
                    self.c.create_line(x0, gy, x1 - 40 * k, gy, fill=mix(T["panel2"], T["text"], 0.1))
                    self.text(x1, gy, f"{gv:.0f}%", fs, T["muted"], anchor="e")
                if len(pts) >= 4:
                    self.c.create_line(*pts, fill=T["accent"], width=max(2, 2.5 * k))
                self.text(x0, y + bh - 18 * k, log[0]["d"], fs, T["muted"], anchor="nw")
                self.text(x1 - 40 * k, y + bh - 18 * k, log[-1]["d"], fs, T["muted"], anchor="ne")
            first, last = log[0], log[-1]
            ch = (last["full"] - first["full"]) * 100 / max(1, last["design"])
            cards.append({"id": "trend", "title": "OVER TIME",
                          "lines": [(f"{'−' if ch < 0 else '+'}{abs(ch):.1f}% since {first['d']}  ·  noted once a day", "muted")],
                          "buttons": [], "extra": bh, "paint": paint})
        else:
            cards.append({"id": "trend", "title": "OVER TIME",
                          "lines": [("Vanta notes the battery's health once a day, so a chart builds up here over the next weeks.",
                                     "muted")], "buttons": []})
        return cards

    # ---------------------------------------------------------------- leftovers and duplicates
    def open_leftovers(self):
        self.leftovers = None
        if self.page != "leftovers":
            self.open_page("leftovers")

        def work():
            try:
                found = systools.find_leftovers()
            except Exception:
                found = []
            self.call(lambda: (setattr(self, "leftovers", found), self.request_draw()))
        self.background(work)

    def remove_leftover(self, item):
        def work():
            ok = systools.recycle(item["path"])

            def fin():
                if ok:
                    self.leftovers = [x for x in (self.leftovers or []) if x["path"] != item["path"]]
                    self.add_log("CLEAN", f"Recycled {item['name']} ({fmt_bytes(item['size'])})")
                    self.show_toast(f"Moved {item['name']} to the Recycle Bin")
                else:
                    self.show_toast("Couldn't remove it (in use, or Preview's safe mode)")
                self.request_draw()
            self.call(fin)
        self.background(work)

    def duplicates(self):
        seen = {}
        for g in self.library or []:
            if str(g["id"]).startswith(("sample:", "rom:", "custom:")):
                continue
            seen.setdefault(systools._norm_title(g["name"]), []).append(g)
        return [v for v in seen.values() if len({g["source"] for g in v}) > 1]

    def cards_leftovers(self):
        lf = getattr(self, "leftovers", None)
        cards = []
        if lf is None:
            cards.append({"id": "ld", "title": "LOOKING…", "lines": [("Checking your Steam libraries for leftovers…", "muted")], "buttons": []})
        elif not lf:
            cards.append({"id": "none", "title": "ALL TIDY", "lines": [("No leftover game folders or orphaned shader caches.", "good")],
                          "buttons": [("CHECK AGAIN", self.open_leftovers, "normal")]})
        else:
            tot = sum(x["size"] for x in lf)
            cards.append({"id": "sum", "title": f"{len(lf)} LEFTOVER{'S' if len(lf) != 1 else ''}  ·  {fmt_bytes(tot)}",
                          "lines": [("Folders no installed Steam game owns (often left by uninstalls) and shader caches of games "
                                     "that are gone. Removing sends them to the Recycle Bin, so you can still get them back.", "muted")],
                          "buttons": [("CHECK AGAIN", self.open_leftovers, "normal")]})
            for i, x in enumerate(lf[:30]):
                armed = self.is_armed(f"lo_{i}")
                cards.append({"id": f"lo{i}", "title": f"{x['name'].upper()}  ·  {fmt_bytes(x['size'])}",
                              "lines": [(x["path"], "muted")],
                              "buttons": [("TAP AGAIN" if armed else "RECYCLE",
                                           lambda x_=x, i_=i: self.confirm(f"lo_{i_}", lambda: self.remove_leftover(x_),
                                                                           f"Tap again to recycle {x_['name']}"), "danger" if armed else "normal"),
                                          ("SHOW", lambda x_=x: systools.show_in_explorer(x_["path"]), "normal")]})
        dups = self.duplicates()
        if dups:
            cards.append({"id": "dups", "title": f"INSTALLED TWICE  ·  {len(dups)}",
                          "lines": [(f"{v[0]['name']}: " + " and ".join(g['source'] for g in v), "text") for v in dups[:12]] +
                                   [("The same game from two stores. Uninstall the one you don't play from its store.", "muted")],
                          "buttons": []})
        return cards

    # ---------------------------------------------------------------- share cards
    def share_image(self, kind):
        T = self.t
        pics = os.path.join(os.path.expanduser("~"), "Pictures", APP_NAME)
        cur, best = self.streaks()
        if kind == "wrap":
            w = self.month_wrap(getattr(self, "wrap_off", 0))
            title = w["label"].split()[0]
            sub = f"{fmt_duration(w['mins'] * 60)} played over {w['days']} days"
            lines = [(f"{i + 1}. {n}"[:34], fmt_duration(sec)) for i, (n, sec) in enumerate(w["top"])]
            if w["longest"]:
                lines.append(("Longest session", fmt_duration(w["longest"]["dur"])))
            if w["smooth"]:
                lines.append((f"Smoothest: {w['smooth'][0]}"[:34], f"{w['smooth'][1]:.0f} FPS"))
            lines.append(("Best streak", f"{best} days"))
            path = os.path.join(pics, f"{APP_NAME} {w['label']}.png")
        else:
            got = [b for b in self.badge_state() if b[3] >= 1]
            title = f"{len(got)} badges"
            sub = f"{cur}-day streak  ·  best {best}"
            lines = [(b[1], "✓") for b in got[-8:]]
            path = os.path.join(pics, f"{APP_NAME} badges {time.strftime('%Y-%m-%d')}.png")

        def work():
            try:
                systools.share_card(path, title, sub, lines, T["accent"], T.get("accent2", T["accent"]), T["bg"], APP_NAME)
                ok = True
            except Exception as ex:
                ok = False
                msg = str(ex)
                self.call(lambda: self.add_log("FAIL", f"Share image: {msg}"))
            self.call(lambda: self.show_toast(f"Saved to Pictures › {APP_NAME}" if ok else "Couldn't make the image"))
            if ok:
                systools.open_target(path)
        self.show_toast("Making the image…")
        self.background(work)

    # ---------------------------------------------------------------- Steam friends
    def open_friends(self):
        self.friends = None
        if self.page != "friends":
            self.open_page("friends")
        key, sid = self.cfg["steam_key"], self.cfg["steam_id"]

        def work():
            sid_ = sid or systools.steam_user_id()
            if not key or not sid_:
                res = "setup"
            else:
                try:
                    res = systools.steam_friends(key, sid_)
                except Exception:
                    res = "offline"
            self.call(lambda: (setattr(self, "friends", res), self.request_draw()))
        self.background(work)

    def cards_friends(self):
        f = getattr(self, "friends", None)
        if f is None:
            return [{"id": "ld", "title": "ONE MOMENT", "lines": [("Asking Steam…", "muted")], "buttons": []}]
        if f == "setup":
            return [{"id": "setup", "title": "CONNECT STEAM",
                     "lines": [("See what your Steam friends are playing. Vanta needs a free Steam Web API key (Settings › "
                                "Stores & deals) and your friends list set to public in Steam's privacy settings.", "text")],
                     "buttons": [("GET A KEY", lambda: systools.open_target("https://steamcommunity.com/dev/apikey"), "accent"),
                                 ("SETTINGS", lambda: self.open_page("settings"), "normal")]}]
        if not isinstance(f, list):
            return [{"id": "off", "title": "COULDN'T REACH STEAM",
                     "lines": [("Check the connection, the key, and that your friends list is public.", "muted")],
                     "buttons": [("TRY AGAIN", self.open_friends, "normal")]}]
        playing = [x for x in f if x["game"]]
        online = [x for x in f if not x["game"] and x["state"] > 0]
        offline = [x for x in f if not x["game"] and x["state"] == 0]
        cards = [{"id": "playing", "title": f"PLAYING NOW  ·  {len(playing)}",
                  "lines": [(f"{x['name']}: {x['game']}", "good") for x in playing[:20]] or [("Nobody's in a game right now.", "muted")],
                  "buttons": [("REFRESH", self.open_friends, "normal")]}]
        if online:
            cards.append({"id": "online", "title": f"ONLINE  ·  {len(online)}",
                          "lines": [(", ".join(x["name"] for x in online[:30]), "text")], "buttons": []})
        cards.append({"id": "offl", "title": f"OFFLINE  ·  {len(offline)}",
                      "lines": [(", ".join(x["name"] for x in offline[:30]) or "None", "muted")], "buttons": []})
        return cards

    # ---------------------------------------------------------------- weather widget
    def weather_tick(self, force=False):
        place = self.cfg["weather_place"]
        if not place or (not force and time.time() - getattr(self, "weather_t", 0) < 1800):
            return
        self.weather_t = time.time()
        fahr = self.cfg["weather_f"]

        def work():
            try:
                w = systools.weather_now(place[1], place[2], fahr)
            except Exception:
                w = None
            if w:
                self.call(lambda: (setattr(self, "weather", w), self.request_draw()))
        self.background(work)

    def weather_label(self):
        w = getattr(self, "weather", None)
        if not self.cfg["weather_place"]:
            return "Set your city"
        if not w or w.get("temp") is None:
            return "Checking…"
        u = "°F" if self.cfg["weather_f"] else "°C"
        return f"{w['temp']:.0f}{u} {w['text']}"

    def type_city(self):
        self._city = ""
        self.page = "weather"

        def typed(kid, label):
            if self._city is None:
                return
            if kid == "bksp":
                self._city = self._city[:-1]
            elif kid == "space":
                self._city += " "
            elif kid == "enter":
                name = self._city.strip()
                self._city = None
                self.close_keyboard()
                if name:
                    self.set_city(name)
            else:
                self._city = (self._city + label)[:40]
            self.request_draw()
        if self.osk:
            self.close_keyboard()
        self.toggle_keyboard(target=typed)
        self.request_draw()

    def set_city(self, name):
        self.show_toast(f"Looking up {name}…")

        def work():
            try:
                pl = systools.find_place(name)
            except Exception:
                pl = "offline"

            def fin():
                if pl == "offline":
                    self.show_toast("Couldn't reach the weather service")
                elif not pl:
                    self.show_toast(f"Couldn't find {name}")
                else:
                    self.cfg["weather_place"] = list(pl)
                    self.weather = None
                    self.weather_tick(True)
                    self.show_toast(f"Weather for {pl[0]}")
                self.request_draw()
            self.call(fin)
        self.background(work)

    def cards_weather(self):
        c = self.cfg
        typing = getattr(self, "_city", None)
        w = getattr(self, "weather", None)
        lines = []
        if typing is not None:
            lines.append((f"City: {typing}▌", "accent"))
            lines.append(("Type your city, then press Enter.", "muted"))
        elif c["weather_place"]:
            lines.append((c["weather_place"][0], "text"))
            if w and w.get("temp") is not None:
                u = "°F" if c["weather_f"] else "°C"
                hi_lo = f"  ·  high {w['hi']:.0f}{u}, low {w['lo']:.0f}{u}" if w.get("hi") is not None and w.get("lo") is not None else ""
                lines.append((f"{w['temp']:.0f}{u}, {w['text'].lower()}{hi_lo}", "good"))
        else:
            lines.append(("Pick a city, then put the Weather tile on Home (Menu › Customize Home).", "muted"))
        lines.append(("From Open-Meteo, free and without an account. Updates every 30 minutes.", "muted"))
        return [{"id": "w", "title": "WEATHER", "lines": lines,
                 "buttons": [("SET CITY", self.type_city, "accent"),
                             ("USE °C" if c["weather_f"] else "USE °F",
                              lambda: (c.__setitem__("weather_f", not c["weather_f"]), self.weather_tick(True), self.request_draw()), "normal"),
                             ("ADD TO HOME", lambda: self.tool_toggle("weather") if "weather" not in c["home_tools"] else
                              self.show_toast("It's already on Home"), "normal")]}]

    # ---------------------------------------------------------------- sleep timer and exporting play history
    SLEEP_OPTS = [0, 15, 30, 45, 60, 90, 120]

    def set_sleep(self, mins):
        self.sleep_warned = False
        self.cfg["sleep_after_game"] = mins == -1
        self.sleep_at = time.time() + mins * 60 if mins and mins > 0 else None
        self.sleep_mins = mins
        if mins == -1:
            self.show_toast("Sleeps a minute after this game closes" if self.game else "Sleeps a minute after your next game closes")
        elif mins:
            self.show_toast(f"Sleeping in {mins} min")
        else:
            self.show_toast("Sleep timer off")
        self.add_log("TOOL", "Sleep timer: " + ("after the game" if mins == -1 else f"{mins} min" if mins else "off"))
        self.request_draw()

    def sleep_left(self):
        at = getattr(self, "sleep_at", None)
        return max(0, at - time.time()) if at else None

    def sleep_tick(self, now):
        at = getattr(self, "sleep_at", None)
        if not at:
            return
        if at - now <= 62 and not getattr(self, "sleep_warned", False):
            self.sleep_warned = True
            self.nudge("Sleeping in 1 minute", "Open Vanta (or the phone app) and turn off the sleep timer to stay awake.")
        if now >= at:
            self.sleep_at = None
            self.sleep_mins = 0
            self.add_log("TOOL", "Sleep timer: going to sleep")
            self.background(systools.sleep_now)

    def sleep_label(self):
        left = self.sleep_left()
        if left is not None:
            return f"in {fmt_duration(max(60, (int(left) // 60 + 1) * 60))}"
        return "after the game" if self.cfg["sleep_after_game"] else "Off"

    def cards_sleeptimer(self):
        cur = getattr(self, "sleep_mins", 0) or (-1 if self.cfg["sleep_after_game"] else 0)
        lab = lambda m: "OFF" if not m else "AFTER THIS GAME" if m == -1 else f"{m} MIN" if m < 60 else (
            f"{m // 60} H" if m % 60 == 0 else f"{m / 60:.1f} H")
        opts = self.SLEEP_OPTS + [-1]
        left = self.sleep_left()
        lines = [("Puts the PC to sleep after a while, with a heads-up a minute before. Handy for falling asleep to a "
                  "stream, or for one last match.", "muted")]
        if left is not None:
            lines.insert(0, (f"Sleeping in {fmt_duration(left)}", "good"))
        elif self.cfg["sleep_after_game"]:
            lines.insert(0, ("Sleeps a minute after the game closes", "good"))
        return [{"id": "sleep", "title": "SLEEP TIMER", "lines": lines,
                 "buttons": [(lab(m) + (" ✓" if m == cur else ""), lambda m_=m: self.set_sleep(m_), "accent" if m == cur else "normal")
                             for m in opts]}]

    def export_history(self):
        folder = os.path.join(os.path.expanduser("~"), "Documents", APP_NAME)
        path = os.path.join(folder, f"{APP_NAME} play history.csv")
        q = lambda v: '"' + str(v).replace('"', '""') + '"' if isinstance(v, str) and any(ch in v for ch in ',"\n') else str(v)
        rows = ["date,start,game,minutes,avg fps,1% low fps,battery used %,avg watts,tdp"]
        for x in self.cfg["sessions"]:
            lt = time.localtime(x["start"])
            rows.append(",".join(q(v) for v in (time.strftime("%Y-%m-%d", lt), time.strftime("%H:%M", lt), x["name"],
                                                 round(x["dur"] / 60, 1), x.get("fps") or "", x.get("low") or "",
                                                 x.get("batt") if x.get("batt") is not None else "", x.get("w") or "", x.get("tdp") or "")))
        try:
            os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:
                f.write("\n".join(rows) + "\n")
        except OSError as ex:
            self.show_toast("Couldn't save the file")
            self.add_log("FAIL", f"Export: {ex}")
            return
        self.show_toast(f"Saved {len(rows) - 1} sessions to Documents › {APP_NAME}")
        self.add_log("TOOL", f"Exported play history: {path}")
        self.background(lambda: systools.open_target(folder))

    # ---------------------------------------------------------------- game colors (accent from the game's art)
    def art_accent(self, path, dark):
        try:
            from PIL import Image
            import colorsys
            im = Image.open(path).convert("RGB")
            im.thumbnail((48, 48))
            bins = {}
            for r, g_, b in im.getdata():
                h, s_, v = colorsys.rgb_to_hsv(r / 255, g_ / 255, b / 255)
                if s_ < 0.3 or v < 0.3:
                    continue
                key = int(h * 24) % 24
                w = s_ * v
                acc = bins.setdefault(key, [0.0, 0.0, 0.0, 0.0])
                acc[0] += w
                acc[1] += r * w
                acc[2] += g_ * w
                acc[3] += b * w
            if not bins:
                return None
            wsum, rs, gs, bs = max(bins.values(), key=lambda a: a[0])
            h, s_, v = colorsys.rgb_to_hsv(rs / wsum / 255, gs / wsum / 255, bs / wsum / 255)
            s_ = max(0.45, min(0.9, s_))
            v = max(0.82, v) if dark else min(0.55, v)
            r, g_, b = colorsys.hsv_to_rgb(h, s_, v)
            return "#%02x%02x%02x" % (int(r * 255), int(g_ * 255), int(b * 255))
        except Exception:
            return None

    def update_game_colors(self, g):
        if not self.cfg["game_colors"]:
            if getattr(self, "game_acc", None):
                self.game_acc = None
                self.game_acc_id = None
            return
        gid = g["id"] if g else None
        if gid == getattr(self, "game_acc_id", "-"):
            return
        self.game_acc_id = gid
        path = (g or {}).get("cover")
        if not path or not os.path.isfile(path):
            if getattr(self, "game_acc", None):
                self.game_acc = None
                self.root.after(1, self.request_draw)
            return
        dark = THEMES[self.theme_name].get("dark", True)

        def work():
            col = self.art_accent(path, dark)

            def fin():
                if self.game_acc_id == gid and col != getattr(self, "game_acc", None):
                    self.game_acc = col
                    self.request_draw()
            self.call(fin)
        self.background(work)

    # ---------------------------------------------------------------- day & night themes
    def daynight_tick(self, now):
        c = self.cfg
        if not c["daynight"]:
            return
        h = time.localtime(now).tm_hour
        per = "day" if c["day_start"] <= h < c["night_start"] else "night"
        if c["dn_period"] != per:
            c["dn_period"] = per
            name = c["day_theme"] if per == "day" else c["night_theme"]
            if name in THEMES and name != self.theme_name:
                self.set_theme(name)
                self.show_toast(f"{'Day' if per == 'day' else 'Night'} theme: {name}")

    def dn_cycle(self, key, d):
        names = [n for n in THEME_NAMES if n != MY_THEME]
        cur = self.cfg[key]
        i = names.index(cur) if cur in names else 0
        self.cfg[key] = names[(i + d) % len(names)]
        self.cfg["dn_period"] = ""
        self.request_draw()

    def dn_hour(self, key, d):
        c = self.cfg
        v = (c[key] + d) % 24
        if (key == "day_start" and v == c["night_start"]) or (key == "night_start" and v == c["day_start"]):
            v = (v + d) % 24
        c[key] = v
        c["dn_period"] = ""
        self.request_draw()

    def set_daynight(self, on):
        self.cfg["daynight"] = on
        self.cfg["dn_period"] = ""
        if on:
            self.daynight_tick(time.time())
        self.request_draw()

    def cards_daynight(self):
        c = self.cfg
        hr = lambda h: time.strftime("%I %p", (2000, 1, 1, h, 0, 0, 0, 1, -1)).lstrip("0")
        cards = [{"id": "dn", "title": "DAY & NIGHT THEMES",
                  "lines": [("One theme for the day and another for the evening, switched for you.", "muted"),
                            (("On" if c["daynight"] else "Off") + f"  ·  day from {hr(c['day_start'])}, night from {hr(c['night_start'])}",
                             "good" if c["daynight"] else "text")],
                  "buttons": [("TURN OFF" if c["daynight"] else "TURN ON", lambda: self.set_daynight(not c["daynight"]),
                               "normal" if c["daynight"] else "accent")]}]
        for key, title, hkey in (("day_theme", "DAY THEME", "day_start"), ("night_theme", "NIGHT THEME", "night_start")):
            cards.append({"id": key, "title": f"{title}  ·  {c[key].upper()}",
                          "lines": [(f"Starts at {hr(c[hkey])}", "muted")],
                          "buttons": [("‹ THEME", lambda k_=key: self.dn_cycle(k_, -1), "normal"),
                                      ("THEME ›", lambda k_=key: self.dn_cycle(k_, 1), "normal"),
                                      ("USE CURRENT", lambda k_=key: (c.__setitem__(k_, self.theme_name), c.__setitem__("dn_period", ""),
                                                                      self.request_draw()), "normal"),
                                      ("− 1 H", lambda h_=hkey: self.dn_hour(h_, -1), "normal"),
                                      ("+ 1 H", lambda h_=hkey: self.dn_hour(h_, 1), "normal")]})
        return cards

    # ---------------------------------------------------------------- for you: one useful suggestion on Home
    def for_you(self):
        now = time.time()
        cache = getattr(self, "_fy", None)
        if cache and now - cache[0] < 30:
            return cache[1]
        out = []
        p, b = self.power, self.batt or {}
        try:
            if p and p.get("battery") and not p.get("ac") and p.get("pct", 100) <= 35 and not self.cfg["batt_goal"]:
                out.append((f"Battery at {p['pct']}%: set a battery goal to last longer", lambda: self.open_page("bgoal")))
            cur, best = self.streaks()
            today = time.strftime("%Y-%m-%d")
            if cur >= 2 and self.day_minutes().get(today, 0) < 1:
                out.append((f"Play today to keep your {cur}-day streak", lambda: self.open_page("badges")))
            if self.recap_new and self.recap:
                out.append((f"See how {self.recap['name']} went", lambda: self.open_page("recap")))
            lt = time.localtime()
            if lt.tm_mday <= 7 and self.month_wrap(1)["mins"] >= 30:
                out.append((f"Your {self.month_wrap(1)['label'].split()[0]} wrap is ready", lambda: self.open_page("calendar")))
            close = [bd for bd in self.badge_state() if 0.85 <= bd[3] < 1]
            if close:
                bd = close[0]
                out.append((f"Almost there: {bd[1]} ({bd[4]})", lambda: self.open_page("badges")))
            lib = self.library or []
            for g in self.news_games()[:6]:
                p_ = self.fresh_patch(g)
                if p_ and self.cfg["news_seen"].get(g["id"]) != p_["date"]:
                    out.insert(0, (f"{g['name']} got an update: {p_['title'][:50]}",
                                   lambda g_=g, p__=p_: (self.cfg["news_seen"].__setitem__(g_["id"], p__["date"]),
                                                         self.open_gameinfo(g_))))
                    break
            if self.cfg["queue"] and not self.game:
                q0 = self.queue_games()[:1]
                if q0:
                    out.append((f"Up next: {q0[0]['name']}", lambda g_=q0[0]: self.pick_home(g_)))
            stale = [g for g in lib if g["id"] in self.cfg["favorites"] and (self.game_stats(g)[0] or 0) and
                     now - self.game_stats(g)[0] > 14 * 86400]
            if stale:
                g = stale[0]
                days = int((now - self.game_stats(g)[0]) / 86400)
                out.append((f"You haven't played {g['name']} in {days} days", lambda g_=g: self.pick_home(g_)))
            fresh = [g for g in lib if not self.game_stats(g)[1] and not str(g["id"]).startswith(("sample:", "rom:"))]
            if fresh:
                g = max(fresh, key=lambda g_: g_.get("size", 0))
                out.append((f"{g['name']} is installed but you haven't played it", lambda g_=g: self.pick_home(g_)))
        except Exception:
            pass
        self._fy = (now, out)
        return out

    def pick_home(self, g):
        self.home_sel = g["id"]
        self.request_draw()

    # ---------------------------------------------------------------- customize Home's one-tap tools
    def home_tool_pool(self):
        ram = f"{int(self.history[-1] * 100)}% RAM in use" if self.history else "Free memory now"
        earned = len(self.cfg["badges_seen"] or [])
        return {
            "boost": ("", "B", "Game Boost", ram, lambda: self.run("boost")),
            "quick": ("", "Q", "Quick settings", "TDP, brightness, refresh", self.later_quick),
            "focus": ("", "F", "Focus mode", "On" if self.focus else "Quiet background apps", self.focus_toggle),
            "find": ("", "/", "Search", "Games, settings, tools", self.open_find),
            "checkup": ("", "+", "Checkup", "Find what's slowing it", self.open_checkup),
            "menu": ("", "≡", "Menu", "Everything else", lambda: self.open_page("menu")),
            "bgoal": ("", "G", "Battery goal", ("Goal " + self.bgoal_label(self.cfg["batt_goal"])) if self.cfg["batt_goal"]
                      else "Last as long as you need", lambda: self.open_page("bgoal")),
            "sleep": ("", "Z", "Sleep timer", self.sleep_label(), lambda: self.open_page("sleeptimer")),
            "playtime": ("", "P", "Reminders", "Breaks and a daily limit", lambda: self.open_page("playtime")),
            "calendar": ("", "D", "Calendar", "Your play days and wraps", lambda: self.open_page("calendar")),
            "badges": ("", "★", "Badges", f"{earned} earned", lambda: self.open_page("badges")),
            "collections": ("", "C", "Collections", "Your shelves", lambda: self.open_page("collections")),
            "surprise": ("", "?", "Surprise me", "A random theme", lambda: self.surprise_theme()),
            "screenshot": ("", "S", "Screenshot", "Game Bar screenshot", systools.save_screenshot),
            "gallery": ("", "G", "Gallery", "Screenshots and clips", lambda: self.open_page("gallery")),
            "weather": ("", "W", "Weather", self.weather_label(), lambda: self.open_page("weather")),
            "music": ("", "♪", "Now playing", (self.np or "Nothing playing")[:40], lambda: self.media("play")),
            "clock": ("", "T", time.strftime("%I:%M %p").lstrip("0"), time.strftime("%A, %B %d"), lambda: self.open_page("calendar")),
            "battery": ("", "B", "Battery health", "Wear and charge cycles", self.open_battery),
            "friends": ("", "F", "Friends", "Who's playing on Steam", self.open_friends),
            "record": ("\ue714", "R", "Stop recording" if getattr(self, "recording", False) else "Record", "Game Bar video", self.toggle_recording),
            "people": ("\ue77b", "P", self.person_name(), "Switch who's playing", lambda: self.open_page("people")),
        }

    def home_tool_cards(self):
        pool = self.home_tool_pool()
        if self.cfg["guest"]:
            return [("home_guest", "", "!", "Guest mode", "Tap to exit", lambda: self.open_page("guest"))]
        ids = [i for i in self.cfg["home_tools"] if i in pool] or ["boost", "quick", "focus", "find", "checkup", "menu"]
        if "menu" not in ids:
            ids = ids[:5] + ["menu"]
        return [("home_" + i,) + pool[i] for i in ids[:6]]

    def tool_toggle(self, tid):
        ids = list(self.cfg["home_tools"])
        if tid in ids:
            if tid == "menu":
                self.show_toast("Menu stays: it's the way to everything else")
                return
            ids.remove(tid)
        elif len(ids) >= 6:
            self.show_toast("Six fit on Home: take one off first")
            return
        else:
            ids.insert(max(0, len(ids) - (1 if "menu" in ids else 0)), tid)
        self.cfg["home_tools"] = ids
        self.request_draw()

    def tool_move(self, tid):
        ids = list(self.cfg["home_tools"])
        if tid in ids:
            i = ids.index(tid)
            if i > 0:
                ids[i - 1], ids[i] = ids[i], ids[i - 1]
                self.cfg["home_tools"] = ids
        self.request_draw()

    def cards_hometools(self):
        pool = self.home_tool_pool()
        ids = list(self.cfg["home_tools"])
        cards = [{"id": "ht", "title": f"ON HOME  ·  {len(ids)} OF 6",
                  "lines": [("Pick the one-tap tools on Home, and their order. ", "muted"),
                            ("  ·  ".join(pool[i][2] for i in ids if i in pool), "text")],
                  "buttons": [("RESET", lambda: (self.cfg.__setitem__("home_tools", ["boost", "quick", "focus", "find", "checkup", "menu"]),
                                                 self.request_draw()), "normal")]}]
        for tid, (gl, fb, title, sub, fn) in pool.items():
            on = tid in ids
            btns = [("REMOVE" if on else "ADD", lambda t_=tid: self.tool_toggle(t_), "normal" if on else "accent")]
            if on and ids.index(tid) > 0:
                btns.append(("‹ MOVE LEFT", lambda t_=tid: self.tool_move(t_), "normal"))
            cards.append({"id": "t_" + tid, "title": title.upper() + ("  ·  ON HOME" if on else ""), "lines": [(sub, "muted")],
                          "buttons": btns})
        return cards

    # ---------------------------------------------------------------- guest mode
    GUEST_PAGES = ("guest", "recap")

    def guest_ids(self):
        sh = self.cfg["guest_shelf"]
        if sh == "fav":
            return set(self.cfg["favorites"])
        if sh.startswith("list:"):
            return set(self.cfg["lists"].get(sh[5:], []))
        return None  # every game

    def guest_allows(self, g):
        ids = self.guest_ids()
        return ids is None or g["id"] in ids

    def shelf_label(self, sh):
        return "Favorites" if sh == "fav" else sh[5:] if sh.startswith("list:") else "All games"

    def start_guest(self):
        ids = self.guest_ids()
        if ids is not None and not ids:
            self.show_toast("That shelf is empty: add games first")
            return
        self.cfg["guest"] = True
        self.close_quick() if self.quick else None
        self.page = None
        self.set_tab("home")
        self.home_sel = None
        self.add_log("TOOL", f"Guest mode on: {self.shelf_label(self.cfg['guest_shelf'])}")
        self.show_toast("Guest mode on")
        self.request_draw()

    def end_guest(self):
        self.cfg["guest"] = False
        self.pin_typed = ""
        self.page = None
        self.add_log("TOOL", "Guest mode off")
        self.show_toast("Guest mode off")
        self.request_draw()

    def pin_key(self, d, mode):
        cur = getattr(self, "pin_typed", "")
        if d == "back":
            self.pin_typed = cur[:-1]
        elif len(cur) < 4:
            self.pin_typed = cur + d
        if len(self.pin_typed) == 4:
            if mode == "set":
                self.cfg["guest_pin"] = self.pin_typed
                self.show_toast("PIN set")
                self.pin_mode = None
            elif self.pin_typed == self.cfg["guest_pin"]:
                self.end_guest()
            else:
                self.show_toast("That's not the PIN")
                self.sound("back") if hasattr(self, "sound") else None
            self.pin_typed = ""
        self.request_draw()

    def keypad_card(self, mode, title):
        typed = getattr(self, "pin_typed", "")
        dots = "  ".join("●" if i < len(typed) else "○" for i in range(4))
        return {"id": "pad_" + mode, "title": title, "lines": [(dots, "accent")],
                "buttons": [(d, lambda d_=d: self.pin_key(d_, mode), "normal") for d in "1234567890"] +
                           [("⌫", lambda: self.pin_key("back", mode), "normal")]}

    def cards_guest(self):
        sh = self.shelf_label(self.cfg["guest_shelf"])
        cards = [{"id": "g", "title": "GUEST MODE IS ON",
                  "lines": [(f"Only games on {sh} can be started. Settings, tools, Quick settings and search are locked.", "text")],
                  "buttons": [] if self.cfg["guest_pin"] else [("EXIT GUEST MODE", self.end_guest, "accent")]}]
        if self.cfg["guest_pin"]:
            cards.append(self.keypad_card("exit", "ENTER THE PIN TO EXIT"))
        return cards

    def cards_guestsetup(self):
        c = self.cfg
        shelves = ["fav"] + ["list:" + n for n in sorted(c["lists"])] + ["all"]
        cards = [{"id": "gs", "title": "GUEST MODE",
                  "lines": [("Hand the device to someone else: they can only start the games you pick, and can't change "
                             "settings, run tools or use Quick settings. It stays on after a restart until the PIN is entered.", "muted")],
                  "buttons": [("START GUEST MODE", self.start_guest, "accent")]},
                 {"id": "gs_shelf", "title": f"GAMES THEY CAN PLAY  ·  {self.shelf_label(c['guest_shelf']).upper()}",
                  "lines": [("Pick a shelf. Make one in Collections (Menu › Collections).", "muted")],
                  "buttons": [(self.shelf_label(s_).upper() + (" ✓" if s_ == c["guest_shelf"] else ""),
                               lambda s__=s_: (c.__setitem__("guest_shelf", s__), self.request_draw()),
                               "accent" if s_ == c["guest_shelf"] else "normal") for s_ in shelves]}]
        if getattr(self, "pin_mode", None) == "set":
            cards.append(self.keypad_card("set", "TYPE A 4-DIGIT PIN"))
        else:
            cards.append({"id": "gs_pin", "title": "PIN  ·  " + ("SET" if c["guest_pin"] else "NONE"),
                          "lines": [("Without a PIN, anyone can leave guest mode from the Menu.", "muted")],
                          "buttons": [("CHANGE PIN" if c["guest_pin"] else "SET A PIN",
                                       lambda: (setattr(self, "pin_mode", "set"), setattr(self, "pin_typed", ""), self.request_draw()), "normal")] +
                                     ([("REMOVE PIN", lambda: (c.__setitem__("guest_pin", ""), self.request_draw()), "normal")]
                                      if c["guest_pin"] else [])})
        return cards

    # ---------------------------------------------------------------- shelves (favorites and your own lists)
    SHELF_IDEAS = ["Backlog", "Up next", "Comfort games", "Quick runs", "Couch co-op", "Finished"]

    def shelf_cards(self):
        lib = self.library or []
        byid = {g["id"]: g for g in lib}
        cards = []
        favs = [byid[i]["name"] for i in self.cfg["favorites"] if i in byid]
        cards.append({"id": "sh_fav", "title": f"★ FAVORITES  ·  {len(favs)}",
                      "lines": [(", ".join(favs[:5]) + ("…" if len(favs) > 5 else ""), "text") if favs else
                                ("Tap ☆ FAVORITE on any game to keep it here, at the top of your library and on Home.", "muted")],
                      "buttons": [(f"SHOW {len(favs)}", lambda: self.show_shelf("fav"), "accent")] if favs else []})
        for name in sorted(self.cfg["lists"]):
            ids = [i for i in self.cfg["lists"][name] if i in byid]
            names = [byid[i]["name"] for i in ids]
            armed = self.is_armed("shdel_" + name)
            cards.append({"id": "sh_" + name, "title": f"{name.upper()}  ·  {len(ids)}",
                          "lines": [(", ".join(names[:5]) + ("…" if len(names) > 5 else ""), "text") if names else
                                    ("Empty for now: open a game and tap + LISTS to add it here.", "muted")],
                          "buttons": ([(f"SHOW {len(ids)}", lambda n=name: self.show_shelf("list:" + n), "accent")] if ids else []) +
                                     [("TAP AGAIN" if armed else "DELETE",
                                       lambda n=name: self.confirm("shdel_" + n, lambda: self.delete_shelf(n), f"Tap again to delete {n}"),
                                       "danger" if armed else "normal")]})
        ideas = [n for n in self.SHELF_IDEAS if n not in self.cfg["lists"]]
        cards.append({"id": "sh_new", "title": "NEW SHELF",
                      "lines": [("Make your own shelf in one tap, then add games from a game's + LISTS button.", "muted")],
                      "buttons": [("+ " + n.upper(), lambda n=n: self.make_shelf(n), "normal") for n in ideas[:4]] +
                                 [("TYPE A NAME", self.type_shelf, "normal")]})
        return cards

    def make_shelf(self, name):
        if name not in self.cfg["lists"]:
            self.cfg["lists"] = dict(self.cfg["lists"], **{name: []})
            self.show_toast(f"Made the shelf {name}")
        self.request_draw()

    def delete_shelf(self, name):
        lists = dict(self.cfg["lists"])
        lists.pop(name, None)
        self.cfg["lists"] = lists
        if self.cfg["lib_filter"] == "list:" + name:
            self.cfg["lib_filter"] = "all"
        if self.cfg["home_row"] == "list:" + name:
            self.cfg["home_row"] = "recent"
        self.request_draw()

    def type_shelf(self):
        self.lists_game = None
        self.page = "lists"
        self.focus_id = None
        self.new_list()
        self.request_draw()

    def show_shelf(self, f):
        self.page = None
        self.set_tab("play")
        self.cfg["lib_filter"] = f
        self.set_off("lib", 0)
        view = self.lib_games()
        if view:
            self.lib_sel = view[0]["id"]
        self.request_draw()

    def home_rows(self):
        rows = [("recent", "JUMP BACK IN")]
        if self.cfg["queue"]:
            rows.append(("queue", "UP NEXT"))
        if self.cfg["favorites"]:
            rows.append(("fav", "FAVORITES"))
        rows += [("list:" + n, n.upper()) for n in sorted(self.cfg["lists"]) if self.cfg["lists"][n]]
        return rows

    def home_row_next(self):
        rows = self.home_rows()
        keys = [r[0] for r in rows]
        cur = self.cfg["home_row"]
        i = keys.index(cur) if cur in keys else 0
        nxt = rows[(i + 1) % len(rows)]
        return nxt if nxt[0] != "recent" else ("recent", "RECENT")

    def set_home_row(self, key):
        self.cfg["home_row"] = key
        self.request_draw()

    def home_row_games(self):
        lib = self.library or []
        if self.cfg["guest"]:
            ids_ = self.guest_ids()
            lib = [g for g in lib if ids_ is None or g["id"] in ids_]
            return "guest", "YOUR GAMES", sorted(lib, key=lambda gg: self.game_stats(gg)[0] or 0, reverse=True)
        recent = sorted(lib, key=lambda gg: self.game_stats(gg)[0] or 0, reverse=True)
        row = self.cfg["home_row"]
        title = dict(self.home_rows()).get(row)
        if not title:
            row, title = "recent", "JUMP BACK IN"
        if row == "queue":
            return row, title, self.queue_games()
        if row == "fav":
            ids = self.cfg["favorites"]
        elif row.startswith("list:"):
            ids = self.cfg["lists"].get(row[5:], [])
        else:
            return row, tr("JUMP BACK IN"), recent
        idset = set(ids)
        return row, title, [g for g in recent if g["id"] in idset]

    # ---------------------------------------------------------------- calendar, monthly wrap, streaks and badges
    def play_days(self):
        """Minutes played per day ("YYYY-MM-DD"), kept beyond the 500 most recent sessions."""
        d = self.cfg["play_days"]
        if d is None:
            d = {}
            for x in self.cfg["sessions"]:
                k_ = time.strftime("%Y-%m-%d", time.localtime(x["start"]))
                d[k_] = round(d.get(k_, 0) + x["dur"] / 60, 1)
            self.cfg["play_days"] = d
        return d

    def day_minutes(self):
        d = dict(self.play_days())
        if self.game:
            today = time.strftime("%Y-%m-%d")
            lt = time.localtime()
            midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
            d[today] = d.get(today, 0) + (time.time() - max(self.game["start"], midnight)) / 60
        return d

    def streaks(self):
        """(current streak, longest streak) in days with at least a minute of play."""
        import datetime as _dt
        days = {k_ for k_, v in self.day_minutes().items() if v >= 1}
        if not days:
            return 0, 0
        t = _dt.date.today()
        if t.isoformat() not in days:
            t -= _dt.timedelta(days=1)
        cur = 0
        while t.isoformat() in days:
            cur += 1
            t -= _dt.timedelta(days=1)
        best = run = 0
        prev = None
        for ds in sorted(days):
            d = _dt.date.fromisoformat(ds)
            run = run + 1 if prev and (d - prev).days == 1 else 1
            best = max(best, run)
            prev = d
        return cur, best

    def badge_stats(self):
        import datetime as _dt
        ss = self.cfg["sessions"]
        dm = self.day_minutes()
        lib = self.library or []
        hours = sum(dm.values()) / 60
        months = {}
        for ds, v in dm.items():
            if v >= 1:
                months[ds[:7]] = months.get(ds[:7], 0) + 1
        weekend = False
        for ds, v in dm.items():
            d = _dt.date.fromisoformat(ds)
            if d.weekday() == 5 and v >= 1 and dm.get((d + _dt.timedelta(days=1)).isoformat(), 0) >= 1:
                weekend = True
                break
        hrs = [time.localtime(x["start"]).tm_hour for x in ss]
        return {"sessions": len(ss), "hours": hours, "longest": self.streaks()[1],
                "marathon": max([x["dur"] for x in ss] or [0]) / 3600,
                "owl": any(0 <= h < 4 for h in hrs), "early": any(5 <= h < 7 for h in hrs),
                "games": len({x["name"].lower() for x in ss} | {g["id"] for g in lib if self.game_stats(g)[1] >= 5}),
                "lib": len([g for g in lib if not str(g["id"]).startswith("sample:")]),
                "devoted": max([self.game_stats(g)[1] for g in lib] or [0]) / 60,
                "fps": max([x.get("fps") or 0 for x in ss] or [0]),
                "sip": any(x.get("w") and x["w"] < 10 and x["dur"] >= 900 for x in ss),
                "weekend": weekend, "month_days": max(months.values() or [0])}

    BADGES = [
        ("first", "First steps", "Play a game with Vanta running", lambda s: (min(1, s["sessions"]), "")),
        ("h10", "Ten hours", "10 hours of play", lambda s: (s["hours"] / 10, f"{s['hours']:.0f}/10 h")),
        ("h50", "Fifty hours", "50 hours of play", lambda s: (s["hours"] / 50, f"{s['hours']:.0f}/50 h")),
        ("h100", "Centurion", "100 hours of play", lambda s: (s["hours"] / 100, f"{s['hours']:.0f}/100 h")),
        ("h500", "Lifer", "500 hours of play", lambda s: (s["hours"] / 500, f"{s['hours']:.0f}/500 h")),
        ("s3", "On a roll", "Play 3 days in a row", lambda s: (s["longest"] / 3, f"best {s['longest']}/3 days")),
        ("s7", "Week warrior", "Play 7 days in a row", lambda s: (s["longest"] / 7, f"best {s['longest']}/7 days")),
        ("s30", "Unstoppable", "Play 30 days in a row", lambda s: (s["longest"] / 30, f"best {s['longest']}/30 days")),
        ("marathon", "Marathon", "One session of 3 hours or more", lambda s: (s["marathon"] / 3, f"longest {s['marathon']:.1f}/3 h")),
        ("owl", "Night owl", "Start a game between midnight and 4 am", lambda s: (float(s["owl"]), "")),
        ("early", "Early bird", "Start a game between 5 and 7 am", lambda s: (float(s["early"]), "")),
        ("explorer", "Explorer", "Play 10 different games", lambda s: (s["games"] / 10, f"{s['games']}/10 games")),
        ("collector", "Collector", "50 games in your library", lambda s: (s["lib"] / 50, f"{s['lib']}/50 games")),
        ("devoted", "Devoted", "100 hours in one game", lambda s: (s["devoted"] / 100, f"{s['devoted']:.0f}/100 h")),
        ("silky", "Silky", "A session averaging 60 FPS or more", lambda s: (s["fps"] / 60, f"best {s['fps']:.0f}/60 FPS")),
        ("sipper", "Power sipper", "15+ minutes averaging under 10 W on battery", lambda s: (float(s["sip"]), "")),
        ("weekend", "Weekender", "Play on a Saturday and the Sunday after", lambda s: (float(s["weekend"]), "")),
        ("regular", "Regular", "Play on 20 days in one month", lambda s: (s["month_days"] / 20, f"best {s['month_days']}/20 days")),
    ]

    def badge_state(self):
        st = self.badge_stats()
        out = []
        for bid, title, desc, fn in self.BADGES:
            try:
                prog, txt = fn(st)
            except Exception:
                prog, txt = 0.0, ""
            out.append((bid, title, desc, max(0.0, min(1.0, prog)), txt))
        return out

    def check_badges(self, announce=True):
        earned = [b[0] for b in self.badge_state() if b[3] >= 1]
        seen = self.cfg["badges_seen"]
        if seen is None or not announce:
            self.cfg["badges_seen"] = sorted(set(earned) | set(seen or []))
            return
        new = [b for b in earned if b not in seen]
        if new:
            self.cfg["badges_seen"] = sorted(set(seen) | set(new))
            titles = {b[0]: b[1] for b in self.BADGES}
            for b in new:
                self.add_log("GAME", f"Badge earned: {titles[b]}")
                self.push_event("Badge earned", titles[b])
            self.show_toast("Badge earned: " + ", ".join(titles[b] for b in new[:3]))

    def cards_badges(self):
        cur, best = self.streaks()
        dm = self.day_minutes()
        month = time.strftime("%Y-%m")
        mdays = sum(1 for d, v in dm.items() if d.startswith(month) and v >= 1)
        bs = self.badge_state()
        got = [b for b in bs if b[3] >= 1]
        todo = sorted([b for b in bs if b[3] < 1], key=lambda b: -b[3])
        k = self.k
        cards = [{"id": "streak", "title": "STREAK",
                  "lines": [(f"{cur} day{'s' if cur != 1 else ''} in a row right now  ·  best ever {best}", "good" if cur >= 2 else "text"),
                            (f"{mdays} day{'s' if mdays != 1 else ''} played this month. "
                             + ("Play today to keep it going." if cur and time.strftime("%Y-%m-%d") not in
                                {d for d, v in dm.items() if v >= 1} else ""), "muted")], "buttons": []}]
        cards.append({"id": "got", "title": f"EARNED  ·  {len(got)} OF {len(bs)}",
                      "lines": [(f"✓  {b[1]}: {b[2][0].lower() + b[2][1:]}", "text") for b in got] or [("None yet: play a game to earn your first.", "muted")],
                      "buttons": [("SHARE IMAGE", lambda: self.share_image("badges"), "normal")] if got else []})
        if todo:
            rows = todo
            rh = 44 * k

            def paint(x0, y, x1, rows=rows):
                T = self.t
                f, fs = self.font(13 * k, True), self.font(11.5 * k)
                for i, (bid, title, desc, prog, txt) in enumerate(rows):
                    yy = y + i * rh
                    self.text(x0, yy + 9 * k, title, f, T["text"], anchor="w")
                    self.text(x1, yy + 9 * k, txt or ("almost" if prog >= 0.5 else ""), fs, T["muted"], anchor="e")
                    self.text(x0 + self.measure(f, title) + 10 * k, yy + 9 * k, desc, fs, T["muted"], anchor="w",
                              maxw=max(10 * k, x1 - x0 - self.measure(f, title) - self.measure(fs, txt) - 30 * k))
                    self.rr(x0, yy + 22 * k, x1, yy + 28 * k, 3 * k, mix(T["panel2"], T["text"], 0.08))
                    if prog > 0.01:
                        self.rr(x0, yy + 22 * k, x0 + max(6 * k, (x1 - x0) * prog), yy + 28 * k, 3 * k, T["accent"])
            cards.append({"id": "todo", "title": "NEXT UP", "lines": [], "buttons": [], "extra": len(rows) * rh, "paint": paint})
        return cards

    def month_wrap(self, off=0):
        lt = time.localtime()
        y_, m_ = lt.tm_year, lt.tm_mon - off
        while m_ < 1:
            m_ += 12
            y_ -= 1
        key = f"{y_:04d}-{m_:02d}"
        pm_y, pm_m = (y_ - 1, 12) if m_ == 1 else (y_, m_ - 1)
        pkey = f"{pm_y:04d}-{pm_m:02d}"
        ss = [x for x in self.cfg["sessions"] if time.strftime("%Y-%m", time.localtime(x["start"])) == key]
        dm = self.day_minutes()
        mins = sum(v for d, v in dm.items() if d.startswith(key))
        pmins = sum(v for d, v in dm.items() if d.startswith(pkey))
        days = sum(1 for d, v in dm.items() if d.startswith(key) and v >= 1)
        per = {}
        for x in ss:
            per[x["name"]] = per.get(x["name"], 0) + x["dur"]
        top = sorted(per.items(), key=lambda kv: -kv[1])[:3]
        longest = max(ss, key=lambda x: x["dur"]) if ss else None
        fpsd = {}
        for x in ss:
            if x.get("fps") and x["dur"] >= 600:
                fpsd.setdefault(x["name"], []).append(x["fps"])
        smooth = max(((n, sum(v) / len(v)) for n, v in fpsd.items()), key=lambda kv: kv[1], default=None)
        wd = {}
        for x in ss:
            w_ = time.localtime(x["start"]).tm_wday
            wd[w_] = wd.get(w_, 0) + x["dur"]
        fav_day = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"][max(wd, key=wd.get)] if wd else None
        sip = [x for x in ss if x.get("w") and x["dur"] >= 900]
        eff = min(sip, key=lambda x: x["w"]) if sip else None
        label = time.strftime("%B %Y", (y_, m_, 1, 0, 0, 0, 0, 1, -1))
        return {"key": key, "label": label, "prev": time.strftime("%B", (pm_y, pm_m, 1, 0, 0, 0, 0, 1, -1)), "mins": mins,
                "pmins": pmins, "days": days, "sessions": len(ss), "top": top, "longest": longest, "smooth": smooth,
                "fav_day": fav_day, "eff": eff}

    def wrap_text(self, w):
        out = [f"{fmt_duration(w['mins'] * 60)} over {w['days']} day{'s' if w['days'] != 1 else ''}  ·  {w['sessions']} sessions"]
        if w["pmins"]:
            d = w["mins"] - w["pmins"]
            out.append(f"{'+' if d >= 0 else '−'}{fmt_duration(abs(d) * 60)} compared with {w['prev']}")
        for i, (n, sec) in enumerate(w["top"]):
            out.append(f"{i + 1}.  {n}: {fmt_duration(sec)}")
        if w["longest"]:
            lg = w["longest"]
            out.append(f"Longest session: {lg['name']}, {fmt_duration(lg['dur'])} on {time.strftime('%b %d', time.localtime(lg['start']))}")
        if w["smooth"]:
            out.append(f"Smoothest: {w['smooth'][0]} at {w['smooth'][1]:.0f} FPS on average")
        if w["eff"]:
            out.append(f"Easiest on battery: {w['eff']['name']} at {w['eff']['w']:.1f} W")
        if w["fav_day"]:
            out.append(f"You played most on {w['fav_day']}")
        done = [v["name"] for v in self.cfg["finished"].values() if time.strftime("%Y-%m", time.localtime(v["t"])) == w["key"]]
        if done:
            out.append("Finished: " + ", ".join(done[:4]) + ("…" if len(done) > 4 else ""))
        return out

    def set_wrap_month(self, d):
        self.wrap_off = max(0, min(24, getattr(self, "wrap_off", 0) + d))
        self.request_draw()

    def copy_wrap(self, w):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(f"My {w['label']} in {APP_NAME}\n" + "\n".join(self.wrap_text(w)))
            self.show_toast("Copied: paste it anywhere")
        except tk.TclError:
            pass

    def wrap_tick(self):
        lt = time.localtime()
        if lt.tm_mday > 7:
            return
        w = self.month_wrap(1)
        if w["mins"] >= 30 and self.cfg["wrap_told"] != w["key"]:
            self.cfg["wrap_told"] = w["key"]
            self.show_toast(f"Your {w['label'].split()[0]} wrap is ready: Menu › Play calendar")
            self.add_log("GAME", f"{w['label']} wrap: {fmt_duration(w['mins'] * 60)} played")

    def cards_calendar(self):
        import datetime as _dt
        k = self.k
        dm = self.day_minutes()
        cell, gap = 18 * k, 4 * k

        def paint(x0, y, x1):
            T = self.t
            fs = self.font(10.5 * k)
            lab_w = 30 * k
            cols = max(4, min(53, int((x1 - x0 - lab_w + gap) // (cell + gap))))
            today = _dt.date.today()
            start = today - _dt.timedelta(days=today.weekday() + 7 * (cols - 1))
            for r, nm in ((0, "Mon"), (2, "Wed"), (4, "Fri"), (6, "Sun")):
                self.text(x0, y + r * (cell + gap) + cell / 2, nm, fs, T["muted"], anchor="w")
            lastm = None
            for ci in range(cols):
                for r in range(7):
                    d = start + _dt.timedelta(days=ci * 7 + r)
                    if d > today:
                        continue
                    v = dm.get(d.isoformat(), 0)
                    lvl = 0 if v < 1 else 0.3 if v < 30 else 0.5 if v < 60 else 0.75 if v < 120 else 1.0
                    col = mix(T["panel2"], T["text"], 0.07) if not lvl else mix(mix(T["panel2"], T["text"], 0.07), T["accent"], lvl)
                    cx = x0 + lab_w + ci * (cell + gap)
                    cy = y + r * (cell + gap)
                    self.rr(cx, cy, cx + cell, cy + cell, 4 * k, col,
                            outline=T["text"] if d == today else "", width=max(1, 1.5 * k) if d == today else 0)
                    if r == 0 and d.month != lastm:
                        lastm = d.month
                        self.text(cx, y + 7 * (cell + gap) + 8 * k, d.strftime("%b"), fs, T["muted"], anchor="w")
            lx = x1
            for lvl, lab in ((1.0, "2h+"), (0.75, "1h"), (0.5, "30m"), (0.3, "<30m"), (0, "none")):
                col = mix(T["panel2"], T["text"], 0.07) if not lvl else mix(mix(T["panel2"], T["text"], 0.07), T["accent"], lvl)
                tw_ = self.measure(fs, lab)
                self.text(lx, y + 7 * (cell + gap) + 32 * k, lab, fs, T["muted"], anchor="e")
                lx -= tw_ + 6 * k
                self.rr(lx - 12 * k, y + 7 * (cell + gap) + 26 * k, lx, y + 7 * (cell + gap) + 38 * k, 3 * k, col)
                lx -= 22 * k
        cur, best = self.streaks()
        days = [v for v in dm.values() if v >= 1]
        cards = [{"id": "heat", "title": "THE DAYS YOU PLAYED",
                  "lines": [(f"{len(days)} days with play  ·  streak {cur} (best {best})  ·  "
                             f"{fmt_duration(sum(dm.values()) * 60)} in all", "muted")],
                  "buttons": [], "extra": 7 * (cell + gap) + 48 * k, "paint": paint}]
        off = getattr(self, "wrap_off", 0)
        w = self.month_wrap(off)
        lines = [(t, "good" if i == 0 else "text") for i, t in enumerate(self.wrap_text(w))] if w["mins"] >= 1 else \
            [("No play recorded this month" + (" yet." if off == 0 else "."), "muted")]
        btns = [("‹ " + self.month_wrap(off + 1)["label"].split()[0].upper(), lambda: self.set_wrap_month(1), "normal")]
        if off:
            btns.append((self.month_wrap(off - 1)["label"].split()[0].upper() + " ›", lambda: self.set_wrap_month(-1), "normal"))
        if w["mins"] >= 1:
            btns.append(("COPY SUMMARY", lambda: self.copy_wrap(w), "normal"))
            btns.append(("SHARE IMAGE", lambda: self.share_image("wrap"), "normal"))
        cards.append({"id": "wrap", "title": f"{w['label'].upper()} WRAP" + ("  ·  SO FAR" if off == 0 else ""), "lines": lines,
                      "buttons": btns})
        return cards

    # ---------------------------------------------------------------- battery goal
    BGOAL_OPTS = [0, 60, 90, 120, 180, 240]

    @staticmethod
    def bgoal_label(m):
        return "Off" if not m else f"{m // 60}h" if m % 60 == 0 else f"{m / 60:.1f}h"

    def set_bgoal(self, mins):
        if mins == self.cfg["batt_goal"]:
            return
        self.bgoal_stop(quiet=True)
        self.cfg["batt_goal"] = mins
        if not mins:
            self.show_toast("Battery goal off")
            self.add_log("TOOL", "Battery goal off")
            self.request_draw()
            return
        if not self.batt:
            self.cfg["batt_goal"] = 0
            self.show_toast("No battery found on this PC")
            return
        tdp0 = (self.tools or {}).get("tdp") or self.cfg["tdp"]
        self.bgoal = {"mins": mins, "end": None, "t": 0.0, "w": None, "w0": tdp0, "hz0": None, "saver": False,
                      "prof0": self.cfg["profile"], "budget": None, "draw": None}
        disp = (self.tools or {}).get("display") or {}
        if disp.get("hz", 0) > 60 and 60 in disp.get("rates", []):
            self.bgoal["hz0"] = disp["hz"]
            self.background(lambda: systools.set_display_mode(hz=60) and self.call(self.load_tools))
        self.add_log("TOOL", f"Battery goal: {self.bgoal_label(mins)}")
        self.show_toast(f"Battery goal {self.bgoal_label(mins)}" +
                        ("" if self.batt.get("discharging") else ": starts when you unplug"))
        self.bgoal_tick(time.time())
        self.request_draw()

    def bgoal_stop(self, quiet=False):
        g, self.bgoal = self.bgoal, None
        if not g:
            return
        w0, hz0 = g.get("w0"), g.get("hz0")

        def work():
            if g.get("w") is not None and w0 and self.device["legion"]:
                systools.set_tdp(w0, self.tdp_max)
            if hz0:
                systools.set_display_mode(hz=hz0)
            self.call(self.load_tools)
        if g.get("w") is not None or hz0:
            self.background(work)
        if g.get("saver") and g.get("prof0") != "saver":
            self.apply_profile(g["prof0"] or "balanced", "AUTO")
        if not quiet:
            self.add_log("TOOL", "Battery goal ended: power settings restored")

    def bgoal_budget(self, now=None):
        """(watts you can spend, hours left) for the running goal, or None."""
        g, b = self.bgoal, self.batt
        if not g or not g.get("end") or not b:
            return None
        left_h = max(0.0, (g["end"] - (now or time.time())) / 3600)
        return (b["remaining_mwh"] / 1000 / left_h if left_h > 0.01 else None), left_h

    def bgoal_tick(self, now):
        g, b = self.bgoal, self.batt
        if not g or not b:
            return
        if not b.get("discharging"):
            g["end"] = None  # plugged in: the clock restarts when you unplug
            return
        if not g["end"]:
            g["end"] = now + g["mins"] * 60
            g["t"] = now  # let the draw settle before the first change
            return
        if now >= g["end"]:
            self.cfg["batt_goal"] = 0
            self.bgoal_stop()
            self.nudge("Battery goal reached", f"You made it to {self.bgoal_label(g['mins'])} on battery.")
            return
        if now - g["t"] < 30:
            return
        g["t"] = now
        budget, left_h = self.bgoal_budget(now)
        hist = [-x for x in list(self.batt_hist)[-20:] if x < 0]
        if budget is None or len(hist) < 5:
            return
        draw = sum(hist) / len(hist)
        g["budget"], g["draw"] = budget, draw
        if self.device["legion"]:
            cur = g["w"] or (self.tools or {}).get("tdp") or self.cfg["tdp"]
            top = min(self.tdp_max, max(5, g["w0"] or self.tdp_max))  # never above what you had set
            if draw > budget * 1.04:
                w = max(5, cur - max(1, min(4, round(draw - budget))))
            elif draw < budget * 0.85:
                w = min(top, cur + 1)
            else:
                return
            if w == cur or self.tdp_busy:
                return
            g["w"] = w

            def work():
                ok = systools.set_tdp(w, self.tdp_max)

                def fin():
                    if ok and self.tools is not None:
                        self.tools["tdp"] = w
                    self.request_draw()
                self.call(fin)
            self.background(work)
        elif draw > budget * 1.05 and not g["saver"] and self.cfg["profile"] != "saver":
            g["saver"] = True
            self.apply_profile("saver", "AUTO")
            self.add_log("AUTO", "Battery goal: switched to Saver to stay on pace")

    def bgoal_status(self):
        g, b = self.bgoal, self.batt
        if not g:
            return ""
        if not b or not b.get("discharging"):
            return f"Starts when you unplug  ·  aims for {self.bgoal_label(g['mins'])}"
        res = self.bgoal_budget()
        if not res or res[0] is None:
            return "Almost there"
        budget, left_h = res
        s = f"{fmt_duration(left_h * 3600)} to go  ·  budget {budget:.1f} W"
        if g.get("draw") is None:
            return s + "  ·  measuring…"
        s += f"  ·  using {g['draw']:.1f} W"
        if g.get("w") is not None:
            s += f"  ·  TDP {g['w']} W"
        return s + ("  ·  on pace" if g["draw"] <= budget * 1.05 else "  ·  catching up")

    def cards_bgoal(self):
        b = self.batt
        if not b:
            return [{"id": "none", "title": "NO BATTERY", "lines": [("This PC doesn't report a battery.", "muted")], "buttons": []}]
        lines = [("Pick how long you want to last. While you're on battery, Vanta compares what you're drawing with what's "
                  "left, and walks the power up or down every 30 seconds to arrive on time.", "text")]
        if self.device["legion"]:
            lines.append(("It changes TDP (never above what you had set) and caps the screen at 60 Hz. "
                          "Auto TDP pauses while a goal is running.", "muted"))
        else:
            lines.append(("It caps the screen at 60 Hz, and switches to Saver if you're drawing more than the goal allows.", "muted"))
        lines.append(("Everything goes back the way it was when you turn it off or reach the goal.", "muted"))
        if self.cfg["batt_goal"]:
            lines.append((self.bgoal_status(), "good"))
        cur = self.cfg["batt_goal"]
        btns = [(self.bgoal_label(m).upper() + (" ✓" if m == cur else ""), lambda m_=m: self.set_bgoal(m_),
                 "accent" if m == cur else "normal") for m in self.BGOAL_OPTS]
        cards = [{"id": "goal", "title": "LAST FOR", "lines": lines, "buttons": btns}]
        if b.get("discharging") and b.get("rate_mw"):
            w = abs(b["rate_mw"]) / 1000
            cards.append({"id": "now", "title": "RIGHT NOW", "lines": [
                (f"Drawing {w:.1f} W  ·  {b['remaining_mwh'] / 1000:.0f} Wh left  ·  about "
                 f"{fmt_duration(b['remaining_mwh'] / abs(b['rate_mw']) * 3600)} at this rate", "text")], "buttons": []})
        return cards

    # ---------------------------------------------------------------- play reminders
    BREAK_OPTS = [0, 30, 45, 60, 90, 120]
    LIMIT_OPTS = [0, 60, 90, 120, 180, 240]

    def played_today(self, now=None):
        now = now or time.time()
        lt = time.localtime(now)
        midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
        total = 0.0
        for x in self.cfg["sessions"]:
            if x["start"] + x["dur"] <= midnight:
                break  # newest first
            total += x["start"] + x["dur"] - max(x["start"], midnight)
        if self.game:
            total += now - max(self.game["start"], midnight)
        return total

    def remind_tick(self, now):
        g, c = self.game, self.cfg
        if getattr(self, "timer_end", None) and now >= self.timer_end:
            self.timer_end = None
            self.nudge("Time's up", f"Your {self.timer_mins}-minute timer is done.")
        if not g:
            return
        if c["break_every"]:
            last = g.setdefault("break_t", g["start"])
            if now - last >= c["break_every"] * 60:
                g["break_t"] = now
                self.nudge("Time for a break", f"{fmt_duration(now - g['start'])} in {g['name']}. "
                                               "Stretch, look away from the screen, have some water.")
        if c["daily_limit"]:
            today = time.strftime("%Y-%m-%d", time.localtime(now))
            played, limit = self.played_today(now), c["daily_limit"] * 60
            if played >= limit and c["limit_day"] != today:
                c["limit_day"] = c["limit_warn"] = today
                self.nudge("Daily play time reached", f"{fmt_duration(played)} today. Your limit is {fmt_duration(limit)}.")
            elif limit - 600 <= played < limit and c["limit_warn"] != today:
                c["limit_warn"] = today
                self.nudge("10 minutes left today", f"{fmt_duration(played)} played of your {fmt_duration(limit)}.")

    def push_event(self, title, body=""):
        """Something worth a ping on the phone app."""
        self.event_n += 1
        self.events.append({"id": self.event_n, "t": time.time(), "title": title, "body": body})

    def nudge(self, title, body):
        """A reminder you'll see over a game: a small on-top card, a Windows note and a buzz."""
        self.push_event(title, body)
        self.add_log("AUTO", f"{title}: {body}")
        self.show_toast(title)
        if self.tray and self.hidden:
            try:
                self.tray.notify(f"{title}. {body}")
            except Exception:
                pass
        if self.cfg["rumble"] and self.pad_on:
            self.pad.rumble(0.5, 180)
            self.root.after(350, lambda: self.pad.rumble(0.5, 180))
        try:
            if self.nudge_win:
                self.nudge_win.destroy()
            self.nudge_win = Nudge(self, title, body)
        except Exception as ex:
            self.nudge_win = None
            self.add_log("FAIL", f"Reminder card: {ex}")

    def theme_day_tick(self, now):
        c = self.cfg
        if not c["theme_daily"] or self.game or c["daynight"]:
            return
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if c["theme_day"] != today:
            c["theme_day"] = today
            self.surprise_theme("Theme of the day")

    def toggle_game_colors(self):
        self.cfg["game_colors"] = not self.cfg["game_colors"]
        self.game_acc = None
        self.game_acc_id = "-"
        self.show_toast("Game colors " + ("on" if self.cfg["game_colors"] else "off"))
        self.request_draw()

    def surprise_theme(self, why="Surprise"):
        cur = self.theme_name
        dark = self.t.get("dark", True)
        pool = [n for n in THEME_NAMES if n != cur and n != MY_THEME and THEMES[n].get("dark", True) == dark] or \
            [n for n in THEME_NAMES if n != cur]
        name = random.choice(pool)
        self.set_theme(name)
        self.show_toast(f"{why}: {name}")
        self.add_log("TOOL", f"{why}: {name}")

    def set_timer(self, mins):
        self.timer_end = time.time() + mins * 60 if mins else None
        self.timer_mins = mins
        self.show_toast(f"Timer: {mins} min" if mins else "Timer off")
        self.request_draw()

    def set_reminder(self, key, val):
        self.cfg[key] = val
        self.request_draw()

    def cards_playtime(self):
        c = self.cfg
        played = self.played_today()
        week = sum(x["dur"] for x in c["sessions"] if x["start"] > time.time() - 7 * 86400)
        lines = [(f"Today: {fmt_duration(played)}" + (f" of {fmt_duration(c['daily_limit'] * 60)}" if c["daily_limit"] else "") +
                  f"  ·  last 7 days: {fmt_duration(week)}", "text")]
        if self.game:
            lines.append((f"Playing {self.game['name']} for {fmt_duration(time.time() - self.game['start'])}", "good"))
        cards = [{"id": "today", "title": "PLAY TIME", "lines": lines, "buttons": []}]
        te = getattr(self, "timer_end", None)
        cards.append({"id": "timer", "title": "TIMER",
                      "lines": [(f"{fmt_duration(te - time.time())} left of {self.timer_mins} min" if te else
                                 "One reminder after a set time: \"just one more run\", then bed.", "good" if te else "muted")],
                      "buttons": ([("CANCEL", lambda: self.set_timer(0), "normal")] if te else []) +
                                 [(f"{m} MIN", lambda m_=m: self.set_timer(m_), "normal") for m in (15, 30, 45, 60, 90)]})
        lbl = lambda m: "OFF" if not m else f"{m} MIN" if m < 60 else (f"{m // 60}H" if m % 60 == 0 else f"{m / 60:.1f}H")
        cards.append({"id": "break", "title": "BREAK REMINDERS",
                      "lines": [("A small card over your game, a Windows note and a buzz, every so often while you play.", "muted")],
                      "buttons": [(lbl(m) + (" ✓" if m == c["break_every"] else ""), lambda m_=m: self.set_reminder("break_every", m_),
                                   "accent" if m == c["break_every"] else "normal") for m in self.BREAK_OPTS]})
        cards.append({"id": "limit", "title": "DAILY LIMIT",
                      "lines": [("A heads-up 10 minutes before, and a reminder when you reach it. Nothing is closed for you.", "muted")],
                      "buttons": [(lbl(m) + (" ✓" if m == c["daily_limit"] else ""), lambda m_=m: self.set_reminder("daily_limit", m_),
                                   "accent" if m == c["daily_limit"] else "normal") for m in self.LIMIT_OPTS]})
        return cards

    # ---------------------------------------------------------------- search everything
    def open_find(self, keyboard=True):
        if self.cfg["guest"]:
            self.show_toast("Search is off in guest mode")
            return
        """One search for games, pages, tools and settings."""
        self.page_from = None
        self.page = "find"
        self.find_q = ""
        self.focus_id = None
        self.set_off("find", 0)
        if keyboard:
            def typed(kid, label):
                if kid == "bksp":
                    self.find_q = self.find_q[:-1]
                elif kid == "space":
                    self.find_q += " "
                elif kid == "enter":
                    self.close_keyboard()
                    res = self.find_results()
                    if res and res[0][1]:
                        res[0][1][0][3]()
                    return
                else:
                    self.find_q += label
                self.set_off("find", 0)
                self.request_draw("page")
            if self.osk:
                self.close_keyboard()
            self.root.after(60, lambda: self.page == "find" and self.toggle_keyboard(target=typed))
        self.request_draw()

    def find_results(self):
        """[(group, [(title, subtitle, glyph, action)])] for the current search."""
        q = self.find_q.strip().lower()
        out = []
        go = lambda fn: (lambda: (self.close_keyboard() if self.osk else None, fn()))

        def pick_game(g):
            self.page = None
            self.set_tab("play")
            self.lib_sel = g["id"]
            self.lib_query = ""
            self.request_draw()
        games = [g for g in (self.library or []) if not q or q in g["name"].lower()]
        if not q:
            games = sorted(games, key=lambda g: self.game_stats(g)[0] or 0, reverse=True)  # recently played first
        if games:
            out.append(("GAMES", [(g["name"], g.get("source", ""), "\ue7fc", go(lambda g=g: pick_game(g))) for g in games[:6]]))
        pages = []
        for tid in TAB_IDS:
            t, b = TAB_TITLES[tid], TAB_BLURBS[tid]
            if not q or q in t.lower() or q in b.lower():
                pages.append((t, b, RAIL_ICONS[tid][0], go(lambda t_=tid: (setattr(self, "page", None), self.set_tab(t_)))))
        for mid, title, glyph, fb, desc, fn in self.menu_items():
            if mid != "find" and q and (q in title.lower() or q in desc.lower()):
                pages.append((title, desc, glyph, go(lambda f=fn: (setattr(self, "page", None), f()))))
        if pages:
            out.append(("PAGES & TOOLS", pages[:8]))
        if q:
            sets = []
            for row in self.settings_items():
                if row[3] != "header" and (q in row[1].lower() or q in row[2].lower()):
                    def open_set(title=row[1]):
                        self.open_page("settings")
                        self.set_query, self.set_drill, self.set_typing = title, True, False
                        self.set_off("settings", 0)
                    sets.append((row[1], row[2] or "Settings", "\ue713", go(open_set)))
            if sets:
                out.append(("SETTINGS", sets[:8]))
        return out

    def draw_find(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        fh = 58 * k
        rid = "find_field"
        self.rr(x0, y0, x1, y0 + fh, fh / 2, mix(T["panel"], T["panel2"], 0.9), outline=T["accent"], width=max(1, 2 * k))
        self.text(x0 + 24 * k, y0 + fh / 2, "⌕", self.font(22 * k), T["accent"], anchor="w")
        q = self.find_q
        f_ = self.font(18 * k)
        self.text(x0 + 56 * k, y0 + fh / 2, q + "▏" if q else "Search games, settings and tools…", f_,
                  T["text"] if q else T["muted"], anchor="w", maxw=x1 - x0 - 120 * k)
        self.region(rid, x0, y0, x1, y0 + fh, tap=lambda: self.open_find(True) if not self.osk else None)
        top = y0 + fh + 18 * k
        res = self.find_results()
        if not res:
            self.text((x0 + x1) / 2, top + 50 * k, f"Nothing called “{q}”", self.font(16 * k), T["muted"], anchor="center")
            return
        rh, hh = 62 * k, 34 * k
        total = sum(hh + rh * len(items) for _, items in res)
        off = self.scroll_area("find", x0, top, x1, y1, total + 10 * k)
        self.clip_to(top, y1)
        y = top - off
        tf, sf, gf = self.font(16 * k, True), self.font(12.5 * k), self.font(11.5 * k, True)
        for group, items in res:
            self.text(x0 + 4 * k, y + hh / 2 + 4 * k, group, gf, T["muted"], anchor="w")
            y += hh
            for i, (title, sub, glyph, fn) in enumerate(items):
                if y + rh >= top and y <= y1:
                    rid = f"find_{group[:3]}_{i}"
                    self.rr(x0, y + 3 * k, x1 - 14 * k, y + rh - 3 * k, 14 * k, T["panel2"])
                    ic = 40 * k
                    self.rr(x0 + 12 * k, y + (rh - ic) / 2, x0 + 12 * k + ic, y + (rh + ic) / 2, 10 * k,
                            mix(T["panel2"], T["accent"], 0.18))
                    if self.icon_family:
                        self.c.create_text(x0 + 12 * k + ic / 2, y + rh / 2, text=glyph, font=self.font(17 * k, icon=True),
                                           fill=T["accent"])
                    else:
                        self.c.create_text(x0 + 12 * k + ic / 2, y + rh / 2, text=title[:1], font=self.font(16 * k, True),
                                           fill=T["accent"])
                    self.text(x0 + 66 * k, y + rh / 2 - 9 * k, title, tf, T["text"], anchor="w", maxw=x1 - x0 - 100 * k)
                    self.text(x0 + 66 * k, y + rh / 2 + 12 * k, sub, sf, T["muted"], anchor="w", maxw=x1 - x0 - 100 * k)
                    self.region(rid, x0, y, x1 - 14 * k, y + rh, tap=fn, sid="find")
                y += rh
        self.end_clip()
        self.scrollbar("find", x1, top, y1 - top)

    WHATS_NEW = [
        ("9.9.2 · No more ghost highlight", "The game you've picked now gets a small bar under it instead of a ring, so it can't "
                                            "be mistaken for the controller's cursor. The mouse hover is now a faint grey outline, and "
                                            "it no longer sticks to the last thing you touched or appears while you use the controller."),
        ("9.9.1 · A normal controller", "The Legion controllers now work like any Xbox controller: Vanta no longer reads their "
                                        "own report, so it doesn't remap the Legion buttons, back buttons or View+Menu, and moving a "
                                        "stick can't move windows or open Vanta. Lenovo's own button service is put back. You can "
                                        "still turn the Legion button features on in Settings › Controller & lights."),
        ("9.9.1 · No more drifting selection", "The left stick only moves the selection once it's been seen resting in the "
                                               "middle, needs a firmer push (60%), and isn't read from the Legion report when the "
                                               "Xbox pad is there. Any direction held for 8 seconds without a break is ignored until "
                                               "it's released. Settings › Left stick moves around turns stick navigation off."),
        ("9.9 · Steam reviews & genres", "Each game shows its Steam review score, and genres come from Steam's store: filter the "
                                         "library by genre, find genre shelves in Collections, and pick a mood in What should I play?."),
        ("9.9 · Reinstall a game", "Games you uninstall are remembered, with a one-tap reinstall (Steam, Epic and GOG open the "
                                   "install screen). Menu › Reinstall a game."),
        ("9.9 · Guides", "Steam guides, PCGamingWiki and a web search for any game, on its Notes & stats page."),
        ("9.9 · Launch options", "Extra options like -dx11 or -windowed for Steam games and games Vanta starts directly."),
        ("9.9 · Record button", "Start or stop a Game Bar recording from Quick settings, Home, the Menu or the phone app."),
        ("9.9 · Sort captures by game", "Copies your screenshots and clips into a folder per game in Pictures › Vanta › Captures, "
                                        "on request or after every game. The originals stay where they are."),
        ("9.9 · Time-of-day rules", "Automations can now run at a time: every day, weekdays or weekends."),
        ("9.9 · Who's playing", "Profiles for each person who uses the device: their own stats, streaks, notes, Up next, shelves, "
                                "Home tiles and theme. Switch from Home or Menu › Who's playing."),
        ("9.9 · Per-game volume", "Set a game's own volume, and turn other apps down or mute them while you play (put back after)."),
        ("9.9 · One battery history", "The System tab and the Battery health page now share one daily record."),
        ("9.8.1 · Controller and animated themes fixed", "Vanta decided whether you were using it by comparing the window in "
                                                        "front with a handle it saved at start-up. Going full screen (console mode does "
                                                        "this at sign-in) gives the window a new handle, so Vanta thought it was in the "
                                                        "background: it ignored the controller and froze animated themes. It now checks "
                                                        "which app is in front, comes to the front by itself at start-up, and logs it "
                                                        "if it ever ignores the controller."),
        ("9.8 · Game news & patches", "Patch notes and news for the Steam games you play, on each game's page and in Menu › Game news. "
                                      "Home tells you when a game you play just got an update."),
        ("9.8 · Controller tester", "Every button, stick and trigger live, a stick drift check and a vibration test. It only reads "
                                    "the controller. Menu › Controller tester."),
        ("9.8 · Dock mode", "Plug into a TV and Vanta gets bigger for the couch, can show the picture on the TV only and switch "
                            "profile; unplug and it goes back. Menu › Dock mode."),
        ("9.8 · Close store apps", "Epic, EA, Ubisoft, Battle.net, GOG and Amazon apps can close a minute after their game does."),
        ("9.8 · Wake your gaming PC", "A WAKE button on the Stream page turns on a sleeping PC (Wake-on-LAN must be on in its settings)."),
        ("9.8 · Up next & finished games", "An ordered list of what to play next (on Home too), and finished games with a date and "
                                           "1–5 stars. Your monthly wrap lists what you finished."),
        ("9.8 · You and your friends", "Compare your hours in a Steam game with your friends' (Notes & stats › Compare)."),
        ("9.8 · Keyboard shortcuts", "Ctrl+1–4 sections, Ctrl+, settings, Ctrl+M menu, Ctrl+Q quick settings, Ctrl+N notes, Ctrl+U up "
                                     "next, Ctrl+P play, F1 help. Menu › Keyboard shortcuts."),
        ("9.8 · Startup speed", "How long Windows took to start, the average of recent startups, and the apps that slowed it."),
        ("9.7 · Smoother animated themes", "Frames are now paced evenly (about twice the frame rate on slow PCs), every shape moves "
                                          "every frame, and hovering or pressing the D-pad no longer pauses the background."),
        ("9.7 · Covers for every store", "Epic covers come from the Epic launcher's own catalog, GOG's from GOG's store, and Xbox, EA, "
                                         "Ubisoft, Battle.net and Amazon games fall back to PCGamingWiki. The Preview build now "
                                         "downloads art too."),
        ("9.7 · Amazon Games", "Games installed with the Amazon Games app now show up in your library."),
        ("9.7 · When you play it", "Per game: start another program with it (a mod manager, a tracker) or after it closes, and "
                                   "close your browsers while you play. NOTES & STATS on any game."),
        ("9.7 · Battery health", "Wear, charge cycles and a chart of the battery's health over time, with a heads-up if it "
                                 "drops fast. The low-battery alert now shows the time left, over your game."),
        ("9.7 · Leftovers & duplicates", "Finds Steam folders and shader caches that uninstalled games left behind (to the Recycle "
                                         "Bin in one tap) and games installed from two stores."),
        ("9.7 · Share images", "Turn your monthly wrap or your badges into a picture to post (Pictures › Vanta)."),
        ("9.7 · Steam friends", "Who's online and what they're playing (needs your Steam Web API key)."),
        ("9.7 · Home widgets", "Weather, Now playing, Clock, Battery health and Friends tiles for Home (Menu › Customize Home)."),
        ("9.7 · High contrast", "Two high-contrast themes, dark and light, with bold outlines and bright accents."),
        ("9.7 · Phone app: touchpad, keyboard & alerts", "A Pad tab turns your phone into a touchpad and keyboard for the PC, and "
                                                        "the app now shows Vanta's alerts (reminders, battery, badges) as they happen."),
        ("9.6 · Guest mode", "Lend your device: only the games on a shelf you pick can be started, and settings, tools, search and "
                             "Quick settings are locked behind a 4-digit PIN. Menu › Guest mode."),
        ("9.5 · Customize Home", "Pick the six one-tap tools on Home and their order: Battery goal, Sleep timer, Calendar, Badges, "
                                 "Screenshot, Gallery and more. Menu › Customize Home."),
        ("9.4 · For you", "Home suggests one useful thing at a time: a favorite you haven't played in a while, a streak to keep, "
                          "a badge you're close to, a battery goal when you're low. Tap it to go there."),
        ("9.4 · Phone app: screenshots & sleep", "A Shots tab with your latest screenshots, and the sleep timer in Control."),
        ("9.3 · Day & night themes", "One theme for the day and another for the evening, switched at the hours you choose. "
                                     "Menu › Day & night themes."),
        ("9.2 · Game colors", "Turn it on and Vanta's accent color follows the art of the game you've picked. "
                              "Menu › Game colors, or Settings › Look & feel."),
        ("9.1 · Sleep timer", "Sleep after 15 minutes to 2 hours, or a minute after the game closes, with a heads-up first."),
        ("9.1 · Export play history", "Every session (date, game, minutes, FPS, battery, watts, TDP) saved as a CSV in Documents."),
        ("9.0 · Game stats", "Each game gets its own page: total time, average and best FPS, battery per hour, the TDP that "
                             "gave the most FPS per watt, recent sessions as a chart, and screenshots taken while playing."),
        ("8.9 · Game notes", "Leave a note on any game (where you left off, a boss to beat). It shows on Home and pops up over the "
                             "game when you start it. NOTES & STATS on a game, or ADD A NOTE on the recap."),
        ("Your shelves", "Collections now starts with your Favorites and your own shelves. Make one in a tap (Backlog, Up next, "
                         "Comfort games…) or type a name, and add games with + LISTS. On Home, the row next to Jump back in "
                         "switches between Recent, Favorites and your shelves."),
        ("Play calendar & monthly wrap", "Menu › Play calendar: a heatmap of the days you played, and a wrap of each month: hours, "
                                         "top games, longest session, smoothest game, easiest on battery. Copy it to share."),
        ("Streaks & badges", "Play streaks on Home and 18 badges to earn, from Night owl to Centurion. Menu › Streaks & badges "
                             "shows what's next and how close you are."),
        ("Smoother animated themes", "Animated backgrounds now move in real time and cost far less to draw: gradients are one image "
                                     "that slides, big shapes take turns, and slow frames never turn into slow motion. "
                                     "Settings › Look & feel shows the frame rate."),
        ("26 new themes", "Sakura, Fireflies, Confetti, Tide, Lagoon, Nebula, Lava Lamp, Northern Lights, Galaxy, Prism, Vaporwave "
                          "and more: 63 in all, with five new animated backgrounds (petals, fireflies, confetti, waves, glowing orbs)."),
        ("Theme of the day & Surprise me", "Turn on Theme of the day for a new look each morning, or tap Menu › Surprise me."),
        ("New phone app", "The phone remote is rebuilt as an app: live FPS/CPU/GPU/battery rings, a TDP slider, battery goal, "
                          "brightness and refresh, your games with covers (tap to play), play reminders, and it remembers the PIN. "
                          "Add it to your home screen to open it like any app."),
        ("Session timer", "Menu › Play reminders › Timer: one reminder after 15–90 minutes."),
        ("Battery goal", "Pick how long to last (1–4 hours). On battery, Vanta paces TDP and caps the screen at 60 Hz to get "
                         "you there, then puts everything back. In Quick settings and the Menu."),
        ("Play reminders", "Break reminders over your game every 30–120 minutes, and an optional daily play time limit "
                           "with a heads-up 10 minutes before. Menu › Play reminders."),
        ("Game recap", "When a game closes you get a recap: time, FPS, battery and power, compared with last time, plus tips."),
        ("Smart collections", "Library shelves that fill themselves: Unplayed, Short sessions, Easy on battery, "
                              "Haven't played lately, Presets ready and Big installs."),
        ("Console home", "A new Home: your last game front and centre (A plays it), recent games and one-tap tools. "
                         "Four sections up top: Home, Library, Tune, Insights. LB/RB switch sections, LT/RT the pages inside. "
                         "The side rail and classic tabs are still in Settings › Look & feel › Layout."),
        ("Search everything", "Find games, settings, tools and pages from one box (top bar, Y on Home, or Ctrl+K)."),
        ("Tidier menu and controller hints", "The menu is grouped into sections, and a hint strip shows what each "
                                            "controller button does on the screen you're on."),
        ("Dark Souls III preset", "A Legion Go preset for Dark Souls III: 30 W and 60 Hz (the game is capped at 60 FPS), "
                                  "with the tested in-game settings."),
        ("Controller fixes", "Quick settings no longer keeps the controller after you go back to the main window, and Vanta "
                             "reads your real controller even when another Xbox pad (virtual or idle) is present."),
        ("Instant response", "Buttons light up the moment you touch them, the controller's focus glides without redrawing "
                             "the screen, and taps inside Settings and other pages only redraw that page."),
        ("Controllers in any mode", "If the controllers end up in DirectInput mode, Vanta Go still reads them for "
                                    "navigation, and Settings › Controller & lights › Restore Xbox controller mode puts them back."),
        ("Animated themes, lighter", "Moving backgrounds pace themselves to your PC, pause while you're tapping or scrolling, "
                                     "and Flow visibly flows."),
        ("Motion controls removed", "The Wii pointer and gyro mouse are gone. Vanta Go no longer sends any command to "
                                    "controllers on the 2025 firmware: it only reads them."),
        ("Legion buttons on 2025 firmware", "Controllers updated in 2025 send their buttons, back buttons, gyro and battery "
                                            "in a new report. Vanta Go now reads it, so Legion L and R work again."),
        ("Legion button test", "Settings › Controller & lights › Legion button test finds where your controllers report "
                               "Legion L and R. Once Vanta has seen a real press, it stops Lenovo's button services so the "
                               "buttons open Vanta instead of Legion Space."),
        ("Smoother motion", "Tab switches, pages, the rail highlight, the focus ring and toasts now glide without redrawing "
                            "the screen, scrolling the library only redraws the games, and hover is instant."),
        ("Vanta and Vanta Go", "Vanta now runs on any Windows PC or handheld. Vanta Go is the Legion Go edition, with the "
                               "Legion buttons, TDP, fans, charge limit, lights and Gen 1 / Gen 2 presets."),
        ("Side rail layout", "Everything is on a rail down the left, grouped into Performance and Insights, with big page "
                             "titles, battery and clock up top, and more room for your games. Prefer the old tabs? "
                             "Settings → Look & feel → Layout."),
        ("A new look", "The Vanta theme: blurred game art behind the library, rounded covers with soft shadows, "
                       "a cinematic game page and a glowing Play button. Your old theme is one tap away in Themes."),
        ("Feels alive", "Buttons, rows and tiles light up under the mouse or trackpad, and the library shows "
                        "placeholder tiles while it finds your games."),
        ("Automations", "When something happens (a game starts, the charger comes out, battery gets low), Vanta does something."),
        ("Clips & screenshots", "Save the last 30 seconds or a screenshot from a back button, and browse them in the menu."),
        ("Desktop controls", "Use the controller as a mouse and keyboard on the desktop, with full-speed fans one tap away."),
        ("Network check", "Ping, jitter and Wi-Fi band, and pause OneDrive while you play online."),
        ("Backups", "Save and restore all your Vanta settings, and share themes as a code."),
    ]

    def draw_logo(self, cx, cy, size):
        """The Vanta mark: a rounded gradient square with a V."""
        T, k = self.t, self.k
        r = size / 2
        steps = 10
        for i in range(steps):
            f = i / (steps - 1)
            y0_ = cy - r + size * i / steps
            col = mix(T["accent"], T.get("accent2", T["accent"]), f)
            self.c.create_rectangle(cx - r, y0_, cx + r, min(cy + r, y0_ + size / steps + 1), fill=col, outline="")
        # round the corners by painting the panel colour over them
        cr = size * 0.24
        bg = T["panel"]
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            ox, oy = cx + sx * (r - cr), cy + sy * (r - cr)
            pts = []
            for a in range(0, 91, 10):
                ang = math.radians(a)
                pts += [ox + sx * cr * math.cos(ang), oy + sy * cr * math.sin(ang)]
            pts += [cx + sx * r, cy + sy * r]
            self.c.create_polygon(pts, fill=bg, outline="")
        self.text(cx, cy + size * 0.03, "V", self.font(size * 0.56, True, display=True), "#ffffff", anchor="center")

    def draw_about(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        lw = 96 * k
        self.draw_logo(x0 + lw / 2, y0 + lw / 2 + 4 * k, lw)
        tx = x0 + lw + 24 * k
        self.text(tx, y0 + 30 * k, APP_NAME, self.font(34 * k, True, display=True), T["text"], anchor="w")
        self.text(tx, y0 + 66 * k, f"Version {VERSION}" + ("  ·  Preview" if PREVIEW else ""),
                  self.font(15 * k), T["muted"], anchor="w")
        self.text(tx, y0 + 92 * k, "Your Legion Go, tuned." if IS_GO else "Your games, your PC, tuned.", self.font(15 * k), T["accent"], anchor="w")
        top = y0 + lw + 34 * k
        self.text(x0, top, tr("What's new").upper(), self.font(12 * k, True), T["muted"], anchor="w")
        top += 18 * k
        f_h, f_b = self.font(16 * k, True), self.font(14 * k)
        bw = x1 - x0 - 44 * k
        rows = [(h, self.wrap(b, f_b, bw)) for h, b in self.WHATS_NEW]
        heights = [44 * k + 21 * k * len(ls) for _, ls in rows]
        off = self.scroll_area("about", x0, top, x1, y1, sum(heights) + 10 * k)
        y = top - off
        for (h, ls), hh in zip(rows, heights):
            if y + hh > top - 10 * k and y < y1:
                self.rr(x0, y + 6 * k, x1 - 14 * k, y + hh - 4 * k, 14 * k, T["panel2"])
                self.c.create_oval(x0 + 16 * k, y + 22 * k, x0 + 24 * k, y + 30 * k, fill=T["accent"], outline="")
                self.text(x0 + 36 * k, y + 26 * k, h, f_h, T["text"], anchor="w")
                for i, ln in enumerate(ls):
                    self.text(x0 + 36 * k, y + 50 * k + i * 21 * k, ln, f_b, T["muted"], anchor="w")
            y += hh
        self.scrollbar("about", x1, top, y1 - top)

    def draw_help(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        mem = fmt_bytes(self.installed) if self.installed else "its"
        lines = [
            ("h", "Controller"),
            ("A / B", "Select / back"), ("X / Y", "Game Boost / Optimize all"),
            ("D-pad", "Move around (left/right also change settings and switches)"),
            ("LB / RB", "Switch tabs"), ("LT / RT", "Page the app list"),
            ("Menu / View", "The menu (themes, checkup, help…) / Settings"), ("L3 / R3", "Auto on/off / next theme"),
            ("In Settings", "LB / RB change category, Y searches, LT / RT scroll a page"),
            ("View + Menu", "Press together to show or hide the mini monitor, even in a game"),
            ("Legion L", "Open the hub, or go back to your game (hold: Task view). Change it in Settings"),
            ("Legion R", "Quick settings over your game (hold: on-screen keyboard). B or Legion R closes it"),
            ("h", "Touch"),
            ("Tap", "Buttons, apps, switches. Tap outside a panel to close it."),
            ("Drag", "Flick any list to scroll; it glides and stretches a little at the ends."),
            ("h", "Legion Go tips"),
            ("Graphics", f"Your device shares {mem} of RAM with the graphics chip. The reserved share is set by the "
                         "UMA frame buffer size in the BIOS; more for graphics means less for Windows and games."),
            ("Legion Space", "Vanta does Legion Space's everyday jobs: the Legion buttons, power and thermal modes, TDP, "
                             "refresh rate, charge limit and controller lights. The STARTUP tab shows how much RAM Legion Space "
                             "uses, closes it and stops it starting. Keep it installed for firmware updates and button remapping."),
            ("Discord", "Settings → Discord. Rich Presence shows your game, play time and FPS on your profile (needs a free "
                        "Application ID). A channel webhook lets Vanta post game recaps and share your last screenshot. "
                        "Mute and deafen buttons are in quick settings."),
            ("Checkup", "The + button at the top scores your setup and fixes the safe things in one tap."),
            ("Auto TDP", "Quick settings → Auto TDP holds an FPS target (30–90) with the lowest wattage, using the FPS counter."),
            ("Back buttons", "Settings → Back buttons maps Y1, Y2, Y3, M2 and M3 to keys or actions, for all games or just one. "
                             "Keys stay held while you hold the button."),
            ("Suspend", "Quick settings → Suspend game freezes it where it is. Resume from the top of PLAY."),
            ("Stores", "The library finds Steam, Epic, GOG, Xbox / Game Pass, EA, Ubisoft and Battle.net games, plus ROMs through "
                       "RetroArch (Settings → Add a ROM folder)."),
            ("Saves", "BACK UP SAVES on a game uses Ludusavi (free) and keeps copies in Documents\\Vanta save backups."),
            ("microSD", "MOVE TO on a Steam game moves it to your other Steam library (close Steam first). The copy is checked "
                        "before the original is removed."),
            ("Best TDP", "During a game: Quick settings → FIND MY BEST TDP tests a few power levels for about 3 minutes "
                         "and recommends the one with the best FPS per watt."),
            ("Quiet", "Settings → Quiet while gaming turns off notifications and pauses Windows Update downloads during games."),
            ("Phone remote", "Settings → Phone remote: open the address it shows on your phone (same Wi-Fi) and type the PIN."),
            ("Keyboard", "Hold Legion R (or pick it for a back button) for a keyboard you can use with the controller: "
                         "A types, X deletes, Y space, LB shift, Start enter, B closes."),
            ("Game Boost", "Trims background apps (not the game in front, Steam, overlays or Legion Space), "
                           "writes out changed pages and drops low-priority cache."),
            ("More FPS", "Game Tools: Performance thermal mode + Best performance power mode while plugged in, "
                         "background recording off, Memory integrity off (Microsoft's own gaming advice; less secure)."),
            ("Portrait", "Detach the controllers and turn the device: the layout switches to portrait."),
            ("Game settings", "In the Play tab, ⚙ opens a game's own TDP, resolution, refresh rate and AMD settings (RSR, Fluid Motion "
                              "Frames, Anti-Lag, Chill, sharpening, frame cap, integer scaling). Games with a PRESET badge have tested Legion Go "
                              "settings from the web, with the source linked."),
            ("Hub", "PLAY tab: tap a game to pick it, tap again (or X) to play. FOCUS MODE (Y) minimizes windows, puts "
                    "background apps in efficiency mode and frees RAM. Hold View + Menu in a game to come back here."),
            ("Gaming", "Settings > Performance modes while gaming switches to Best performance (and Legion Performance) "
                       "when a full-screen game starts, and puts your modes back when it closes."),
            ("Mini monitor", "Shows RAM, CPU, battery watts and time left on top of windowed and borderless games."),
            ("Profiles", "Game Tools > Profiles sets power mode, Legion thermal mode and refresh rate in one tap. "
                         "Settings can switch profiles for you when you plug in or unplug."),
            ("Display", "60 Hz uses noticeably less battery than 144 Hz. A lower desktop resolution helps borderless games."),
            ("Custom TDP", "Tools > Performance mode. Sets the sustained power limit (with a little boost headroom) through "
                           "Lenovo's firmware. Experimental: tap Quiet/Balanced/Performance to go back."),
            ("Games tab", "Give each game its own profile, close chosen apps when a game starts, and turn on the FPS counter."),
            ("About", f"Vanta {VERSION}, formerly RAM//OPT Go. Your settings, profiles and stats carried over."),
            ("Report", "SAVE A REPORT (top of this page) writes a text file to your Desktop for troubleshooting."),
            ("h", "Keyboard"),
            ("Keys", "Tab switch tabs · B boost · O all · 1-6 actions · T/A trim · U auto · S settings · C theme · L log · F11"),
        ]
        if not self.device["legion"]:
            skip = {"Legion L", "Legion R", "Legion Space", "Back buttons", "Auto TDP", "Best TDP", "Custom TDP", "Graphics",
                    "Wii pointer"}
            lines = [(a, "Tips" if (a, b) == ("h", "Legion Go tips") else
                      b.replace(" (and Legion Performance)", "").replace(", Legion thermal mode", ""))
                     for a, b in lines if a not in skip]
            lines = [(a, b if a != "About" else f"{APP_NAME} {VERSION}.") for a, b in lines]
        elif IS_GO:
            lines = [(a, b if a != "About" else f"{APP_NAME} {VERSION} (Vanta's Legion Go edition), formerly RAM//OPT Go. "
                                                  "Your settings, profiles and stats carried over.") for a, b in lines]
        hf, kf, tf = self.font(15 * k, True), self.font(14 * k, True), self.font(14 * k)
        y = y0
        col = 150 * k
        for key, text in lines:
            if key == "h":
                y += 6 * k
                if y + hf.metrics("linespace") > y1:
                    break
                self.text(x0, y, text.upper(), hf, T["accent"])
                y += hf.metrics("linespace") + 4 * k
                continue
            out = self.wrap(text, tf, x1 - x0 - col)
            if y + tf.metrics("linespace") * len(out) > y1:
                break
            self.text(x0, y, key, kf, T["text"])
            for ln in out:
                self.text(x0 + col, y, ln, tf, T["muted"])
                y += tf.metrics("linespace")
            y += 3 * k

    def draw_log(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        f = self.font(14 * k)
        mf = self.font(13 * k, mono=True)
        lh = f.metrics("linespace") + 6 * k
        n = max(1, int((y1 - y0) // lh))
        tags = {"FAIL": T["danger"], "DENY": T["warn"], "AUTO": T["accent2"], "GAME": T["accent2"], "TRIM": T["good"],
                "USER": T["accent"], "CLEAN": T["good"], "TOOL": T["accent"]}
        for i, (ts, tag, msg) in enumerate(list(self.log)[-n:]):
            y = y0 + i * lh
            self.text(x0, y, ts, mf, T["muted"])
            tx = x0 + mf.measure("00:00:00  ")
            self.text(tx, y, tag, mf, tags.get(tag, T["muted"]))
            self.text(tx + mf.measure("CLEAN  "), y, msg, f, T["text"], maxw=x1 - tx - mf.measure("CLEAN  "))


# =====================================================================  entry

def main():
    args = sys.argv[1:]
    if "--run" in args:
        i = args.index("--run")
        action = args[i + 1] if i + 1 < len(args) else "standbylow"
        if is_admin():
            enable_privileges()
            game_boost() if action == "boost" else run_action(action)
        return
    mutex = kernel32.CreateMutexW(None, False, f"Local\\{INSTANCE}_SINGLE")
    if ctypes.get_last_error() == 183:  # already running: bring that window up instead
        ev = kernel32.OpenEventW(0x0002, False, f"Local\\{INSTANCE}_SHOW")
        if ev:
            kernel32.SetEvent(ev)
        return
    show_event = kernel32.CreateEventW(None, False, False, f"Local\\{INSTANCE}_SHOW")
    set_dpi_awareness()
    ui = UI(start_hidden="--tray" in args, show_event=show_event)
    ui.root.mainloop()
    del mutex


if __name__ == "__main__":
    main()
