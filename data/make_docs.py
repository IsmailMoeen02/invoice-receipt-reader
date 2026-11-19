"""Makes the dummy supplier documents used for the demo, the tests and the evaluation. Every supplier, number and name is invented.

  python data/make_docs.py                 # writes data/docs/dev, data/docs/heldout and data/*_truth.json
The development set is what I tuned the extraction on. The held-out set was written after, with layouts and label wording the rules had not seen,
and was run once before any change (see eval/run_eval.py).  Some documents are digital PDFs, some are scans: rotated, blurred, noisy, low contrast."""
import io, json, random, subprocess, sys, tempfile
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from PIL import Image, ImageFilter, ImageEnhance
import numpy as np
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent
SUPPLIERS = ["Millbrook Flour Co", "Alder & Finch Packaging", "Brightwater Dairy", "Cobble Lane Produce", "Northgate Cleaning Supplies", "Ember Coffee Roasters",
             "Hollis & Pike Equipment", "Tern Valley Eggs", "Saltmarsh Linen Hire", "Quarry Road Print", "Wren Electric Services", "Kestrel Fuel Cards"]
ITEMS = [("Strong white flour 16kg", 18.40), ("Unsalted butter 5kg", 31.00), ("Caster sugar 25kg", 27.50), ("Free range eggs tray of 30", 6.80), ("Whole milk 20L", 14.90),
         ("Kraft paper bags 500pk", 22.00), ("Cake boxes 10in 100pk", 38.50), ("Sourdough starter kit", 12.00), ("Dishwasher tablets 200", 24.60), ("Hand soap 5L", 9.75),
         ("Espresso beans 1kg", 19.90), ("Oat milk 12x1L", 17.40), ("Baking parchment roll", 7.20), ("Piping bags 100pk", 8.95), ("Linen napkins hire (weekly)", 45.00),
         ("Menu cards printed 200", 54.00), ("Delivery charge", 12.50), ("Gas cylinder 13kg", 33.00), ("Mixer service call", 96.00), ("Vanilla extract 1L", 41.25)]
BILL_TO = "Fernhill Bakery Group"
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
C2 = lambda x: Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

# ---------------------------------------------------------------- the invoice data
def make_invoice(rng, supplier=None, kind="invoice", currency="USD", n_items=None, tax_rate=None, terms=None, number_style=None):
    supplier = supplier or rng.choice(SUPPLIERS); n = n_items or rng.randint(2, 7)
    items = []
    for desc, price in (rng.sample(ITEMS, n) if n <= len(ITEMS) else [rng.choice(ITEMS) for _ in range(n)]):
        qty = rng.choice([1, 1, 2, 3, 4, 5, 6, 10]); unit = C2(price * rng.choice([1, 1, 1, 1.05, .95]))
        items.append({"desc": desc, "qty": qty, "unit": unit, "amount": C2(unit * qty)})
    rate = Decimal(str({"USD": rng.choice([0, 0.08, 0.0825]), "GBP": rng.choice([0, 0.2]), "EUR": rng.choice([0.19, 0.07, 0.2])}[currency] if tax_rate is None else tax_rate))
    if kind == "credit_note":
        for it in items: it["qty"] = -abs(it["qty"]); it["amount"] = -abs(it["amount"])
    sub = sum((i["amount"] for i in items), Decimal("0")); tax = C2(sub * rate); total = sub + tax
    issue = date(2026, 9, 1) + timedelta(days=rng.randint(0, 60)); days = {"Net 30": 30, "Net 14": 14, "Net 7": 7, "Due on receipt": 0}
    terms = terms if terms is not None else rng.choice(["Net 30", "Net 14", "Net 7", "Due on receipt", None])
    due = issue + timedelta(days=days[terms]) if terms else None
    prefix = "".join(w[0] for w in supplier.replace("&", "").split())[:3].upper()
    num = {"dash": f"{prefix}-{rng.randint(10000, 99999)}", "plain": str(rng.randint(100000, 999999)), "inv": f"INV-{issue.year}-{rng.randint(100, 999)}", "short": f"{rng.randint(1000, 9999)}"}[number_style or rng.choice(["dash", "plain", "inv", "short"])]
    return {"supplier": supplier, "kind": kind, "invoice_no": num, "issue": issue, "due": due, "terms": terms, "currency": currency, "items": items, "rate": rate, "subtotal": sub, "tax": tax, "total": total,
            "po": rng.choice([None, None, f"PO-{rng.randint(1000, 9999)}"])}

def truth(inv, layout):
    return {"supplier": inv["supplier"], "kind": inv["kind"], "invoice_no": inv["invoice_no"], "issue_date": inv["issue"].isoformat(), "due_date": inv["due"].isoformat() if (inv["due"] and layout != "receipt") else None,
            "currency": inv["currency"], "subtotal": float(inv["subtotal"]), "tax": float(inv["tax"]), "total": float(inv["total"]), "n_items": len(inv["items"]), "item_amounts": [float(i["amount"]) for i in inv["items"]],
            "po": inv["po"] if layout == "classic" else None, "layout": layout}

# ---------------------------------------------------------------- formatting
SYM = {"USD": "$", "GBP": "£", "EUR": "€"}
def money(x, cur, style="us", symbol=True):
    x = Decimal(x); neg = x < 0; s = f"{abs(x):,.2f}"
    if style == "eu": s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    out = (f"{s} {SYM[cur]}" if style == "eu" else f"{SYM[cur]}{s}") if symbol else s
    return ("-" + out) if neg else out
def fdate(d, style):
    return {"iso": d.isoformat(), "us": d.strftime("%m/%d/%Y"), "uk": d.strftime("%d/%m/%Y"), "eu": d.strftime("%d.%m.%Y"), "long": f"{d.day:02d} {MONTHS[d.month - 1]} {d.year}",
            "us_long": f"{MONTHS[d.month - 1]} {d.day}, {d.year}"}[style]

# ---------------------------------------------------------------- drawing helpers
class P:
    def __init__(self, c, w, h): self.c, self.w, self.h = c, w, h
    def t(self, x, y, s, size=10, font="Helvetica", align="l", color=(0, 0, 0)):
        self.c.setFont(font, size); self.c.setFillColorRGB(*color); y = self.h - y
        {"l": self.c.drawString, "r": self.c.drawRightString, "c": self.c.drawCentredString}[align](x, y, s)
    def line(self, x1, y1, x2, y2, wd=.6, color=(0, 0, 0)): self.c.setStrokeColorRGB(*color); self.c.setLineWidth(wd); self.c.line(x1, self.h - y1, x2, self.h - y2)
    def rect(self, x, y, w, h, fill):
        self.c.setFillColorRGB(*fill); self.c.rect(x, self.h - y - h, w, h, stroke=0, fill=1)

def pdf(path, pagesize, draw):
    c = canvas.Canvas(str(path), pagesize=pagesize); draw(c); c.save()

# ---- layout 1: classic invoice
def classic(inv, path, ds="long", ms="us", labels=None, per_page=22):
    L = {"no": "Invoice No:", "date": "Date:", "due": "Due Date:", "head": "INVOICE", "sub": "Subtotal", "tax": "Sales tax", "tot": "Total Due", "po": "PO Number:", **(labels or {})}
    cur = inv["currency"]; items = inv["items"]; pages = [items[i:i + per_page] for i in range(0, len(items), per_page)] or [[]]
    def draw(c):
        for pi, chunk in enumerate(pages):
            p = P(c, *A4); p.t(40, 60, inv["supplier"], 18, "Helvetica-Bold"); p.t(40, 76, "14 Orchard Lane, Westbrook   |   accounts@example.invalid", 8.5, color=(.35, .35, .35))
            p.t(555, 60, L["head"], 22, "Helvetica-Bold", "r", (.2, .3, .5))
            if len(pages) > 1: p.t(555, 76, f"Page {pi + 1} of {len(pages)}", 9, align="r")
            if pi == 0:
                p.t(40, 120, "Bill To:", 9, "Helvetica-Bold"); p.t(40, 134, BILL_TO, 10); p.t(40, 148, "9 Mill Street, Riverton", 10)
                y = 120
                for lab, val in ((L["no"], inv["invoice_no"]), (L["date"], fdate(inv["issue"], ds)), (L["due"], fdate(inv["due"], ds) if inv["due"] else None), (L["po"], inv["po"]), ("Terms:", inv["terms"])):
                    if val: p.t(380, y, lab, 10, "Helvetica-Bold"); p.t(555, y, val, 10, align="r"); y += 15
            y0 = 200 if pi == 0 else 110
            p.rect(40, y0 - 13, 515, 20, (.9, .92, .96)); p.t(46, y0, "Description", 9.5, "Helvetica-Bold"); p.t(360, y0, "Qty", 9.5, "Helvetica-Bold", "r"); p.t(450, y0, "Unit Price", 9.5, "Helvetica-Bold", "r"); p.t(550, y0, "Amount", 9.5, "Helvetica-Bold", "r")
            y = y0 + 24
            for it in chunk:
                p.t(46, y, it["desc"], 10); p.t(360, y, str(it["qty"]), 10, align="r"); p.t(450, y, money(it["unit"], cur, ms), 10, align="r"); p.t(550, y, money(it["amount"], cur, ms), 10, align="r"); y += 18
            if pi == len(pages) - 1:
                y += 8; p.line(380, y - 12, 555, y - 12)
                p.t(450, y, L["sub"], 10, align="r"); p.t(550, y, money(inv["subtotal"], cur, ms), 10, align="r"); y += 16
                if inv["rate"] > 0 or True: p.t(450, y, f"{L['tax']} ({inv['rate'] * 100:g}%)" if inv["rate"] else L["tax"], 10, align="r"); p.t(550, y, money(inv["tax"], cur, ms), 10, align="r"); y += 18
                p.line(380, y - 12, 555, y - 12, 1.1); p.t(450, y, L["tot"], 11.5, "Helvetica-Bold", "r"); p.t(550, y, money(inv["total"], cur, ms), 11.5, "Helvetica-Bold", "r")
                p.t(40, 780, "Please pay by bank transfer. Thank you for your business.", 8.5, color=(.4, .4, .4))
            c.showPage()
    pdf(path, A4, draw)

# ---- layout 2: modern band
def modern(inv, path, ds="us_long", ms="us", labels=None):
    L = {"no": "Invoice #", "date": "Issued", "due": "Payment due", "sub": "Subtotal", "tax": "VAT", "tot": "Amount due", **(labels or {})}
    cur = inv["currency"]
    def draw(c):
        p = P(c, *A4); p.rect(0, 0, 595, 110, (.16, .25, .36)); p.t(40, 55, inv["supplier"], 20, "Helvetica-Bold", color=(1, 1, 1)); p.t(40, 74, "Wholesale supply for the food trade", 9, color=(.8, .85, .9))
        p.t(555, 55, "TAX INVOICE" if cur == "GBP" else "INVOICE", 14, "Helvetica-Bold", "r", (1, 1, 1))
        y = 150
        for lab, val in ((L["no"], inv["invoice_no"]), (L["date"], fdate(inv["issue"], ds)), (L["due"], fdate(inv["due"], ds) if inv["due"] else None)):
            if val: p.t(40, y, lab.upper(), 8, "Helvetica-Bold", color=(.4, .4, .4)); p.t(40, y + 14, val, 11); y += 36
        p.t(330, 150, "BILLED TO", 8, "Helvetica-Bold", color=(.4, .4, .4)); p.t(330, 164, BILL_TO, 11); p.t(330, 178, "9 Mill Street, Riverton", 10)
        y = 280; p.line(40, y - 14, 555, y - 14, 1.2); p.t(40, y, "Item", 9, "Helvetica-Bold"); p.t(330, y, "Qty", 9, "Helvetica-Bold", "r"); p.t(430, y, "Rate", 9, "Helvetica-Bold", "r"); p.t(555, y, "Total", 9, "Helvetica-Bold", "r"); y += 22
        for it in inv["items"]:
            p.t(40, y, it["desc"], 10); p.t(330, y, str(it["qty"]), 10, align="r"); p.t(430, y, money(it["unit"], cur, ms), 10, align="r"); p.t(555, y, money(it["amount"], cur, ms), 10, align="r"); y += 20; p.line(40, y - 14, 555, y - 14, .3, (.8, .8, .8))
        y += 14; p.t(430, y, L["sub"], 10, align="r"); p.t(555, y, money(inv["subtotal"], cur, ms), 10, align="r"); y += 17
        p.t(430, y, f"{L['tax']} {inv['rate'] * 100:g}%", 10, align="r"); p.t(555, y, money(inv["tax"], cur, ms), 10, align="r"); y += 22
        p.rect(330, y - 15, 225, 26, (.93, .95, .98)); p.t(430, y, L["tot"], 12, "Helvetica-Bold", "r"); p.t(550, y, money(inv["total"], cur, ms), 12, "Helvetica-Bold", "r")
        c.showPage()
    pdf(path, A4, draw)

# ---- layout 3: till receipt
def receipt(inv, path, ds="uk", ms="us"):
    cur = inv["currency"]; h = 330 + 16 * len(inv["items"])
    def draw(c):
        p = P(c, 226, h); p.t(113, 30, inv["supplier"].upper(), 11, "Courier-Bold", "c"); p.t(113, 44, "14 Orchard Lane, Westbrook", 8, "Courier", "c")
        p.t(12, 70, f"RECEIPT {inv['invoice_no']}", 9, "Courier"); p.t(12, 83, f"{fdate(inv['issue'], ds)}  14:{(int(inv['invoice_no'][-2:]) if inv['invoice_no'][-2:].isdigit() else 7) % 60:02d}", 9, "Courier"); p.line(12, 92, 214, 92, .5)
        y = 108
        for it in inv["items"]:
            p.t(12, y, f"{it['qty']} x {it['desc'][:22]}", 8.5, "Courier"); p.t(214, y, money(it["amount"], cur, ms, False), 8.5, "Courier", "r"); y += 16
        p.line(12, y - 8, 214, y - 8, .5); y += 6
        p.t(12, y, "SUBTOTAL", 9, "Courier"); p.t(214, y, money(inv["subtotal"], cur, ms, False), 9, "Courier", "r"); y += 14
        p.t(12, y, f"TAX {inv['rate'] * 100:g}%", 9, "Courier"); p.t(214, y, money(inv["tax"], cur, ms, False), 9, "Courier", "r"); y += 18
        p.t(12, y, "TOTAL", 11, "Courier-Bold"); p.t(214, y, money(inv["total"], cur, ms), 11, "Courier-Bold", "r"); y += 24; p.t(113, y, "THANK YOU", 9, "Courier", "c")
        c.showPage()
    pdf(path, (226, h), draw)

# ---- layout 4: bill, two columns, no quantities
def bill(inv, path, ds="long", ms="us", labels=None):
    L = {"no": "Bill No.", "date": "Bill Date", "due": "Pay By", "sub": "Net", "tax": "GST", "tot": "Balance due", **(labels or {})}
    cur = inv["currency"]
    def draw(c):
        p = P(c, *A4); p.t(300, 70, inv["supplier"], 17, "Helvetica-Bold", "c"); p.t(300, 86, "BILL", 10, "Helvetica", "c", (.4, .4, .4)); p.line(40, 98, 555, 98, 1)
        y = 126
        for lab, val in ((L["no"], inv["invoice_no"]), (L["date"], fdate(inv["issue"], ds)), (L["due"], fdate(inv["due"], ds) if inv["due"] else None), ("Customer", BILL_TO), ("Terms", inv["terms"])):
            if val: p.t(60, y, lab, 10, "Helvetica-Bold"); p.t(200, y, val, 10); y += 16
        y += 22; p.t(60, y, "Item", 10, "Helvetica-Bold"); p.t(540, y, "Amount", 10, "Helvetica-Bold", "r"); p.line(60, y + 6, 540, y + 6, .8); y += 24
        for it in inv["items"]:
            q = f" x{it['qty']}" if abs(it["qty"]) > 1 else ""
            p.t(60, y, it["desc"] + q, 10); p.t(540, y, money(it["amount"], cur, ms), 10, align="r"); y += 19
        y += 10; p.line(360, y - 12, 540, y - 12, .6)
        p.t(440, y, L["sub"], 10, align="r"); p.t(540, y, money(inv["subtotal"], cur, ms), 10, align="r"); y += 16
        p.t(440, y, f"{L['tax']} @ {inv['rate'] * 100:g}%", 10, align="r"); p.t(540, y, money(inv["tax"], cur, ms), 10, align="r"); y += 20
        p.t(440, y, L["tot"], 12, "Helvetica-Bold", "r"); p.t(540, y, money(inv["total"], cur, ms), 12, "Helvetica-Bold", "r"); c.showPage()
    pdf(path, A4, draw)

# ---- layout 5: European, comma decimals, totals at the left (held-out only)
def euro(inv, path, ds="eu", labels=None):
    L = {"no": "Invoice Number", "date": "Invoice Date", "due": "Due by", "sub": "Net amount", "tax": "VAT", "tot": "Total (incl. VAT)", **(labels or {})}
    cur = inv["currency"]
    def draw(c):
        p = P(c, *A4); p.t(40, 60, inv["supplier"], 16, "Helvetica-Bold"); p.t(40, 76, "Hauptstrasse 12, Westbrook", 9, color=(.4, .4, .4)); p.t(40, 120, f"{L['no']}  {inv['invoice_no']}", 10)
        p.t(40, 136, f"{L['date']}  {fdate(inv['issue'], ds)}", 10)
        if inv["due"]: p.t(40, 152, f"{L['due']}  {fdate(inv['due'], ds)}", 10)
        p.t(360, 120, "Customer", 9, "Helvetica-Bold"); p.t(360, 134, BILL_TO, 10)
        y = 210; p.t(40, y, "Pos", 9, "Helvetica-Bold"); p.t(80, y, "Description", 9, "Helvetica-Bold"); p.t(360, y, "Qty", 9, "Helvetica-Bold", "r"); p.t(450, y, "Price", 9, "Helvetica-Bold", "r"); p.t(555, y, "Amount", 9, "Helvetica-Bold", "r"); p.line(40, y + 6, 555, y + 6, .8); y += 24
        for i, it in enumerate(inv["items"], 1):
            p.t(40, y, str(i), 10); p.t(80, y, it["desc"], 10); p.t(360, y, str(it["qty"]), 10, align="r"); p.t(450, y, money(it["unit"], cur, "eu"), 10, align="r"); p.t(555, y, money(it["amount"], cur, "eu"), 10, align="r"); y += 18
        y += 16
        for lab, val, bold in ((L["sub"], inv["subtotal"], False), (f"{L['tax']} {inv['rate'] * 100:g} %", inv["tax"], False), (L["tot"], inv["total"], True)):
            p.t(40, y, lab, 10.5 if bold else 10, "Helvetica-Bold" if bold else "Helvetica"); p.t(250, y, money(val, cur, "eu"), 10.5 if bold else 10, "Helvetica-Bold" if bold else "Helvetica", "r"); y += 17
        c.showPage()
    pdf(path, A4, draw)

LAYOUTS = {"classic": classic, "modern": modern, "receipt": receipt, "bill": bill, "euro": euro}

# ---------------------------------------------------------------- scans: render, then damage
def render(pdf_path, dpi=200):
    d = tempfile.mkdtemp(); subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(pdf_path), f"{d}/p"], check=True)
    return [Image.open(f).convert("RGB") for f in sorted(Path(d).glob("p*.png"))]

def damage(img, rng, level="mild"):
    a = {"mild": dict(rot=1.2, blur=.5, noise=6, contrast=.92, q=78), "medium": dict(rot=2.6, blur=.8, noise=10, contrast=.82, q=62), "rough": dict(rot=3.6, blur=1.1, noise=16, contrast=.72, q=48)}[level]
    ang = rng.uniform(-a["rot"], a["rot"]); img = img.rotate(ang, resample=Image.BICUBIC, expand=True, fillcolor=(244, 242, 236))
    img = img.filter(ImageFilter.GaussianBlur(a["blur"])); img = ImageEnhance.Contrast(img).enhance(a["contrast"]); arr = np.asarray(img).astype(np.int16)
    arr = arr + np.random.default_rng(rng.randint(0, 10**6)).normal(0, a["noise"], arr.shape).astype(np.int16)
    h, w = arr.shape[:2]; shade = np.linspace(rng.uniform(0, 14), rng.uniform(0, 26), w)[None, :, None]; arr = arr - shade.astype(np.int16)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)), a["q"]

def as_scan(pdf_path, out_path, rng, level="mild", fmt="jpg"):
    pages = [damage(im, rng, level) for im in render(pdf_path)]
    if fmt == "pdf":
        pages[0][0].save(out_path, "PDF", resolution=200.0, save_all=True, append_images=[p[0] for p in pages[1:]])
    else:
        pages[0][0].save(out_path, "JPEG" if fmt == "jpg" else "PNG", quality=pages[0][1])
    Path(pdf_path).unlink()

# ---------------------------------------------------------------- the two sets
def build(name, plan, seed):
    rng = random.Random(seed); out = ROOT / "docs" / name; out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*"): f.unlink()
    T = {}
    for i, spec in enumerate(plan, 1):
        s = dict(spec); layout = s.pop("layout"); scan = s.pop("scan", None); kw = s.pop("kw", {}); fmt = s.pop("fmt", "jpg")
        inv = make_invoice(rng, **s); fname = f"{name[:3]}{i:02d}_{layout}_{inv['supplier'].split()[0].lower().strip('&')}"
        tmp = out / f"{fname}.pdf"; LAYOUTS[layout](inv, tmp, **kw)
        if scan: dst = out / f"{fname}_scan.{fmt}"; as_scan(tmp, dst, rng, scan, fmt); fn = dst.name
        else: fn = tmp.name
        T[fn] = truth(inv, layout); T[fn]["layout"] = layout + ("+" + scan if scan else "")
    (ROOT / f"{name}_truth.json").write_text(json.dumps(T, indent=1)); print(name, len(T), "documents")

DEV = [
    dict(layout="classic", currency="USD"), dict(layout="classic", currency="USD", kw=dict(ds="us_long")), dict(layout="classic", currency="GBP", tax_rate=0.2, kw=dict(ds="long", ms="us")),
    dict(layout="classic", currency="USD", n_items=34, kw=dict(per_page=20)), dict(layout="classic", currency="USD", scan="mild"), dict(layout="classic", currency="USD", scan="medium", fmt="png"),
    dict(layout="modern", currency="GBP"), dict(layout="modern", currency="USD", kw=dict(ds="us_long")), dict(layout="modern", currency="EUR", kw=dict(ds="eu", labels={"tax": "VAT"})), dict(layout="modern", currency="GBP", scan="mild", fmt="pdf"),
    dict(layout="receipt", currency="USD", kw=dict(ds="us")), dict(layout="receipt", currency="GBP", kw=dict(ds="uk")), dict(layout="receipt", currency="USD", scan="medium", kw=dict(ds="us")),
    dict(layout="bill", currency="USD"), dict(layout="bill", currency="GBP", tax_rate=0.2), dict(layout="bill", currency="USD", scan="mild", fmt="png"),
    dict(layout="classic", currency="USD", kind="credit_note", kw=dict(labels={"head": "CREDIT NOTE", "no": "Credit No:", "tot": "Credit Total"})),
    dict(layout="modern", currency="GBP", kind="credit_note", kw=dict(labels={"no": "Credit note #", "tot": "Credit due"})),
    dict(layout="classic", currency="USD", tax_rate=0, kw=dict()), dict(layout="classic", currency="USD", terms=None, n_items=2), dict(layout="bill", currency="USD", scan="medium", fmt="jpg"),
    dict(layout="modern", currency="USD", scan="rough", fmt="jpg"), dict(layout="classic", currency="GBP", scan="medium", fmt="pdf", tax_rate=0.2), dict(layout="receipt", currency="USD", scan="mild", kw=dict(ds="us")),
]
HELD = [
    dict(layout="euro", currency="EUR"), dict(layout="euro", currency="EUR", kw=dict(ds="iso")), dict(layout="euro", currency="EUR", scan="mild", fmt="png"),
    dict(layout="classic", currency="USD", kw=dict(labels={"no": "Inv #", "date": "Invoice date", "due": "Payable by", "tot": "Total Payable", "tax": "Tax"})),
    dict(layout="classic", currency="GBP", tax_rate=0.2, kw=dict(ds="uk", labels={"head": "TAX INVOICE", "no": "Invoice Number:", "date": "Tax point:", "due": "Pay before:", "tot": "Amount payable"})),
    dict(layout="modern", currency="USD", kw=dict(ds="iso", labels={"no": "Reference", "date": "Date issued", "due": "Due date", "tot": "Total (incl. tax)", "tax": "Sales tax"})),
    dict(layout="modern", currency="GBP", scan="mild", fmt="jpg", kw=dict(ds="long")), dict(layout="bill", currency="USD", kw=dict(ds="us_long", labels={"no": "Bill Number", "date": "Billing Date", "due": "Payment Due", "tot": "Total Amount Due", "tax": "Tax"})),
    dict(layout="bill", currency="GBP", tax_rate=0.2, scan="medium", fmt="png", kw=dict(ds="uk")), dict(layout="receipt", currency="GBP", kw=dict(ds="long")), dict(layout="receipt", currency="USD", scan="mild", kw=dict(ds="iso")),
    dict(layout="classic", currency="USD", n_items=27, kw=dict(per_page=14)), dict(layout="classic", currency="USD", kind="credit_note", scan="mild", fmt="pdf", kw=dict(labels={"head": "CREDIT NOTE", "no": "Credit Note No:", "tot": "Total Credit"})),
    dict(layout="euro", currency="EUR", kind="credit_note", kw=dict(labels={"no": "Credit Note Number", "tot": "Total credit"})), dict(layout="modern", currency="USD", scan="rough", fmt="jpg", kw=dict(ds="us_long")),
    dict(layout="bill", currency="USD", terms=None, kw=dict(ds="long")), dict(layout="classic", currency="USD", n_items=1, kw=dict()), dict(layout="classic", currency="USD", scan="medium", fmt="jpg", number_style="short"),
    dict(layout="euro", currency="EUR", scan="medium", fmt="jpg", kw=dict(ds="eu")), dict(layout="modern", currency="GBP", tax_rate=0, kw=dict(ds="uk", labels={"tax": "VAT (exempt)"})),
]
if __name__ == "__main__":
    build("dev", DEV, 11); build("heldout", HELD, 902)
