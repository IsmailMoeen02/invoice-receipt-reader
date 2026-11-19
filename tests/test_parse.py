from datetime import date
from decimal import Decimal
from app import parse, ocr

def doc(*rows):
    lines = []; y = 20
    for r in rows:
        words = []; x = 10
        for seg in r.split("   "):
            for w in seg.split():
                words.append(ocr.Word(w, x, y, x + 6 * len(w), y + 10)); x += 6 * len(w) + 4
            x += 220
        lines.append(ocr.Line(words, 0)); y += 18
    return ocr.Doc(lines, "digital", 1)

def test_money_us_and_eu():
    assert parse.money_in("$1,234.50")[0][0] == Decimal("1234.50")
    assert parse.money_in("1.234,50 €")[0][0] == Decimal("1234.50")
    assert parse.money_in("18,40 €")[0][0] == Decimal("18.40")
    assert parse.money_in("-$73.60")[0][0] == Decimal("-73.60")
    assert parse.money_in("£12.50")[0][1] == "GBP"

def test_money_ignores_dates_and_ids():
    assert parse.money_in("Date 14.10.2026") == []
    assert parse.money_in("Invoice INV-2026-801") == []
    assert parse.money_in("PO-4821") == []

def test_dates_day_first_vs_month_first():
    assert parse.dates_in("03/04/2026", True)[0][0] == date(2026, 4, 3)
    assert parse.dates_in("03/04/2026", False)[0][0] == date(2026, 3, 4)
    assert parse.dates_in("25/04/2026", False)[0][0] == date(2026, 4, 25)   # 25 cannot be a month
    assert parse.dates_in("14.10.2026", False)[0][0] == date(2026, 10, 14)
    assert parse.dates_in("Oct 3, 2026", False)[0][0] == date(2026, 10, 3)
    assert parse.dates_in("02 Sep 2026", False)[0][0] == date(2026, 9, 2)
    assert parse.dates_in("2026-09-02", False)[0][0] == date(2026, 9, 2)

def test_impossible_date_is_dropped():
    assert parse.dates_in("31/02/2026", True) == []

def basic(**over):
    rows = ["Acme Paper Ltd   INVOICE", "Invoice No: AP-10442", "Date: 02 Sep 2026", "Due Date: 02 Oct 2026", "Description   Qty   Unit Price   Amount",
            "Box files 10 $3.00 $30.00", "Stapler 2 $10.00 $20.00", "Subtotal $50.00", "Sales tax (8%) $4.00", "Total Due $54.00"]
    return doc(*rows)

def test_basic_fields():
    p = parse.parse(basic())
    assert p["supplier"].value == "Acme Paper Ltd" and p["invoice_no"].value == "AP-10442"
    assert p["issue_date"].value == date(2026, 9, 2) and p["due_date"].value == date(2026, 10, 2)
    assert (p["subtotal"].value, p["tax"].value, p["total"].value) == (Decimal("50.00"), Decimal("4.00"), Decimal("54.00"))
    assert [i["amount"] for i in p["items"]] == [30.0, 20.0] and p["currency"].value == "USD"

def test_subtotal_not_mistaken_for_total():
    p = parse.parse(basic()); assert p["total"].value == Decimal("54.00") and p["subtotal"].value == Decimal("50.00")

def test_label_variants_for_number_and_dates():
    for no_label in ("Invoice #", "Bill No.", "Inv #", "Invoice Number", "Credit Note No:"):
        d = doc("Acme Paper Ltd", f"{no_label} AP-10442", "Issued 2026-09-02", "Pay by 2026-10-02", "Total $5.00")
        assert parse.parse(d)["invoice_no"].value == "AP-10442", no_label
    for due in ("Due Date", "Payment due", "Pay by", "Payable by", "Due by", "Pay before"):
        d = doc("Acme Paper Ltd", "Invoice No: A-1234", "Date: 2026-09-02", f"{due}: 2026-10-02", "Total $5.00")
        assert parse.parse(d)["due_date"].value == date(2026, 10, 2), due

def test_european_document():
    d = doc("Hof Bäckerei GmbH", "Rechnung Invoice Number RE-20551", "Invoice Date 14.10.2026", "Pos   Description   Qty   Price   Amount", "1 Mehl 2 18,40 € 36,80 €",
            "Net amount   1.036,80 €", "VAT 19 %   197,00 €", "Total (incl. VAT)   1.233,80 €")
    p = parse.parse(d)
    assert p["issue_date"].value == date(2026, 10, 14) and p["total"].value == Decimal("1233.80") and p["currency"].value == "EUR"
    assert p["locale"].value["number_format"] == "1.234,56"

def test_credit_note_negative_and_kind():
    d = doc("Acme Paper Ltd   CREDIT NOTE", "Credit No: CN-2201", "Date: 2026-09-02", "Box files -2 $3.00 -$6.00", "Subtotal -$6.00", "Sales tax -$0.48", "Credit Total -$6.48")
    p = parse.parse(d); assert p["kind"].value == "credit_note" and p["total"].value == Decimal("-6.48") and p["items"][0]["amount"] == -6.0

def test_multipage_header_and_page_lines_skipped():
    d = doc("Acme Paper Ltd   INVOICE", "Page 1 of 2", "Invoice No: AP-10442", "Date: 2026-09-02", "Description Qty Unit Price Amount", "Box 1 $3.00 $3.00", "Page 2 of 2", "Description Qty Unit Price Amount", "Pens 1 $2.00 $2.00",
            "Subtotal $5.00", "Total Due $5.00")
    assert [i["amount"] for i in parse.parse(d)["items"]] == [3.0, 2.0]

def test_missing_fields_come_back_empty_not_invented():
    p = parse.parse(doc("hello world", "nothing useful here"))
    assert not p["invoice_no"].ok() and not p["total"].ok() and not p["issue_date"].ok() and p["items"] == []

def test_stacked_label_layout():
    d = doc("Acme Paper Ltd", "INVOICE #   BILLED TO", "AP-9981   Fernhill Bakery Group", "Total $5.00")
    assert parse.parse(d)["invoice_no"].value == "AP-9981"

def test_ambiguous_slash_date_is_flagged_not_guessed():
    d = doc("Acme Paper Ltd", "Invoice No: AP-10442", "Date: 03/04/2026", "Total $5.00")
    p = parse.parse(d); assert p["issue_date"].conf <= 0.6 and "swapped" in p["issue_date"].how

def test_another_date_on_the_page_settles_the_order():
    d = doc("Acme Paper Ltd", "Invoice No: AP-10442", "Date: 03/04/2026", "Due Date: 25/04/2026", "Total $5.00")
    p = parse.parse(d); assert p["issue_date"].value == date(2026, 4, 3) and p["issue_date"].conf > .8
