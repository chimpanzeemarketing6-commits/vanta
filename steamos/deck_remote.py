"""Vanta Deck phone app: a small web page on your home network, opened from your phone's browser.

Every request except the page itself needs the PIN shown on the Deck. Nothing is sent anywhere else."""
import hmac
import json
import mimetypes
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8787

PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0d14"><title>Vanta Deck</title><style>
:root{--bg:#0b0d14;--p:#141826;--p2:#1c2133;--t:#eef1f8;--m:#8d96ad;--a:#5b8cff;--g:#3ddc97;--w:#ffb84d;--d:#ff5c6c}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}body{margin:0;font:15px/1.4 system-ui,sans-serif;background:var(--bg);color:var(--t)}
header{display:flex;align-items:center;gap:10px;padding:16px 18px 8px}header b{font-size:18px;letter-spacing:.04em}
.logo{width:32px;height:32px;border-radius:9px;background:var(--a);display:grid;place-items:center;font-weight:800;color:#fff}
nav{display:flex;gap:8px;padding:6px 18px 12px;position:sticky;top:0;background:var(--bg);z-index:2}
nav button{flex:1;border:0;border-radius:20px;padding:10px;background:var(--p2);color:var(--t);font-weight:700}
nav button.on{background:var(--a);color:#fff}main{padding:0 18px 40px}
.card{background:var(--p);border-radius:18px;padding:16px;margin-bottom:12px}.lab{color:var(--m);font-size:12px;font-weight:700;letter-spacing:.08em}
.big{font-size:30px;font-weight:800}.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}.muted{color:var(--m)}
.btn{display:block;width:100%;border:0;border-radius:14px;padding:14px;font-weight:800;font-size:15px;background:var(--a);color:#fff;margin-top:10px}
.btn.alt{background:var(--p2);color:var(--t)}.bar{height:8px;border-radius:4px;background:var(--p2);margin-top:8px;overflow:hidden}.bar i{display:block;height:100%;background:var(--a)}
.games{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.games div{position:relative}.games img,.ph{width:100%;aspect-ratio:2/3;border-radius:12px;object-fit:cover;background:var(--p2);display:block}
.ph{display:grid;place-items:center;padding:6px;text-align:center;font-size:12px;font-weight:700}.games span{display:block;font-size:12px;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.shots{display:grid;grid-template-columns:1fr 1fr;gap:8px}.shots img{width:100%;border-radius:10px;display:block}
#pin{display:none;padding:40px 18px;text-align:center}#pin input{font-size:28px;text-align:center;width:180px;padding:12px;border-radius:14px;border:0;background:var(--p2);color:var(--t);letter-spacing:.3em}
#toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--p2);padding:12px 18px;border-radius:14px;font-weight:700;display:none}
</style></head><body>
<header><div class="logo">V</div><b>VANTA DECK</b><span class="muted" id="sub" style="margin-left:auto"></span></header>
<div id="pin"><p>Type the PIN shown on your Deck<br><span class="muted">Vanta Deck › Tools › Phone app</span></p><input id="pinin" inputmode="numeric" maxlength="6"><br><button class="btn" style="width:180px;margin:16px auto" onclick="savePin()">Connect</button></div>
<div id="app" style="display:none"><nav><button data-t="now" class="on">Now</button><button data-t="games">Games</button><button data-t="shots">Shots</button></nav><main id="main"></main></div>
<div id="toast"></div>
<script>
const qp=new URLSearchParams(location.search).get('pin');if(qp){localStorage.setItem('vdpin',qp);history.replaceState(null,'','/')}
let pin=localStorage.getItem('vdpin')||'',tab='now',st=null,timer=null;
const $=s=>document.querySelector(s);
function toast(t){const e=$('#toast');e.textContent=t;e.style.display='block';clearTimeout(e._t);e._t=setTimeout(()=>e.style.display='none',2600)}
async function api(p,body){const r=await fetch(p,{method:body?'POST':'GET',headers:{'X-Vanta-Pin':pin,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
 if(r.status==403){showPin();throw 'pin'}return r.json()}
function showPin(){$('#pin').style.display='block';$('#app').style.display='none'}
function savePin(){pin=$('#pinin').value.trim();localStorage.setItem('vdpin',pin);start()}
function img(id){return '/api/cover?id='+encodeURIComponent(id)+'&pin='+encodeURIComponent(pin)}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
async function act(a,v){try{const r=await api('/api/action',{a,v});toast(r.msg||'Done');refresh()}catch(e){}}
function now(){const s=st,b=s.batt||{};let h='';
 h+=`<div class="card"><div class="lab">${s.game?'PLAYING':'NOT PLAYING'}</div><div class="big">${esc(s.game||'Nothing running')}</div>${s.game?`<div class="muted">for ${esc(s.game_for)}</div>`:''}</div>`;
 h+=`<div class="row"><div class="card"><div class="lab">BATTERY</div><div class="big">${b.pct??'–'}%</div><div class="muted">${esc(b.text||'')}</div></div>`;
 h+=`<div class="card"><div class="lab">TODAY</div><div class="big">${esc(s.today)}</div><div class="muted">streak ${s.streak} days</div></div></div>`;
 h+=`<div class="row"><div class="card"><div class="lab">CPU</div><div class="big">${s.cpu??'–'}%</div><div class="muted">${esc(s.cpu_temp||'')}</div></div><div class="card"><div class="lab">GPU</div><div class="big">${s.gpu??'–'}%</div><div class="muted">${esc(s.gpu_temp||'')}</div></div></div>`;
 h+=`<div class="card"><div class="lab">MEMORY</div><div class="big">${esc(s.ram_text)}</div><div class="bar"><i style="width:${s.ram_pct}%"></i></div>
   <button class="btn" onclick="act('boost')">Game Boost now</button><div class="muted" style="margin-top:8px">${esc(s.boost_text)}</div></div>`;
 if(s.goal)h+=`<div class="card"><div class="lab">BATTERY GOAL</div><div style="font-weight:700">${esc(s.goal)}</div></div>`;
 return h}
function games(){return '<div class="games">'+st.games.map(g=>`<div onclick="if(confirm('Play ${esc(g.name).replace(/'/g,'')} on the Deck?'))act('play','${g.id}')">${g.cover?`<img loading="lazy" src="${img(g.id)}">`:`<div class="ph">${esc(g.name)}</div>`}<span>${esc(g.name)}</span></div>`).join('')+'</div>'}
async function shots(){const r=await api('/api/shots');if(!r.length)return '<div class="card muted">No screenshots yet</div>';
 return '<div class="shots">'+r.map(x=>`<a href="/api/shot?i=${x.i}&pin=${encodeURIComponent(pin)}" target="_blank"><img loading="lazy" src="/api/shot?i=${x.i}&thumb=1&pin=${encodeURIComponent(pin)}"></a>`).join('')+'</div>'}
async function render(){if(!st)return;$('#sub').textContent=st.clock;if(tab=='now')$('#main').innerHTML=now();else if(tab=='games')$('#main').innerHTML=games();else $('#main').innerHTML=await shots()}
async function refresh(){try{st=await api('/api/state');if(tab!='shots'||!$('#main').innerHTML)render();else $('#sub').textContent=st.clock}catch(e){}}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{tab=b.dataset.t;document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('on',x==b));render()});
async function start(){try{st=await api('/api/state');$('#pin').style.display='none';$('#app').style.display='block';render();clearInterval(timer);timer=setInterval(refresh,3000)}catch(e){}}
if(pin)start();else showPin();
</script></body></html>"""


class Remote:
    """provider must have: pin (str), state() -> dict, action(a, v) -> str, cover(id) -> path, shots() -> [paths]."""

    def __init__(self, provider, port=PORT):
        self.p = provider
        prov = provider

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def ok_pin(self, q):
                given = self.headers.get("X-Vanta-Pin") or (q.get("pin") or [""])[0]
                return bool(prov.pin) and hmac.compare_digest(given.encode(), prov.pin.encode())

            def send(self, code, body, ctype="application/json"):
                if isinstance(body, (dict, list)):
                    body = json.dumps(body).encode()
                elif isinstance(body, str):
                    body = body.encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def send_file(self, path):
                try:
                    with open(path, "rb") as f:
                        data = f.read()
                except OSError:
                    return self.send(404, {"error": "missing"})
                self.send(200, data, mimetypes.guess_type(path)[0] or "application/octet-stream")

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(u.query)
                if u.path in ("/", "/index.html"):
                    return self.send(200, PAGE, "text/html; charset=utf-8")
                if not self.ok_pin(q):
                    return self.send(403, {"error": "pin"})
                if u.path == "/api/state":
                    return self.send(200, prov.state())
                if u.path == "/api/cover":
                    p = prov.cover((q.get("id") or [""])[0])
                    return self.send_file(p) if p else self.send(404, {"error": "none"})
                if u.path == "/api/shots":
                    return self.send(200, [{"i": i} for i in range(len(prov.shots()))][:60])
                if u.path == "/api/shot":
                    sh = prov.shots()
                    try:
                        it = sh[int((q.get("i") or ["-1"])[0])]
                    except (ValueError, IndexError):
                        return self.send(404, {"error": "none"})
                    return self.send_file(it["thumb"] if q.get("thumb") else it["path"])
                self.send(404, {"error": "unknown"})

            def do_POST(self):
                u = urllib.parse.urlparse(self.path)
                if not self.ok_pin(urllib.parse.parse_qs(u.query)):
                    return self.send(403, {"error": "pin"})
                try:
                    n = min(int(self.headers.get("Content-Length") or 0), 4096)
                    body = json.loads(self.rfile.read(n) or b"{}")
                except (ValueError, OSError):
                    return self.send(400, {"error": "bad"})
                if u.path == "/api/action":
                    return self.send(200, {"msg": prov.action(str(body.get("a", "")), body.get("v"))})
                self.send(404, {"error": "unknown"})

        self.httpd = ThreadingHTTPServer(("0.0.0.0", port), H)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass
