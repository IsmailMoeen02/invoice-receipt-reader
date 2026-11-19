from app import validate
from app.parse import F

def fs(sub, tax, tot, items):
    return {"subtotal": F(sub, .9), "tax": F(tax, .9), "total": F(tot, .9), "items": [{"amount": a} for a in items]}

def test_consistent_numbers_get_higher_confidence():
    d = fs(50.0, 4.0, 54.0, [30.0, 20.0]); validate.reconcile(d); assert d["total"].conf >= .95

def test_repairs_a_misread_tax_from_total_and_subtotal():
    d = fs(50.0, 435.1, 54.0, [30.0, 20.0]); notes = validate.reconcile(d)
    assert d["tax"].value == 4.0 and notes

def test_repairs_a_misread_total():
    d = fs(50.0, 4.0, 540.0, [30.0, 20.0]); validate.reconcile(d); assert d["total"].value == 54.0

def test_repairs_a_misread_subtotal_with_items_as_anchor():
    d = fs(5.0, 4.0, 54.0, [30.0, 20.0]); validate.reconcile(d); assert d["subtotal"].value == 50.0

def test_missing_total_is_computed_with_low_confidence():
    d = fs(50.0, 4.0, None, [30.0, 20.0]); validate.reconcile(d); assert d["total"].value == 54.0 and d["total"].conf < .8

def test_cannot_repair_when_nothing_agrees():
    d = fs(51.0, 7.0, 99.0, [30.0, 20.0]); validate.reconcile(d); assert (d["subtotal"].value, d["tax"].value, d["total"].value) == (51.0, 7.0, 99.0)

def base(**o):
    r = {"supplier": "A", "invoice_no": "1", "issue_date": "2026-09-01", "due_date": "2026-10-01", "kind": "invoice", "subtotal": 50.0, "tax": 4.0, "total": 54.0, "items": [{"amount": 30.0}, {"amount": 20.0}]}
    r.update(o); return r
def failed(r, dup=None): return [c["name"] for c in validate.checks(r, dup) if not c["ok"]]

def test_clean_invoice_passes_everything(): assert failed(base()) == []
def test_items_not_adding_up(): assert "line items add up to the subtotal" in failed(base(items=[{"amount": 30.0}, {"amount": 25.0}]))
def test_total_not_matching(): assert "subtotal plus tax equals the total" in failed(base(total=60.0))
def test_implausible_tax_rate(): assert "tax rate is plausible" in failed(base(tax=40.0, total=90.0))
def test_due_before_issue(): assert "due date is not before the issue date" in failed(base(due_date="2026-08-01"))
def test_missing_required(): assert "invoice no found" in failed(base(invoice_no=None))
def test_credit_note_must_be_negative(): assert "credit note total is negative" in failed(base(kind="credit_note"))
def test_invoice_must_not_be_negative(): assert "invoice total is not negative" in failed(base(subtotal=-50.0, tax=-4.0, total=-54.0, items=[{"amount": -50.0}]))
def test_duplicate_flagged(): assert "not a duplicate" in failed(base(), dup=7)
def test_no_items_flagged(): assert "line items found" in failed(base(items=[], subtotal=None))
