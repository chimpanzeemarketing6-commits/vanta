import os, sys, io, traceback
out = []
LOG = os.path.join(os.path.dirname(sys.executable), "selftest.txt")
open(LOG, "w").write("started")
def check(name, fn):
    try:
        r = fn(); out.append(f"OK   {name} {r if r is not None else ''}")
    except Exception as ex:
        out.append(f"FAIL {name}: {type(ex).__name__}: {ex}")
    open(LOG, "w").write("\n".join(out))
import systools
out.append("imported systools"); open(LOG, "w").write("\n".join(out))
import vanta
out.append("imported vanta"); open(LOG, "w").write("\n".join(out))
for _m in ("PIL.Image", "PIL.ImageOps", "PIL.ImageFilter", "PIL.ImageEnhance", "PIL.ImageDraw", "PIL.ImageTk"):
    out.append("importing " + _m); open(LOG, "w").write("\n".join(out))
    __import__(_m)
from PIL import Image, ImageTk, ImageOps, ImageFilter, ImageEnhance, ImageDraw
out.append("PIL imported"); open(LOG, "w").write("\n".join(out))
def img_roundtrip(fmt):
    im = Image.new("RGB", (64, 96), (200, 30, 90)); b = io.BytesIO(); im.save(b, fmt); b.seek(0)
    return Image.open(b).convert("RGBA").size
check("jpeg", lambda: img_roundtrip("JPEG"))
check("png", lambda: img_roundtrip("PNG"))
check("webp", lambda: img_roundtrip("WEBP"))
check("affine gradient", lambda: Image.new("RGB", (64, 1), (9, 9, 9)).transform((40, 30), Image.AFFINE, (0.5, 0.3, 2, 0, 0, 0), resample=Image.BILINEAR).size)
check("alpha sprite", lambda: (lambda m: (Image.new("RGBA", (32, 32), (255, 0, 0, 0)).putalpha(m), m.size)[1])(Image.new("L", (32, 32), 90).filter(ImageFilter.GaussianBlur(3))))
check("truetype font", lambda: __import__("systools")._font(40, True).getbbox("Vanta"))
check("share card", lambda: os.path.getsize(__import__("systools").share_card(os.path.join(os.path.dirname(sys.executable), "share.png"), "November", "27h", [("1. Elden Ring", "11h")])))
check("sqlite3", lambda: __import__("sqlite3").connect(":memory:").execute("select 1").fetchone())
check("hmac pin", lambda: __import__("hmac").compare_digest("123456", "123456"))
check("draw", lambda: (ImageDraw.Draw(Image.new("RGB", (10, 10))).rectangle((1, 1, 5, 5), fill="red"), "ok")[1])
check("filters", lambda: ImageEnhance.Brightness(ImageOps.fit(Image.new("RGB", (50, 50)), (20, 30)).filter(ImageFilter.GaussianBlur(2))).enhance(0.5).size)
import tkinter as tk
r = tk.Tk(); r.withdraw()
check("tk photo", lambda: ImageTk.PhotoImage(Image.new("RGBA", (20, 20)), master=r).width())
check("tk font", lambda: tk.font.Font(root=r, family="Segoe UI", size=12).measure("Vanta") if hasattr(tk, "font") else __import__("tkinter.font").font.Font(root=r, size=12).measure("Vanta"))
check("tk encoding", lambda: r.tk.call("encoding", "system"))
check("https", lambda: len(systools._get_json("https://store.steampowered.com/api/appdetails?appids=1091500&filters=basic")))
check("pystray", lambda: __import__("pystray._win32").__name__)
check("hid", lambda: __import__("hid").__name__)
check("zipfile", lambda: __import__("zipfile").ZIP_DEFLATED)
check("urllib", lambda: __import__("urllib.request").__name__)
check("escape", lambda: vanta.escape("a<b&c"))
check("light", lambda: (systools.set_self_efficiency(True), systools.trim_self(), systools.self_memory_mb(), systools.set_self_efficiency(False)))
check("theme code", lambda: systools.theme_from_code(systools.theme_to_code({"theme": "Neon"})))
import tempfile
systools.BACKUP_DIR = tempfile.mkdtemp()
check("backup", lambda: systools.read_backup(systools.make_backup({"a": 1, "sgdb_key": "x"})))
check("hdr state", lambda: systools.hdr_state())
def _dc():
    d = systools.DesktopControls(); d.start("wasd"); import time as _t; _t.sleep(0.3); alive = d.thread.is_alive(); d.end(); return alive
check("padmouse thread", _dc)
check("captures", lambda: len(systools.list_captures()))
check("lang", lambda: (vanta.LANG.update(code="ja"), vanta.tr("Settings"))[1].encode("unicode_escape"))
r.destroy()
open(os.path.join(os.path.dirname(sys.executable), "selftest.txt"), "w").write("\n".join(out))
