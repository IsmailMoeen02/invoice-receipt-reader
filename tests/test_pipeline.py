"""End to end on generated documents: PDF and scan in, structured result out."""
from decimal import Decimal
from app import pipeline

def test_digital_pdfs_read_correctly(docs):
    for name in ("classic", "modern", "receipt", "bill", "euro"):
        path, inv = docs[name]; r = pipeline.extract(path); f = r["fields"]
        assert r["source"] == "digital", name
        assert f["total"]["value"] == float(inv["total"]), name
        assert f["subtotal"]["value"] == float(inv["subtotal"]), name
        if f["issue_date"]["conf"] >= .8: assert f["issue_date"]["value"] == inv["issue"].isoformat(), name   # an ambiguous 03/09/2026 must be flagged, never silently guessed
        assert len(r["items"]) == len(inv["items"]), name
        assert r["status"] in ("ready", "review") and (r["status"] == "ready" or "issue_date" in r["low_confidence"]), name

def test_scan_goes_through_ocr_and_is_read(docs):
    path, inv = docs["scan"]; r = pipeline.extract(path)
    assert r["source"] == "image" and any("OCR" in n for n in r["notes"])
    assert r["fields"]["total"]["value"] == float(inv["total"]) and r["fields"]["invoice_no"]["value"] == inv["invoice_no"]

def test_european_numbers_and_dates(docs):
    path, inv = docs["euro"]; r = pipeline.extract(path)
    assert r["currency" if "currency" in r else "fields"]["currency"]["value"] == "EUR" and r["locale"]["number_format"] == "1.234,56"

def test_unreadable_file_fails_without_crashing(tmp_path):
    p = tmp_path / "x.pdf"; p.write_bytes(b"%PDF-1.4\n garbage"); r = pipeline.extract(p)
    assert r["status"] == "failed" and r["error"]

def test_blank_page_is_failed_not_invented(tmp_path):
    from PIL import Image
    p = tmp_path / "blank.png"; Image.new("RGB", (900, 1200), "white").save(p); r = pipeline.extract(p)
    assert r["status"] == "failed"

def test_duplicate_lookup_forces_review(docs):
    path, _ = docs["classic"]; r = pipeline.extract(path, duplicate_lookup=lambda s, n: 99)
    assert r["status"] == "review" and any(c["name"] == "not a duplicate" and not c["ok"] for c in r["checks"])

def test_llm_cannot_break_a_good_read(docs):
    path, inv = docs["classic"]
    class Evil:
        def fill(self, text, fields): fields["total"].update(value=1.0, conf=.7); return ["total"]
    r = pipeline.extract(path, llm=Evil())   # whatever fills in, the checks still run and catch it
    assert r["status"] == "review"
