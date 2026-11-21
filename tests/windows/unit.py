import sys, os, io, time, types, collections
sys.path.insert(0, r"Z:\home\claude\app")
import systools as S
# FPS parser with PresentMon 2.x-style output
r = S.FpsReader.__new__(S.FpsReader)
r.frames = collections.deque(maxlen=4000); r.error = None
hdr = "Application,ProcessID,SwapChainAddress,PresentRuntime,SyncInterval,PresentFlags,AllowsTearing,PresentMode,FrameType,CPUStartTime,FrameTime,CPUBusy,CPUWait"
rows = [f"game.exe,1000,0x1,DXGI,0,0,1,Hardware: Independent Flip,Application,{i*16.6:.3f},{16.6 if i % 50 else 33.3},10,6" for i in range(80)]
r.proc = types.SimpleNamespace(stdout=iter([hdr + "\n"] + [x + "\n" for x in rows]), stderr=io.StringIO(""))
r._read(); print("FPS v2:", [round(v, 1) for v in r.stats()])
r.frames.clear(); r.proc = types.SimpleNamespace(stdout=iter(["Application,ProcessID,MsBetweenPresents\n", "g,1,8.33\n"] * 3), stderr=io.StringIO(""))
r._read(); print("FPS v1:", [round(v, 1) if v else v for v in r.stats()])
r.frames.clear(); r.proc = types.SimpleNamespace(stdout=iter([]), stderr=io.StringIO("error: access denied\n")); r._read(); print("error:", r.error)
# duplicates
dl = S.known_folder("374de290-123f-4565-9164-39c4925e467b"); print("Downloads:", dl)
os.makedirs(os.path.join(dl, "sub"), exist_ok=True)
blob = os.urandom(1024 * 1024) * 21
for p in (os.path.join(dl, "a.bin"), os.path.join(dl, "sub", "a_copy.bin")):
    open(p, "wb").write(blob)
open(os.path.join(dl, "same_size_diff.bin"), "wb").write(blob[:-1] + b"X")
g = S.find_duplicates(); print("dupe groups:", [(sz, [os.path.basename(f) for f, _ in fs]) for sz, fs in g])
print("big files:", [(os.path.basename(f), sz) for f, sz, _, _ in S.big_files(min_size=20 * 1048576)])
print("recycle:", S.recycle(os.path.join(dl, "sub", "a_copy.bin")), os.path.exists(os.path.join(dl, "sub", "a_copy.bin")))
for p in (os.path.join(dl, "a.bin"), os.path.join(dl, "same_size_diff.bin")):
    os.remove(p)
try:
    print("gpu meter:", S.GpuMeter().read())
except Exception as e:
    print("gpu meter unavailable here:", e)
