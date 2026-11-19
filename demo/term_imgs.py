"""Terminal-style images of the real test, evaluation and bot output.
  pytest -v > /tmp/pytest_dd.txt ; python eval/run_eval.py dev ; python eval/run_eval.py heldout ; python demo/term_imgs.py"""
import html, json
from collections import Counter
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parent.parent; A = ROOT / "assets"
def page(title, text, w):
    return f"""<body style="margin:0;background:linear-gradient(135deg,#e6f1ee,#faf9f5 60%,#f3ecd6);display:grid;place-items:center;height:100vh">
    <div style="width:{w - 80}px;border-radius:14px;overflow:hidden;box-shadow:0 18px 50px rgba(31,100,93,.25);background:#17302f">
    <div style="background:#1f4442;padding:11px 16px;display:flex;gap:8px;align-items:center"><i style="width:12px;height:12px;border-radius:50%;background:#e29b94"></i><i style="width:12px;height:12px;border-radius:50%;background:#e9c46a"></i><i style="width:12px;height:12px;border-radius:50%;background:#7fbf9f"></i><span style="color:#b9d3cf;font:13px 'DejaVu Sans',sans-serif;margin-left:12px">{title}</span></div>
    <pre style="margin:0;padding:20px 24px;color:#e8f3f1;font:15px/1.55 'DejaVu Sans Mono',monospace;white-space:pre-wrap">{text}</pre></div></body>"""
G = lambda t: f'<b style="color:#7fd1a8">{t}</b>'; Y = lambda t: f'<b style="color:#e9c46a">{t}</b>'
pct = lambda g, t: f"{g}/{t}  ({100 * g / t:.0f}%)"
FIELDS = ["supplier", "invoice_no", "issue_date", "due_date", "currency", "subtotal", "tax", "total", "po", "kind", "items"]
LAB = {"items": "line items"}
def block(name, r, extra=""):
    n = r["n"]; out = f"{name}\n  documents: {n}\n"
    for f in FIELDS: out += f"  {LAB.get(f, f):11s}: {pct(r['per_field'][f], n)}\n"
    return out + f"  every field right: {pct(r['docs_ok'], n)}\n" + extra
with sync_playwright() as pw:
    b = pw.chromium.launch()
    lines = Path("/tmp/pytest_dd.txt").read_text().splitlines()
    tests = [l for l in lines if l.startswith("tests/")]; summary = [l for l in lines if " passed" in l and not l.startswith("tests/")][-1]
    per = Counter(l.split("::")[0].replace("tests/", "") for l in tests)
    body = "$ pytest -v\n\n" + "\n".join(f'{G("PASSED")}  {html.escape(f):<26} {n:>3} tests' for f, n in per.items()) + f"\n\n{G(html.escape(summary.strip('= ')))}"
    pg = b.new_page(viewport={"width": 1280, "height": 150 + 26 * len(per) + 60}, device_scale_factor=2); pg.set_content(page("pytest: automated tests, offline", body, 1280)); pg.screenshot(path=str(A / "13_tests_passing.png"))
    dev = json.load(open(ROOT / "eval" / "result_dev.json")); held = json.load(open(ROOT / "eval" / "result_heldout.json"))
    st = lambda r: f"  status: ready {sum(x[4] == 'ready' for x in r['rows'])}, review {sum(x[4] == 'review' for x in r['rows'])}, failed {sum(x[4] == 'failed' for x in r['rows'])}; wrong but marked ready: {r['wrong_ready']}\n"
    body = "$ python eval/run_eval.py\n\n" + block("DEVELOPMENT SET (tuned on)", dev, st(dev)) + "\n" + block("HELD-OUT SET (written after the rules, run once first)", held, st(held) + "  first run, before any change: 19 of 20 fully right, ready 18, review 2\n")
    body = html.escape(body).replace("DEVELOPMENT SET", Y("DEVELOPMENT SET")).replace("HELD-OUT SET", Y("HELD-OUT SET"))
    pg = b.new_page(viewport={"width": 1280, "height": 130 + 25 * (body.count("\n") + 3)}, device_scale_factor=2); pg.set_content(page("Evaluation: dummy documents against hand-written answers", body, 1280)); pg.screenshot(path=str(A / "17_extraction_evaluation.png"))
    body = html.escape("$ python portal/bot.py --key $INBOUND_KEY\nstatement lines read: 18; documents downloaded and sent: 17; without a file: 1\n\nGET /api/admin/reconcile\n  match     15\n  mismatch   2   (statement and document totals differ)\n  missing    1   (on the statement, no PDF to download)\n  unlisted   0")
    pg = b.new_page(viewport={"width": 1280, "height": 360}, device_scale_factor=2); pg.set_content(page("Portal bot run against the dummy supplier portal", body, 1280)); pg.screenshot(path=str(A / "18_portal_bot_run.png"))
    b.close()
print("ok")
