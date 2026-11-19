"""Checks on an extracted invoice: arithmetic, dates, required fields. Repairs the obvious single-digit OCR slips by using the other numbers on the page."""
from __future__ import annotations
from decimal import Decimal
C = lambda x: Decimal(str(x)).quantize(Decimal("0.01"))
REQUIRED = ["supplier", "invoice_no", "issue_date", "total"]

def reconcile(d: dict):
    """Use any two consistent numbers to fix the third. d holds F objects for subtotal, tax, total and a list of items."""
    notes = []; sub, tax, tot = d["subtotal"], d["tax"], d["total"]; isum = sum((C(i["amount"]) for i in d["items"]), Decimal("0")) if d["items"] else None
    s = C(sub.value) if sub.ok() else None; t = C(tax.value) if tax.ok() else None; g = C(tot.value) if tot.ok() else None
    ok = lambda a, b, c: a is not None and b is not None and c is not None and abs(a + b - c) <= Decimal("0.02")
    if ok(s, t, g):
        if isum is not None and abs(isum - s) <= Decimal("0.02"): sub.conf = max(sub.conf, .97); tax.conf = max(tax.conf, .96); tot.conf = max(tot.conf, .97)
        return notes
    # which pair is trustworthy? try items sum as the anchor
    if isum is not None and g is not None and t is not None and abs(isum + t - g) <= Decimal("0.02"):
        if s != isum: notes.append(f"subtotal {s} did not match; set to the sum of line items {isum}"); sub.value = float(isum); sub.conf = .85; sub.how = "repaired from items"
        return notes
    if isum is not None and s is not None and abs(isum - s) <= Decimal("0.02") and g is not None:
        plaus = lambda x: s != 0 and abs(x / s) <= Decimal("0.30")      # a tax rate above 30 percent is not believable
        newt = g - s if g is not None else None; newg = s + t if t is not None else None
        given_ok = t is not None and plaus(t); implied_ok = newt is not None and plaus(newt)
        if t is None or (implied_ok and not given_ok):
            notes.append(f"tax {t} did not fit; set to total minus subtotal {newt}"); tax.value = float(newt); tax.conf = .8; tax.how = "repaired from total and subtotal"
        elif given_ok and not implied_ok:
            notes.append(f"total {g} did not fit; set to subtotal plus tax {newg}"); tot.value = float(newg); tot.conf = .8; tot.how = "repaired from subtotal and tax"
        else:
            tax.conf = min(tax.conf, .5); tot.conf = min(tot.conf, .5); notes.append("tax and total disagree and both look possible, please check")
        return notes
    if s is None and isum is not None: sub.value = float(isum); sub.conf = .6; sub.how = "sum of items"; notes.append("subtotal missing, used sum of line items")
    if t is None and s is not None and g is not None: tax.value = float(g - s); tax.conf = .6; tax.how = "total minus subtotal"
    if g is None and s is not None and t is not None: tot.value = float(s + t); tot.conf = .6; tot.how = "subtotal plus tax"
    return notes

def checks(r: dict, duplicate_of=None) -> list:
    """List of {name, ok, detail}. A failed check puts the document in the review queue."""
    out = []; add = lambda n, ok, det="": out.append({"name": n, "ok": bool(ok), "detail": det})
    for f in REQUIRED: add(f"{f.replace('_', ' ')} found", r.get(f) not in (None, ""), "")
    items = r.get("items") or []; sub, tax, tot = r.get("subtotal"), r.get("tax"), r.get("total")
    if items and sub is not None:
        isum = sum((C(i["amount"]) for i in items), Decimal("0")); add("line items add up to the subtotal", abs(isum - C(sub)) <= Decimal("0.02"), f"items {isum}, subtotal {C(sub)}")
    elif not items: add("line items found", False, "no rows read from the table")
    if None not in (sub, tax, tot): add("subtotal plus tax equals the total", abs(C(sub) + C(tax) - C(tot)) <= Decimal("0.02"), f"{C(sub)} + {C(tax)} vs {C(tot)}")
    if sub not in (None, 0) and tax is not None:
        rate = abs(C(tax) / C(sub)); add("tax rate is plausible", rate <= Decimal("0.30"), f"{rate * 100:.1f}%")
    iss, due = r.get("issue_date"), r.get("due_date")
    if iss and due: add("due date is not before the issue date", due >= iss, f"{iss} to {due}")
    if iss: add("issue date is plausible", "2015-01-01" <= iss <= "2030-12-31", iss)
    if r.get("kind") == "credit_note" and tot is not None: add("credit note total is negative", C(tot) < 0, str(C(tot)))
    if r.get("kind") == "invoice" and tot is not None: add("invoice total is not negative", C(tot) >= 0, str(C(tot)))
    if duplicate_of: add("not a duplicate", False, f"same supplier and number as document {duplicate_of}")
    return out
