VERSION = "v1.0.1"
import os, json, html, math, time, hashlib, threading, urllib.request, urllib.parse
_retry_timer = None
_sweep_lock = threading.Lock()
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie

DEFAULT_JF_URL = os.environ.get("JELLYFIN_URL", "http://localhost:8096")
AUTH_USER = os.environ.get("AUTH_USER", "admin")
DEFAULT_AUTH_PASS = os.environ.get("AUTH_PASS", "changeme")
DATA_FILE = "/app/blacklist.json"
CONFIG_FILE = "/app/config.json"
import base64
PER_PAGE = 5
FAVICON_PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAACXBIWXMAAAsTAAALEwEAmpwYAAAAZElEQVRYhe2WQQ6AIAwE9//0XryIJl7ER09g0W1DSoq4yWQmQ5o+t1MA0AB0gAtQAZ4AdwD+g+B2gBvQAE5ABTgD7gB8B8HtADegAZyACnAG3AH4DoLbAW5AAzgBFeAMuANwAL6fNBy+o4R9AAAAAElFTkSuQmCC')

def load_cfg():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d
        except Exception:
            pass
    return {}

def save_cfg(updates):
    cfg = load_cfg()
    cfg.update(updates)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def get_api_key():
    return load_cfg().get("api_key", "").strip()

def get_jf_url():
    return (load_cfg().get("jellyfin_url") or DEFAULT_JF_URL).strip().rstrip("/")

def get_auth_pass():
    return (load_cfg().get("auth_pass") or DEFAULT_AUTH_PASS).strip()

def get_session_token():
    return hashlib.sha256(f"{AUTH_USER}:{get_auth_pass()}:cb_salt".encode()).hexdigest()

def get_needs_clean():
    cfg = load_cfg()
    if "needs_clean" in cfg:
        return bool(cfg["needs_clean"])
    return not os.path.exists(CONFIG_FILE)

def load_list():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump([], f)
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_list(items):
    with open(DATA_FILE, "w") as f:
        json.dump(sorted(list(set(items))), f, indent=2)

def api(path, method="GET", data=None):
    key = get_api_key()
    if not key:
        raise RuntimeError("Missing API key")
    headers = {
        "Authorization": f'MediaBrowser Client="CollectionBlockarr", Device="NAS", DeviceId="cb1", Version="1.0", Token="{key}"',
        "Content-Type": "application/json"
    }
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(f"{get_jf_url()}{path}", data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else None

VER_FILE = "/app/jf_version.txt"

def get_jf_versions(lock_if_ok=False):
    live = ""
    try:
        live = ((api("/System/Info/Public") or {}).get("Version", "")).strip()
    except Exception:
        pass
    stored = ""
    if os.path.exists(VER_FILE):
        try:
            with open(VER_FILE, "r") as f:
                stored = f.read().strip()
        except Exception:
            pass
    if not stored and live:
        stored = live
        with open(VER_FILE, "w") as f:
            f.write(stored)
    elif lock_if_ok and live:
        stored = live
        with open(VER_FILE, "w") as f:
            f.write(stored)
    return stored or "Unknown", live

def get_existing_collections():
    try:
        bl = set(load_list())
        return sorted([b["Name"] for b in api("/Items?IncludeItemTypes=BoxSet&Recursive=true").get("Items", []) if b["Name"] not in bl])
    except Exception:
        return []

BACKUP_DIR=os.path.join(os.path.dirname(DATA_FILE),"backups")
def _snap_path(n):
 os.makedirs(BACKUP_DIR,exist_ok=True)
 return os.path.join(BACKUP_DIR,("".join(c if c.isalnum() or c in " _-()" else "_" for c in n).strip() or "col")+".json")
def restore_collection(n):
 sp=_snap_path(n)
 if not os.path.exists(sp):return
 try:
  sn=json.load(open(sp));uid=next(u["Id"] for u in api("/Users") if u.get("Policy",{}).get("IsAdministrator"));ids=sn.get("ids",[]);tm=sn.get("tmdb_id","")
  for cid in (ids if tm else []):
   try:it=api(f"/Users/{uid}/Items/{cid}");pd=it.get("ProviderIds",{});pd["TmdbCollection"]=tm;it["ProviderIds"]=pd;api(f"/Items/{cid}",method="POST",data=it)
   except Exception:pass
  if ids:api("/Collections?"+urllib.parse.urlencode({"Name":sn.get("name",n),"Ids":",".join(ids)}),method="POST")
  os.remove(sp);print(f"Restored: {n}",flush=True)
 except Exception as e:print(f"Restore error: {e}",flush=True)
def clean_collections():
 if not _sweep_lock.acquire(blocking=False): return
 try:
  bl=load_list()
  if not bl: return
  uid=next(u["Id"] for u in api("/Users") if u.get("Policy",{}).get("IsAdministrator"))
  for box in api("/Items?IncludeItemTypes=BoxSet&Recursive=true").get("Items",[]):
   if box["Name"] in bl:
    bid=box["Id"];cids=[];tm=""
    for ch in api(f"/Users/{uid}/Items?ParentId={bid}").get("Items",[]):
     cid=ch["Id"];cids.append(cid);it=api(f"/Users/{uid}/Items/{cid}");pd=it.get("ProviderIds",{})
     if "TmdbCollection" in pd:
      if not tm:tm=pd["TmdbCollection"]
      del pd["TmdbCollection"]
     it["ProviderIds"]=pd;api(f"/Items/{cid}",method="POST",data=it)
    if cids and not os.path.exists(_snap_path(box["Name"])):json.dump({"name":box["Name"],"ids":cids,"tmdb_id":tm},open(_snap_path(box["Name"]),"w"),indent=2)
    api(f"/Items/{bid}",method="DELETE");print(f"Deleted: {box['Name']}",flush=True)
 except Exception as e:print(f"Cleanup error: {e}",flush=True)
 finally:
  _sweep_lock.release()

def schedule_retest():
    global _retry_timer
    if _retry_timer and _retry_timer.is_alive():
        return
    def _recheck():
        r = run_health_checks(full=True, from_retry=True)
        ok = all(v is not False for v in r.values())
        save_cfg({"retry_state": "passed" if ok else "failed"})
    _retry_timer = threading.Timer(300, _recheck)
    _retry_timer.daemon = True
    _retry_timer.start()

def run_health_checks(full=False, from_retry=False):
    res = {"auth": bool(AUTH_USER and get_auth_pass()), "api": False, "clean": None, "webhook": None, "storage": False}
    try:
        load_list()
        res["storage"] = True
    except Exception:
        pass
    try:
        uid = next(u["Id"] for u in api("/Users") if u.get("Policy", {}).get("IsAdministrator"))
        res["api"] = True
    except Exception:
        uid = None
    if full and res["api"] and uid:
        try:
            api("/Items?IncludeItemTypes=BoxSet&Recursive=true")
            res["clean"] = True
        except Exception:
            res["clean"] = False
        try:
            wh_url = "http://" + "127.0.0.1" + ":8099/webhook"
            req = urllib.request.Request(wh_url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=3) as r:
                res["webhook"] = (r.status == 200)
        except Exception:
            res["webhook"] = False
    if full:
        ok = all(v is not False for v in res.values())
        st = load_cfg().get("retry_state", "")
        if ok:
            if st in ("waiting", "failed"):
                save_cfg({"retry_state": "passed" if from_retry else ""})
        else:
            if not from_retry:
                if st != "failed":
                    save_cfg({"retry_state": "waiting"})
                schedule_retest()
    return res

LOGIN_CSS = '*{box-sizing:border-box;margin:0;padding:0}body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#101010;color:#f0f0f0;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;padding:16px}.login-box{background:#1c1c1c;border:1px solid #2a2a2a;border-radius:10px;padding:32px 26px;width:100%;max-width:380px}h1{color:#00a4dc;font-size:1.8rem;font-weight:700;text-align:center;margin-bottom:24px}input{width:100%;padding:11px 14px;border-radius:6px;border:1px solid #333;background:#141414;color:#d0d0d0;font-size:.9rem;margin-bottom:14px;outline:none}input:focus{border-color:#00a4dc}button{width:100%;padding:12px;border:none;border-radius:6px;background:#0095d5;color:#fff;font-size:1rem;font-weight:600;cursor:pointer}button:hover{background:#00a4dc}.err{background:#3b1818;border:1px solid #742a2a;color:#feb2b2;padding:8px 12px;border-radius:6px;font-size:.85rem;margin-bottom:14px;text-align:center}'

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def is_authed(self):
        if not AUTH_USER or not get_auth_pass():
            return True
        c = SimpleCookie(self.headers.get("Cookie", ""))
        return "cb_session" in c and c["cb_session"].value == get_session_token()

    def send_login(self, error=""):
        err_html = f'<div class="err">{html.escape(error)}</div>' if error else ""
        page = f'<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CollectionBlockarr - Sign In</title><style>.modal-bg{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:999;align-items:center;justify-content:center;padding:16px}}.modal-box{{background:#1c1c1c;border:1px solid #2e2e2e;border-radius:10px;max-width:520px;width:100%;padding:22px;position:relative;box-shadow:0 12px 32px rgba(0,0,0,.65)}}.modal-close{{position:absolute;top:14px;right:14px;background:#262626;color:#aaa;border:1px solid #333;border-radius:6px;width:28px;height:28px;font-size:1.1rem;line-height:1;cursor:pointer}}.modal-close:hover{{color:#fff;border-color:#00a4dc}}{LOGIN_CSS}.modal-bg{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:50;align-items:center;justify-content:center;padding:16px}}.modal-box{{background:#1c1c1c;border:1px solid #2e2e2e;border-radius:10px;max-width:520px;width:100%;padding:22px;position:relative;box-shadow:0 12px 32px rgba(0,0,0,.6)}}.modal-close{{position:absolute;top:14px;right:14px;background:#262626;color:#aaa;border:1px solid #333;border-radius:6px;width:28px;height:28px;font-size:1.1rem;line-height:1;cursor:pointer}}.modal-close:hover{{color:#fff;border-color:#00a4dc}}.settings-panel input{{margin-bottom:10px;padding:8px 12px;font-size:.85rem}}.modal-bg{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:999;align-items:center;justify-content:center;padding:16px}}.modal-box{{background:#1c1c1c;border:1px solid #2e2e2e;border-radius:10px;max-width:520px;width:100%;padding:22px;position:relative;box-shadow:0 12px 32px rgba(0,0,0,.65)}}.modal-close{{position:absolute;top:14px;right:14px;background:#262626;color:#aaa;border:1px solid #333;border-radius:6px;width:28px;height:28px;font-size:1.1rem;line-height:1;cursor:pointer}}.modal-close:hover{{color:#fff;border-color:#00a4dc}}</style></head><body><div class="login-box"><h1>CollectionBlockarr</h1>{err_html}<form method="POST" action="/login"><input type="text" name="username" placeholder="Username" required autofocus><input type="password" name="password" placeholder="Password" required><button type="submit">Sign In</button></form></div></body></html>'
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode())

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/export":
            if not self.is_authed():
                self.send_response(401)
                self.end_headers()
                return
            os.makedirs(BACKUP_DIR, exist_ok=True)
            snaps = {}
            for fn in os.listdir(BACKUP_DIR):
                if fn.endswith(".json"):
                    try:
                        snaps[fn] = json.load(open(os.path.join(BACKUP_DIR, fn)))
                    except Exception:
                        pass
            cfg = load_cfg()
            payload = {
                "blacklist": load_list(),
                "backups": snaps,
                "settings": {k: cfg[k] for k in ("jellyfin_url", "api_key", "auth_pass") if k in cfg}
            }
            data = json.dumps(payload, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Disposition", "attachment; filename=collectionblockarr-backup.json")
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path == "/clean-now":
            if not self.is_authed():
                self.send_response(401)
                self.end_headers()
                return
            clean_collections()
            save_cfg({"needs_clean": False})
            self.send_response(303)
            self.send_header("Location", "/?cleaned=1")
            self.end_headers()
            return
        if parsed.path in ("/favicon.png", "/favicon.ico"):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(FAVICON_PNG)
            return
        if parsed.path == "/logout":
            self.send_response(303)
            self.send_header("Set-Cookie", "cb_session=; Path=/; Max-Age=0")
            self.send_header("Location", "/")
            self.end_headers()
            return
        if not self.is_authed():
            self.send_login()
            return
        if parsed.path == "/test":
            hc = run_health_checks(full=True)
            if all(hc.values()):
                get_jf_versions(lock_if_ok=True)
            q = urllib.parse.urlencode({k: ("1" if v else "0") for k, v in hc.items()})
            self.send_response(303)
            self.send_header("Location", f"/?{q}")
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        base_hc = run_health_checks(full=False)
        def pill(label, val, qkey):
            if qkey in params:
                ok = params[qkey] == ["1"]
                return f'<span class="pill {"ok" if ok else "bad"}">{label} {"✓" if ok else "✕"}</span>'
            if val is None:
                return f'<span class="pill idle">{label} •</span>'
            return f'<span class="pill {"ok" if val else "bad"}">{label} {"✓" if val else "✕"}</span>'

        stored_v, live_v = get_jf_versions(lock_if_ok=False)
        jf_ver = html.escape(stored_v)
        drift = f' <span style="color:#fc8181;font-weight:600">(New Version Detected: {html.escape(live_v)} — run Test)</span>' if (live_v and stored_v != "Unknown" and live_v != stored_v) else ""
        stored_v, live_v = get_jf_versions(lock_if_ok=False)
        jf_ver = html.escape(stored_v)
        drift = f' <span style="color:#fc8181;font-weight:600">(New Version Detected: {html.escape(live_v)} — run Test)</span>' if (live_v and stored_v != "Unknown" and live_v != stored_v) else ""
        clean_now_btn = '<a href="/clean-now" class="btn-test" style="background:#361818;border-color:#742a2a;color:#fc8181">Clean Now</a>' if get_needs_clean() else ""
        status_bar = f'<div class="status-bar"><div class="status-top"><div class="pills">{pill("Auth", base_hc["auth"], "auth")}{pill("API", base_hc["api"], "api")}{pill("Clean", base_hc["clean"], "clean")}{pill("Webhook", base_hc["webhook"], "webhook")}{pill("Storage", base_hc["storage"], "storage")}</div><div style="display:flex;gap:6px">{clean_now_btn}<a href="/test" class="btn-test">Test</a></div></div><div style="font-size:.8rem;color:#aaa;border-top:1px solid #242424;padding-top:7px">Stored Jellyfin version: <strong style="color:#d0d0d0;font-weight:600">{jf_ver}</strong>{drift}</div></div>'

        saved_key = get_api_key()
        saved_url = get_jf_url()
        if "saved" in params:
            toast = '<div class="toast">Settings saved.</div>'
        elif "cleaned" in params:
            toast = '<div class="toast">Library cleaned.</div>'
        elif "imported" in params:
            toast = '<div class="toast">Blocklist imported — click Clean Now to sweep library.</div>'
        elif "imp_err" in params:
            toast = '<div class="warn">Invalid JSON list — paste a valid JSON array like ["Collection A"].</div>'
        else:
            toast = ""
        warn = '<div class="warn">API key required — click Settings to add your Jellyfin API key.</div>' if not saved_key else ""
        _rst = load_cfg().get("retry_state", "")
        if _rst == "passed":
            save_cfg({"retry_state": ""})
        retry_banner = (
            "<div class=\"warn\">Potential issue detected — automatic blocking may not take effect until resolved.<br>Please wait for the automatic 5-minute retest...</div>" if _rst == "waiting" else
            "<div class=\"toast\">Retest passed — things should be back to normal.</div>" if _rst == "passed" else
            "<div class=\"warn\" style=\"background:#361818;border-color:#742a2a;color:#fc8181\">5-minute retest failed — automatic blocking wont work &amp; the app may need updating.</div>" if _rst == "failed" else ""
        )
        setup_modal = '<div id="setup-modal" class="modal-bg" style="display:flex;z-index:1100"><div class="modal-box" style="border:2px solid #fc8181;text-align:center"><h2 style="color:#fc8181;font-size:1.2rem;margin-bottom:10px">Setup Required — Jellyfin API Key Missing</h2><p style="font-size:.9rem;color:#e0e0e0;line-height:1.55;margin-bottom:16px"><strong>Nothing will work until your Jellyfin API key is configured.</strong><br>Webhooks, tests, and cleanup sweeps are paused until you save your key in Settings.</p><button type="button" class="btn-primary" onclick="document.getElementById(\'setup-modal\').style.display=\'none\';document.getElementById(\'settings-panel\').style.display=\'block\';document.querySelector(\'input[name=api_key]\').focus()">Configure Jellyfin API Key Now</button></div></div>' if not saved_key else ""
        panel_display = "block" if not saved_key else "none"

        items = load_list()
        total = len(items)
        total_pages = max(1, math.ceil(total / PER_PAGE))
        try:
            page = max(1, min(int(params.get("page", ["1"])[0]), total_pages))
        except ValueError:
            page = 1
        page_items = items[(page - 1) * PER_PAGE : page * PER_PAGE]

        existing = get_existing_collections()
        options = f'<option value="">--- Choose a collection ---</option>' + "".join(
            f'<option value="{html.escape(c)}">{html.escape(c)}</option>' for c in existing
        )

        rows = "".join(
            f'<div class="item-row"><span>{html.escape(i)}</span><form method="POST" action="/delete" style="margin:0"><input type="hidden" name="name" value="{html.escape(i)}"><input type="hidden" name="page" value="{page}"><button type="submit" class="btn-remove" title="Restore"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="display:block"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg></button></form></div>'
            for i in page_items
        ) if page_items else '<div class="empty">No collections blocked yet.</div>'

        prev_cls = "page-btn disabled" if page <= 1 else "page-btn"
        next_cls = "page-btn disabled" if page >= total_pages else "page-btn"
        logout_btn = '<a href="/logout" class="settings-toggle" style="text-decoration:none">Logout</a>' if (AUTH_USER and get_auth_pass()) else ""

        page_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" type="image/png" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAmUlEQVR4nO3WwQ2AIAwFUKZgX3ZxLEcx0YsmDdHaT/vh0kOP5L/QllBqrefKKglIADvgaG0MULZ9uGT4MsAT7gZA/bzPWMMpACQ8HICGwwCt7zJcG0wK4C88HIBcOxVg6TkNYN5zBgDa82gAvOdewNe0W8JDASPhLoCsfs+nAt4emWmA/tqXAbTBRD8pMEAbTDpgRiUgAQm4ABKAHFeilajbAAAAAElFTkSuQmCC"><title>CollectionBlockarr</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#101010;color:#f0f0f0;display:flex;flex-direction:column;align-items:center;padding:40px 16px}}.topbar{{width:100%;max-width:580px;display:flex;flex-direction:column;align-items:flex-start;gap:12px;margin-bottom:24px}}.top-actions{{display:flex;flex-wrap:wrap;gap:8px;width:100%}}h1{{color:#00a4dc;font-size:2rem;font-weight:700}}.top-actions{{display:flex;gap:8px}}.settings-toggle{{display:inline-flex;align-items:center;justify-content:center;font-family:inherit;line-height:1.2;display:inline-flex;align-items:center;justify-content:center;font-family:inherit;line-height:1.2;background:#1c1c1c;color:#aaa;border:1px solid #2e2e2e;border-radius:6px;padding:6px 12px;font-size:.8rem;cursor:pointer;text-decoration:none;text-decoration:none}}.settings-toggle:hover{{color:#fff;border-color:#00a4dc}}.status-bar{{width:100%;max-width:580px;display:flex;flex-direction:column;background:#161616;border:1px solid #262626;border-radius:8px;padding:10px 12px;margin-bottom:16px;gap:8px}}.status-top{{width:100%;display:flex;justify-content:space-between;align-items:center;gap:8px}}.pills{{display:flex;flex-wrap:wrap;gap:6px}}.pill{{font-size:.75rem;font-weight:600;padding:3px 8px;border-radius:5px}}.pill.ok{{background:#152e20;color:#68d391;border:1px solid #276749}}.pill.bad{{background:#361818;color:#fc8181;border:1px solid #742a2a}}.pill.idle{{background:#222;color:#888;border:1px solid #333}}.btn-test{{background:#242424;color:#00a4dc;border:1px solid #333;border-radius:5px;padding:4px 10px;font-size:.75rem;font-weight:600;text-decoration:none;white-space:nowrap}}.btn-test:hover{{background:#2e2e2e}}.settings-panel{{display:{panel_display};background:#181818;border:1px solid #2a2a2a;border-radius:8px;padding:14px;width:100%;max-width:580px;margin-bottom:18px}}.settings-row{{display:flex;gap:8px}}.settings-row input{{margin-bottom:0;padding:8px 12px;font-size:.85rem}}.btn-save{{background:#2b2b2b;color:#00a4dc;border:1px solid #3a3a3a;border-radius:6px;padding:8px 14px;font-size:.85rem;font-weight:600;cursor:pointer}}.toast{{width:100%;max-width:580px;background:#163020;border:1px solid #276749;color:#9ae6b4;padding:8px 14px;border-radius:6px;font-size:.85rem;margin-bottom:16px;text-align:center}}.warn{{width:100%;max-width:580px;background:#362912;border:1px solid #744210;color:#fbd38d;padding:8px 14px;border-radius:6px;font-size:.85rem;margin-bottom:16px;text-align:center}}.card{{background:#1c1c1c;border:1px solid #2a2a2a;border-radius:10px;padding:22px;width:100%;max-width:580px;margin-bottom:32px}}label{{display:block;font-size:.9rem;color:#d0d0d0;margin-bottom:8px}}select,input[type="text"]{{width:100%;padding:11px 14px;border-radius:6px;border:1px solid #333;background:#141414;color:#d0d0d0;font-size:.9rem;margin-bottom:14px;outline:none}}select:focus,input[type="text"]:focus{{border-color:#00a4dc}}.btn-primary{{width:100%;padding:12px;border:none;border-radius:6px;background:#0095d5;color:#fff;font-size:1rem;font-weight:600;cursor:pointer}}.btn-primary:hover{{background:#00a4dc}}.list-section{{background:#1c1c1c;border:1px solid #2a2a2a;border-radius:10px;padding:22px;width:100%;max-width:580px}}.list-title{{font-size:.9rem;font-weight:400;color:#d0d0d0;margin-bottom:14px}}.item-row{{display:flex;justify-content:space-between;align-items:center;background:#141414;border:1px solid #2a2a2a;border-radius:8px;padding:10px 14px;margin-bottom:10px;font-size:.9rem;color:#d0d0d0}}.btn-remove{{background:#c94a4a;color:#fff;border:none;border-radius:5px;padding:7px 10px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center}}.empty{{color:#777;text-align:center;padding:20px;background:#141414;border-radius:8px}}.pagination{{display:flex;justify-content:space-between;align-items:center;margin-top:18px}}.page-btn{{background:#262626;color:#e0e0e0;text-decoration:none;padding:8px 16px;border-radius:6px;font-size:.9rem;border:1px solid #333}}.page-btn.disabled{{background:#181818;color:#555;border-color:#222;pointer-events:none}}.page-info{{font-size:.9rem;color:#ccc}}.modal-bg{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:999;align-items:center;justify-content:center;padding:16px}}.modal-box{{background:#1c1c1c;border:1px solid #2e2e2e;border-radius:10px;max-width:520px;width:100%;padding:22px;position:relative;box-shadow:0 12px 32px rgba(0,0,0,.65)}}.modal-close{{position:absolute;top:14px;right:14px;background:#262626;color:#aaa;border:1px solid #333;border-radius:6px;width:28px;height:28px;font-size:1.1rem;line-height:1;cursor:pointer}}.modal-close:hover{{color:#fff;border-color:#00a4dc}}</style></head>
<body>
<div class="topbar"><h1>CollectionBlockarr <span style="font-size:.72rem;font-weight:500;color:#777;background:#1c1c1c;border:1px solid #2e2e2e;border-radius:5px;padding:2px 7px;vertical-align:middle;margin-left:6px">{VERSION}</span></h1><div class="top-actions"><a href="https://github.com/MoreBloodWine/CollectionBlockarr" target="_blank" rel="noopener" class="settings-toggle" style="text-decoration:none">GitHub</a><button type="button" class="settings-toggle" onclick="toggleChangelog()">Changelog</button><button type="button" class="settings-toggle" onclick="toggleAbout()">About</button><button type="button" class="settings-toggle" onclick="toggleSettings()">Settings</button>{logout_btn}</div></div>
{status_bar}
<div id="settings-panel" class="settings-panel">
<form method="POST" action="/settings" style="margin:0">
<label style="font-size:.8rem;color:#aaa;margin-bottom:6px">Jellyfin Server URL</label>
<input type="text" name="jellyfin_url" value="{html.escape(saved_url)}" placeholder="http://localhost:8096" required><div style="font-size:.75rem;color:#777;margin:-6px 0 10px">Use the address you open Jellyfin with (e.g. http://192.168.1.50:8096) if localhost fails.</div>
<label style="font-size:.8rem;color:#aaa;margin-bottom:6px">Jellyfin API Key</label>
<input type="text" name="api_key" value="{html.escape(saved_key)}" placeholder="Paste Jellyfin API key..." required>
<label style="font-size:.8rem;color:#aaa;margin-bottom:6px">Change Password <span style="color:#666">(leave blank to keep current)</span></label>
<input type="password" name="new_password" placeholder="New password..." style="width:100%;padding:8px 12px;border-radius:6px;border:1px solid #333;background:#141414;color:#d0d0d0;font-size:.85rem;margin-bottom:12px;outline:none">
<button type="submit" class="btn-save" style="width:100%">Save Settings</button>
</form>
<div style="border-top:1px solid #262626;margin-top:14px;padding-top:12px">
<label style="font-size:.8rem;color:#aaa;margin-bottom:8px">Full Backup &amp; Restore</label>
<div style="display:flex;gap:8px;margin-bottom:10px">
<a href="/export" class="btn-save" style="text-decoration:none;text-align:center;flex:1">Export JSON</a>
<button type="button" class="btn-save" style="flex:1" onclick="var el=document.getElementById('imp-box');el.style.display=el.style.display==='block'?'none':'block'">Import JSON</button>
</div>
<form id="imp-box" method="POST" action="/import" style="display:none;margin:0">
<input type="file" accept=".json,application/json" onchange="var f=this.files[0];if(!f)return;var r=new FileReader();r.onload=function(e){{document.getElementById('imp-ta').value=e.target.result;document.getElementById('imp-box').submit()}};r.readAsText(f)" style="width:100%;font-size:.8rem;color:#aaa;margin-bottom:8px">
<textarea id="imp-ta" name="import_json" rows="3" placeholder='Paste collectionblockarr-backup.json (or legacy blacklist array)' style="width:100%;padding:8px 10px;border-radius:6px;border:1px solid #333;background:#141414;color:#d0d0d0;font-size:.8rem;margin-bottom:8px;outline:none"></textarea>
<button type="submit" class="btn-save" style="width:100%">Import &amp; Merge</button>
</form>
</div>
</div>
<div id="cl-modal" class="modal-bg" style="display:none" onclick="if(event.target===this)toggleChangelog()">
<div class="modal-box" style="max-width:560px">
<button type="button" class="modal-close" onclick="toggleChangelog()" title="Close">&times;</button>
<h2 style="color:#00a4dc;font-size:1.15rem;margin-bottom:12px">Changelog</h2>
<div style="font-size:.85rem;line-height:1.6;color:#ccc;max-height:360px;overflow-y:auto;padding-right:4px">
<div style="margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid #2a2a2a"><strong style="color:#fff">v1.0.1</strong> <span style="color:#777;font-size:.78rem">(2026-11-27)</span><br>&bull; Added background sweep thread (every 60s) with thread-safe sweep lock so scheduled Jellyfin scans never leave blocked collections behind.<br>&bull; Fixed missing <code>threading</code> / <code>_retry_timer</code> crash in 5-minute health retest.<br>&bull; Added in-app Changelog modal and direct GitHub link in top bar.</div>
<div><strong style="color:#fff">v1.0.0</strong> <span style="color:#777;font-size:.78rem">(2026-11-26)</span><br>&bull; Initial release: Jellyfin BoxSet blocking, <code>TmdbCollection</code> stripping, instant JSON restore snapshots, real-time webhook interception, health checks, and full-state export/import.</div>
</div>
</div>
</div>
<div id="about-modal" class="modal-bg" style="display:none" onclick="if(event.target===this){{aboutPage(1);toggleAbout()}}">
<div class="modal-box" style="max-width:680px">
<button type="button" class="modal-close" onclick="aboutPage(1);toggleAbout()" title="Close">&times;</button>
<h2 id="ab-title" style="color:#00a4dc;font-size:1.15rem;margin-bottom:12px">About CollectionBlockarr</h2>
<div id="ab-p1" style="font-size:.86rem;line-height:1.6;color:#ccc;min-height:295px"><div style="white-space:pre-line;color:#e2e8f0;padding-bottom:14px;margin-bottom:14px;border-bottom:1px solid #2a2a2a">Box sets pile up in the dead of night,
Auto-grouped ghosts that ruin the sight.
One silent webhook, one swift API call,
CollectionBlockarr clears them all.</div><strong style="color:#fff">Why CollectionBlockarr Exists</strong><br>If you run a large Jellyfin library with Jellyfin's automatic collection grouping enabled, TMDb metadata automatically groups standalone movies, cash-grab sequels, and unwanted spin-offs into clutter collections—like <em>The Scorpion King Collection</em> or <em>The Mummy Collection</em>—while you still want legitimate sagas and custom collections left alone.<br><br><strong style="color:#fff">Why Existing Workarounds Fell Short</strong><br>&bull; <strong>Disabling Auto-Collections:</strong> Stops auto-collections server-wide, forcing manual curation for every real saga.<br>&bull; <strong>Deleting Collections in Jellyfin:</strong> Only lasts until the next library scan—because the movies still hold their <code>TmdbCollection</code> provider ID, Jellyfin rebuilds them every time.<br>&bull; <strong>Manual Per-Movie Edits:</strong> Tedious, error-prone, and easily overwritten during routine metadata refreshes.</div>
<div id="ab-p2" style="display:none;font-size:.86rem;line-height:1.6;color:#ccc;min-height:295px"><strong style="color:#fff">How CollectionBlockarr Works</strong><br>Built over ~4&ndash;5 days of real-world testing on a production NAS library as a lightweight, zero-dependency Python web app running in Docker alongside Jellyfin:<br><br>1. <strong>Strips the Root Cause (<code>TmdbCollection</code>):</strong> Removes the <code>TmdbCollection</code> provider ID from every movie inside a blocked box set before deleting the collection itself—so future Jellyfin library scans never rebuild it.<br>2. <strong>Real-Time Webhook Defense + Startup Sweep:</strong> Listens for Jellyfin Webhook events (<code>ItemAdded</code> / library updates) to catch and remove blocked collections immediately, backed by an automatic sweep every time the container starts.<br>3. <strong>True Instant Restore Snapshots:</strong> Saves a tiny JSON metadata snapshot (collection name, member movie IDs, and original <code>TmdbCollection</code> ID—never video files) so one click restores the exact grouped collection in Jellyfin.<br><br><strong style="color:#fff">Built-In Safeguards &amp; Reliability</strong><br>&bull; <strong>Zero Media Touch:</strong> Never modifies, moves, or deletes video files, manual collections, or unblocked sagas.<br>&bull; <strong>Self-Monitoring Health Checks &amp; 5-Minute Auto-Retest:</strong> Live status pills verify your API, webhook, config, blocklist, and Jellyfin version with automatic 5-minute background recovery.<br>&bull; <strong>Portable Full-State Backup &amp; Restore:</strong> One-click JSON export and file-picker import bundle your blocklist, restore snapshots, and settings into one portable file.</div>
<div id="ab-p3" style="display:none;font-size:.86rem;line-height:1.6;color:#ccc;min-height:295px"><strong style="color:#fff">Set-and-Forget Automation &amp; Real-World Edge Cases</strong><br>Once paired with Radarr or Sonarr, new releases frequently land in Jellyfin overnight and trigger TMDb to spawn a brand-new unwanted box set before morning. Because CollectionBlockarr hooks directly into Jellyfin&rsquo;s Webhook plugin, blocked collections are intercepted and stripped within seconds of arrival—before anyone browsing your library ever sees the clutter.<br><br>&bull; <strong>Auto-Grouped &amp; Custom Collections Alike:</strong> Whether a blocked entry was auto-generated by TMDb or grouped by hand, CollectionBlockarr snapshots its exact member movie IDs before removal—re-linking TMDb IDs when present and rebuilding custom groupings cleanly if you ever hit restore.<br>&bull; <strong>Why Zero Dependencies Matters:</strong> Built strictly on Python&rsquo;s standard library with no external databases, background queues, or third-party packages—keeping RAM usage negligible and eliminating surprise breakage when Jellyfin or Docker updates.<br>&bull; <strong>Plain-Text Portability:</strong> Every setting, blocklist entry, and restore snapshot lives in clean, human-readable JSON (<code>config.json</code>, <code>blacklist.json</code>, and <code>backups/</code>), so migrating servers or recovering from scratch takes a single exported file and one click.</div>
<div id="ab-p4" style="display:none;font-size:.86rem;line-height:1.6;color:#ccc;min-height:295px"><strong style="color:#fff">Quick-Start &amp; Jellyfin Webhook Blueprint</strong><br>Getting CollectionBlockarr wired into a live Jellyfin server takes under two minutes:<br><br>1. <strong>Generate a Jellyfin API Key:</strong> Open Jellyfin <em>Dashboard &rarr; API Keys</em>, create a key labeled <code>CollectionBlockarr</code>, and paste it alongside your Jellyfin URL inside <strong>Settings</strong>.<br>2. <strong>Enable Real-Time Webhook Interception:</strong> In Jellyfin&rsquo;s official <em>Webhook</em> plugin, add a Generic Destination pointing to <code>http://&lt;your-host-ip&gt;:8099/webhook</code>, check <strong>Item Added</strong> (and <strong>Item Updated</strong>), and enable <em>Send All Properties</em>.<br>3. <strong>Verify Live Health Pills:</strong> Click <strong>Test</strong> on the top status bar—once <code>API</code>, <code>Webhook</code>, <code>Config</code>, <code>Blocklist</code>, and <code>Jellyfin Version</code> read green, every blocked collection is handled automatically.<br><br><strong style="color:#fff">Pro Tip:</strong> Use <strong>Export JSON</strong> inside <strong>Settings</strong> after building your blocklist so your entire setup can be restored onto any future NAS in one click.</div>
<div id="ab-p5" style="display:none;font-size:.86rem;line-height:1.6;color:#ccc;min-height:295px"><strong style="color:#fff">Origin Story, Scope &amp; Open-Source Spirit</strong><br>CollectionBlockarr started as a late-night quality-of-life fix on a home NAS after watching unwanted spin-off box sets like <em>The Scorpion King</em> and <em>The Mummy</em> repeatedly reappear every time Jellyfin refreshed metadata. Over ~4&ndash;5 days of iterative testing against a real multi-terabyte library, it evolved from a single cleanup script into a self-contained web companion.<br><br>&bull; <strong>Deliberately Focused Scope:</strong> CollectionBlockarr stays purpose-built for Jellyfin rather than bloating into multi-server adapters or risky autonomous code-editing—keeping the codebase small, predictable, and easy to audit.<br>&bull; <strong>Built for Self-Hosters, by a Self-Hoster:</strong> Every feature—from 5-item pagination and keyboard-navigable modals to instant restore snapshots and full-state JSON backups—was shaped by real daily use.<br>&bull; <strong>Fork, Tweak &amp; Share Freely:</strong> Released as a clean, open-source Docker setup ready for anyone tired of fighting their own media server&rsquo;s auto-collections.<div style="margin-top:18px;text-align:right;font-style:italic;font-size:.83rem;line-height:1.5;color:#aaa">Conceived, directed, and battle-tested on a live home NAS by <strong style="color:#ddd;font-style:normal">MoreBloodWine</strong> &mdash;<br>built and refined in collaboration with <strong style="color:#00a4dc;font-style:normal">Gemini</strong> (Google AI).<br><span style="font-size:.76rem;color:#777">November 2026</span></div></div>
<div style="display:flex;justify-content:space-between;align-items:center;margin-top:16px;padding-top:12px;border-top:1px solid #2a2a2a">
<button type="button" id="ab-prev" class="page-btn disabled" style="padding:6px 12px;font-size:.8rem;cursor:pointer" onclick="aboutPage(window._abp-1)">&larr; Prev</button>
<span id="ab-ind" style="font-size:.8rem;color:#888">1 / 5</span>
<button type="button" id="ab-next" class="page-btn" style="padding:6px 12px;font-size:.8rem;cursor:pointer" onclick="aboutPage(window._abp+1)">Next &rarr;</button>
</div>
<script>
window._abp=1;
window._abTitles=["About CollectionBlockarr","Architecture & Safeguards","Automation & Design Philosophy","Quick-Start & Webhook Blueprint","Origin Story & Open-Source Spirit"];
function aboutPage(n){{
  if(n<1||n>5)return;
  window._abp=n;
  for(var i=1;i<=5;i++){{document.getElementById("ab-p"+i).style.display=(i===n)?"block":"none";}}
  document.getElementById("ab-title").textContent=window._abTitles[n-1];
  document.getElementById("ab-ind").textContent=n+" / 5";
  document.getElementById("ab-prev").className=(n<=1)?"page-btn disabled":"page-btn";
  document.getElementById("ab-next").className=(n>=5)?"page-btn disabled":"page-btn";
}}
document.addEventListener("keydown",function(e){{
  var m=document.getElementById("about-modal");
  if(!m||m.style.display==="none")return;
  if(e.key==="ArrowLeft")aboutPage(window._abp-1);
  if(e.key==="ArrowRight")aboutPage(window._abp+1);
  if(e.key==="Escape"){{aboutPage(1);toggleAbout();}}
}});
</script>
</div>
</div>
{toast}{warn}{retry_banner}{setup_modal}
<div class="card"><form method="POST" action="/add"><label for="selected">Select Existing Jellyfin Collection ({len(existing):,})</label><select id="selected" name="selected">{options}</select><input type="text" id="manual" name="manual" placeholder="Or type collection name manually to begin searching..." oninput="filterList()"><button type="submit" class="btn-primary">Block &amp; Clean</button></form></div>
<div class="list-section"><div class="list-title">Blocked Collections ({total:,})</div>{rows}<div class="pagination"><a href="/?page={page-1}" class="{prev_cls}">&larr; Previous</a><span class="page-info">Page {page:,} of {total_pages:,}</span><a href="/?page={page+1}" class="{next_cls}">Next &rarr;</a></div></div>
<script>
if(window.location.search)window.history.replaceState(null,"","/");function toggleChangelog(){{var m=document.getElementById("cl-modal");m.style.display=m.style.display==="flex"?"none":"flex";}}function toggleAbout(){{var m=document.getElementById("about-modal");m.style.display=m.style.display==="flex"?"none":"flex";}}function toggleSettings(){{const p=document.getElementById("settings-panel");p.style.display=p.style.display==="block"?"none":"block"}}
const ALL_OPTS=Array.from(document.getElementById("selected").options).slice(1).map(o=>({{v:o.value,t:o.text}}));
function filterList(){{const q=document.getElementById("manual").value.toLowerCase();const s=document.getElementById("selected");const m=ALL_OPTS.filter(o=>o.t.toLowerCase().includes(q));s.innerHTML='<option value="">--- Choose a collection ---</option>'+m.map(o=>`<option value="${{o.v.replace(/"/g,"&quot;")}}">${{o.t}}</option>`).join("");if(q&&m.length===1)s.selectedIndex=1;}}
</script>
</body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page_html.encode())

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        if parsed.path == "/webhook":
            clean_collections()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            return
        if parsed.path == "/login":
            params = urllib.parse.parse_qs(body)
            u = params.get("username", [""])[0]
            p = params.get("password", [""])[0]
            if u == AUTH_USER and p == get_auth_pass():
                self.send_response(303)
                self.send_header("Set-Cookie", f"cb_session={get_session_token()}; Path=/; HttpOnly; SameSite=Lax")
                self.send_header("Location", "/")
                self.end_headers()
            else:
                self.send_login("Invalid username or password.")
            return
        if not self.is_authed():
            self.send_response(401)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(body)
        if parsed.path == "/settings":
            updates = {
                "api_key": next(iter(params.get("api_key", ())), "").strip(),
                "jellyfin_url": next(iter(params.get("jellyfin_url", ())), "").strip()
            }
            new_pw = next(iter(params.get("new_password", ())), "").strip()
            if new_pw:
                updates["auth_pass"] = new_pw
            try:
                req = urllib.request.Request(f"{updates['jellyfin_url'].rstrip('/')}/System/Info", headers={"X-Emby-Token": updates["api_key"]})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status != 200:
                        raise Exception("Bad status")
            except Exception:
                self.send_response(303)
                self.send_header("Location", "/?badkey=1")
                self.end_headers()
                return
            save_cfg(updates)
            self.send_response(303)
            if new_pw:
                self.send_header("Set-Cookie", f"cb_session={get_session_token()}; Path=/; HttpOnly; SameSite=Lax")
            self.send_header("Location", "/?saved=1")
            self.end_headers()
            return
        if parsed.path == "/import":
            raw_json = next(iter(params.get("import_json", ())), "").strip()
            try:
                imported = json.loads(raw_json)
                if isinstance(imported, dict) and ("blacklist" in imported or "settings" in imported or "backups" in imported):
                    bl = imported.get("blacklist", [])
                    if isinstance(bl, list):
                        save_list(load_list() + [str(x).strip() for x in bl if str(x).strip()])
                    st = imported.get("settings", {})
                    if isinstance(st, dict):
                        upd = {k: st[k] for k in ("jellyfin_url", "api_key", "auth_pass") if k in st and st[k]}
                        upd["needs_clean"] = True
                        save_cfg(upd)
                    else:
                        save_cfg({"needs_clean": True})
                    bk = imported.get("backups", {})
                    if isinstance(bk, dict):
                        os.makedirs(BACKUP_DIR, exist_ok=True)
                        for fn, snap in bk.items():
                            safe_fn = os.path.basename(str(fn))
                            if safe_fn.endswith(".json") and isinstance(snap, dict):
                                json.dump(snap, open(os.path.join(BACKUP_DIR, safe_fn), "w"), indent=2)
                    self.send_response(303)
                    if isinstance(st, dict) and st.get("auth_pass"):
                        self.send_header("Set-Cookie", f"cb_session={get_session_token()}; Path=/; HttpOnly; SameSite=Lax")
                    self.send_header("Location", "/?imported=1")
                    self.end_headers()
                    return
                if isinstance(imported, list):
                    merged = load_list() + [str(x).strip() for x in imported if str(x).strip()]
                    save_list(merged)
                    save_cfg({"needs_clean": True})
                    self.send_response(303)
                    self.send_header("Location", "/?imported=1")
                    self.end_headers()
                    return
            except Exception:
                pass
            self.send_response(303)
            self.send_header("Location", "/?imp_err=1")
            self.end_headers()
            return
        if parsed.path == "/add":
            name = params.get("selected", [""])[0].strip() or params.get("manual", [""])[0].strip()
            if name:
                items = load_list()
                items.append(name)
                save_list(items)
                clean_collections()
        elif parsed.path == "/delete":
            name = params.get("name", [""])[0]
            items = [i for i in load_list() if i != name]
            save_list(items)
            if name:
                restore_collection(name)
        self.send_response(303)
        self.send_header("Location", f"/?page={params.get('page', ['1'])[0]}")
        self.end_headers()
        return
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

def _bg_loop():
    while True:
        time.sleep(60)
        clean_collections()

if __name__ == "__main__":
    clean_collections()
    threading.Thread(target=_bg_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
