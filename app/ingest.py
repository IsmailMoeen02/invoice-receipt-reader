"""Take a file in, make sure it is what it says it is, extract it, store it."""
from __future__ import annotations
import hashlib, json, re, subprocess, uuid
from pathlib import Path
from . import config, db, llm, ocr, pipeline, validate

class Rejected(ValueError): pass
MIME = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg"}
def safe_name(n: str) -> str:
    n = Path(n or "document").name; n = re.sub(r"[^A-Za-z0-9._ -]", "_", n)[:120].strip(" .") or "document"; return n

def check_upload(data: bytes, filename: str):
    if not data: raise Rejected("The file is empty")
    if len(data) > config.MAX_UPLOAD: raise Rejected(f"The file is larger than {config.MAX_UPLOAD // (1024 * 1024)} MB")
    kind = ocr.kind_of(data)
    if not kind: raise Rejected("Only PDF, PNG and JPG files are accepted (the file contents do not look like one)")
    return kind

def page_count(path: Path, kind: str) -> int:
    if kind != "pdf": return 1
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(path)).pages)
    except Exception: raise Rejected("The PDF could not be opened")

def log(c, doc, text): c.execute("insert into activity(doc,text,ts) values(?,?,?)", (doc, text, config.now().isoformat(timespec="seconds")))

def _dup(c, supplier, number, exclude=None):
    if not supplier or not number: return None
    n = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    for r in c.execute("select id, supplier, invoice_no from documents where state!='rejected' and invoice_no is not null" + (" and id!=%d" % exclude if exclude else "")):
        if r["supplier"] and n(r["supplier"]) == n(supplier) and n(r["invoice_no"]) == n(number): return r["id"]
    return None

def store(c, doc_id, r):
    f = r["fields"]; g = lambda k: f[k]["value"] if f else None
    meta = {"conf": {k: v["conf"] for k, v in f.items()}, "how": {k: v["how"] for k, v in f.items()}, "text": {k: v["text"] for k, v in f.items()}, "checks": r["checks"], "notes": r["notes"],
            "low": r.get("low_confidence", []), "locale": r.get("locale"), "error": r.get("error")}
    c.execute("""update documents set supplier=?,invoice_no=?,issue_date=?,due_date=?,currency=?,po=?,terms=?,kind=?,subtotal=?,tax=?,total=?,status=?,overall=?,meta=?,engine=?,pages=? where id=?""",
              (g("supplier"), g("invoice_no"), g("issue_date"), g("due_date"), g("currency"), g("po"), g("terms"), r.get("kind") or "invoice", g("subtotal"), g("tax"), g("total"), r["status"], r.get("overall", 0),
               json.dumps(meta), r.get("source"), r.get("pages"), doc_id))
    c.execute("delete from items where doc=?", (doc_id,))
    for i, it in enumerate(r["items"], 1): c.execute("insert into items(doc,pos,description,qty,unit_price,amount) values(?,?,?,?,?,?)", (doc_id, i, it["description"], it.get("qty"), it.get("unit_price"), it["amount"]))

def process(data: bytes, filename: str, source="upload", portal_ref=None) -> dict:
    kind = check_upload(data, filename); sha = hashlib.sha256(data).hexdigest(); c = db.connect()
    try:
        row = c.execute("select id, status from documents where sha=?", (sha,)).fetchone()
        if row: return {"id": row["id"], "duplicate": True, "status": row["status"], "note": "this exact file was already received"}
        stored = f"{uuid.uuid4().hex}.{kind}"; path = config.FILES_DIR / stored; path.write_bytes(data)
        try: pages = page_count(path, kind)
        except Rejected: path.unlink(missing_ok=True); raise
        if pages > config.MAX_PAGES: path.unlink(missing_ok=True); raise Rejected(f"The document has {pages} pages; the limit is {config.MAX_PAGES}")
        cur = c.execute("insert into documents(filename,stored,sha,source,mime,size,pages,created,portal_ref,status) values(?,?,?,?,?,?,?,?,?,'review')",
                        (safe_name(filename), stored, sha, source, MIME[kind], len(data), pages, config.now().isoformat(timespec="seconds"), portal_ref)); did = cur.lastrowid
        r = pipeline.extract(path, llm=llm.make(), duplicate_lookup=lambda s, n: _dup(c, s, n, did)); store(c, did, r)
        log(c, did, f"Received from {source}; read as {r.get('source') or 'unreadable'}; status {r['status']}")
        return {"id": did, "duplicate": False, "status": r["status"], "supplier": r["fields"].get("supplier", {}).get("value"), "invoice_no": r["fields"].get("invoice_no", {}).get("value"),
                "total": r["fields"].get("total", {}).get("value"), "overall": r.get("overall")}
    finally: c.close()

def revalidate(c, doc_id):
    """After a person edits fields: recompute the checks. The status becomes ready only if every check passes."""
    d = c.execute("select * from documents where id=?", (doc_id,)).fetchone(); meta = json.loads(d["meta"] or "{}")
    items = [dict(i) for i in c.execute("select * from items where doc=? order by pos", (doc_id,))]
    flat = {k: d[k] for k in ("supplier", "invoice_no", "issue_date", "due_date", "po", "kind", "subtotal", "tax", "total")}; flat["items"] = items
    checks = validate.checks(flat, _dup(c, d["supplier"], d["invoice_no"], doc_id)); meta["checks"] = checks
    status = "ready" if all(x["ok"] for x in checks) else "review"
    c.execute("update documents set meta=?, status=? where id=?", (json.dumps(meta), status, doc_id)); return status
