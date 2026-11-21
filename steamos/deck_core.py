"""Vanta Deck, the data side: the Steam library on SteamOS, play tracking, the Deck's sensors and storage cleanup.

Only reads, apart from three things the user asks for: launching games (through Steam), moving leftover folders to
the Trash, and fetching public data (covers, news, reviews, Deck compatibility) from Steam and ProtonDB."""
import glob
import json
import os
import re
import shutil
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.request

# The bundled OpenSSL looks for certificates where Ubuntu keeps them; SteamOS (Arch) keeps them elsewhere.
if not os.environ.get("SSL_CERT_FILE"):
    for _ca in ("/etc/ssl/certs/ca-certificates.crt", "/etc/ca-certificates/extracted/tls-ca-bundle.pem",
                "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/cert.pem"):
        if os.path.exists(_ca):
            os.environ["SSL_CERT_FILE"] = _ca
            break

HOME = os.path.expanduser("~")
DATA = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share"), "vanta-deck")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache"), "vanta-deck")
SYS = os.environ.get("VANTA_SYS_ROOT", "")  # tests point this at a fake /sys and /proc
UA = "VantaDeck/1.1 (+SteamOS)"

TOOL_NAMES = re.compile(r"^(proton|steam linux runtime|steamworks common|steamvr|steam audio|"
                        r"directx|vc\+\+|easy anti-cheat|battleye)", re.I)


# =====================================================================  small helpers
def read(path, default=None):
    try:
        with open(SYS + path if path.startswith(("/sys", "/proc")) else path, encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except OSError:
        return default


def read_num(path, default=None):
    v = read(path)
    try:
        return float(v) if v not in (None, "") else default
    except ValueError:
        return default


def get_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def download(url, path, timeout=20):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        if len(data) < 1500:
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def dir_size(path):
    total = 0
    for root, dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def fmt_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") or n >= 100 else f"{n:.1f} {unit}"
        n /= 1024


def fmt_duration(sec):
    sec = int(max(0, sec or 0))
    h, m = divmod(sec // 60, 60)
    return f"{h}h {m:02d}m" if h else f"{m} min" if m else f"{sec}s"


def ago(t):
    if not t:
        return "never"
    d = time.time() - t
    if d < 3600:
        return "just now"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    if d < 2 * 86400:
        return "yesterday"
    if d < 30 * 86400:
        return f"{int(d // 86400)} days ago"
    return time.strftime("%b %d, %Y", time.localtime(t))


# =====================================================================  config
DEFAULTS = {"theme": "Vanta", "animations": True, "start_tab": "home", "fahrenheit": False, "art_fetch": True,
            "sessions": [], "notes": {}, "queue": [], "finished": {}, "favorites": [], "home_sel": None,
            "lib_filter": "all", "lib_sort": "recent", "welcomed": False, "ui_scale": 100, "ratings": {}, "power": {},
            "play_range": "month", "shots_game": None}


class Config(dict):
    def __init__(self):
        super().__init__(json.loads(json.dumps(DEFAULTS)))
        self.path = os.path.join(DATA, "config.json")
        try:
            with open(self.path, encoding="utf-8") as f:
                saved = json.load(f)
            for k, v in saved.items():
                if k in DEFAULTS and type(v) is type(DEFAULTS[k]) or (k in DEFAULTS and DEFAULTS[k] is None):
                    self[k] = v
        except (OSError, ValueError):
            pass
        self._lock = threading.Lock()

    def save(self):
        with self._lock:
            os.makedirs(DATA, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dict(self), f, separators=(",", ":"))
            os.replace(tmp, self.path)


# =====================================================================  Valve's file formats
def parse_vdf(text):
    """Steam's text KeyValues (appmanifest, libraryfolders, localconfig) into nested dicts."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    stack, cur, key = [], {}, None
    for s, brace in tokens:
        if brace == "{":
            new = {}
            if key is not None:
                cur[key] = new
            stack.append(cur)
            cur, key = new, None
        elif brace == "}":
            cur = stack.pop() if stack else cur
            key = None
        elif key is None:
            key = s.replace('\\"', '"').replace("\\\\", "\\")
        else:
            cur[key] = s.replace('\\"', '"').replace("\\\\", "\\")
            key = None
    return cur


def ci(d, *keys):
    """Case-insensitive walk through nested dicts (Steam isn't consistent about key case)."""
    for k in keys:
        if not isinstance(d, dict):
            return None
        lk = k.lower()
        d = next((v for kk, v in d.items() if kk.lower() == lk), None)
    return d


def parse_binary_vdf(data):
    """Steam's binary KeyValues (shortcuts.vdf)."""
    pos = 0

    def cstr():
        nonlocal pos
        end = data.index(b"\x00", pos)
        s = data[pos:end].decode("utf-8", "replace")
        pos = end + 1
        return s

    def node():
        nonlocal pos
        out = {}
        while pos < len(data):
            t = data[pos]
            pos += 1
            if t == 0x08:
                return out
            name = cstr()
            if t == 0x00:
                out[name] = node()
            elif t == 0x01:
                out[name] = cstr()
            elif t == 0x02:
                out[name] = struct.unpack_from("<i", data, pos)[0]
                pos += 4
            elif t == 0x07:
                out[name] = struct.unpack_from("<Q", data, pos)[0]
                pos += 8
            else:
                raise ValueError(f"unknown binary VDF type {t}")
        return out
    return node()


# =====================================================================  Steam on SteamOS
def steam_root():
    env = os.environ.get("VANTA_STEAM")
    cands = ([env] if env else []) + [os.path.join(HOME, ".local", "share", "Steam"), os.path.join(HOME, ".steam", "steam"),
                                       os.path.join(HOME, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam")]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "steamapps")):
            return os.path.realpath(c)
    return None


def library_folders(root):
    out = [os.path.join(root, "")[:-1]]
    vdf = read(os.path.join(root, "steamapps", "libraryfolders.vdf"))
    if vdf:
        d = ci(parse_vdf(vdf), "libraryfolders") or {}
        for v in d.values():
            p = ci(v, "path") if isinstance(v, dict) else None
            if p and os.path.isdir(os.path.join(p, "steamapps")) and os.path.realpath(p) not in map(os.path.realpath, out):
                out.append(p)
    return out


def user_dir(root):
    """The userdata folder of the account that used Steam last."""
    best, best_t = None, 0
    for d in glob.glob(os.path.join(root, "userdata", "*")):
        name = os.path.basename(d)
        if not name.isdigit() or name == "0":
            continue
        lc = os.path.join(d, "config", "localconfig.vdf")
        t = os.path.getmtime(lc) if os.path.exists(lc) else os.path.getmtime(d)
        if t > best_t:
            best, best_t = d, t
    return best


def local_apps(udir):
    """{appid: (last played time, minutes)} from Steam's own records."""
    out = {}
    text = read(os.path.join(udir, "config", "localconfig.vdf")) if udir else None
    if not text:
        return out
    apps = ci(parse_vdf(text), "UserLocalConfigStore", "Software", "Valve", "Steam", "apps") or {}
    for appid, v in apps.items():
        if isinstance(v, dict):
            try:
                out[str(appid)] = (int(ci(v, "LastPlayed") or 0), int(ci(v, "Playtime") or 0))
            except ValueError:
                pass
    return out


def app_extras(udir):
    """{appid: {"opts": launch options, "wk2": minutes in the last two weeks}} from Steam's local config."""
    text = read(os.path.join(udir, "config", "localconfig.vdf")) if udir else None
    apps = ci(parse_vdf(text), "UserLocalConfigStore", "Software", "Valve", "Steam", "apps") or {} if text else {}
    out = {}
    for a, v in apps.items():
        if isinstance(v, dict):
            try:
                wk2 = int(ci(v, "Playtime2wks") or 0)
            except ValueError:
                wk2 = 0
            out[str(a)] = {"opts": ci(v, "LaunchOptions") or "", "wk2": wk2}
    return out


def compat_tools(root):
    """{appid: compatibility tool} from Steam's config ("0" is the default for every game)."""
    text = read(os.path.join(root, "config", "config.vdf")) if root else None
    m = ci(parse_vdf(text), "InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping") or {} if text else {}
    return {str(a): ci(v, "name") for a, v in m.items() if isinstance(v, dict) and ci(v, "name")}


def tool_label(name):
    if not name:
        return None
    n = name.lower()
    if n == "proton_experimental":
        return "Proton Experimental"
    if n == "proton_hotfix":
        return "Proton Hotfix"
    m = re.match(r"proton_(\d+)$", n)
    if m:  # proton_63 is 6.3 and proton_513 is 5.13, but proton_9 and proton_10 are 9 and 10
        v = m.group(1)
        return f"Proton {v[0]}.{v[1:]}" if int(v) >= 30 else f"Proton {v}"
    if n.startswith("steamlinuxruntime"):
        return "Steam Linux Runtime"
    return name


def screenshots(udir):
    """Your Steam screenshots, newest first: [{appid, path, thumb, t}]."""
    out = []
    if not udir:
        return out
    for d in glob.glob(os.path.join(udir, "760", "remote", "*", "screenshots")):
        appid = os.path.basename(os.path.dirname(d))
        for p in glob.glob(os.path.join(d, "*.jpg")) + glob.glob(os.path.join(d, "*.png")):
            th = os.path.join(d, "thumbnails", os.path.basename(p))
            try:
                t = os.path.getmtime(p)
            except OSError:
                continue
            out.append({"appid": appid, "path": p, "thumb": th if os.path.exists(th) else p, "t": t})
    out.sort(key=lambda x: -x["t"])
    return out


def shortcut_list(udir):
    path = os.path.join(udir, "config", "shortcuts.vdf") if udir else None
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "rb") as f:
            d = parse_binary_vdf(f.read())
    except (OSError, ValueError, struct.error, IndexError):
        return []
    out = []
    for v in (ci(d, "shortcuts") or {}).values():
        if not isinstance(v, dict):
            continue
        aid = ci(v, "appid")
        name = ci(v, "AppName") or ci(v, "appname")
        if aid is None or not name:
            continue
        aid &= 0xFFFFFFFF
        out.append({"appid": aid, "name": name, "exe": ci(v, "Exe") or "", "last": int(ci(v, "LastPlayTime") or 0)})
    return out


def find_art(root, udir, appid, kind="cover"):
    """A cover (600x900) or hero image Steam already has on disk: your custom grid art first, then Steam's cache."""
    appid = str(appid)
    if udir:
        grid = os.path.join(udir, "config", "grid")
        names = [f"{appid}p.png", f"{appid}p.jpg"] if kind == "cover" else [f"{appid}_hero.png", f"{appid}_hero.jpg"]
        for n in names:
            p = os.path.join(grid, n)
            if os.path.exists(p):
                return p
    lc = os.path.join(root, "appcache", "librarycache")
    want = "library_600x900" if kind == "cover" else "library_hero"
    for pat in (f"{appid}_{want}*.jpg", os.path.join(appid, f"{want}*.jpg"), os.path.join(appid, "*", f"{want}*.jpg")):
        hits = sorted(glob.glob(os.path.join(lc, pat)), key=len)
        if hits:
            return hits[0]
    cached = os.path.join(CACHE, "art", f"{appid}_{kind}.jpg")
    return cached if os.path.exists(cached) else None


def fetch_art(appid, kind="cover"):
    """Download a cover or hero from Steam's public image server into the cache."""
    path = os.path.join(CACHE, "art", f"{appid}_{kind}.jpg")
    if os.path.exists(path):
        return path
    miss = path + ".none"
    if os.path.exists(miss) and time.time() - os.path.getmtime(miss) < 7 * 86400:
        return None
    base = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/"
    names = ["library_600x900_2x.jpg", "library_600x900.jpg"] if kind == "cover" else ["library_hero.jpg"]
    for n in names:
        if download(base + n, path):
            return path
    try:
        os.makedirs(os.path.dirname(miss), exist_ok=True)
        open(miss, "w").close()
    except OSError:
        pass
    return None


def scan_library():
    """Every installed Steam game plus your non-Steam shortcuts."""
    root = steam_root()
    if not root:
        return [], None
    udir = user_dir(root)
    local = local_apps(udir)
    extras = app_extras(udir)
    tools = compat_tools(root)
    games, seen = [], set()
    for lib in library_folders(root):
        for acf in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
            st = ci(parse_vdf(read(acf, "") or ""), "AppState") or {}
            appid, name = str(ci(st, "appid") or ""), ci(st, "name") or ""
            if not appid or not name or appid in seen or TOOL_NAMES.match(name):
                continue
            seen.add(appid)
            last, mins = local.get(appid, (int(ci(st, "LastPlayed") or 0), 0))
            flags = int(ci(st, "StateFlags") or 4)
            games.append({"id": f"steam:{appid}", "appid": appid, "name": name, "source": "Steam", "lib": lib,
                          "size": int(ci(st, "SizeOnDisk") or 0), "last": last, "minutes": mins,
                          "installdir": ci(st, "installdir") or "", "updating": not flags & 4 or bool(flags & 2),
                          "launch": f"steam://rungameid/{appid}", "opts": extras.get(appid, {}).get("opts", ""),
                          "wk2": extras.get(appid, {}).get("wk2", 0),
                          "tool": tool_label(tools.get(appid)), "tool_default": tool_label(tools.get("0")),
                          "cover": find_art(root, udir, appid), "hero": find_art(root, udir, appid, "hero")})
    for sc in shortcut_list(udir):
        gid = (sc["appid"] << 32) | 0x02000000
        games.append({"id": f"sc:{sc['appid']}", "appid": str(sc["appid"]), "name": sc["name"], "source": "Non-Steam",
                      "lib": None, "size": 0, "last": sc["last"], "minutes": 0, "installdir": "", "updating": False,
                      "launch": f"steam://rungameid/{gid}", "opts": "", "wk2": 0, "tool": tool_label(tools.get(str(sc["appid"]))),
                      "tool_default": None, "cover": find_art(root, udir, sc["appid"]),
                      "hero": find_art(root, udir, sc["appid"], "hero")})
    return games, {"root": root, "udir": udir}


def launch(url):
    """Hand a steam:// link to Steam (works in Game Mode and Desktop Mode)."""
    for cmd in (["steam", url], ["xdg-open", url]):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        except OSError:
            continue
    return False


def open_url(url):
    try:
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


def running_appids():
    """App ids of games running right now (Steam starts every game through its 'reaper' with AppId=…)."""
    out = set()
    for d in glob.glob((SYS or "") + "/proc/[0-9]*"):
        try:
            with open(os.path.join(d, "cmdline"), "rb") as f:
                cmd = f.read(4096)
        except OSError:
            continue
        if b"AppId=" in cmd and (b"reaper" in cmd or b"SteamLaunch" in cmd):
            m = re.search(rb"AppId=(\d+)", cmd)
            if m and m.group(1) != b"0":
                out.add(m.group(1).decode())
    return out


# =====================================================================  public data: news, reviews, compatibility
def steam_news(appid, count=4):
    d = get_json(f"https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid={int(appid)}&count={count}&maxlength=300"
                 "&feeds=steam_community_announcements")
    out = []
    for it in (d.get("appnews") or {}).get("newsitems", []):
        text = re.sub(r"\[/?[^\]]*\]|<[^>]+>|https?://\S+|\{STEAM_CLAN_IMAGE\}\S*", " ", it.get("contents") or "")
        title = it.get("title") or ""
        out.append({"title": title, "date": int(it.get("date") or 0), "url": it.get("url") or "", "text": " ".join(text.split())[:260],
                    "patch": bool(re.search(r"\b(patch|update|hotfix|fix(es)?|v\d+\.\d+)\b", title, re.I))})
    return out


def steam_reviews(appid):
    d = get_json(f"https://store.steampowered.com/appreviews/{int(appid)}?json=1&language=all&purchase_type=all&num_per_page=0")
    q = d.get("query_summary") or {}
    tot = int(q.get("total_reviews") or 0)
    return {"desc": q.get("review_score_desc") or "", "pct": round(int(q.get("total_positive") or 0) * 100 / tot) if tot else None,
            "total": tot}


DECK_CATS = {3: ("Verified", "good"), 2: ("Playable", "warn"), 1: ("Unsupported", "danger"), 0: ("Unknown", "muted")}


def app_name(appid):
    """A Steam app's name from the public store (for leftovers of games that are gone). Cached."""
    path = os.path.join(CACHE, "names.json")
    try:
        with open(path, encoding="utf-8") as f:
            names = json.load(f)
    except (OSError, ValueError):
        names = {}
    if str(appid) in names:
        return names[str(appid)]
    try:
        d = get_json(f"https://store.steampowered.com/api/appdetails?appids={int(appid)}&filters=basic&l=english", timeout=10)
        name = ((d.get(str(appid)) or {}).get("data") or {}).get("name")
    except Exception:
        return None
    names[str(appid)] = name
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(names, f)
    except OSError:
        pass
    return name


def deck_compat(appid):
    """Valve's own Steam Deck compatibility rating for a game."""
    d = get_json(f"https://store.steampowered.com/saleaction/ajaxgetdeckappcompatibilityreport?nAppID={int(appid)}&l=english")
    cat = int(((d.get("results") or {}).get("resolved_category")) or 0)
    return DECK_CATS.get(cat, DECK_CATS[0])


def protondb_tier(appid):
    d = get_json(f"https://www.protondb.com/api/v1/reports/summaries/{int(appid)}.json")
    return (d.get("tier") or d.get("trendingTier") or "").lower() or None, int(d.get("total") or 0)


# =====================================================================  the Deck's sensors
class Sensors:
    """Battery, CPU, GPU, temperatures, fan and memory from /sys and /proc. Everything is optional."""

    def __init__(self):
        self.prev_cpu = None
        self.hist = {"cpu": [], "gpu": [], "watts": [], "temp": []}

    def battery(self):
        for d in sorted(glob.glob((SYS or "") + "/sys/class/power_supply/*")):
            if read_num(d[len(SYS):] + "/capacity") is None or (read(d[len(SYS):] + "/type") or "Battery") != "Battery":
                continue
            p = d[len(SYS):]
            pw = read_num(p + "/power_now")
            if pw is None:
                cur, volt = read_num(p + "/current_now"), read_num(p + "/voltage_now")
                pw = cur * volt / 1e6 if cur is not None and volt is not None else None
            full = read_num(p + "/energy_full") or (read_num(p + "/charge_full") or 0) * (read_num(p + "/voltage_min_design") or 0) / 1e6
            design = read_num(p + "/energy_full_design") or \
                (read_num(p + "/charge_full_design") or 0) * (read_num(p + "/voltage_min_design") or 0) / 1e6
            now_e = read_num(p + "/energy_now") or (read_num(p + "/charge_now") or 0) * (read_num(p + "/voltage_min_design") or 0) / 1e6
            status = read(p + "/status") or ""
            watts = (pw or 0) / 1e6
            left = now_e / 1e6 / watts * 3600 if status == "Discharging" and watts > 0.5 and now_e else None
            return {"pct": int(read_num(p + "/capacity") or 0), "status": status, "watts": watts, "left": left,
                    "health": full / design * 100 if full and design else None, "cycles": read_num(p + "/cycle_count"),
                    "full_wh": full / 1e6 if full else None, "design_wh": design / 1e6 if design else None}
        return None

    def cpu(self):
        line = (read("/proc/stat") or "").split("\n", 1)[0].split()
        if len(line) < 5:
            return None
        vals = [int(x) for x in line[1:]]
        idle, total = vals[3] + (vals[4] if len(vals) > 4 else 0), sum(vals)
        prev, self.prev_cpu = self.prev_cpu, (idle, total)
        if not prev or total == prev[1]:
            return None
        return max(0.0, min(100.0, 100 * (1 - (idle - prev[0]) / (total - prev[1]))))

    def gpu(self):
        for p in sorted(glob.glob((SYS or "") + "/sys/class/drm/card*/device/gpu_busy_percent")):
            v = read_num(p[len(SYS):])
            if v is not None:
                return v
        return None

    def hwmon(self):
        out = {}
        for d in sorted(glob.glob((SYS or "") + "/sys/class/hwmon/hwmon*")):
            p = d[len(SYS):]
            name = read(p + "/name") or ""
            if name in ("jupiter", "steamdeck_hwmon", "galileo"):
                f = read_num(p + "/fan1_input")
                if f is not None:
                    out["fan"] = f
            elif name == "k10temp":
                t = read_num(p + "/temp1_input")
                if t is not None:
                    out["cpu_temp"] = t / 1000
            elif name == "amdgpu":
                t = read_num(p + "/temp1_input")
                if t is not None:
                    out["gpu_temp"] = t / 1000
                w = read_num(p + "/power1_average") or read_num(p + "/power1_input")
                if w is not None:
                    out["apu_watts"] = w / 1e6
            elif "fan" not in out:
                f = read_num(p + "/fan1_input")
                if f:
                    out["fan"] = f
        return out

    def memory(self):
        m = {}
        for line in (read("/proc/meminfo") or "").splitlines():
            k, _, v = line.partition(":")
            if k in ("MemTotal", "MemAvailable"):
                m[k] = int(v.split()[0]) * 1024
        return (m["MemTotal"] - m["MemAvailable"], m["MemTotal"]) if len(m) == 2 else None

    def sample(self):
        s = {"batt": self.battery(), "cpu": self.cpu(), "gpu": self.gpu(), "mem": self.memory(), **self.hwmon()}
        for key, v in (("cpu", s["cpu"]), ("gpu", s["gpu"]), ("watts", (s["batt"] or {}).get("watts")),
                       ("temp", s.get("cpu_temp"))):
            if v is not None:
                h = self.hist[key]
                h.append(v)
                del h[:-90]
        up = read_num("/proc/uptime")
        s["uptime"] = up
        return s


# =====================================================================  storage
def drives(paths):
    """[(label, mount path, used, total)] for the drives your Steam libraries are on."""
    seen, out = set(), []
    for p in paths:
        try:
            st = os.stat(p)
            du = shutil.disk_usage(p)
        except OSError:
            continue
        if st.st_dev in seen:
            continue
        seen.add(st.st_dev)
        label = "Internal storage" if os.path.realpath(p).startswith(os.path.realpath(HOME)) else \
            ("microSD card" if "/run/media" in p or "/media" in p else os.path.basename(p.rstrip("/")) or p)
        out.append((label, p, du.used, du.total))
    return out


def cleanup_scan(games, libs):
    """Shader caches and Proton prefixes. Leftovers belong to games that aren't installed any more (and aren't one of
    your non-Steam shortcuts). Nothing is touched here."""
    installed = {g["appid"] for g in games}
    leftovers, caches = [], []
    for lib in libs:
        apps = os.path.join(lib, "steamapps")
        for kind, sub in (("shaders", "shadercache"), ("prefix", "compatdata")):
            for d in glob.glob(os.path.join(apps, sub, "*")):
                aid = os.path.basename(d)
                if not aid.isdigit() or not os.path.isdir(d):
                    continue
                size = dir_size(d)
                item = {"kind": kind, "appid": aid, "path": d, "size": size, "lib": lib}
                if aid in installed:
                    if kind == "shaders":
                        caches.append(item)
                elif int(aid) > 10:  # 0 and tiny ids are Steam's own
                    leftovers.append(item)
    leftovers.sort(key=lambda x: -x["size"])
    caches.sort(key=lambda x: -x["size"])
    return leftovers, caches


def trash(path):
    """Move to the desktop's Trash (freedesktop spec), on the same drive so nothing gets copied."""
    path = os.path.realpath(path)
    home_trash = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share"), "Trash")
    try:
        same = os.stat(path).st_dev == os.stat(HOME).st_dev
    except OSError:
        return False
    if same:
        tdir = home_trash
    else:
        top = path
        while not os.path.ismount(top):
            top = os.path.dirname(top)
        tdir = os.path.join(top, f".Trash-{os.getuid()}")
    files, info = os.path.join(tdir, "files"), os.path.join(tdir, "info")
    try:
        os.makedirs(files, exist_ok=True)
        os.makedirs(info, exist_ok=True)
        base = os.path.basename(path)
        name, n = base, 1
        while os.path.exists(os.path.join(files, name)) or os.path.exists(os.path.join(info, name + ".trashinfo")):
            n += 1
            name = f"{base}.{n}"
        with open(os.path.join(info, name + ".trashinfo"), "w", encoding="utf-8") as f:
            f.write("[Trash Info]\nPath=" + urllib.parse.quote(path) + "\nDeletionDate=" + time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
        os.rename(path, os.path.join(files, name))
        return True
    except OSError:
        return False


def add_to_steam(exe):
    """SteamOS's own tool for adding a program to the Steam library (Desktop Mode)."""
    tool = shutil.which("steamos-add-to-steam")
    if not tool:
        return False
    try:
        subprocess.Popen([tool, exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


# =====================================================================  the controller (Linux joystick API)
class Joystick:
    """Reads /dev/input/js* (Steam's virtual gamepad in Game Mode, or any pad). Events go to a callback as names:
    up, down, left, right, a, b, x, y, lb, rb, back, start. In Desktop Mode Steam usually turns the Deck's controls
    into keyboard and mouse instead, which Vanta Deck also understands."""
    BTN = {0: "a", 1: "b", 2: "x", 3: "y", 4: "lb", 5: "rb", 6: "back", 7: "start"}

    def __init__(self, cb):
        self.cb = cb
        self.stop = False
        self.name = None
        self.axes = {}
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        while not self.stop:
            devs = sorted(glob.glob(os.environ.get("VANTA_JS", "/dev/input/js*")))
            for dev in devs:
                try:
                    f = open(dev, "rb", buffering=0)
                except OSError:
                    continue
                self.name = dev
                try:
                    self.read_loop(f)
                except OSError:
                    pass
                finally:
                    f.close()
                    self.name = None
            time.sleep(2)

    def read_loop(self, f):
        held = {}
        while not self.stop:
            ev = f.read(8)
            if len(ev) < 8:
                return
            _, value, etype, num = struct.unpack("<IhBB", ev)
            init = etype & 0x80
            etype &= 0x7F
            if init:
                continue
            if etype == 0x01 and value:  # button down
                name = self.BTN.get(num) or {11: "left", 12: "right", 13: "up", 14: "down"}.get(num)
                if name:
                    self.cb(name)
            elif etype == 0x02:
                self.axes[num] = value
                dirs = None
                if num in (6, 7):  # D-pad as a hat
                    dirs = ("left", "right") if num == 6 else ("up", "down")
                    thr = 16000
                elif num in (0, 1):  # left stick: a firm push only
                    dirs = ("left", "right") if num == 0 else ("up", "down")
                    thr = 24000
                if dirs:
                    state = -1 if value < -thr else 1 if value > thr else 0
                    if state and held.get(num) != state:
                        self.cb(dirs[0] if state < 0 else dirs[1])
                    held[num] = state


# =====================================================================  memory (RAM)
# Never offered for closing: Steam, the Game Mode / desktop session and system services. A running game is
# left alone too (everything started under Steam's "reaper").
KEEP = re.compile(r"^(steam|steamwebhelper|steam-runtime.*|steamos.*|gamescope.*|xwayland|xorg|systemd.*|dbus.*|pipewire.*|"
                  r"wireplumber|pulseaudio|plasmashell|kwin.*|ksmserver|kded.*|kglobalaccel.*|xdg-.*|at-spi.*|polkit.*|"
                  r"sddm.*|startplasma.*|plasma_session|baloo.*|powerdevil.*|reaper|pressure-vessel.*|srt-bwrap|bwrap|"
                  r"wine.*|.*\.exe|bash|sh|zsh|fish|sudo|ssh.*|gpg-agent|mangoapp|inputplumber|hhd.*|jupiter-.*|"
                  r"vanta.*|python3?.*)$", re.I)


def memory_info():
    m = {}
    for line in (read("/proc/meminfo") or "").splitlines():
        k, _, v = line.partition(":")
        try:
            m[k] = int(v.split()[0]) * 1024
        except (ValueError, IndexError):
            pass
    if "MemTotal" not in m:
        return None
    return {"total": m["MemTotal"], "avail": m.get("MemAvailable", 0), "cached": m.get("Cached", 0) + m.get("Buffers", 0),
            "swap_total": m.get("SwapTotal", 0), "swap_used": m.get("SwapTotal", 0) - m.get("SwapFree", 0)}


def memory_apps(min_bytes=40 * 2**20):
    """Your own background apps by memory use: [{name, pids, rss}], biggest first. Steam, the session, system services,
    shells and anything a running game started are left out."""
    procs = {}
    me = os.getpid()
    for d in glob.glob((SYS or "") + "/proc/[0-9]*"):
        pid = int(os.path.basename(d))
        try:
            if os.stat(d).st_uid != os.getuid():
                continue
        except OSError:
            continue
        st = read(f"/proc/{pid}/stat") or ""
        status = read(f"/proc/{pid}/status") or ""
        try:
            ppid = int(st.rsplit(")", 1)[1].split()[1])
        except (IndexError, ValueError):
            ppid = 0
        name, rss = "", 0
        for line in status.splitlines():
            if line.startswith("Name:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("VmRSS:"):
                try:
                    rss = int(line.split()[1]) * 1024
                except (ValueError, IndexError):
                    pass
        cmd = (read(f"/proc/{pid}/cmdline") or "").replace("\x00", " ").strip()
        procs[pid] = {"pid": pid, "ppid": ppid, "name": name, "rss": rss, "cmd": cmd}

    def under(pid, test):
        seen = set()
        while pid in procs and pid not in seen:
            seen.add(pid)
            if test(procs[pid]):
                return True
            pid = procs[pid]["ppid"]
        return False

    groups = {}
    for p in procs.values():
        if not p["cmd"] or not p["rss"] or p["pid"] == me:
            continue  # kernel threads, zombies and Vanta itself
        if KEEP.match(p["name"]) or KEEP.match(os.path.basename(p["cmd"].split(" ")[0])):
            continue
        if under(p["pid"], lambda q: q["name"] == "reaper" or "SteamLaunch" in q["cmd"] or q["pid"] == me):
            continue
        key = os.path.basename(p["cmd"].split(" ")[0]) or p["name"]
        g = groups.setdefault(key, {"name": key, "pids": [], "rss": 0})
        g["pids"].append(p["pid"])
        g["rss"] += p["rss"]
    return sorted([g for g in groups.values() if g["rss"] >= min_bytes], key=lambda g: -g["rss"])


def close_app(pids):
    """Ask an app to close (SIGTERM, like closing its window). Returns how many processes got the request."""
    n = 0
    for pid in pids:
        try:
            if SYS:  # tests: "closing" a fake process removes it from the fake /proc
                shutil.rmtree(f"{SYS}/proc/{pid}")
            else:
                os.kill(pid, 15)
            n += 1
        except OSError:
            pass
    return n
