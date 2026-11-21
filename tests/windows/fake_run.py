import json
import os, sys, time
sys.path.insert(0, r"Z:\home\claude\app")
import vanta as R, systools as S
geo, tab, page = os.environ.get("G"), os.environ.get("TAB"), os.environ.get("PAGE")
R.device_info = lambda: {"name": "Legion Go 8APU1", "legion": True, "variant": "go"}
if os.environ.get("NOLEGION"): R.device_info = lambda: {"name": "ROG Ally RC71L", "legion": False, "variant": ""}
R.installed_ram = lambda: 16 * 1024**3
R.power_status = lambda: {"ac": False, "pct": 64, "battery": True, "charging": False}
S.get_thermal_mode = lambda: 2
S.get_power_mode = lambda: "balanced"
S.read_tweaks = lambda: {"gamemode": True, "dvr": True, "hvci": True, "hags": False, "transparency": True, "boost_dc": True, "bgapps": True, "diagtrack": True, "sysmain": True, "wsearch": True}
S.set_priority = lambda pid, level="above": True
S.drives = lambda: [("C", 512 * 1024**3, 61 * 1024**3), ("D", 1000 * 1024**3, 640 * 1024**3)]
sizes = {"temp": 1.4e9, "wintemp": 2.1e8, "recycle": 3.3e9, "dumps": 8.4e8, "delivery": 1.1e9, "updates": 2.6e9, "thumbs": 9e7, "shaders": 1.9e9, "steamshaders": 6.2e9}
S.scan_category = lambda c: int(sizes[c])
def items():
    mk = lambda n, src, det, en, kind="run", leg=False: {"key": n, "kind": kind, "name": n, "source": src, "detail": det, "enabled": en, "legion": leg}
    return [mk("Legion Space", "Store app", "LegionSpaceStartup", True, "pkg", True),
            mk("LegionSpace Daemon", "Scheduled task", "LSDaemon.exe", True, "task", True),
            mk("Legion Space Service", "Service", "LegionSpaceService", True, "service", True),
            mk("Discord", "Registry (you)", "Update.exe", True), mk("Steam", "Registry (you)", "steam.exe", True),
            mk("Microsoft Teams", "Store app", "TeamsTfwStartupTask", False, "pkg"), mk("OneDrive", "Registry (you)", "OneDrive.exe", True),
            mk("AMD Software", "Scheduled task", "RadeonSoftware.exe", False, "task"), mk("Spotify", "Registry (you)", "Spotify.exe", False)], \
           [("Legion Space", "E0469640.LenovoLegionSpace_x!App")]
S.startup_items = items
_names = ["ELDEN RING","Cyberpunk 2077","Hades","Stardew Valley","Apex Legends","Hollow Knight","Forza Horizon 5","Balatro","Celeste","Baldur's Gate 3"]
def fake_library(custom, *a):
    out = [{"id": f"steam:{1000+i}", "source": "Steam", "name": n, "size": int((i + 1) * 7.3e9), "last": time.time() - i * 86400 * 3,
            "minutes": (10 - i) * 190, "cover": rf"Z:\tmp\covers\{i}.jpg", "launch": "steam://rungameid/1", "store": "steam://nav"} for i, n in enumerate(_names)]
    out += [{"id": "epic:fortnite", "source": "Epic", "name": "Fortnite", "size": 3.1e10, "last": 0, "minutes": 0, "cover": None, "launch": "x://", "exe": ""},
            {"id": "gog:1", "source": "GOG", "name": "The Witcher 3: Wild Hunt", "size": 0, "last": 0, "minutes": 0, "cover": None, "launch": "x://"},
            {"id": "custom:c:\\emu\\retroarch.exe", "source": "Added", "name": "RetroArch", "size": 0, "last": 0, "minutes": 0, "cover": None, "launch": "x://"}]
    return out
S.game_library = fake_library
if os.environ.get("REALART"):
    def real_library(custom, *a):
        mk = lambda gid, src, name: {"id": gid, "source": src, "name": name, "size": 4e10, "last": 0, "minutes": 0, "cover": None, "launch": "x://"}
        return [mk("steam:1145360", "Steam", "Hades"), mk("steam:1245620", "Steam", "ELDEN RING"), mk("steam:2379780", "Steam", "Balatro"),
                mk("gog:1", "GOG", "The Witcher 3: Wild Hunt"), mk("ea:198196", "EA", "Mass Effect Legendary Edition"),
                mk("ubisoft:13504", "Ubisoft", "Assassin's Creed Mirage"), mk("xbox:fh5", "Xbox", "Forza Horizon 5"),
                mk("bnet:diablo iv", "Battle.net", "Diablo IV"), mk("epic:fortnite", "Epic", "Fortnite"), mk("steam:1091500", "Steam", "Cyberpunk 2077")]
    S.game_library = real_library
class FakeAdlx:
    error = ""
    detail = "fake"
    gpu_name = "AMD Radeon Graphics"
    ready = True
    def restart(self): return True
    def __init__(self):
        self.st = {"rsr": {"on": False, "sharp": 75, "range": (0, 100)}, "afmf": {"on": False}, "antilag": {"on": True},
                   "chill": {"on": False, "min": 30, "max": 60, "range": (10, 144)}, "ris": {"on": True, "sharp": 80, "range": (10, 100)},
                   "frtc": {"on": False, "fps": 60, "range": (30, 144)}, "boost": {"on": False, "res": 50, "range": (50, 90)},
                   "esync": {"on": False}, "integer": {"on": False}, "gpu_scaling": {"on": True}}
        self.applied = []
    def available(self): return True
    def read(self): return {k: dict(v) for k, v in self.st.items()}
    def snapshot(self, keys): return {k: self.st[k]["on"] for k in keys if k in self.st}
    def apply(self, d):
        self.applied.append(dict(d)); out = []
        for k, v in d.items():
            if k in self.st: self.st[k]["on"] = bool(v); out.append(f"{k} {'on' if v else 'off'}")
        return out
S.ADLX = FakeAdlx()
S.launch_game = lambda g: True
S.minimize_windows = lambda keep: [1, 2, 3, 4]
S.throttle_background = lambda procs, keep, names: [(1, "a.exe", 32)] * 9
S.unthrottle = lambda r: None
S.restore_windows = lambda h: None
S.force_foreground = lambda h: True
import random
class FakeGpu:
    def read(self): return 55 + random.random() * 30
S.GpuMeter = FakeGpu
S.get_tdp = lambda: 18
S.get_charge_limit = lambda: True
S.get_brightness = lambda: 50
S.presentmon_installed = lambda: True
class FakeFps:
    def __init__(self, pid):
        import collections, random
        self.error = None; self.r = random.Random(7)
        self.frames = collections.deque(maxlen=4000)
        t = time.time()
        for i in range(400):
            ms = 16.7 + self.r.uniform(-1.2, 1.2) + (28 if i in (300, 301, 340) else 0)
            self.frames.append((t - (400 - i) * 0.0167, ms))
    def stats(self): return (58.4, 41.0)
    def stop(self): pass
S.FpsReader = FakeFps
S.find_duplicates = lambda: [(2.3e9, [(r"C:\Users\me\Downloads\SteamSetup.exe", 1.0), (r"C:\Users\me\Desktop\SteamSetup.exe", 2.0)]),
                             (4.1e8, [(r"C:\Users\me\Videos\clip.mp4", 1.0), (r"C:\Users\me\Videos\old\clip.mp4", 2.0), (r"C:\Users\me\Documents\clip.mp4", 3.0)])]
S.display_modes = lambda: {"w": 2560, "h": 1600, "hz": 144, "rates": [60, 144], "sizes": [(2560, 1600), (1920, 1200), (1680, 1050), (1280, 800)]}
S.battery_state = lambda: {"ac": False, "charging": False, "discharging": True, "full_mwh": 45200, "remaining_mwh": 29000, "rate_mw": -14300 + int(time.time() * 7 % 3000), "est_s": None}
S.battery_static = lambda: {"design": 49200, "cycles": 187}
S.steam_games = lambda: [("1245620", "ELDEN RING", 63e9, time.time() - 86400 * 3, "C:\\Steam"), ("1091500", "Cyberpunk 2077", 71e9, time.time() - 86400 * 70, "D:\\SteamLibrary"),
    ("1172470", "Apex Legends", 75e9, 0, "C:\\Steam"), ("1145360", "Hades", 15e9, time.time() - 86400 * 400, "C:\\Steam"), ("413150", "Stardew Valley", 6e8, time.time() - 7200, "C:\\Steam")]
S.big_files = lambda: [(r"C:\Users\me\Downloads\SteamSetup.exe", 2.3e9, time.time() - 86400 * 200, "Downloads"),
    (r"C:\Users\me\Videos\Captures\Elden Ring 2026-10-02.mp4", 1.8e9, time.time() - 86400 * 40, "Videos"),
    (r"C:\Users\me\Downloads\Win11_24H2_English_x64.iso", 5.8e9, time.time() - 86400 * 300, "Downloads")]
class FakePad:
    def __init__(self, cb, bmap=None): self.cb, self.connected, self.error, self.sent, self.bmap, self.reports, self.seen_legion = cb, True, "", [], bmap, 0, False
    def start(self): pass
    def stop(self): pass
    def write(self, packets): self.sent.append(packets); return True
S.LegionButtons = FakePad
S.legion_space_processes = lambda procs: [(9001, "LegionSpace.exe", int(4.12e8)), (9002, "LSDaemon.exe", int(9.6e7)), (9003, "LegionGoQuickSettings.exe", int(7.1e7))] if not os.environ.get("NOLS") else []
S.own_memory = lambda: int(8.8e7)
S.discord_running = lambda procs: [] if os.environ.get("NODISC") else [(9101, "Discord.exe", int(2.1e8)), (9102, "Discord.exe", int(1.6e8)), (9103, "Discord.exe", int(9.0e7))]
S.latest_screenshot = lambda: (r"C:\Users\me\Pictures\Screenshots\Screenshot 2026-11-17 103412.png", time.time() - 300)
S.discord_webhook = lambda url, payload, file_path=None: (print("WEBHOOK", json.dumps(payload)[:300], file_path, flush=True), (True, "Posted to Discord"))[1]
S.take_screenshot = lambda: print("SCREENSHOT", flush=True)
class FakePresence:
    def __init__(self): self.connected, self.error, self.acts = False, "", []
    def start(self, cid): self.connected = True
    def stop(self): pass
    def set(self, a): self.acts.append(a)
S.DiscordPresence = FakePresence
S.steam_states = lambda: {"1001": ("UPDATING", 43.0), "1004": ("UPDATE NEEDED", None)}
S.shader_cache = lambda appid: (None, int(1.4e9) if appid in ("1000", "1002") else 0)
S.notifications_enabled = lambda: True
S.set_notifications = lambda on: True
S.updates_paused = lambda: False
S.pause_updates = lambda h=12: True
S.resume_updates = lambda: True
S.now_playing = lambda: "Daft Punk - Harder, Better, Faster, Stronger"
S.get_radios = lambda: {"wifi": True, "bluetooth": False}
S.set_radio = lambda kind, on: True
S.ping = lambda host="1.1.1.1", count=4, timeout_ms=1000: (23.4, 0)
S.wifi_info = lambda: {"ssid": "HomeNet-5G", "signal": 86}
S.media_key = lambda w: print("MEDIA", w)
S.toggle_hdr = lambda: print("HDR")
S.suspend_process = lambda pid, resume=False: True
S.key_combo = lambda combo, down=True, up=True: print("COMBO", combo, down, up) or True
S.close_processes = lambda pids: len(pids)
if os.environ.get("INITPROF"):
    import cProfile, pstats, io as _io
    _ip = cProfile.Profile(); _ip.enable()
ui = R.UI()
if os.environ.get("INITPROF"):
    ui.draw(); ui.root.update(); _ip.disable(); _s = _io.StringIO()
    pstats.Stats(_ip, stream=_s).sort_stats("cumulative").print_stats(35); print(_s.getvalue()[:6000], flush=True)
if os.environ.get("FIRSTDRAW"):
    ui.draw(); ui.root.update()
    print("READY %.2f" % (time.time() - float(os.environ["FIRSTDRAW"])), flush=True)
ui.quick_autoclose = False
ui.cfg["welcomed"] = not os.environ.get("WELCOME")
if os.environ.get("DISCORD"):
    ui.cfg["discord_presence"] = True; ui.cfg["discord_app_id"] = "1234567890123456789"
    ui.cfg["discord_webhook"] = "https://discord.com/api/webhooks/1311223344556677889/abcDEF_token-xyz"
    ui.root.after(3000, ui.open_discord)
if os.environ.get("STATS"):
    import random
    rnd = random.Random(4)
    names = ["ELDEN RING", "Hades", "Balatro", "Stardew Valley", "Cyberpunk 2077", "Hollow Knight", "Forza Horizon 5"]
    now = time.time(); ses = []
    for i in range(70):
        n = names[min(int(rnd.expovariate(0.6)), len(names) - 1)]
        st = now - rnd.random() * 86400 * 30
        if i < 14: st = now - rnd.random() * 86400 * 6.5
        ses.append({"name": n, "start": st, "dur": rnd.uniform(900, 7200), "peak": 0.5, "id": None,
                    "fps": round(rnd.uniform(40, 75), 1), "batt": rnd.randint(10, 45)})
    ses.sort(key=lambda s_: -s_["start"]); ui.cfg["sessions"] = ses
    ui.cfg["batt_hist"] = [[time.strftime("%Y-%m-%d", time.localtime(now - (90 - d) * 86400)), int(49200 * (0.995 - d * 0.0006 + rnd.uniform(-0.002, 0.002))), 49200, 40 + d * 2] for d in range(90)]
if os.environ.get("BACKPAGE"):
    ui.cfg["back_map"] = {"y1": "key:F5", "y2": "key:F9", "y3": "act:quick", "m3": "act:screenshot"}
    ui.root.after(3000, ui.open_back_buttons)
if os.environ.get("SUSPENDED"):
    ui.root.after(2500, lambda: setattr(ui, "suspended", 1000))
if os.environ.get("WALL"):
    ui.cfg["wallpaper"] = r"C:\wall.jpg"
if os.environ.get("OSK"):
    ui.root.after(3000, ui.toggle_keyboard)
S.type_text = lambda t: print("TYPE", repr(t)) or True
S.play_sound = lambda n: None
S.prepare_sounds = lambda v=0.25: None
if os.environ.get("POINTER"):
    def _gyro_demo():
        import threading
        ui.cfg["legion_buttons"] = True; ui.cfg["wallpaper"] = ""; ui.start_legion_buttons(); ui.set_pointer_mode("vanta")
        def run():
            t0 = time.perf_counter(); t = t0
            while time.perf_counter() - t0 < 4.0:
                t = time.perf_counter(); el = t - t0
                yaw = -0.33 if 1.4 < el < 2.3 else 0.0      # turn right
                pitch = -0.22 if 2.5 < el < 3.1 else 0.0    # tilt down
                if ui.pointer: ui.pointer.feed(pitch + 0.004, yaw - 0.003, 0.002, 0, 0, t)
                time.sleep(0.004)
        threading.Thread(target=run, daemon=True).start()
    ui.root.after(3500, _gyro_demo)
    ui.root.after(9000, lambda: print("PTRDBG", ui.cfg["pointer_mode"], ui.pointer and (ui.pointer.x, ui.pointer.y, ui.pointer.calib, ui.pointer.bias, ui.pointer.dx), ui.toast, ui.legion and ui.legion.connected, ui.c.find_withtag("pointer"), flush=True))
if os.environ.get("BENCH"):
    ui.cfg["bench_results"]["eldenring"] = {"name": "ELDEN RING", "when": time.time(), "results": [
        {"w": 8, "fps": 31.5, "low": 24, "watts": 11.2}, {"w": 11, "fps": 42.8, "low": 33, "watts": 14.1},
        {"w": 15, "fps": 55.9, "low": 44, "watts": 18.3}, {"w": 20, "fps": 58.6, "low": 47, "watts": 23.4},
        {"w": 25, "fps": 59.4, "low": 48, "watts": 28.0}, {"w": 30, "fps": 59.8, "low": 48, "watts": 32.9}]}
    ui.bench_view = "eldenring"
    ui.root.after(3000, lambda: setattr(ui, "page", "bench") or ui.request_draw())
if os.environ.get("SLEEPLOG"):
    now = time.time()
    ui.cfg["sleep_log"] = [{"start": now - d * 86400 - 9 * 3600, "end": now - d * 86400, "from": 82, "to": 82 - 5 - d % 3,
                            "woke": ["Intel Wi-Fi 6E AX211", None, "the power button or opening the lid"][d % 3]} for d in range(5, 0, -1)]
if os.environ.get("SEARCH"):
    ui.cfg["lists"] = {"Short sessions": ["steam:1000", "steam:1003"], "Co-op": ["steam:1002"]}
    ui.root.after(3000, lambda: (setattr(ui, "lib_query", os.environ["SEARCH"]), ui.request_draw()))
if os.environ.get("LISTS"):
    ui.cfg["lists"] = {"Short sessions": ["steam:1000", "steam:1003"], "Co-op": ["steam:1002"]}
    ui.root.after(3000, lambda: ui.open_lists({"id": "steam:1000", "name": "Balatro", "source": "Steam"}))
if os.environ.get("REMOTE"):
    ui.cfg["remote_pin"] = "424242"; ui.cfg["remote_on"] = True; ui.root.after(1000, ui.start_remote)
if os.environ.get("EDITOR"):
    ui.root.after(3000, lambda: (ui.open_editor(), ui.cfg["custom_theme"]["colors"].update(accent="#ff2bd6", accent2="#00e0ff", bg="#120a1f", panel="#1d1230"),
                                 ui.cfg["custom_theme"].update(grad=True, fx="stars"), ui.apply_custom_theme()))
if os.environ.get("ARTTEST"):
    def _arts():
        for i, g in enumerate(ui.library or []):
            if i < 8:
                g["cover"] = r"Z:\tmp\art\cover%d.jpg" % (i % 4)
                g["hero"] = r"Z:\tmp\art\hero%d.jpg" % (i % 4)
        ui.cfg["art_fetch"] = True
        ui.covers.clear()
        ui.request_draw()
    ui.root.after(7000, _arts)
if os.environ.get("REALART"):
    ui.cfg["lib_filter"] = "all"; ui.cfg["lib_sort"] = "name"
if os.environ.get("CHECKUP"): ui.root.after(3000, ui.open_checkup)
if not os.environ.get("STATS"): ui.cfg["sessions"] = [{"name": "eldenring", "start": time.time() - 86400, "dur": 5400, "peak": 0.91}, {"name": "Hades", "start": time.time() - 86400 * 3, "dur": 2700, "peak": 0.62}]
ui.cfg["stats"] = {"ram": 38e9, "disk": 21e9, "boosts": 57, "cleanups": 9}
S.process_alive = lambda pid: True
if os.environ.get("GAME"): ui.game = {"pid": 1000, "name": "eldenring", "exe": "eldenring.exe", "start": time.time() - 2400, "peak": 0.84, "saved": None}; ui.fps = FakeFps(1000)
if not os.environ.get("REALFOCUS"): ui.focused = lambda: True
if os.environ.get("THEME"): ui.cfg["theme"] = os.environ["THEME"]; ui.cfg["accent"] = ""; ui.cfg["follow_windows"] = False; ui.retheme()
if os.environ.get("TFILTER"): ui.theme_filter = os.environ["TFILTER"]
ui.cfg["game_profiles"] = {"eldenring": "max", "hades": "saver", "steam:1000": "max"}; ui.cfg["favorites"] = ["steam:1002", "steam:1007"]
if os.environ.get("SCROLLLIB"): ui.root.after(6000, lambda: (ui.set_off("lib", 99999), setattr(ui, "lib_sel", "gog:1"), ui.request_draw()))
if os.environ.get("TUNE"): ui.root.after(4500, lambda: ui.open_tune(os.environ["TUNE"], os.environ.get("TUNENAME", "ELDEN RING")))
if os.environ.get("FOCUSON"): ui.root.after(3000, ui.focus_start); ui.cfg["close_list"] = ["Discord.exe", "Spotify.exe"]
if os.environ.get("CVIEW"): ui.root.after(500, lambda: ui.set_clean_view(os.environ["CVIEW"]))
if os.environ.get("OVERLAY"): ui.cfg["overlay"] = True; ui.root.after(600, ui.ensure_overlay); ui.focused = lambda: False
ui.pad.slot = 0 if os.environ.get("PAD") else None
if ui.pad: ui.pad.poll = lambda: []
if geo: ui.root.geometry(geo)
if tab: ui.set_tab(tab)
if page: ui.page = page
if os.environ.get("SETCAT"): ui.set_cat = os.environ["SETCAT"]; ui.set_drill = True
if os.environ.get("SETQ"): ui.set_query = os.environ["SETQ"]
if os.environ.get("SETSCROLL"): ui.root.after(5000, lambda: (ui.set_off("settings", float(os.environ["SETSCROLL"])), ui.request_draw()))
if os.environ.get("LIBOFF"): ui.root.after(6000, lambda: (ui.set_off("lib", float(os.environ["LIBOFF"])), ui.request_draw()))
if os.environ.get("UISCALE"): ui.cfg["ui_scale"] = int(os.environ["UISCALE"])
if os.environ.get("TUNEOFF"): ui.root.after(int(os.environ.get("TUNEWAIT", "9000")), lambda: (ui.set_off("tune", float(os.environ["TUNEOFF"])), ui.request_draw()))
if os.environ.get("STUBS"):
    exec(open(r"Z:\home\claude\testkit\stubs74.py", encoding="utf-8").read())
if os.environ.get("AMDNA"):
    systools.ADLX.read = lambda *a, **k: {}
    systools.ADLX.error = "AMD's settings library didn't accept the graphics chip"
if os.environ.get("INFO"): ui.root.after(4500, lambda: ui.open_info(os.environ["INFO"]))
if os.environ.get("SKEL"): ui.root.after(6000, lambda: (setattr(ui, "library", None), setattr(ui, "load_library", lambda *a, **k: None), ui.request_draw()))
if os.environ.get("HOVER"): ui.root.after(7000, lambda: (setattr(ui, "hovered", os.environ["HOVER"]), ui.request_draw()))
if os.environ.get("GEN"): ui.cfg["preset_gen"] = os.environ["GEN"]
for i in range(60): ui.history.append(0.55 + 0.002 * i)
ui.procs = [(1000 + i, n, s) for i, (n, s) in enumerate([("eldenring.exe", 7.1e9), ("steamwebhelper.exe", 6.2e8), ("msedge.exe", 5.4e8), ("Discord.exe", 3.9e8), ("explorer.exe", 2.1e8), ("LegionSpace.exe", 1.9e8), ("dwm.exe", 1.2e8), ("svchost.exe", 9e7), ("OneDrive.exe", 8e7), ("Spotify.exe", 7e7), ("RadeonSoftware.exe", 6e7)])]
ui.proc_time = time.time() + 999
if os.environ.get("QUICK"): ui.root.after(int(os.environ.get("QUICKAT", "4000")), ui.open_quick)
if os.environ.get("QSCROLL"): ui.root.after(7000, lambda: (ui.set_off("qp", float(os.environ["QSCROLL"])), ui.request_draw()))
if os.environ.get("FIRSTDRAW"):
    _fd = ui.draw
    def _first(*a, **k):
        r = _fd(*a, **k)
        if not getattr(ui, "_fd_done", False):
            ui._fd_done = True
            print("FIRSTDRAW %.2f" % (time.time() - float(os.environ["FIRSTDRAW"])), flush=True)
        return r
    ui.draw = _first
if os.environ.get("WRAPTEST"):
    def _wt():
        ui.page = "welcome"; ui.draw(); ui.root.update()
        df = ui.font(14 * ui.k)
        intro = "This is the Preview build. It doesn't need admin, keeps its own settings, and won't change this PC while"
        print("WRAP k=%.3f size=%s actual=%s cached=%s fresh=%s" % (ui.k, df.cget("size"), df.actual(), ui.measure(df, intro), df.measure(intro)), flush=True)
        items = [i for i in ui.c.find_all() if ui.c.type(i) == "text" and "Legion Space" in ui.c.itemcget(i, "text")]
        for i in items: print("BBOX", ui.c.bbox(i), "measured", ui.measure(ui.c.nametowidget(".") and df, ui.c.itemcget(i, "text")), "W", ui.c.winfo_width(), flush=True)
        ui.root.destroy()
    ui.root.after(5000, _wt)
if os.environ.get("LSTEST"):
    def _ls():
        import systools
        closed = []
        t_boot = time.time() - 3600
        procs = {"svc": (900, "LSDaemon.exe", 40 << 20), "app": None}
        def fake_windows(allp, since=None):
            out = []
            if procs["app"]:
                pid, start = procs["app"]
                if since is None or start >= since:
                    out.append((pid, "LegionSpace.exe", 300 << 20))
            return out
        systools.legion_space_windows = fake_windows
        systools.legion_space_processes = lambda allp: [procs["svc"]] + ([(procs["app"][0], "LegionSpace.exe", 300 << 20)] if procs["app"] else [])
        systools.close_processes = lambda pids: (closed.extend(pids), procs.update(app=None), len(pids))[2]
        systools.button_service_state = lambda: "running"
        ui.device["legion"] = True; ui.cfg["ls_keep_closed"] = True
        # 1. Legion Space already open before the press (you opened it): left alone
        procs["app"] = (1111, time.time() - 600)
        ui.legion_action("legion_l")
        t_end = time.time() + 3
        while time.time() < t_end: ui.root.update(); time.sleep(0.05)
        print("LS old window kept:", closed == [], flush=True)
        # 2. pops up right after a press: closed
        procs["app"] = (2222, time.time() + 0.3)
        ui.legion_action("legion_r")
        t_end = time.time() + 3
        while time.time() < t_end: ui.root.update(); time.sleep(0.05)
        print("LS popped up closed:", closed == [2222], "log:", ui.log[-1][2] if ui.log else None, flush=True)
        # 3. you opened it from Vanta's shortcut: not closed for 30 min
        ui.open_legion_space_myself("shell:AppsFolder\\x")
        procs["app"] = (3333, time.time() + 0.3)
        ui.legion_action("legion_l")
        t_end = time.time() + 3
        while time.time() < t_end: ui.root.update(); time.sleep(0.05)
        print("LS opened yourself kept:", 3333 not in closed, flush=True)
        # 4. Close it now only closes the window, never the service
        ui.ls_user_until = 0; procs["app"] = (4444, time.time()); ui.ls_time = 0; ui.load_ls_info()
        t_end = time.time() + 2
        while time.time() < t_end: ui.root.update(); time.sleep(0.05)
        print("LS card:", [p[1] for p in ui.ls_info["procs"]], "services:", [p[1] for p in ui.ls_info["services"]], "svc state:", ui.ls_service, flush=True)
        ui.close_legion_space()
        t_end = time.time() + 2
        while time.time() < t_end: ui.root.update(); time.sleep(0.05)
        print("LS close-now closed:", closed, "(900 = service must not be there)", flush=True)
        ui.root.destroy()
    ui.root.after(5000, _ls)
if os.environ.get("HIDETEST"):
    def _ht():
        import systools
        calls = []
        systools.set_self_efficiency = lambda on: calls.append(("eco", on)) or True
        systools.trim_self = lambda: calls.append("trim") or True
        systools.self_memory_mb = lambda: 90.0 if "trim" not in calls else 40.0
        print("HIDE: light_footprint", ui.cfg["light_footprint"], flush=True); ui.cfg["light_footprint"] = True
        ui.draw(); n0 = len(ui.c.find_all())
        ui.hide(); ui.root.update()
        ui.request_draw(); ui.root.update(); time.sleep(0.05); ui.root.update()
        print("HIDE: stale", ui.stale, "items kept", len(ui.c.find_all()) == n0, flush=True)
        ui.light_tick(); ui.hidden_since -= 200; ui.light_tick()
        print("HIDE: eco/trim calls", calls, "covers", len(ui.covers), "log", ui.log[-1][2] if ui.log else None, flush=True)
        ui.show(); ui.root.update(); ui.light_tick(); ui.root.update(); time.sleep(0.1); ui.root.update()
        print("SHOW: stale", ui.stale, "eco", ui.eco, "calls", calls, flush=True)
        ui.root.destroy()
    ui.root.after(6000, _ht)
if os.environ.get("PERF2"):
    import ctypes, threading, cProfile, pstats, io
    from ctypes import wintypes
    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in
                    ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                     "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]
    def _mem():
        m = PMC(); m.cb = ctypes.sizeof(m)
        ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(m), m.cb)
        return m.PrivateUsage / 1048576, m.WorkingSetSize / 1048576
    def _cpu():
        a, b, c_, d = (wintypes.FILETIME() for _ in range(4))
        ctypes.windll.kernel32.GetProcessTimes(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(a), ctypes.byref(b), ctypes.byref(c_), ctypes.byref(d))
        f = lambda t: (t.dwHighDateTime << 32 | t.dwLowDateTime) / 1e7
        return f(c_) + f(d)
    _calls = {"draw": 0, "after": 0}
    _od = ui.draw
    def _cd(*a, **k):
        _calls["draw"] += 1; return _od(*a, **k)
    ui.draw = _cd
    _oa = ui.root.after
    def _ca(ms, fn=None, *a):
        _calls["after"] += 1; return _oa(ms, fn, *a) if fn else _oa(ms)
    ui.root.after = _ca
    _st = {}
    _pr = cProfile.Profile()
    def _p0():
        _st.update(cpu=_cpu(), t=time.time(), d=_calls["draw"], a=_calls["after"], mem=_mem()); _pr.enable()
    def _p1():
        _pr.disable()
        dt = time.time() - _st["t"]
        print("PERF2 idle %.1fs: cpu %.1f%%  draws/s %.1f  afters/s %.1f  threads %d  mem start %.0f/%.0f MB  now %.0f/%.0f MB" % (
            dt, (_cpu() - _st["cpu"]) / dt * 100, (_calls["draw"] - _st["d"]) / dt, (_calls["after"] - _st["a"]) / dt,
            threading.active_count(), *_st["mem"], *_mem()), flush=True)
        print("THREADS", [t.name for t in threading.enumerate()], flush=True)
        sio = io.StringIO(); pstats.Stats(_pr, stream=sio).sort_stats("tottime").print_stats(22); print(sio.getvalue()[:4500], flush=True)
        ui.root.destroy()
    _oa(int(os.environ.get("P0", "10000")), _p0)
    _oa(int(os.environ.get("P1", "30000")), _p1)
    print("STARTUP to first idle", flush=True)
if os.environ.get("PERF"):
    def _perf():
        import cProfile, pstats, io
        res = {}
        for name, setup in (("lib", lambda: (setattr(ui, "page", None), ui.set_tab("play"))),
                            ("settings", lambda: ui.open_page("settings")),
                            ("tune", lambda: ui.open_tune("steam:1001", "Cyberpunk 2077"))):
            setup(); ui.draw(); ui.root.update()
            t0 = time.perf_counter()
            for i in range(20):
                sid = "lib" if name == "lib" else name
                if sid in ui.scrolls: ui.set_off(sid, (i * 37) % 900)
                ui.draw_scope = "page" if name != "lib" else "all"
                ui.draw(); ui.root.update_idletasks()
            res[name] = (time.perf_counter() - t0) / 20 * 1000
            res[name + "_items"] = len(ui.c.find_all())
        print("PERF", res, flush=True)
        ui.open_page("settings"); ui.draw(); ui.root.update()
        def bench(label):
            t0 = time.perf_counter()
            for i in range(20):
                ui.set_off("settings", (i * 37) % 900); ui.draw_scope = "page"; ui.draw(); ui.root.update_idletasks()
            print("VAR", label, (time.perf_counter() - t0) / 20 * 1000, flush=True)
        bench("base")
        for it in ui.c.find_withtag("pagebase"): ui.c.itemconfigure(it, state="hidden")
        bench("noscrim")
        for it in ui.c.find_withtag("main"): ui.c.itemconfigure(it, state="hidden")
        bench("nohub")
        pr = cProfile.Profile(); ui.open_page("settings"); pr.enable()
        for i in range(10): ui.set_off("settings", i * 50); ui.draw(); ui.root.update_idletasks()
        pr.disable(); sio = io.StringIO(); pstats.Stats(pr, stream=sio).sort_stats("cumulative").print_stats(25); print(sio.getvalue()[:5000], flush=True)
        ui.root.destroy()
    ui.root.after(7000, _perf)
ui.root.after(15000, ui.root.destroy) if os.environ.get("AUTOQUIT") else None
if os.environ.get("SVCFLOW"):
    def _sv():
        import systools
        st = {"s": "running", "modes": None}
        systools.button_services = lambda: ["DAService", "LSDaemon"]
        systools.button_service_state = lambda: st["s"]
        def fake_set(on, modes=None):
            st["s"] = "running" if on else "disabled"; st["modes"] = modes
            return True, ({} if on else {"DAService": "auto", "LSDaemon": "demand"})
        systools.set_button_service = fake_set
        opened = []
        systools.open_target = lambda t: opened.append(t)
        ui.admin = True; ui.device["legion"] = True; ui.cfg["legion_buttons"] = True; ui.cfg["ls_keep_closed"] = True
        ui.cfg["ls_svc_off"] = False; ui.cfg["ls_svc_modes"] = {}
        ui.take_over_buttons()
        def chk1():
            print("SVC after takeover:", st["s"], ui.cfg["ls_svc_off"], ui.cfg["ls_svc_modes"], "toast", ui.toast and ui.toast[0], flush=True)
            ui.open_legion_space_myself("legionspace:")
            ui.root.after(1500, chk2)
        def chk2():
            print("SVC after open myself:", st["s"], "restored with", st["modes"], "opened", opened, "off", ui.cfg["ls_svc_off"], flush=True)
            ui.take_over_buttons()
            ui.root.after(1500, chk3)
        def chk3():
            print("SVC next start:", st["s"], ui.cfg["ls_svc_off"], flush=True)
            ui.adjust("ls_keep_closed", 1)
            ui.root.after(1500, chk4)
        def chk4():
            print("SVC keep-closed off:", st["s"], "restored with", st["modes"], "keep", ui.cfg["ls_keep_closed"], flush=True)
            ui.root.destroy()
        ui.root.after(1500, chk1)
    ui.root.after(5000, _sv)
if os.environ.get("BTNTEST"):
    import systools as _S
    class _FP(_S.HidProbe):
        def run(self, phases):
            self.running = True
            self.devices = [{"vid": 0x17EF, "pid": 0x61EB, "usage_page": 0xFFA0, "usage": 1, "interface": 2, "opened": True, "error": "", "reports": 3120},
                            {"vid": 0x17EF, "pid": 0x61EB, "usage_page": 0xFF00, "usage": 1, "interface": 3, "opened": True, "error": "", "reports": 1490}]
            for name, secs in phases:
                self.phase = name; time.sleep(0.5 if os.environ.get("BTNFAST") else secs)
            self.counts = {"idle": {}, "l": {(1, 4, 9, 0x10): 6}, "r": {(1, 4, 9, 0x20): 6}}
            self.idle_val = {(1, 4, 9, 0x10): True, (1, 4, 9, 0x20): True}
            self.running = False; self.phase = "done"; self.result = self.analyse()
    _S.HidProbe = _FP
    ui.root.after(4000, lambda: (ui.open_page("btntest"), ui.start_btntest()))
if os.environ.get("FXPERF"):
    def _fx():
        _st = ui.fx_step; n = {"c": 0}
        def counted(): n["c"] += 1; return _st()
        ui.fx_step = counted
        ui.root.after(5000, lambda: (print("FXPERF steps in 5s:", n["c"], "items", len(ui.fx_items), "fx_enabled", ui.fx_enabled(),
                                           "focused", ui.focused(), "game", bool(ui.game), "anims", dict(ui.anims), "press", ui.press, flush=True), _fx2()))
        def _fx2():
            ui.fx_step = _st; ts = []
            for i in range(20):
                t0 = time.perf_counter(); ui.fx_step(); ui.root.update_idletasks(); ts.append((time.perf_counter() - t0) * 1000)
            ts.sort(); print("FXPERF frame median %.1f ms" % ts[10], flush=True); ui.root.destroy()
    ui.root.after(int(os.environ.get("APWAIT", "9000")), _fx)

if os.environ.get("FXPROF"):
    def _prof():
        c = ui.c
        from collections import Counter
        items = c.find_all()
        cnt = Counter(c.type(i) for i in items)
        def full():
            W, H = c.winfo_width(), c.winfo_height()
            a = c.create_rectangle(0, 0, 1, 1, outline=""); b = c.create_rectangle(W - 1, H - 1, W, H, outline="")
            c.lower(a); c.lower(b)
            ts = []
            for k in range(7):
                c.move(a, 0, 0.0001); c.move(b, 0, 0.0001); c.coords(a, 0, 0, 1 + k % 2, 1); c.coords(b, W - 1 - k % 2, H - 1, W, H)
                t0 = time.perf_counter(); c.update_idletasks(); ts.append((time.perf_counter() - t0) * 1000)
            c.delete(a); c.delete(b); ts.sort(); return ts[3]
        out = ["items %d %s" % (len(items), dict(cnt)), "full %.1f" % full()]
        for typ in ("image", "text", "polygon", "line", "oval", "rectangle", "arc"):
            ids = [i for i in items if c.type(i) == typ]
            for i in ids: c.itemconfigure(i, state="hidden")
            out.append("no-%s %.1f" % (typ, full()))
            for i in ids: c.itemconfigure(i, state="")
        stip = [i for i in items if c.type(i) in ("polygon", "rectangle", "oval") and c.itemcget(i, "stipple")]
        out.append("stippled %d" % len(stip))
        print("FXPROF", " | ".join(out), flush=True); ui.root.destroy()
    ui.root.after(int(os.environ.get("APWAIT", "9000")), _prof)

if os.environ.get("NEWFEAT"):
    def _nf():
        import json as _j
        out = []
        try:
            ui.batt = dict(ui.batt or {}, discharging=True, ac=False, rate_mw=-15000, remaining_mwh=30000, full_mwh=50000)
            ui.set_bgoal(120)
            now = time.time()
            for v in [-15.0] * 10:
                ui.batt_hist.append(v)
            ui.bgoal_tick(now)
            ui.bgoal["t"] = 0; ui.bgoal_tick(now + 1)
            out.append("goal %s | %s" % (ui.bgoal and {k: ui.bgoal[k] for k in ("w", "budget", "draw")}, ui.bgoal_status()))
            for v in [-25.0] * 20:
                ui.batt_hist.append(v)
            ui.bgoal["t"] = 0; ui.bgoal_tick(now + 2)
            out.append("over-budget w=%s" % ui.bgoal["w"])
            st = ui.remote_state(); _j.dumps(st)
            out.append("remote keys %d games %d" % (len(st), len(st["games"])))
            for a, v in (("tdp_set", "14"), ("tdp_set", "99"), ("bright", "40"), ("hz", "61"), ("bgoal", "60"), ("break", "45"),
                         ("limit", "120"), ("launch", "nope"), ("overlay", None), ("focus", None), ("profile", "saver"), ("bogus", None)):
                out.append("%s=%s -> %s" % (a, v, ui.remote_action(a, v)))
            ui.cfg["sessions"] = [{"name": "X", "start": time.time() - 3 * 3600, "dur": 2 * 3600}] + list(ui.cfg["sessions"])
            out.append("today %.0f min" % (ui.played_today() / 60))
            ui.game = {"pid": 1, "name": "Test Game", "exe": "t.exe", "start": time.time() - 3700, "peak": 0.1, "saved": None, "hub": None,
                       "fps_sum": 0, "fps_n": 0, "batt0": None}
            ui.cfg["break_every"] = 60; ui.cfg["daily_limit"] = 60; ui.cfg["limit_day"] = ""
            ui.remind_tick(time.time())
            out.append("nudge %s limit_day %s" % (bool(ui.nudge_win), ui.cfg["limit_day"]))
            ui.set_timer(15); ui.timer_end = time.time() - 1; ui.remind_tick(time.time())
            out.append("timer cleared %s" % (ui.timer_end is None))
            ui.game = None
            th = ui.theme_name; ui.surprise_theme(); out.append("surprise %s -> %s" % (th, ui.theme_name))
            ui.cfg["theme_daily"] = True; ui.cfg["theme_day"] = ""; ui.theme_day_tick(time.time()); out.append("daily %s" % ui.theme_name)
            ui.set_bgoal(0); out.append("goal off %s" % (ui.bgoal is None))
        except Exception:
            import traceback; out.append(traceback.format_exc())
        print("NEWFEAT", " || ".join(out), flush=True)
        ui.open_page(os.environ.get("NFPAGE", "playtime")); ui.request_draw()
    ui.root.after(int(os.environ.get("APWAIT", "9000")), _nf)

if os.environ.get("PLAYHIST"):
    def _ph():
        import random as _r
        _r.seed(4)
        names = [g["name"] for g in (ui.library or [])][:6] or ["Elden Ring", "Hades II", "Balatro"]
        ss = []
        now = time.time()
        for d in range(0, 75):
            if _r.random() < (0.85 if d < 9 else 0.55):
                for _ in range(_r.randint(1, 2)):
                    st = now - d * 86400 - _r.randint(0, 5) * 3600
                    ss.append({"name": _r.choice(names), "start": st, "dur": _r.randint(10, 160) * 60, "peak": 0.5,
                               "fps": _r.randint(40, 90), "w": round(_r.uniform(8, 20), 1), "id": None})
        ss.sort(key=lambda x: -x["start"])
        ui.cfg["sessions"] = ss
        ui.cfg["play_days"] = None
        ui.cfg["badges_seen"] = None
        lib = ui.library or []
        ui.cfg["favorites"] = [g["id"] for g in lib[:3]]
        ui.cfg["lists"] = {"Backlog": [g["id"] for g in lib[3:6]]}
        ui.check_badges(False)
        print("PLAYHIST streak", ui.streaks(), "earned", len(ui.cfg["badges_seen"]), flush=True)
        pg = os.environ.get("PHPAGE", "calendar")
        if pg == "homefav":
            ui.cfg["home_row"] = "fav"
        else:
            ui.open_page(pg)
        ui.request_draw()
    ui.root.after(int(os.environ.get("APWAIT", "9000")), _ph)

if os.environ.get("V96"):
    def _v96():
        import json as _j
        out = []
        try:
            import systools; systools.sleep_now = lambda: out.append("SLEPT") or True
            lib = ui.library or []
            g = lib[0]
            ui.save_note(g, "Beat Margit next, then Stormveil. Use the bleed build")
            out.append("note " + ui.note_of(g["id"])[:20])
            ui.open_gameinfo(g); ui.cards_gameinfo()
            ui.edit_note(); ui.cards_gameinfo(); out.append("osk %s" % bool(ui.osk))
            ui.close_keyboard(); ui._note_edit = None
            (ui.export_history(), out.append("export ok")) if not os.environ.get("NOEXPORT") else None
            ui.set_sleep(15); out.append("sleep " + ui.sleep_label())
            ui.sleep_at = time.time() + 30; ui.sleep_tick(time.time()); ui.sleep_at = time.time() - 1; ui.sleep_tick(time.time())
            out.append("after-sleep " + ui.sleep_label())
            ui.set_sleep(-1); out.append("sleep -1 " + str(ui.cfg["sleep_after_game"])); ui.set_sleep(0)
            from PIL import Image
            pth = os.path.join(os.environ.get("TEMP", "."), "cov_test.png")
            Image.new("RGB", (60, 90), (200, 40, 60)).save(pth)
            out.append("accent %s" % ui.art_accent(pth, True))
            ui.cfg["daynight"] = True; ui.cfg["dn_period"] = ""; ui.cfg["day_start"] = 0; ui.cfg["night_start"] = 23
            ui.cfg["day_theme"] = "Sakura"; ui.daynight_tick(time.time()); out.append("daynight " + ui.theme_name)
            ui.cfg["daynight"] = False
            ui._fy = None; out.append("foryou %d" % len(ui.for_you()))
            ui.tool_toggle("sleep"); ui.tool_toggle("calendar"); out.append("tools " + ",".join(ui.cfg["home_tools"]))
            ui.tool_move("sleep"); ui.cards_hometools()
            out.append("shots %s" % (ui.remote_shots()[:1],))
            out.append("remote sleep " + ui.remote_action("sleep", "30")); ui.set_sleep(0)
            _j.dumps(ui.remote_state())
            ui.cfg["favorites"] = [x["id"] for x in lib[:2]]
            ui.cfg["guest_shelf"] = "fav"; ui.cfg["guest_pin"] = ""
            ui.pin_mode = "set"; ui.pin_typed = ""
            for d in "1357": ui.pin_key(d, "set")
            out.append("pin " + ui.cfg["guest_pin"])
            ui.start_guest(); out.append("guest %s lib %d" % (ui.cfg["guest"], len(ui.lib_games())))
            ui.open_page("settings"); ui.draw(); out.append("page " + str(ui.page))
            ui.set_tab("memory"); ui.draw(); out.append("tab " + ui.tab)
            ui.play(lib[5]) if len(lib) > 5 else None
            for d in "1111": ui.pin_key(d, "exit")
            out.append("still guest %s" % ui.cfg["guest"])
        except Exception:
            import traceback; out.append(traceback.format_exc())
        print("V96", " || ".join(out), flush=True)
        pg = os.environ.get("V96PAGE", "")
        if pg == "guestexit":
            for d in "1357": ui.pin_key(d, "exit")
            ui.request_draw()
        elif pg == "guest":
            ui.page = None; ui.request_draw()
        elif pg:
            ui.cfg["guest"] = False
            if pg == "home":
                ui.page = None; ui.set_tab("home")
            elif pg == "gameinfo":
                ui.open_gameinfo((ui.library or [])[0])
            else:
                ui.page = pg
            ui.request_draw()
    ui.root.after(int(os.environ.get("APWAIT", "9000")), _v96)

if os.environ.get("JANK"):
    def _jank():
        draws = []; frames = []
        od = ui.draw
        def wd(*a, **k):
            t0 = time.perf_counter(); r = od(*a, **k); draws.append((t0, time.perf_counter() - t0, ui.draw_scope)); return r
        ui.draw = wd
        of = ui.fx_step
        steps = []
        def wf():
            frames.append(time.perf_counter()); r = of(); steps.append(time.perf_counter() - frames[-1]); return r
        ui.fx_step = wf
        def rep():
            gaps = [b - a for a, b in zip(frames, frames[1:])]
            gaps.sort()
            steps.sort(); print("JANK step_ms p50 %.1f fx_cost %.1f" % (steps[len(steps)//2]*1000 if steps else -1, ui.fx_cost*1000), flush=True)
            print("JANK frames %d draws %d draw_ms %s gaps_ms p50 %.0f p90 %.0f max %.0f" % (
                len(frames), len(draws), [round(d[1] * 1000) for d in draws][:12],
                gaps[len(gaps) // 2] * 1000 if gaps else -1, gaps[int(len(gaps) * 0.9)] * 1000 if gaps else -1,
                gaps[-1] * 1000 if gaps else -1), flush=True)
            ui.root.destroy()
        ui.root.after(8000, rep)
    ui.root.after(int(os.environ.get("APWAIT", "9000")), _jank)

if os.environ.get("V97"):
    def _v97():
        import json as _j, systools as S_
        out = []
        try:
            opened, typed = [], []
            S_.open_target = lambda t: opened.append(t) or True
            S_.close_apps = lambda names: ["chrome.exe"]
            S_.mouse_move = lambda dx, dy: typed.append(("m", dx, dy)) or True
            S_.mouse_click = lambda right=False: typed.append(("c", right)) or True
            S_.type_text = lambda t: typed.append(("t", t)) or True
            S_.tap_key = lambda vk: typed.append(("k", vk)) or True
            S_.recycle = lambda p: True
            S_.find_leftovers = lambda: [{"kind": "folder", "name": "OldGame", "path": r"D:\\SteamLibrary\\steamapps\\common\\OldGame", "size": 7.4e9},
                                         {"kind": "shaders", "name": "Shader cache for app 4000", "path": r"C:\\x", "size": 3.1e8}]
            S_.steam_friends = lambda k, s: [{"name": "Kai", "state": 1, "game": "Hades II", "last": 0}, {"name": "Mira", "state": 1, "game": "", "last": 0},
                                             {"name": "Ollie", "state": 0, "game": "", "last": 5}]
            S_.weather_now = lambda la, lo, f: {"temp": 41.0, "hi": 47.0, "lo": 33.0, "text": "Partly cloudy", "code": 2}
            S_.find_place = lambda n: ("Detroit, Michigan", 42.33, -83.05)
            S_.steam_user_id = lambda: "76561198000000000"
            lib = ui.library or []
            g = lib[0]
            ui.set_extra(g["id"], "with", r"C:\\Tools\\Tracker.exe"); ui.set_extra(g["id"], "after", r"C:\\Tools\\Backup.bat"); ui.set_extra(g["id"], "browsers", True)
            ui.run_launch_extras(g, "with"); ui.run_launch_extras(g, "after")
            time.sleep(0.3)
            out.append("opened %s" % opened)
            ui.cfg["batt_log"] = [{"d": "2026-0%d-01" % m, "full": 49000 - m * 300, "design": 49200, "cycles": 80 + m * 9} for m in range(1, 10)]
            ui.batt_static = {"design": 49200, "full": 46100, "cycles": 162, "maker": "SMP"}
            ui.log_battery(ui.batt_static); out.append("batt log %d" % len(ui.cfg["batt_log"]))
            out.append("battery cards %d" % len(ui.cards_battery()))
            ui.leftovers = S_.find_leftovers(); out.append("left cards %d dups %d" % (len(ui.cards_leftovers()), len(ui.duplicates())))
            ui.remove_leftover(ui.leftovers[0])
            ui.friends = S_.steam_friends(1, 2); out.append("friends %s" % [c_["title"] for c_ in ui.cards_friends()])
            ui.set_city("Detroit")
            for _ in range(20): ui.root.update(); time.sleep(0.05)
            out.append("weather %s %s" % (ui.cfg["weather_place"], ui.weather_label()))
            for a, v in (("mouse", "12,-5"), ("click", "right"), ("type", "hello"), ("key", "enter"), ("key", "nope")):
                out.append("%s->%r" % (a, ui.remote_action(a, v)))
            out.append("typed %s" % typed)
            ui.cfg["phone_input"] = False; out.append("off->%r" % ui.remote_action("mouse", "1,1")); ui.cfg["phone_input"] = True
            ui.nudge("Test alert", "body"); st = ui.remote_state(); _j.dumps(st); out.append("events %d" % len(st["events"]))
            pth = os.path.join(os.environ.get("TEMP", "."), "share_test.png")
            S_.share_card(pth, "November", "27h played over 13 days", [("1. Elden Ring", "11h 03m"), ("Best streak", "7 days")], "#ff8fc7", "#ffd1e8", "#2a0f26", "Vanta")
            out.append("share %d bytes" % os.path.getsize(pth))
            import shutil; shutil.copy(pth, r"Z:\\tmp\\th\\share_test.png")
            ui.cfg["home_tools"] = ["weather", "music", "clock", "battery", "friends", "menu"]
            print("V97", " || ".join(out), flush=True)
        except Exception:
            import traceback; print("V97", traceback.format_exc(), flush=True)
        pg = os.environ.get("V97PAGE", "")
        if pg == "home":
            ui.page = None; ui.set_tab("home")
        elif pg == "gameinfo":
            ui.open_gameinfo((ui.library or [])[0])
        elif pg:
            ui.page = pg
        ui.request_draw()
    ui.root.after(int(os.environ.get("APWAIT", "9000")), _v97)

if os.environ.get("V98"):
    def _v98():
        import systools as S_, types as _t
        out = []
        try:
            now = time.time()
            S_.steam_news = lambda appid, count=3: [{"title": "Patch 1.16.1 Notes: balance changes and fixes", "date": int(now - 86400 * 0.4),
                "url": "https://store.steampowered.com/news/x", "text": "Fixed a crash when loading saves. Improved performance in Leyndell. Adjusted several bosses.", "patch": True, "official": True},
                {"title": "Community spotlight", "date": int(now - 86400 * 6), "url": "", "text": "Art from players.", "patch": False, "official": True}]
            S_.monitor_count = lambda: ui._mons
            S_.screen_size = lambda: ui._size
            switched = []
            S_.display_switch = lambda m: switched.append(m) or True
            S_.close_apps = lambda names: list(names)
            S_.wake_on_lan = lambda mac, ip=None: True
            S_.friends_playtime = lambda k, sid, appid, limit=40: [("Kai", 210.5), ("Mira", 12.0)]
            S_.steam_user_id = lambda: "765"
            S_.boot_report = lambda: {"boots": [(now - 3600, 38.2, 19.5, 18.7), (now - 90000, 44.0, 21.0, 23.0)],
                                      "slow": [("Discord", 6.4), ("OneDrive", 3.1)], "last": now - 3600}
            lib = ui.library or []
            steam = [g for g in lib if str(g["id"]).startswith("steam:")]
            g = steam[0] if steam else lib[0]
            ui.cfg["steam_key"] = "k"
            ui.news_tick(True)
            for _ in range(40): ui.root.update(); time.sleep(0.05)
            out.append("news %d games, cards %d" % (len(ui.news), len(ui.cards_news())))
            ui._fy = None; out.append("foryou0 " + (ui.for_you()[0][0] if ui.for_you() else "-"))
            ui._mons, ui._size = 1, (1280, 800); ui.cfg["dock_auto"] = True; ui.cfg["dock_switch"] = True; ui.cfg["dock_profile"] = "max"
            ui.dock_tick(); ui._mons = 2; ui.dock_tick(); out.append("docked scale %s switched %s" % (ui.cfg["ui_scale"], switched))
            ui._mons, ui._size = 1, (1920, 1080); ui.dock_tick(); out.append("still docked %s" % (ui.dock_saved is not None))
            ui._size = (1280, 800); ui.dock_tick(); out.append("undocked scale %s" % ui.cfg["ui_scale"]); ui.cfg["dock_auto"] = False
            ui.cfg["close_stores"] = ["Epic"]; ui.after_game_stores({"source": "Epic"}); out.append("store close scheduled")
            ui.cfg["wol"] = {"192.168.1.20": "aa:bb:cc:dd:ee:ff"}; ui.wake_pc("192.168.1.20")
            for x in lib[1:4]: ui.queue_toggle(x)
            ui.queue_move(lib[3]["id"], -1); out.append("queue " + ",".join(x["name"][:6] for x in ui.queue_games()))
            ui.set_finished(lib[2]); ui.set_finished(lib[2], True, 4); out.append("finished %s queue %d" % (ui.cfg["finished"][lib[2]["id"]].get("stars"), len(ui.cfg["queue"])))
            ui.compare_friends(g)
            for _ in range(20): ui.root.update(); time.sleep(0.05)
            out.append("friends %s" % (ui.friend_hours["data"],))
            ev = _t.SimpleNamespace(keysym="2", char="2", state=0x4); ui.on_key(ev); out.append("ctrl2 tab " + ui.tab)
            ev = _t.SimpleNamespace(keysym="u", char="u", state=0x4); ui.on_key(ev); out.append("ctrlU page " + str(ui.page))
            ui.page = None
            ui.boot = S_.boot_report(); out.append("boot cards %d" % len(ui.cards_bootreport()))
            class _P: slot = None; hid = None
            ui.pad_axes = lambda: ("Xbox (XInput)", 0x1000 | 0x0200 | 0x0008, 0.62, 0.35, -0.1, 0.04, 0.0, 0.8)
            out.append("pad cards %d" % len(ui.cards_padtest()))
            ui.drift = {"l": 0.03, "r": 0.12}
            for f in ("cards_news", "cards_dock", "cards_storeclose", "cards_queue", "cards_shortcuts", "cards_padtest"): getattr(ui, f)()
            ui.open_gameinfo(g); ui.cards_gameinfo()
        except Exception:
            import traceback; out.append(traceback.format_exc())
        print("V98", " || ".join(out), flush=True)
        pg = os.environ.get("V98PAGE", "")
        if pg == "gameinfo": ui.open_gameinfo(g)
        elif pg == "home": ui.page = None; ui.set_tab("home")
        elif pg: ui.page = pg
        ui.request_draw()
    ui.root.after(int(os.environ.get("APWAIT", "9000")), _v98)

if os.environ.get("FOCUSTEST"):
    def _ft():
        import ctypes as _c
        u = _c.windll.user32
        h0 = ui.hwnd
        def rep(tag):
            fg = u.GetForegroundWindow()
            print("FOCUS", tag, "focused", ui.focused(), "old_check", fg == h0, "fg", fg, "h0", h0, "now", ui.cur_hwnd(), "front", ui.front_window(), flush=True)
        rep("start")
        ui.toggle_fullscreen(); ui.root.update()
        ui.root.after(2500, lambda: (rep("fullscreen"), ui.toggle_fullscreen(), ui.root.after(2500, lambda: (rep("windowed"), ui.root.destroy()))))
    ui.root.after(9000, _ft)

if os.environ.get("V99"):
    def _v99():
        import systools as S_
        out = []
        try:
            now = time.time()
            S_.steam_reviews = lambda appid: {"desc": "Very Positive", "pct": 92, "total": 512345}
            S_.steam_genres = lambda appid: {"1000": ["Action", "RPG"], "1001": ["Action", "Roguelike", "Indie"]}.get(str(appid), ["Adventure"])
            S_.toggle_recording = lambda: out.append("REC")
            S_.list_captures = lambda limit=120: [{"path": r"C:\\c\\a.png", "name": "a.png", "kind": "shot", "size": 1, "time": now - 3000}]
            copied = []
            S_.copy_capture = lambda src, folder: copied.append(folder) or True
            S_.set_app_volume = lambda match, level: out.append("VOL %.2f" % level) or 1
            S_.quiet_other_apps = lambda keep, level: {123: 0.8}
            S_.restore_app_volumes = lambda saved: out.append("RESTORE %s" % saved) or True
            S_.open_target = lambda t: out.append("OPEN " + t) or True
            lib = ui.library or []
            g = lib[0]
            ui.reviews.clear(); ui.review_of(g)
            for _ in range(20): ui.root.update(); time.sleep(0.03)
            out.append("review chip %s" % ui.review_chip(g))
            ui.genres_started = False; ui.cfg["genres"] = {}
            S_time = time.sleep; time.sleep = lambda x: None
            ui.fetch_genres()
            for _ in range(40): ui.root.update(); S_time(0.03)
            time.sleep = S_time
            out.append("genres %s counts %s" % (len(ui.cfg["genres"]), ui.genre_counts()[:3]))
            ui.cfg["lib_filter"] = "genre:RPG"; out.append("rpg games %d" % len(ui.lib_games())); ui.cfg["lib_filter"] = "all"
            ui.cfg["known_games"] = {}; ui.cfg["gone_games"] = {}
            ui.track_library(lib); ui.track_library(lib[1:])
            out.append("gone %s" % list(ui.cfg["gone_games"]))
            out.append("reinstall %s" % ui.reinstall_target(g["id"], ui.cfg["gone_games"].get(g["id"], {})))
            ui.cfg["launch_args"] = {g["id"]: "-dx11 -windowed"}
            out.append("args %s" % ui.with_launch_args(g).get("launch"))
            ui.toggle_recording(); ui.toggle_recording()
            ui.sort_captures([{"name": "ELDEN RING", "start": now - 4000, "dur": 3000}], quiet=True)
            for _ in range(20): ui.root.update(); time.sleep(0.03)
            out.append("sorted %s" % copied)
            lt = time.localtime(); m = lt.tm_hour * 60 + lt.tm_min
            ui.cfg["automations"] = [{"id": 77, "on": True, "trigger": "time", "arg": m - m % 30, "days": "every day", "action": "brightness", "value": 40}]
            ran = []; orr = ui.run_rule; ui.run_rule = lambda r, d=None: ran.append(r["id"])
            ui.time_rules_tick(time.time()); ui.time_rules_tick(time.time())
            ui.run_rule = orr; out.append("time rule ran %s text %s" % (ran, ui.rule_text(ui.cfg["automations"][0])))
            ui.cards_automations() if hasattr(ui, "cards_automations") else None
            ui.save_note(g, "mine")
            ui.cfg["person"] = "Alex"; ui.switch_person("Sam"); out.append("sam note %r sessions %d" % (ui.note_of(g["id"]), len(ui.cfg["sessions"])))
            ui.switch_person("Alex"); out.append("alex note %r people %s" % (ui.note_of(g["id"]), list(ui.cfg["people"])))
            ui.game = {"pid": 4242, "name": "X", "exe": "x.exe", "start": now, "peak": 0, "hub": {"id": g["id"]}}
            ui.cfg["game_volume"] = {g["id"]: 60}; ui.cfg["quiet_others"] = 30
            ui.apply_game_audio()
            for _ in range(20): ui.root.update(); time.sleep(0.03)
            ui.restore_game_audio(ui.game); ui.game = None
            for _ in range(10): ui.root.update(); time.sleep(0.03)
            ui.cfg["batt_hist"] = [["2026-06-01", 48000, 49200, 90], ["2026-11-01", 46000, 49200, 160]]
            out.append("batt series %d" % len(ui.batt_series()))
            for f in ("cards_reinstall", "cards_people", "cards_pick", "cards_collections", "cards_battery"): getattr(ui, f)()
            ui.open_gameinfo(g); ui.cards_gameinfo()
            ui.cfg["quiet_others"] = 100
        except Exception:
            import traceback; out.append(traceback.format_exc())
        print("V99", ascii(" || ".join(out)), flush=True)
        pg = os.environ.get("V99PAGE", "")
        if pg == "gameinfo": ui.open_gameinfo((ui.library or [])[0])
        elif pg == "home": ui.page = None; ui.set_tab("home")
        elif pg == "lib": ui.page = None; ui.cfg["lib_filter"] = "genre:Action"; ui.set_tab("play")
        elif pg: ui.page = pg
        ui.request_draw()
    ui.root.after(int(os.environ.get("APWAIT", "9000")), _v99)

if os.environ.get("STUCKTEST"):
    def _st():
        import types as _t
        G = R.Gamepad
        out = []
        def mk():
            pad = G.__new__(G); pad.get = lambda i, st: 1167; pad.slot, pad.prev, pad.next_scan, pad.repeat_at = None, 0, 0.0, {}
            pad.getbat = None; pad.hid = _t.SimpleNamespace(pad_state=None)
            pad.axis_seen_center = [False, False]; pad.held_since = {}; pad.stuck = 0; pad.stick_nav = True
            return pad
        pad = mk(); ev = []
        for i in range(30):
            pad.hid.pad_state = (time.time(), 0, -1.0, -1.0, 0, 0); ev += pad.poll(); time.sleep(0.01)
        out.append("stuck axis events %s" % ev)
        pad = mk(); ev = []
        pad.hid.pad_state = (time.time(), 0, 0.0, 0.0, 0, 0); ev += pad.poll()
        pad.hid.pad_state = (time.time(), 0, 0.0, -0.9, 0, 0); ev += pad.poll()
        out.append("real push %s" % ev)
        pad = mk(); ev = []
        t0 = time.time(); real = time.time
        for i in range(12):
            time.time = lambda i=i: t0 + i
            pad.hid.pad_state = (t0 + i, 0x0004, 0.0, 0.0, 0, 0); ev += pad.poll()
        time.time = real
        out.append("held left %d events, stuck %s" % (len(ev), pad.stuck))
        pad.hid.pad_state = (time.time(), 0, 0.0, 0.0, 0, 0); pad.poll(); out.append("released stuck %s" % pad.stuck)
        print("STUCK", " || ".join(out), flush=True); ui.root.destroy()
    ui.root.after(6000, _st)

if os.environ.get("PADSTATE"):
    ui.root.after(7000, lambda: (print("PADSTATE", ui.cfg["legion_buttons"], ui.cfg["pad_combo"], ui.cfg["ls_keep_closed"], ui.legion is None,
                                       getattr(ui.pad, "hid", "nopad"), ascii([l[2] for l in list(ui.log)[-6:]]), flush=True), ui.root.destroy()))
if os.environ.get("RINGTEST"):
    ui.root.after(7000, lambda: (setattr(ui, "focus_visible", True), setattr(ui, "focus_id", "tab_memory"), ui.request_draw()))
if os.environ.get("INTERACT"):
    def _it():
        E = type("E", (), {})
        def med(fn, n=9):
            ts = []
            for i in range(n):
                t0 = time.perf_counter(); fn(i); ui.root.update_idletasks(); ts.append((time.perf_counter() - t0) * 1000)
                ui.root.update()
            ts.sort(); return ts[n // 2]
        ui.set_tab("tools"); ui.draw_scope = "all"; ui.draw(); ui.root.update()
        btn = next(r for r in ui.active_regions() if r["kind"] == "button" and r["id"].startswith("prof_"))
        def press(i):
            e = E(); e.x, e.y = (btn["x0"] + btn["x1"]) / 2, (btn["y0"] + btn["y1"]) / 2
            ui.on_press(e)
        def release(i):
            e = E(); e.x, e.y = (btn["x0"] + btn["x1"]) / 2, (btn["y0"] + btn["y1"]) / 2
            ui.press = None; ui.pressed = None; ui.c.delete("pressfx")
        out = ["press feedback %.1f ms" % med(lambda i: (press(i), ui.root.update_idletasks(), release(i)))]
        ui.focus_visible = True; ui.focus_id = btn["id"]; ui.draw(); ui.root.update()
        out.append("controller move %.1f ms" % med(lambda i: ui.nav("down" if i % 2 == 0 else "up")))
        ui.open_page("settings"); ui.draw_scope = "all"; ui.draw(); ui.root.update()
        row = next(r for r in ui.active_regions() if r["id"].startswith("set_"))
        def tap(i):
            e = E(); e.x, e.y = (row["x0"] + row["x1"]) / 2, (row["y0"] + row["y1"]) / 2
            ui.on_press(e); ui.on_release(e); ui.draw()
        out.append("tap in settings %.1f ms" % med(tap, 5))
        print("INTERACT", " | ".join(out), flush=True); ui.root.destroy()
    ui.root.after(int(os.environ.get("APWAIT", "11000")), _it)
if os.environ.get("PRESSSHOT"):
    ui.root.after(8000, lambda: (setattr(ui, "pressed", next(r["id"] for r in ui.active_regions() if r["id"].startswith("prof_"))), ui.draw_press()))
if os.environ.get("PADPATH"):
    def _pp():
        import types as _t
        G = R.Gamepad
        pad = G.__new__(G); pad.get = lambda i, st: 1167; pad.slot, pad.prev, pad.next_scan, pad.repeat_at = None, 0, 0.0, {}
        pad.getbat = None
        st = {"b": 0}
        pad.hid = _t.SimpleNamespace(pad_state=None)
        ui.pad = pad
        if os.environ.get("PADQUICK"):
            ui.open_quick(); ui.quick_autoclose = False; ui.panel_focused = lambda: False
        def feed(b):
            pad.hid.pad_state = (time.time(), b, 0.0, 0.0, 0, 0)
        seq = [0, 0x0002, 0, 0x0002, 0, 0x0008, 0, 0x1000, 0]
        log = []
        def stepper(i=0):
            if i < len(seq):
                feed(seq[i]); pad.hid.pad_state = (time.time(), seq[i], 0.0, 0.0, 0, 0)
                ui.root.after(120, lambda: (log.append((seq[i], ui.focus_id, ui.page, ui.tab, bool(ui.osk), bool(ui.quick), ui.focused())), stepper(i + 1)))
            else:
                for l in log: print("PADPATH", l, flush=True)
                ui.root.destroy()
        stepper()
    ui.root.after(9000, _pp)
if os.environ.get("FINDQ"):
    ui.root.after(8000, lambda: (ui.open_find(False), setattr(ui, "find_q", os.environ["FINDQ"]), ui.request_draw()))
if os.environ.get("HINTS"):
    ui.root.after(8000, lambda: (setattr(ui, "focus_visible", True), setattr(ui, "focus_id", "tab_play"), ui.request_draw()))
if os.environ.get("HOMEPAD"):
    def _hp():
        log = []
        for b in ("down", "right", "left", "rb", "rb", "rt", "rt", "lb", "lb", "lb"):
            ui.on_pad(b); ui.root.update()
            log.append((b, ui.tab, ui.focus_id))
        for l in log: print("HOMEPAD", l, flush=True)
        ui.root.destroy()
    ui.root.after(9000, _hp)
if os.environ.get("RECAPSHOT"):
    def _rc():
        now = time.time()
        ui.cfg["sessions"] = [{"name": "ELDEN RING", "id": "steam:1000", "start": now - 4000, "dur": 3900, "peak": 0.71, "fps": 58.4,
                               "low": 44, "batt": 31, "w": 17.6, "tdp": 18, "cap": 60},
                              {"name": "ELDEN RING", "id": "steam:1000", "start": now - 90000, "dur": 3000, "peak": 0.69, "fps": 52.1,
                               "low": 39, "batt": 30, "w": 19.2, "tdp": 20, "cap": None},
                              {"name": "Hades", "id": "steam:1001", "start": now - 190000, "dur": 1300, "peak": 0.4, "fps": 120,
                               "batt": 8, "w": 9.5},
                              {"name": "Hades", "id": "steam:1001", "start": now - 290000, "dur": 1500, "peak": 0.4}]
        ui.recap = ui.cfg["sessions"][0]; ui.recap_new = True
        ui.open_page(os.environ["RECAPSHOT"]) if os.environ["RECAPSHOT"] != "recap" else ui.show_recap_soon()
    ui.root.after(8000, _rc)
if os.environ.get("ANIMPERF"):
    if os.environ.get("NOSHADOW"): ui.shadow = lambda *a, **k: (None, 0)
    if os.environ.get("NOAMB"): ui.cfg["ambient"] = False
    if os.environ.get("NOHERO"): ui.hero = lambda *a, **k: None
    def _ap():
        import cProfile, pstats, io
        out = []
        pr = cProfile.Profile()
        for tab in ("play", "memory", "tools", "system"):
            ui.page = None; ui.set_tab(tab); ui.motions.clear(); ui.draw(); ui.root.update()
            ts = []
            for i in range(15):
                t0 = time.perf_counter()
                ui.draw_scope = "all"
                if tab == "play": pr.enable()
                ui.draw(); ui.root.update_idletasks()
                if tab == "play": pr.disable()
                ts.append((time.perf_counter() - t0) * 1000)
            ts.sort()
            out.append(f"{tab}: median {ts[7]:.1f} ms  min {ts[0]:.1f}  items {len(ui.c.find_all())}")
        # hover-only change on play
        ui.set_tab("play"); ui.motions.clear(); ui.draw(); ui.root.update()
        ts = []
        for i in range(15):
            t0 = time.perf_counter(); ui.c.move("content", 3 if i % 2 else -3, 0); ui.root.update_idletasks(); ts.append((time.perf_counter() - t0) * 1000)
        ts.sort(); out.append(f"move content: {ts[7]:.1f} ms")
        ts = []
        for i in range(15):
            t0 = time.perf_counter(); ui.c.delete("hov"); ui.rr(300, 300 + i, 500, 400 + i, 14, "", outline="#8b7bff", width=2); ui.c.addtag_all  # noqa
            ui.root.update_idletasks(); ts.append((time.perf_counter() - t0) * 1000)
        ts.sort(); out.append(f"one item: {ts[7]:.1f} ms")
        ts = []
        for i in range(15):
            t0 = time.perf_counter(); ui.c.delete("all"); ui.root.update_idletasks(); ts.append((time.perf_counter() - t0) * 1000); ui.draw_scope="all"; ui.draw(); ui.root.update_idletasks()
        ts.sort(); out.append(f"delete all: {ts[7]:.1f} ms")
        def med(fn, n=15):
            ts = []
            for i in range(n):
                t0 = time.perf_counter(); fn(i); ui.root.update_idletasks(); ts.append((time.perf_counter() - t0) * 1000)
            ts.sort(); return ts[n // 2]
        ui.set_tab("play"); ui.draw_scope = "all"; ui.draw(); ui.root.update()
        out.append("lib scroll frame: %.1f ms" % med(lambda i: (ui.set_off("lib", 40 + (i % 5) * 30), setattr(ui, "draw_scope", "lib"), ui.draw())))
        ids = [r["id"] for r in ui.regions if r["id"].startswith("g_")][:2]
        out.append("hover: %.1f ms" % med(lambda i: ui.set_hover(ids[i % 2])))
        def slide(i):
            ui.begin_slide("tab", "content", 0, 46 * ui.k, 0.3); ui.draw_scope = "all"; ui.draw()
        out.append("tab first frame: %.1f ms" % med(slide, 5))
        _ops = ui.place_slide; _log = []
        ui.place_slide = lambda n, r: (_log.append((n, dict(ui.slides.get(n) or {}))), _ops(n, r))[1]
        ui.slides.clear(); ui.begin_slide("tab", "content", 0, 46 * ui.k, 60.0); _log.append(("after begin", list(ui.slides))); ui.draw_scope = "all"; ui.draw(); _log.append(("after draw", list(ui.slides))); ui.root.update()
        out.append("tab slide frame: %.1f ms" % med(lambda i: ui.anim_tick()))
        ui.slides.clear()
        print("ANIMPERF", " | ".join(out), flush=True)
        sio = io.StringIO(); pstats.Stats(pr, stream=sio).sort_stats("tottime").print_stats(18); print(sio.getvalue()[:3800], flush=True)
        ui.root.destroy()
    ui.root.after(int(os.environ.get("APWAIT", "9000")), _ap)
if os.environ.get("AMBDBG"):
    ui.root.after(20000, lambda: (print("AMB", [(k_, v) for k_, v in ui.covers.items() if str(k_[0]).startswith("amb")], "pending", [k_ for k_ in ui.cover_pending if str(k_[0]).startswith("amb")], "sel", ui.selected_game() and {a: ui.selected_game().get(a) for a in ("id", "hero", "cover")}, flush=True), ui.root.destroy()))
ui.root.mainloop()
