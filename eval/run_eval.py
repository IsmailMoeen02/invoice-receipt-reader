"""Scores the extraction against hand-written truth. Usage: python eval/run_eval.py dev|heldout [--show]
A field is right when it matches exactly (money to the cent, dates exactly, text ignoring case and punctuation). A document is right when every field is right."""
import json, re, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from app import pipeline

FIELDS = ["supplier", "invoice_no", "issue_date", "due_date", "currency", "subtotal", "tax", "total", "po", "kind"]
norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower()) if s is not None else None
def same(f, a, b):
    if f in ("subtotal", "tax", "total"): return a is not None and abs(float(a) - float(b)) < 0.005
    if f in ("supplier", "invoice_no", "po"): return norm(a) == norm(b)
    return a == b

def run(name, show=False):
    truth = json.loads((ROOT / "data" / f"{name}_truth.json").read_text()); rows = []; t0 = time.time()
    for fn, tr in truth.items():
        r = pipeline.extract(ROOT / "data" / "docs" / name / fn); got = {k: v["value"] for k, v in r["fields"].items()}; got["kind"] = r.get("kind")
        res = {f: same(f, got.get(f), tr[f if f != "issue_date" else "issue_date"]) for f in FIELDS}
        ia = sorted(i["amount"] for i in r["items"]); ta = sorted(tr["item_amounts"]); res["items"] = len(ia) == len(ta) and all(abs(a - b) < .005 for a, b in zip(ia, ta))
        scan = "scan" in fn; rows.append((fn, tr["layout"], scan, res, r, got, tr))
    n = len(rows); per = {f: sum(r[3][f] for r in rows) for f in FIELDS + ["items"]}; docs_ok = sum(all(r[3].values()) for r in rows)
    print(f"\n== {name}: {n} documents in {time.time() - t0:.0f}s")
    for f, v in per.items(): print(f"  {f:10s} {v:3d}/{n}  {v / n:5.1%}")
    print(f"  all fields right: {docs_ok}/{n}  ({docs_ok / n:.0%})")
    for lab, sel in (("digital", lambda r: not r[2]), ("scanned", lambda r: r[2])):
        sub = [r for r in rows if sel(r)]; print(f"  {lab}: {sum(all(r[3].values()) for r in sub)}/{len(sub)} fully right")
    # status quality: a "ready" document must be right, a wrong one should not be "ready"
    ready = [r for r in rows if r[4]["status"] == "ready"]; wrong_ready = [r for r in ready if not all(r[3].values())]
    print(f"  status: ready {len(ready)}, review {sum(r[4]['status'] == 'review' for r in rows)}, failed {sum(r[4]['status'] == 'failed' for r in rows)}; wrong but marked ready: {len(wrong_ready)}")
    wrong_review = [r for r in rows if not all(r[3].values()) and r[4]["status"] != "ready"]; print(f"  wrong documents caught for review: {len(wrong_review)} of {sum(not all(r[3].values()) for r in rows)}")
    if show:
        for fn, lay, scan, res, r, got, tr in rows:
            bad = [f for f, ok in res.items() if not ok]
            if bad:
                print(f"\n  {fn} [{r['status']}]")
                for f in bad: print(f"     {f}: got {got.get(f) if f != 'items' else sorted(i['amount'] for i in r['items'])} want {tr.get(f) if f != 'items' else sorted(tr['item_amounts'])}")
    return {"name": name, "n": n, "per_field": per, "docs_ok": docs_ok, "wrong_ready": len(wrong_ready), "rows": [(r[0], r[1], r[2], r[3], r[4]["status"]) for r in rows]}

if __name__ == "__main__":
    out = run(sys.argv[1], "--show" in sys.argv)
    (ROOT / "eval" / f"result_{sys.argv[1]}.json").write_text(json.dumps(out, indent=1, default=str))
