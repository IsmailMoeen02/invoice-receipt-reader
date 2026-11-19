"""A dummy supplier portal. It exists so the extraction tool has something realistic to log in to: a login form, a paginated statements table and per-row PDF downloads.
Not the real thing and not connected to anything. Login: buyer / portal-demo."""
import hashlib, hmac, html, json, os, secrets
from pathlib import Path
from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse

ROOT = Path(__file__).resolve().parent; ROWS = json.loads((ROOT / "data.json").read_text()); PER_PAGE = 6
USER, PW = "buyer", os.environ.get("PORTAL_PASSWORD", "portal-demo"); SESSIONS = set()
app = FastAPI(docs_url=None, redoc_url=None); e = html.escape
CSS = """body{font-family:Inter,system-ui,sans-serif;background:#f7f6f2;color:#243b3a;margin:0}main{max-width:900px;margin:40px auto;padding:0 20px}
h1{font-size:22px;margin:0 0 4px}.sub{color:#6b7f7d;margin:0 0 22px}table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e4e8e3;border-radius:10px}
th,td{padding:10px 12px;border-bottom:1px solid #e4e8e3;text-align:left;font-size:14px}th{background:#eef3ef;color:#4b6361;font-weight:600}td.n{text-align:right}
a{color:#0f766e}.pg{margin-top:16px;display:flex;gap:8px;align-items:center}.pg a,.pg span{padding:6px 12px;border:1px solid #e4e8e3;border-radius:8px;background:#fff;text-decoration:none}
form{background:#fff;border:1px solid #e4e8e3;border-radius:12px;padding:24px;max-width:340px;margin:80px auto}input{width:100%;padding:10px;margin:6px 0 14px;border:1px solid #cfd8d3;border-radius:8px;box-sizing:border-box}
button{background:#0f766e;color:#fff;border:0;border-radius:8px;padding:10px 16px;font-size:14px;cursor:pointer}.top{background:#fff;border-bottom:1px solid #e4e8e3;padding:14px 20px;font-weight:600;color:#0f766e}"""
def page(body, title="Supplier Portal"): return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>{e(title)}</title><style>{CSS}</style><div class=top>Supplier Portal (dummy)</div>{body}")
def authed(r: Request): return r.cookies.get("sid") in SESSIONS

@app.get("/", response_class=HTMLResponse)
def home(r: Request): return RedirectResponse("/statements" if authed(r) else "/login")
@app.get("/login", response_class=HTMLResponse)
def login_form(): return page("<form method=post action=/login><h1>Sign in</h1><p class=sub>Statements and invoices</p><label>User</label><input name=user id=user autocomplete=off><label>Password</label><input name=pw id=pw type=password><button id=go>Sign in</button></form>")
@app.post("/login")
def login(user: str = Form(...), pw: str = Form(...)):
    if not (hmac.compare_digest(user, USER) and hmac.compare_digest(pw, PW)): return page("<form method=post action=/login><h1>Sign in</h1><p style='color:#c8615a'>Wrong user or password</p><label>User</label><input name=user><label>Password</label><input name=pw type=password><button>Sign in</button></form>")
    sid = secrets.token_urlsafe(24); SESSIONS.add(sid); r = RedirectResponse("/statements", 303); r.set_cookie("sid", sid, httponly=True, samesite="lax"); return r
@app.get("/statements", response_class=HTMLResponse)
def statements(r: Request, p: int = 1):
    if not authed(r): return RedirectResponse("/login")
    pages = (len(ROWS) + PER_PAGE - 1) // PER_PAGE; p = max(1, min(p, pages)); chunk = ROWS[(p - 1) * PER_PAGE: p * PER_PAGE]
    sym = {"USD": "$", "GBP": "£", "EUR": "€"}
    trs = "".join(f"<tr><td>{e(x['ref'])}</td><td>{e(x['supplier'])}</td><td>{e(x['invoice_no'])}</td><td>{e(x['date'])}</td><td class=n>{sym[x['currency']]}{x['amount']:,.2f}</td><td>" + (f"<a class=dl href='/download/{e(x['file'])}'>Download PDF</a>" if x["file"] else "<span style='color:#6b7f7d'>not available</span>") + "</td></tr>" for x in chunk)
    nav = (f"<a class=prev href='/statements?p={p - 1}'>Previous</a>" if p > 1 else "") + f"<span>Page {p} of {pages}</span>" + (f"<a class=next href='/statements?p={p + 1}'>Next</a>" if p < pages else "")
    return page(f"<main><h1>Account statement</h1><p class=sub>Fernhill Bakery Group, {len(ROWS)} lines</p><table id=stmt><thead><tr><th>Ref</th><th>Supplier</th><th>Invoice</th><th>Date</th><th>Amount</th><th>Document</th></tr></thead><tbody>{trs}</tbody></table><div class=pg>{nav}</div></main>", "Statements")
@app.get("/download/{name}")
def download(name: str, r: Request):
    if not authed(r): raise HTTPException(401)
    if name not in {x["file"] for x in ROWS if x["file"]}: raise HTTPException(404)
    return FileResponse(ROOT / "files" / name, filename=name)
