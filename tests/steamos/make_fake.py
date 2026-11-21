"""Build a fake SteamOS home (Steam library, shortcuts, art) and a fake /sys + /proc for Vanta Deck tests."""
import os, struct, shutil, time, random
from PIL import Image, ImageDraw
H = "/tmp/deckhome"; S = "/tmp/fakesys"
shutil.rmtree(H, ignore_errors=True); shutil.rmtree(S, ignore_errors=True)
steam = f"{H}/.local/share/Steam"; sd = f"{H}/sdcard/SteamLibrary"
games = [(1245620, "ELDEN RING", 60e9, steam, 7, 3110), (1145360, "Hades", 15e9, steam, 1, 1520), (1091500, "Cyberpunk 2077", 70e9, sd, 20, 900),
         (413150, "Stardew Valley", 0.6e9, steam, 3, 4200), (2379780, "Balatro", 0.2e9, steam, 0.2, 2210), (367520, "Hollow Knight", 9e9, sd, 40, 1730),
         (1086940, "Baldur's Gate 3", 150e9, sd, 2.5, 6100), (1145350, "Hades II", 12e9, steam, None, 0), (1493710, "Proton Experimental", 1e9, steam, None, 0),
         (504230, "Celeste", 1.2e9, steam, 90, 640), (1794680, "Vampire Survivors", 0.5e9, steam, 12, 1300)]
os.makedirs(f"{steam}/steamapps", exist_ok=True); os.makedirs(f"{sd}/steamapps", exist_ok=True)
open(f"{steam}/steamapps/libraryfolders.vdf", "w").write(f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{steam}"\n\t}}\n\t"1"\n\t{{\n\t\t"path"\t\t"{sd}"\n\t}}\n}}\n')
apps = []
for appid, name, size, lib, days, mins in games:
    open(f"{lib}/steamapps/appmanifest_{appid}.acf", "w").write(f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n\t"StateFlags"\t\t"4"\n\t"installdir"\t\t"{name}"\n\t"SizeOnDisk"\t\t"{int(size)}"\n}}\n')
    if days is not None:
        apps.append(f'\t\t\t\t\t"{appid}"\n\t\t\t\t\t{{\n\t\t\t\t\t\t"LastPlayed"\t\t"{int(time.time() - days * 86400)}"\n\t\t\t\t\t\t"Playtime"\t\t"{mins}"\n\t\t\t\t\t}}\n')
ud = f"{steam}/userdata/123456/config"; os.makedirs(ud + "/grid", exist_ok=True)
open(f"{ud}/localconfig.vdf", "w").write('"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"apps"\n\t\t\t\t{\n' + "".join(apps) + '\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n')
def bstr(k, v): return b"\x01" + k.encode() + b"\x00" + v.encode() + b"\x00"
def bint(k, v): return b"\x02" + k.encode() + b"\x00" + struct.pack("<I", v & 0xFFFFFFFF)
sc = b"\x00shortcuts\x00"
for i, (aid, name) in enumerate(((3123456789, "RetroArch"), (2987654321, "Heroic: Alan Wake 2"))):
    sc += b"\x00" + str(i).encode() + b"\x00" + bint("appid", aid) + bstr("AppName", name) + bstr("Exe", "/usr/bin/x") + bint("LastPlayTime", int(time.time() - 86400 * (i + 3))) + b"\x08"
sc += b"\x08\x08"
open(f"{ud}/shortcuts.vdf", "wb").write(sc)
def art(path, w, h, text, hue):
    import colorsys
    r, g, b = colorsys.hls_to_rgb(hue, 0.45, 0.6)
    im = Image.new("RGB", (w, h), (int(r * 255), int(g * 255), int(b * 255)))
    d = ImageDraw.Draw(im)
    for j in range(10):
        x_, y_ = random.randint(0, w), random.randint(0, h); d.ellipse((x_, y_, x_ + 90, y_ + 90), outline=(255, 255, 255), width=3)
    d.text((20, h - 60), text, fill=(255, 255, 255))
    os.makedirs(os.path.dirname(path), exist_ok=True); im.save(path, quality=85)
lc = f"{steam}/appcache/librarycache"
for i, (appid, name, *_r) in enumerate(games):
    if i % 3 == 0: art(f"{lc}/{appid}_library_600x900.jpg", 600, 900, name, i / 11)
    elif i % 3 == 1: art(f"{lc}/{appid}/library_600x900.jpg", 600, 900, name, i / 11)
    if i % 2 == 0: art(f"{lc}/{appid}/abc123/library_hero.jpg", 1920, 620, name, i / 11)
art(f"{ud}/grid/3123456789p.png", 600, 900, "RetroArch", 0.8)
for lib, aid, mb in ((steam, 1245620, 300), (steam, 1145360, 90), (steam, 220, 40), (sd, 292030, 900), (sd, 1091500, 400)):
    for sub in ("shadercache", "compatdata"):
        d = f"{lib}/steamapps/{sub}/{aid}"; os.makedirs(d, exist_ok=True)
        with open(f"{d}/blob.bin", "wb") as f: f.truncate(int(mb * 1024 * 1024 * (0.4 if sub == "compatdata" else 1)))
# fake sysfs/procfs
b = f"{S}/sys/class/power_supply/BAT1"; os.makedirs(b)
for k_, v in {"type": "Battery", "capacity": "64", "status": "Discharging", "power_now": "13800000", "energy_now": "25600000",
              "energy_full": "36500000", "energy_full_design": "40040000", "cycle_count": "182"}.items(): open(f"{b}/{k_}", "w").write(v)
for n, (name, files) in enumerate((("jupiter", {"fan1_input": "2950"}), ("k10temp", {"temp1_input": "71250"}),
                                   ("amdgpu", {"temp1_input": "66000", "power1_average": "9800000"}))):
    d = f"{S}/sys/class/hwmon/hwmon{n}"; os.makedirs(d)
    open(f"{d}/name", "w").write(name)
    for k_, v in files.items(): open(f"{d}/{k_}", "w").write(v)
os.makedirs(f"{S}/sys/class/drm/card0/device"); open(f"{S}/sys/class/drm/card0/device/gpu_busy_percent", "w").write("78")
os.makedirs(f"{S}/proc/4242")
open(f"{S}/proc/4242/cmdline", "wb").write(b"/home/deck/.local/share/Steam/ubuntu12_32/reaper\x00SteamLaunch\x00AppId=1145360\x00--\x00hades")
open(f"{S}/proc/stat", "w").write("cpu  1000 0 500 8000 100 0 0 0 0 0\n")
open(f"{S}/proc/meminfo", "w").write("MemTotal:       16000000 kB\nMemAvailable:    9100000 kB\n")
open(f"{S}/proc/uptime", "w").write("15234.2 50000.1")
print("fake ready")
