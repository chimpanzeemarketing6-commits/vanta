import faulthandler, sys as _s; faulthandler.dump_traceback_later(int(__import__("os").environ.get("FH", "400")), exit=True, file=_s.stderr)
import os, sys, time, traceback, types
sys.path.insert(0, r"Z:\home\claude\app")
os.environ["TAB"] = ""
exec(open(r"Z:\home\claude\testkit\fake_run.py").read().split("ui = R.UI()")[0])
R.set_startup = lambda on: True
S.set_startup_item = lambda it, on: True
S.set_tweak = lambda t, on: True
S.set_thermal_mode = lambda v: True
S.set_power_mode = lambda m: True
S.clean_category = lambda c: 12345
S.open_target = lambda t: True
S.restart_pc = lambda: print("RESTART CALLED (should only be after confirm)")
S.set_display_mode = lambda *a, **kw: True
S.apply_profile = lambda pid, legion: ["power mode", "thermal mode"]
S.set_tdp = lambda w, m=30: True
S.set_charge_limit = lambda on: True
S.close_apps = lambda n: n
S.set_brightness = lambda p: True
S.volume_key = lambda *a: None
S.download_presentmon = lambda: "v2.3"
S.recycle = lambda p: True
S.show_in_explorer = lambda p: None
R.game_boost = lambda: (1e8, 0.3, 42)
R.run_action = lambda a: (5e7, 0.1)
R.trim_process = lambda pid: (True, 1e6)
S.send_keys = lambda *k: print("KEYS", k)
os.startfile = lambda *a: print("STARTFILE", a)
S.type_text = lambda t: print("TYPE", repr(t)) or True
import tkinter.filedialog as _fd
_fd.askdirectory = lambda **k: r"C:\ROMs"
_fd.askopenfilename = lambda **k: r"C:\wall.jpg"
S.play_sound = lambda n: None
S.prepare_sounds = lambda v=0.25: None
S.ludusavi_installed = lambda: True
S.ludusavi = lambda action, game, path=None: (True, "done", 123456)
S.steam_running = lambda: False
S.move_steam_game = lambda appid, target, progress=None: (progress and progress(50, 100), (True, "moved"))[1]
S.check_update = lambda repo, cur, asset: (True, "v6.1", "https://example.invalid/Vanta.exe", "notes")
S.get_radios = lambda: {"wifi": True, "bluetooth": False}
S.set_radio = lambda kind, on: True
S.ping = lambda host="1.1.1.1", count=4, timeout_ms=1000: (23.4, 0)
S.wifi_info = lambda: {"ssid": "HomeNet", "signal": 80}
S.now_playing = lambda: "Artist - Song"
S.suspend_process = lambda pid, resume=False: True
S.key_combo = lambda combo, down=True, up=True: print("COMBO", combo, down, up) or True
S.media_key = lambda w: print("MEDIA", w)
S.mouse_move = lambda dx, dy: True
S.get_cpu_max = lambda: (100, 100)
S.set_cpu_max = lambda ac, dc=None: True
S.sleep_now = lambda: print("SLEEP")
S.restart_now = lambda: print("RESTART")
S.shutdown_now = lambda: print("SHUTDOWN")
S.last_wake = lambda: "Intel Wi-Fi"
S.steam_states = lambda: {"1001": ("UPDATING", 43.0)}
S.shader_cache = lambda appid: (None, int(1.4e9))
S.clear_shader_cache = lambda appid: int(1.4e9)
S.notifications_enabled = lambda: True
S.set_notifications = lambda on: print("NOTIF", on) or True
S.updates_paused = lambda: False
S.pause_updates = lambda h=12: print("PAUSE UPDATES") or True
S.resume_updates = lambda: print("RESUME UPDATES") or True
S.sgdb_cover = lambda key, gid, name: None
S.steam_art = lambda appid, kind="cover": None
S.steam_appid_for = lambda name: None
S.steam_achievements = lambda key, sid, appid: (23, 50)
S.steam_user_id = lambda: "76561197960435530"
import tempfile as _tf
_sync_dir = _tf.mkdtemp()
S.sync_folder = lambda: _sync_dir
S.touch_keyboard = lambda: print("OSK") or True
S.end_process = lambda pid, name: True
errors = []
ui = R.UI()
ui.root.report_callback_exception = lambda *a: (errors.append("".join(traceback.format_exception(*a))), print("CALLBACK ERROR", errors[-1], flush=True), ui.root.after(10, ui.root.destroy))
ui.root.geometry("1280x800+0+0")
ui.procs = [(1000 + i, f"app{i}.exe", int(1e8 - i * 1e6)) for i in range(40)]
ui.proc_time = time.time() + 999
ui.pad.slot = 0
ui.pad.poll = lambda: []
import json as _json
def _dv(**kw):
    d = _json.load(open(r"Z:\home\claude\testkit\dv_cp.json", encoding="utf-8")); d["summary"] = d.get("reports_summary", "")
    return d
S.dv_game = _dv
S.find_stream_hosts = lambda timeout=2.5: [{"name": "GAMING-PC", "ip": "192.168.1.20"}]
S.stream_host_info = lambda ip, timeout=3: None
S.moonlight_path = lambda: r"C:\\Moonlight.exe"
S.moonlight_stream = lambda host, app="Desktop": True
S.epic_free_games = lambda: [{"title": "Knightica", "url": "https://store.epicgames.com/p/knightica", "now": True, "until": "2026-11-19T16:00:00Z", "from": None},
                             {"title": "Mark of the Deep", "url": "x", "now": False, "until": None, "from": "2026-11-19T16:00:00Z"}]
S.steam_user_id = lambda: "76561190000000000"
S.steam_wishlist_deals = lambda sid, cc="us", limit=60: [{"appid": "1091500", "name": "Cyberpunk 2077", "pct": 65, "price": "$20.99", "was": "$59.99"}]
S.ra_summary = lambda u, k, games=8: {"points": 1234, "softcore": 50, "url": "https://retroachievements.org/user/x",
    "recent": [{"id": 1, "title": "Sonic the Hedgehog", "console": "Genesis/Mega Drive", "got": 12, "total": 23, "url": "u"}]}
S.update_report = lambda: {"have": {"bios": "N3CN39WW", "mtm": "83E1", "gpu": "AMD Radeon Graphics", "drv": "32.0.21013.1000", "drvdate": "2026-09-01"},
    "items": [{"what": "BIOS", "have": "N3CN39WW", "latest": "N3CN35", "date": "2024-09-12", "newer": False},
              {"what": "AMD graphics driver (Lenovo)", "have": "32.0.21013.1000", "latest": "31.0.24028.1001", "date": "2024-06-03", "newer": False}],
    "model": "Legion Go", "catalog_ok": True}
S.pcgw_support = lambda appid=None, name=None, max_age=0: {"page": "Elden Ring", "url": "https://www.pcgamingwiki.com/wiki/Elden_Ring",
    "items": [("Upscalers", "FSR 2"), ("Frame generation", "No"), ("HDR", "Yes"), ("60 FPS", "Yes"), ("120+ FPS", "With a fix"), ("Controller", "Yes")]}
SKIP = {"hdr_close", "hdr_hide", "hdr_full", "page_close", "mon_toggle", "lib_add"}
E = lambda x, y: types.SimpleNamespace(x=x, y=y, delta=-120)
taps = 0
S.open_target = lambda *a_, **k_: True
S.sleep_now = lambda: True
def step(fn, *a):
    try: fn(*a)
    except Exception: errors.append(traceback.format_exc())
    if ui.cfg["guest"]: ui.cfg["guest"] = False; print("  (guest mode was turned on: turned off for the test)", flush=True)
    try: ui.draw()
    except Exception: errors.append(traceback.format_exc())
def run_all():
    global taps
    for tab in ["home", "play", "memory", "clean", "tools", "games", "system", "startup"]:
        print("TAB", tab, flush=True)
        step(ui.set_tab, tab); ui.root.update(); time.sleep(0.3); ui.root.update()
        step(ui.draw)
        for r in list(ui.active_regions()):
            if r["id"] in SKIP or r["id"].startswith("tab_"): continue
            cx, cy = (r["x0"]+r["x1"])/2, (r["y0"]+r["y1"])/2
            print("  tap", r["id"], flush=True)
            step(ui.on_press, E(cx, cy)); step(ui.on_release, E(cx, cy)); taps += 1
            ui.root.update()
            if ui.page: step(ui.back)
        # drag every scroll area
        for sid, s in list(ui.scrolls.items()):
            y = s["y0"] + s["h"] / 2
            step(ui.on_press, E(300, y))
            for d in range(1, 8): step(ui.on_motion, E(300, y - d * 30))
            step(ui.on_release, E(300, y - 210)); step(ui.on_wheel, E(300, y))
        for b in ["down"] * 12 + ["right"] * 4 + ["up"] * 15 + ["left"] * 4 + ["a", "lt", "rt", "x", "y", "ls", "rs"]:
            step(ui.on_pad, b); ui.root.update()
        print("  pad done", flush=True)
        t0=time.time()
        while ui.busy and time.time()-t0<10: ui.root.update(); time.sleep(0.05)
        print("  busy", ui.busy, flush=True)
    ui.dv.clear(); ui.dv["steam:1000"] = {"status": "ok", "data": _dv(), "appid": "1245620"}
    for gen in ("go1", "go2"):
        ui.cfg["preset_gen"] = gen
        print("  community", gen, [(p["tag"], p.get("tdp"), (p.get("amd") or {}).get("frtc_fps")) for p in ui.community_for("steam:1000")], flush=True)
    ui.cfg["preset_gen"] = "auto"
    now_ = time.time()
    ui.cfg["sessions"] = [{"name": "ELDEN RING", "start": now_ - 4000, "dur": 1800, "peak": 0.5, "id": "steam:1000", "key": "steam:1000",
                           "fps": 66.0, "low": 55.0, "w": 19.5, "tdp": 22, "cap": None, "batt": 20},
                          {"name": "ELDEN RING", "start": now_ - 90000, "dur": 1200, "peak": 0.5, "id": "steam:1000", "key": "steam:1000",
                           "fps": 64.0, "low": 54.0, "w": 19.0, "tdp": 22, "cap": None, "batt": 15}] + list(ui.cfg["sessions"])
    ui.pcgw.clear(); ui.lookup_pcgw("steam:1000", "ELDEN RING")
    for _ in range(20): ui.root.update(); time.sleep(0.05)
    print("  insight cards:", [(c_["title"], [l[0][:50] for l in c_["lines"]]) for c_ in ui.insight_cards("steam:1000", "ELDEN RING", {})], flush=True)
    ui.share_settings("steam:1000", "ELDEN RING")
    # automations: add every idea, cycle every field, fire every trigger
    for t in R.AUTO_TEMPLATES: step(ui.add_rule, t)
    step(ui.add_rule)
    r0 = ui.cfg["automations"][-1]
    for field in ("trigger", "action", "value", "arg"):
        for _ in range(12): step(ui.rule_cycle, r0, field)
    print("  rules:", ascii([ui.rule_text(r) for r in ui.cfg["automations"]][:7]), flush=True)
    for trg in R.AUTO_TRIGGERS: step(ui.fire, trg, "Test")
    for _ in range(10): ui.root.update(); time.sleep(0.03)
    # controller as mouse: run the engine briefly on a fake controller
    import ctypes as _ct
    moves = []
    S.mouse_move = lambda dx, dy: moves.append((dx, dy)) or True
    S.mouse_button = lambda b, d: moves.append((b, d)) or True
    S.key_vk = lambda vk, d: moves.append(("key", vk, d)) or True
    S.mouse_wheel = lambda d, horizontal=False: moves.append(("wheel", d)) or True
    def _fake_get(i, ptr):
        st = _ct.cast(ptr, _ct.POINTER(S.XINPUT_STATE_SYS)).contents
        st.Gamepad.sThumbRX, st.Gamepad.sThumbLY, st.Gamepad.wButtons = 30000, -30000, 0x1000
        return 0
    dc = S.DesktopControls(_fake_get)
    dc.start("desktop"); time.sleep(0.4); dc.end(); time.sleep(0.1)
    print("  padmouse desktop:", sum(1 for m in moves if isinstance(m[0], int) and m[0] > 0), "moves,", [m for m in moves if m[0] == "left"][:2], [m for m in moves if m[0] == "wheel"][:1], flush=True)
    moves.clear(); dc.start("wasd"); time.sleep(0.3); dc.end(); time.sleep(0.1)
    print("  padmouse wasd keys:", sorted({m[1] for m in moves if m[0] == "key"}), flush=True)
    # backup + theme code
    step(ui.backup_now)
    for _ in range(20): ui.root.update(); time.sleep(0.03)
    print("  backups:", len(S.list_backups()), flush=True)
    code = S.theme_to_code({"theme": ui.cfg["theme"], "accent": ""}); print("  theme code ok:", S.theme_from_code(code) is not None, len(code), flush=True)
    for lang in ("es", "de", "fr", "ja", "en"):
        ui.cfg["lang"] = lang; step(ui.draw)
    for pg in ("automations", "pick", "gallery", "storage", "network", "stream", "deals", "retro", "updates"):
        ui.page = None; step(ui.open_info, pg)
        for _ in range(30):
            ui.root.update(); time.sleep(0.05)
            if (getattr(ui, "info_" + pg) or {}).get("status") != "loading": break
        print("  page", pg, getattr(ui, "info_" + pg)["status"], ascii([c_["title"] for c_ in getattr(ui, "cards_" + pg)()] if pg != "gallery" else "grid"), flush=True)
        for r in list(ui.active_regions()):
            if r["kind"] == "scroll" or r["id"] in SKIP: continue
            cx, cy = (r["x0"]+r["x1"])/2, (r["y0"]+r["y1"])/2
            step(ui.on_press, E(cx, cy)); step(ui.on_release, E(cx, cy)); taps += 1
            if ui.page != pg: ui.page = pg
    ui.cfg["ra_user"], ui.cfg["ra_key"] = "tester", "a" * 32
    ui.info_retro = None; ui.page = None; step(ui.open_info, "retro")
    for _ in range(30): ui.root.update(); time.sleep(0.05)
    print("  retro with account:", [c_["title"] for c_ in ui.cards_retro()], flush=True)
    ui.check_deals(force=True)
    for _ in range(30): ui.root.update(); time.sleep(0.05)
    print("  deal alerts seen:", ui.cfg["deals_seen"], flush=True)
    # controllers off and back on
    class _L: attached = {"left": True, "right": False}; connected = True; error = ""; on_gyro = None
    old_legion = ui.legion; ui.legion = _L(); ui.cfg["detach_profile"] = True; ui.cfg["detach_hz"] = 60
    sc0 = ui.cfg["ui_scale"]; step(ui.on_attach_change); print("  detached:", ui.detach_saved is not None, ui.cfg["ui_scale"], flush=True)
    ui.legion.attached = {"left": True, "right": True}; step(ui.on_attach_change)
    print("  reattached:", ui.detach_saved is None, ui.cfg["ui_scale"] == sc0, flush=True)
    ui.legion = old_legion; ui.cfg["detach_profile"] = False
    ui.page = None
    ui.tune_target = ("steam:1000", "ELDEN RING"); ui.amd_state = S.ADLX.read(); ui.tune_modes = S.display_modes()
    ui.cfg["discord_webhook"] = "https://discord.com/api/webhooks/1311223344556677889/abcDEF_token-xyz"
    ui.cfg["discord_app_id"] = "1234567890123456789"
    # settings: every category (wide and narrow), search, and the menu
    for narrow_scale in (100, 210):
        ui.cfg["ui_scale"] = narrow_scale
        step(ui.open_page, "settings")
        for cat in [c_[0][0] for c_ in ui.settings_categories()]:
            ui.anims.clear(); step(ui.pick_settings_cat, cat)
            for r in list(ui.active_regions()):
                if r["id"] in SKIP or r["id"] in ("set_startup", "set_search") or r["kind"] == "scroll": continue
                cx, cy = (r["x0"]+r["x1"])/2, (r["y0"]+r["y1"])/2
                step(ui.on_press, E(cx, cy)); step(ui.on_release, E(cx, cy)); taps += 1
                if ui.page != "settings": ui.page = "settings"
                if ui.osk: step(ui.close_keyboard)
            print("  settings cat", cat, ui.set_narrow, flush=True)
        for q in ("gyro", "zzz", "tdp"):
            ui.set_query = q; step(ui.draw)
            print("  search", q, sum(1 for r in ui.settings_view()[2] if r[3] != "header"), flush=True)
        for b in ["rb", "rb", "lb", "y", "b", "b", "rt", "lt", "b"]:
            step(ui.on_pad, b)
            if ui.osk: step(ui.close_keyboard)
        ui.page = "settings"
        for ch in "gen":
            step(ui.on_key, types.SimpleNamespace(keysym=ch, char=ch, state=0))
        print("  typed query:", repr(ui.set_query), flush=True)
        step(ui.on_key, types.SimpleNamespace(keysym="Escape", char="", state=0))
        ui.page = None
    ui.cfg["ui_scale"] = 100
    ui.anims.clear()
    for page in ["automations", "pick", "gallery", "storage", "network", "stream", "deals", "retro", "updates", "menu", "settings", "themes", "help", "log", "tune", "checkup", "welcome", "discord", "buttons", "bench", "lists", "editor"]:
        step(ui.open_page, page)
        for r in list(ui.active_regions()):
            if r["id"] in SKIP or r["id"] == "set_startup": continue
            cx, cy = (r["x0"]+r["x1"])/2, (r["y0"]+r["y1"])/2
            ui.anims.clear()
            step(ui.on_press, E(cx, cy)); step(ui.on_release, E(cx, cy)); taps += 1
            if ui.osk: step(ui.close_keyboard)
            if ui.quick: step(ui.close_quick)
            if ui.page != page: ui.page = None; step(ui.open_page, page)
        for b in ["down"] * 14 + ["left", "right", "a", "b"]:
            step(ui.on_pad, b)
        ui.page = None
    for ks in ["Tab", "Up", "Down", "Return", "Prior", "Next", "Escape"]:
        step(ui.on_key, types.SimpleNamespace(keysym=ks, char="", state=0))
    for ch in "ob123456tauch":
        step(ui.on_key, types.SimpleNamespace(keysym=ch, char=ch, state=0)); ui.root.update()
        if ui.page: ui.page = None
        while ui.busy: ui.root.update(); time.sleep(0.05)
    # ---- quick settings panel (Legion R) and Legion buttons
    print("QUICK", flush=True)
    for _ in range(5): ui.root.update(); time.sleep(0.05)
    if ui.quick: step(ui.close_quick); ui.root.update()
    if ui.osk: step(ui.close_keyboard)
    ui.game = {"pid": 1000, "name": "ELDEN RING", "exe": "eldenring.exe", "start": time.time() - 600, "peak": 0.5, "saved": None, "hub": {"id": "steam:1000"}}
    step(ui.legion_action, "legion_r"); ui.root.update(); time.sleep(0.5); ui.root.update()
    assert ui.quick, "panel didn't open"
    for scroll in (0, 700, 1400, 2100, 9999):
        ui.set_off("qp", scroll); step(ui.draw); ui.root.update()
        regs = list(ui.quick.state["regions"])
        for r in regs:
            if not ui.quick: step(ui.open_quick); ui.root.update(); ui.set_off("qp", scroll); step(ui.draw)
            if r["kind"] == "scroll" or r["id"] in ("q_close", "q_hub", "q_tune", "q_kbd", "q_tasks"): continue
            cx, cy = (r["x0"]+r["x1"])/2, (r["y0"]+r["y1"])/2
            print("  qtap", r["id"], flush=True)
            step(ui.quick_event, ui.on_press, E(cx, cy)); step(ui.quick_event, ui.on_release, E(cx, cy)); taps += 1
            ui.root.update()
    if not ui.quick: step(ui.open_quick); ui.root.update()
    for b in ["down"] * 30 + ["left", "right", "up", "up", "a"]:
        step(ui.quick_pad, b); ui.root.update()
    ui.armed = None
    step(ui.quick_event, ui.on_press, E(5, 5))
    step(ui.quick_event, ui.on_release, E(5, 5))
    # end-game needs two taps
    ui.set_off("qp", 9999); step(ui.draw)
    eg = [r for r in ui.quick.state["regions"] if r["id"] == "q_endgame"] if ui.quick else []
    print("  endgame region", bool(eg), flush=True)
    step(ui.quick_pad, "b"); ui.root.update()
    print("  closed by B:", ui.quick is None, flush=True)
    step(ui.legion_action, "legion_r"); ui.root.update(); step(ui.legion_action, "legion_r"); ui.root.update()
    print("  R twice -> closed:", ui.quick is None, flush=True)
    step(ui.legion_action, "legion_r"); ui.root.update(); step(ui.legion_action, "legion_l"); ui.root.update()
    print("  R then L -> panel closed, hub tab:", ui.quick is None, ui.tab, flush=True)
    for ev in ("legion_l_hold", "legion_r_hold"): step(ui.legion_action, ev)
    for a in R.LEGION_ACTION_ORDER:
        if a not in ("hub",): step(ui.do_action, a); ui.root.update()
        if ui.quick: step(ui.close_quick)
    step(ui.quick_game_settings); print("  game settings page:", ui.page, ui.tune_target, flush=True); ui.page = None
    if not ui.legion: ui.cfg["legion_buttons"] = True; ui.start_legion_buttons()
    if ui.legion:
        ui.legion.sent.clear(); step(ui.set_rgb, "pulse", "#ff3b6b", 50); ui.root.update(); time.sleep(0.3); ui.root.update()
        print("  rgb packets:", ui.legion.sent[-1] if ui.legion.sent else None, flush=True)
    step(ui.set_tab, "startup"); ui.ls_time = 0; step(ui.draw); ui.root.update(); time.sleep(0.4); ui.root.update(); step(ui.draw)
    ls = [r for r in ui.active_regions() if r["id"] == "ls_close"]
    for _ in range(2):
        if ls: step(ui.on_press, E((ls[0]["x0"]+ls[0]["x1"])/2, ls[0]["y0"]+5)); step(ui.on_release, E((ls[0]["x0"]+ls[0]["x1"])/2, ls[0]["y0"]+5))
    ui.root.update(); time.sleep(0.3); ui.root.update()
    # slider drag in the quick panel
    step(ui.open_quick); ui.root.update(); ui.set_off("qp", 0); step(ui.draw)
    sl = [r for r in ui.quick.state["regions"] if r["id"] == "q_tdp"]
    if sl:
        r = sl[0]; yy = (r["y0"] + r["y1"]) / 2
        step(ui.quick_event, ui.on_press, E(r["x0"] + 20, yy))
        for xx in range(int(r["x0"]) + 20, int(r["x1"]), 40): step(ui.quick_event, ui.on_motion, E(xx, yy))
        step(ui.quick_event, ui.on_release, E(r["x1"] - 5, yy))
    print("  tdp after drag:", ui.cfg["tdp"], flush=True)
    step(ui.close_quick)
    step(ui.open_checkup); ui.root.update(); time.sleep(0.5); ui.root.update(); step(ui.draw)
    print("  checkup:", ui.checkup_score(ui.checkup_items()), [i[0] for i in ui.checkup_items()], flush=True)
    step(ui.fix_all); ui.root.update(); time.sleep(0.5); ui.root.update()
    ui.page = None
    ui.cfg["welcomed"] = False; step(ui.maybe_welcome); step(ui.finish_welcome); ui.root.update(); time.sleep(0.4); ui.root.update()
    print("  welcomed:", ui.cfg["welcomed"], ui.page, flush=True)
    # discord
    ui.cfg["discord_presence"] = True; step(ui.start_discord)
    ui.game = {"pid": 1000, "name": "ELDEN RING", "exe": "eldenring.exe", "start": time.time() - 900, "peak": 0.55, "saved": None, "hub": None,
               "fps_sum": 5200.0, "fps_n": 100, "batt0": 88}
    ui.fps_stats = (52.3, 40)
    print("  presence:", ui.presence_activity(), flush=True)
    step(ui.presence_tick, True); print("  sent to discord:", ui.discord.acts[-1] if ui.discord.acts else None, flush=True)
    ui.hook_busy = False; step(ui.post_recap, ui.game, 900); ui.root.update(); time.sleep(0.4); ui.root.update()
    step(ui.share_screenshot); ui.root.update(); time.sleep(0.4); ui.root.update()
    for w in ("mute", "deafen"): step(ui.discord_voice, w)
    step(ui.trim_discord); ui.root.update(); time.sleep(0.4); ui.root.update()
    ui.root.clipboard_clear(); ui.root.clipboard_append("https://discord.com/api/webhooks/999/xyz"); step(ui.paste_setting, "discord_webhook")
    ui.root.clipboard_clear(); ui.root.clipboard_append("my id is 1111222233334444555"); step(ui.paste_setting, "discord_app_id")
    print("  pasted:", ui.cfg["discord_webhook"], ui.cfg["discord_app_id"], flush=True)
    step(ui.stop_discord); ui.game = None
    # ---- v6 features
    print("V6", flush=True)
    S.process_alive = lambda pid: True
    ui.game = {"pid": 1000, "name": "ELDEN RING", "exe": "eldenring.exe", "start": time.time() - 900, "peak": 0.5, "saved": None,
               "hub": {"id": "steam:1000"}, "fps_sum": 0.0, "fps_n": 0, "batt0": 80}
    ui.device["legion"] = True; ui.cfg["auto_tdp"] = True; ui.cfg["auto_tdp_target"] = 60; ui.tools = ui.tools or {}; ui.tools["tdp"] = 15
    ui.fps_stats = (48.0, 40); ui.atdp_t = 0; step(ui.auto_tdp_step); ui.root.update(); time.sleep(0.4); ui.root.update()
    print("  auto tdp after low fps:", ui.atdp_w, flush=True)
    ui.fps_stats = (61.0, 55); ui.atdp_t = 0; ui.atdp_up = 0; step(ui.auto_tdp_step); ui.root.update(); time.sleep(0.4); ui.root.update()
    print("  auto tdp after target met:", ui.atdp_w, flush=True)
    ui.cfg["back_map"] = {"y1": "key:Shift", "y3": "act:quick"}; ui.cfg["back_map_game"] = {"steam:1000": {"y1": "key:F5"}}
    for ev in ("back_y1_down", "back_y1_up", "back_y3_down", "back_y3_up"): step(ui.legion_action, ev); ui.root.update()
    print("  quick open from Y3:", bool(ui.quick), flush=True); step(ui.close_quick)
    step(ui.open_back_buttons); step(ui.set_back, "m2", 1); step(ui.set_back, "m2", 1); print("  m2 for game:", ui.cfg["back_map_game"]["steam:1000"].get("m2"), flush=True)
    ui.back_scope = "all"; step(ui.set_back, "y2", -1); ui.page = None
    step(ui.toggle_suspend); print("  suspended:", ui.suspended, flush=True); step(ui.toggle_suspend); print("  resumed:", ui.suspended, flush=True)
    step(ui.save_game_lights, True); print("  game lights:", ui.cfg["game_lights"].get("steam:1000"), flush=True); step(ui.save_game_lights, False)
    g0 = {"id": "steam:1000", "name": "Hades", "source": "Steam"}
    step(ui.save_backup, g0); ui.root.update(); time.sleep(0.4); ui.root.update()
    step(ui.move_game, g0, r"D:\SteamLibrary"); step(ui.move_game, g0, r"D:\SteamLibrary"); ui.root.update(); time.sleep(0.4); ui.root.update()
    step(ui.toggle_keyboard); ui.root.update()
    for b in ["right", "right", "a", "down", "a", "lb", "a", "x", "y", "start", "up", "up", "up", "up", "down", "down", "down", "down", "a"]:
        if ui.osk: step(ui.osk.pad, b)
    print("  keyboard closed by close key:", ui.osk is None, flush=True)
    if ui.osk: step(ui.close_keyboard)
    step(ui.media, "play"); step(ui.check_network); step(ui.toggle_radio, "bluetooth"); ui.radios = {"wifi": True, "bluetooth": False}
    ui.cfg["update_repo"] = "me/vanta"; step(ui.check_updates); ui.root.update(); time.sleep(0.4); ui.root.update()
    print("  update:", ui.update_text(), flush=True)
    step(ui.set_tab, "stats"); step(ui.draw)
    ui.cfg["batt_hist"] = []; ui.batt = {"full_mwh": 46000, "remaining_mwh": 30000, "rate_mw": -12000, "discharging": True}
    ui.batt_static = {"design": 49200, "cycles": 210}; step(ui.record_battery_health); print("  batt hist:", ui.cfg["batt_hist"], flush=True)
    ui.cfg["auto_tdp"] = False; ui.game = None
    # ---- v7 features
    print("V7", flush=True)
    S.process_alive = lambda pid: True
    ui.cfg["legion_buttons"] = True
    if not ui.legion: ui.start_legion_buttons()
    step(ui.set_pointer_mode, "vanta"); step(ui.set_pointer_mode, "mouse"); ui.root.update()
    print("  motion controls stay off:", ui.pointer is None and ui.cfg["pointer_mode"] == "off", flush=True)
    ui.game = {"pid": 1000, "name": "ELDEN RING", "exe": "eldenring.exe", "start": time.time() - 900, "peak": 0.5, "saved": None,
               "hub": {"id": "steam:1000"}, "fps_sum": 0.0, "fps_n": 0, "batt0": 80}
    ui.device["legion"] = True
    step(ui.start_bench); b = ui.bench
    if b:
        for i, w in enumerate(b["steps"]):
            b["results"].append({"w": w, "fps": min(60, 20 + w * 2.2), "low": 30, "watts": w + 3})
        b["i"] = len(b["steps"]) - 1; b["phase"] = "measure"; b["t"] = time.time() - 30; b["samples"] = [(60, 50, 33)]
        b["results"].pop()
        step(ui.bench_tick)
    print("  bench page:", ui.page, "pick:", (ui.bench_pick(ui.cfg["bench_results"]["steam:1000"]["results"]) or {}).get("w"), flush=True)
    step(ui.draw); step(ui.use_bench, "steam:1000", 20, "ELDEN RING"); ui.page = None
    step(ui.set_cpu_max_now, 80); ui.root.update(); time.sleep(0.3); ui.root.update()
    ui.charge_limit = True; ui.power = {"ac": True, "pct": 90, "battery": True, "charging": True}
    step(ui.topup); ui.root.update(); time.sleep(0.3); ui.root.update(); print("  topup:", ui.cfg["topup"], flush=True)
    ui.power = {"ac": True, "pct": 100, "battery": True, "charging": False}; step(ui.check_topup); ui.root.update(); time.sleep(0.3); ui.root.update()
    print("  topup after full:", ui.cfg["topup"], flush=True)
    ui.last_sample = (time.time() - 5 * 3600, 80, False)
    R.power_status = lambda: {"ac": False, "pct": 74, "battery": True, "charging": False}
    step(ui.track_sleep, time.time()); ui.root.update(); time.sleep(0.4); ui.root.update()
    print("  sleep log:", ui.cfg["sleep_log"][-1]["from"], "->", ui.cfg["sleep_log"][-1]["to"], ui.cfg["sleep_log"][-1]["woke"], flush=True)
    ui.cfg["game_quiet"] = True; step(ui.quiet_on, ui.game); ui.root.update(); time.sleep(0.4); ui.root.update()
    print("  quiet pending:", ui.cfg["quiet_pending"], flush=True); step(ui.quiet_off); ui.root.update(); time.sleep(0.3)
    ui.cfg["steam_key"] = "0" * 32; step(ui.achievements_for, {"id": "steam:1000", "source": "Steam", "name": "x"}); ui.root.update(); time.sleep(0.4); ui.root.update()
    print("  achievements:", ui.achievements_for({"id": "steam:1000", "source": "Steam", "name": "x"}), flush=True)
    step(ui.search_library)
    for b_ in ["right", "a", "a"]:
        if ui.osk: step(ui.osk.pad, b_)
    print("  search query:", repr(ui.lib_query), flush=True); step(ui.close_keyboard); ui.lib_query = ""
    step(ui.open_lists, {"id": "steam:1000", "name": "Balatro", "source": "Steam"}); step(ui.new_list)
    for b_ in ["a", "start"]:
        if ui.osk: step(ui.osk.pad, b_)
    print("  lists:", ui.cfg["lists"], flush=True); ui.page = None
    step(ui.open_editor); step(ui.edit_color, "accent", 0.9, 0.5, 0.9); print("  theme:", ui.cfg["theme"], R.THEMES["My theme"]["accent"], flush=True)
    ui.page = None
    ui.cfg["sync_on"] = True; step(ui.sync_tick, True); ui.root.update(); time.sleep(0.6); ui.root.update()
    print("  sync:", ui.sync_status, os.listdir(_sync_dir), flush=True)
    step(ui.clear_shaders, "1000", "X"); step(ui.clear_shaders, "1000", "X"); ui.root.update(); time.sleep(0.3); ui.root.update()
    for a in ("profile_max", "tdp_up", "boost", "play", "suspend"):
        print("  remote", a, "->", ui.remote_action(a), flush=True)
    ui.root.update()
    ui.game = None; ui.cfg["sync_on"] = False; ui.cfg["game_quiet"] = False
    print("  ls log:", [m for _, t, m in list(ui.log)[-2:]], flush=True)
    print(f"AUTOTEST taps={taps} errors={len(errors)}")
    for e in errors[:5]: print(e)
    print("LOG:", [m for _, t, m in list(ui.log)[-6:]])
    ui.root.after(10, ui.root.destroy)
ui.root.after(1500, run_all)
ui.root.mainloop()
