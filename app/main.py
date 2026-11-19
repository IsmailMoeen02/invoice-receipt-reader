import base64, binascii, csv, hmac, io, json, logging, re, subprocess, tempfile
from decimal import Decimal
from datetime import date
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Depends, UploadFile, File
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import config, db, ingest, security

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("docdesk")
def jlog(**kw): log.info(json.dumps({"ts": config.wall().isoformat(timespec="seconds"), **kw}))

STATIC = Path(__file__).resolve().parent.parent / "static"
app = FastAPI(title=f"{config.COMPANY} Document Desk", docs_url=None, redoc_url=None)
db.init()
inbound_rl, login_rl = security.RateLimiter(config.INBOUND_PER_MIN), security.RateLimiter(config.LOGIN_PER_MIN)
if config.GENERATED_PASSWORD: print(f"Admin password for this run: {config.GENERATED_PASSWORD}")

@app.middleware("http")
async def headers(request: Request, call_next):
    r = await call_next(request)
    r.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                      "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data: blob:",
                      "Cache-Control": "no-store" if request.url.path.startswith("/api") else "no-cache"})
    return r

def ip(request): return request.client.host if request.client else "?"
def is_admin(request):
    h = request.headers.get("authorization", ""); return h.startswith("Bearer ") and security.verify_token(h[7:])
def admin(request: Request):
    if not is_admin(request): raise HTTPException(401, "Not signed in")
def door(request: Request):
    key = request.headers.get("x-inbound-key", "")
    if not (is_admin(request) or (config.INBOUND_KEY and hmac.compare_digest(key, config.INBOUND_KEY))): raise HTTPException(401, "Missing or wrong inbound key")
    if not inbound_rl.allow(ip(request)): raise HTTPException(429, "Too many documents, slow down")

@app.get("/health")
def health(): return {"ok": True}

# ---------- inbound: n8n, the portal bot, a mail forwarder. JSON with base64, or a multipart file ----------
class Inbound(BaseModel):
    filename: str = Field(max_length=200)
    content_base64: str = Field(max_length=15_000_000)
    source: str = Field(default="inbound", max_length=40)
    portal_ref: str | None = Field(default=None, max_length=80)

@app.post("/api/inbound", dependencies=[Depends(door)])
def inbound(body: Inbound):
    try: data = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError): raise HTTPException(422, "content_base64 is not valid base64")
    try: res = ingest.process(data, body.filename, body.source, body.portal_ref)
    except ingest.Rejected as e: raise HTTPException(422, str(e))
    jlog(event="document", **{k: res.get(k) for k in ("id", "status", "duplicate")}); return res

@app.post("/api/admin/upload", dependencies=[Depends(admin)])
async def upload(file: UploadFile = File(...)):
    data = await file.read(config.MAX_UPLOAD + 1)
    try: return ingest.process(data, file.filename or "upload", "upload")
    except ingest.Rejected as e: raise HTTPException(422, str(e))

class Login(BaseModel): password: str = Field(max_length=200)
@app.post("/api/admin/login")
def login(body: Login, request: Request):
    if not login_rl.allow(ip(request)): raise HTTPException(429, "Too many attempts, wait a minute")
    if not security.check_password(body.password): raise HTTPException(401, "Wrong password")
    return {"token": security.make_token()}

# ---------- reading ----------
def doc_row(r, brief=True):
    d = dict(r); meta = json.loads(d.pop("meta") or "{}"); d["conf"] = meta.get("conf", {}); d["low"] = meta.get("low", []); d["checks_failed"] = sum(not c["ok"] for c in meta.get("checks", []))
    if not brief: d["how"], d["text"], d["checks"], d["notes"], d["locale"] = meta.get("how", {}), meta.get("text", {}), meta.get("checks", []), meta.get("notes", []), meta.get("locale")
    d.pop("stored", None); d.pop("sha", None); return d

@app.get("/api/admin/stats", dependencies=[Depends(admin)])
def stats():
    c = db.connect()
    try:
        q = lambda sql, *a: c.execute(sql, a).fetchone()[0]
        total = q("select count(*) from documents"); ready = q("select count(*) from documents where status='ready' and state='pending'")
        return {"documents": total, "ready": ready, "review": q("select count(*) from documents where status='review' and state='pending'"), "failed": q("select count(*) from documents where status='failed' and state='pending'"),
                "approved": q("select count(*) from documents where state='approved'"), "rejected": q("select count(*) from documents where state='rejected'"),
                "approved_value": round(q("select coalesce(sum(total),0) from documents where state='approved'"), 2), "pending_value": round(q("select coalesce(sum(total),0) from documents where state='pending'"), 2),
                "straight_through": round(100 * q("select count(*) from documents where status='ready'") / total) if total else 0,
                "corrections": q("select count(*) from activity where text like 'Corrected%'"), "suppliers": [dict(r) for r in c.execute("select supplier, count(*) n, round(sum(total),2) total from documents where supplier is not null and state!='rejected' group by 1 order by 3 desc limit 6")],
                "sources": {r[0]: r[1] for r in c.execute("select source, count(*) from documents group by 1")}}
    finally: c.close()

@app.get("/api/admin/docs", dependencies=[Depends(admin)])
def docs(status: str = "", state: str = "", q: str = ""):
    c = db.connect()
    try:
        sql, a = "select * from documents where 1=1", []
        if status: sql += " and status=?"; a.append(status)
        if state: sql += " and state=?"; a.append(state)
        if q: sql += " and (supplier like ? or invoice_no like ? or filename like ? or po like ?)"; a += [f"%{q[:60]}%"] * 4
        return [doc_row(r) for r in c.execute(sql + " order by case status when 'review' then 0 when 'failed' then 1 else 2 end, id desc limit 300", a)]
    finally: c.close()

@app.get("/api/admin/docs/{did}", dependencies=[Depends(admin)])
def doc_detail(did: int):
    c = db.connect()
    try:
        r = c.execute("select * from documents where id=?", (did,)).fetchone()
        if not r: raise HTTPException(404, "No such document")
        return {"doc": doc_row(r, False), "items": [dict(i) for i in c.execute("select * from items where doc=? order by pos", (did,))], "activity": [dict(a) for a in c.execute("select text, ts from activity where doc=? order by id desc", (did,))]}
    finally: c.close()

@app.get("/api/admin/docs/{did}/file", dependencies=[Depends(admin)])
def doc_file(did: int):
    c = db.connect()
    try:
        r = c.execute("select stored, filename, mime from documents where id=?", (did,)).fetchone()
        if not r: raise HTTPException(404, "No such document")
        p = config.FILES_DIR / r["stored"]
        if not p.exists(): raise HTTPException(404, "File missing")
        return FileResponse(p, media_type=r["mime"], filename=r["filename"], content_disposition_type="attachment")
    finally: c.close()

@app.get("/api/admin/docs/{did}/preview/{page}", dependencies=[Depends(admin)])
def doc_preview(did: int, page: int = 1):
    """A PNG of one page, so the browser never has to open a PDF viewer."""
    c = db.connect()
    try:
        r = c.execute("select stored, mime, pages from documents where id=?", (did,)).fetchone()
        if not r: raise HTTPException(404, "No such document")
        if page < 1 or page > (r["pages"] or 1): raise HTTPException(404, "No such page")
        p = config.FILES_DIR / r["stored"]; cache = config.FILES_DIR / f"{p.stem}.p{page}.png"
        if not cache.exists():
            if r["mime"] == "application/pdf":
                with tempfile.TemporaryDirectory() as d:
                    subprocess.run(["pdftoppm", "-r", "110", "-f", str(page), "-l", str(page), "-png", str(p), f"{d}/x"], check=True, timeout=60)
                    cache.write_bytes(next(Path(d).glob("x*.png")).read_bytes())
            else:
                from PIL import Image
                im = Image.open(p).convert("RGB"); im.thumbnail((1000, 1400)); im.save(cache, "PNG")
        return FileResponse(cache, media_type="image/png")
    finally: c.close()

# ---------- people correcting and deciding ----------
FIELD_TYPES = {"supplier": str, "invoice_no": str, "po": str, "currency": str, "kind": str, "issue_date": "date", "due_date": "date", "subtotal": float, "tax": float, "total": float}
class ItemIn(BaseModel):
    description: str = Field(max_length=200); qty: float | None = None; unit_price: float | None = None; amount: float
class DocPatch(BaseModel):
    fields: dict | None = None
    items: list[ItemIn] | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)

@app.patch("/api/admin/docs/{did}", dependencies=[Depends(admin)])
def patch_doc(did: int, body: DocPatch):
    c = db.connect()
    try:
        d = c.execute("select * from documents where id=?", (did,)).fetchone()
        if not d: raise HTTPException(404, "No such document")
        if d["state"] != "pending": raise HTTPException(409, f"This document is already {d['state']}")
        meta = json.loads(d["meta"] or "{}"); changed = []
        for k, v in (body.fields or {}).items():
            if k not in FIELD_TYPES: raise HTTPException(400, f"Unknown field {k}")
            t = FIELD_TYPES[k]
            if v in ("", None): v = None
            elif t == "date":
                try: v = date.fromisoformat(str(v)).isoformat()
                except ValueError: raise HTTPException(422, f"{k} must be a date like 2026-10-31")
            elif t is float:
                try: v = round(float(v), 2)
                except (TypeError, ValueError): raise HTTPException(422, f"{k} must be a number")
            else: v = str(v).strip()[:200]
            if k == "kind" and v not in ("invoice", "credit_note"): raise HTTPException(422, "kind must be invoice or credit_note")
            if k == "currency" and v not in (None, "USD", "GBP", "EUR"): raise HTTPException(422, "currency must be USD, GBP or EUR")
            if v != d[k]:
                c.execute(f"update documents set {k}=? where id=?", (v, did)); changed.append(f"{k}: {d[k]} to {v}")
                meta.setdefault("conf", {})[k] = 1.0; meta.setdefault("how", {})[k] = "corrected by a person"
        if body.items is not None:
            old = [i["amount"] for i in c.execute("select amount from items where doc=? order by pos", (did,))]
            c.execute("delete from items where doc=?", (did,))
            for n, i in enumerate(body.items, 1): c.execute("insert into items(doc,pos,description,qty,unit_price,amount) values(?,?,?,?,?,?)", (did, n, i.description, i.qty, i.unit_price, round(i.amount, 2)))
            if old != [round(i.amount, 2) for i in body.items]: changed.append("line items")
        c.execute("update documents set meta=? where id=?", (json.dumps(meta), did))
        if changed: ingest.log(c, did, "Corrected " + "; ".join(changed))
        return {"ok": True, "status": ingest.revalidate(c, did), "changed": len(changed)}
    finally: c.close()

def decide(did, state, note=""):
    c = db.connect()
    try:
        d = c.execute("select status, state from documents where id=?", (did,)).fetchone()
        if not d: raise HTTPException(404, "No such document")
        if d["state"] != "pending": raise HTTPException(409, f"This document is already {d['state']}")
        if state == "approved" and d["status"] == "failed": raise HTTPException(409, "Nothing could be read from this document, correct the fields first")
        c.execute("update documents set state=?, reviewed=?, reviewer_note=? where id=?", (state, config.now().isoformat(timespec="seconds"), note[:500], did))
        ingest.log(c, did, state.capitalize() + (f": {note[:200]}" if note else "")); return {"ok": True, "state": state}
    finally: c.close()
class Decision(BaseModel): note: str = Field(default="", max_length=500)
@app.post("/api/admin/docs/{did}/approve", dependencies=[Depends(admin)])
def approve(did: int, body: Decision = Decision()): return decide(did, "approved", body.note)
@app.post("/api/admin/docs/{did}/reject", dependencies=[Depends(admin)])
def reject(did: int, body: Decision = Decision()): return decide(did, "rejected", body.note)

# ---------- export ----------
COLS = ["id", "supplier", "invoice_no", "kind", "issue_date", "due_date", "currency", "po", "subtotal", "tax", "total", "status", "state", "filename"]
def export_rows(state):
    c = db.connect()
    try:
        sql = "select " + ",".join(COLS) + " from documents where state!='rejected'" + (" and state=?" if state else ""); return [list(r) for r in c.execute(sql, (state,) if state else ())]
    finally: c.close()
def safe_cell(v):
    """Stops spreadsheet formula injection: a supplier name that starts with = + - @ would otherwise run as a formula."""
    return "'" + v if isinstance(v, str) and v[:1] in "=+-@\t\r" else v

@app.get("/api/admin/export.csv", dependencies=[Depends(admin)])
def export_csv(state: str = "approved"):
    buf = io.StringIO(); w = csv.writer(buf); w.writerow(COLS)
    for r in export_rows(state if state != "all" else ""): w.writerow([safe_cell(x) for x in r])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=documents.csv"})

@app.get("/api/admin/export.xlsx", dependencies=[Depends(admin)])
def export_xlsx(state: str = "approved"):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook(); ws = wb.active; ws.title = "Documents"; ws.append(COLS)
    for cell in ws[1]: cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="0F766E")
    for r in export_rows(state if state != "all" else ""): ws.append([safe_cell(x) for x in r])
    for col, w in zip("ABCDEFGHIJKLMN", (6, 28, 16, 12, 12, 12, 9, 12, 12, 10, 12, 9, 10, 36)): ws.column_dimensions[col].width = w
    out = io.BytesIO(); wb.save(out)
    return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=documents.xlsx"})

# ---------- supplier portal statements, and reconciling them with what was extracted ----------
class Stmt(BaseModel):
    ref: str = Field(max_length=80); supplier: str = Field(max_length=120); invoice_no: str = Field(max_length=60); amount: float; stmt_date: str | None = Field(default=None, max_length=20); file: str | None = Field(default=None, max_length=200)
@app.post("/api/inbound/statements", dependencies=[Depends(door)])
def statements(rows: list[Stmt]):
    if len(rows) > 500: raise HTTPException(413, "Too many rows")
    c = db.connect(); new = 0
    try:
        for s in rows:
            new += c.execute("insert into statements(ref,supplier,invoice_no,amount,stmt_date,file,scraped) values(?,?,?,?,?,?,?) on conflict(ref) do update set amount=excluded.amount, stmt_date=excluded.stmt_date",
                             (s.ref, s.supplier, s.invoice_no, s.amount, s.stmt_date, s.file, config.now().isoformat(timespec="seconds"))).rowcount and 1
        return {"ok": True, "rows": len(rows)}
    finally: c.close()

@app.get("/api/admin/reconcile", dependencies=[Depends(admin)])
def reconcile():
    n = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower()); c = db.connect()
    try:
        docs_ = {(n(r["supplier"]), n(r["invoice_no"])): dict(r) for r in c.execute("select id, supplier, invoice_no, total, state, status from documents where state!='rejected'")}
        out, seen = [], set()
        for s in c.execute("select * from statements order by supplier, invoice_no"):
            key = (n(s["supplier"]), n(s["invoice_no"])); d = docs_.get(key); seen.add(key)
            if not d: out.append({**dict(s), "result": "missing", "doc": None, "extracted": None, "why": "On the portal statement but no document received"}); continue
            diff = round((d["total"] or 0) - s["amount"], 2)
            out.append({**dict(s), "result": "match" if abs(diff) < 0.005 else "mismatch", "doc": d["id"], "extracted": d["total"], "why": "Amounts agree" if abs(diff) < 0.005 else f"Document total differs by {diff:+.2f}"})
        for key, d in docs_.items():
            if key not in seen and d["invoice_no"]: out.append({"ref": None, "supplier": d["supplier"], "invoice_no": d["invoice_no"], "amount": None, "result": "unlisted", "doc": d["id"], "extracted": d["total"], "why": "Document received but not on any statement"})
        return {"rows": out, "counts": {k: sum(1 for r in out if r["result"] == k) for k in ("match", "mismatch", "missing", "unlisted")}}
    finally: c.close()

app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
