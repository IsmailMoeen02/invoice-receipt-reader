"""One call: file in, structured result out. Result has fields (value + confidence + where it came from), items, checks, status and notes."""
from __future__ import annotations
from decimal import Decimal
from . import ocr, parse, validate

FIELDS = ["supplier", "invoice_no", "issue_date", "due_date", "currency", "po", "terms", "subtotal", "tax", "total"]
REVIEW_BELOW = 0.80

def _val(f):
    v = f.value
    if hasattr(v, "isoformat"): return v.isoformat()
    if isinstance(v, Decimal): return float(v)
    return v

def extract(path, llm=None, duplicate_lookup=None) -> dict:
    try: doc = ocr.read(path)
    except Exception as e: return {"status": "failed", "error": str(e)[:200], "fields": {}, "items": [], "checks": [], "notes": [], "source": None}
    p = parse.parse(doc); notes = list(doc.notes)
    notes += validate.reconcile(p)
    fields = {k: {"value": _val(p[k]), "conf": p[k].conf, "how": p[k].how, "text": p[k].src} for k in FIELDS}
    kind = p["kind"].value
    if llm is not None:
        try:
            changed = llm.fill(doc.text, fields)
            notes += [f"language model filled {c}" for c in changed]
        except Exception as e: notes.append(f"language model skipped: {str(e)[:80]}")
    flat = {k: fields[k]["value"] for k in FIELDS}; flat["kind"] = kind; flat["items"] = p["items"]
    dup = duplicate_lookup(flat["supplier"], flat["invoice_no"]) if duplicate_lookup and flat["supplier"] and flat["invoice_no"] else None
    checks = validate.checks(flat, dup)
    confs = [fields[k]["conf"] for k in ("supplier", "invoice_no", "issue_date", "subtotal", "tax", "total") if fields[k]["value"] is not None]
    low = [k for k in ("supplier", "invoice_no", "issue_date", "total") if fields[k]["value"] is None or fields[k]["conf"] < REVIEW_BELOW]
    failed_checks = [c for c in checks if not c["ok"]]
    if fields["total"]["value"] is None and fields["invoice_no"]["value"] is None: status = "failed"
    elif failed_checks or low: status = "review"
    else: status = "ready"
    overall = round(min(confs) if confs else 0.0, 2)
    return {"status": status, "kind": kind, "fields": fields, "items": p["items"], "checks": checks, "low_confidence": low, "overall": overall, "notes": notes, "source": doc.source, "pages": doc.pages,
            "locale": p["locale"].value}
