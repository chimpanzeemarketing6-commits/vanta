"""System tools for Vanta: disk clean-up, FPS-related Windows settings, power & thermal modes,
and a startup app manager (including turning off Legion Space at startup).

Everything here is plain Win32 / registry / built-in Windows commands, and every function fails
softly (returns None/False) so the UI never crashes on a machine that lacks a feature.
"""
import ctypes
import fnmatch
import json
import hmac
import os
import re
import stat
import struct
import subprocess
import time
import uuid
import winreg
from ctypes import wintypes

NO_WINDOW = 0x08000000
HKCU, HKLM = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32")
kernel32.GetDiskFreeSpaceExW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_ulonglong),
                                         ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_ulonglong)]
kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
kernel32.GetLogicalDrives.restype = wintypes.DWORD


def run(cmd, timeout=30):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
    except Exception:
        return None


def powershell(script, timeout=30):
    r = run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script], timeout)
    if r is None or r.returncode != 0:
        return None
    return r.stdout.strip()


def reg_get(root, path, name, default=None):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


def reg_set(root, path, name, value, kind=winreg.REG_DWORD):
    with winreg.CreateKeyEx(root, path, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
        winreg.SetValueEx(k, name, 0, kind, value)


def reg_subkeys(root, path):
    out = []
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumKey(k, i))
                except OSError:
                    break
                i += 1
    except OSError:
        pass
    return out


def reg_values(root, path, access=0):
    out = []
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | (access or winreg.KEY_WOW64_64KEY)) as k:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumValue(k, i))
                except OSError:
                    break
                i += 1
    except OSError:
        pass
    return out


def open_target(target):
    """Open a settings page, folder or program."""
    try:
        os.startfile(target)
        return True
    except OSError:
        return False


# =====================================================================  disk clean-up

LOCAL = os.environ.get("LOCALAPPDATA", "")
WIN = os.environ.get("SystemRoot", r"C:\Windows")
PDATA = os.environ.get("ProgramData", r"C:\ProgramData")
TEMP = os.environ.get("TEMP", os.path.join(LOCAL, "Temp"))


def _entries(path):
    try:
        return list(os.scandir(path))
    except OSError:
        return []


def _is_link(e):
    try:
        return e.is_symlink() or (hasattr(e, "is_junction") and e.is_junction())
    except OSError:
        return True


def folder_size(path, pattern=None):
    total, stack = 0, [path]
    while stack:
        for e in _entries(stack.pop()):
            try:
                if _is_link(e):
                    continue  # never follow links/junctions out of the folder
                if e.is_dir(follow_symlinks=False):
                    if pattern is None:
                        stack.append(e.path)
                elif pattern is None or fnmatch.fnmatch(e.name.lower(), pattern):
                    total += e.stat(follow_symlinks=False).st_size
            except OSError:
                pass
    return total


def clean_folder(path, pattern=None, min_age=0):
    """Delete the contents of path (never path itself). Locked/in-use files are skipped."""
    freed = 0
    now = time.time()
    for e in _entries(path):
        try:
            if _is_link(e):
                continue
            if e.is_dir(follow_symlinks=False):
                if pattern is not None:
                    continue
                freed += clean_folder(e.path, None, min_age)
                try:
                    os.rmdir(e.path)
                except OSError:
                    pass
                continue
            if pattern is not None and not fnmatch.fnmatch(e.name.lower(), pattern):
                continue
            st = e.stat(follow_symlinks=False)
            if min_age and now - st.st_mtime < min_age:
                continue
            try:
                os.remove(e.path)
            except PermissionError:
                os.chmod(e.path, stat.S_IWRITE)
                os.remove(e.path)
            freed += st.st_size
        except OSError:
            pass
    return freed


class SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]


def recycle_bin_size():
    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    try:
        if shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
            return info.i64Size
    except Exception:
        pass
    return 0


def empty_recycle_bin():
    size = recycle_bin_size()
    try:
        shell32.SHEmptyRecycleBinW(None, None, 0x7)  # no confirmation, no progress UI, no sound
    except Exception:
        return 0
    return max(0, size - recycle_bin_size())


def steam_libraries():
    steam = reg_get(HKCU, r"Software\Valve\Steam", "SteamPath")
    libs = []
    if steam:
        steam = os.path.normpath(steam)
        libs.append(steam)
        try:
            with open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="ignore") as f:
                for m in re.finditer(r'"path"\s+"([^"]+)"', f.read()):
                    p = os.path.normpath(m.group(1).replace("\\\\", "\\"))
                    if p.lower() not in (x.lower() for x in libs):
                        libs.append(p)
        except OSError:
            pass
    return libs


def _cat_targets(cid):
    """(kind, path, pattern, min_age) for each clean-up category."""
    if cid == "temp":
        return [("dir", TEMP, None, 3600)]
    if cid == "wintemp":
        return [("dir", os.path.join(WIN, "Temp"), None, 3600)]
    if cid == "dumps":
        return [("dir", os.path.join(LOCAL, "CrashDumps"), None, 0),
                ("dir", os.path.join(PDATA, r"Microsoft\Windows\WER\ReportArchive"), None, 0),
                ("dir", os.path.join(PDATA, r"Microsoft\Windows\WER\ReportQueue"), None, 0),
                ("dir", os.path.join(WIN, "Minidump"), None, 0),
                ("dir", os.path.join(WIN, "LiveKernelReports"), "*.dmp", 0),
                ("file", os.path.join(WIN, "MEMORY.DMP"), None, 0)]
    if cid == "updates":
        return [("dir", os.path.join(WIN, r"SoftwareDistribution\Download"), None, 0)]
    if cid == "delivery":
        return [("dir", os.path.join(WIN, r"ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\Cache"), None, 0)]
    if cid == "thumbs":
        return [("dir", os.path.join(LOCAL, r"Microsoft\Windows\Explorer"), "thumbcache_*.db", 0)]
    if cid == "shaders":
        return [("dir", os.path.join(LOCAL, "D3DSCache"), None, 0)] + \
               [("dir", os.path.join(LOCAL, "AMD", n), None, 0) for n in ("DxCache", "DxcCache", "VkCache", "GLCache", "OglCache")]
    if cid == "steamshaders":
        return [("dir", os.path.join(lib, "steamapps", "shadercache"), None, 0) for lib in steam_libraries()]
    return []


# id, name, description, selected by default
CLEAN_CATEGORIES = [
    ("temp", "Temporary files", "Leftovers apps put in your Temp folder", True),
    ("wintemp", "Windows temporary files", "Leftovers in Windows\\Temp", True),
    ("recycle", "Recycle Bin", "Files you already deleted", True),
    ("dumps", "Crash dumps & error reports", "Saved after apps or games crashed", True),
    ("delivery", "Delivery Optimization cache", "Update pieces shared with other PCs", True),
    ("updates", "Windows Update downloads", "Installer files; pending updates may download again", False),
    ("thumbs", "Thumbnail cache", "Explorer rebuilds the pictures it needs", False),
    ("shaders", "DirectX & AMD shader cache", "Good after a driver update. First game launches may stutter", False),
    ("steamshaders", "Steam shader cache", "Can be several GB. Steam downloads it again per game", False),
]


def scan_category(cid):
    if cid == "recycle":
        return recycle_bin_size()
    total = 0
    for kind, path, pattern, _ in _cat_targets(cid):
        if kind == "file":
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
        elif os.path.isdir(path):
            total += folder_size(path, pattern)
    return total


def clean_category(cid):
    if cid == "recycle":
        return empty_recycle_bin()
    freed = 0
    for kind, path, pattern, min_age in _cat_targets(cid):
        if kind == "file":
            try:
                size = os.path.getsize(path)
                os.remove(path)
                freed += size
            except OSError:
                pass
        elif os.path.isdir(path):
            freed += clean_folder(path, pattern, min_age)
    return freed


def drives():
    """[(letter, total, free)] for fixed drives."""
    out = []
    mask = kernel32.GetLogicalDrives()
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = f"{chr(65 + i)}:\\"
        if kernel32.GetDriveTypeW(root) != 3:  # DRIVE_FIXED
            continue
        free, total, _ = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
        if kernel32.GetDiskFreeSpaceExW(root, ctypes.byref(free), ctypes.byref(total), ctypes.byref(_)):
            out.append((chr(65 + i), total.value, free.value))
    return out


# =====================================================================  power & thermal

class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _guid(s):
    return GUID.from_buffer_copy(uuid.UUID(s).bytes_le)


# Windows 11 "Power mode" (Settings > System > Power & battery).
POWER_MODES = [
    ("efficiency", "Best power efficiency", "961cc777-2547-4f9d-8174-7d86181b8a7a"),
    ("balanced", "Balanced", "00000000-0000-0000-0000-000000000000"),
    ("performance", "Best performance", "ded574b5-45a0-4f42-8737-46345c09c238"),
]

try:
    _powrprof = ctypes.WinDLL("powrprof")
    _get_overlay = _powrprof.PowerGetEffectiveOverlayScheme
    _get_overlay.argtypes = [ctypes.POINTER(GUID)]
    _set_overlay = _powrprof.PowerSetActiveOverlayScheme
    _set_overlay.argtypes = [GUID]
except (OSError, AttributeError):
    _get_overlay = _set_overlay = None


def get_power_mode():
    if not _get_overlay:
        return None
    g = GUID()
    try:
        if _get_overlay(ctypes.byref(g)) != 0:
            return None
    except Exception:
        return None
    s = str(uuid.UUID(bytes_le=bytes(g)))
    return next((mid for mid, _, gid in POWER_MODES if gid == s), None)


def set_power_mode(mode_id):
    if not _set_overlay:
        return False
    gid = next(g for mid, _, g in POWER_MODES if mid == mode_id)
    try:
        return _set_overlay(_guid(gid)) == 0
    except Exception:
        return False


# Legion thermal mode, the same switch Legion Space uses (Lenovo GameZone WMI).
THERMAL_MODES = [(1, "Quiet"), (2, "Balanced"), (3, "Performance")]
_GZ = "Get-CimInstance -Namespace root/WMI -ClassName LENOVO_GAMEZONE_DATA"


def get_thermal_mode():
    out = powershell(f"({_GZ} | Invoke-CimMethod -MethodName GetSmartFanMode).Data", timeout=20)
    try:
        return int(out.splitlines()[-1]) if out else None
    except ValueError:
        return None


def set_thermal_mode(value):
    return powershell(f"{_GZ} | Invoke-CimMethod -MethodName SetSmartFanMode -Arguments @{{Data={int(value)}}} | Out-Null; 'ok'",
                      timeout=20) == "ok"


# =====================================================================  FPS-related Windows settings

GAMEBAR = r"Software\Microsoft\GameBar"
GAMEDVR = r"Software\Microsoft\Windows\CurrentVersion\GameDVR"
GFX = r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers"
HVCI = r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity"
PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def _set_dvr(on):
    reg_set(HKCU, r"System\GameConfigStore", "GameDVR_Enabled", 1 if on else 0)
    reg_set(HKCU, GAMEDVR, "AppCaptureEnabled", 1 if on else 0)
    return True


_BOOST = ["SCHEME_CURRENT", "SUB_PROCESSOR", "PERFBOOSTMODE"]


def get_cpu_boost_dc():
    """Is CPU boost allowed on battery? (PERFBOOSTMODE, hidden in the Windows UI.)"""
    r = run(["powercfg", "/q"] + _BOOST)
    m = re.search(r"Current DC Power Setting Index:\s*0x([0-9a-fA-F]+)", r.stdout if r else "")
    return int(m.group(1), 16) != 0 if m else None


def set_cpu_boost_dc(on):
    r = run(["powercfg", "/setdcvalueindex"] + _BOOST + ["2" if on else "0"])  # 2 = aggressive (default), 0 = off
    run(["powercfg", "/setactive", "SCHEME_CURRENT"])
    return bool(r and r.returncode == 0)


SERVICES_KEY = r"SYSTEM\CurrentControlSet\Services"


def service_enabled(name):
    start = reg_get(HKLM, rf"{SERVICES_KEY}\{name}", "Start", None)
    return None if start is None else start != 4


def set_service(name, on, auto="auto"):
    """Turn a Windows service off (disabled + stopped) or back on (its normal start type + started)."""
    r = run(["sc.exe", "config", name, "start=", auto if on else "disabled"])
    run(["sc.exe", "start" if on else "stop", name], timeout=20)
    return bool(r and r.returncode == 0)


BG_APPS = r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications"

# id, label, description, getter, setter, recommended state for FPS (None = no advice), needs restart, confirm
TWEAKS = [
    ("gamemode", "Game Mode", "Windows puts the game you're playing first",
     lambda: reg_get(HKCU, GAMEBAR, "AutoGameModeEnabled", 1) != 0,
     lambda on: reg_set(HKCU, GAMEBAR, "AutoGameModeEnabled", 1 if on else 0) or True, True, False, False),
    ("dvr", "Background recording", "Game Bar recording in the background costs FPS",
     lambda: reg_get(HKCU, r"System\GameConfigStore", "GameDVR_Enabled", 1) != 0 and reg_get(HKCU, GAMEDVR, "AppCaptureEnabled", 1) != 0,
     _set_dvr, False, False, False),
    ("hvci", "Memory integrity", "Microsoft suggests turning it off for gaming. Lowers protection against attacks",
     lambda: reg_get(HKLM, HVCI, "Enabled", 0) == 1,
     lambda on: reg_set(HKLM, HVCI, "Enabled", 1 if on else 0) or True, False, True, True),
    ("hags", "Hardware-accelerated GPU scheduling", "Results vary by game and driver",
     lambda: reg_get(HKLM, GFX, "HwSchMode", 1) == 2,
     lambda on: reg_set(HKLM, GFX, "HwSchMode", 2 if on else 1) or True, None, True, False),
    ("transparency", "Transparency effects", "Small saving for the integrated graphics",
     lambda: reg_get(HKCU, PERSONALIZE, "EnableTransparency", 1) != 0,
     lambda on: reg_set(HKCU, PERSONALIZE, "EnableTransparency", 1 if on else 0) or True, False, False, False),
    ("boost_dc", "CPU boost on battery", "Off: much cooler and longer battery, a few FPS less in CPU-heavy games",
     get_cpu_boost_dc, set_cpu_boost_dc, None, False, False),
    ("bgapps", "Store apps in the background", "Lets Store apps run and sync when they're closed",
     lambda: reg_get(HKCU, BG_APPS, "GlobalUserDisabled", 0) != 1,
     lambda on: reg_set(HKCU, BG_APPS, "GlobalUserDisabled", 0 if on else 1) or True, False, False, False),
    ("diagtrack", "Telemetry service", "Sends usage data to Microsoft in the background. Safe to turn off",
     lambda: service_enabled("DiagTrack"), lambda on: set_service("DiagTrack", on), False, False, False),
    ("sysmain", "SysMain (Superfetch)", "Preloads apps into RAM. Off can mean fewer stutters on 16 GB, slower app launches",
     lambda: service_enabled("SysMain"), lambda on: set_service("SysMain", on), None, False, False),
    ("wsearch", "Search indexing", "Indexes files in the background. Off: Start search finds files more slowly",
     lambda: service_enabled("WSearch"), lambda on: set_service("WSearch", on, "delayed-auto"), None, False, False),
]


def read_tweaks():
    out = {}
    for tid, _, _, get, *_ in TWEAKS:
        try:
            v = get()
            out[tid] = None if v is None else bool(v)
        except Exception:
            out[tid] = None
    return out


def set_tweak(tid, on):
    for t in TWEAKS:
        if t[0] == tid:
            try:
                return bool(t[4](on))
            except Exception:
                return False
    return False


AMD_SOFTWARE = r"C:\Program Files\AMD\CNext\CNext\RadeonSoftware.exe"


def shortcuts(legion_apps):
    out = [("Graphics settings", "ms-settings:display-advancedgraphics"),
           ("Game Mode settings", "ms-settings:gaming-gamemode"),
           ("Storage settings", "ms-settings:storagesense")]
    if os.path.exists(AMD_SOFTWARE):
        out.insert(0, ("AMD Software", AMD_SOFTWARE))
    for name, appid in legion_apps[:1]:
        out.insert(0, (f"Open {name}", f"shell:AppsFolder\\{appid}"))
    return out


# =====================================================================  startup apps

APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN32 = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
PKG_TASKS = r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\SystemAppData"

_PS_STARTUP = r"""
$t = @(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
    $_.TaskPath -notlike '\Microsoft\*' -and $_.TaskName -notin @('RAMOPT Go', 'Vanta') -and
    ($_.Triggers | Where-Object { $_.CimClass.CimClassName -in 'MSFT_TaskLogonTrigger','MSFT_TaskBootTrigger' }) } |
    ForEach-Object { [pscustomobject]@{Name=$_.TaskName; Path=$_.TaskPath; State=[string]$_.State;
                     Exec=[string](($_.Actions | Select-Object -First 1).Execute)} })
$a = @(Get-StartApps | Where-Object { $_.Name -like '*Legion*' } | Select-Object Name, AppID)
[pscustomobject]@{tasks=$t; apps=$a} | ConvertTo-Json -Depth 4 -Compress
"""


def _approved_enabled(root, sub, name):
    data = reg_get(root, f"{APPROVED}\\{sub}", name)
    return not (isinstance(data, (bytes, bytearray)) and data and data[0] & 1)


def _short(cmd):
    m = re.match(r'\s*"([^"]+)"|\s*(\S+)', cmd or "")
    path = (m.group(1) or m.group(2)) if m else ""
    return os.path.basename(path) or cmd or ""


def _pkg_name(family):
    base = family.split("_")[0]
    base = base.split(".", 1)[1] if "." in base else base
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base)


def startup_items():
    """Everything that starts with Windows, as dicts the UI can show and toggle. Also returns Legion Start-menu apps."""
    items = []
    for root, path, sub, src in ((HKCU, RUN, "Run", "Registry (you)"), (HKLM, RUN, "Run", "Registry (all users)"),
                                 (HKLM, RUN32, "Run32", "Registry (all users)")):
        for name, cmd, _ in reg_values(root, path):
            items.append({"key": f"run|{root}|{sub}|{name}", "kind": "run", "name": name, "source": src,
                          "detail": _short(str(cmd)), "enabled": _approved_enabled(root, sub, name),
                          "root": root, "sub": sub, "value": name})
    for root, folder, src in ((HKCU, os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup"), "Startup folder (you)"),
                              (HKLM, os.path.join(PDATA, r"Microsoft\Windows\Start Menu\Programs\StartUp"), "Startup folder (all users)")):
        for e in _entries(folder):
            if e.name.lower() == "desktop.ini" or not e.is_file():
                continue
            items.append({"key": f"folder|{root}|{e.name}", "kind": "run", "name": os.path.splitext(e.name)[0], "source": src,
                          "detail": e.name, "enabled": _approved_enabled(root, "StartupFolder", e.name),
                          "root": root, "sub": "StartupFolder", "value": e.name})
    for family in reg_subkeys(HKCU, PKG_TASKS):
        for task in reg_subkeys(HKCU, f"{PKG_TASKS}\\{family}"):
            state = reg_get(HKCU, f"{PKG_TASKS}\\{family}\\{task}", "State")
            if state is None:
                continue
            items.append({"key": f"pkg|{family}|{task}", "kind": "pkg", "name": _pkg_name(family), "source": "Store app",
                          "detail": task, "enabled": state in (2, 4), "path": f"{PKG_TASKS}\\{family}\\{task}",
                          "locked": state in (3, 4)})
    apps = []
    data = powershell(_PS_STARTUP, timeout=40)
    if data:
        try:
            obj = json.loads(data)
            tasks = obj.get("tasks") or []
            tasks = [tasks] if isinstance(tasks, dict) else tasks
            for t in tasks:
                full = (t.get("Path") or "\\") + (t.get("Name") or "")
                items.append({"key": f"task|{full}", "kind": "task", "name": t.get("Name") or full, "source": "Scheduled task",
                              "detail": _short(t.get("Exec") or ""), "enabled": (t.get("State") or "") != "Disabled", "path": full})
            a = obj.get("apps") or []
            a = [a] if isinstance(a, dict) else a
            apps = [(x.get("Name"), x.get("AppID")) for x in a if x.get("AppID")]
        except (ValueError, AttributeError):
            pass
    for svc in reg_subkeys(HKLM, r"SYSTEM\CurrentControlSet\Services"):
        base = f"SYSTEM\\CurrentControlSet\\Services\\{svc}"
        display = str(reg_get(HKLM, base, "DisplayName", "") or "")
        if "legion" not in (svc + display).lower() or display.startswith("@"):
            continue
        if not reg_get(HKLM, base, "Type", 0) & 0x30:  # services only, not drivers
            continue
        start = reg_get(HKLM, base, "Start", 3)
        items.append({"key": f"svc|{svc}", "kind": "service", "name": display or svc, "source": "Service",
                      "detail": svc, "enabled": start == 2, "service": svc})
    for it in items:
        it["legion"] = "legion" in (it["name"] + " " + it["detail"] + " " + it.get("path", "")).lower()
    items.sort(key=lambda i: (not i["legion"], i["name"].lower()))
    return items, apps


def set_startup_item(item, on):
    kind = item["kind"]
    try:
        if kind == "run":
            reg_set(item["root"], f"{APPROVED}\\{item['sub']}", item["value"], bytes([2 if on else 3]) + bytes(11), winreg.REG_BINARY)
            return True
        if kind == "pkg":
            reg_set(HKCU, item["path"], "State", 2 if on else 1)
            return True
        if kind == "task":
            r = run(["schtasks", "/change", "/tn", item["path"], "/enable" if on else "/disable"])
            return bool(r and r.returncode == 0)
        if kind == "service":
            r = run(["sc", "config", item["service"], "start=", "auto" if on else "demand"])
            return bool(r and r.returncode == 0)
    except OSError:
        return False
    return False


def restart_pc():
    run(["shutdown", "/r", "/t", "5", "/c", "Restarting to apply Vanta settings"])


# =====================================================================  CPU & battery

class FILETIME(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    @property
    def value(self):
        return (self.hi << 32) | self.lo


kernel32.GetSystemTimes.argtypes = [ctypes.POINTER(FILETIME)] * 3
kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(FILETIME)] * 4
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
CPU_COUNT = os.cpu_count() or 1


def system_times():
    idle, kern, user = FILETIME(), FILETIME(), FILETIME()
    if not kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
        return None
    return idle.value, kern.value + user.value  # kernel time includes idle


def cpu_percent(prev, cur):
    if not prev or not cur:
        return None
    di, dt = cur[0] - prev[0], cur[1] - prev[1]
    return max(0.0, min(100.0, (1 - di / dt) * 100)) if dt > 0 else None


def process_cpu_times(pids):
    """{pid: kernel+user time in 100 ns units}"""
    out = {}
    c, e, k, u = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    for pid in pids:
        h = kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            continue
        try:
            if kernel32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
                out[pid] = k.value + u.value
        finally:
            kernel32.CloseHandle(h)
    return out


def process_alive(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(h)


END_TASK_PROTECT = {"system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
                    "lsass.exe", "svchost.exe", "dwm.exe", "explorer.exe", "fontdrvhost.exe", "memcompression",
                    "audiodg.exe", "ctfmon.exe", "sihost.exe", "textinputhost.exe", "spoolsv.exe", "msmpeng.exe"}


def end_process(pid, name):
    if pid <= 4 or pid == os.getpid() or name.lower() in END_TASK_PROTECT:
        return False
    h = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
    if not h:
        return False
    try:
        return bool(kernel32.TerminateProcess(h, 1))
    finally:
        kernel32.CloseHandle(h)


class SYSTEM_BATTERY_STATE(ctypes.Structure):
    _fields_ = [("AcOnLine", ctypes.c_ubyte), ("BatteryPresent", ctypes.c_ubyte), ("Charging", ctypes.c_ubyte),
                ("Discharging", ctypes.c_ubyte), ("Spare1", ctypes.c_ubyte * 3), ("Tag", ctypes.c_ubyte),
                ("MaxCapacity", wintypes.DWORD), ("RemainingCapacity", wintypes.DWORD), ("Rate", ctypes.c_long),
                ("EstimatedTime", wintypes.DWORD), ("DefaultAlert1", wintypes.DWORD), ("DefaultAlert2", wintypes.DWORD)]


try:
    _cnpi = ctypes.WinDLL("powrprof").CallNtPowerInformation
    _cnpi.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG]
except (OSError, AttributeError):
    _cnpi = None


def battery_state():
    """Cheap native battery read: capacity in mWh, rate in mW (negative while discharging)."""
    if not _cnpi:
        return None
    s = SYSTEM_BATTERY_STATE()
    try:
        if _cnpi(5, None, 0, ctypes.byref(s), ctypes.sizeof(s)) != 0 or not s.BatteryPresent:
            return None
    except Exception:
        return None
    rate = s.Rate
    if rate in (-0x80000000, 0x80000000):  # BATTERY_UNKNOWN_RATE
        rate = 0
    est = s.EstimatedTime if s.EstimatedTime not in (0xFFFFFFFF, 0) else None
    return {"ac": bool(s.AcOnLine), "charging": bool(s.Charging), "discharging": bool(s.Discharging),
            "full_mwh": s.MaxCapacity, "remaining_mwh": s.RemainingCapacity, "rate_mw": rate, "est_s": est}


_PS_BATTERY = r"""
$d = Get-CimInstance -Namespace root/WMI -ClassName BatteryStaticData -ErrorAction SilentlyContinue | Select-Object -First 1
$c = Get-CimInstance -Namespace root/WMI -ClassName BatteryCycleCount -ErrorAction SilentlyContinue | Select-Object -First 1
$f = Get-CimInstance -Namespace root/WMI -ClassName BatteryFullChargedCapacity -ErrorAction SilentlyContinue | Select-Object -First 1
[pscustomobject]@{design=$d.DesignedCapacity; cycles=$c.CycleCount; full=$f.FullChargedCapacity; maker=$d.ManufactureName} | ConvertTo-Json -Compress
"""


def battery_static():
    """Design capacity and cycle count (slow, read once)."""
    out = powershell(_PS_BATTERY, timeout=25)
    try:
        return json.loads(out) if out else None
    except ValueError:
        return None


def windows_light_mode():
    return reg_get(HKCU, PERSONALIZE, "AppsUseLightTheme", 0) == 1


def windows_build():
    v = reg_get(HKLM, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "DisplayVersion", "")
    b = reg_get(HKLM, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "CurrentBuildNumber", "")
    name = "Windows 11" if b and b.isdigit() and int(b) >= 22000 else "Windows 10" if b else "Windows"
    return f"{name} {v} (build {b})".strip()


# =====================================================================  Steam games & big files

def _acf_value(text, key):
    m = re.search(r'"%s"\s+"([^"]*)"' % key, text)
    return m.group(1) if m else ""


def steam_games():
    """[(appid, name, size_bytes, last_played_ts, library)] sorted by size."""
    games = []
    for lib in steam_libraries():
        apps = os.path.join(lib, "steamapps")
        for e in _entries(apps):
            if not (e.name.startswith("appmanifest_") and e.name.endswith(".acf")):
                continue
            try:
                with open(e.path, encoding="utf-8", errors="ignore") as f:
                    t = f.read()
            except OSError:
                continue
            appid, name = _acf_value(t, "appid"), _acf_value(t, "name")
            if appid in ("228980",) or not name:  # Steamworks Common Redistributables
                continue
            size = int(_acf_value(t, "SizeOnDisk") or 0)
            if not size:
                inst = _acf_value(t, "installdir")
                if inst:
                    size = folder_size(os.path.join(apps, "common", inst))
            last = int(_acf_value(t, "LastPlayed") or 0)
            games.append((appid, name, size, last, lib))
    games.sort(key=lambda g: g[2], reverse=True)
    return games


def known_folder(guid_str):
    """Real path of a user folder, even if it was moved (e.g. Downloads on another drive)."""
    try:
        sh = ctypes.WinDLL("shell32")
        sh.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
        out = ctypes.c_wchar_p()
        if sh.SHGetKnownFolderPath(ctypes.byref(_guid(guid_str)), 0, None, ctypes.byref(out)) == 0:
            path = out.value
            ctypes.windll.ole32.CoTaskMemFree(out)
            return path
    except Exception:
        pass
    return None


USER_FOLDERS = [("Downloads", "374de290-123f-4565-9164-39c4925e467b"), ("Videos", "18989b1d-99b5-455b-841c-ab7c74e4ddfc"),
                ("Desktop", "b4bfcc3a-db2c-424c-b029-7fe99a87c641"), ("Documents", "fdd39ad0-238f-46af-adb4-6c85480369c7"),
                ("Pictures", "33e28130-4e1e-4676-835a-98395c3bc3bb")]


def big_files(min_size=150 * 1048576, limit=40):
    """Largest files in your own folders: [(path, size, mtime, folder_label)]."""
    found = []
    for label, gid in USER_FOLDERS:
        root = known_folder(gid) or os.path.join(os.path.expanduser("~"), label)
        stack, seen = [root], 0
        while stack and seen < 60000:
            for e in _entries(stack.pop()):
                seen += 1
                try:
                    if _is_link(e) or e.name.startswith("."):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                        continue
                    st = e.stat(follow_symlinks=False)
                    if st.st_size >= min_size:
                        found.append((e.path, st.st_size, st.st_mtime, label))
                except OSError:
                    pass
    found.sort(key=lambda f: f[1], reverse=True)
    return found[:limit]


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR)]


def recycle(path):
    """Send a file to the Recycle Bin (so it can be restored)."""
    op = SHFILEOPSTRUCTW()
    op.wFunc = 3  # FO_DELETE
    op.pFrom = path + "\0"
    op.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400  # ALLOWUNDO | NOCONFIRMATION | SILENT | NOERRORUI
    try:
        return shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not os.path.exists(path)
    except Exception:
        return False


def show_in_explorer(path):
    run(["explorer.exe", f"/select,{path}"], timeout=5)


# =====================================================================  overlay window

user32 = ctypes.WinDLL("user32")
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
try:
    _get_ex = user32.GetWindowLongPtrW
    _set_ex = user32.SetWindowLongPtrW
except AttributeError:
    _get_ex, _set_ex = user32.GetWindowLongW, user32.SetWindowLongW
_get_ex.argtypes = [wintypes.HWND, ctypes.c_int]
_get_ex.restype = ctypes.c_ssize_t
_set_ex.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_set_ex.restype = ctypes.c_ssize_t


def make_click_through(widget):
    """Let taps and clicks pass through an overlay window to the game below; keep it off the taskbar and Alt+Tab."""
    hwnd = user32.GetParent(widget.winfo_id()) or widget.winfo_id()
    ex = _get_ex(hwnd, -20)
    _set_ex(hwnd, -20, ex | 0x00080000 | 0x00000020 | 0x00000080 | 0x08000000 | 0x00000008)
    # WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST


# =====================================================================  display (refresh rate & resolution)

class DEVMODEW(ctypes.Structure):
    _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD), ("dmDriverVersion", wintypes.WORD),
                ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
                ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG), ("dmDisplayOrientation", wintypes.DWORD),
                ("dmDisplayFixedOutput", wintypes.DWORD), ("dmColor", wintypes.SHORT), ("dmDuplex", wintypes.SHORT),
                ("dmYResolution", wintypes.SHORT), ("dmTTOption", wintypes.SHORT), ("dmCollate", wintypes.SHORT),
                ("dmFormName", wintypes.WCHAR * 32), ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD),
                ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD), ("dmICMIntent", wintypes.DWORD),
                ("dmMediaType", wintypes.DWORD), ("dmDitherType", wintypes.DWORD), ("dmReserved1", wintypes.DWORD),
                ("dmReserved2", wintypes.DWORD), ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD)]


user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW)]
user32.ChangeDisplaySettingsExW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(DEVMODEW), wintypes.HWND, wintypes.DWORD, ctypes.c_void_p]
user32.ChangeDisplaySettingsExW.restype = ctypes.c_long


def _devmode(index):
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    return dm if user32.EnumDisplaySettingsW(None, index, ctypes.byref(dm)) else None


def display_modes():
    """Current mode and the choices for the main screen: {"w","h","hz","rates":[...],"sizes":[(w,h),...]}"""
    cur = _devmode(0xFFFFFFFF)  # ENUM_CURRENT_SETTINGS
    if not cur:
        return None
    modes, i = set(), 0
    while True:
        dm = _devmode(i)
        if not dm:
            break
        if dm.dmBitsPerPel == cur.dmBitsPerPel:
            modes.add((dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency))
        i += 1
        if i > 2000:
            break
    w, h, hz = cur.dmPelsWidth, cur.dmPelsHeight, cur.dmDisplayFrequency
    rates = sorted({m[2] for m in modes if m[0] == w and m[1] == h and m[2] > 1})
    aspect = w / max(1, h)
    sizes = sorted({(m[0], m[1]) for m in modes if abs(m[0] / max(1, m[1]) - aspect) < 0.02 and min(m[0], m[1]) >= 720},
                   reverse=True)
    return {"w": w, "h": h, "hz": hz, "rates": rates or [hz], "sizes": sizes or [(w, h)]}


def set_display_mode(w=None, h=None, hz=None):
    cur = _devmode(0xFFFFFFFF)
    if not cur:
        return False
    fields = 0
    if w and h:
        cur.dmPelsWidth, cur.dmPelsHeight = w, h
        fields |= 0x80000 | 0x100000  # DM_PELSWIDTH | DM_PELSHEIGHT
    if hz:
        best = None
        if w and h:  # pick the closest refresh rate the new resolution supports
            for i in range(2000):
                dm = _devmode(i)
                if not dm:
                    break
                if dm.dmPelsWidth == w and dm.dmPelsHeight == h and (best is None or abs(dm.dmDisplayFrequency - hz) < abs(best - hz)):
                    best = dm.dmDisplayFrequency
        cur.dmDisplayFrequency = best or hz
        fields |= 0x400000  # DM_DISPLAYFREQUENCY
    cur.dmFields = fields
    return user32.ChangeDisplaySettingsExW(None, ctypes.byref(cur), None, 0x1, None) == 0  # CDS_UPDATEREGISTRY


# =====================================================================  profiles

# id, name, description, Windows power mode, Legion thermal mode, refresh choice ("min" / "max" / None = leave)
PROFILES = [
    ("saver", "Battery saver", "Efficiency power · Quiet · lowest refresh rate", "efficiency", 1, "min"),
    ("balanced", "Balanced", "Balanced power · Balanced thermal", "balanced", 2, None),
    ("max", "Max performance", "Best performance · Performance · highest refresh", "performance", 3, "max"),
]


def apply_profile(pid, legion):
    """Returns a list of what changed (for the log)."""
    prof = next(p for p in PROFILES if p[0] == pid)
    done = []
    if set_power_mode(prof[3]):
        done.append("power mode")
    if legion and set_thermal_mode(prof[4]):
        done.append("thermal mode")
    if prof[5]:
        modes = display_modes()
        if modes:
            target = modes["rates"][0] if prof[5] == "min" else modes["rates"][-1]
            if target != modes["hz"] and set_display_mode(hz=target):
                done.append(f"{target} Hz")
    return done


# =====================================================================  Legion firmware: custom TDP & charge limit
# IDs as used by Lenovo's "Other Method" WMI interface (see the lenovo-wmi-other Linux driver):
#   0x0102FF00 sustained power limit (SPL), 0x0101FF00 short boost (SPPT), 0x0103FF00 peak (FPPT),
#   0x03010001 battery charge limit (stops at about 80%).
_OM = "Get-CimInstance -Namespace root/WMI -ClassName LENOVO_OTHER_METHOD"
TDP_IDS = {"spl": 0x0102FF00, "sppt": 0x0101FF00, "fppt": 0x0103FF00}
CHARGE_LIMIT_ID = 0x03010001


def get_feature(fid):
    out = powershell(f"({_OM} | Invoke-CimMethod -MethodName GetFeatureValue -Arguments @{{IDs=[int]{fid}}}).Value", timeout=20)
    try:
        return int(out.splitlines()[-1]) if out else None
    except ValueError:
        return None


def set_features(pairs):
    """pairs: [(id, value)] in one PowerShell call. True if every call ran."""
    lines = [f"{_OM} | Invoke-CimMethod -MethodName SetFeatureValue -Arguments @{{IDs=[int]{fid}; value=[int]{int(v)}}} | Out-Null"
             for fid, v in pairs]
    return powershell("$ErrorActionPreference='Stop'; " + "; ".join(lines) + "; 'ok'", timeout=30) == "ok"


def get_tdp():
    return get_feature(TDP_IDS["spl"])


def set_tdp(watts, max_w=30):
    """Custom thermal mode, then sustained = watts with a small boost/peak headroom on top."""
    w = max(5, min(max_w, int(watts)))
    if not set_thermal_mode(255):
        return False
    return set_features([(TDP_IDS["spl"], w), (TDP_IDS["sppt"], min(w + 2, max_w + 2)), (TDP_IDS["fppt"], min(w + 4, max_w + 5))])


def get_charge_limit():
    v = get_feature(CHARGE_LIMIT_ID)
    return None if v is None else bool(v)


def set_charge_limit(on):
    return set_features([(CHARGE_LIMIT_ID, 1 if on else 0)])


# =====================================================================  GPU usage (performance counters)

class _PDH_VALUE(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class _PDH_ITEM(ctypes.Structure):
    _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", _PDH_VALUE)]


class GpuMeter:
    """3D engine utilization summed over all processes, like Task Manager's GPU graph."""

    def __init__(self):
        self.pdh = ctypes.WinDLL("pdh")
        self.q, self.c = wintypes.HANDLE(), wintypes.HANDLE()
        if self.pdh.PdhOpenQueryW(None, None, ctypes.byref(self.q)) != 0:
            raise OSError("PdhOpenQuery failed")
        path = r"\GPU Engine(*engtype_3D)\Utilization Percentage"
        if self.pdh.PdhAddEnglishCounterW(self.q, path, None, ctypes.byref(self.c)) != 0:
            raise OSError("GPU counters unavailable")
        self.pdh.PdhCollectQueryData(self.q)

    def read(self):
        if self.pdh.PdhCollectQueryData(self.q) != 0:
            return None
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        fmt = 0x00000200 | 0x00008000  # PDH_FMT_DOUBLE | PDH_FMT_NOCAP100
        r = self.pdh.PdhGetFormattedCounterArrayW(self.c, fmt, ctypes.byref(size), ctypes.byref(count), None)
        if r != ctypes.c_long(0x800007D2).value and r != 0x800007D2:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if self.pdh.PdhGetFormattedCounterArrayW(self.c, fmt, ctypes.byref(size), ctypes.byref(count), buf) != 0:
            return None
        items = ctypes.cast(buf, ctypes.POINTER(_PDH_ITEM * count.value)).contents
        engines = {}
        for it in items:
            if it.FmtValue.CStatus in (0, 1):  # valid data
                name = it.szName or ""
                key = name[name.find("luid"):] if "luid" in name else name  # same engine across processes
                engines[key] = engines.get(key, 0.0) + it.FmtValue.doubleValue
        return min(100.0, max(engines.values())) if engines else 0.0


# =====================================================================  brightness & volume

def get_brightness():
    out = powershell("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop | "
                     "Select-Object -First 1).CurrentBrightness", timeout=15)
    try:
        return int(out.splitlines()[-1]) if out else None
    except ValueError:
        return None


def set_brightness(pct):
    return powershell("$m = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop | "
                      f"Select-Object -First 1; Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness "
                      f"-Arguments @{{Timeout=[uint32]0; Brightness=[byte]{int(pct)}}} | Out-Null; 'ok'", timeout=15) == "ok"


user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]


def volume_key(which, times=1):
    """Windows' own volume keys, so the usual volume pop-up shows."""
    vk = {"down": 0xAE, "up": 0xAF, "mute": 0xAD}[which]
    for _ in range(times):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)


# =====================================================================  duplicates

def find_duplicates(min_size=20 * 1048576, max_files=20000):
    """Groups of identical files in your own folders: [(size, [(path, mtime), ...])], biggest waste first."""
    import hashlib
    by_size = {}
    seen = 0
    for label, gid in USER_FOLDERS:
        root = known_folder(gid) or os.path.join(os.path.expanduser("~"), label)
        stack = [root]
        while stack and seen < max_files:
            for e in _entries(stack.pop()):
                try:
                    if _is_link(e) or e.name.startswith("."):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                        continue
                    st = e.stat(follow_symlinks=False)
                    if st.st_size >= min_size:
                        seen += 1
                        by_size.setdefault(st.st_size, []).append((e.path, st.st_mtime))
                except OSError:
                    pass

    def digest(path, quick):
        h = hashlib.sha1()
        try:
            with open(path, "rb") as f:
                if quick:
                    h.update(f.read(65536))
                    f.seek(max(0, os.path.getsize(path) - 65536))
                    h.update(f.read(65536))
                else:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
        except OSError:
            return None
        return h.hexdigest()

    groups = []
    for size, files in by_size.items():
        if len(files) < 2:
            continue
        for quick in (True, False):
            buckets = {}
            for f in files:
                d = digest(f[0], quick)
                if d:
                    buckets.setdefault(d, []).append(f)
            files = [f for b in buckets.values() if len(b) > 1 for f in b]
            if not files:
                break
        full = {}
        for f in files:
            full.setdefault(digest(f[0], False), []).append(f)
        for b in full.values():
            if len(b) > 1:
                groups.append((size, sorted(b, key=lambda x: x[1])))
    groups.sort(key=lambda g: g[0] * (len(g[1]) - 1), reverse=True)
    return groups


# =====================================================================  closing apps

def close_apps(names):
    """Force-close every running copy of these programs (only ones the user picked)."""
    closed = []
    for n in names:
        if n.lower() in END_TASK_PROTECT:
            continue
        r = run(["taskkill", "/f", "/t", "/im", n], timeout=15)
        if r and r.returncode == 0:
            closed.append(n)
    return closed


# =====================================================================  FPS (PresentMon, downloaded on request)

PM_DIR = os.path.join(LOCAL or os.path.expanduser("~"), "Vanta")
PM_PATH = os.path.join(PM_DIR, "PresentMon.exe")
_OLD_PM = os.path.join(LOCAL or os.path.expanduser("~"), "RamOptimizer", "PresentMon.exe")


def presentmon_installed():
    if not os.path.exists(PM_PATH) and os.path.exists(_OLD_PM):  # downloaded by RAM//OPT Go: reuse it
        try:
            import shutil
            os.makedirs(PM_DIR, exist_ok=True)
            shutil.copy2(_OLD_PM, PM_PATH)
        except OSError:
            return False
    return os.path.exists(PM_PATH)


def download_presentmon():
    """Fetch Intel's PresentMon console app (MIT licence) from its official GitHub releases."""
    import urllib.request
    req = urllib.request.Request("https://api.github.com/repos/GameTechDev/PresentMon/releases/latest",
                                 headers={"User-Agent": "Vanta", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rel = json.loads(r.read().decode("utf-8"))
    assets = rel.get("assets", [])
    pick = next((a for a in assets if re.fullmatch(r"PresentMon-[\d.]+-x64\.exe", a.get("name", ""))), None) or \
        next((a for a in assets if a.get("name", "").lower().endswith(".exe") and "x64" in a.get("name", "").lower()), None)
    if not pick:
        raise OSError("No PresentMon download found in the latest release")
    os.makedirs(PM_DIR, exist_ok=True)
    tmp = PM_PATH + ".part"
    req = urllib.request.Request(pick["browser_download_url"], headers={"User-Agent": "Vanta"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
    os.replace(tmp, PM_PATH)
    return rel.get("tag_name", "")


class FpsReader:
    """Runs PresentMon for one process and keeps a rolling window of frame times."""
    COLUMNS = ("FrameTime", "MsBetweenPresents", "msBetweenPresents", "MsBetweenAppStart")

    def __init__(self, pid):
        import collections
        import threading
        self.pid = pid
        self.frames = collections.deque(maxlen=4000)  # (time, ms)
        self.error = None
        self.proc = subprocess.Popen(
            [PM_PATH, "--process_id", str(pid), "--output_stdout", "--stop_existing_session",
             "--terminate_on_proc_exit", "--session_name", "VANTA"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=NO_WINDOW)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        col = None
        for line in self.proc.stdout:
            parts = line.rstrip("\r\n").split(",")
            if col is None:
                col = next((parts.index(c) for c in self.COLUMNS if c in parts), None)
                continue
            try:
                ms = float(parts[col])
            except (ValueError, IndexError):
                continue
            if ms > 0:
                self.frames.append((time.time(), ms))
        if col is None:
            try:
                self.error = (self.proc.stderr.read() or "").strip().splitlines()[0][:120]
            except Exception:
                self.error = "PresentMon stopped"

    def stats(self):
        """(fps over the last second, 1% low over the last 10 s) or None."""
        now = time.time()
        recent = [ms for t, ms in self.frames if now - t <= 1.0]
        if not recent:
            return None
        window = sorted((ms for t, ms in self.frames if now - t <= 10.0), reverse=True)
        low = window[max(0, len(window) // 100)] if window else None
        return 1000.0 / (sum(recent) / len(recent)), (1000.0 / low if low else None)

    def stop(self):
        try:
            self.proc.terminate()
        except Exception:
            pass


# =====================================================================  game library (hub)

def parse_vdf(text):
    """Minimal Valve KeyValues (text VDF) parser -> nested dicts with lower-cased keys."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    root, stack, key = {}, [], None
    cur = root
    for quoted, brace in tokens:
        if brace == "{":
            new = {}
            if key is not None:
                cur[key.lower()] = new
            stack.append(cur)
            cur, key = new, None
        elif brace == "}":
            cur = stack.pop() if stack else root
            key = None
        elif key is None:
            key = quoted
        else:
            cur[key.lower()] = quoted.replace("\\\\", "\\")
            key = None
    return root


def _steam_root():
    p = reg_get(HKCU, r"Software\Valve\Steam", "SteamPath")
    return os.path.normpath(p) if p else None


def steam_playtimes(steam):
    """{appid: (minutes, last_played)} from the most recently used Steam account."""
    best, best_m = None, 0
    for user in _entries(os.path.join(steam, "userdata")):
        cfg = os.path.join(user.path, "config", "localconfig.vdf")
        try:
            m = os.path.getmtime(cfg)
        except OSError:
            continue
        if m > best_m:
            best, best_m = cfg, m
    if not best:
        return {}
    try:
        with open(best, encoding="utf-8", errors="ignore") as f:
            data = parse_vdf(f.read())
    except OSError:
        return {}
    node = data
    for key in ("userlocalconfigstore", "software", "valve", "steam", "apps"):
        node = node.get(key, {}) if isinstance(node, dict) else {}
    out = {}
    for appid, info in node.items():
        if isinstance(info, dict):
            try:
                out[appid] = (int(info.get("playtime", 0) or 0), int(info.get("lastplayed", 0) or 0))
            except ValueError:
                pass
    return out


def steam_cover(steam, appid):
    """Portrait cover art Steam already keeps on disk (old and 2024+ cache layouts)."""
    cache = os.path.join(steam, "appcache", "librarycache")
    for name in (f"{appid}_library_600x900.jpg", f"{appid}_library_600x900_2x.jpg"):
        p = os.path.join(cache, name)
        if os.path.exists(p):
            return p
    folder = os.path.join(cache, str(appid))
    found = {}
    stack = [(folder, 0)]
    while stack:
        path, depth = stack.pop()
        for e in _entries(path):
            if e.is_dir(follow_symlinks=False) and depth < 2:
                stack.append((e.path, depth + 1))
            elif e.name.lower().endswith((".jpg", ".png")):
                found.setdefault(e.name.lower(), e.path)
    for want in ("library_600x900.jpg", "library_600x900_2x.jpg", "library_capsule.jpg", "header.jpg", "library_header.jpg"):
        if want in found:
            return found[want]
    p = os.path.join(cache, f"{appid}_header.jpg")
    return p if os.path.exists(p) else None


def steam_library():
    steam = _steam_root()
    if not steam:
        return []
    times = steam_playtimes(steam)
    out = []
    for appid, name, size, last, lib in steam_games():
        minutes, last2 = times.get(appid, (0, 0))
        out.append({"id": f"steam:{appid}", "source": "Steam", "name": name, "size": size, "last": max(last, last2),
                    "minutes": minutes, "cover": steam_cover(steam, appid), "launch": f"steam://rungameid/{appid}",
                    "store": f"steam://nav/games/details/{appid}"})
    return out


def epic_library():
    folder = os.path.join(PDATA, r"Epic\EpicGamesLauncher\Data\Manifests")
    out = []
    for e in _entries(folder):
        if not e.name.endswith(".item"):
            continue
        try:
            with open(e.path, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        if m.get("bIsIncompleteInstall") or not m.get("DisplayName"):
            continue
        ns, item, app = m.get("CatalogNamespace", ""), m.get("CatalogItemId", ""), m.get("AppName", "")
        out.append({"id": f"epic:{app}", "source": "Epic", "name": m["DisplayName"], "size": int(m.get("InstallSize") or 0),
                    "last": 0, "minutes": 0, "cover": None, "epic_item": item,
                    "launch": f"com.epicgames.launcher://apps/{ns}%3A{item}%3A{app}?action=launch&silent=true",
                    "exe": os.path.join(m.get("InstallLocation", ""), m.get("LaunchExecutable", ""))})
    return out


def gog_library():
    out = []
    base = r"SOFTWARE\WOW6432Node\GOG.com\Games"
    for gid in reg_subkeys(HKLM, base):
        k = f"{base}\\{gid}"
        name = reg_get(HKLM, k, "gameName") or reg_get(HKLM, k, "GAMENAME")
        exe = reg_get(HKLM, k, "exe") or reg_get(HKLM, k, "EXE")
        if not name or not exe:
            continue
        out.append({"id": f"gog:{gid}", "source": "GOG", "name": name, "size": 0, "last": 0, "minutes": 0, "cover": None,
                    "launch": exe, "exe": exe, "cwd": reg_get(HKLM, k, "path") or os.path.dirname(exe)})
    return out


def amazon_library():
    """Amazon Games (Prime Gaming) installs, from the Amazon Games app's own install database."""
    import sqlite3
    db = os.path.join(LOCAL or "", r"Amazon Games\Data\Games\Sql\GameInstallInfo.sqlite")
    if not LOCAL or not os.path.exists(db):
        return []
    out = []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
    try:
        rows = con.execute("SELECT Id, ProductTitle, InstallDirectory, Installed FROM DbSet").fetchall()
    finally:
        con.close()
    for gid, title, folder, installed in rows:
        if not installed or not title or not gid:
            continue
        out.append({"id": f"amazon:{gid}", "source": "Amazon", "name": title, "size": 0, "last": 0, "minutes": 0, "cover": None,
                    "launch": f"amazon-games://play/{gid}", "exe": "", "cwd": folder or ""})
    return out


def game_library(custom, rom_dirs=()):
    games = []
    for fn in (steam_library, epic_library, gog_library, xbox_library, ea_library, ubisoft_library, battlenet_library, amazon_library,
               lambda: emulator_library(rom_dirs)):
        try:
            games += fn()
        except Exception:
            pass
    for c in custom:
        games.append({"id": f"custom:{c['exe'].lower()}", "source": "Added", "name": c["name"], "size": 0, "last": 0,
                      "minutes": 0, "cover": c.get("cover"), "launch": c["exe"], "exe": c["exe"], "cwd": os.path.dirname(c["exe"])})
    seen, unique = set(), []
    for g in games:
        if g["id"] not in seen:
            seen.add(g["id"])
            unique.append(g)
    return unique


def launch_game(g):
    target = g["launch"]
    try:
        if target.startswith("shell:"):
            subprocess.Popen(["explorer.exe", target])
        elif "://" in target:
            os.startfile(target)
        else:
            subprocess.Popen([target] + list(g.get("args") or []), cwd=g.get("cwd") or os.path.dirname(target) or None)
        return True
    except OSError:
        return False


# =====================================================================  focus mode

user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.GetPriorityClass.argtypes = [wintypes.HANDLE]
kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
kernel32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
try:
    _dwm = ctypes.WinDLL("dwmapi")
    _dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
except OSError:
    _dwm = None

SKIP_WINDOW_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW", "Windows.UI.Core.CoreWindow",
                       "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland", "XamlExplorerHostIslandWindow"}


def _pid_of(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _cloaked(hwnd):
    if not _dwm:
        return False
    v = wintypes.DWORD()
    return _dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(v), 4) == 0 and v.value != 0


def app_windows(exclude_pids):
    """Visible, normal top-level windows of other apps (what you'd see in Alt+Tab)."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd) or user32.GetWindow(hwnd, 4):  # GW_OWNER
                return True
            if user32.GetWindowTextLengthW(hwnd) == 0 or _cloaked(hwnd):
                return True
            if _get_ex(hwnd, -20) & 0x80:  # WS_EX_TOOLWINDOW
                return True
            cls = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, cls, 128)
            if cls.value in SKIP_WINDOW_CLASSES or _pid_of(hwnd) in exclude_pids:
                return True
            found.append(hwnd)
        except Exception:
            pass
        return True

    user32.EnumWindows(cb, 0)
    return found


def minimize_windows(exclude_pids):
    hwnds = app_windows(exclude_pids)
    for h in hwnds:
        user32.ShowWindowAsync(h, 7)  # SW_SHOWMINNOACTIVE
    return hwnds


def restore_windows(hwnds):
    for h in hwnds:
        try:
            if user32.IsIconic(h):
                user32.ShowWindowAsync(h, 4)  # SW_SHOWNOACTIVATE
        except Exception:
            pass


class POWER_THROTTLING(ctypes.Structure):
    _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]


FOCUS_KEEP_DEFAULT = ["discord.exe", "obs64.exe", "spotify.exe"]
_FOCUS_SKIP_PARTS = ("legion", "lenovo", "steam", "epicgames", "galaxy", "gog", "xbox", "gamebar", "rtss", "afterburner",
                     "radeon", "amdrs", "amdow", "nvcontainer", "nvidia", "handheldcompanion", "ramopt", "vanta", "presentmon",
                     "battleye", "easyanticheat", "vgc", "vgtray", "faceit")
_FOCUS_SKIP_NAMES = END_TASK_PROTECT | {"runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe",
                                        "shellexperiencehost.exe", "textinputhost.exe", "applicationframehost.exe",
                                        "systemsettings.exe", "conhost.exe", "dllhost.exe", "taskhostw.exe", "taskmgr.exe",
                                        "lockapp.exe", "securityhealthsystray.exe", "rtkauduservice64.exe", "audiodg.exe",
                                        "wudfhost.exe", "smartscreen.exe", "python.exe", "pythonw.exe", "msmpeng.exe",
                                        "mpdefendercoreservice.exe", "nissrv.exe", "sgrmbroker.exe"}


def _session(pid):
    s = wintypes.DWORD()
    return s.value if kernel32.ProcessIdToSessionId(pid, ctypes.byref(s)) else -1


def throttle_background(procs, keep_pids, keep_names):
    """Windows 11 'efficiency mode' (low priority + EcoQoS) for your own background apps. Returns what to undo."""
    mine = _session(os.getpid())
    keep = {n.lower() for n in keep_names}
    done = []
    for pid, name, _ in procs:
        low = name.lower()
        if pid in keep_pids or pid <= 4 or low in keep or low in _FOCUS_SKIP_NAMES or any(p in low for p in _FOCUS_SKIP_PARTS):
            continue
        if _session(pid) != mine:
            continue  # services and other users' processes stay untouched
        h = kernel32.OpenProcess(0x0200 | 0x1000, False, pid)  # SET_INFORMATION | QUERY_LIMITED
        if not h:
            continue
        try:
            prev = kernel32.GetPriorityClass(h)
            if prev in (0, 0x80, 0x100):  # unknown, HIGH, REALTIME: leave alone
                continue
            st = POWER_THROTTLING(1, 0x1, 0x1)  # PROCESS_POWER_THROTTLING_EXECUTION_SPEED on
            kernel32.SetProcessInformation(h, 4, ctypes.byref(st), ctypes.sizeof(st))
            if kernel32.SetPriorityClass(h, 0x40):  # IDLE_PRIORITY_CLASS, like Task Manager's efficiency mode
                done.append((pid, name, prev))
        finally:
            kernel32.CloseHandle(h)
    return done


def unthrottle(records):
    for pid, name, prev in records:
        h = kernel32.OpenProcess(0x0200 | 0x1000, False, pid)
        if not h:
            continue
        try:
            st = POWER_THROTTLING(1, 0, 0)  # let Windows decide again
            kernel32.SetProcessInformation(h, 4, ctypes.byref(st), ctypes.sizeof(st))
            kernel32.SetPriorityClass(h, prev or 0x20)
        finally:
            kernel32.CloseHandle(h)


def force_foreground(hwnd):
    """Bring a window to the front even when another app (a game) has focus."""
    user32.keybd_event(0x12, 0, 0, 0)  # a tap of Alt lifts Windows' focus-stealing lock
    user32.keybd_event(0x12, 0, 2, 0)
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.BringWindowToTop(hwnd)
    return bool(user32.SetForegroundWindow(hwnd))


# =====================================================================  AMD graphics settings (ADLX)
# AMD's official settings library ships with the Radeon driver as amdadlx64.dll. Interface layouts follow the
# public ADLX SDK headers (I3DSettings.h, I3DSettings1.h, IDisplays.h, IDisplaySettings.h, ISystem.h, ICollections.h).
# These settings are system-wide in ADLX, so Vanta applies a game's choices when it starts and restores them afterwards.

class _ADLXIntRange(ctypes.Structure):
    _fields_ = [("minValue", ctypes.c_int), ("maxValue", ctypes.c_int), ("step", ctypes.c_int)]


class _ADLXObj:
    def __init__(self, ptr):
        self.p = ptr

    def call(self, idx, restype, argtypes, *args):
        vt = ctypes.cast(self.p, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vt[idx])
        return fn(self.p, *args)

    def get(self, idx, *pre, types=()):
        out = ctypes.c_void_p()
        r = self.call(idx, ctypes.c_int, list(types) + [ctypes.POINTER(ctypes.c_void_p)], *pre, ctypes.byref(out))
        return _ADLXObj(out.value) if r == 0 and out.value else None

    def query(self, iid):
        out = ctypes.c_void_p()
        r = self.call(2, ctypes.c_int, [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)], iid, ctypes.byref(out))
        return _ADLXObj(out.value) if r == 0 and out.value else None

    def release(self):
        try:
            self.call(1, ctypes.c_long, [])
        except Exception:
            pass

    def get_bool(self, idx):
        v = ctypes.c_bool()
        return v.value if self.call(idx, ctypes.c_int, [ctypes.POINTER(ctypes.c_bool)], ctypes.byref(v)) == 0 else None

    def get_int(self, idx):
        v = ctypes.c_int()
        return v.value if self.call(idx, ctypes.c_int, [ctypes.POINTER(ctypes.c_int)], ctypes.byref(v)) == 0 else None

    def get_range(self, idx):
        r = _ADLXIntRange()
        ok = self.call(idx, ctypes.c_int, [ctypes.POINTER(_ADLXIntRange)], ctypes.byref(r)) == 0
        return (r.minValue, r.maxValue) if ok else None

    def set_bool(self, idx, v):
        return self.call(idx, ctypes.c_int, [ctypes.c_bool], bool(v)) == 0

    def set_int(self, idx, v):
        return self.call(idx, ctypes.c_int, [ctypes.c_int], int(v)) == 0


# key: (service, getter index on that service, needs "gpu"/"display"/None, method indices on the feature object)
# Feature object indices start at 3 (0-2 are Acquire/Release/QueryInterface).
AMD_FEATURES = {
    "antilag": ("3d", 3, "gpu", {"sup": 3, "get": 4, "set": 5}),
    "chill": ("3d", 4, "gpu", {"sup": 3, "get": 4, "set": 8, "range": 5, "min": (6, 9), "max": (7, 10)}),
    "boost": ("3d", 5, "gpu", {"sup": 3, "get": 4, "set": 7, "range": 5, "res": (6, 8)}),
    "ris": ("3d", 6, "gpu", {"sup": 3, "get": 4, "set": 7, "range": 5, "sharp": (6, 8)}),
    "esync": ("3d", 7, "gpu", {"sup": 3, "get": 4, "set": 5}),
    "frtc": ("3d", 9, "gpu", {"sup": 3, "get": 4, "set": 7, "range": 5, "fps": (6, 8)}),
    "rsr": ("3d", 14, None, {"sup": 3, "get": 4, "set": 5, "range": 6, "sharp": (7, 8)}),
    "afmf": ("3d1", 17, None, {"sup": 3, "get": 4, "set": 5}),
    "gpu_scaling": ("disp", 11, "display", {"sup": 3, "get": 4, "set": 5}),
    "integer": ("disp", 13, "display", {"sup": 3, "get": 4, "set": 5}),
}
AMD_LABELS = {
    "rsr": ("Radeon Super Resolution", "Upscales games running below the screen's resolution (fullscreen)"),
    "afmf": ("Fluid Motion Frames", "Driver frame generation: smoother motion, a little more lag"),
    "antilag": ("Radeon Anti-Lag", "Lower input lag when the GPU is the limit"),
    "boost": ("Radeon Boost", "Drops resolution during fast motion for more FPS"),
    "chill": ("Radeon Chill", "Lowers FPS when you're still: big battery saver"),
    "ris": ("Image Sharpening", "Crisper image, great with FSR/RSR"),
    "frtc": ("Frame rate cap", "Caps FPS to save power"),
    "esync": ("Enhanced Sync", "Less tearing without V-Sync's lag"),
    "integer": ("Integer scaling", "Pixel-perfect 1280×800 on the 2560×1600 screen"),
    "gpu_scaling": ("GPU scaling", "Lets the GPU scale lower resolutions (needed for integer scaling)"),
}
# parameter keys for each feature: (name, label, default)
AMD_PARAMS = {"rsr": [("sharp", "Sharpness", 75)], "ris": [("sharp", "Sharpness", 80)], "boost": [("res", "Lowest resolution %", 50)],
              "chill": [("min", "Chill min FPS", 30), ("max", "Chill max FPS", 60)], "frtc": [("fps", "Cap at FPS", 60)]}


class Adlx:
    """AMD's settings library. Starts lazily, retries if the driver wasn't ready (e.g. right after sign-in), and
    starts over if its objects go stale (after sleep or a driver update)."""

    def __init__(self):
        import threading
        self.lock = threading.RLock()
        self.ready = None  # None = not tried yet
        self.error = ""
        self.detail = ""
        self.failed_at = 0.0
        self.gpu_name = ""

    def _terminate(self):
        try:
            if getattr(self, "dll", None) and getattr(self, "sys", None):
                fn = getattr(self.dll, "ADLXTerminate", None)
                if fn:
                    fn()
        except Exception:
            pass
        self.sys = None
        self.ready = None

    def _gpu_at(self, lst, i):
        """The i-th GPU as a real IADLXGPU*: the typed At_GPUList (slot 11), else the generic At + QueryInterface."""
        g = lst.get(11, i, types=[ctypes.c_uint])
        if g:
            return g
        item = lst.get(7, i, types=[ctypes.c_uint])
        if not item:
            return None
        q = item.query("IADLXGPU")
        item.release()
        return q

    def _gpu_info(self, g):
        name, vendor = ctypes.c_char_p(), ctypes.c_char_p()
        try:
            g.call(7, ctypes.c_int, [ctypes.POINTER(ctypes.c_char_p)], ctypes.byref(name))
            g.call(3, ctypes.c_int, [ctypes.POINTER(ctypes.c_char_p)], ctypes.byref(vendor))
        except Exception:
            pass
        dec = lambda v: (v.value or b"").decode("utf-8", "replace")
        return dec(name), dec(vendor)

    def _init(self):
        if self.ready:
            return True
        if self.ready is False and time.time() - self.failed_at < 15:
            return False  # the driver may still be starting: try again in a bit
        self.ready = False
        self.failed_at = time.time()
        steps = []
        try:
            if not getattr(self, "dll", None):
                self.dll = ctypes.CDLL("amdadlx64.dll")
            dll = self.dll
            ver = ctypes.c_uint64()
            dll.ADLXQueryFullVersion.argtypes = [ctypes.POINTER(ctypes.c_uint64)]
            r = dll.ADLXQueryFullVersion(ctypes.byref(ver))
            steps.append(f"version {ver.value:#x} (r={r})")
            sysp = ctypes.c_void_p()
            for fname in ("ADLXInitialize", "ADLXInitializeWithIncompatibleDriver"):
                fn = getattr(dll, fname, None)
                if not fn:
                    continue
                fn.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)]
                r = fn(ver.value, ctypes.byref(sysp))
                steps.append(f"{fname} r={r}")
                if r in (0, 1, 2) and sysp.value:  # OK / already enabled / already initialized
                    break
            if not sysp.value:
                self.error = "AMD's settings library didn't start (try updating AMD Software)"
                self.detail = "; ".join(steps)
                return False
            self.sys = _ADLXObj(sysp.value)
            gpus = self.sys.get(1)
            n = gpus.call(3, ctypes.c_uint, []) if gpus else 0
            steps.append(f"{n} GPU(s)")
            self.svc = {"3d": self.sys.get(7)}
            self.svc["3d1"] = self.svc["3d"].query("IADLX3DSettingsServices1") if self.svc["3d"] else None
            self.svc["disp"] = self.sys.get(3)
            steps.append("3D settings " + ("ok" if self.svc["3d"] else "missing"))
            # pick the AMD GPU whose settings actually answer (normally the only one: the built-in Radeon)
            self.gpu = None
            for i in range(n or 0):
                g = self._gpu_at(gpus, i)
                if not g:
                    continue
                name, vendor = self._gpu_info(g)
                steps.append(f"GPU {i}: {name or '?'} [{vendor or '?'}]")
                probe = self.svc["3d"].get(3, g.p, types=[ctypes.c_void_p]) if self.svc["3d"] else None  # Anti-Lag
                if probe:
                    probe.release()
                    self.gpu, self.gpu_name = g, name
                    break
                if self.gpu is None and "1002" in (vendor or "1002"):
                    self.gpu, self.gpu_name = g, name  # keep as a fallback
            displays = self.svc["disp"].get(4) if self.svc["disp"] else None
            self.display = None
            if displays and displays.call(3, ctypes.c_uint, []):
                self.display = displays.get(11, 0, types=[ctypes.c_uint]) or displays.get(7, 0, types=[ctypes.c_uint])
            self.ready = bool(self.svc["3d"] and self.gpu)
            if not self.ready:
                self.error = ("Windows hasn't finished starting the AMD driver yet: Vanta will keep trying" if not n
                              else "AMD's settings library didn't accept the graphics chip")
        except OSError:
            self.error = "AMD Software (Adrenalin) isn't installed, so its settings library is missing"
        except Exception as ex:
            self.error = f"AMD settings unavailable ({ex})"
        self.detail = "; ".join(steps)
        return self.ready

    def restart(self):
        """Start over (after sleep, a driver update, or when every read fails)."""
        with self.lock:
            self._terminate()
            self.failed_at = 0.0
            return self._init()

    def available(self):
        with self.lock:
            return self._init()

    def _feature(self, key):
        svc, idx, needs, _ = AMD_FEATURES[key]
        s = self.svc.get(svc)
        if not s:
            return None
        if needs == "gpu":
            return s.get(idx, self.gpu.p, types=[ctypes.c_void_p])
        if needs == "display":
            return s.get(idx, self.display.p, types=[ctypes.c_void_p]) if self.display else None
        return s.get(idx)

    def read(self, _retry=True):
        """{feature: {"supported", "on", params..., "range"}} for everything this driver supports."""
        out = {}
        with self.lock:
            if not self._init():
                return out
            out = self._read()
            if not out and _retry:
                # every call failed: the objects are probably stale (sleep, driver update), so start over once
                if self.restart():
                    out = self._read()
                if not out and self.ready:
                    self.error = "The AMD driver answered but didn't report any settings: try updating AMD Software"
        return out

    def _read(self):
        out = {}
        if True:
            for key, (_, _, _, m) in AMD_FEATURES.items():
                try:
                    f = self._feature(key)
                    if not f:
                        continue
                    try:
                        if not f.get_bool(m["sup"]):
                            continue
                        st = {"on": f.get_bool(m["get"])}
                        for pname, _, _ in AMD_PARAMS.get(key, []):
                            st[pname] = f.get_int(m[pname][0])
                        if "range" in m:
                            st["range"] = f.get_range(m["range"])
                        out[key] = st
                    finally:
                        f.release()
                except Exception:
                    continue
        return out

    def snapshot(self, keys):
        """Current values for the given features, in apply() format, so they can be restored later."""
        cur = self.read()
        snap = {}
        for key in keys:
            if key in cur:
                snap[key] = bool(cur[key]["on"])
                for pname, _, _ in AMD_PARAMS.get(key, []):
                    if cur[key].get(pname) is not None:
                        snap[f"{key}_{pname}"] = cur[key][pname]
        return snap

    def apply(self, settings, _retry=True):
        """settings: {"rsr": True, "rsr_sharp": 75, "chill": False, ...}. Turns things off first to avoid conflicts."""
        done = []
        with self.lock:
            if not self._init():
                return done
            done = self._apply(settings)
            if not done and _retry and any(k in AMD_FEATURES for k in settings) and self.restart():
                done = self._apply(settings)  # stale objects after sleep / driver update: start over once
        return done

    def _apply(self, settings):
        done = []
        if True:
            keys = [k for k in AMD_FEATURES if k in settings]
            keys.sort(key=lambda k: bool(settings[k]))  # offs first (Chill vs frame cap, RSR vs integer scaling...)
            for key in keys:
                m = AMD_FEATURES[key][3]
                try:
                    f = self._feature(key)
                    if not f:
                        continue
                    try:
                        if not f.get_bool(m["sup"]):
                            continue
                        on = bool(settings[key])
                        if on:  # parameters first, then switch on
                            for pname, _, _ in AMD_PARAMS.get(key, []):
                                v = settings.get(f"{key}_{pname}")
                                if v is not None:
                                    f.set_int(m[pname][1], v)
                        if f.set_bool(m["set"], on):
                            done.append(f"{AMD_LABELS[key][0]} {'on' if on else 'off'}")
                    finally:
                        f.release()
                except Exception:
                    continue
        return done


ADLX = Adlx()


# =====================================================================  Legion Go game presets
# Each preset cites the article or test it comes from. tdp/hz/res/amd are what Vanta can set for you;
# notes are the in-game settings to pick yourself.
# Recommended presets, per generation. "go1" = Legion Go (Ryzen Z1 Extreme, 2560×1600 IPS, up to 30 W);
# "go2" = Legion Go 2 (Ryzen Z2 / Z2 Extreme, 1920×1200 OLED, 15–35 W). A game tested on only one generation is still
# offered on the other, labelled with the generation it was tested on.
_SWB = ("Switchblade Gaming (tested on a Z1 Extreme Legion Go)", "https://www.switchbladegaming.com/game-settings/best-legion-go-games-2026/")
_NBC = ("Notebookcheck (ETA Prime, Legion Go 2)",
        "https://www.notebookcheck.net/This-is-how-the-more-affordable-Lenovo-Legion-Go-2-Ryzen-Z2-handles-Cyberpunk-2077-Elden-Ring-and-Borderlands-4.1159698.0.html")
GAME_PRESETS = [
    {"id": "cyberpunk", "match": ["cyberpunk 2077"], "title": "Cyberpunk 2077",
     "go1": {"tdp": 28, "notes": ["800p in the game's display settings", "25–30 W is the sweet spot", "Expect 45–60 FPS"], "source": _SWB},
     "go2": {"tdp": 25, "amd": {"antilag": True},
             "notes": ["1920×1200 in the game's display settings", "FSR Frame Generation on", "Reported about 84 FPS at 25 W"],
             "source": _NBC}},
    {"id": "eldenring", "match": ["elden ring"], "title": "Elden Ring",
     "go2": {"tdp": 25, "hz": 60, "notes": ["1600×1000, Medium preset", "Reported 57–59 FPS at 25 W",
                                             "The game is capped at 60 FPS, so Vanta sets 60 Hz to save power"], "source": _NBC}},
    {"id": "darksouls3", "match": ["dark souls iii", "dark souls 3", "darksouls iii"], "title": "Dark Souls III",
     "go1": {"tdp": 30, "hz": 60,
             "notes": ["2560×1600 with a mix of Low–High settings, as tested at 30 W",
                       "The game is capped at 60 FPS, so Vanta sets 60 Hz to save power",
                       "On battery: try 1280×800 in game, then Quick settings › Find my best TDP for the lowest steady wattage"],
             "source": ("Legion Go gameplay test (YouTube)", "https://www.youtube.com/watch?v=VPIUOBifkjw")}},
    {"id": "forza5", "match": ["forza horizon 5"], "title": "Forza Horizon 5",
     "go1": {"tdp": 20, "notes": ["1200p in game", "18–22 W", "Expect 50–60 FPS"], "source": _SWB},
     "go2": {"tdp": 16, "notes": ["1200p, Medium preset", "Reported about 73 FPS at 16 W"], "source": _NBC}},
    {"id": "hades", "match": ["hades"], "title": "Hades",
     "go1": {"tdp": 10, "notes": ["Native 1600p is fine", "9–12 W", "100+ FPS"], "source": _SWB}},
    {"id": "bg3", "match": ["baldur's gate 3", "baldurs gate 3"], "title": "Baldur's Gate 3",
     "go1": {"tdp": 30, "notes": ["800p in game", "FSR 2 on Quality", "Recommended 28–35 W; the original Legion Go tops out at 30 W",
                                  "Expect 30–40 FPS, lower in Act 3"], "source": _SWB}},
    {"id": "gowr", "match": ["god of war ragnar", "god of war: ragnar"], "title": "God of War Ragnarök",
     "go1": {"notes": ["Low/Medium settings, 800p", "Frame Generation off, V-Sync off, frame limit off",
                       "The tester got about 57 FPS at 848×524"],
             "source": ("Clawsomegamer", "https://clawsomegamer.com/best-god-of-war-ragnarok-settings-on-legion-go")}},
    {"id": "helldivers2", "match": ["helldivers 2", "helldivers™ 2"], "title": "Helldivers 2",
     "go1": {"tdp": 25, "hz": 144, "amd": {"integer": False},
             "notes": ["All graphics Low, Anti-aliasing Off, Async Compute Off", "800p in game and in Windows",
                       "Source used 25 W with 32 W boost / 41 W peak (Vanta uses a smaller boost on top)"],
             "source": ("Lenovo Legion Go community", "https://gaming.lenovo.com/legion-go/post/helldivers-2---game-settings-3gfOeVzPhOiqA8S")}},
    {"id": "avowed", "match": ["avowed"], "title": "Avowed",
     "go1": {"tdp": 28, "amd": {"afmf": True, "chill": True, "chill_min": 45, "chill_max": 50, "gpu_scaling": True, "integer": True},
             "notes": ["800p with FSR 3 Quality, or TSR at 67%", "Textures Medium, everything else Low"],
             "source": ("Clawsomegamer", "https://clawsomegamer.com/avowed-best-settings-on-legion-go")}},
    {"id": "rivals", "match": ["marvel rivals"], "title": "Marvel Rivals",
     "go1": {"notes": ["800p in game", "1200p dips into the 30s–40s, so it isn't recommended"],
             "source": ("Clawsomegamer", "https://clawsomegamer.com/legion-go-best-marvel-rivals-settings")}},
    {"id": "silenthillf", "match": ["silent hill f"], "title": "Silent Hill f",
     "go1": {"tdp": 30, "notes": ["1920×1200, Fullscreen", "Frame rate limit 30, V-Sync off", "Mix of Low/Medium/High for a steady 30 FPS"],
             "source": ("Deltia's Gaming", "https://deltiasgaming.com/silent-hill-f-best-settings-for-rog-ally-lenovo-legion-and-msi-claw")}},
    {"id": "aomr", "match": ["age of mythology"], "title": "Age of Mythology: Retold",
     "go1": {"notes": ["Borderless, 1280×720", "Brightness around 50–60% for longer battery"],
             "source": ("Clawsomegamer", "https://clawsomegamer.com/best-age-of-mythology-retold-settings-for-legion-go")}},
    {"id": "legohorizon", "match": ["lego horizon"], "title": "LEGO Horizon Adventures",
     "go1": {"tdp": 25, "notes": ["800p, TSR 50–70%", "High settings at 30 FPS", "Newer AMD drivers reduce stutter"],
             "source": ("Clawsomegamer", "https://clawsomegamer.com/lego-horizon-adventures-best-legion-go-settings-for-high-fps")}},
    {"id": "witcher3", "match": ["witcher 3"], "title": "The Witcher 3",
     "go1": {"tdp": 15, "notes": ["Medium-High settings with FSR", "At 15 W reviewers saw 2.5–4 h of battery"],
             "source": ("HotHardware review / Evetech", "https://hothardware.com/reviews/lenovo-legion-go-review?page=2")},
     "go2": {"tdp": 25, "notes": ["1200p, Medium, FSR on", "HDR looks great on the OLED"],
             "source": ("NoobFeed (Legion Go 2)", "https://noobfeed.com/articles/steamos-lenovo-legion-go2-handheld-gaming")}},
]

GENERAL_PRESETS = [
    {"id": "g_battery", "title": "Battery stretch",
     "go1": {"tdp": 10, "hz": 60, "amd": {"frtc": True, "frtc_fps": 30, "chill": False},
             "notes": ["Cap at 30 FPS, 8–10 W, 800p", "Screen brightness around 40%", "FSR 3 on Quality if the game has it"],
             "source": ("Evetech battery tips", "https://evezone.evetech.co.za/quick-bytes/legion-go-battery-life-tips-how-to-get-more-gaming-time")},
     "go2": {"tdp": 10, "hz": 60, "amd": {"frtc": True, "frtc_fps": 30, "chill": False},
             "notes": ["Cap at 30 FPS, 8–10 W", "Dark scenes cost less power on the OLED", "FSR 3 on Quality if the game has it"],
             "source": ("Evetech battery tips", "https://evezone.evetech.co.za/quick-bytes/legion-go-battery-life-tips-how-to-get-more-gaming-time")}},
    {"id": "g_balanced", "title": "Plugged-in balance",
     "go1": {"tdp": 25, "amd": {"rsr": True, "rsr_sharp": 75},
             "notes": ["20–25 W while plugged in", "Render at 1080p/1200p and let RSR upscale to 1600p"],
             "source": ("Evetech setup guide", "https://evezone.evetech.co.za/quick-bytes/how-to-configure-lenovo-legion-go-for-optimal-performance-in-2026")},
     "go2": {"tdp": 25, "amd": {"rsr": True, "rsr_sharp": 75},
             "notes": ["25 W while plugged in", "Render at 1600×1000 or 1440×900 and let RSR upscale to the 1200p screen"],
             "source": ("NoobFeed (Legion Go 2 tests at 1600×1000, 25 W)", "https://www.noobfeed.com/hardware/legion-go-2-performance-showcase")}},
    {"id": "g_800p_rsr", "title": "800p + RSR",
     "go1": {"amd": {"rsr": True, "rsr_sharp": 75, "integer": False},
             "notes": ["Set the game to 1280×800 fullscreen first: it's the biggest FPS win", "RSR upscales back to a clean image"],
             "source": ("Switchblade Gaming", "https://www.switchbladegaming.com/game-settings/best-legion-go/")},
     "go2": {"amd": {"rsr": True, "rsr_sharp": 75, "integer": False},
             "notes": ["Set the game to 1280×800 fullscreen first", "RSR upscales it to the 1920×1200 screen"],
             "source": ("Switchblade Gaming", "https://www.switchbladegaming.com/game-settings/best-legion-go/")}},
    {"id": "g_integer", "title": "Pixel-perfect half res",
     "go1": {"amd": {"gpu_scaling": True, "integer": True, "rsr": False},
             "notes": ["Run the game at 1280×800: exactly half of 2560×1600, so integer scaling keeps it sharp"],
             "source": ("r/LegionGo setup guide", "https://www.reddit.com/r/LegionGo/comments/17xgugu/legion_go_first_day_setup_guide/")},
     "go2": {"amd": {"gpu_scaling": True, "integer": True, "rsr": False},
             "notes": ["Run the game at 960×600: exactly half of the 1920×1200 screen, so integer scaling keeps it sharp",
                       "Best for older or pixel-art games"],
             "source": ("r/LegionGo setup guide", "https://www.reddit.com/r/LegionGo/comments/17xgugu/legion_go_first_day_setup_guide/")}},
]

GENS = {"go1": "Gen 1 · Legion Go", "go2": "Gen 2 · Legion Go 2"}


def preset_variant(p, gen):
    """The preset as it applies to one generation; 'tested' says which generation its numbers come from."""
    if not p:
        return None
    other = "go2" if gen == "go1" else "go1"
    v = p.get(gen) or p.get(other)
    if not v:
        return None
    return {"id": p["id"], "title": p["title"], "match": p.get("match", []), **v, "gen": gen,
            "tested": gen if p.get(gen) else other}


def general_presets(gen):
    return [preset_variant(p, gen) for p in GENERAL_PRESETS]


def preset_by_id(pid, gen):
    return preset_variant(next((x for x in GAME_PRESETS + GENERAL_PRESETS if x["id"] == pid), None), gen)


def _norm(name):
    return re.sub(r"[^a-z0-9' ]+", " ", name.lower().replace("™", "").replace("®", "")).strip()


def find_preset(game_name, gen="go1"):
    n = _norm(game_name)
    hits = [p for p in GAME_PRESETS if any(_norm(m) in n for m in p["match"])]
    # "hades" also matches "hades ii": prefer the longest (most specific) match
    hits.sort(key=lambda p: -max(len(_norm(m)) for m in p["match"]))
    for p in hits:
        if p["id"] == "hades" and "hadesii" in n.replace(" ", ""):
            continue
        return preset_variant(p, gen)
    return None


# =====================================================================  Legion Go controllers: Legion L / R buttons and lights
# The controllers report their extra buttons on a vendor HID interface (usage page 0xFFA0), report 0x74.
# Byte 18: 0x80 = Legion L, 0x40 = Legion R (bit layout as documented by the open-source Handheld Daemon project).
# Without Legion Space nothing listens to these buttons, so Vanta does.
LEGION_VID = 0x17EF
LEGION_PIDS = {0x6182, 0x6183, 0x6184, 0x6185, 0x61EB, 0x61EC, 0x61ED, 0x61EE}
# Byte 20 of the same report: the back buttons (Y1/Y2 left, Y3/M2/M3 right), per the Handheld Daemon bit map.
BACK_BUTTONS = {"y1": 0x80, "y2": 0x40, "y3": 0x20, "m2": 0x08, "m3": 0x04}
# Gyro in the same report (signed 16-bit big-endian, rad/s after scaling), per the Handheld Daemon map:
# (byte offset, scale) for pitch (x), yaw (y), roll (z).
# Bytes 12/13: lowest bit set = left/right controller detached from the tablet (Handheld Daemon's
# is_attached_left/right, which reads bit 7 counted from the top and flips it).
ATTACH_BYTES = {"left": 12, "right": 13}
GYRO_LAYOUT = {"right": [(56, -0.001065), (58, -0.001065), (54, 0.001065)],
               "left": [(41, -0.001065), (45, -0.001065), (43, -0.001065)]}


def gyro_packets(side, on):
    rc = 0x03 if side == "left" else 0x04
    if on:  # turn the IMU on, then switch to the high-rate report
        return [[0x05, 0x06, 0x6A, 0x02, rc, 0x01, 0x01], [0x05, 0x06, 0x6A, 0x07, rc, 0x02, 0x01]]
    return [[0x05, 0x06, 0x6A, 0x07, rc, 0x01, 0x01]]  # back to the normal report


# Controllers on Lenovo's 2025 firmware (PIDs 0x61EB-0x61EE, the "Legion Go 2" protocol), as measured on a Legion Go on
# Windows with Vanta's button test: the 0xFFA0 interface sends report 0x04 instead of 0x74, with the same layout two bytes
# earlier (sticks at 12-15 instead of 14-17, battery at 3/5 instead of 5/7, Legion L/R at byte 16: 0x80 / 0x40 instead of
# byte 18). Vanta moves it back into the documented layout, so every reading below works unchanged.
NEW_FW_PIDS = {0x61EB, 0x61EC, 0x61ED, 0x61EE}
DINPUT_PIDS = {0x6183, 0x6184, 0x61EC, 0x61ED}  # DirectInput / dual DirectInput: Windows' Xbox controller support doesn't see them

# Gamepad mode on the 2025 firmware, from the Linux kernel's hid-lenovo-go driver (mcu_property_out): output report 0x05,
# MCU_CONFIG_DATA (0x00), SET_FEATURE_STATUS (0x04), FEATURE_GAMEPAD_MODE (0x0e), device UNSPECIFIED (0x00), value
# 1 = xinput / 2 = dinput, padded to the 64-byte packet.
XINPUT_MODE_PACKET = [0x05, 0x00, 0x04, 0x0E, 0x00, 0x01]


def restore_xinput_mode():
    """Switch Legion Go controllers on the 2025 firmware back to XInput (Xbox) mode. Returns (ok, message)."""
    try:
        import hid
    except ImportError:
        return False, "hidapi is missing"
    for d in hid.enumerate(LEGION_VID, 0):
        if d.get("product_id") in NEW_FW_PIDS and d.get("usage_page") == 0xFFA0 and d.get("usage") in (1, 0):
            dev = hid.device()
            try:
                dev.open_path(d["path"])
                pkt = XINPUT_MODE_PACKET + [0] * (64 - len(XINPUT_MODE_PACKET))
                n = dev.write(bytes(pkt))
                if n is None or n < 0:
                    n = dev.write(bytes(pkt + [0]))  # some Windows drivers want one more byte
                if n is None or n < 0:
                    return False, "The controller didn't accept the command"
                return True, "Sent: the controllers should reconnect in Xbox mode in a few seconds"
            except Exception as ex:
                return False, f"Couldn't reach the controller ({str(ex)[:60]})"
            finally:
                try:
                    dev.close()
                except Exception:
                    pass
    return False, "No Legion controller on the 2025 firmware found"


# The motion rates come little-endian on that firmware (big-endian in the documented report): measured on a Legion Go,
# right controller turned right -> +204 at byte 56 (yaw), tilted up -> -266 at byte 54 (pitch), at rest -2/-46/-6.
NEW_FW_SWAP = (41, 43, 45, 54, 56, 58)  # gyro fields, as positions in the documented report


# The documented report's gamepad bits (Handheld Daemon's map, counted from the top bit) as XInput wButtons.
_PAD_BITS = [(18, 0x08, 0x0001), (18, 0x04, 0x0002), (18, 0x02, 0x0004), (18, 0x01, 0x0008),   # d-pad
             (20, 0x01, 0x0010), (20, 0x02, 0x0020), (18, 0x20, 0x0040), (18, 0x10, 0x0080),   # start, view, L3, R3
             (19, 0x08, 0x0100), (19, 0x02, 0x0200),                                            # LB, RB
             (19, 0x80, 0x1000), (19, 0x40, 0x2000), (19, 0x20, 0x4000), (19, 0x10, 0x8000)]    # A, B, X, Y


def pad_bits(d):
    """(wButtons, left stick x, left stick y (-1…1, up is negative), LT, RT) from a report in the documented layout."""
    b = 0
    for i, mask, xb in _PAD_BITS:
        if d[i] & mask:
            b |= xb
    return b, (d[14] - 128) / 128, (d[15] - 128) / 128, d[23], d[22]


def from_new_firmware(data):
    """A 2025-firmware report 0x04, laid out as the documented report 0x74."""
    out = [0x74, 0x00, 0x00] + list(data[1:])
    for i in NEW_FW_SWAP:
        if i + 1 < len(out):
            out[i], out[i + 1] = out[i + 1], out[i]
    return out


def normalize_bmap(m):
    """Learned or built-in button maps, old formats included -> {"rid", "l", "r", "key_l", "key_r", "pairs", ...}."""
    if not m:
        return None
    m = dict(m)
    if m.get("kind") == "keys":  # 8.4.3: both buttons as keys
        m.update(key_l=m.get("l"), key_r=m.get("r"), l=None, r=None, rid=None)
    m.setdefault("key_l", None)
    m.setdefault("key_r", None)
    m.setdefault("pairs", False)
    m.setdefault("rid", None)
    return m


class LegionButtons:
    """Reads the Legion L/R and back buttons from the controller. `bmap` (from HidProbe, or the built-in map for the
    2025 firmware) says where Legion L and R are found when the controller differs from the documented layout."""

    def __init__(self, on_event, bmap=None):
        import threading
        self.bmap = normalize_bmap(bmap)
        self.reports = 0          # reports read (shown in the button test)
        self.seen_legion = False  # a Legion press actually arrived
        self.seen = set()         # which of legion_l / legion_r have arrived
        self.pid = None
        self.on_event = on_event  # called from a background thread with "legion_l"/"legion_r" (+ "_hold")
        self.running = False
        self.connected = False
        self.dev = None
        self.error = ""
        self.lock = threading.Lock()
        self.thread = None
        self.keys = None
        self.back = {}
        self.on_gyro = None
        self.gyro_side = "right"
        self.attached = None  # {"left": bool, "right": bool} once known
        self._attach_seen = None
        self._attach_since = 0.0
        self._kpress = {}     # name -> press time (or -1 after its hold fired)
        self._kpend = None    # a swallowed key-down we haven't decided about yet: (vk, time)
        self._kcombo = False
        self.tap_log = []
        self.gmap = None  # learned motion layout (HidProbe.analyse_motion)
        self.pad_state = None  # (time, buttons, lx, ly, lt, rt) from the controller's own report, XInput-style bits

    def start(self):
        import threading
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self._start_keys()

    def _start_keys(self):
        m = self.bmap
        if self.keys or not m or not (m.get("key_l") or m.get("key_r")):
            return
        self._keymap = {vk: name for vk, name in ((m.get("key_l"), "legion_l"), (m.get("key_r"), "legion_r")) if vk}
        self.keys = KeyWatcher(self._on_key)
        self.keys.start()

    # --- keystrokes from the controller (see NEW_FW_MAP)
    def _press(self, name, now):
        self._kpress[name] = now
        self.seen_legion = True
        self.seen.add(name)

        def hold(t=now):
            if self._kpress.get(name) == t:
                self._kpress[name] = -1.0
                self.on_event(name + "_hold")
        import threading as _th
        _th.Timer(0.8, hold).start()

    def _release(self, name):
        t = self._kpress.pop(name, None)
        if t is not None and t > 0:
            self.on_event(name)

    def _tap(self, name, now):
        """One whole tap of the key. With "pairs", a tap marks the press and the next one the release."""
        self.tap_log = (self.tap_log + [round(now, 2)])[-6:]
        if not self.bmap.get("pairs"):
            self._press(name, now)
            self._release(name)
            return
        t = self._kpress.get(name)
        if t is None or (t > 0 and now - t > 10):  # not pressed (or a release went missing): this is a press
            self._press(name, now)
        else:
            self._release(name)

    def _on_key(self, vk, scan, down, injected):
        name = self._keymap.get(vk)
        if injected:
            return False
        now = time.time()
        if name:
            if not self.bmap.get("pairs"):  # a key that is down while the button is down
                if down and name not in self._kpress:
                    self._press(name, now)
                elif not down:
                    self._release(name)
                return True
            # a quick tap from the controller: hold the key-down back until we know it's a lone tap,
            # so Windows-key shortcuts from a real keyboard (Win+E…) still work
            if down:
                if self._kpend is None:
                    self._kpend, self._kcombo = (vk, now), False
                return not self._kcombo
            if self._kpend and self._kpend[0] == vk:
                combo = self._kcombo
                self._kpend, self._kcombo = None, False
                if combo:
                    return False  # it was a shortcut: let the key-up through
                self._tap(name, now)
                return True
            return False
        if down and self._kpend and not self._kcombo:
            # another key while ours is down: it's a shortcut from a keyboard, so give Windows the key-down we held back
            self._kcombo = True
            try:
                u32 = ctypes.WinDLL("user32")
                u32.keybd_event(self._kpend[0], 0, 0x0001, 0)  # KEYEVENTF_EXTENDEDKEY (the Windows key is extended)
            except Exception:
                pass
        return False

    def stop(self):
        self.running = False
        if getattr(self, "keys", None):
            self.keys.stop()

    def _open(self):
        import hid
        m = self.bmap if self.bmap and self.bmap.get("vid") else None
        for d in hid.enumerate(m["vid"] if m else LEGION_VID, 0):
            if m:
                ok = (d.get("product_id") == m["pid"] and d.get("usage_page") == m["usage_page"] and d.get("usage") == m["usage"]
                      and d.get("interface_number", -1) == m.get("interface", d.get("interface_number", -1)))
            else:
                ok = d.get("product_id") in LEGION_PIDS and d.get("usage_page") == 0xFFA0 and d.get("usage") in (1, 0)
            if ok:
                dev = hid.device()
                dev.open_path(d["path"])
                self.pid = d.get("product_id")
                return dev
        return None

    def _loop(self):
        try:
            import hid  # noqa: F401
        except ImportError:
            self.error = "hidapi is missing"
            self.running = False
            return
        down = {"legion_l": None, "legion_r": None}
        while self.running:
            if not self.dev:
                try:
                    with self.lock:
                        self.dev = self._open()
                    self.connected = bool(self.dev)
                except Exception as ex:
                    self.dev, self.connected, self.error = None, False, str(ex)
                if not self.dev:
                    time.sleep(2.0)
                    continue
            try:
                data = self.dev.read(64, 250)
            except Exception:
                with self.lock:
                    try:
                        self.dev.close()
                    except Exception:
                        pass
                    self.dev = None
                self.connected = False
                continue
            now = time.time()
            if data:
                self.reports += 1
                self.last_raw = list(data[:32])
                g = self.gmap
                if g and self.on_gyro and data[0] == g["rid"]:
                    try:
                        vals = []
                        for key in ("pitch", "yaw"):
                            b, e, sign = g[key]
                            vals.append(struct.unpack(e + "h", bytes(data[b:b + 2]))[0] * 0.001065 * sign)
                        t20 = from_new_firmware(data) if data[0] == 0x04 and self.pid in NEW_FW_PIDS else data
                        lt, rt = (t20[23], t20[22]) if len(t20) > 23 else (0, 0)
                        self.on_gyro(vals[0], -vals[1], 0.0, lt, rt, time.perf_counter())
                    except Exception:
                        pass
                if data[0] == 0x04 and len(data) >= 40 and self.pid in NEW_FW_PIDS and not self.bmap:
                    data = from_new_firmware(data)
            m = self.bmap
            if m and data and m.get("rid") is not None and data[0] == m["rid"]:
                state = {}
                for name, key in (("legion_l", "l"), ("legion_r", "r")):
                    if m.get(key):
                        i, mask, idle = m[key]
                        state[name] = len(data) > i and bool(data[i] & mask) != bool(idle)
                if state:
                    self._edges(state, down, now)
                if data[0] != 0x74:
                    continue  # the learned report only carries the Legion buttons
            if data and len(data) > 23 and data[0] == 0x74:
                self.pad_state = (now,) + pad_bits(data)
            if data and len(data) >= 60 and data[0] == 0x74 and self.on_gyro and not self.gmap:
                o = GYRO_LAYOUT[self.gyro_side]
                g = [struct.unpack(">h", bytes(data[i:i + 2]))[0] * sc for i, sc in o]
                try:
                    self.on_gyro(g[0], g[1], g[2], data[23], data[22], time.perf_counter())  # pitch, yaw, roll (rad/s), LT, RT
                except Exception:
                    pass
            if data and len(data) > 13 and data[0] == 0x74:
                att = {side: not (data[i] & 0x01) for side, i in ATTACH_BYTES.items()}
                if att != self._attach_seen:
                    self._attach_seen, self._attach_since = att, now
                elif att != self.attached and now - self._attach_since >= 1.0:  # steady for a second
                    first = self.attached is None
                    self.attached = att
                    if not first:
                        self.on_event("attach_change")
            if data and len(data) > 20 and data[0] == 0x74:
                back = data[20]
                for name, bit in BACK_BUTTONS.items():  # back buttons: report presses and releases (for held keys)
                    on = bool(back & bit)
                    if on != self.back.get(name, False):
                        self.back[name] = on
                        self.on_event(f"back_{name}_{'down' if on else 'up'}")
            if self.bmap:
                if not data:
                    self._edges({k: down[k] is not None for k in down if self.bmap.get(k[-1:])}, down, now)
                continue  # Legion L/R come from the map above
            if data and len(data) > 18 and data[0] == 0x74:
                state = {"legion_l": bool(data[18] & 0x80), "legion_r": bool(data[18] & 0x40)}
            elif data:
                continue
            else:
                state = {k: down[k] is not None for k in down}  # no report: keep state, check holds
            self._edges(state, down, now)

    def _edges(self, state, down, now):
        for name, pressed in state.items():
            if pressed and down[name] is None:
                down[name] = now
                self.seen_legion = True
                self.seen.add(name)
            elif pressed and down[name] and down[name] > 0 and now - down[name] >= 0.8:
                down[name] = -1.0  # hold fired; wait for release
                self.on_event(name + "_hold")
            elif not pressed and down[name] is not None:
                if down[name] > 0:
                    self.on_event(name)
                down[name] = None

    def write(self, packets):
        if self.pid in NEW_FW_PIDS:
            # these commands were written for the original firmware: on the 2025 firmware they can change the
            # controller's mode (one switched a Legion Go into dual DirectInput). Only read from it.
            return False
        with self.lock:
            if not self.dev:
                return False
            try:
                for p in packets:
                    self.dev.write(bytes(p))
                    time.sleep(0.03)
                return True
            except Exception:
                return False


class KeyWatcher:
    """A low-level keyboard hook on its own thread. on_key(vk, scan, down, injected) -> True swallows the key."""

    def __init__(self, on_key):
        self.on_key = on_key
        self.thread_id = None
        self.running = False
        self._proc = None

    def start(self):
        import threading
        self.running = True
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _run(self):
        class KBD(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
        LRESULT = ctypes.c_ssize_t
        HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        u32.CallNextHookEx.restype = LRESULT
        u32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        u32.SetWindowsHookExW.restype = ctypes.c_void_p

        def proc(code, wparam, lparam):
            if code == 0:
                k = ctypes.cast(lparam, ctypes.POINTER(KBD)).contents
                down = wparam in (0x100, 0x104)  # WM_KEYDOWN, WM_SYSKEYDOWN
                try:
                    if self.on_key(int(k.vkCode), int(k.scanCode), down, bool(k.flags & 0x10)):
                        return 1
                except Exception:
                    pass
            return u32.CallNextHookEx(None, code, wparam, lparam)
        self._proc = HOOKPROC(proc)
        self.thread_id = kernel32.GetCurrentThreadId()
        hook = u32.SetWindowsHookExW(13, self._proc, None, 0)  # WH_KEYBOARD_LL
        if not hook:
            self.running = False
            return
        msg = wintypes.MSG()
        while self.running and u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        u32.UnhookWindowsHookEx(ctypes.c_void_p(hook))

    def stop(self):
        self.running = False
        if self.thread_id:
            ctypes.WinDLL("user32").PostThreadMessageW(self.thread_id, 0x0012, 0, 0)  # WM_QUIT


class HidProbe:
    """Finds where a controller reports a button, by watching it. Phases: rest, hold Legion L, let go, hold Legion R,
    let go. Every HID collection of the Legion controllers is read, and keystrokes are watched too (newer firmware
    can send the Legion buttons as keys). A bit or key that stays changed for the whole of one hold, and nowhere
    else, is that button. Nothing is sent to the controller."""
    VIDS = (LEGION_VID, 0x1A86)  # Lenovo, and the Legion Go S controller's vendor

    def __init__(self):
        self.phase = "idle"
        self.devices = []
        self.running = False
        self.result = None
        self.samples = {}     # phase -> number of samples
        self.diff = {}        # phase -> {(dev, rid, byte, mask): samples where the bit differs from rest}
        self.base = {}        # (dev, rid) -> report at the end of the rest phase
        self.snap = {}        # phase -> {(dev, rid): report in the middle of the phase}
        self.keys = {}        # phase -> {vk: seconds held}
        self.key_log = []     # (phase, vk, scan, down, injected, seconds since the start)
        self._keydown = {}
        self.taps = {}        # phase -> {vk: key-downs}
        self.series = {}      # motion phase -> {(dev, rid): [report, …]} sampled every 10 ms
        self.t_start = time.time()

    def _on_key(self, vk, scan, down, injected):
        ph = self.phase
        now = time.time()
        if len(self.key_log) < 60:
            self.key_log.append((ph, vk, scan, down, injected, round(now - self.t_start, 2)))
        if down and vk not in self._keydown:
            d = self.taps.setdefault(ph, {})
            d[vk] = d.get(vk, 0) + 1
        if down and vk not in self._keydown:
            self._keydown[vk] = (now, ph)
        elif not down and vk in self._keydown:
            t0, ph0 = self._keydown.pop(vk)
            d = self.keys.setdefault(ph0, {})
            d[vk] = d.get(vk, 0.0) + (now - t0) + 0.05
        return False

    def run(self, phases):
        """phases: [(name, seconds)]; the button phases are named "l" and "r"."""
        import hid
        self.running = True
        self.t_start = time.time()
        devs = []
        kw = KeyWatcher(self._on_key)
        try:
            kw.start()
        except Exception:
            kw = None
        try:
            for vid in self.VIDS:
                for d in hid.enumerate(vid, 0):
                    if vid == 0x1A86 and d.get("product_id") not in (0xE310, 0xE311):
                        continue
                    info = {"vid": vid, "pid": d.get("product_id"), "usage_page": d.get("usage_page"), "usage": d.get("usage"),
                            "interface": d.get("interface_number"), "opened": False, "error": "", "reports": 0, "rids": {}}
                    dev = None
                    try:
                        dev = hid.device()
                        dev.open_path(d["path"])
                        dev.set_nonblocking(1)
                        info["opened"] = True
                    except Exception as ex:
                        info["error"] = str(ex)[:60] or "can't open"
                        dev = None
                    self.devices.append(info)
                    devs.append(dev)
            latest = {}
            for name, secs in phases:
                self.phase = name
                t0 = time.time()
                end = t0 + secs
                settle = t0 + (0.8 if name in ("l", "r") else 0.3)  # time to react to the prompt
                mid_done = False
                next_sample = t0
                while time.time() < end and self.running:
                    got = False
                    for i, dev in enumerate(devs):
                        if dev is None:
                            continue
                        for _ in range(16):
                            try:
                                data = dev.read(128)
                            except Exception:
                                data = None
                            if not data:
                                break
                            got = True
                            info = self.devices[i]
                            info["reports"] += 1
                            info["rids"][data[0]] = info["rids"].get(data[0], 0) + 1
                            latest[(i, data[0])] = list(data)
                    now = time.time()
                    if now >= next_sample and now >= settle:
                        next_sample = now + 0.01
                        n = self.samples[name] = self.samples.get(name, 0) + 1
                        if name in ("still", "turn", "tilt"):
                            ser = self.series.setdefault(name, {})
                            for k_, data in latest.items():
                                if self.devices[k_[0]]["usage_page"] >= 0xFF00:
                                    ser.setdefault(k_, []).append(list(data))
                        elif name == "idle":
                            self.base = {k_: list(v) for k_, v in latest.items()}
                        else:
                            dd = self.diff.setdefault(name, {})
                            for k_, data in latest.items():
                                b0 = self.base.get(k_)
                                if not b0 or len(b0) != len(data):
                                    continue
                                for b in range(1, len(data)):
                                    x = b0[b] ^ data[b]
                                    while x:
                                        mask = x & -x
                                        x ^= mask
                                        kk = (k_[0], k_[1], b, mask)
                                        dd[kk] = dd.get(kk, 0) + 1
                        if not mid_done and now >= (t0 + end) / 2:
                            mid_done = True
                            self.snap[name] = {k_: list(v) for k_, v in latest.items()}
                    if not got:
                        time.sleep(0.003)
        finally:
            for dev in devs:
                try:
                    dev and dev.close()
                except Exception:
                    pass
            if kw:
                kw.stop()
            self.running = False
            self.phase = "done"
            self.result = self.analyse()
            try:
                self.result["motion"] = self.analyse_motion() if self.series else None
            except Exception as ex:
                self.result["motion"] = None
                self.motion_error = str(ex)

    def analyse(self):
        def frac(ph, k_):
            n = self.samples.get(ph, 0)
            return self.diff.get(ph, {}).get(k_, 0) / n if n else 0.0

        def busy(k_):
            """How many bits of the same byte change anywhere: a button byte is quiet, a stick or sensor isn't."""
            return sum(1 for d_ in self.diff.values() for kk in d_ if kk[:3] == k_[:3] and kk != k_)

        def best_bit(ph, others):
            cands = []
            for k_ in self.diff.get(ph, {}):
                f = frac(ph, k_)
                worst = max([frac(o, k_) for o in others] + [0.0])
                if f >= 0.75 and worst <= 0.15:
                    cands.append((round(f - worst, 1), -busy(k_), k_[0] != 0, k_))
            cands.sort(reverse=True)
            return cands[0][3] if cands else None

        def best_key(ph, other):
            """(vk, pairs): a key held through the hold, or one tapped only during this hold (press/release taps)."""
            held, taps = self.keys.get(ph, {}), self.taps.get(ph, {})
            for vk, t in sorted(held.items(), key=lambda kv: -kv[1]):
                if t >= 1.0 and self.keys.get(other, {}).get(vk, 0) < 0.3 and not self.taps.get("idle", {}).get(vk):
                    return vk, False
            for vk, n in sorted(taps.items(), key=lambda kv: -kv[1]):
                if n >= 1 and not self.taps.get(other, {}).get(vk) and not self.taps.get("idle", {}).get(vk):
                    return vk, n >= 2
            return None, False
        # the button's own hold, against the other button's hold (letting go a little late is fine)
        lk, rk = best_bit("l", ["r"]), best_bit("r", ["l"])
        (kl, pl), (kr, pr) = best_key("l", "r"), best_key("r", "l")
        out = {"l": lk, "r": rk, "map": None, "key_l": kl, "key_r": kr}
        if lk and rk and (lk[0], lk[1]) != (rk[0], rk[1]):
            rk = None
        hid_side = lk or rk
        if (lk or kl) and (rk or kr):
            m = {"kind": "mixed", "rid": None, "l": None, "r": None, "key_l": None if lk else kl, "key_r": None if rk else kr,
                 "pairs": bool((pl and not lk) or (pr and not rk))}
            if hid_side:
                d = self.devices[hid_side[0]]
                base = self.base.get((hid_side[0], hid_side[1]), [])
                idle = lambda k_: bool(base[k_[2]] & k_[3]) if len(base) > k_[2] else False
                m.update(vid=d["vid"], pid=d["pid"], usage_page=d["usage_page"], usage=d["usage"], interface=d["interface"],
                         rid=hid_side[1])
                if lk:
                    m["l"] = [lk[2], lk[3], idle(lk)]
                if rk:
                    m["r"] = [rk[2], rk[3], idle(rk)]
            out["map"] = m
        return out

    def analyse_motion(self):
        """Finds the turn (yaw) and tilt (pitch) rates: 16-bit fields that move smoothly while you turn or tilt the
        controller and stay put while it's still. Returns {"rid", "dev", "yaw": [byte, "<" or ">", sign], "pitch": …}."""
        import struct
        st, tu, ti = self.series.get("still", {}), self.series.get("turn", {}), self.series.get("tilt", {})
        best = {}
        for k_ in tu:
            if k_ not in ti or k_ not in st or len(tu[k_]) < 20 or len(ti[k_]) < 20:
                continue
            n = min(len(r) for ser in (st[k_], tu[k_], ti[k_]) for r in ser)
            for b in range(1, n - 1):
                for e in ("<", ">"):
                    stats = {}
                    for ph, ser in (("still", st[k_]), ("turn", tu[k_]), ("tilt", ti[k_])):
                        v = [struct.unpack(e + "h", bytes(r[b:b + 2]))[0] for r in ser]
                        m = sum(v) / len(v)
                        sd = (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5
                        rough = sum(abs(v[i] - v[i - 1]) for i in range(1, len(v))) / max(1, len(v) - 1)
                        stats[ph] = (m, sd, rough)
                    for axis, mine, other in (("yaw", "turn", "tilt"), ("pitch", "tilt", "turn")):
                        m1, sd1, rough1 = stats[mine]
                        if sd1 < 120 or sd1 < 2.5 * rough1:  # too small, or jumpy (a byte from the next field)
                            continue
                        score = sd1 / (stats[other][1] + stats["still"][1] + 40)
                        sign = 1 if m1 - stats["still"][0] >= 0 else -1
                        cand = (score, k_, b, e, sign, round(sd1), round(stats["still"][1]))
                        if axis not in best or cand[0] > best[axis][0]:
                            best[axis] = cand
        self.motion_found = best
        y, p_ = best.get("yaw"), best.get("pitch")
        if not y or not p_ or y[1] != p_[1] or y[2] == p_[2] or y[0] < 1.5 or p_[0] < 1.5:
            return None
        d = self.devices[y[1][0]]
        return {"rid": y[1][1], "usage_page": d["usage_page"], "usage": d["usage"],
                "yaw": [y[2], y[3], y[4]], "pitch": [p_[2], p_[3], p_[4]]}

    def summary(self):
        lines = []
        for i, d in enumerate(self.devices):
            rids = ",".join(f"{r:02x}:{n}" for r, n in sorted(d.get("rids", {}).items()))
            lines.append(f"#{i} {d['vid']:04x}:{d['pid']:04x} page {d['usage_page']:04x} usage {d['usage']:04x} if {d['interface']} "
                         + (f"reports {d['reports']} ids {rids}" if d["opened"] else f"not opened ({d['error']})"))
        r = self.result or {}
        for side in ("l", "r"):
            k_ = r.get(side)
            kv = r.get("key_" + side)
            lines.append(f"Legion {side.upper()} bit: " + (f"#{k_[0]} id {k_[1]:#04x} byte {k_[2]} mask {k_[3]:#04x}" if k_ else "none")
                         + f" · key: {f'{kv:#04x}' if kv else 'none'}")
        for ph in ("l", "r"):
            n = self.samples.get(ph, 0) or 1
            top = sorted(((c, k_) for k_, c in self.diff.get(ph, {}).items()), reverse=True)[:8]
            lines.append(f"{ph} bits: " + ", ".join(f"#{k_[0]}/{k_[1]:02x}/b{k_[2]}/{k_[3]:02x}={c / n:.2f}" for c, k_ in top))
        keys = {ph: {vk: round(t, 1) for vk, t in v.items()} for ph, v in self.keys.items()}
        lines.append(f"keys held: {keys}")
        if self.key_log:
            lines.append("key events: " + " ".join(f"{ph}:{vk:02x}/{sc:02x}{'v' if dn else '^'}{'i' if inj else ''}@{t}"
                                                   for ph, vk, sc, dn, inj, t in self.key_log[:30]))
        mf = getattr(self, "motion_found", None)
        if mf is not None:
            lines.append("motion: " + ", ".join(f"{ax} #{c[1][0]}/{c[1][1]:02x} b{c[2]}{c[3]} sign {c[4]} score {c[0]:.1f} "
                                                 f"sd {c[5]} still {c[6]}" for ax, c in mf.items()) +
                         ("" if (self.result or {}).get("motion") else " (not confident)"))
        for ph in ("idle", "l", "r", "turn", "tilt"):
            src = self.base if ph == "idle" else self.snap.get(ph, {})
            for (i, rid), data in sorted(src.items())[:3]:
                lines.append(f"{ph} #{i}/{rid:02x}: " + " ".join(f"{b:02x}" for b in data[:64]))
        return "\n".join(lines)


RGB_MODES = {"solid": 1, "pulse": 2, "dynamic": 3, "spiral": 4}


def _rgb_packets(mode, r, g, b, brightness=1.0, speed=0.5, profile=1):
    out = []
    for side in (0x03, 0x04):  # left, right controller
        out.append([0x05, 0x0C, 0x72, 0x01, side, RGB_MODES.get(mode, 1), r, g, b,
                    min(max(int(64 * brightness), 0), 63), min(max(int(64 * (1 - speed)), 0), 63), profile, 0x01])
    for side in (0x03, 0x04):
        out.append([0x05, 0x06, 0x73, 0x02, side, profile, 0x01])
    for side in (0x03, 0x04):
        out.append([0x05, 0x06, 0x70, 0x02, side, 0x01, 0x01])
    return out


def rgb_packets(mode, color_hex, brightness=1.0, speed=0.5):
    if mode == "off":
        return [[0x05, 0x06, 0x70, 0x02, side, 0x00, 0x01] for side in (0x03, 0x04)]
    c = color_hex.lstrip("#")
    return _rgb_packets(mode, int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), brightness, speed)


# =====================================================================  Legion Space footprint

def legion_space_processes(procs):
    """[(pid, name, working set)] for Legion Space and its helpers."""
    out = []
    for pid, name, ws in procs:
        low = name.lower()
        # only Legion Space itself: other Lenovo services handle hotkeys, drivers and updates, so they stay
        if ("legion" in low or low.startswith(("lsdaemon", "lsservice", "lsquick", "lsoverlay")) or "quicksetting" in low and
                "lenovo" in low) and "vanta" not in low:
            out.append((pid, name, ws))
    return out


def process_start_session(pid):
    """(start time as a Unix timestamp, session id) for a process, or (None, None). Session 0 = a Windows service."""
    start = sess = None
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        try:
            c, e, k_, u = FILETIME(), FILETIME(), FILETIME(), FILETIME()
            if kernel32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k_), ctypes.byref(u)):
                start = c.value / 1e7 - 11644473600  # FILETIME (1601) -> Unix time
        finally:
            kernel32.CloseHandle(h)
    sid = wintypes.DWORD()
    try:
        if kernel32.ProcessIdToSessionId(wintypes.DWORD(pid), ctypes.byref(sid)):
            sess = sid.value
    except Exception:
        pass
    return start, sess


def legion_space_windows(procs, since=None):
    """Legion Space's app processes in your session (not Lenovo's background services, which Windows restarts
    if they're killed and which then reopen the app). With `since`, only ones started after that time."""
    out = []
    for pid, name, ws in legion_space_processes(procs):
        start, sess = process_start_session(pid)
        if sess == 0:
            continue
        if since is not None and (start is None or start < since):
            continue
        out.append((pid, name, ws))
    return out


# Lenovo's services that open Legion Space when a Legion button is pressed, even with Legion Space's own startup
# turned off. The Legion buttons send nothing to Windows by themselves: a Lenovo service reads them from the controller
# and launches Legion Space. DAService is the one the Handheld Companion developers say to disable; LSDaemon is Legion
# Space's own background service (named by the Legion Helper project). Vanta reads the buttons itself, so both can stop.
LENOVO_BUTTON_SERVICE = "DAService"
_BUTTON_SERVICES = None


def button_services():
    """[name] of the installed Lenovo services that react to the Legion buttons (found once per run)."""
    global _BUTTON_SERVICES
    if _BUTTON_SERVICES is None:
        out = powershell("Get-CimInstance Win32_Service | Where-Object { $_.Name -eq 'DAService' -or $_.Name -match '^LSDaemon' "
                         "-or $_.PathName -match 'LSDaemon|Legion ?Space' } | ForEach-Object { $_.Name }", timeout=25)
        names = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
        if not names:  # PowerShell unavailable: fall back to the known names
            names = [n for n in (LENOVO_BUTTON_SERVICE, "LSDaemon") if (lambda r: r and r.returncode == 0)(run(["sc", "query", n]))]
        _BUTTON_SERVICES = names
    return list(_BUTTON_SERVICES)


def _service_state(name):
    """('running' | 'stopped' | 'disabled', start mode 'auto' | 'demand' | 'disabled' | 'delayed-auto') or None."""
    r = run(["sc", "query", name])
    if not r or r.returncode != 0:
        return None
    q = run(["sc", "qc", name])
    txt = (q.stdout if q else "") or ""
    mode = "disabled" if "DISABLED" in txt else "delayed-auto" if "DELAYED" in txt else "auto" if "AUTO_START" in txt else "demand"
    if "RUNNING" in (r.stdout or "") or "START_PENDING" in (r.stdout or ""):
        return "running", mode
    return ("disabled" if mode == "disabled" else "stopped"), mode


def button_service_state():
    """'running' if any of them runs, 'stopped' if none runs but one could start again, 'disabled' if all are
    disabled, or None if none is installed."""
    states = [st for st in (_service_state(n) for n in button_services()) if st]
    if not states:
        return None
    if any(st[0] == "running" for st in states):
        return "running"
    return "disabled" if all(st[1] == "disabled" for st in states) else "stopped"


def set_button_service(on, modes=None):
    """on=False: stop the services and keep them from starting; returns (ok, {name: previous start mode}) so they
    can be put back exactly. on=True: put them back (the saved start modes, else automatic) and start them."""
    names = button_services()
    if not names:
        return False, {}
    if on:
        ok = True
        for n in names:
            mode = (modes or {}).get(n) or "auto"
            a = run(["sc", "config", n, "start=", "disabled" if mode == "disabled" else mode])
            ok = ok and bool(a and a.returncode == 0)
            if mode != "disabled":
                run(["sc", "start", n])
        return ok, {}
    prev, ok = {}, True
    for n in names:
        st = _service_state(n)
        if st:
            prev[n] = st[1]
        a = run(["sc", "config", n, "start=", "disabled"])
        run(["sc", "stop", n])
        ok = ok and bool(a and a.returncode == 0)
    return ok, prev


def close_processes(pids):
    closed = 0
    for pid in pids:
        h = kernel32.OpenProcess(0x0001, False, pid)
        if h:
            try:
                closed += bool(kernel32.TerminateProcess(h, 0))
            finally:
                kernel32.CloseHandle(h)
    return closed


def own_memory():
    import ctypes as _c

    class PMC(_c.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", _c.c_size_t),
                    ("WorkingSetSize", _c.c_size_t), ("a", _c.c_size_t), ("b", _c.c_size_t), ("c", _c.c_size_t),
                    ("d", _c.c_size_t), ("PagefileUsage", _c.c_size_t), ("PeakPagefileUsage", _c.c_size_t)]
    pmc = PMC()
    pmc.cb = _c.sizeof(pmc)
    psapi = _c.WinDLL("psapi")
    if psapi.GetProcessMemoryInfo(_c.c_void_p(-1), _c.byref(pmc), pmc.cb):  # -1 = this process
        return pmc.WorkingSetSize
    return 0


def send_keys(*vks):
    """Press a key combination, e.g. send_keys(0x5B, 0x09) for Win+Tab."""
    for vk in vks:
        user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, 2, 0)


def touch_keyboard():
    """Show the on-screen keyboard (the classic one: the touch keyboard has no reliable way to be opened from outside)."""
    try:
        os.startfile(os.path.join(WIN, "System32", "osk.exe"))
        return True
    except Exception:
        return False


def set_priority(pid, level="above"):
    """Give a process more CPU time. 'above' = above normal (safe for games), 'normal' to undo."""
    cls = {"above": 0x8000, "high": 0x80, "normal": 0x20}[level]
    h = kernel32.OpenProcess(0x0200, False, pid)  # PROCESS_SET_INFORMATION
    if not h:
        return False
    try:
        return bool(kernel32.SetPriorityClass(h, cls))
    finally:
        kernel32.CloseHandle(h)


# =====================================================================  Discord
# Rich Presence talks to the Discord app over its local pipe (\\.\pipe\discord-ipc-N): 8-byte header
# (opcode, length; little-endian uint32) + JSON. Opcode 0 = handshake, 1 = frame. It needs an Application ID
# from discord.com/developers (the app's name is what Discord shows as "Playing ...").
# Session posts and screenshot sharing use a channel webhook URL. Voice buttons press Discord's own global
# shortcuts (Ctrl+Shift+M mute, Ctrl+Shift+D deafen).

class DiscordPresence:
    def __init__(self):
        import threading
        self.client_id = ""
        self.want = None          # activity dict, or None to clear
        self.sent = "unset"
        self.pipe = None
        self.connected = False
        self.error = ""
        self.running = False
        self.wake = threading.Event()
        self.last_try = 0.0

    def start(self, client_id):
        import threading
        self.client_id = str(client_id).strip()
        if self.running:
            self.wake.set()
            return
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False
        self.wake.set()

    def set(self, activity):
        self.want = activity
        self.wake.set()

    def _frame(self, op, payload):
        data = json.dumps(payload).encode()
        self.pipe.write(struct.pack("<II", op, len(data)) + data)  # one write: the pipe needs the whole frame at once
        self.pipe.flush()

    def _read(self):
        head = self.pipe.read(8)
        if len(head) < 8:
            raise OSError("Discord closed the connection")
        op, n = struct.unpack("<II", head)
        body = json.loads(self.pipe.read(n) or b"{}")
        if op == 2:
            raise OSError(body.get("message", "Discord closed the connection"))
        return op, body

    def _connect(self):
        if not self.client_id.isdigit():
            self.error = "Add your Application ID first"
            return False
        for i in range(10):
            try:
                self.pipe = open(rf"\\.\pipe\discord-ipc-{i}", "r+b", buffering=0)
                break
            except OSError:
                self.pipe = None
        if not self.pipe:
            self.error = "Discord isn't running"
            return False
        try:
            self._frame(0, {"v": 1, "client_id": self.client_id})
            op, body = self._read()
            if body.get("evt") != "READY":
                raise OSError(body.get("data", {}).get("message") or "Discord said no")
        except Exception as ex:
            self._drop(str(ex) or "Couldn't connect")
            return False
        self.connected, self.error, self.sent = True, "", "unset"
        return True

    def _drop(self, err=""):
        try:
            if self.pipe:
                self.pipe.close()
        except Exception:
            pass
        self.pipe, self.connected, self.error = None, False, err

    def _loop(self):
        import uuid
        while self.running:
            self.wake.wait(15)
            self.wake.clear()
            if not self.running:
                break
            want = self.want
            key = json.dumps(want, sort_keys=True)
            if self.connected and key == self.sent:
                continue
            if not self.connected:
                if want is None or time.time() - self.last_try < 10:
                    continue
                self.last_try = time.time()
                if not self._connect():
                    continue
            try:
                args = {"pid": os.getpid()}
                if want is not None:
                    args["activity"] = want
                self._frame(1, {"cmd": "SET_ACTIVITY", "args": args, "nonce": str(uuid.uuid4())})
                op, body = self._read()
                if body.get("evt") == "ERROR":
                    self.error = body.get("data", {}).get("message", "Discord rejected the status")
                else:
                    self.sent, self.error = key, ""
            except Exception as ex:
                self._drop(str(ex) or "Lost Discord")
            time.sleep(4.5)  # Discord allows about 5 status updates per 20 seconds
        if self.connected:
            try:
                self._frame(1, {"cmd": "SET_ACTIVITY", "args": {"pid": os.getpid()}, "nonce": "bye"})
                self._read()
            except Exception:
                pass
        self._drop()


def valid_webhook(url):
    return bool(re.match(r"^https://(?:\w+\.)?(?:discord|discordapp)\.com/api/webhooks/\d+/[\w-]+$", (url or "").strip()))


def discord_webhook(url, payload, file_path=None):
    """Post to a Discord channel webhook. Returns (ok, message)."""
    import urllib.request
    import urllib.error
    if not valid_webhook(url):
        return False, "That isn't a Discord webhook link"
    headers = {"User-Agent": "Vanta (Legion Go hub)"}
    if file_path:
        boundary = "vanta" + os.urandom(8).hex()
        name = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            blob = f.read()
        if len(blob) > 10 * 1024 * 1024:
            return False, "That screenshot is over Discord's 10 MB limit"
        mime = "image/png" if name.lower().endswith(".png") else "image/jpeg"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
                f"Content-Type: application/json\r\n\r\n{json.dumps(payload)}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"{name}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n").encode() + blob + f"\r\n--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    else:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url.strip(), data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status in (200, 204), "Posted to Discord"
    except urllib.error.HTTPError as ex:
        return False, {401: "Discord says the webhook link is wrong", 404: "That webhook was deleted",
                       429: "Discord says slow down, try again in a minute"}.get(ex.code, f"Discord error {ex.code}")
    except Exception:
        return False, "Couldn't reach Discord"


def discord_running(procs):
    return [(pid, name, ws) for pid, name, ws in procs if name.lower() in ("discord.exe", "discordptb.exe", "discordcanary.exe")]


def screenshot_folders():
    home = os.path.expanduser("~")
    out = []
    for base in (home, os.path.join(home, "OneDrive")):
        out += [os.path.join(base, "Pictures", "Screenshots"), os.path.join(base, "Videos", "Captures")]
    return [p for p in out if os.path.isdir(p)]


def latest_screenshot():
    best = None
    for folder in screenshot_folders():
        try:
            for e in os.scandir(folder):
                if e.is_file() and e.name.lower().endswith((".png", ".jpg", ".jpeg")):
                    t = e.stat().st_mtime
                    if not best or t > best[1]:
                        best = (e.path, t)
        except OSError:
            pass
    return best  # (path, mtime) or None


def take_screenshot():
    """Win+PrtScn: Windows saves the whole screen to Pictures\\Screenshots."""
    send_keys(0x5B, 0x2C)


# =====================================================================  media, radios, network (quick settings)
VK_MEDIA = {"play": 0xB3, "next": 0xB0, "prev": 0xB1, "stop": 0xB2}


def media_key(what):
    """Play/pause, next, previous: the same keys a keyboard's media buttons send, so any player reacts."""
    send_keys(VK_MEDIA[what])


def _exe_name(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        n = wintypes.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(h)


def now_playing():
    """'Artist - Song' from Spotify's window title (Spotify puts the current track there while playing)."""
    titles = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        try:
            n = user32.GetWindowTextLengthW(hwnd)
            if n and not user32.GetWindow(hwnd, 4):
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                t = buf.value
                if " - " in t and _exe_name(_pid_of(hwnd)) == "spotify.exe":
                    titles.append(t)
        except Exception:
            pass
        return True

    user32.EnumWindows(cb, 0)
    return titles[0] if titles else None


_RADIO_PS = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$g = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
Function Await($t, $r) { $a = $g.MakeGenericMethod($r); $n = $a.Invoke($null, @($t)); $n.Wait(-1) | Out-Null; $n.Result }
[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioAccessStatus,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioState,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
"""


def get_radios():
    """{'wifi': True/False, 'bluetooth': True/False} for radios this PC has."""
    out = powershell(_RADIO_PS + "$radios | % { \"$($_.Kind)=$($_.State)\" }", timeout=20)
    res = {}
    for line in (out or "").splitlines():
        kind, _, state = line.strip().partition("=")
        key = {"WiFi": "wifi", "Bluetooth": "bluetooth"}.get(kind)
        if key:
            res[key] = state == "On"
    return res


def set_radio(kind, on):
    k = {"wifi": "WiFi", "bluetooth": "Bluetooth"}[kind]
    out = powershell(_RADIO_PS + f"$r = $radios | ? {{ $_.Kind -eq '{k}' }} | Select -First 1; "
                     f"if ($r) {{ (Await ($r.SetStateAsync('{'On' if on else 'Off'}')) ([Windows.Devices.Radios.RadioAccessStatus])).ToString() }}",
                     timeout=20)
    return (out or "").strip().endswith("Allowed")


def toggle_hdr():
    """Win+Alt+B: Windows' own HDR on/off shortcut."""
    send_keys(0x5B, 0x12, 0x42)


def open_settings(page):
    try:
        os.startfile(f"ms-settings:{page}")
        return True
    except Exception:
        return False


class _IPOPT(ctypes.Structure):
    _fields_ = [("Ttl", ctypes.c_ubyte), ("Tos", ctypes.c_ubyte), ("Flags", ctypes.c_ubyte), ("OptionsSize", ctypes.c_ubyte),
                ("OptionsData", ctypes.c_void_p)]


class _ECHO(ctypes.Structure):
    _fields_ = [("Address", ctypes.c_ulong), ("Status", ctypes.c_ulong), ("RoundTripTime", ctypes.c_ulong),
                ("DataSize", ctypes.c_ushort), ("Reserved", ctypes.c_ushort), ("Data", ctypes.c_void_p), ("Options", _IPOPT)]


def ping(host="1.1.1.1", count=4, timeout_ms=1000):
    """(average ms, lost) using Windows' ICMP API (no admin needed). None average if every ping was lost."""
    import socket
    try:
        ip = socket.gethostbyname(host)
    except OSError:
        return None, count
    iph = ctypes.WinDLL("iphlpapi")
    iph.IcmpCreateFile.restype = wintypes.HANDLE
    iph.IcmpSendEcho.argtypes = [wintypes.HANDLE, ctypes.c_ulong, ctypes.c_void_p, wintypes.WORD, ctypes.c_void_p,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
    iph.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
    addr = struct.unpack("<L", socket.inet_aton(ip))[0]
    h = iph.IcmpCreateFile()
    times, lost = [], 0
    try:
        data = b"vanta-ping-32-bytes-of-payload!!"
        for _ in range(count):
            buf = ctypes.create_string_buffer(ctypes.sizeof(_ECHO) + len(data) + 8)
            n = iph.IcmpSendEcho(h, addr, data, len(data), None, buf, len(buf), timeout_ms)
            rep = _ECHO.from_buffer(buf)
            if n and rep.Status == 0:
                times.append(rep.RoundTripTime)
            else:
                lost += 1
    finally:
        iph.IcmpCloseHandle(h)
    return (sum(times) / len(times) if times else None), lost


def wifi_info():
    """{'ssid': ..., 'signal': percent} from netsh (English Windows labels)."""
    r = run(["netsh", "wlan", "show", "interfaces"], timeout=10)
    text = r.stdout if r else ""
    sig = re.search(r"^\s*Signal\s*:\s*(\d+)\s*%", text, re.M)
    ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", text, re.M)
    return {"ssid": ssid.group(1).strip() if ssid else None, "signal": int(sig.group(1)) if sig else None}



# =====================================================================  keyboard output for back-button mapping
# SendInput with scan codes: games that read DirectInput/raw input see these, unlike plain virtual-key events.
class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


KEY_NAMES = {
    "Esc": 0x1B, "Tab": 0x09, "Enter": 0x0D, "Space": 0x20, "Backspace": 0x08, "Shift": 0x10, "Ctrl": 0x11, "Alt": 0x12,
    "Win": 0x5B, "Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27, "PrtScn": 0x2C, "Delete": 0x2E,
    **{f"F{i}": 0x6F + i for i in range(1, 13)}, **{c: ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
}
_EXTENDED = {0x26, 0x28, 0x25, 0x27, 0x2E, 0x5B, 0x2C}


def _key_input(vk, up):
    scan = user32.MapVirtualKeyW(vk, 0)  # MAPVK_VK_TO_VSC
    flags = 0x0008 if scan else 0  # KEYEVENTF_SCANCODE
    if vk in _EXTENDED:
        flags |= 0x0001
    if up:
        flags |= 0x0002
    i = _INPUT(type=1)
    i.ki = _KEYBDINPUT(wVk=0 if scan else vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return i


def combo_keys(combo):
    """'Ctrl+Shift+M' -> [vk, ...]; unknown names are dropped."""
    return [KEY_NAMES[p] for p in combo.replace(" ", "").split("+") if p in KEY_NAMES]


def key_combo(combo, down=True, up=True):
    """Press and/or release a combination (down only = hold it until a matching up call)."""
    vks = combo_keys(combo)
    if not vks:
        return False
    seq = []
    if down:
        seq += [_key_input(vk, False) for vk in vks]
    if up:
        seq += [_key_input(vk, True) for vk in reversed(vks)]
    arr = (_INPUT * len(seq))(*seq)
    return user32.SendInput(len(seq), arr, ctypes.sizeof(_INPUT)) == len(seq)


# =====================================================================  suspend / resume a game
def suspend_process(pid, resume=False):
    """Freeze (or unfreeze) every thread of a process, like the Steam Deck's suspend."""
    ntdll = ctypes.WinDLL("ntdll")
    h = kernel32.OpenProcess(0x0800, False, pid)  # PROCESS_SUSPEND_RESUME
    if not h:
        return False
    try:
        fn = ntdll.NtResumeProcess if resume else ntdll.NtSuspendProcess
        fn.argtypes = [wintypes.HANDLE]
        return fn(h) == 0
    finally:
        kernel32.CloseHandle(h)


# =====================================================================  more game stores
def _uninstall_entries():
    """Installed programs from the Uninstall keys (both registry views, machine and user)."""
    out = []
    roots = [(HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (HKLM, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (HKCU, r"Software\Microsoft\Windows\CurrentVersion\Uninstall")]
    for root, path in roots:
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    try:
                        sub = winreg.EnumKey(k, i)
                        with winreg.OpenKey(k, sub) as s:
                            e = {"key": sub}
                            for n in ("DisplayName", "Publisher", "InstallLocation", "DisplayIcon", "UninstallString"):
                                try:
                                    e[n] = str(winreg.QueryValueEx(s, n)[0])
                                except OSError:
                                    e[n] = ""
                            if e["DisplayName"]:
                                out.append(e)
                    except OSError:
                        pass
        except OSError:
            pass
    return out


def _dir_size(path, limit=200000):
    total, n = 0, 0
    for root, _, files in os.walk(path):
        for f in files:
            n += 1
            if n > limit:
                return total
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def ubisoft_library():
    out = []
    base = r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs"
    try:
        with winreg.OpenKey(HKLM, base, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                gid = winreg.EnumKey(k, i)
                d = reg_get(HKLM, rf"{base}\{gid}", "InstallDir", "")
                if d and os.path.isdir(d):
                    out.append({"id": f"ubisoft:{gid}", "source": "Ubisoft", "name": os.path.basename(os.path.normpath(d)),
                                "size": 0, "last": 0, "minutes": 0, "cover": None, "launch": f"uplay://launch/{gid}/0", "path": d})
    except OSError:
        pass
    return out


def ea_library():
    out, seen = [], set()
    dirs = [e["InstallLocation"] for e in _uninstall_entries() if "electronic arts" in e["Publisher"].lower() and e["InstallLocation"]]
    for drive in "CDEFG":
        for parent in (rf"{drive}:\Program Files\EA Games", rf"{drive}:\EA Games"):
            if os.path.isdir(parent):
                dirs += [os.path.join(parent, n) for n in os.listdir(parent)]
    for d in dirs:
        xml = os.path.join(d, "__Installer", "installerdata.xml")
        if d.lower() in seen or not os.path.exists(xml):
            continue
        seen.add(d.lower())
        try:
            text = open(xml, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        ids = re.findall(r"<contentID>\s*([^<\s]+)\s*</contentID>", text)
        title = re.search(r"<gameTitle[^>]*>\s*([^<]+?)\s*</gameTitle>", text)
        if ids:
            out.append({"id": f"ea:{ids[0]}", "source": "EA", "name": title.group(1) if title else os.path.basename(os.path.normpath(d)),
                        "size": 0, "last": 0, "minutes": 0, "cover": None,
                        "launch": "origin2://game/launch?offerIds=" + ids[0], "path": d})
    return out


# Battle.net launch codes (Battle.net.exe --exec="launch CODE"); other Blizzard games open in Battle.net instead.
BNET_CODES = [("World of Warcraft", "WoW"), ("Diablo II: Resurrected", "OSI"), ("Diablo III", "D3"), ("Overwatch", "Pro"),
              ("Hearthstone", "WTCG"), ("StarCraft II", "S2"), ("StarCraft", "S1"), ("Warcraft III", "W3"),
              ("Blizzard Arcade Collection", "RTRO")]


def battlenet_library():
    entries = _uninstall_entries()
    bnet = next((e for e in entries if e["DisplayName"].lower() == "battle.net"), None)
    exe = os.path.join(bnet["InstallLocation"], "Battle.net.exe") if bnet and bnet["InstallLocation"] else \
        r"C:\Program Files (x86)\Battle.net\Battle.net.exe"
    if not os.path.exists(exe):
        return []
    out = []
    for e in entries:
        if "blizzard" not in e["Publisher"].lower() or e["DisplayName"].lower() == "battle.net" or "Battle.net" not in e["UninstallString"]:
            continue
        name = e["DisplayName"]
        code = next((c for n, c in BNET_CODES if name.lower().startswith(n.lower())), None)
        out.append({"id": f"bnet:{name.lower()}", "source": "Battle.net", "name": name, "size": 0, "last": 0, "minutes": 0,
                    "cover": None, "launch": exe, "args": [f"--exec=launch {code}"] if code else [], "path": e["InstallLocation"]})
    return out


def xbox_library():
    """Game Pass / Microsoft Store games installed to XboxGames folders (they carry a MicrosoftGame.config)."""
    found = []
    for drive in "CDEFGH":
        root = f"{drive}:\\XboxGames"
        if not os.path.isdir(root):
            continue
        for n in os.listdir(root):
            cfg = os.path.join(root, n, "Content", "MicrosoftGame.config")
            if not os.path.exists(cfg):
                continue
            try:
                text = open(cfg, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            ident = re.search(r'<Identity[^>]*\bName="([^"]+)"', text)
            exe = re.search(r'<Executable[^>]*\bId="([^"]+)"', text)
            disp = re.search(r'DefaultDisplayName="([^"]+)"', text)
            if ident:
                found.append((ident.group(1), exe.group(1) if exe else "Game", disp.group(1) if disp and "ms-resource" not in disp.group(1)
                              else n, os.path.join(root, n)))
    if not found:
        return []
    names = ",".join(f"'{f[0]}'" for f in found)
    fam = {}
    out = powershell(f"Get-AppxPackage | ? {{ @({names}) -contains $_.Name }} | % {{ \"$($_.Name)|$($_.PackageFamilyName)\" }}", timeout=40)
    for line in (out or "").splitlines():
        n, _, pfn = line.strip().partition("|")
        fam[n] = pfn
    res = []
    for ident, app, disp, path in found:
        if ident in fam:
            res.append({"id": f"xbox:{ident}", "source": "Xbox", "name": disp, "size": 0, "last": 0, "minutes": 0, "cover": None,
                        "launch": f"shell:AppsFolder\\{fam[ident]}!{app}", "path": path})
    return res


# Emulators through RetroArch: ROM extension -> cores to try, first one installed wins.
ROM_CORES = {
    ".nes": ["mesen", "nestopia", "fceumm"], ".sfc": ["snes9x", "bsnes"], ".smc": ["snes9x", "bsnes"],
    ".gb": ["gambatte", "sameboy", "mgba"], ".gbc": ["gambatte", "sameboy", "mgba"], ".gba": ["mgba", "vba_next"],
    ".n64": ["mupen64plus_next", "parallel_n64"], ".z64": ["mupen64plus_next", "parallel_n64"], ".v64": ["mupen64plus_next"],
    ".md": ["genesis_plus_gx", "picodrive"], ".gen": ["genesis_plus_gx", "picodrive"], ".sms": ["genesis_plus_gx"],
    ".gg": ["genesis_plus_gx"], ".pce": ["mednafen_pce_fast"], ".nds": ["melonds", "desmume"],
    ".cue": ["swanstation", "mednafen_psx_hw", "pcsx_rearmed"], ".chd": ["swanstation", "mednafen_psx_hw", "pcsx_rearmed"],
    ".pbp": ["swanstation", "pcsx_rearmed"], ".a26": ["stella"], ".ws": ["mednafen_wswan"], ".wsc": ["mednafen_wswan"],
}


def find_retroarch():
    home = os.path.expanduser("~")
    cands = [r"C:\RetroArch-Win64\retroarch.exe", r"C:\RetroArch\retroarch.exe", os.path.join(home, "AppData", "Roaming", "RetroArch", "retroarch.exe"),
             r"C:\Program Files\RetroArch\retroarch.exe"]
    cands += [os.path.join(lib, "steamapps", "common", "RetroArch", "retroarch.exe") for lib in steam_libraries()]
    return next((c for c in cands if os.path.exists(c)), None)


def _rom_name(fn):
    n = os.path.splitext(fn)[0]
    n = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", n)  # drop (USA), [!] and similar tags
    return n.strip() or fn


def emulator_library(rom_dirs):
    ra = find_retroarch()
    if not ra or not rom_dirs:
        return []
    cores_dir = os.path.join(os.path.dirname(ra), "cores")
    have = {f.lower().replace("_libretro.dll", "") for f in os.listdir(cores_dir)} if os.path.isdir(cores_dir) else set()
    out = []
    for d in rom_dirs:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                core = next((c for c in ROM_CORES.get(ext, []) if c in have), None)
                if not core:
                    continue
                p = os.path.join(root, f)
                system = os.path.basename(root)
                out.append({"id": f"rom:{p.lower()}", "source": "Emulator", "name": _rom_name(f), "size": 0, "last": 0, "minutes": 0,
                            "cover": None, "launch": ra, "args": ["-L", os.path.join(cores_dir, core + "_libretro.dll"), p],
                            "cwd": os.path.dirname(ra), "detail": f"{system} · {core}"})
                if len(out) > 3000:
                    return out
    return out


# =====================================================================  save backups (Ludusavi, open source)
LUDUSAVI_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Vanta", "tools", "ludusavi")
LUDUSAVI = os.path.join(LUDUSAVI_DIR, "ludusavi.exe")
SAVE_BACKUPS = os.path.join(os.path.expanduser("~"), "Documents", "Vanta save backups")


def ludusavi_installed():
    return os.path.exists(LUDUSAVI)


def download_ludusavi():
    """Fetch Ludusavi (MIT licence) from its official GitHub releases."""
    import urllib.request
    import zipfile
    import io
    req = urllib.request.Request("https://api.github.com/repos/mtkennerly/ludusavi/releases/latest",
                                 headers={"User-Agent": "Vanta", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rel = json.loads(r.read().decode("utf-8"))
    assets = rel.get("assets", [])
    pick = next((a for a in assets if re.search(r"win64\.zip$", a.get("name", "")) and "legacy" not in a.get("name", "")), None)
    if not pick:
        raise OSError("No Windows download found in Ludusavi's latest release")
    req = urllib.request.Request(pick["browser_download_url"], headers={"User-Agent": "Vanta"})
    with urllib.request.urlopen(req, timeout=180) as r:
        blob = r.read()
    os.makedirs(LUDUSAVI_DIR, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        exe = next((n for n in z.namelist() if n.lower().endswith("ludusavi.exe")), None)
        if not exe:
            raise OSError("The download didn't contain ludusavi.exe")
        with z.open(exe) as src, open(LUDUSAVI + ".part", "wb") as dst:
            dst.write(src.read())
    os.replace(LUDUSAVI + ".part", LUDUSAVI)
    return rel.get("tag_name", "")


def ludusavi(action, game, path=None):
    """Back up or restore one game's saves. Returns (ok, message, bytes)."""
    path = path or SAVE_BACKUPS
    os.makedirs(path, exist_ok=True)
    r = run([LUDUSAVI, action, "--force", "--api", "--path", path, game], timeout=300)
    if not r:
        return False, "Ludusavi didn't run", 0
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        return False, (r.stderr or r.stdout or "Ludusavi failed").strip().splitlines()[-1][:120], 0
    games = data.get("games", {})
    if not games:
        return False, f"Ludusavi doesn't know where {game} keeps its saves", 0
    size = data.get("overall", {}).get("processedBytes", 0)
    failed = data.get("errors", {}).get("someGamesFailed")
    return (not failed), ("Some files couldn't be copied" if failed else "done"), size


# =====================================================================  move Steam games between drives
def steam_running():
    r = run(["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"], timeout=10)
    return bool(r and "steam.exe" in r.stdout.lower())


def steam_game_location(appid):
    """(library path, manifest path, install folder) for an installed Steam game."""
    for lib in steam_libraries():
        man = os.path.join(lib, "steamapps", f"appmanifest_{appid}.acf")
        if os.path.exists(man):
            try:
                text = open(man, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            m = re.search(r'"installdir"\s+"([^"]+)"', text)
            if m:
                return lib, man, os.path.join(lib, "steamapps", "common", m.group(1))
    return None


def move_steam_game(appid, target_lib, progress=None):
    """Copy, verify, then remove the original. Steam must be closed. Returns (ok, message)."""
    import shutil
    loc = steam_game_location(appid)
    if not loc:
        return False, "Couldn't find the game's files"
    lib, man, src = loc
    if os.path.normcase(lib) == os.path.normcase(target_lib):
        return False, "It's already on that drive"
    if steam_running():
        return False, "Close Steam first (Steam must be closed to move games)"
    total = _dir_size(src, limit=10 ** 9)
    free = shutil.disk_usage(target_lib).free
    if total > free - 1024 ** 3:
        return False, f"Not enough room: needs {total / 1024 ** 3:.1f} GB"
    dst = os.path.join(target_lib, "steamapps", "common", os.path.basename(src))
    if os.path.exists(dst):
        return False, "A folder with that name is already on the target drive"
    tmp = dst + ".vanta-moving"
    done = [0]

    def copy(s, d):
        shutil.copy2(s, d)
        done[0] += os.path.getsize(d)
        if progress:
            progress(done[0], total)

    try:
        shutil.copytree(src, tmp, copy_function=copy)
        if _dir_size(tmp, limit=10 ** 9) != total:
            raise OSError("the copy doesn't match the original")
        os.replace(tmp, dst)
        shutil.copy2(man, os.path.join(target_lib, "steamapps", os.path.basename(man)))
    except Exception as ex:
        shutil.rmtree(tmp, ignore_errors=True)
        return False, f"Move stopped, nothing was removed: {ex}"
    os.remove(man)
    shutil.rmtree(src, ignore_errors=True)
    return True, "moved"


def type_text(text):
    """Type characters into whatever window has focus (Unicode, so any layout and symbols work)."""
    seq = []
    for ch in text:
        o = ord(ch)
        codes = [o] if o < 0x10000 else [0xD800 + ((o - 0x10000) >> 10), 0xDC00 + ((o - 0x10000) & 0x3FF)]  # UTF-16
        for code in codes:
            for up in (False, True):
                i = _INPUT(type=1)
                i.ki = _KEYBDINPUT(wVk=0, wScan=code, dwFlags=0x0004 | (0x0002 if up else 0), time=0, dwExtraInfo=0)
                seq.append(i)
    if not seq:
        return False
    arr = (_INPUT * len(seq))(*seq)
    return user32.SendInput(len(seq), arr, ctypes.sizeof(_INPUT)) == len(seq)


# =====================================================================  UI sounds (made here, no files shipped)
SOUND_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Vanta", "sounds")


def _tone_wav(path, notes, volume):
    """Write a tiny 16-bit mono WAV: notes = [(frequency Hz, milliseconds)], with a soft fade so nothing clicks."""
    import math
    import wave
    rate = 22050
    frames = bytearray()
    for freq, ms in notes:
        n = int(rate * ms / 1000)
        for i in range(n):
            env = min(1.0, i / (rate * 0.004)) * max(0.0, 1 - i / n) ** 1.6
            v = int(32767 * volume * env * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", v)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


SOUNDS = {"move": [(1320, 28)], "select": [(880, 40), (1320, 55)], "back": [(990, 40), (660, 60)], "toggle": [(1175, 45)],
          "error": [(330, 90), (262, 120)]}


def prepare_sounds(volume=0.25):
    os.makedirs(SOUND_DIR, exist_ok=True)
    tag = os.path.join(SOUND_DIR, f"v{int(volume * 100)}.ok")
    if not os.path.exists(tag):
        for name, notes in SOUNDS.items():
            _tone_wav(os.path.join(SOUND_DIR, f"{name}.wav"), notes, volume)
        for f in os.listdir(SOUND_DIR):
            if f.endswith(".ok"):
                os.remove(os.path.join(SOUND_DIR, f))
        open(tag, "w").close()


def play_sound(name):
    try:
        import winsound
        winsound.PlaySound(os.path.join(SOUND_DIR, f"{name}.wav"), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        pass


# =====================================================================  updates from a GitHub repository's releases
def parse_repo(text):
    m = re.search(r"(?:github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", (text or "").strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _ver(tag):
    return tuple(int(x) for x in re.findall(r"\d+", tag or "")[:4]) or (0,)


def check_update(repo, current, asset_name):
    """(newer?, tag, download url, notes) from the repo's latest release."""
    import urllib.request
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                 headers={"User-Agent": "Vanta", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        rel = json.loads(r.read().decode("utf-8"))
    tag = rel.get("tag_name", "")
    asset = next((a for a in rel.get("assets", []) if a.get("name", "").lower() == asset_name.lower()), None)
    return _ver(tag) > _ver(current), tag, asset["browser_download_url"] if asset else None, (rel.get("body") or "")[:400]


def install_update(url, exe_path):
    """Download the new exe next to the running one, then hand over to a small script that swaps them after we exit."""
    import urllib.request
    import tempfile
    new = exe_path + ".new"
    req = urllib.request.Request(url, headers={"User-Agent": "Vanta"})
    with urllib.request.urlopen(req, timeout=300) as r, open(new, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
    with open(new, "rb") as f:
        if f.read(2) != b"MZ":
            os.remove(new)
            raise OSError("the download isn't a Windows program")
    script = os.path.join(tempfile.gettempdir(), "vanta_update.cmd")
    pid = os.getpid()
    with open(script, "w") as f:
        f.write("@echo off\r\n"
                f':wait\r\ntasklist /FI "PID eq {pid}" | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto wait)\r\n'
                "set n=0\r\n"
                f':swap\r\nmove /y "{exe_path}" "{exe_path}.old" >nul 2>&1 || (set /a n+=1 & timeout /t 1 /nobreak >nul & '
                'if %n% lss 30 goto swap)\r\n'
                f'move /y "{new}" "{exe_path}" >nul\r\n'
                f'start "" "{exe_path}"\r\n'
                f'del "{exe_path}.old" >nul 2>&1\r\n')
    subprocess.Popen(["cmd", "/c", script], creationflags=NO_WINDOW | 0x00000008)  # DETACHED_PROCESS
    return True


def mouse_move(dx, dy):
    """Relative mouse movement (games read this as aim, like a real mouse)."""
    i = _INPUT(type=0)
    i.mi = _MOUSEINPUT(dx=int(dx), dy=int(dy), mouseData=0, dwFlags=0x0001, time=0, dwExtraInfo=0)
    return user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(_INPUT)) == 1


def mouse_click(right=False):
    seq = (_INPUT * 2)(_INPUT(type=0), _INPUT(type=0))
    down, up = (0x0008, 0x0010) if right else (0x0002, 0x0004)
    seq[0].mi = _MOUSEINPUT(0, 0, 0, down, 0, 0)
    seq[1].mi = _MOUSEINPUT(0, 0, 0, up, 0, 0)
    return user32.SendInput(2, seq, ctypes.sizeof(_INPUT)) == 2


# =====================================================================  CPU limit, power menu, sleep tracking
_THROTTLE = ["SCHEME_CURRENT", "SUB_PROCESSOR", "PROCTHROTTLEMAX"]


def get_cpu_max():
    """(plugged-in %, battery %) maximum processor state of the active power plan."""
    r = run(["powercfg", "/q"] + _THROTTLE)
    text = r.stdout if r else ""
    ac = re.search(r"Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)", text)
    dc = re.search(r"Current DC Power Setting Index:\s*0x([0-9a-fA-F]+)", text)
    return (int(ac.group(1), 16) if ac else None, int(dc.group(1), 16) if dc else None)


def set_cpu_max(ac, dc=None):
    """Cap CPU speed (100 = no cap, 99 = no boost clocks, lower = slower and cooler)."""
    dc = ac if dc is None else dc
    ok = True
    for flag, v in (("/setacvalueindex", ac), ("/setdcvalueindex", dc)):
        if v is not None:
            r = run(["powercfg", flag] + _THROTTLE + [str(int(v))])
            ok &= bool(r and r.returncode == 0)
    run(["powercfg", "/setactive", "SCHEME_CURRENT"])
    return ok


def sleep_now():
    powrprof = ctypes.WinDLL("powrprof")
    return bool(powrprof.SetSuspendState(False, False, False))


def restart_now():
    run(["shutdown", "/r", "/t", "0"])


def shutdown_now():
    run(["shutdown", "/s", "/t", "0"])


def last_wake():
    """What woke the PC last (powercfg /lastwake), as a short line."""
    r = run(["powercfg", "/lastwake"], timeout=15)
    text = r.stdout if r else ""
    for key in ("Friendly Name:", "Description:", "Instance Path:"):
        for line in text.splitlines():
            if line.strip().startswith(key):
                v = line.split(":", 1)[1].strip()
                if v:
                    return v[:80]
    m = re.search(r"Wake Source Count - (\d+)", text)
    if m and m.group(1) == "0":
        return "the power button or opening the lid"
    return None


# =====================================================================  quiet while gaming: notifications + Windows Update
PUSH = r"Software\Microsoft\Windows\CurrentVersion\PushNotifications"
WU_UX = r"SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"
WU_POLICY = r"SOFTWARE\Microsoft\WindowsUpdate\UpdatePolicy\Settings"
_WU_PAUSE = ("PauseUpdatesStartTime", "PauseUpdatesExpiryTime", "PauseFeatureUpdatesStartTime", "PauseFeatureUpdatesEndTime",
             "PauseQualityUpdatesStartTime", "PauseQualityUpdatesEndTime")


def notifications_enabled():
    return reg_get(HKCU, PUSH, "ToastEnabled", 1) != 0


def set_notifications(on):
    """The same switch as Settings → Notifications; the notification service is restarted so it applies now."""
    reg_set(HKCU, PUSH, "ToastEnabled", 1 if on else 0)
    powershell("Get-Service -Name WpnUserService* | Restart-Service -Force -ErrorAction SilentlyContinue", timeout=20)
    return True


def updates_paused():
    return bool(reg_get(HKLM, WU_UX, "PauseUpdatesExpiryTime", ""))


def pause_updates(hours=12):
    """Pause Windows Update the way Settings does (it stops new downloads); resume_updates() undoes it."""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    start, end = now.strftime(fmt), (now + datetime.timedelta(hours=hours)).strftime(fmt)
    try:
        with winreg.CreateKeyEx(HKLM, WU_UX, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as k:
            for n in _WU_PAUSE:
                winreg.SetValueEx(k, n, 0, winreg.REG_SZ, start if n.endswith("StartTime") else end)
        reg_set(HKLM, WU_POLICY, "PausedFeatureStatus", 1)
        reg_set(HKLM, WU_POLICY, "PausedQualityStatus", 1)
        return True
    except OSError:
        return False


def resume_updates():
    """Remove the pause dates (this doesn't trigger an immediate update check)."""
    try:
        with winreg.OpenKey(HKLM, WU_UX, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as k:
            for n in _WU_PAUSE:
                try:
                    winreg.DeleteValue(k, n)
                except OSError:
                    pass
        reg_set(HKLM, WU_POLICY, "PausedFeatureStatus", 0)
        reg_set(HKLM, WU_POLICY, "PausedQualityStatus", 0)
        return True
    except OSError:
        return False


# =====================================================================  Steam: update status, shader caches
def steam_states():
    """{appid: (label, percent or None)} for games Steam is updating or wants to update."""
    out = {}
    for lib in steam_libraries():
        apps = os.path.join(lib, "steamapps")
        for e in _entries(apps):
            if not (e.name.startswith("appmanifest_") and e.name.endswith(".acf")):
                continue
            try:
                t = open(e.path, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            flags = int(_acf_value(t, "StateFlags") or 4)
            if flags & 4 and not flags & (2 | 256 | 512 | 1024):
                continue
            todo, done = int(_acf_value(t, "BytesToDownload") or 0), int(_acf_value(t, "BytesDownloaded") or 0)
            pct = done * 100 / todo if todo else None
            if flags & 256:
                label = "UPDATING"
            elif flags & 512:
                label = "UPDATE PAUSED"
            elif flags & (2 | 1024):
                label = "UPDATE NEEDED"
            else:
                label = "INSTALLING"
            out[_acf_value(t, "appid")] = (label, pct)
    return out


def shader_cache(appid):
    """(path, bytes) of Steam's shader cache for one game."""
    for lib in steam_libraries():
        p = os.path.join(lib, "steamapps", "shadercache", str(appid))
        if os.path.isdir(p):
            return p, _dir_size(p)
    return None, 0


def clear_shader_cache(appid):
    import shutil
    p, size = shader_cache(appid)
    if not p:
        return 0
    shutil.rmtree(p, ignore_errors=True)
    return size - (_dir_size(p) if os.path.isdir(p) else 0)


# =====================================================================  SteamGridDB covers, Steam achievements
COVER_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Vanta", "covers")


def _get_json(url, headers=None, timeout=20):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Vanta", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def sgdb_cover(key, gid, name):
    """Find a 600x900 cover on SteamGridDB (free account key) and cache it. Returns the file path or None."""
    import urllib.parse
    import urllib.request
    safe = re.sub(r"[^\w.-]+", "_", gid)[:80]
    path = os.path.join(COVER_DIR, safe + ".img")
    if os.path.exists(path):
        return path
    h = {"Authorization": f"Bearer {key}"}
    base = "https://www.steamgriddb.com/api/v2"
    found = _get_json(f"{base}/search/autocomplete/{urllib.parse.quote(name)}", h)
    games = found.get("data") or []
    if not games:
        return None
    grids = _get_json(f"{base}/grids/game/{games[0]['id']}?dimensions=600x900", h).get("data") or []
    if not grids:
        return None
    os.makedirs(COVER_DIR, exist_ok=True)
    req = urllib.request.Request(grids[0]["url"], headers={"User-Agent": "Vanta"})
    with urllib.request.urlopen(req, timeout=30) as r, open(path + ".part", "wb") as f:
        f.write(r.read())
    os.replace(path + ".part", path)
    return path


def _norm_title(name):
    t = re.sub(r"[™®©]", "", name or "").lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


_EPIC_CAT = None


def epic_catalog_art():
    """{catalog item id or normalized title: tall box art URL} from the Epic launcher's local catalog cache."""
    global _EPIC_CAT
    if _EPIC_CAT is not None:
        return _EPIC_CAT
    import base64
    out = {}
    path = os.path.join(PDATA, r"Epic\EpicGamesLauncher\Data\Catalog\catcache.bin")
    try:
        with open(path, "rb") as f:
            items = json.loads(base64.b64decode(f.read()).decode("utf-8", "replace"))
        for it in items if isinstance(items, list) else []:
            imgs = {i.get("type"): i.get("url") for i in it.get("keyImages") or [] if isinstance(i, dict)}
            url = imgs.get("DieselGameBoxTall") or imgs.get("OfferImageTall")
            if not url:
                continue
            if it.get("id"):
                out[it["id"]] = url
            if it.get("title"):
                out.setdefault(_norm_title(it["title"]), url)
    except Exception:
        pass
    _EPIC_CAT = out
    return out


def epic_cover(item_id, name):
    """Tall cover for an Epic game from the launcher's own catalog cache (no account or key needed)."""
    cat = epic_catalog_art()
    url = cat.get(item_id or "") or cat.get(_norm_title(name))
    if not url:
        return None
    os.makedirs(COVER_DIR, exist_ok=True)
    path = os.path.join(COVER_DIR, "epic_" + re.sub(r"[^\w.-]+", "_", item_id or _norm_title(name))[:80] + ".jpg")
    if os.path.exists(path):
        return path
    return path if _download_image(url, path) else None


def gog_cover(gid):
    """A cover for a GOG game made from its store background (GOG's public product API)."""
    os.makedirs(COVER_DIR, exist_ok=True)
    path = os.path.join(COVER_DIR, f"gog_{int(gid)}_cover.jpg")
    if os.path.exists(path):
        return path
    try:
        d = _get_json(f"https://api.gog.com/products/{int(gid)}")
    except Exception:
        return None
    img = (d.get("images") or {})
    url = img.get("background") or img.get("logo2x") or img.get("logo")
    if not url:
        return None
    url = ("https:" + url) if url.startswith("//") else url
    tmp = path + ".src"
    if not _download_image(url, tmp):
        return None
    try:
        _portrait_from_header(tmp, path)
        return path
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def pcgw_cover(name):
    """The box art from the game's PCGamingWiki page (covers nearly every PC game, any store). Cached; None if not found."""
    import urllib.parse
    os.makedirs(COVER_DIR, exist_ok=True)
    key = re.sub(r"[^\w.-]+", "_", _norm_title(name))[:80]
    path = os.path.join(COVER_DIR, f"pcgw_{key}.img")
    miss = path + ".none"
    if os.path.exists(path):
        return path
    if os.path.exists(miss) and time.time() - os.path.getmtime(miss) < 14 * 86400:
        return None
    clean = re.sub(r"[™®©]", "", name).strip()
    try:
        q = {"action": "opensearch", "format": "json", "search": clean, "limit": "1", "namespace": "0"}
        res = _get_json(PCGW_API + "?" + urllib.parse.urlencode(q), timeout=20)
        page = res[1][0] if len(res) > 1 and res[1] else None
        if page and _norm_title(page) != _norm_title(clean) and not _norm_title(page).startswith(_norm_title(clean)[:12]):
            page = None  # the search found some other game
        cover = None
        if page:
            q = {"action": "parse", "format": "json", "page": page, "prop": "wikitext", "redirects": "1"}
            d = _get_json(PCGW_API + "?" + urllib.parse.urlencode(q), timeout=25)
            text = ((d.get("parse") or {}).get("wikitext") or {}).get("*", "")
            m = re.search(r"\|\s*cover\s*=\s*([^\n|}]+)", text)
            cover = m.group(1).strip() if m else None
    except Exception:
        return None  # offline: try again next time
    tries = [cover] if cover else []
    if page:
        tries += [f"{page} cover.jpg", f"{page} cover.png"]  # the wiki's usual file names
    for fname in tries:
        if _download_image("https://www.pcgamingwiki.com/wiki/Special:FilePath/" + urllib.parse.quote(fname.replace(" ", "_")), path):
            return path
    try:
        open(miss, "w").close()
    except OSError:
        pass
    return None


# =====================================================================  leftovers: folders and caches of games that are gone
def find_leftovers():
    """[{"kind", "name", "path", "size"}] for Steam game folders no installed game owns and shader caches of
    uninstalled games. Nothing is touched here."""
    out = []
    for lib in steam_libraries():
        apps = os.path.join(lib, "steamapps")
        owned, ids = set(), set()
        for e in _entries(apps):
            if e.name.startswith("appmanifest_") and e.name.endswith(".acf"):
                try:
                    t = open(e.path, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                d, a = _acf_value(t, "installdir"), _acf_value(t, "appid")
                if d:
                    owned.add(d.lower())
                if a:
                    ids.add(str(a))
        if not ids:
            continue  # couldn't read this library: don't call everything a leftover
        for e in _entries(os.path.join(apps, "common")):
            if e.is_dir() and e.name.lower() not in owned and e.name.lower() not in ("steamworks shared", "steam controller configs"):
                out.append({"kind": "folder", "name": e.name, "path": e.path, "size": _dir_size(e.path)})
        for e in _entries(os.path.join(apps, "shadercache")):
            if e.is_dir() and e.name.isdigit() and e.name not in ids:
                out.append({"kind": "shaders", "name": f"Shader cache for app {e.name}", "path": e.path, "size": _dir_size(e.path)})
    out.sort(key=lambda x: -x["size"])
    return out


# =====================================================================  typing text (phone keyboard)
def type_text(text):
    """Type text into the app in front, as Unicode key presses (works with any keyboard layout)."""
    seq = []
    for ch in str(text)[:500]:
        if ch == "\n":
            seq += [_key_input(0x0D, False), _key_input(0x0D, True)]
            continue
        for code in (ch.encode("utf-16-le")[i:i + 2] for i in range(0, len(ch.encode("utf-16-le")), 2)):
            u = int.from_bytes(code, "little")
            for up in (False, True):
                i = _INPUT(type=1)
                i.ki = _KEYBDINPUT(wVk=0, wScan=u, dwFlags=0x0004 | (0x0002 if up else 0), time=0, dwExtraInfo=0)
                seq.append(i)
    if not seq:
        return True
    arr = (_INPUT * len(seq))(*seq)
    return user32.SendInput(len(seq), arr, ctypes.sizeof(_INPUT)) == len(seq)


def tap_key(vk):
    arr = (_INPUT * 2)(_key_input(vk, False), _key_input(vk, True))
    return user32.SendInput(2, arr, ctypes.sizeof(_INPUT)) == 2


# =====================================================================  weather (Open-Meteo: free, no key)
WEATHER_CODES = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Fog", 51: "Drizzle", 53: "Drizzle",
                 55: "Drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
                 66: "Freezing rain", 67: "Freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
                 80: "Showers", 81: "Showers", 82: "Heavy showers", 85: "Snow showers", 86: "Snow showers", 95: "Thunderstorm",
                 96: "Thunderstorm", 99: "Thunderstorm"}


def find_place(name):
    """(label, lat, lon) for a city name, or None."""
    import urllib.parse
    d = _get_json("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": name, "count": 1}), timeout=15)
    r = (d.get("results") or [None])[0]
    if not r:
        return None
    label = ", ".join(x for x in (r.get("name"), r.get("admin1") or r.get("country")) if x)
    return label, r["latitude"], r["longitude"]


def weather_now(lat, lon, fahrenheit=False):
    """{"temp", "hi", "lo", "text", "code"} for a place."""
    import urllib.parse
    q = {"latitude": lat, "longitude": lon, "current": "temperature_2m,weather_code",
         "daily": "temperature_2m_max,temperature_2m_min", "forecast_days": 1, "timezone": "auto"}
    if fahrenheit:
        q["temperature_unit"] = "fahrenheit"
    d = _get_json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q), timeout=15)
    cur, day = d.get("current") or {}, d.get("daily") or {}
    code = cur.get("weather_code")
    return {"temp": cur.get("temperature_2m"), "code": code, "text": WEATHER_CODES.get(code, ""),
            "hi": (day.get("temperature_2m_max") or [None])[0], "lo": (day.get("temperature_2m_min") or [None])[0]}


# =====================================================================  Steam friends (Web API key + public friends list)
def steam_friends(key, steamid):
    """[{"name", "state", "game", "last"}] for your Steam friends, people in a game first. None if it can't be read."""
    d = _get_json(f"https://api.steampowered.com/ISteamUser/GetFriendList/v1/?key={key}&steamid={steamid}&relationship=friend")
    ids = [f["steamid"] for f in (d.get("friendslist") or {}).get("friends", [])]
    out = []
    for i in range(0, len(ids), 100):
        s_ = _get_json(f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key={key}&steamids={','.join(ids[i:i + 100])}")
        for p in (s_.get("response") or {}).get("players", []):
            out.append({"name": p.get("personaname", "?"), "state": int(p.get("personastate") or 0),
                        "game": p.get("gameextrainfo") or "", "last": int(p.get("lastlogoff") or 0)})
    out.sort(key=lambda f: (not f["game"], f["state"] == 0, -f["last"]))
    return out


# =====================================================================  share cards (an image of your month or badges)
def _font(size, bold=False):
    from PIL import ImageFont
    fd = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for name in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
        try:
            return ImageFont.truetype(os.path.join(fd, name), size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()


def share_card(path, title, subtitle, lines, accent="#3d8bff", accent2="#7c5cff", bg="#0b0f17", app="Vanta"):
    """A 1080x1350 image (good for phones and social posts): big title, a few lines, the app's name at the bottom."""
    from PIL import Image, ImageDraw
    W, H = 1080, 1350
    hx = lambda c: tuple(int(c.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    a, a2, b = hx(accent), hx(accent2), hx(bg)
    img = Image.new("RGB", (W, H), b)
    px = img.load()
    for y in range(H):
        for x in range(0, W, 4):
            t = max(0.0, 1 - ((x - W) ** 2 + y ** 2) ** 0.5 / 1300)
            u = max(0.0, 1 - (x ** 2 + (y - H) ** 2) ** 0.5 / 1200)
            col = tuple(int(b[i] + (a[i] - b[i]) * t * 0.55 + (a2[i] - b[i]) * u * 0.45) for i in range(3))
            for dx in range(4):
                if x + dx < W:
                    px[x + dx, y] = col
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((70, 70, 150, 150), 22, fill=a)
    d.text((110, 110), app[:1], font=_font(54, True), fill="white", anchor="mm")
    d.text((172, 110), app.upper(), font=_font(34, True), fill="white", anchor="lm")
    y = 250
    d.text((80, y), title, font=_font(78, True), fill="white")
    y += 110
    d.text((84, y), subtitle, font=_font(40), fill=(220, 225, 235))
    y += 100
    for i, (big, small) in enumerate(lines[:8]):
        d.rounded_rectangle((70, y, W - 70, y + 100), 26, fill=tuple(int(c * 0.6) for c in b) if sum(b) > 60 else (24, 28, 40))
        d.text((105, y + 50), big, font=_font(40, True), fill="white", anchor="lm")
        if small:
            d.text((W - 105, y + 50), small, font=_font(34), fill=a, anchor="rm")
        y += 118
    d.text((80, H - 80), f"Made with {app}", font=_font(28), fill=(170, 176, 190), anchor="lm")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "PNG")
    return path


# =====================================================================  Steam news (patch notes), keyless
def _strip_markup(t):
    t = re.sub(r"\[/?[a-zA-Z0-9*]+(=[^\]]*)?\]", " ", t or "")   # BBCode
    t = re.sub(r"<[^>]+>", " ", t)                                # HTML
    t = re.sub(r"\{STEAM_CLAN_IMAGE\}\S*", " ", t)
    t = re.sub(r"https?://\S+", "", t)
    return " ".join(t.split())


def steam_news(appid, count=3):
    """[{"title", "date", "url", "text", "patch"}] newest first, from Steam's public news service."""
    d = _get_json(f"https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid={int(appid)}&count={int(count)}&maxlength=400&format=json",
                  timeout=15)
    out = []
    for it in (d.get("appnews") or {}).get("newsitems", []):
        title = it.get("title") or ""
        tags = [t.lower() for t in it.get("tags") or []]
        patch = "patchnotes" in tags or bool(re.search(r"\b(patch|update|hotfix|fix(es)?|version|v\d+\.\d+)\b", title, re.I))
        out.append({"title": title, "date": int(it.get("date") or 0), "url": it.get("url") or "",
                    "text": _strip_markup(it.get("contents"))[:300], "patch": patch,
                    "official": it.get("feed_type") == 1 or "steam_community_announcements" in (it.get("feedname") or "")})
    return out


# =====================================================================  Wake-on-LAN
def mac_for_ip(ip):
    """The MAC address of a PC on this network that answered recently (from Windows' ARP table), or None."""
    r = run(["arp", "-a", str(ip)], timeout=8)
    m = re.search(r"([0-9a-fA-F]{2}[-:]){5}[0-9a-fA-F]{2}", (r.stdout if r else "") or "")
    mac = m.group(0).replace("-", ":").lower() if m else None
    return None if not mac or mac in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00") else mac


def wake_on_lan(mac, ip=None):
    """Send the standard Wake-on-LAN 'magic packet' (6x 0xFF, then the MAC 16 times) to the network."""
    import socket
    raw = bytes.fromhex(re.sub(r"[^0-9a-fA-F]", "", mac))
    if len(raw) != 6:
        return False
    pkt = b"\xff" * 6 + raw * 16
    targets = ["255.255.255.255"]
    if ip and ip.count(".") == 3:
        targets.append(".".join(ip.split(".")[:3] + ["255"]))
    ok = False
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
        sk.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for t in targets:
            for port in (9, 7):
                try:
                    sk.sendto(pkt, (t, port))
                    ok = True
                except OSError:
                    pass
    return ok


# =====================================================================  friends' playtime in one game
def friends_playtime(key, steamid, appid, limit=40):
    """[(name, hours)] for friends who own this Steam game (public profiles only), most hours first."""
    fr = _get_json(f"https://api.steampowered.com/ISteamUser/GetFriendList/v1/?key={key}&steamid={steamid}&relationship=friend")
    ids = [f["steamid"] for f in (fr.get("friendslist") or {}).get("friends", [])][:limit]
    names = {}
    if ids:
        s_ = _get_json(f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key={key}&steamids={','.join(ids)}")
        names = {p["steamid"]: p.get("personaname", "?") for p in (s_.get("response") or {}).get("players", [])}
    out = []
    for sid in ids:
        try:
            d = _get_json(f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?key={key}&steamid={sid}"
                          f"&include_played_free_games=1&appids_filter[0]={int(appid)}", timeout=10)
        except Exception:
            continue
        for g in (d.get("response") or {}).get("games", []):
            if str(g.get("appid")) == str(appid):
                out.append((names.get(sid, "?"), round(g.get("playtime_forever", 0) / 60, 1)))
    out.sort(key=lambda x: -x[1])
    return out


# =====================================================================  displays: docking
def monitor_count():
    return user32.GetSystemMetrics(80)  # SM_CMONITORS


def screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def display_switch(mode):
    """Windows' own Win+P switch: 'external' (second screen only), 'internal' (PC screen only), 'extend', 'clone'."""
    if mode not in ("external", "internal", "extend", "clone"):
        return False
    exe = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "DisplaySwitch.exe")
    r = run([exe, "/" + mode], timeout=15)
    return r is not None


# =====================================================================  store apps that stay open after a game
STORE_APPS = {"Epic": ["EpicGamesLauncher.exe"], "EA": ["EADesktop.exe"], "Ubisoft": ["upc.exe", "UbisoftConnect.exe"],
              "Battle.net": ["Battle.net.exe"], "GOG": ["GalaxyClient.exe"], "Amazon": ["Amazon Games.exe"],
              "Xbox": ["XboxPcApp.exe"], "Steam": ["steam.exe"]}


# =====================================================================  startup speed (Windows' own boot records)
_PS_BOOT = r"""
$ev = Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Diagnostics-Performance/Operational'; Id=100,101,102,103} -MaxEvents 80 -ErrorAction SilentlyContinue
$out = @()
foreach ($e in $ev) {
  $x = [xml]$e.ToXml(); $d = @{}
  foreach ($n in $x.Event.EventData.Data) { $d[$n.Name] = $n.'#text' }
  $out += [pscustomobject]@{id=$e.Id; t=[int][double]::Parse((Get-Date $e.TimeCreated -UFormat %s)); boot=$d['BootTime'];
    main=$d['MainPathBootTime']; post=$d['BootPostBootTime']; name=$d['FriendlyName']; file=$d['Name']; total=$d['TotalTime'];
    slow=$d['DegradationTime']}
}
$os = Get-CimInstance Win32_OperatingSystem
[pscustomobject]@{events=$out; last=[int][double]::Parse((Get-Date $os.LastBootUpTime -UFormat %s))} | ConvertTo-Json -Compress -Depth 4
"""


def boot_report():
    """{"boots": [(time, seconds, main_s, after_s)], "slow": [(name, extra_s)], "last": time}. Reading the boot log
    needs admin; without it only the last boot time is known."""
    out = powershell(_PS_BOOT, timeout=40)
    try:
        d = json.loads(out) if out else None
    except ValueError:
        d = None
    if not d:
        return None
    evs = d.get("events") or []
    if isinstance(evs, dict):
        evs = [evs]
    boots, slow = [], {}
    num = lambda v: float(v) / 1000 if v not in (None, "") else None
    for e in evs:
        if e.get("id") == 100 and e.get("boot"):
            boots.append((e["t"], num(e["boot"]), num(e.get("main")), num(e.get("post"))))
        elif e.get("id") in (101, 102, 103) and (e.get("name") or e.get("file")) and e.get("slow"):
            nm = e.get("name") or os.path.basename(e.get("file") or "")
            slow[nm] = max(slow.get(nm, 0), num(e["slow"]) or 0)
    return {"boots": sorted(boots, reverse=True)[:12], "slow": sorted(slow.items(), key=lambda kv: -kv[1])[:10],
            "last": d.get("last")}


# =====================================================================  Steam reviews and genres (Steam's public store services)
def steam_reviews(appid):
    """{"desc", "pct", "total"} like ("Very Positive", 94, 120345), or None."""
    d = _get_json(f"https://store.steampowered.com/appreviews/{int(appid)}?json=1&language=all&purchase_type=all&num_per_page=0",
                  timeout=15)
    q = d.get("query_summary") or {}
    tot = int(q.get("total_reviews") or 0)
    if not tot:
        return {"desc": "No reviews yet", "pct": None, "total": 0}
    return {"desc": q.get("review_score_desc") or "", "pct": round(int(q.get("total_positive") or 0) * 100 / tot), "total": tot}


def steam_genres(appid):
    """The store's genres for a Steam app, like ["Action", "RPG"]; [] if none."""
    d = _get_json(f"https://store.steampowered.com/api/appdetails?appids={int(appid)}&l=english", timeout=20)
    data = (d.get(str(appid)) or {}).get("data") or {}
    return [x.get("description") for x in data.get("genres") or [] if x.get("description")][:6]


def toggle_recording():
    """Win+Alt+R: Game Bar starts (or stops) recording the game."""
    send_keys(0x5B, 0x12, 0x52)


def copy_capture(src, folder):
    """Copy a screenshot or clip into a folder (keeps the original). Returns True if copied, False if it was already there."""
    import shutil
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, os.path.basename(src))
    if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
        return False
    shutil.copy2(src, dst)
    return True


# =====================================================================  per-app volume (Windows Core Audio)
class _GUIDS(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


def _mkguid(s):
    import uuid
    u = uuid.UUID(s)
    g = _GUIDS()
    g.Data1, g.Data2, g.Data3 = u.fields[0], u.fields[1], u.fields[2]
    for i, b in enumerate(u.bytes[8:]):
        g.Data4[i] = b
    return g


_CLSID_MMDeviceEnumerator = "bcde0395-e52f-467c-8e3d-c4579291692e"
_IID_IMMDeviceEnumerator = "a95664d2-9614-4f35-a746-de8db63617e6"
_IID_IAudioSessionManager2 = "77aa99a0-1bd6-484f-8bc7-2c654c9a9b6f"
_IID_IAudioSessionControl2 = "bfb7ff88-7239-4fc9-8fa2-07c950be9c6d"
_IID_ISimpleAudioVolume = "87ce5498-68d6-44e5-9215-6da47ef883d8"


def _vcall(obj, index, argtypes, *args):
    """Call method #index of a COM object (a raw interface pointer). Returns the HRESULT."""
    vtbl = ctypes.c_void_p.from_address(obj).value
    fn_addr = ctypes.c_void_p.from_address(vtbl + index * ctypes.sizeof(ctypes.c_void_p)).value
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
    return proto(fn_addr)(obj, *args)


def _release(obj):
    if obj:
        try:
            _vcall(obj, 2, [])
        except Exception:
            pass


def _audio_sessions(fn):
    """Run fn(pid, simple_volume_ptr) for every audio session on the default speakers. Returns how many were seen."""
    ole32 = ctypes.OleDLL("ole32")
    try:
        ole32.CoInitializeEx(None, 0)  # multithreaded; already initialized on this thread is fine
        inited = True
    except OSError:
        inited = False
    seen = 0
    enum = dev = mgr = senum = None
    try:
        p = ctypes.c_void_p()
        ole32.CoCreateInstance(ctypes.byref(_mkguid(_CLSID_MMDeviceEnumerator)), None, 1 | 2 | 4 | 16,
                               ctypes.byref(_mkguid(_IID_IMMDeviceEnumerator)), ctypes.byref(p))
        enum = p.value
        p = ctypes.c_void_p()
        if _vcall(enum, 4, [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)], 0, 1, ctypes.byref(p)) < 0:
            return 0
        dev = p.value
        p = ctypes.c_void_p()
        if _vcall(dev, 3, [ctypes.POINTER(_GUIDS), ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
                  ctypes.byref(_mkguid(_IID_IAudioSessionManager2)), 23, None, ctypes.byref(p)) < 0:
            return 0
        mgr = p.value
        p = ctypes.c_void_p()
        if _vcall(mgr, 5, [ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(p)) < 0:
            return 0
        senum = p.value
        n = ctypes.c_int()
        _vcall(senum, 3, [ctypes.POINTER(ctypes.c_int)], ctypes.byref(n))
        for i in range(n.value):
            ctl = c2 = vol = None
            try:
                p = ctypes.c_void_p()
                if _vcall(senum, 4, [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)], i, ctypes.byref(p)) < 0:
                    continue
                ctl = p.value
                p = ctypes.c_void_p()
                if _vcall(ctl, 0, [ctypes.POINTER(_GUIDS), ctypes.POINTER(ctypes.c_void_p)],
                          ctypes.byref(_mkguid(_IID_IAudioSessionControl2)), ctypes.byref(p)) < 0:
                    continue
                c2 = p.value
                pid = wintypes.DWORD()
                _vcall(c2, 14, [ctypes.POINTER(wintypes.DWORD)], ctypes.byref(pid))
                p = ctypes.c_void_p()
                if _vcall(ctl, 0, [ctypes.POINTER(_GUIDS), ctypes.POINTER(ctypes.c_void_p)],
                          ctypes.byref(_mkguid(_IID_ISimpleAudioVolume)), ctypes.byref(p)) < 0:
                    continue
                vol = p.value
                seen += 1
                fn(pid.value, vol)
            finally:
                for o in (vol, c2, ctl):
                    _release(o)
    except OSError:
        return seen
    finally:
        for o in (senum, mgr, dev, enum):
            _release(o)
        if inited:
            try:
                ole32.CoUninitialize()
            except OSError:
                pass
    return seen


def _get_vol(vol):
    f = ctypes.c_float()
    _vcall(vol, 4, [ctypes.POINTER(ctypes.c_float)], ctypes.byref(f))
    return f.value


def _set_vol(vol, level):
    _vcall(vol, 3, [ctypes.c_float, ctypes.c_void_p], ctypes.c_float(max(0.0, min(1.0, level))), None)


def app_volumes():
    """{pid: volume 0…1} for apps that are playing sound (or have recently)."""
    out = {}
    _audio_sessions(lambda pid, v: out.__setitem__(pid, _get_vol(v)) if pid else None)
    return out


def set_app_volume(match, level):
    """Set the volume (0…1) of every audio session whose process id matches match(pid). Returns how many changed."""
    hits = []

    def each(pid, v):
        if pid and match(pid):
            _set_vol(v, level)
            hits.append(pid)
    _audio_sessions(each)
    return len(hits)


def quiet_other_apps(keep, level):
    """Turn every other app down to level (0 = silent). Returns {pid: old volume} to put back later."""
    saved = {}

    def each(pid, v):
        if pid and not keep(pid) and pid != os.getpid():
            saved[pid] = _get_vol(v)
            _set_vol(v, min(saved[pid], level))
    _audio_sessions(each)
    return saved


def restore_app_volumes(saved):
    def each(pid, v):
        if pid in saved:
            _set_vol(v, saved[pid])
    _audio_sessions(each)
    return True


def steam_user_id():
    """64-bit SteamID of the account that last signed in to Steam on this PC."""
    steam = _steam_root()
    if not steam:
        return None
    try:
        t = open(os.path.join(steam, "config", "loginusers.vdf"), encoding="utf-8", errors="ignore").read()
    except OSError:
        return None
    users = re.findall(r'"(7656\d{13})"\s*\{(.*?)\}', t, re.S)
    for sid, body in users:
        if re.search(r'"MostRecent"\s+"1"', body):
            return sid
    return users[0][0] if users else None


def steam_achievements(key, steamid, appid):
    """(unlocked, total) or None if the game has none / the profile is private."""
    d = _get_json(f"https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v1/?appid={appid}&key={key}&steamid={steamid}")
    ach = (d.get("playerstats") or {}).get("achievements")
    if not ach:
        return None
    return sum(1 for a in ach if a.get("achieved")), len(ach)


# =====================================================================  phone remote (LAN web page, PIN protected)
def lan_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent; this just picks the Wi-Fi/LAN address
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


REMOTE_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<meta name="theme-color" content="#0b0f17"><meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><meta name="apple-mobile-web-app-title" content="Vanta">
<link rel="manifest" href="/manifest.json"><link rel="icon" href="/icon.svg"><link rel="apple-touch-icon" href="/icon.svg">
<title>Vanta</title><style>
:root{--bg:#0b0f17;--p:#131a28;--p2:#1b2436;--t:#e9eef8;--m:#8e9ab0;--a:#3d8bff;--a2:#7c5cff;--g:#3ddc97;--w:#ffb547;--d:#ff5d6c;--line:rgba(255,255,255,.07)}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;margin:0}
html,body{background:var(--bg);color:var(--t);font:15px/1.35 -apple-system,"Segoe UI",system-ui,sans-serif;-webkit-user-select:none;user-select:none}
body{padding:calc(env(safe-area-inset-top) + 12px) 16px calc(env(safe-area-inset-bottom) + 92px);min-height:100vh;
 background:radial-gradient(120% 60% at 100% 0%,color-mix(in srgb,var(--a) 22%,transparent),transparent 60%),
 radial-gradient(90% 50% at 0% 10%,color-mix(in srgb,var(--a2) 16%,transparent),transparent 60%),var(--bg);background-attachment:fixed}
header{display:flex;align-items:center;gap:10px;margin:4px 2px 16px}
.logo{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,var(--a),var(--a2));display:grid;place-items:center;font-weight:800;font-size:17px;color:#fff;box-shadow:0 6px 20px color-mix(in srgb,var(--a) 45%,transparent)}
.brand{font-weight:800;letter-spacing:.28em;font-size:15px}.brand small{display:block;letter-spacing:.04em;font-weight:500;color:var(--m);font-size:12px}
.dot{margin-left:auto;display:flex;align-items:center;gap:6px;font-size:12px;color:var(--m)}.dot i{width:8px;height:8px;border-radius:50%;background:var(--g);box-shadow:0 0 10px var(--g)}
.dot.off i{background:var(--d);box-shadow:0 0 10px var(--d)}
.card{background:color-mix(in srgb,var(--p) 88%,transparent);border:1px solid var(--line);border-radius:22px;padding:16px;margin-bottom:14px;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
h2{font-size:11.5px;letter-spacing:.16em;color:var(--m);font-weight:700;margin:0 2px 10px;display:flex;justify-content:space-between}
h2 b{color:var(--t);letter-spacing:0;font-weight:600}
.hero{position:relative;overflow:hidden;min-height:170px;display:flex;flex-direction:column;justify-content:flex-end;padding:18px}
.hero .art{position:absolute;inset:0;background-size:cover;background-position:center;opacity:.55;filter:saturate(1.2)}
.hero:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,transparent 10%,rgba(0,0,0,.75))}
.hero>*:not(.art){position:relative;z-index:1}.hero .k{font-size:11.5px;letter-spacing:.18em;color:rgba(255,255,255,.75);font-weight:700}
.hero .n{font-size:26px;font-weight:800;margin:2px 0 4px;text-shadow:0 2px 12px rgba(0,0,0,.6)}.hero .s{color:rgba(255,255,255,.8);font-size:13.5px}
.rings{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.ring{text-align:center}.ring svg{width:100%;max-width:78px;display:block;margin:auto}
.ring b{font-size:17px;font-weight:800}.ring span{display:block;color:var(--m);font-size:10.5px;letter-spacing:.14em;font-weight:700;margin-top:2px}
canvas{width:100%;height:70px;display:block}
.row{display:flex;justify-content:space-between;align-items:center;padding:6px 0;color:var(--m);font-size:14px}.row b{color:var(--t);font-weight:600}
.seg{display:flex;background:var(--p2);border-radius:14px;padding:4px;gap:4px;margin:4px 0 12px}
.seg button{flex:1;background:none;border:0;color:var(--m);padding:11px 2px;border-radius:11px;font:600 13px inherit;font-family:inherit;transition:background .2s,color .2s}
.seg button.on{background:linear-gradient(135deg,var(--a),color-mix(in srgb,var(--a) 70%,var(--a2)));color:#fff;box-shadow:0 4px 14px color-mix(in srgb,var(--a) 40%,transparent)}
.sl{margin:6px 0 14px}.sl .lab{display:flex;justify-content:space-between;font-size:14px;color:var(--m);margin-bottom:8px}.sl .lab b{color:var(--t)}
input[type=range]{-webkit-appearance:none;appearance:none;width:100%;height:34px;background:transparent}
input[type=range]::-webkit-slider-runnable-track{height:8px;border-radius:8px;background:linear-gradient(90deg,var(--a) var(--v,50%),var(--p2) var(--v,50%))}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:26px;height:26px;border-radius:50%;background:#fff;margin-top:-9px;box-shadow:0 2px 10px rgba(0,0,0,.4)}
input[type=range]::-moz-range-track{height:8px;border-radius:8px;background:var(--p2)}input[type=range]::-moz-range-progress{height:8px;border-radius:8px;background:var(--a)}
input[type=range]::-moz-range-thumb{width:26px;height:26px;border-radius:50%;background:#fff;border:0}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.btn{background:var(--p2);border:1px solid var(--line);color:var(--t);border-radius:16px;padding:14px 6px;font:600 12.5px inherit;font-family:inherit;display:flex;flex-direction:column;align-items:center;gap:6px;transition:transform .12s,background .2s}
.btn:active{transform:scale(.95);background:color-mix(in srgb,var(--a) 35%,var(--p2))}.btn .i{font-size:22px;line-height:1}
.btn.on{background:color-mix(in srgb,var(--a) 28%,var(--p2));border-color:color-mix(in srgb,var(--a) 60%,transparent)}
.big{width:100%;padding:15px;border:0;border-radius:16px;background:linear-gradient(135deg,var(--a),var(--a2));color:#fff;font:700 15px inherit;font-family:inherit;letter-spacing:.06em;margin-top:4px}
.big:active{transform:scale(.98)}.big.ghost{background:var(--p2);color:var(--t)}
.tog{display:flex;justify-content:space-between;align-items:center;padding:8px 0 12px}.tog div{font-size:14.5px}.tog small{display:block;color:var(--m);font-size:12.5px}
.sw{width:52px;height:31px;border-radius:20px;background:var(--p2);position:relative;flex:none;border:0;transition:background .2s}.sw:after{content:"";position:absolute;width:25px;height:25px;border-radius:50%;background:#fff;top:3px;left:3px;transition:left .2s}
.sw.on{background:var(--a)}.sw.on:after{left:24px}
.media{display:flex;align-items:center;gap:10px}.media .np{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:600}
.media button{width:46px;height:46px;border-radius:50%;border:0;background:var(--p2);color:var(--t);font-size:18px}.media button.pp{background:var(--a);color:#fff;width:54px;height:54px}
.search{width:100%;padding:13px 16px;border-radius:14px;border:1px solid var(--line);background:var(--p);color:var(--t);font:15px inherit;font-family:inherit;margin-bottom:14px;outline:none}
.games{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.gm{border-radius:14px;overflow:hidden;background:var(--p2);aspect-ratio:2/3;position:relative;border:1px solid var(--line)}
.gm img{width:100%;height:100%;object-fit:cover;display:block}.gm .ph{position:absolute;inset:0;display:grid;place-items:center;font-weight:800;font-size:34px;letter-spacing:.04em;color:rgba(255,255,255,.85);background:linear-gradient(160deg,hsl(var(--h,220) 55% 38%),hsl(calc(var(--h,220) + 40) 45% 16%))}
.gm .t{position:absolute;left:0;right:0;bottom:0;padding:18px 7px 6px;font-size:11px;font-weight:600;background:linear-gradient(transparent,rgba(0,0,0,.85));white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gm.run{outline:2px solid var(--g)}a.gm{color:#fff;text-decoration:none;display:block}
nav{position:fixed;left:12px;right:12px;bottom:calc(env(safe-area-inset-bottom) + 10px);display:flex;background:color-mix(in srgb,var(--p) 82%,transparent);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);border:1px solid var(--line);border-radius:24px;padding:6px;z-index:5;box-shadow:0 10px 30px rgba(0,0,0,.4)}
nav button{flex:1;border:0;background:none;color:var(--m);padding:8px 0 6px;border-radius:18px;font:600 10.5px inherit;min-width:0;font-family:inherit;display:flex;flex-direction:column;align-items:center;gap:3px}
nav button .i{font-size:20px}nav button.on{color:#fff;background:color-mix(in srgb,var(--a) 30%,transparent)}
.tab{display:none;animation:in .25s ease}.tab.on{display:block}@keyframes in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
#msg{position:fixed;left:50%;bottom:calc(env(safe-area-inset-bottom) + 92px);transform:translateX(-50%) translateY(10px);background:var(--t);color:var(--bg);padding:10px 18px;border-radius:22px;font-weight:700;font-size:14px;opacity:0;transition:.25s;z-index:9;pointer-events:none;max-width:88vw;text-align:center}
#msg.on{opacity:1;transform:translateX(-50%)}
.sheet{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;align-items:flex-end;z-index:8}.sheet.on{display:flex}
.sheet>div{background:var(--p);width:100%;border-radius:26px 26px 0 0;padding:22px 18px calc(env(safe-area-inset-bottom) + 22px);animation:up .25s ease}
@keyframes up{from{transform:translateY(40px);opacity:.4}to{transform:none;opacity:1}}.sheet h3{font-size:21px;margin-bottom:4px}.sheet p{color:var(--m);margin-bottom:16px;font-size:14px}
#login{position:fixed;inset:0;background:var(--bg);display:none;flex-direction:column;align-items:center;justify-content:center;gap:16px;z-index:20;padding:24px;text-align:center}
#login.on{display:flex}#login input{font-size:32px;letter-spacing:.4em;text-align:center;width:9em;padding:12px;border-radius:16px;border:1px solid var(--line);background:var(--p);color:var(--t);outline:none}
#login .logo{width:64px;height:64px;font-size:30px;border-radius:18px}.muted{color:var(--m);font-size:13.5px}
.chips{display:flex;gap:8px;flex-wrap:wrap}.chip{background:var(--p2);padding:7px 12px;border-radius:20px;font-size:12.5px;color:var(--m)}.chip b{color:var(--t)}
</style></head><body>
<div id="login"><div class="logo">V</div><div class="brand" style="font-size:20px">VANTA</div>
<div class="muted">Type the PIN shown in Vanta › Settings › Phone remote</div>
<input id="pin" inputmode="numeric" maxlength="6" autocomplete="one-time-code"><button class="big" style="max-width:280px" onclick="login()">CONNECT</button>
<div class="muted" id="lerr"></div></div>

<header><div class="logo">V</div><div class="brand">VANTA<small id="dev">Remote</small></div><div class="dot" id="conn"><i></i><span>Live</span></div></header>

<section class="tab on" id="t-now">
 <div class="card hero" id="hero"><div class="art" id="art"></div><div class="k" id="hk">IN THE HUB</div><div class="n" id="hn">Ready to play</div><div class="s" id="hs"></div></div>
 <div class="card"><div class="rings" id="rings"></div></div>
 <div class="card"><h2>CPU <b id="cpuv"></b></h2><canvas id="spark"></canvas></div>
 <div class="card"><h2>BATTERY <b id="batv"></b></h2>
  <div class="row">Draw<b id="bw">–</b></div><div class="row">Time left<b id="bl">–</b></div><div id="bgr" style="display:none;margin-top:8px;padding:10px 12px;border-radius:12px;background:color-mix(in srgb,var(--g) 14%,transparent);color:var(--t);font-size:13.5px"><b style="color:var(--g)">Battery goal</b> · <span id="bg"></span></div></div>
 <div class="card"><h2>PLAY TIME</h2><div class="chips" id="pt"></div></div>
</section>

<section class="tab" id="t-ctl">
 <div class="card"><h2>PERFORMANCE</h2><div class="seg" id="prof"></div>
  <div id="tdpbox"><div class="sl"><div class="lab">TDP<b id="tdpv"></b></div><input type="range" id="tdp" min="5" max="30" step="1"></div>
  <div class="tog"><div>Auto TDP<small id="atdps">Finds the lowest wattage that holds your FPS</small></div><button class="sw" id="atdp" onclick="act('auto_tdp')"></button></div></div>
  <h2 style="margin-top:4px">BATTERY GOAL</h2><div class="seg" id="goal"></div>
  <h2 style="margin-top:4px">SLEEP TIMER <b id="slv"></b></h2><div class="seg" id="slp"></div></div>
 <div class="card"><h2>SCREEN</h2><div class="sl"><div class="lab">Brightness<b id="brv"></b></div><input type="range" id="br" min="0" max="100" step="5"></div>
  <div class="seg" id="hz"></div></div>
 <div class="card"><h2>MEDIA & SOUND</h2><div class="media"><div class="np" id="np">Nothing playing</div>
  <button onclick="act('prev')">⏮</button><button class="pp" onclick="act('play')">⏯</button><button onclick="act('next')">⏭</button></div>
  <div class="grid" style="margin-top:14px"><button class="btn" onclick="act('vol_down')"><span class="i">🔉</span>VOL −</button><button class="btn" onclick="act('mute')"><span class="i">🔇</span>MUTE</button><button class="btn" onclick="act('vol_up')"><span class="i">🔊</span>VOL +</button></div></div>
 <div class="card"><h2>ACTIONS</h2><div class="grid">
  <button class="btn" onclick="act('boost')"><span class="i">🚀</span>BOOST</button><button class="btn" id="fo" onclick="act('focus')"><span class="i">🎯</span>FOCUS</button>
  <button class="btn" onclick="act('screenshot')"><span class="i">📸</span>SCREENSHOT</button><button class="btn" id="su" onclick="act('suspend')"><span class="i">⏸</span>SUSPEND</button>
  <button class="btn" onclick="act('quick')"><span class="i">⚡</span>QUICK MENU</button><button class="btn" onclick="act('hub')"><span class="i">🏠</span>OPEN HUB</button>
  <button class="btn" id="ov" onclick="act('overlay')"><span class="i">📊</span>STATS OVERLAY</button><button class="btn" onclick="act('discord_mute')"><span class="i">🎙</span>DISCORD MUTE</button></div></div>
</section>

<section class="tab" id="t-games"><input class="search" id="q" placeholder="Search your games" oninput="drawGames()"><div class="games" id="games"></div></section>

<section class="tab" id="t-shots"><div class="games" id="shots" style="grid-template-columns:repeat(2,1fr)"></div></section>

<section class="tab" id="t-pad">
 <div id="padoff" class="card muted" style="display:none">Touchpad and keyboard are off. Turn them on in Vanta › Settings › Phone touchpad &amp; keyboard.</div>
 <div id="padon"><div id="tp" style="height:46vh;border-radius:22px;background:var(--p);border:1px solid var(--line);display:grid;place-items:center;color:var(--m);font-size:13px;touch-action:none;margin-bottom:12px">Drag to move · tap to click · two fingers to scroll</div>
 <div class="grid" style="grid-template-columns:1fr 1fr;margin-bottom:14px"><button class="btn" onclick="raw('click','left')">LEFT CLICK</button><button class="btn" onclick="raw('click','right')">RIGHT CLICK</button></div>
 <div class="card"><h2>KEYBOARD</h2><div style="display:flex;gap:8px"><input class="search" id="kt" style="margin:0" placeholder="Type here, then Send" onkeydown="if(event.key==='Enter'){sendText()}"><button class="big" style="width:auto;padding:0 18px;margin:0" onclick="sendText()">SEND</button></div>
 <div class="grid" style="grid-template-columns:repeat(5,1fr);margin-top:12px">
 <button class="btn" onclick="raw('key','enter')">ENTER</button><button class="btn" onclick="raw('key','back')">⌫</button><button class="btn" onclick="raw('key','esc')">ESC</button><button class="btn" onclick="raw('key','tab')">TAB</button><button class="btn" onclick="raw('key','win')">WIN</button>
 <button class="btn" onclick="raw('key','left')">←</button><button class="btn" onclick="raw('key','up')">↑</button><button class="btn" onclick="raw('key','down')">↓</button><button class="btn" onclick="raw('key','right')">→</button><button class="btn" onclick="raw('key','space')">SPACE</button></div></div></div>
</section>

<section class="tab" id="t-more">
 <div class="card"><h2>BREAK REMINDERS</h2><div class="seg" id="brk"></div><h2 style="margin-top:6px">DAILY LIMIT</h2><div class="seg" id="lim"></div></div>
 <div class="card"><h2>THIS DEVICE</h2><div id="info"></div></div>
 <div class="card"><h2>APP</h2><div class="muted" style="margin-bottom:12px">Add this page to your home screen (Share › Add to Home Screen, or the browser menu) to open it like an app.</div>
  <button class="big ghost" onclick="logout()">FORGET PIN</button></div>
</section>

<nav><button class="on" data-t="now"><span class="i">◉</span>Now</button><button data-t="ctl"><span class="i">⚙</span>Control</button><button data-t="games"><span class="i">▦</span>Games</button><button data-t="shots"><span class="i">▣</span>Shots</button><button data-t="pad"><span class="i">⌨</span>Pad</button><button data-t="more"><span class="i">⋯</span>More</button></nav>
<div class="sheet" id="sheet" onclick="if(event.target===this)closeSheet()"><div><h3 id="sh-n"></h3><p id="sh-s"></p><button class="big" id="sh-play">▶  PLAY</button><button class="big ghost" style="margin-top:10px" onclick="closeSheet()">CANCEL</button></div></div>
<div id="msg"></div>
<script>
const $=id=>document.getElementById(id);
let PIN=new URLSearchParams(location.search).get('pin')||localStorage.getItem('vanta_pin')||'';
if(new URLSearchParams(location.search).get('pin')){localStorage.setItem('vanta_pin',PIN);history.replaceState(null,'','/')}
let S=null,busy=0,lastDrag=0;
function toast(t){const m=$('msg');m.textContent=t;m.classList.add('on');clearTimeout(m._t);m._t=setTimeout(()=>m.classList.remove('on'),1700)}
function buzz(){try{navigator.vibrate&&navigator.vibrate(12)}catch(e){}}
async function api(p,opt){const r=await fetch(p,Object.assign({headers:{'X-Vanta-Pin':PIN},cache:'no-store'},opt||{}));const j=await r.json().catch(()=>({}));if(r.status==403||r.status==429){showLogin(j.error);throw 0}return j}
async function act(a,v){buzz();try{const j=await api('/api/do?a='+a+(v!==undefined?'&v='+encodeURIComponent(v):''),{method:'POST'});toast(j.msg||'Done');setTimeout(poll,350)}catch(e){if(e!==0)toast('Vanta is not reachable')}}
function showLogin(err){$('login').classList.add('on');$('lerr').textContent=PIN&&err?err:'';setTimeout(()=>$('pin').focus(),50)}
function login(){PIN=$('pin').value.trim();localStorage.setItem('vanta_pin',PIN);$('login').classList.remove('on');poll()}
$('pin').addEventListener('keydown',e=>{if(e.key==='Enter')login()});
function logout(){localStorage.removeItem('vanta_pin');PIN='';showLogin()}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{buzz();document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('on',x===b));
 document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('on',t.id==='t-'+b.dataset.t));window.scrollTo({top:0});if(b.dataset.t==='games')drawGames();if(b.dataset.t==='shots')loadShots()});
function seg(id,opts,cur,a){const el=$(id);const key=JSON.stringify([opts,cur]);if(el._k===key)return;el._k=key;el.innerHTML='';
 for(const [v,l] of opts){const b=document.createElement('button');b.textContent=l;if(String(v)===String(cur))b.className='on';b.onclick=()=>act(a,v);el.appendChild(b)}}
function ringSvg(f,col){const r=30,c=2*Math.PI*r;f=Math.max(0,Math.min(1,f||0));
 return `<svg viewBox="0 0 78 78"><circle cx="39" cy="39" r="${r}" fill="none" stroke="var(--p2)" stroke-width="7"/><circle cx="39" cy="39" r="${r}" fill="none" stroke="${col}" stroke-width="7" stroke-linecap="round" stroke-dasharray="${c*f} ${c}" transform="rotate(-90 39 39)" style="transition:stroke-dasharray .6s"/></svg>`}
function fmt(s){s=Math.round(s||0);const h=Math.floor(s/3600),m=Math.floor(s%3600/60);return h?`${h}h ${String(m).padStart(2,'0')}m`:`${m} min`}
function theme(t){if(!t)return;const r=document.documentElement.style;for(const [k,v] of Object.entries({bg:'--bg',panel:'--p',panel2:'--p2',text:'--t',muted:'--m',accent:'--a',accent2:'--a2',good:'--g',warn:'--w',danger:'--d'}))if(t[k])r.setProperty(v,t[k]);
 document.querySelector('meta[name=theme-color]').content=t.bg||'#0b0f17'}
function spark(h){const cv=$('spark'),dpr=devicePixelRatio||1,w=cv.clientWidth,hh=cv.clientHeight;cv.width=w*dpr;cv.height=hh*dpr;const x=cv.getContext('2d');x.scale(dpr,dpr);
 if(!h||h.length<2)return;const cs=getComputedStyle(document.documentElement),a=cs.getPropertyValue('--a').trim()||'#3d8bff';
 x.beginPath();h.forEach((v,i)=>{const px=i/(h.length-1)*w,py=hh-4-v*(hh-8);i?x.lineTo(px,py):x.moveTo(px,py)});x.strokeStyle=a;x.lineWidth=2.2;x.lineJoin='round';x.stroke();
 x.lineTo(w,hh);x.lineTo(0,hh);x.closePath();const g=x.createLinearGradient(0,0,0,hh);g.addColorStop(0,a+'55');g.addColorStop(1,a+'00');x.fillStyle=g;x.fill()}
function slider(id,val,lo,hi,label,fmtv,a){const el=$(id);el.min=lo;el.max=hi;
 const paint=()=>{el.style.setProperty('--v',((el.value-lo)/(hi-lo)*100)+'%');$(label).textContent=fmtv(el.value)};
 if(!el._w){el._w=1;el.addEventListener('input',()=>{lastDrag=Date.now();paint()});el.addEventListener('change',()=>{lastDrag=Date.now();act(a,el.value)})}
 if(Date.now()-lastDrag>2500&&val!=null)el.value=val;paint()}
function render(){const s=S;if(!s)return;theme(s.theme);events(s.events);$('padon').style.display=s.pad_ok?'block':'none';$('padoff').style.display=s.pad_ok?'none':'block';$('dev').textContent=s.device||'Remote';
 const g=s.game;$('hk').textContent=g?'NOW PLAYING':'IN THE HUB';$('hn').textContent=g?g.name:(s.last?s.last:'Ready to play');
 $('hs').textContent=g?(fmt(g.time)+(s.fps?' · '+s.fps+' FPS':'')):(s.last?'Last played':'');
 const art=g&&g.cover?'/api/cover?id='+encodeURIComponent(g.id)+'&pin='+PIN:(s.last_cover?'/api/cover?id='+encodeURIComponent(s.last_id)+'&pin='+PIN:'');
 if($('art')._u!==art){$('art')._u=art;$('art').style.backgroundImage=art?`url("${art}")`:''}
 const R=[['FPS',s.fps??'–',s.fps?Math.min(1,s.fps/(s.hz||60)):0,'var(--a2)'],['CPU',s.cpu!=null?s.cpu+'%':'–',(s.cpu||0)/100,'var(--a)'],
  ['GPU',s.gpu!=null?s.gpu+'%':'–',(s.gpu||0)/100,'var(--a)'],['BAT',s.bat!=null?s.bat+'%':'–',(s.bat||0)/100,(s.bat||100)<20?'var(--d)':'var(--g)']];
 $('rings').innerHTML=R.map(([l,v,f,c])=>`<div class="ring" style="position:relative">${ringSvg(f,c)}<div style="position:absolute;inset:0;display:grid;place-items:center;top:-4px"><b>${v}</b></div><span>${l}</span></div>`).join('');
 $('cpuv').textContent=s.cpu!=null?s.cpu+'%':'';spark(s.cpu_hist);
 $('batv').textContent=s.bat!=null?s.bat+'%'+(s.charging?' · charging':s.ac?' · plugged in':''):'';$('bw').textContent=s.draw?s.draw.toFixed(1)+' W':'–';$('bl').textContent=s.left?fmt(s.left):'–';
 $('bgr').style.display=s.goal?'block':'none';$('bg').textContent=s.goal_status||'';
 $('pt').innerHTML=`<span class="chip">Today <b>${fmt(s.today)}</b>${s.limit?' of '+fmt(s.limit*60):''}</span><span class="chip">7 days <b>${fmt(s.week)}</b></span>`+(s.streak>1?`<span class="chip">Streak <b>${s.streak} days</b></span>`:'')+(s.brk?`<span class="chip">Breaks every <b>${s.brk} min</b></span>`:'');
 seg('prof',[['saver','Saver'],['balanced','Balanced'],['max','Max']],s.profile,'profile');
 $('tdpbox').style.display=s.legion?'block':'none';if(s.legion){slider('tdp',s.tdp_set,5,s.tdp_max,'tdpv',v=>v+' W'+(s.tdp_now&&s.tdp_now!=v?` · now ${s.tdp_now} W`:''),'tdp_set');
  $('atdp').classList.toggle('on',!!s.auto_tdp);$('atdps').textContent=s.auto_tdp?`Holding ${s.auto_tdp_target} FPS`:'Finds the lowest wattage that holds your FPS'}
 seg('slp',[[0,'Off'],[30,'30m'],[60,'1h'],[90,'1.5h'],[-1,'After game']],s.sleep_sel,'sleep');$('slv').textContent=s.sleep_label&&s.sleep_label!=='Off'?s.sleep_label:'';
 seg('goal',s.goal_opts.map(m=>[m,m?(m%60?(m/60).toFixed(1):m/60)+'h':'Off']),s.goal,'bgoal');
 slider('br',s.bright,0,100,'brv',v=>v+'%','bright');
 if(s.rates&&s.rates.length)seg('hz',s.rates.map(r=>[r,r+' Hz']),s.hz,'hz');
 $('np').textContent=s.np||'Nothing playing';$('fo').classList.toggle('on',!!s.focus);$('su').classList.toggle('on',!!s.suspended);$('ov').classList.toggle('on',!!s.overlay);
 const lb=m=>m?(m<60?m+'m':(m%60?(m/60).toFixed(1):m/60)+'h'):'Off';seg('brk',s.brk_opts.map(m=>[m,lb(m)]),s.brk,'break');seg('lim',s.lim_opts.map(m=>[m,lb(m)]),s.limit,'limit');
 $('info').innerHTML=[['App',s.app],['Version',s.version],['Profile',s.profile||'Custom'],['Refresh',s.hz?s.hz+' Hz':'–']].map(([a,b])=>`<div class="row">${a}<b>${b||'–'}</b></div>`).join('');
 if(document.querySelector('#t-games.on'))drawGames()}
function drawGames(){if(!S)return;const q=$('q').value.toLowerCase(),el=$('games');const list=(S.games||[]).filter(g=>!q||g.name.toLowerCase().includes(q));
 const key=JSON.stringify([q,list.map(g=>g.id),S.game&&S.game.id]);if(el._k===key)return;el._k=key;
 el.innerHTML=list.map(g=>`<div class="gm${S.game&&S.game.id===g.id?' run':''}" data-id="${encodeURIComponent(g.id)}">${g.cover?`<img loading="lazy" src="/api/cover?id=${encodeURIComponent(g.id)}&pin=${PIN}" onerror="this.remove()">`:''}<div class="ph" style="--h:${[...g.name].reduce((h,c)=>(h*31+c.charCodeAt(0))%360,7)};${g.cover?'z-index:-1':''}">${g.name.split(/\s+/).filter(w=>/^[A-Za-z0-9]/.test(w)).slice(0,2).map(w=>w[0].toUpperCase()).join('').replace(/</g,'')}</div><div class="t">${g.name.replace(/</g,'&lt;')}</div></div>`).join('')||'<div class="muted">No games found</div>';
 el.querySelectorAll('.gm').forEach(d=>d.onclick=()=>openSheet(decodeURIComponent(d.dataset.id)))}
function openSheet(id){const g=S.games.find(x=>x.id===id);if(!g)return;buzz();$('sh-n').textContent=g.name;$('sh-s').textContent=[g.source,g.played?fmt(g.played*60)+' played':'Not played yet'].filter(Boolean).join(' · ');
 const running=S.game&&S.game.id===id;$('sh-play').textContent=running?'● PLAYING':'▶  PLAY';$('sh-play').onclick=()=>{if(!running)act('launch',id);closeSheet()};$('sheet').classList.add('on')}
function closeSheet(){$('sheet').classList.remove('on')}
async function raw(a,v){try{await fetch('/api/do?a='+a+'&v='+encodeURIComponent(v),{method:'POST',headers:{'X-Vanta-Pin':PIN}});if(a==='click'||a==='key')buzz()}catch(e){}}
function sendText(){const t=$('kt').value;if(!t)return;raw('type',t);$('kt').value='';toast('Sent')}
(function(){const el=$('tp');let pts={},acc=[0,0],moved=0,t0=0,two=0,last=null;
 setInterval(()=>{if(Math.abs(acc[0])>=1||Math.abs(acc[1])>=1){const dx=Math.round(acc[0]),dy=Math.round(acc[1]);acc=[acc[0]-dx,acc[1]-dy];raw(two?'scroll':'mouse',two?String(-dy*6):dx+','+dy)}},40);
 el.addEventListener('pointerdown',e=>{el.setPointerCapture(e.pointerId);pts[e.pointerId]=[e.clientX,e.clientY];if(Object.keys(pts).length===1){moved=0;t0=Date.now();two=0}else two=1});
 el.addEventListener('pointermove',e=>{const p=pts[e.pointerId];if(!p)return;const dx=e.clientX-p[0],dy=e.clientY-p[1];pts[e.pointerId]=[e.clientX,e.clientY];
  moved+=Math.abs(dx)+Math.abs(dy);const sp=1.4+Math.min(2,Math.hypot(dx,dy)/12);if(two){acc[1]+=dy/2}else{acc[0]+=dx*sp;acc[1]+=dy*sp}});
 const up=e=>{delete pts[e.pointerId];if(Object.keys(pts).length===0){if(moved<8&&Date.now()-t0<300)raw('click',two?'right':'left');two=0}};
 el.addEventListener('pointerup',up);el.addEventListener('pointercancel',up)})();
let seenEv=+(localStorage.getItem('vanta_ev')||-1);
function events(l){if(!l||!l.length)return;const top=l[l.length-1].id;if(seenEv<0||top<seenEv){seenEv=top;localStorage.setItem('vanta_ev',top);return}
 const nw=l.filter(e=>e.id>seenEv);if(nw.length){const e=nw[nw.length-1];const m=$('msg');m.textContent=e.title+(e.body?' · '+e.body:'');m.classList.add('on');clearTimeout(m._t);m._t=setTimeout(()=>m.classList.remove('on'),5000);
 try{navigator.vibrate&&navigator.vibrate([60,40,60])}catch(x){}seenEv=top;localStorage.setItem('vanta_ev',top)}}
async function loadShots(){const el=$('shots');try{const j=await api('/api/shots');const l=j.shots||[];
 el.innerHTML=l.map(x=>`<a class="gm" style="aspect-ratio:16/10" href="/api/shot?i=${x.i}&pin=${PIN}" target="_blank"><img loading="lazy" src="/api/shot?i=${x.i}&pin=${PIN}"><div class="t">${new Date(x.time*1000).toLocaleString([], {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}</div></a>`).join('')||'<div class="muted">No screenshots yet. Take one from Control › Screenshot.</div>'}catch(e){}}
async function poll(){if(busy)return;busy=1;try{const j=await api('/api/state');if(j.error){showLogin(j.error)}else{S=j;$('conn').classList.remove('off');$('conn').lastChild.textContent='Live';render()}}
 catch(e){if(e!==0){$('conn').classList.add('off');$('conn').lastChild.textContent='Offline'}}finally{busy=0}}
if(!PIN)showLogin();else poll();setInterval(()=>{if(!document.hidden&&PIN)poll()},1500);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll()});
</script></body></html>"""

REMOTE_ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#3d8bff"/><stop offset="1" stop-color="#7c5cff"/></linearGradient></defs><rect width="512" height="512" rx="112" fill="url(#g)"/><path d="M136 150h64l56 150 56-150h64L290 362h-68z" fill="#fff"/></svg>"""

REMOTE_MANIFEST = """{"name":"Vanta","short_name":"Vanta","start_url":"/","display":"standalone","background_color":"#0b0f17","theme_color":"#0b0f17","icons":[{"src":"/icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}]}"""


class RemoteServer:
    def __init__(self, port, pin, state_fn, action_fn, cover_fn=None, shots_fn=None):
        import threading
        from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
        from urllib.parse import urlparse, parse_qs
        server = self
        self.pin = str(pin)
        self.fails = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype + ("" if ctype.startswith("image/") else "; charset=utf-8"))
                self.send_header("Cache-Control", "max-age=86400" if ctype.startswith("image/") else "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _ok_pin(self, q):
                now = time.time()
                server.fails = [t for t in server.fails if now - t < 60]
                if len(server.fails) >= 5:
                    return None  # locked for a minute after 5 wrong PINs
                given = self.headers.get("X-Vanta-Pin") or q.get("pin", [""])[0]
                good = bool(given) and hmac.compare_digest(given, server.pin)
                if not good and given:
                    server.fails.append(now)
                return good

            def _handle(self, method):
                u = urlparse(self.path)
                q = parse_qs(u.query)
                ok = self._ok_pin(q)
                if u.path in ("/", "/index.html"):
                    return self._send(200, REMOTE_PAGE, "text/html")  # the page holds no data; the API needs the PIN
                if u.path == "/manifest.json":
                    return self._send(200, REMOTE_MANIFEST, "application/manifest+json")
                if u.path == "/icon.svg":
                    return self._send(200, REMOTE_ICON, "image/svg+xml")
                if ok is None:
                    return self._send(429, json.dumps({"error": "Too many wrong PINs, wait a minute"}))
                if not ok:
                    return self._send(403, json.dumps({"error": "Wrong PIN"}))
                if u.path == "/api/state":
                    return self._send(200, json.dumps(state_fn()))
                if u.path == "/api/do" and method == "POST":
                    msg = action_fn(q.get("a", [""])[0], q.get("v", [None])[0])
                    return self._send(200, json.dumps({"msg": msg}))
                if u.path == "/api/shots" and shots_fn:
                    return self._send(200, json.dumps({"shots": shots_fn()}))
                if u.path == "/api/shot" and shots_fn:
                    try:
                        path = shots_fn(int(q.get("i", ["-1"])[0]))
                    except ValueError:
                        path = None
                    ext = os.path.splitext(path or "")[1].lower()
                    types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
                    if path and ext in types and os.path.isfile(path):
                        with open(path, "rb") as f:
                            return self._send(200, f.read(), types[ext])
                    return self._send(404, json.dumps({"error": "No picture"}))
                if u.path == "/api/cover" and cover_fn:
                    path = cover_fn(q.get("id", [""])[0])
                    ext = os.path.splitext(path or "")[1].lower()
                    types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
                    if path and ext in types and os.path.isfile(path):
                        with open(path, "rb") as f:
                            return self._send(200, f.read(), types[ext])
                    return self._send(404, json.dumps({"error": "No cover"}))
                self._send(404, json.dumps({"error": "Not found"}))

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

        self.httpd = ThreadingHTTPServer(("0.0.0.0", port), H)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


# =====================================================================  settings sync through OneDrive
def sync_folder():
    for env in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        p = os.environ.get(env)
        if p and os.path.isdir(p):
            return os.path.join(p, "Vanta")
    return None


# =====================================================================  game art from Steam (no key needed)
# Steam's public store search finds a game's appid by name; its image CDN serves the library art.
STEAM_ART_URLS = ["https://shared.steamstatic.com/store_item_assets/steam/apps/{id}/{f}",
                  "https://cdn.cloudflare.steamstatic.com/steam/apps/{id}/{f}",
                  "https://cdn.akamai.steamstatic.com/steam/apps/{id}/{f}"]
_EDITIONS = {"remastered", "remaster", "completeedition", "gameoftheyearedition", "gameoftheyear", "goty", "gotyedition",
             "definitiveedition", "enhancededition", "ultimateedition", "deluxeedition", "directorscut", "anniversaryedition",
             "standardedition", "edition", "remake", "hd", "special edition", "specialedition", "legendaryedition"}
_ART_SKIP = ("soundtrack", " ost", "demo", "dlc", "season pass", "artbook", "bundle", "upgrade", "expansion pass", "playtest")


def _norm_title(t):
    t = t.lower().replace("&", "and")
    t = re.sub(r"[™®©]", "", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def steam_appid_for(name):
    """Steam appid for a game title (Epic/EA/Xbox/... games that are also on Steam), or None."""
    import difflib
    import urllib.parse
    d = _get_json("https://store.steampowered.com/api/storesearch/?term=" + urllib.parse.quote(name) + "&l=english&cc=US")
    items = [i for i in d.get("items", []) if i.get("type") == "app"
             and not any(w in i.get("name", "").lower() for w in _ART_SKIP)]
    want = _norm_title(name)
    for i in items:
        if _norm_title(i["name"]) == want:
            return i["id"]
    for i in items:  # "The Witcher 3: Wild Hunt" -> "The Witcher 3: Wild Hunt – Remastered"
        n = _norm_title(i["name"])
        if n.startswith(want) and n[len(want):] in _EDITIONS:
            return i["id"]
    best, score = None, 0.0
    for i in items:
        r = difflib.SequenceMatcher(None, want, _norm_title(i["name"])).ratio()
        if r > score:
            best, score = i["id"], r
    return best if score >= 0.86 else None


def _download_image(url, path):
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Vanta"})
        with urllib.request.urlopen(req, timeout=20) as r:
            blob = r.read()
    except (urllib.error.URLError, OSError, ValueError):
        return False
    if len(blob) < 2048:
        return False
    try:
        from PIL import Image
        import io
        with Image.open(io.BytesIO(blob)) as im:
            im.verify()
    except Exception:
        return False
    with open(path + ".part", "wb") as f:
        f.write(blob)
    os.replace(path + ".part", path)
    return True


def _portrait_from_header(header_path, out_path):
    """Make a 600x900 cover from a wide header: blurred fill behind, the header centred on top."""
    from PIL import Image, ImageFilter, ImageEnhance, ImageOps
    with Image.open(header_path) as im:
        im = im.convert("RGB")
        bg = ImageOps.fit(im, (600, 900), Image.LANCZOS).filter(ImageFilter.GaussianBlur(28))
        bg = ImageEnhance.Brightness(bg).enhance(0.55)
        w = 600
        h = int(im.height * w / im.width)
        fg = im.resize((w, h), Image.LANCZOS)
        bg.paste(fg, (0, (900 - h) // 2))
        bg.save(out_path, "JPEG", quality=90)
    return out_path


def steam_art(appid, kind="cover"):
    """Path to cached art for a Steam app: kind 'cover' (600x900) or 'hero' (wide backdrop). None if Steam has none."""
    os.makedirs(COVER_DIR, exist_ok=True)
    path = os.path.join(COVER_DIR, f"steam_{appid}_{kind}.jpg")
    miss = path + ".none"
    if os.path.exists(path):
        return path
    if os.path.exists(miss) and time.time() - os.path.getmtime(miss) < 7 * 86400:
        return None
    files = ["library_600x900_2x.jpg", "library_600x900.jpg"] if kind == "cover" else ["library_hero.jpg"]
    for f in files:
        for u in STEAM_ART_URLS:
            if _download_image(u.format(id=appid, f=f), path):
                return path
    # Newer games keep library art in hashed folders: fall back to the store's own image links.
    try:
        d = _get_json(f"https://store.steampowered.com/api/appdetails?appids={appid}&l=english")
        data = (d.get(str(appid)) or {}).get("data") or {}
    except Exception:
        data = {}
    if kind == "cover" and data.get("header_image"):
        tmp = path + ".header"
        if _download_image(data["header_image"], tmp):
            try:
                _portrait_from_header(tmp, path)
                return path
            except Exception:
                pass
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    if kind == "hero":
        for key in ("background_raw", "background"):
            if data.get(key) and _download_image(data[key], path):
                return path
    open(miss, "w").close()
    return None


# =====================================================================  community presets (Deck Verified)
# Deck Verified (https://deckverified.games, open source: github.com/DeckSettings) collects player reports of the
# settings they use on handhelds, including the Legion Go and Legion Go 2. Most reports are from SteamOS / Linux:
# wattage, FPS caps and in-game graphics settings carry over to Windows on the same hardware; exact FPS can differ.
DV_API = "https://deckverified.games/deck-verified/api/v1"
DV_SITE = "https://deckverified.games"
DV_NEW_REPORT = "https://deckverified.games/submit-report"
DV_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Vanta", "community")
# How close each Deck Verified device is to each Legion Go. Lower tier = better match.
DV_TIERS = {
    "go1": [({"Lenovo Legion Go"}, "LEGION GO", "Reported on the Legion Go"),
            ({"Lenovo Legion Go S Z1E", "Lenovo Legion Go S", "ASUS ROG Ally Z1 Extreme", "ROG Ally Z1 Extreme", "ASUS ROG Ally X",
              "ROG Ally X"}, "SAME CHIP", "Same Ryzen Z1 Extreme chip as the Legion Go"),
            ({"Lenovo Legion Go 2"}, "LEGION GO 2", "Legion Go 2 report: that chip is faster, so aim a little lower")],
    "go2": [({"Lenovo Legion Go 2"}, "LEGION GO 2", "Reported on the Legion Go 2"),
            ({"Lenovo Legion Go", "Lenovo Legion Go S Z1E", "Lenovo Legion Go S", "ASUS ROG Ally Z1 Extreme", "ROG Ally Z1 Extreme",
              "ASUS ROG Ally X", "ROG Ally X"}, "Z1 EXTREME", "Z1 Extreme report: the Legion Go 2 has headroom to spare")],
}
DV_DECK = ("STEAM DECK", "Steam Deck report: a safe floor; its wattage isn't used")
DV_OS_NOTE = "Tested on SteamOS / Linux: the wattage, FPS cap and in-game settings carry over to Windows, FPS may differ a little"


def _dv_num(v, lo, hi):
    try:
        n = int(float(str(v).strip().split()[0]))
    except (ValueError, IndexError, TypeError):
        return None
    return n if lo <= n <= hi else None


_DV_KEEP = ("resolution", "preset", "quality", "upscal", "scaling", "fsr", "xess", "dlss", "frame gen", "framegen", "frame-gen",
            "fps", "frame rate", "framerate", "texture", "shadow", "ray", "sharp", "vsync", "v-sync", "lod", "detail")
_DV_SKIP = ("monitor", "display mode", "windowed", "hdr", "nvidia", "reflex", "intel® xe low", "brightness", "gamma", "language",
            "subtitle", "field of view", "fov", "motion blur", "film grain", "chromatic", "vignette")


def _dv_lines(md, limit=6):
    """'- **TEXTURE QUALITY:** High' markdown lines -> 'Texture quality: High', the settings that matter most first."""
    rows = []
    for ln in (md or "").splitlines():
        m = re.match(r"\s*[-*]\s*\*\*(.+?):?\*\*:?\s*(.+)", ln)
        if not m:
            continue
        k, v = m.group(1).strip().rstrip(":"), m.group(2).strip()
        if not v or v.lower() in ("n/a", "none", "-"):
            continue
        if k.lower() in ("value", "amount", "level") and rows:  # a sub-value of the line above
            rows[-1][1] += f" ({v})"
            continue
        rows.append([k, v])
    keep = []
    for k, v in rows:
        kl = k.lower()
        if any(x in kl for x in _DV_SKIP):
            continue
        score = 0 if any(x in kl for x in _DV_KEEP[:9]) else 1 if any(x in kl for x in _DV_KEEP) else 2
        keep.append((score, f"{k[:1].upper()}{k[1:].lower()}: {v}"))
    keep.sort(key=lambda x: x[0])  # stable: original order within each group
    return [t for _, t in keep[:limit]]


def dv_preset(report, gen, tdp_max):
    """Turn one Deck Verified report into a Vanta preset (or None if it's from a device too different to use)."""
    d = report.get("data") or {}
    dev = (d.get("device") or "").strip()
    tier, tag, why = None, None, None
    for i, (devs, tag_, why_) in enumerate(DV_TIERS[gen]):
        if dev in devs:
            tier, tag, why = i, tag_, why_
            break
    deck = tier is None and "steam deck" in dev.lower()
    if tier is None:
        if not deck:
            return None
        tier, (tag, why) = 9, DV_DECK
    fps = _dv_num(d.get("frame_limit"), 20, 240)
    if str(d.get("disable_frame_limit", "")).lower() == "on":
        fps = None
    tdp = None if deck else _dv_num(d.get("tdp_limit"), 4, 54)
    p = {"id": f"dv:{report.get('number')}", "title": (d.get("summary") or "Community preset").strip()[:80],
         "gen": gen, "tested": gen, "community": True, "tier": tier, "tag": tag, "device": dev}
    if tdp:
        p["tdp"] = min(tdp, tdp_max)
    if fps:
        p["amd"] = {"frtc": True, "frtc_fps": fps, "chill": False}
    notes = []
    res = (d.get("game_resolution") or "").strip()
    ingame = _dv_lines((d.get("game_display_settings") or "") + "\n" + (d.get("game_graphics_settings") or ""), 6)
    if res and res.lower() not in ("default", "native") and not any(n.lower().startswith("resolution:") for n in ingame):
        notes.append(f"Resolution: {res}")
    notes += ingame
    if d.get("target_framerate"):
        bat = d.get("average_battery_power_draw")
        mins = d.get("calculated_battery_life_minutes")
        extra = f", about {bat} W from the battery" if _dv_num(bat, 1, 80) else ""
        extra += f" (~{mins // 60}h {mins % 60:02d}m)" if isinstance(mins, int) and mins > 0 else ""
        notes.append(f"Aimed for {d['target_framerate']}{extra}")
    if tdp and tdp > tdp_max:
        notes.append(f"The report used {tdp} W; Vanta caps it at {tdp_max} W here")
    notes.append(why)
    if "windows" not in (d.get("os_version") or "").lower():
        notes.append(DV_OS_NOTE)
    p["notes"] = notes
    who = (report.get("user") or {}).get("login") or "a player"
    p["source"] = (f"Deck Verified report #{report.get('number')} by {who}", report.get("html_url") or DV_SITE)
    md = report.get("metadata") or {}
    p["votes"] = int(md.get("reactions_thumbs_up") or 0) - int(md.get("reactions_thumbs_down") or 0) \
        if isinstance(md, dict) else 0
    p["updated"] = report.get("updated_at") or report.get("created_at") or ""
    return p


def _dv_cache(key):
    return os.path.join(DV_DIR, re.sub(r"[^\w.-]+", "_", key)[:80] + ".json")


def dv_game(appid=None, name=None, max_age=3 * 86400, offline=False):
    """Deck Verified's data for one game ({} if it has none, None if it couldn't be reached). Cached for 3 days."""
    import urllib.parse
    import urllib.request
    key = f"app_{appid}" if appid else f"name_{(name or '').lower()}"
    path = _dv_cache(key)
    stale = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                stale = json.load(f)
            if offline or time.time() - os.path.getmtime(path) < max_age:
                return stale
        except (OSError, ValueError):
            stale = None
    if offline:
        return None
    url = f"{DV_API}/game_details?" + (f"appid={appid}" if appid else f"name={urllib.parse.quote(name or '')}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Vanta (Legion Go hub)", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
            data = json.loads(body.decode("utf-8")) if r.status != 204 and body.strip() else {}
    except Exception:
        return stale  # offline or the site is down: use what we had
    keep = {"gameName": data.get("gameName"), "appId": data.get("appId"), "summary": data.get("reports_summary") or "",
            "reports": [{k: rep.get(k) for k in ("number", "html_url", "data", "metadata", "user", "created_at", "updated_at")}
                        for rep in data.get("reports") or []]}
    for rep in keep["reports"]:
        u = rep.get("user") or {}
        rep["user"] = {"login": u.get("login")} if isinstance(u, dict) else {}
    try:
        os.makedirs(DV_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(keep, f)
    except OSError:
        pass
    return keep


def community_presets(data, gen, tdp_max, limit=4):
    """Best-matching presets for this Legion Go from Deck Verified data: closest device first, then votes, then newest."""
    out = [p for p in (dv_preset(r, gen, tdp_max) for r in (data or {}).get("reports") or []) if p]
    out.sort(key=lambda p: (p["tier"], -p["votes"], "" if not p["updated"] else "".join(chr(255 - ord(ch)) for ch in p["updated"])))
    return out[:limit]


def dv_game_page(appid=None, name=None):
    import urllib.parse
    return f"{DV_SITE}/app/{appid}" if appid else f"{DV_SITE}/game/{urllib.parse.quote(name or '')}"


# =====================================================================  share to Deck Verified (pre-filled report)
DV_FORM = "https://github.com/DeckSettings/game-reports-steamos/issues/new"
DV_DEVICES = {"go1": "Lenovo Legion Go", "go2": "Lenovo Legion Go 2"}


def dv_share_url(game, appid, gen, summary, tdp=None, fps_cap=None, avg_fps=None, watts=None, os_name="Windows 11",
                 notes=""):
    """A GitHub issue-form link with everything Vanta knows filled in (the player still reviews and submits it).
    Field ids and option texts come from the project's GAME-REPORT.yml form."""
    import urllib.parse
    q = {"template": "GAME-REPORT.yml", "title": "(Placeholder - Issue title will be automatically populated with the information provided below)",
         "summary": summary[:120], "game_name": game, "device": DV_DEVICES.get(gen, DV_DEVICES["go1"]),
         "os_version": f"{os_name} (Vanta)", "launcher": "Other"}
    if appid:
        q["app_id"] = str(appid)
    if tdp:
        q["tdp_limit"] = str(int(tdp))
    if fps_cap:
        q["frame_limit"] = str(int(fps_cap))
    if avg_fps:
        f = avg_fps
        q["target_framerate"] = "<30 FPS" if f < 30 else "30-39 FPS" if f < 40 else "40-49 FPS" if f < 50 else "50-59 FPS" if f < 60 else "60+ FPS"
    if watts and 1 <= round(watts) <= 29:
        q["average_battery_power_draw"] = str(int(round(watts)))
    q["additional_notes"] = (notes + "\n\n" if notes else "") + "Played on Windows with Vanta. Steam Play / Proton fields don't apply."
    return DV_FORM + "?" + urllib.parse.urlencode(q)


# =====================================================================  learn from your own play
def learn_from_sessions(sessions, tdp_max, tdp_min=6):
    """Look at this game's past sessions (each with avg fps, 1% low, TDP and FPS cap) and suggest a TDP.
    Returns None, or {"tdp", "why", "kind": "lower"|"raise"|"keep", "fps", "low", "mins"}."""
    use = [s for s in sessions if s.get("fps") and s.get("tdp") and s.get("dur", 0) >= 300]
    if not use:
        return None
    t = use[0]["tdp"]  # most recent wattage
    same = [s for s in use if s["tdp"] == t]
    mins = sum(s["dur"] for s in same) / 60
    if mins < 15:
        return None
    w = sum(s["dur"] for s in same)
    fps = sum(s["fps"] * s["dur"] for s in same) / w
    lows = [s for s in same if s.get("low")]
    low = sum(s["low"] * s["dur"] for s in lows) / sum(s["dur"] for s in lows) if lows else None
    cap = next((s.get("cap") for s in same if s.get("cap")), None)
    target = cap or next((x for x in (144, 120, 90, 75, 60, 45, 40, 30) if fps >= x * 0.97), 30)
    out = {"fps": fps, "low": low, "mins": mins, "tdp": t, "target": target}
    if fps >= target * 1.12 and (low is None or low >= target * 0.92) and t - 2 >= tdp_min:
        out.update(kind="lower", tdp=max(tdp_min, t - (3 if fps >= target * 1.25 else 2)),
                   why=f"You averaged {fps:.0f} FPS at {t} W over {mins:.0f} min, well above {target}: try a little less power")
    elif cap and fps < cap * 0.9 and t + 2 <= tdp_max:
        out.update(kind="raise", tdp=min(tdp_max, t + 3),
                   why=f"You averaged {fps:.0f} FPS at {t} W but capped at {cap}: a few more watts should hold the cap")
    else:
        out.update(kind="keep", why=f"{fps:.0f} FPS at {t} W over {mins:.0f} min: this wattage suits this game")
    return out


def battery_estimate(sessions, full_mwh, remaining_mwh=None):
    """Hours of play from past sessions' average battery draw: (from_full_h, from_now_h, watts) or None."""
    ws = [(s["w"], s["dur"]) for s in sessions if s.get("w") and s.get("dur", 0) >= 300]
    if not ws or not full_mwh:
        return None
    w = sum(a * b for a, b in ws) / sum(b for _, b in ws)
    if w < 1:
        return None
    return full_mwh / 1000 / w, (remaining_mwh / 1000 / w if remaining_mwh else None), w


# =====================================================================  PCGamingWiki: what a game supports
PCGW_API = "https://www.pcgamingwiki.com/w/api.php"
PCGW_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Vanta", "pcgw")
# {{Video}} / {{Input}} template parameters (PCGamingWiki editing guide)
PCGW_FIELDS = [("upscaling tech", "Upscalers"), ("framegen", "Frame generation"), ("framegen tech", "Frame gen tech"),
               ("hdr", "HDR"), ("60 fps", "60 FPS"), ("120 fps", "120+ FPS"), ("ray tracing", "Ray tracing"),
               ("controller support", "Controller"), ("full controller", "Full controller support")]


def _pcgw_value(text, name):
    m = re.search(r"\|\s*" + re.escape(name).replace(r"\ ", r"[ _]") + r"\s*=\s*([^\n|}]*)", text, re.I)
    v = m.group(1).strip() if m else ""
    return v if v and v.lower() not in ("unknown", "n/a") else ""


def pcgw_support(appid=None, name=None, max_age=14 * 86400):
    """What PCGamingWiki says a game supports: {"page", "url", "items": [(label, value)]}, {} if not found,
    None if unreachable. Cached for two weeks."""
    import urllib.parse
    key = f"app_{appid}" if appid else f"name_{(name or '').lower()}"
    path = os.path.join(PCGW_DIR, re.sub(r"[^\w.-]+", "_", key)[:80] + ".json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    try:
        if appid:
            q = {"action": "cargoquery", "format": "json", "tables": "Infobox_game", "fields": "Infobox_game._pageName=Page",
                 "where": f'Infobox_game.Steam_AppID HOLDS "{int(appid)}"', "limit": "1"}
            rows = _get_json(PCGW_API + "?" + urllib.parse.urlencode(q), timeout=20).get("cargoquery") or []
            page = rows[0]["title"]["Page"] if rows else None
        else:
            page = name
        if not page:
            out = {}
        else:
            q = {"action": "parse", "format": "json", "page": page, "prop": "wikitext", "redirects": "1"}
            d = _get_json(PCGW_API + "?" + urllib.parse.urlencode(q), timeout=25)
            text = ((d.get("parse") or {}).get("wikitext") or {}).get("*", "")
            items = []
            for field, label in PCGW_FIELDS:
                v = _pcgw_value(text, field)
                if v:
                    v = {"true": "Yes", "false": "No", "limited": "Limited", "hackable": "With a fix", "always on": "Always on"}.get(v.lower(), v)
                    items.append((label, v[:60]))
            title = (d.get("parse") or {}).get("title") or page
            out = {"page": title, "url": "https://www.pcgamingwiki.com/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
                   "items": items} if text else {}
    except Exception:
        return None
    try:
        os.makedirs(PCGW_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f)
    except OSError:
        pass
    return out


# =====================================================================  game streaming (Sunshine / Moonlight)
MOONLIGHT = [r"C:\Program Files\Moonlight Game Streaming\Moonlight.exe",
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Moonlight Game Streaming", "Moonlight.exe")]
CLOUD_SERVICES = [("Xbox Cloud Gaming", "https://www.xbox.com/play"), ("GeForce NOW", "https://play.geforcenow.com")]
GFN_APP = os.path.join(os.environ.get("LOCALAPPDATA", ""), "NVIDIA Corporation", "GeForceNOW", "CEF", "GeForceNOW.exe")


def moonlight_path():
    return next((p for p in MOONLIGHT if p and os.path.exists(p)), None)


def find_stream_hosts(timeout=2.5):
    """Sunshine (and GeForce Experience) hosts on the local network, found with an mDNS query for _nvstream._tcp.
    Returns [{"name", "ip"}]."""
    import socket
    def qname(n):
        return b"".join(bytes([len(p)]) + p.encode() for p in n.split(".")) + b"\0"
    pkt = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0) + qname("_nvstream._tcp.local") + struct.pack(">HH", 12, 0x8001)  # PTR, ask for a unicast reply
    found = {}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.settimeout(0.4)
        s.sendto(pkt, ("224.0.0.251", 5353))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, addr = s.recvfrom(9000)
            except socket.timeout:
                continue
            if b"_nvstream" not in data:
                continue
            # the instance name is the first label of the PTR answer's target; good enough for a display name
            m = re.search(rb"([\x01-\x3f])([^\x00-\x1f]{1,63})\x09_nvstream", data)
            name = m.group(2).decode("utf-8", "replace") if m else addr[0]
            found[addr[0]] = {"name": name, "ip": addr[0]}
        s.close()
    except OSError:
        pass
    return list(found.values())


def stream_host_info(ip, timeout=3):
    """Ask a Sunshine/GFE host for its name (http://host:47989/serverinfo). None if it doesn't answer."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{ip}:47989/serverinfo", timeout=timeout) as r:
            t = r.read().decode("utf-8", "replace")
        m = re.search(r"<hostname>(.*?)</hostname>", t)
        return {"name": m.group(1) if m else ip, "ip": ip}
    except Exception:
        return None


def moonlight_stream(host, app="Desktop"):
    exe = moonlight_path()
    if not exe:
        return False
    subprocess.Popen([exe, "stream", host, app], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True


# =====================================================================  free games and wishlist deals
EPIC_FREE = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US"


def epic_free_games():
    """[{"title", "url", "now": bool, "until"/"from": iso date}] from Epic's public store feed."""
    d = _get_json(EPIC_FREE, timeout=20)
    out = []
    for e in (((d.get("data") or {}).get("Catalog") or {}).get("searchStore") or {}).get("elements") or []:
        p = e.get("promotions") or {}
        cur = [o for g in (p.get("promotionalOffers") or []) for o in g.get("promotionalOffers") or []
               if (o.get("discountSetting") or {}).get("discountPercentage") == 0]
        up = [o for g in (p.get("upcomingPromotionalOffers") or []) for o in g.get("promotionalOffers") or []
              if (o.get("discountSetting") or {}).get("discountPercentage") == 0]
        if not cur and not up:
            continue
        slug = e.get("productSlug") or next((m.get("pageSlug") for m in ((e.get("catalogNs") or {}).get("mappings") or [])), None) \
            or e.get("urlSlug")
        slug = (slug or "").split("/")[0]
        o = (cur or up)[0]
        out.append({"title": e.get("title", "?"), "url": f"https://store.epicgames.com/p/{slug}" if slug else "https://store.epicgames.com/free-games",
                    "now": bool(cur), "until": o.get("endDate"), "from": o.get("startDate")})
    out.sort(key=lambda x: (not x["now"], x.get("from") or ""))
    return out


def steam_wishlist_deals(steamid, cc="us", limit=60):
    """Games on a public Steam wishlist that are on sale: [{"appid", "name", "pct", "price", "was"}]."""
    d = _get_json(f"https://api.steampowered.com/IWishlistService/GetWishlist/v1/?steamid={steamid}", timeout=20)
    ids = [str(i["appid"]) for i in ((d.get("response") or {}).get("items") or [])][:limit]
    out = []
    for i in range(0, len(ids), 30):
        chunk = ids[i:i + 30]
        p = _get_json(f"https://store.steampowered.com/api/appdetails?appids={','.join(chunk)}&filters=price_overview&cc={cc}", timeout=20)
        for a in chunk:
            po = ((p.get(a) or {}).get("data") or {}) if isinstance((p.get(a) or {}).get("data"), dict) else {}
            po = po.get("price_overview") or {}
            if po.get("discount_percent"):
                out.append({"appid": a, "pct": po["discount_percent"], "price": po.get("final_formatted"),
                            "was": po.get("initial_formatted") or ""})
    for x in out:
        try:
            x["name"] = (_get_json(f"https://store.steampowered.com/api/appdetails?appids={x['appid']}&filters=basic", timeout=15)
                         .get(x["appid"], {}).get("data") or {}).get("name") or f"App {x['appid']}"
        except Exception:
            x["name"] = f"App {x['appid']}"
    out.sort(key=lambda x: -x["pct"])
    return out


# =====================================================================  RetroAchievements
def ra_summary(user, key, games=8):
    """Points and recently played games with progress, from the RetroAchievements web API (user's own key)."""
    import urllib.parse
    q = urllib.parse.urlencode({"u": user, "y": key, "g": games, "a": 0})
    d = _get_json(f"https://retroachievements.org/API/API_GetUserSummary.php?{q}", timeout=25)
    aw = d.get("Awarded") or {}
    recent = []
    for g in d.get("RecentlyPlayed") or []:
        a = aw.get(str(g.get("GameID"))) or {}
        recent.append({"id": g.get("GameID"), "title": g.get("Title", "?"), "console": g.get("ConsoleName", ""),
                       "got": int(a.get("NumAchieved") or 0), "total": int(a.get("NumPossibleAchievements") or g.get("AchievementsTotal") or 0),
                       "url": f"https://retroachievements.org/game/{g.get('GameID')}"})
    return {"points": d.get("TotalPoints") or 0, "softcore": d.get("TotalSoftcorePoints") or 0, "recent": recent,
            "url": f"https://retroachievements.org/user/{urllib.parse.quote(user)}"}


# =====================================================================  driver and BIOS updates
LENOVO_MODELS = {"83E1": "Legion Go", "83N0": "Legion Go 2", "83N1": "Legion Go 2"}  # machine types (Handheld Daemon list)
AMD_HANDHELD_DRIVERS = "https://www.amd.com/en/support/download/drivers.html"
LENOVO_SUPPORT = "https://pcsupport.lenovo.com/"

_PS_VERSIONS = r"""
$b = Get-CimInstance Win32_BIOS | Select-Object -First 1
$p = Get-CimInstance Win32_ComputerSystemProduct | Select-Object -First 1
$g = Get-CimInstance Win32_VideoController | Where-Object { $_.PNPDeviceID -like 'PCI\VEN_1002*' } | Select-Object -First 1
[pscustomobject]@{bios=$b.SMBIOSBIOSVersion; mtm=$p.Name; gpu=$g.Name; drv=$g.DriverVersion;
  drvdate=if ($g.DriverDate) { $g.DriverDate.ToString('yyyy-MM-dd') } else { '' }} | ConvertTo-Json -Compress
"""


def installed_versions():
    out = powershell(_PS_VERSIONS, timeout=30)
    try:
        return json.loads(out) if out else {}
    except ValueError:
        return {}


def _ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def lenovo_catalog(mtm):
    """Lenovo's own update catalog for this machine type (the one Lenovo's updaters read):
    [{"title", "category", "version", "date", "url", "bios_level"}]."""
    import urllib.request
    mtm = (mtm or "")[:4].upper()
    req = urllib.request.Request(f"https://download.lenovo.com/catalog/{mtm}_Win11.xml", headers={"User-Agent": "Vanta"})
    with urllib.request.urlopen(req, timeout=20) as r:
        cat = r.read().decode("utf-8-sig", "replace")
    out = []
    for loc, category in re.findall(r"<location>(.*?)</location>\s*<category>(.*?)</category>", cat, re.S):
        if not any(x in category for x in ("BIOS", "Graphics", "Video")):
            continue
        try:
            with urllib.request.urlopen(urllib.request.Request(loc.strip(), headers={"User-Agent": "Vanta"}), timeout=20) as r:
                s = r.read().decode("utf-8-sig", "replace")
        except Exception:
            continue
        t = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", s, re.S) or [None, ""])[1].strip()
        ver = re.search(r'<Package [^>]*version="([^"]*)"', s)
        lvl = re.search(r"<_Bios>\s*<Level>([^<]*)</Level>", s)
        out.append({"title": re.sub(r"\s+", " ", t("Desc") or t("Title")), "category": category.strip(),
                    "version": ver.group(1) if ver else t("Version"), "date": t("ReleaseDate"),
                    "url": loc.strip(), "bios_level": lvl.group(1).rstrip("*") if lvl else None})
    return out


def update_report():
    """Installed BIOS / AMD driver versus Lenovo's catalog. Only claims an update when the catalog is newer."""
    have = installed_versions()
    res = {"have": have, "items": [], "model": LENOVO_MODELS.get((have.get("mtm") or "")[:4].upper(), "")}
    try:
        cat = lenovo_catalog(have.get("mtm")) if have.get("mtm") else []
    except Exception:
        cat = None
    res["catalog_ok"] = cat is not None
    for c in cat or []:
        if "BIOS" in c["category"]:
            cur, new = have.get("bios") or "", c["bios_level"] or c["version"]
            newer = bool(cur and new and cur[:4] == new[:4] and _ver_tuple(new[4:]) > _ver_tuple(cur[4:]))
            res["items"].append({"what": "BIOS", "have": cur, "latest": new, "date": c["date"], "newer": newer})
        else:
            cur, new = have.get("drv") or "", c["version"]
            newer = bool(cur and new and _ver_tuple(new.split("/")[0]) > _ver_tuple(cur))
            res["items"].append({"what": "AMD graphics driver (Lenovo)", "have": cur, "latest": new, "date": c["date"], "newer": newer})
    return res


# =====================================================================  Vanta's own footprint
class _PowerThrottling(ctypes.Structure):
    _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]


class _MemCounters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in (
        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
        "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]


def set_self_efficiency(on):
    """Below-normal priority plus Windows 11 EcoQoS ("efficiency mode") for Vanta itself while it's in the background,
    so it never competes with a game. Off again restores normal priority."""
    k32 = ctypes.windll.kernel32
    h = k32.GetCurrentProcess()
    ok = False
    try:
        ok = bool(k32.SetPriorityClass(h, 0x4000 if on else 0x20))  # BELOW_NORMAL / NORMAL
    except Exception:
        pass
    try:
        st = _PowerThrottling(1, 0x1, 0x1 if on else 0x0)  # PROCESS_POWER_THROTTLING_EXECUTION_SPEED
        k32.SetProcessInformation(h, 4, ctypes.byref(st), ctypes.sizeof(st))  # ProcessPowerThrottling
    except Exception:
        pass
    return ok


def trim_self():
    """Hand Vanta's unused memory pages back to Windows (they come back on demand)."""
    try:
        return bool(ctypes.windll.kernel32.SetProcessWorkingSetSize(ctypes.windll.kernel32.GetCurrentProcess(),
                                                                    ctypes.c_size_t(-1), ctypes.c_size_t(-1)))
    except Exception:
        return False


def self_memory_mb():
    """Vanta's working set in MB (what Task Manager shows), or None."""
    try:
        m = _MemCounters()
        m.cb = ctypes.sizeof(m)
        if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(m), m.cb):
            return m.WorkingSetSize / 1048576
    except Exception:
        pass
    return None


# =====================================================================  fan: full speed (Lenovo feature 0x04020000)
# The same GameZone feature interface Vanta uses for TDP. Handheld Daemon uses this ID for the Legion Go's
# "full fan speed" switch. (Custom fan curves go through a different ACPI method that isn't confirmed on Windows.)
FAN_FULL_ID = 0x04020000


def get_full_fan():
    v = get_feature(FAN_FULL_ID)
    return None if v is None else bool(v)


def set_full_fan(on):
    return set_features([(FAN_FULL_ID, 1 if on else 0)])


# =====================================================================  HDR state (Windows display configuration API)
class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _DCHeader(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("size", ctypes.c_uint32), ("adapterId", _LUID), ("id", ctypes.c_uint32)]


class _DCGetColor(ctypes.Structure):
    _fields_ = [("header", _DCHeader), ("value", ctypes.c_uint32), ("colorEncoding", ctypes.c_uint32), ("bits", ctypes.c_uint32)]


class _DCSetColor(ctypes.Structure):
    _fields_ = [("header", _DCHeader), ("value", ctypes.c_uint32)]


def _display_targets():
    """[(adapter LUID, target id)] for active displays."""
    np_, nm = ctypes.c_uint32(), ctypes.c_uint32()
    if user32.GetDisplayConfigBufferSizes(2, ctypes.byref(np_), ctypes.byref(nm)) != 0:  # QDC_ONLY_ACTIVE_PATHS
        return []
    paths = (ctypes.c_byte * (72 * max(1, np_.value)))()
    modes = (ctypes.c_byte * (64 * max(1, nm.value)))()
    if user32.QueryDisplayConfig(2, ctypes.byref(np_), paths, ctypes.byref(nm), modes, None) != 0:
        return []
    out = []
    for i in range(np_.value):
        base = i * 72 + 20  # targetInfo starts after the 20-byte sourceInfo
        luid = _LUID.from_buffer(paths, base)
        tid = ctypes.c_uint32.from_buffer(paths, base + 8).value
        out.append((_LUID(luid.LowPart, luid.HighPart), tid))
    return out


def hdr_state():
    """(supported, on) for the main display, or (False, False)."""
    try:
        return _hdr_state()
    except (AttributeError, OSError):  # older Windows / no display config API
        return False, False


def _hdr_state():
    for luid, tid in _display_targets()[:1]:
        g = _DCGetColor()
        g.header = _DCHeader(9, ctypes.sizeof(_DCGetColor), luid, tid)  # GET_ADVANCED_COLOR_INFO
        if user32.DisplayConfigGetDeviceInfo(ctypes.byref(g)) == 0:
            return bool(g.value & 1), bool(g.value & 2)
    return False, False


def set_hdr(on):
    try:
        return _set_hdr(on)
    except (AttributeError, OSError):
        return False


def _set_hdr(on):
    for luid, tid in _display_targets()[:1]:
        s_ = _DCSetColor()
        s_.header = _DCHeader(10, ctypes.sizeof(_DCSetColor), luid, tid)  # SET_ADVANCED_COLOR_STATE
        s_.value = 1 if on else 0
        return user32.DisplayConfigSetDeviceInfo(ctypes.byref(s_)) == 0
    return False


# =====================================================================  captures: clips and screenshots (Windows Game Bar)
def captures_dir():
    d = reg_get(HKCU, GAMEDVR, "AppCaptureFolder") if "GAMEDVR" in globals() else None
    if not d:
        d = os.path.join(os.path.expanduser("~"), "Videos", "Captures")
    return os.path.expandvars(d)


def list_captures(limit=120):
    """Newest first: [{"path", "name", "kind": "clip"|"shot", "size", "time"}] from the Captures and Screenshots folders."""
    folders = [captures_dir(), os.path.join(os.path.expanduser("~"), "Pictures", "Screenshots")]
    out = []
    for d in folders:
        for e in _entries(d):
            if not e.is_file():
                continue
            ext = os.path.splitext(e.name)[1].lower()
            kind = "clip" if ext in (".mp4", ".mkv", ".webm") else "shot" if ext in (".png", ".jpg", ".jpeg", ".jxr") else None
            if kind:
                st = e.stat()
                out.append({"path": e.path, "name": e.name, "kind": kind, "size": st.st_size, "time": st.st_mtime})
    out.sort(key=lambda x: -x["time"])
    return out[:limit]


def save_clip():
    """Win+Alt+G: Game Bar saves the last moments (needs background recording on)."""
    send_keys(0x5B, 0x12, 0x47)


def save_screenshot():
    """Win+Alt+PrtScn: Game Bar screenshot of the game window."""
    send_keys(0x5B, 0x12, 0x2C)


# =====================================================================  mouse buttons / wheel for controller-as-mouse
_MOUSE_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}


def mouse_button(btn, down):
    i = _INPUT(type=0)
    i.mi = _MOUSEINPUT(0, 0, 0, _MOUSE_FLAGS[btn][0 if down else 1], 0, 0)
    return user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(_INPUT)) == 1


def mouse_wheel(delta, horizontal=False):
    i = _INPUT(type=0)
    i.mi = _MOUSEINPUT(0, 0, ctypes.c_uint32(int(delta)).value, 0x01000 if horizontal else 0x0800, 0, 0)
    return user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(_INPUT)) == 1


def key_vk(vk, down):
    arr = (_INPUT * 1)(_key_input(vk, not down))
    return user32.SendInput(1, arr, ctypes.sizeof(_INPUT)) == 1


# Layouts: controller button -> what it does. "mouse:left", "wheel", "key:Space", "keys:Alt+Tab" (tap), "osk".
PAD_LAYOUTS = {
    "desktop": {"name": "Desktop", "stick_mouse": "right", "stick_other": "scroll",
                "map": {"a": "mouse:left", "b": "mouse:right", "x": "key:Enter", "y": "osk", "rt": "mouse:left", "lt": "mouse:right",
                        "rb": "keys:Alt+Tab", "lb": "keys:Alt+Shift+Tab", "start": "key:Win", "back": "key:Esc",
                        "up": "key:Up", "down": "key:Down", "left": "key:Left", "right": "key:Right", "r3": "mouse:middle",
                        "l3": "key:Shift"}},
    "wasd": {"name": "Game: WASD", "stick_mouse": "right", "stick_other": "wasd",
             "map": {"rt": "mouse:left", "lt": "mouse:right", "a": "key:Space", "b": "key:Ctrl", "x": "key:R", "y": "key:E",
                     "lb": "key:Q", "rb": "key:F", "start": "key:Esc", "back": "key:Tab", "l3": "key:Shift", "r3": "mouse:middle",
                     "up": "key:1", "right": "key:2", "down": "key:3", "left": "key:4"}},
}
_XI_BITS = {"up": 0x0001, "down": 0x0002, "left": 0x0004, "right": 0x0008, "start": 0x0010, "back": 0x0020, "l3": 0x0040,
            "r3": 0x0080, "lb": 0x0100, "rb": 0x0200, "a": 0x1000, "b": 0x2000, "x": 0x4000, "y": 0x8000}


class DesktopControls:
    """Turns the controller into a mouse and keyboard (for launchers and games without controller support).
    Runs its own ~120 Hz thread on the raw XInput state; on_osk is called for the keyboard action."""

    def __init__(self, xinput_get=None, on_osk=None):
        import threading
        self.get = xinput_get or _xinput_get_state()
        self.on_osk = on_osk
        self.layout = None
        self.sens = 1.0
        self.held = set()
        self.wasd = set()
        self.stop = threading.Event()
        self.thread = None
        self.slot = None
        self.paused = False  # e.g. while the on-screen keyboard has the controller

    def start(self, layout, sens=1.0):
        import threading
        self.layout, self.sens = PAD_LAYOUTS[layout], sens
        if self.thread and self.thread.is_alive():
            return
        self.stop.clear()
        self.thread = threading.Thread(target=self._run, name="vanta-desktop-controls", daemon=True)
        self.thread.start()

    def end(self):
        self.stop.set()
        self._release_all()
        self.layout = None

    @property
    def on(self):
        return self.layout is not None and self.thread is not None and self.thread.is_alive()

    def _act(self, action, down):
        kind, _, arg = action.partition(":")
        if kind == "mouse":
            mouse_button(arg, down)
        elif kind == "key":
            for vk in combo_keys(arg)[:1]:
                key_vk(vk, down)
        elif kind == "keys" and down:
            key_combo(arg)
        elif kind == "osk" and down and self.on_osk:
            self.on_osk()

    def _release_all(self):
        for name in list(self.held):
            act = (self.layout or {}).get("map", {}).get(name)
            if act:
                self._act(act, False)
        for vk in list(self.wasd):
            key_vk(vk, False)
        self.held.clear()
        self.wasd.clear()

    def _read(self):
        from ctypes import byref
        st = XINPUT_STATE_SYS()
        if self.slot is None:
            for i in range(4):
                if self.get(i, byref(st)) == 0:
                    self.slot = i
                    break
            else:
                return None
        if self.get(self.slot, byref(st)) != 0:
            self.slot = None
            return None
        return st.Gamepad

    def _run(self):
        last = time.perf_counter()
        frac = [0.0, 0.0]
        scroll_acc = 0.0
        while not self.stop.is_set():
            time.sleep(1 / 120)
            now = time.perf_counter()
            dt = min(0.05, now - last)
            last = now
            lay = self.layout
            if self.paused:
                if self.held or self.wasd:
                    self._release_all()
                continue
            g = self._read()
            if not lay or g is None:
                continue
            m = lay["map"]
            pressed = {n for n, bit in _XI_BITS.items() if g.wButtons & bit}
            if g.bLeftTrigger > 100:
                pressed.add("lt")
            if g.bRightTrigger > 100:
                pressed.add("rt")
            if {"back", "start"} <= pressed:  # View + Menu together is Vanta's way out of mouse mode: don't type with it
                pressed -= {"back", "start"}
            for n in pressed - self.held:
                if n in m:
                    self._act(m[n], True)
            for n in self.held - pressed:
                if n in m:
                    self._act(m[n], False)
            self.held = pressed
            sticks = {"left": (g.sThumbLX, g.sThumbLY), "right": (g.sThumbRX, g.sThumbRY)}
            mx, my = sticks[lay["stick_mouse"]]
            dead = 7000

            def curve(v):
                a = abs(v)
                if a < dead:
                    return 0.0
                t = (a - dead) / (32767 - dead)
                return (t ** 2.2) * (1 if v > 0 else -1)  # fine control near the centre, fast at the edge
            speed = 1900 * self.sens * dt
            frac[0] += curve(mx) * speed
            frac[1] -= curve(my) * speed
            ix, iy = int(frac[0]), int(frac[1])
            if ix or iy:
                mouse_move(ix, iy)
                frac[0] -= ix
                frac[1] -= iy
            ox, oy = sticks["left" if lay["stick_mouse"] == "right" else "right"]
            if lay["stick_other"] == "scroll":
                scroll_acc += curve(oy) * 1400 * dt
                if abs(scroll_acc) >= 40:
                    mouse_wheel(int(scroll_acc))
                    scroll_acc = 0.0
            elif lay["stick_other"] == "wasd":
                want = set()
                if oy > 12000: want.add(0x57)
                if oy < -12000: want.add(0x53)
                if ox < -12000: want.add(0x41)
                if ox > 12000: want.add(0x44)
                for vk in want - self.wasd:
                    key_vk(vk, True)
                for vk in self.wasd - want:
                    key_vk(vk, False)
                self.wasd = want
        self._release_all()


def _xinput_get_state():
    """XInputGetState bound to this module's own state struct."""
    for name in ("xinput1_4", "xinput9_1_0", "xinput1_3"):
        try:
            fn = getattr(ctypes.WinDLL(name), "XInputGetState")
        except (OSError, AttributeError):
            continue
        fn.argtypes = [wintypes.DWORD, ctypes.c_void_p]
        fn.restype = wintypes.DWORD
        return fn
    return lambda i, p: 1167  # ERROR_DEVICE_NOT_CONNECTED


class _XI_GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", wintypes.WORD), ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short), ("sThumbRY", ctypes.c_short)]


class XINPUT_STATE_SYS(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", _XI_GAMEPAD)]


# =====================================================================  downloads that hurt online play
def pause_onedrive():
    """OneDrive's own /shutdown (it restarts cleanly with resume_onedrive)."""
    exe = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "OneDrive", "OneDrive.exe")
    if not os.path.exists(exe):
        return False
    subprocess.Popen([exe, "/shutdown"], creationflags=NO_WINDOW)
    return True


def resume_onedrive():
    exe = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "OneDrive", "OneDrive.exe")
    if not os.path.exists(exe):
        return False
    subprocess.Popen([exe, "/background"], creationflags=NO_WINDOW)
    return True


NET_TARGETS = [("Cloudflare", "1.1.1.1"), ("Steam", "store.steampowered.com"), ("Xbox Live", "xbox.com"),
               ("Epic", "epicgames.com"), ("Your router", None)]


def default_gateway():
    r = run(["route", "print", "0.0.0.0"])
    m = re.search(r"0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)", r.stdout if r else "")
    return m.group(1) if m else None


def ping_stats(host, count=8):
    """(average ms, jitter ms, lost) with jitter = mean difference between consecutive pings."""
    times = []
    lost = 0
    for _ in range(count):
        avg, l_ = ping(host, 1, 900)
        if avg is None:
            lost += 1
        else:
            times.append(avg)
    if not times:
        return None, None, lost
    jit = sum(abs(a - b) for a, b in zip(times, times[1:])) / max(1, len(times) - 1)
    return sum(times) / len(times), jit, lost


def wifi_details():
    """{"ssid", "signal", "band", "rate"} from netsh."""
    r = run(["netsh", "wlan", "show", "interfaces"])
    t = r.stdout if r else ""
    g = lambda pat: (re.search(pat, t) or [None, None])[1]
    ch = g(r"Channel\s*:\s*(\d+)")
    band = g(r"Band\s*:\s*([\d.]+ GHz)")
    if not band and ch:
        band = "2.4 GHz" if int(ch) <= 14 else "5 GHz" if int(ch) < 180 else "6 GHz"
    sig = g(r"Signal\s*:\s*(\d+)%")
    return {"ssid": (g(r"\n\s*SSID\s*:\s*(.+)") or "").strip() or None, "signal": int(sig) if sig else None, "band": band,
            "rate": g(r"Receive rate \(Mbps\)\s*:\s*([\d.]+)")}


# =====================================================================  uninstall + storage
def uninstall_target(g):
    """Where to uninstall a library game: (label, target to open)."""
    src, gid = g.get("source"), g.get("id", "")
    if gid.startswith("steam:"):
        return "Uninstall in Steam", f"steam://uninstall/{gid.split(':', 1)[1]}"
    if src == "Epic":
        return "Open Epic to uninstall", "com.epicgames.launcher://store/library"
    if src == "GOG":
        return "Open GOG Galaxy", "goggalaxy://openGameView/" + gid.split(":", 1)[1]
    return "Open Installed apps", "ms-settings:appsfeatures"


# =====================================================================  backup / restore and theme codes
BACKUP_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Vanta backups")


def make_backup(cfg_dict, extra_files=()):
    """A zip with Vanta's settings (keys and tokens left out) plus any extra files. Returns its path."""
    import zipfile
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, time.strftime("Vanta backup %Y-%m-%d %H%M.zip"))
    secret = ("key", "token", "webhook", "secret", "password")
    clean = {k: v for k, v in cfg_dict.items() if not any(s in k.lower() for s in secret)}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("vanta-settings.json", json.dumps(clean, indent=1))
        for f in extra_files:
            if os.path.isfile(f):
                z.write(f, os.path.join("files", os.path.basename(f)))
    return path


def list_backups():
    out = [e for e in _entries(BACKUP_DIR) if e.is_file() and e.name.lower().endswith(".zip")]
    return sorted(((e.path, e.stat().st_mtime) for e in out), key=lambda x: -x[1])


def read_backup(path):
    import zipfile
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("vanta-settings.json").decode("utf-8"))


def theme_to_code(theme):
    import base64
    import zlib
    raw = json.dumps(theme, separators=(",", ":")).encode("utf-8")
    return "VANTA1-" + base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii").rstrip("=")


def theme_from_code(code):
    import base64
    import zlib
    code = (code or "").strip()
    if not code.startswith("VANTA1-"):
        return None
    b = code[7:]
    try:
        d = json.loads(zlib.decompress(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4))).decode("utf-8"))
    except Exception:
        return None
    ok = isinstance(d, dict) and all(isinstance(v, (str, int, float, bool)) for v in d.values()) and len(json.dumps(d)) < 4000
    return d if ok else None
