import json
from app import llm

TEXT = "Acme Paper Ltd\nInvoice No: AP-10442\nDate: 02 Sep 2026\nTotal Due $54.00"
def fields(**vals):
    base = {k: {"value": None, "conf": 0.0, "how": "", "text": ""} for k in llm.ASK}; base["currency"] = {"value": "USD", "conf": .9}
    for k, v in vals.items(): base[k]["value"] = v; base[k]["conf"] = .95
    return base

def run(reply, f):
    return llm.GroqFiller(call=lambda p: json.dumps(reply)).fill(TEXT, f)

def test_accepts_quoted_values_and_reads_them_with_the_rules():
    f = fields(); changed = run({"invoice_no": {"as_written": "AP-10442"}, "issue_date": {"as_written": "02 Sep 2026"}, "total": {"as_written": "$54.00"}}, f)
    assert set(changed) == {"invoice_no", "issue_date", "total"} and f["issue_date"]["value"] == "2026-09-02" and f["total"]["value"] == 54.0

def test_drops_a_value_that_is_not_in_the_text():
    f = fields(); changed = run({"total": {"as_written": "$540.00"}, "invoice_no": {"as_written": "AP-99999"}}, f)
    assert changed == [] and f["total"]["value"] is None and f["invoice_no"]["value"] is None

def test_model_cannot_supply_a_value_without_a_quote():
    f = fields(); assert run({"total": 54.0, "invoice_no": "AP-10442"}, f) == []

def test_only_asks_about_missing_or_weak_fields():
    f = fields(**{k: ("x" if k not in ("total",) else None) for k in llm.ASK}); calls = []
    llm.GroqFiller(call=lambda p: calls.append(p) or "{}").fill(TEXT, f); assert "total" in calls[0] and "invoice_no" not in calls[0].split("Fields:")[1].split(".")[0]

def test_no_call_when_everything_is_confident():
    f = fields(**{k: "x" for k in llm.ASK}); calls = []; llm.GroqFiller(call=lambda p: calls.append(1)).fill(TEXT, f); assert calls == []

def test_off_without_a_key(monkeypatch):
    monkeypatch.setattr(llm.config, "GROQ_API_KEY", ""); assert llm.make() is None
