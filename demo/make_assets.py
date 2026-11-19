"""Records the product tour and takes the portfolio screenshots of the running Document Desk, the dummy portal and the n8n version of the flow.

  python demo/make_assets.py shots | tour | n8nvideo | portalvideo | cover | arch
Needs: playwright with chromium, ffmpeg, the demo template database (made automatically by scripts/seed.py), n8n running for shots and n8nvideo (n8n/README.md)."""
import base64, json, os, shutil, subprocess, sys, threading, time, urllib.request, http.cookiejar
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
A = ROOT / "assets"; A.mkdir(exist_ok=True)
PORT = 8796; URL = f"http://127.0.0.1:{PORT}"; PPORT = 8090; PURL = f"http://127.0.0.1:{PPORT}"
N8N = "http://127.0.0.1:5678"; N8N_USER, N8N_PASS = "owner@leaddesk.example", "LeadDesk#2026"
NOW = "2026-11-05T09:30"; SLACK_LOG = "/tmp/fake_slack_dd.log"; SEED = Path("/tmp/dd_seed")
INK, TEAL = "#17403d", "#2a7f77"

def seed_template():
    if (SEED / "d.db").exists(): return
    SEED.mkdir(exist_ok=True)
    subprocess.run([sys.executable, "scripts/seed.py"], cwd=ROOT, env=dict(os.environ, DB_PATH=str(SEED / "d.db"), FILES_DIR=str(SEED / "f"), FAKE_NOW=NOW, LLM_PROVIDER="rules", GROQ_API_KEY=""), check=True)

def start(tag, seeded=True):
    seed_template(); w = Path(f"/tmp/dd_{tag}"); shutil.rmtree(w, ignore_errors=True); w.mkdir()
    if seeded: shutil.copy(SEED / "d.db", w / "d.db"); shutil.copytree(SEED / "f", w / "f")
    env = dict(os.environ, DB_PATH=str(w / "d.db"), FILES_DIR=str(w / "f"), DEMO_MODE="1", FAKE_NOW=NOW, LLM_PROVIDER="rules", GROQ_API_KEY="", INBOUND_KEY="demo-key", INBOUND_PER_MIN="100000", LOGIN_PER_MIN="1000")
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)], cwd=ROOT, env=env, stdout=open(f"/tmp/dd_{tag}.log", "w"), stderr=subprocess.STDOUT)
    for _ in range(80):
        try: urllib.request.urlopen(URL + "/health", timeout=1); return srv, env
        except Exception: time.sleep(0.3)
    raise RuntimeError("server did not start")
def start_portal():
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--port", str(PPORT)], cwd=ROOT / "portal", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try: urllib.request.urlopen(PURL + "/login", timeout=1); return p
        except Exception: time.sleep(0.3)
    raise RuntimeError("portal did not start")

INIT = """
(() => {
 function init(){
  if(document.getElementById('__cap')) return;
  const s=document.createElement('style'); s.textContent=`
  body{padding-top:64px!important;box-sizing:border-box}
  header{top:64px!important}.pane{top:142px!important;max-height:calc(100vh - 160px)!important}
  #__cur{position:fixed;z-index:99999;width:24px;height:24px;border-radius:50%;background:rgba(42,127,119,.25);border:2px solid #2a7f77;pointer-events:none;transform:translate(-50%,-50%);left:-60px;top:-60px}
  #__cur.dn{background:rgba(42,127,119,.7);transform:translate(-50%,-50%) scale(.75)}
  #__cap{position:fixed;left:0;right:0;top:0;height:64px;z-index:99998;background:#17403d;color:#fff;font:600 17px 'DejaVu Sans',system-ui,sans-serif;display:flex;align-items:center;justify-content:center;text-align:center;padding:0 18px}
  #__cap span{opacity:0;transition:opacity .35s}#__cap span.on{opacity:1}`;
  document.head.appendChild(s);
  const c=document.createElement('div');c.id='__cur';document.body.appendChild(c);
  const k=document.createElement('div');k.id='__cap';k.innerHTML='<span></span>';document.body.appendChild(k);
  document.addEventListener('mousemove',e=>{c.style.left=e.clientX+'px';c.style.top=e.clientY+'px'},true);
  document.addEventListener('mousedown',()=>c.classList.add('dn'),true);document.addEventListener('mouseup',()=>c.classList.remove('dn'),true);
 }
 if(document.readyState!=='loading')init();else document.addEventListener('DOMContentLoaded',init);
})();
"""
def cap(pg, text, wait=0):
    pg.evaluate("t=>{const s=document.querySelector('#__cap span');if(!s)return;s.classList.remove('on');setTimeout(()=>{s.textContent=t;s.classList.add('on')},200)}", text); pg.wait_for_timeout(wait)
def glide(pg, sel, steps=24, nth=0):
    el = pg.locator(sel).nth(nth); el.scroll_into_view_if_needed(); bb = el.bounding_box(); pg.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2, steps=steps)
def click(pg, sel, nth=0):
    glide(pg, sel, nth=nth); pg.wait_for_timeout(220); pg.mouse.down(); pg.wait_for_timeout(90); pg.mouse.up(); pg.wait_for_timeout(300)
def typ(pg, sel, text, delay=35):
    click(pg, sel); pg.keyboard.press("Control+A"); pg.keyboard.type(text, delay=delay); pg.wait_for_timeout(200)
def card(pg, title, sub, foot=""):
    pg.set_content(f"""<body style="margin:0;height:100vh;display:grid;place-items:center;background:linear-gradient(135deg,#e6f1ee,#faf9f5 60%,#f3ecd6);font-family:Inter,'DejaVu Sans',sans-serif;color:{INK};text-align:center">
    <div style="max-width:980px;padding:30px"><div style="width:84px;height:84px;margin:0 auto 26px;border-radius:24px;background:{TEAL};box-shadow:0 14px 30px #2a7f7755;display:grid;place-items:center"><div style="width:30px;height:36px;border:5px solid #fff;border-top-width:11px;border-radius:5px"></div></div>
    <div style="font-size:46px;font-weight:750;line-height:1.15;letter-spacing:-1px">{title}</div><div style="font-size:21px;color:#5f7673;margin-top:18px;line-height:1.5">{sub}</div>
    <div style="font-size:15px;color:#1f645d;margin-top:34px;letter-spacing:.4px;font-weight:600">{foot}</div></div></body>""")

def api(path, body=None, token=None, key=None):
    h = {"Content-Type": "application/json"}; token and h.update(Authorization="Bearer " + token); key and h.update({"X-Inbound-Key": key})
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode() if body is not None else None, headers=h); return json.load(urllib.request.urlopen(req, timeout=120))
def token(): return api("/api/admin/login", {"password": "demo"})["token"]
def doc_id(name_part):
    return next(d["id"] for d in api("/api/admin/docs", token=token()) if name_part in d["filename"])
def sign_in(pg):
    pg.goto(URL + "/"); pg.fill("#pw", "demo"); pg.click("#lgo"); pg.wait_for_selector("tr.row")
def open_row(pg, did): pg.click(f"tr.row[data-id='{did}']"); pg.wait_for_selector("#pv[src^=blob]"); pg.wait_for_timeout(700)

# ---------- n8n ----------
def n8n_id():
    jar = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.open(urllib.request.Request(N8N + "/rest/login", data=json.dumps({"emailOrLdapLoginId": N8N_USER, "password": N8N_PASS}).encode(), headers={"Content-Type": "application/json"}))
    for w in json.load(op.open(N8N + "/rest/workflows"))["data"]:
        if w["name"].startswith("Documents to review") and w.get("active") and not w.get("isArchived"): return w["id"]
    raise RuntimeError("workflow not imported, see n8n/README.md")
def n8n_login(pg):
    pg.goto(N8N + "/signin"); pg.wait_for_timeout(1800)
    pg.fill("input[type=email], input[name=emailOrLdapLoginId]", N8N_USER); pg.fill("input[type=password]", N8N_PASS); pg.keyboard.press("Enter"); pg.wait_for_timeout(3000)
def fire(path, name, wait=120):
    data = (ROOT / "data" / "docs" / "heldout" / name).read_bytes()
    req = urllib.request.Request(N8N + path, data=json.dumps({"filename": name, "content_base64": base64.b64encode(data).decode()}).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=wait))
N8N_DOCS = ["hel13_classic_hollis_scan.pdf", "hel09_bill_kestrel_scan.png", "hel16_bill_alder.pdf", "hel11_receipt_northgate_scan.jpg", "hel18_classic_northgate_scan.jpg", "hel20_modern_millbrook.pdf"]

# ---------- screenshots ----------
def shots():
    srv, env = start("shots", seeded=True); slack = subprocess.Popen([sys.executable, str(ROOT / "n8n" / "fake_slack.py"), "8799", SLACK_LOG]); portal = start_portal()
    try:
        wid = n8n_id(); (os.path.exists(SLACK_LOG) and os.remove(SLACK_LOG))
        with sync_playwright() as pw:
            b = pw.chromium.launch(); ctx = b.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=2); pg = ctx.new_page()
            n8n_login(pg); pg.goto(f"{N8N}/workflow/{wid}"); pg.wait_for_selector('[data-node-name="Reply with result"]', timeout=60000); pg.wait_for_timeout(1500); pg.screenshot(path=str(A / "14_n8n_workflow.png"))
            res = [fire("/webhook/incoming-document", n) for n in N8N_DOCS]; print("n8n results:", [(r["status"], r.get("duplicate")) for r in res])
            pg.goto(f"{N8N}/workflow/{wid}/executions"); pg.wait_for_timeout(3500); pg.screenshot(path=str(A / "15_n8n_executions.png"))
            rows = pg.locator("text=Succeeded in"); print("execution rows:", rows.count()); rows.nth(1).click(); pg.wait_for_timeout(3200); pg.screenshot(path=str(A / "16_n8n_one_run.png"))
            b.close()
        msgs = [json.loads(l)["text"] for l in (open(SLACK_LOG).read().splitlines() if os.path.exists(SLACK_LOG) else []) if l.strip()]; print("chat messages:", msgs)
        desk_shots()
    finally: srv.terminate(); slack.terminate(); portal.terminate()

def desk_shots():
    with sync_playwright() as pw:
        b = pw.chromium.launch(); ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2); pg = ctx.new_page()
        pg.goto(URL + "/"); pg.wait_for_timeout(600); pg.screenshot(path=str(A / "01_login.png"))
        pg.fill("#pw", "demo"); pg.click("#lgo"); pg.wait_for_selector("tr.row"); pg.wait_for_timeout(500); pg.screenshot(path=str(A / "02_inbox.png"))
        pg.click(".chip[data-f=review]"); pg.wait_for_timeout(700); pg.screenshot(path=str(A / "03_needs_review.png"))
        pg.click(".chip[data-f='']"); pg.wait_for_timeout(500)
        d1 = doc_id("dev01_classic"); open_row(pg, d1); pg.screenshot(path=str(A / "04_review_digital.png"))
        pg.click("#bk"); pg.wait_for_selector("tr.row")
        d2 = doc_id("dev24_receipt"); open_row(pg, d2); pg.screenshot(path=str(A / "05_review_scan_problem.png"))
        pg.evaluate("window.scrollTo(0, 700)"); pg.wait_for_timeout(300); pg.screenshot(path=str(A / "06_checks_and_items.png"))
        pg.click("#addi"); r = pg.locator("#it tbody tr").last; ins = r.locator("input")
        ins.nth(0).fill("Baking parchment roll"); ins.nth(1).fill("2"); ins.nth(2).fill("7.56"); ins.nth(3).fill("15.12"); pg.click("#save"); pg.wait_for_timeout(1500)
        pg.wait_for_selector("#pv[src^=blob]"); pg.screenshot(path=str(A / "07_after_fix_ready.png"))
        pg.click("#bk"); pg.wait_for_selector("tr.row"); pg.click("[data-v=recon]"); pg.wait_for_selector("#v-recon .rc"); pg.wait_for_timeout(700); pg.screenshot(path=str(A / "08_portal_check.png"))
        m = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True, has_touch=True); mp = m.new_page()
        mp.goto(URL + "/"); mp.fill("#pw", "demo"); mp.click("#lgo"); mp.wait_for_selector("tr.row"); mp.wait_for_timeout(500); mp.screenshot(path=str(A / "09_mobile_inbox.png"))
        # the dummy portal
        pp = b.new_context(viewport={"width": 1200, "height": 760}, device_scale_factor=2).new_page(); pp.goto(PURL + "/login"); pp.wait_for_timeout(400); pp.screenshot(path=str(A / "10_portal_login.png"))
        pp.fill("#user", "buyer"); pp.fill("#pw", "portal-demo"); pp.click("#go"); pp.wait_for_selector("#stmt"); pp.wait_for_timeout(400); pp.screenshot(path=str(A / "11_portal_statement.png"))
        b.close()
    print("desk screenshots done")

# ---------- the tour ----------
def tour():
    srv, env = start("tour")
    try:
        d_fix = doc_id("dev24_receipt"); d_dig = doc_id("dev01_classic")
        with sync_playwright() as pw:
            b = pw.chromium.launch(); c0 = b.new_context(viewport={"width": 1440, "height": 900}); p0 = c0.new_page(); p0.goto(URL + "/"); p0.fill("#pw", "demo"); p0.click("#lgo"); p0.wait_for_selector("tr.row"); state = c0.storage_state(); c0.close()
            ctx = b.new_context(viewport={"width": 1440, "height": 900}, storage_state=state, record_video_dir=str(A / "_vid"), record_video_size={"width": 1440, "height": 900})
            ctx.add_init_script(INIT); pg = ctx.new_page()
            card(pg, "Fernhill Document Desk", "Reads supplier invoices and receipts, PDF or scanned,<br>checks the arithmetic, and lets a person approve with one click.", "Python  |  FastAPI  |  OCR  |  n8n  |  Demo with dummy data"); pg.wait_for_timeout(4200)
            pg.goto(URL + "/"); pg.wait_for_selector("tr.row"); pg.wait_for_timeout(900)
            cap(pg, "1. The inbox. Every document that arrived, from uploads, the supplier portal or email", 4600)
            cap(pg, "The tiles show what is ready, what needs a look, and how much was read without help", 3800)
            click(pg, ".chip[data-f=review]"); cap(pg, "2. 'Needs review' holds only what the checks could not confirm", 4200)
            click(pg, ".chip[data-f='']"); pg.wait_for_timeout(500)
            cap(pg, "3. Open any document. The original is on the left, what was read is on the right", 800)
            click(pg, f"tr.row[data-id='{d_dig}']"); pg.wait_for_selector("#pv[src^=blob]"); pg.wait_for_timeout(2600)
            cap(pg, "Each field shows how sure the reader is, and where it came from", 4200)
            pg.evaluate("window.scrollTo({top:620,behavior:'smooth'})"); pg.wait_for_timeout(900)
            cap(pg, "The arithmetic is checked: items, subtotal, tax and total must agree", 4400)
            pg.evaluate("window.scrollTo({top:0,behavior:'smooth'})"); pg.wait_for_timeout(700)
            click(pg, "#bk"); pg.wait_for_selector("tr.row"); pg.wait_for_timeout(400)
            cap(pg, "4. A scanned receipt where one line was too blurry to read", 700)
            click(pg, f"tr.row[data-id='{d_fix}']"); pg.wait_for_selector("#pv[src^=blob]"); pg.wait_for_timeout(2400)
            pg.evaluate("window.scrollTo({top:620,behavior:'smooth'})"); pg.wait_for_timeout(900)
            cap(pg, "The line items do not add up to the subtotal, so it was held back for a person", 4600)
            cap(pg, "The person adds the missing line from the picture on the left", 700)
            click(pg, "#addi"); ins = pg.locator("#it tbody tr").last.locator("input")
            for i, t in enumerate(["Baking parchment roll", "2", "7.56", "15.12"]): ins.nth(i).click(); pg.keyboard.type(t, delay=60); pg.wait_for_timeout(120)
            pg.wait_for_timeout(500); click(pg, "#save"); pg.wait_for_timeout(1800)
            cap(pg, "Saved. The checks pass now and the status turns to Ready. The edit is logged", 4200)
            pg.evaluate("window.scrollTo({top:700,behavior:'smooth'})"); pg.wait_for_timeout(700); cap(pg, "Everything a person changed is in the history", 2800)
            pg.evaluate("window.scrollTo({top:0,behavior:'smooth'})"); pg.wait_for_timeout(700); click(pg, "#ok"); pg.wait_for_selector("tr.row"); pg.wait_for_timeout(900); cap(pg, "Approved. It is ready for export", 2800)
            cap(pg, "5. Drop in a new document. A 27-line invoice over two pages", 600)
            hel = next((ROOT / "data" / "docs" / "heldout").glob("hel12_*")); pg.set_input_files("#file", str(hel)); pg.wait_for_timeout(9000)
            cap(pg, "Read in a few seconds, every field and line, and the checks passed", 4200)
            click(pg, f"tr.row[data-id='{doc_id('hel12_')}']"); pg.wait_for_selector("#pv[src^=blob]"); pg.wait_for_timeout(1800); cap(pg, "Multi-page documents have a tab per page", 3000)
            click(pg, ".pages .chip", nth=1); pg.wait_for_timeout(2200); click(pg, "#bk"); pg.wait_for_selector("tr.row")
            click(pg, "[data-v=recon]"); pg.wait_for_selector("#v-recon .rc"); pg.wait_for_timeout(800)
            cap(pg, "6. Portal check: the supplier statement against what was actually read", 3800)
            cap(pg, "Amounts that differ, and statement lines with no document, are listed", 4200)
            click(pg, "[data-v=inbox]"); pg.wait_for_selector("tr.row"); pg.wait_for_timeout(500)
            cap(pg, "7. Export the approved documents as CSV or Excel for the accounts system", 800)
            click(pg, "#expxlsx"); pg.wait_for_timeout(3000)
            card(pg, "Fernhill Document Desk", "Read it, check it, approve it.<br>A person stays in charge of anything the checks cannot confirm.", "Code, tests and case study included"); pg.wait_for_timeout(3800)
            video = pg.video; ctx.close(); b.close(); vpath = video.path()
    finally: srv.terminate()
    encode(vpath, A / "Document_Desk_Tour.mp4")

def encode(vpath, out, cut=None, speed=None):
    vf = ["-filter_complex", f"[0:v]trim=0:{cut[0]:.2f},setpts=PTS-STARTPTS[a];[0:v]trim=start={cut[1]:.2f},setpts=PTS-STARTPTS[b];[a][b]concat=n=2:v=1:a=0[v]", "-map", "[v]"] if cut else []
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(vpath), *vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], check=True)
    shutil.rmtree(A / "_vid", ignore_errors=True); print("wrote", out, f"{out.stat().st_size // 1024} KB")

# ---------- the n8n video ----------
def n8nvideo():
    srv, env = start("n8n"); slack = subprocess.Popen([sys.executable, str(ROOT / "n8n" / "fake_slack.py"), "8799", SLACK_LOG])
    name = "hel15_modern_cobble_scan.jpg"
    try:
        wid = n8n_id()
        with sync_playwright() as pw:
            b = pw.chromium.launch(); c0 = b.new_context(viewport={"width": 1600, "height": 900}); p0 = c0.new_page(); n8n_login(p0); state = c0.storage_state(); c0.close()
            ctx = b.new_context(viewport={"width": 1600, "height": 900}, storage_state=state, record_video_dir=str(A / "_vid"), record_video_size={"width": 1600, "height": 900})
            ctx.add_init_script(INIT.replace("header{top:64px!important}.pane{top:142px!important;max-height:calc(100vh - 160px)!important}", "")); t0 = time.time(); pg = ctx.new_page()
            card(pg, "The same flow in n8n", "A workflow that takes a document, sends it to Document Desk,<br>and routes it by how well it could be read.", "n8n  |  Webhook  |  HTTP Request  |  Switch  |  Chat alert"); pg.wait_for_timeout(4000)
            cut_a = time.time() - t0 - .3; pg.goto(f"{N8N}/workflow/{wid}"); pg.wait_for_selector('[data-node-name="Reply with result"]', timeout=60000); pg.wait_for_timeout(600); cut_b = time.time() - t0 - .3
            pg.wait_for_timeout(2500)
            cap(pg, "The workflow. Documents come in on the left (a test inbox here, a mailbox in production)", 4200)
            cap(pg, "It sends the file to Document Desk, then routes by the result", 4000)
            cap(pg, "Now a real run. Click Execute workflow, then send it a scanned invoice", 500)
            click(pg, "text=Execute workflow"); pg.wait_for_timeout(1800)
            cap(pg, "The test inbox is listening. A scanned invoice arrives now", 800)
            t = threading.Thread(target=lambda: fire("/webhook-test/incoming-document", name)); t.start(); pg.wait_for_timeout(9000); t.join()
            cap(pg, "Every step ran. It was read as a scan and sent down the right branch", 4200)
            bb = pg.locator('[data-node-name="Send to Document Desk"]').first.bounding_box(); pg.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2, steps=25); pg.wait_for_timeout(300)
            pg.mouse.dblclick(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2); pg.wait_for_timeout(2600)
            cap(pg, "Open any step to see what went in and what came out", 4200)
            pg.keyboard.press("Escape"); pg.wait_for_timeout(800)
            cap(pg, "In production the workflow is switched on and keeps a history of every run", 400)
            pg.goto(f"{N8N}/workflow/{wid}/executions"); pg.wait_for_timeout(3500); cap(pg, "Every run is recorded, so a failure can be found and replayed", 4200)
            card(pg, "Two ways to run it", "Document Desk on its own, or driven by n8n.<br>Same reader, same checks, same approval step.", "n8n workflow file included"); pg.wait_for_timeout(3600)
            video = pg.video; ctx.close(); b.close(); vpath = video.path()
    finally: srv.terminate(); slack.terminate()
    encode(vpath, A / "n8n_Flow_Demo.mp4", cut=(cut_a, cut_b))

# ---------- the portal bot video ----------
def portalvideo():
    srv, env = start("bot", seeded=False); portal = start_portal()
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(slow_mo=250); ctx = b.new_context(viewport={"width": 1280, "height": 800}, accept_downloads=True, record_video_dir=str(A / "_vid"), record_video_size={"width": 1280, "height": 800})
            ctx.add_init_script(INIT.replace("header{top:64px!important}.pane{top:142px!important;max-height:calc(100vh - 160px)!important}", ".top{top:64px!important}")); pg = ctx.new_page()
            card(pg, "A bot that collects the documents", "Logs in to the supplier portal like a person, reads the statement,<br>downloads each PDF and hands it to Document Desk.", "Playwright  |  Python"); pg.wait_for_timeout(3800)
            pg.goto(PURL + "/login"); pg.wait_for_timeout(500); cap(pg, "1. The bot signs in to the supplier portal", 800)
            pg.fill("#user", "buyer"); pg.fill("#pw", "portal-demo"); pg.click("#go"); pg.wait_for_selector("#stmt"); cap(pg, "2. It reads every row of the statement table", 2500)
            n = 0
            for pgno in range(3):
                for tr in pg.query_selector_all("#stmt tbody tr")[:3]:
                    tr.scroll_into_view_if_needed(); tr.hover(); link = tr.query_selector("a.dl")
                    if link:
                        cap(pg, "3. It downloads the PDF for each line and sends it for reading", 0)
                        with pg.expect_download() as dl: link.click()
                        d = dl.value; data = open(d.path(), "rb").read(); api("/api/inbound", {"filename": d.suggested_filename, "content_base64": base64.b64encode(data).decode(), "source": "portal"}, key="demo-key"); n += 1
                nx = pg.query_selector("a.next")
                if not nx: break
                cap(pg, "4. Next page. The bot keeps going until the statement ends", 0); nx.click(); pg.wait_for_load_state(); pg.wait_for_timeout(500)
            cap(pg, f"Done: {n} documents downloaded and read. Every one now waits in Document Desk", 3500)
            page2 = ctx.new_page(); page2.goto(URL + "/"); page2.fill("#pw", "demo"); page2.click("#lgo"); page2.wait_for_selector("tr.row"); cap(page2, "In Document Desk, the new documents arrive marked with source 'portal'", 4500)
            video = pg.video; ctx.close(); b.close(); vpath = video.path()
    finally: srv.terminate(); portal.terminate()
    encode(vpath, A / "Portal_Bot_Demo.mp4")

def cover():
    img = base64.b64encode((A / "02_inbox.png").read_bytes()).decode()
    with sync_playwright() as pw:
        b = pw.chromium.launch(); pg = b.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
        pg.set_content(f"""<body style="margin:0;width:1600px;height:900px;background:linear-gradient(135deg,#e6f1ee,#faf9f5 55%,#f3ecd6);font-family:Inter,'DejaVu Sans',sans-serif;color:{INK};position:relative;overflow:hidden">
        <div style="position:absolute;left:84px;top:150px;width:620px">
          <div style="display:inline-block;background:#fff;border:1px solid #cfe0dc;color:#1f645d;font-weight:700;font-size:20px;padding:9px 18px;border-radius:999px">Document and portal data extraction</div>
          <div style="font-size:78px;font-weight:800;line-height:1.04;letter-spacing:-2.5px;margin-top:28px">Document Desk</div>
          <div style="font-size:28px;color:#5a706d;line-height:1.45;margin-top:26px">Reads invoices and receipts, PDF or scanned, checks the numbers and keeps a person in charge of the doubtful ones.</div>
          <div style="display:flex;gap:12px;margin-top:40px;flex-wrap:wrap">{"".join(f'<span style="background:{TEAL};color:#fff;font-weight:650;font-size:20px;padding:10px 18px;border-radius:12px">{t}</span>' for t in ("Read", "Check", "Approve"))}</div>
          <div style="font-size:19px;color:#6a7f7c;margin-top:30px">Python  |  FastAPI  |  Tesseract OCR  |  Playwright  |  n8n</div></div>
        <div style="position:absolute;left:740px;top:110px;width:760px;border-radius:18px;overflow:hidden;box-shadow:0 40px 90px rgba(31,100,93,.25);border:1px solid #cfe0dc;background:#fff">
          <div style="background:#eef3ef;padding:12px 16px;display:flex;gap:8px"><i style="width:12px;height:12px;border-radius:50%;background:#e29b94"></i><i style="width:12px;height:12px;border-radius:50%;background:#e9c46a"></i><i style="width:12px;height:12px;border-radius:50%;background:#7fbf9f"></i></div>
          <img src="data:image/png;base64,{img}" style="width:760px;display:block;margin-top:-4px"></div></body>""")
        pg.wait_for_timeout(400); pg.screenshot(path=str(A / "00_cover.png")); b.close()
    print("cover done")

def architecture():
    box = lambda x, y, w, h, t, sub="", fill="#fff", stroke="#cfe0dc", col=INK: f"""<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{stroke}" stroke-width="2"/><text x="{x + w / 2}" y="{y + h / 2 - (8 if sub else -6)}" text-anchor="middle" font-size="21" font-weight="700" fill="{col}">{t}</text>{f'<text x="{x + w / 2}" y="{y + h / 2 + 18}" text-anchor="middle" font-size="15" fill="{"#d6ebe7" if fill == TEAL else "#6a7f7c"}">{sub}</text>' if sub else ''}"""
    arrow = lambda x1, y1, x2, y2: f'<path d="M{x1} {y1} L{x2} {y2}" stroke="{TEAL}" stroke-width="3" marker-end="url(#a)" fill="none"/>'
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="640" viewBox="0 0 1500 640" font-family="Inter,'DejaVu Sans',sans-serif">
    <defs><marker id="a" markerUnits="userSpaceOnUse" markerWidth="14" markerHeight="14" refX="12" refY="7" orient="auto"><path d="M0 1 L13 7 L0 13 z" fill="{TEAL}"/></marker></defs>
    <rect width="1500" height="640" fill="#f6f5f0"/>
    {box(40, 130, 210, 90, "Supplier portal", "Playwright bot", "#e6f1ee", TEAL)}
    {box(40, 250, 210, 90, "n8n or mailbox", "PDF or image", "#e6f1ee", TEAL)}
    {box(40, 370, 210, 90, "Upload", "drag and drop", "#e6f1ee", TEAL)}
    {box(330, 250, 240, 100, "Inbound door", "key, type and size checked", "#fff")}
    {box(650, 250, 250, 100, "Reader", "PDF text or OCR + deskew", TEAL, "#1f645d", "#fff")}
    {box(980, 250, 220, 100, "Field rules", "labels, dates, numbers", "#fff")}
    {box(1260, 250, 200, 100, "Checks", "arithmetic, dates", "#fff")}
    {box(980, 450, 220, 90, "SQLite", "documents, items, log")}
    {box(650, 450, 250, 90, "Review queue", "ready or needs review", "#fff")}
    {box(330, 450, 240, 90, "Dashboard", "fix, approve, export", "#e6f1ee", TEAL)}
    {box(1260, 450, 200, 90, "CSV and Excel", "approved only")}
    {box(980, 60, 220, 90, "Groq (optional)", "quote must be in the text")}
    {box(650, 60, 250, 90, "Portal statement", "reconciled with totals")}
    {arrow(250, 175, 330, 285)}{arrow(250, 295, 330, 300)}{arrow(250, 415, 330, 330)}{arrow(570, 300, 650, 300)}{arrow(900, 300, 980, 300)}{arrow(1200, 300, 1260, 300)}
    {arrow(1090, 150, 1090, 250)}{arrow(1360, 350, 1360, 450)}{arrow(1260, 495, 1200, 495)}{arrow(980, 495, 900, 495)}{arrow(650, 495, 570, 495)}{arrow(775, 150, 775, 450)}
    <text x="40" y="610" font-size="17" fill="#6a7f7c">A document is only approved by a person, and anything the checks cannot confirm waits in the review queue.</text></svg>"""
    with sync_playwright() as pw:
        b = pw.chromium.launch(); pg = b.new_page(viewport={"width": 1500, "height": 640}, device_scale_factor=2)
        pg.set_content(f"<body style='margin:0'>{svg}</body>"); pg.screenshot(path=str(A / "12_architecture.png")); b.close()
    print("architecture done")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"shots": shots, "tour": tour, "n8nvideo": n8nvideo, "portalvideo": portalvideo, "cover": cover, "arch": architecture}.get(cmd, lambda: print("use: shots|tour|n8nvideo|portalvideo|cover|arch"))()
