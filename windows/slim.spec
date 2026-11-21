# Vanta build spec: one file, without the parts Vanta never uses (smaller exe, faster start).
import os
NAME = os.environ.get("VANTA_NAME", "Vanta")
ENTRY = os.environ.get("VANTA_ENTRY", "vanta.py")
ADMIN = os.environ.get("VANTA_ADMIN", "1") == "1"
VERSION_FILE = os.environ.get("VANTA_VERSION_FILE", "version.txt")

EXCLUDES = [
    # Pillow pieces Vanta doesn't use: AVIF/HEIF decoding, colour management, Qt (FreeType text is kept for share images)
    "PIL.AvifImagePlugin", "PIL._avif", "PIL.ImageCms", "PIL._imagingcms",
    "PIL.ImageQt", "PIL.ImageShow", "PIL.FpxImagePlugin", "PIL.MicImagePlugin",
    # standard library Vanta doesn't need
    "xml", "pyexpat", "_elementtree", "lzma", "_lzma", "bz2", "_bz2", "pydoc", "doctest", "unittest", "pdb",
    "tkinter.test", "lib2to3", "distutils", "setuptools", "pip", "ftplib", "argparse", "csv", "difflib",
]
HIDDEN = ["pystray._win32", "PIL.ImageTk", "PIL.ImageOps", "PIL.ImageFilter", "PIL.ImageEnhance", "PIL.ImageDraw", "PIL.ImageFont", "sqlite3", "hid"]
if ENTRY != "vanta.py":
    HIDDEN.append("vanta")

# Tcl/Tk data Vanta never touches: time zones, translated messages, demos, sample images and the larger
# legacy CJK encodings (the Windows code pages, cp932/936/949/950 included, stay).
KEEP_ENC_PREFIX = ("cp", "ascii", "iso8859", "utf", "unicode", "identity", "koi8")
def keep_data(dest):
    d = dest.replace("\\", "/")
    for junk in ("/tzdata/", "/msgs/", "/demos/", "/images/", "/http1.0/", "/opt0.4/", "/dde1.4/", "/reg1.3/"):
        if junk in "/" + d + "/" or d.endswith(junk.rstrip("/")):
            return False
    if "/encoding/" in d:
        return os.path.basename(d).startswith(KEEP_ENC_PREFIX)
    return True

a = Analysis([ENTRY], pathex=["."], binaries=[], datas=[("vanta.ico", ".")], hiddenimports=HIDDEN,
             hookspath=[], runtime_hooks=[], excludes=EXCLUDES, noarchive=False, optimize=1)
a.datas = [d for d in a.datas if keep_data(d[0])]
a.binaries = [b for b in a.binaries if not any(x in b[0] for x in ("_avif", "_imagingcms", "_lzma", "_bz2", "pyexpat", "_elementtree"))]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=NAME, icon="vanta.ico", version=VERSION_FILE,
          console=False, uac_admin=ADMIN, upx=False, runtime_tmpdir=None, debug=False, strip=False)
