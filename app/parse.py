"""Rules that turn lines of text into invoice fields. Each field comes back with a confidence and the line it was read from.
Handles: US and European number formats, day-first and month-first dates, many label wordings, credit notes (negative amounts), multi-page tables."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
SYM = {"$": "USD", "£": "GBP", "€": "EUR"}

# ------------------------------------------------------------------ numbers
MONEY = re.compile(r"(?<![\w.,/-])([-−(]?)\s?([$£€]?)\s?([-−]?)(\d{1,3}(?:[.,]\d{3})*[.,]\d{2}|\d+[.,]\d{2})(?![\d]|[.,]\d)\s?([$£€]?)\)?")
def to_dec(s: str, comma_decimal: bool | None = None):
    s = s.replace(" ", "")
    last_c, last_d = s.rfind(","), s.rfind(".")
    if comma_decimal is None: comma_decimal = last_c > last_d and len(s) - last_c - 1 == 2
    s = s.replace(".", "").replace(",", ".") if comma_decimal else s.replace(",", "")
    try: return Decimal(s)
    except InvalidOperation: return None

def money_in(text: str):
    """All money amounts in a string: list of (Decimal, currency|None, start, end)."""
    out = []
    for m in MONEY.finditer(text):
        neg = bool(m.group(1) or m.group(3)); v = to_dec(m.group(4))
        if v is None: continue
        sym = m.group(2) or m.group(5)
        out.append((-v if neg else v, SYM.get(sym), m.start(), m.end()))
    return out

# ------------------------------------------------------------------ dates
DATE_RES = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
    (re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "slash"),
    (re.compile(r"\b(\d{1,2})[ -]([A-Za-z]{3})[a-z]*\.?,?[ -](\d{4})\b"), "dMy"),
    (re.compile(r"\b([A-Za-z]{3})[a-z]*\.? (\d{1,2}),? (\d{4})\b"), "Mdy"),
]
def dates_in(text: str, day_first: bool):
    out = []
    for rx, kind in DATE_RES:
        for m in rx.finditer(text):
            a, b, c = m.groups(); d = None
            try:
                if kind == "iso": d = date(int(a), int(b), int(c))
                elif kind == "dmy": d = date(int(c), int(b), int(a))
                elif kind == "slash":
                    x, y = int(a), int(b)
                    if x > 12: d = date(int(c), y, x)
                    elif y > 12: d = date(int(c), x, y)
                    else: d = date(int(c), y, x) if day_first else date(int(c), x, y)
                elif kind == "dMy": d = date(int(c), MONTHS[b.lower()[:3]], int(a))
                elif kind == "Mdy": d = date(int(c), MONTHS[a.lower()[:3]], int(b))
            except (ValueError, KeyError): d = None
            if d and 2000 <= d.year <= 2100: out.append((d, m.start(), kind))
    return sorted(out, key=lambda t: t[1])

# ------------------------------------------------------------------ labels
def rx(*alts): return re.compile(r"(?<![a-z])(?:" + "|".join(alts) + r")(?![a-z])", re.I)
L_SUB = rx(r"sub[\s-]?total", r"net amount", r"net total", r"total net", r"net", r"goods total")
L_TAX = rx(r"sales tax", r"vat", r"gst", r"tax", r"mwst", r"ust")
L_TOT = rx(r"total due", r"amount due", r"balance due", r"total payable", r"amount payable", r"total amount due", r"total credit", r"credit total", r"credit due",
           r"total \(incl[^)]*\)", r"grand total", r"invoice total", r"total")
L_NO = rx(r"invoice\s*(?:no\.?|number|#|num)", r"inv\s*(?:no\.?|#)", r"bill\s*(?:no\.?|number|#)", r"credit\s*(?:note\s*)?(?:no\.?|number|#)", r"receipt(?:\s*no\.?|\s*#)?", r"reference", r"ref(?:\.|:)?", r"document\s*(?:no|number)")
L_DUE = rx(r"due\s*date", r"payment\s*due", r"pay\s*by", r"due\s*by", r"payable\s*by", r"pay\s*before", r"due")
L_ISS = rx(r"invoice\s*date", r"date\s*issued", r"issued", r"bill(?:ing)?\s*date", r"tax\s*point", r"issue\s*date", r"date")
L_PO = rx(r"po\s*(?:number|no\.?|#)?", r"purchase\s*order")
HEAD_WORDS = re.compile(r"^(tax\s+)?(invoice|bill|receipt|credit\s*note|statement)$", re.I)
ITEM_HEAD = re.compile(r"\b(description|item|desc)\b.*\b(amount|total|price|rate)\b", re.I)

@dataclass
class F:
    value: object = None; conf: float = 0.0; src: str = ""; how: str = ""
    def ok(self): return self.value is not None

def _first(rxx, text): m = rxx.search(text); return m
def _confidence(line, base): return round(base * max(0.35, min(1.0, line.conf / 92) ** 1.2), 2)

def slash_order(doc_text: str):
    """Look for a slash date that settles the order (a 25 can only be a day). Returns 'dmy', 'mdy' or None when every slash date is ambiguous."""
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/\d{4}\b", doc_text):
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 and b <= 12: return "dmy"
        if b > 12 and a <= 12: return "mdy"
    return None
def ambiguous_slash(text: str) -> bool:
    return any(int(m.group(1)) <= 12 and int(m.group(2)) <= 12 and m.group(1) != m.group(2) for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/\d{4}\b", text))

def day_first_hint(doc_text: str, currency: str | None) -> bool:
    so = slash_order(doc_text)
    if so: return so == "dmy"
    if re.search(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b", doc_text): return True
    if currency in ("GBP", "EUR"): return True
    return False

def detect_currency(lines):
    cnt = {}
    for l in lines:
        for _, cur, _, _ in money_in(l.text):
            if cur: cnt[cur] = cnt.get(cur, 0) + 1
    t = " ".join(l.text for l in lines)
    for code in ("USD", "GBP", "EUR"):
        if re.search(rf"\b{code}\b", t): cnt[code] = cnt.get(code, 0) + 3
    if re.search(r"\b(mwst|ust)\b", t, re.I): cnt["EUR"] = cnt.get("EUR", 0) + 2
    if not cnt: return F(None)
    cur = max(cnt, key=cnt.get); return F(cur, 0.97 if cnt[cur] >= 3 else 0.8, how="symbol count")

def comma_style(lines):
    """True if the document writes decimals with a comma."""
    c = d = 0
    for l in lines:
        for m in re.finditer(r"\d[.,]\d{2}(?!\d)", l.text):
            if m.group(0)[1] == ",": c += 1
            else: d += 1
    return c > d

def label_amount(lines, label, skip=None, last=True, comma=None):
    """Find the line whose label matches, return the money value on it (the last one by default)."""
    best = None
    for l in lines:
        t = l.text
        m = label.search(t)
        if not m or (skip and skip.search(t[:m.start() + 20]) and False): continue
        ms = [x for x in money_in(t) if x[2] >= m.start() or True]
        if not ms: continue
        v = ms[-1] if last else ms[0]
        best = (l, v, m)  # later lines win for totals
    return best

def parse(doc) -> dict:
    lines = [l for l in doc.lines if l.words]; full = "\n".join(l.text for l in lines)
    out: dict = {}; cur = detect_currency(lines); out["currency"] = cur
    comma = comma_style(lines); dayfirst = day_first_hint(full, cur.value)
    out["locale"] = F({"number_format": "1.234,56" if comma else "1,234.56", "dates": "day-first" if dayfirst else "month-first"}, 0.9)

    # ---- supplier: first segment of the top lines that is not a header word
    sup = F(None)
    for l in lines[:6]:
        if l.page != 0: break
        for seg in l.segments():
            s = re.sub(r"\s*\b(tax\s+invoice|invoice|bill|credit\s*note|receipt)\s*$", "", seg.strip(), flags=re.I).strip(" -|")
            if not s or HEAD_WORDS.match(s) or re.search(r"\d{3,}|@|\bpage\b|^bill to|^invoice\b", s, re.I) or len(s) < 3: continue
            sup = F(s.title() if s.isupper() else s, _confidence(l, 0.9), s, "top of page"); break
        if sup.ok(): break
    out["supplier"] = sup

    # ---- kind
    kind = "credit_note" if re.search(r"credit\s*note|credit\s*(?:no|#|total|due)", full, re.I) else "invoice"  # receipts are filed as invoices
    out["kind"] = F(kind, 0.9 if kind != "invoice" else 0.85)

    # ---- invoice number
    num = F(None)
    for l in lines:
        for seg in [l.text] + l.segments():
            m = L_NO.search(seg)
            if not m: continue
            rest = seg[m.end():].strip(" :#.")
            tok = re.match(r"([A-Z0-9][A-Z0-9\-/]{2,24})", rest, re.I)
            if tok and re.search(r"\d", tok.group(1)) and not re.match(r"\d{1,2}[./]\d", tok.group(1)):
                num = F(tok.group(1), _confidence(l, 0.95 if "no" in m.group(0).lower() or "#" in m.group(0) or "number" in m.group(0).lower() or "receipt" in m.group(0).lower() else 0.8), seg, "label"); break
        if num.ok(): break
    if not num.ok():  # label on its own row (or in its own column), value in the same column of the row below
        for i, l in enumerate(lines[:-1]):
            for seg in l.segments():
                m = L_NO.search(seg)
                if m and not seg[m.end():].strip(" :#."):
                    nxt = lines[i + 1]; tok = re.match(r"([A-Z0-9][A-Z0-9\-/]{2,24})", nxt.segments()[0].strip(), re.I)
                    if tok and re.search(r"\d", tok.group(1)): num = F(tok.group(1), _confidence(nxt, 0.88), nxt.text, "below label"); break
            if num.ok(): break
    out["invoice_no"] = num

    # ---- dates: look at the label first, then at the date on the same line, or on the next line (stacked layout)
    def date_for(label, exclude=None):
        for i, l in enumerate(lines):
            m = label.search(l.text)
            if not m: continue
            if exclude and exclude.search(l.text): continue
            for txt in (l.text[m.end():], lines[i + 1].text if i + 1 < len(lines) else ""):
                ds = dates_in(txt, dayfirst)
                if ds: return F(ds[0][0], _confidence(l, 0.92 if txt is l.text[m.end():] else 0.82), l.text, "label"), ds[0][2]
        return F(None), None
    due, _ = date_for(L_DUE)
    iss, k = date_for(L_ISS, exclude=re.compile(r"due|pay", re.I))
    if not iss.ok():
        alld = [(d, l) for l in lines for d, _, _ in dates_in(l.text, dayfirst)]
        if alld: iss = F(min(d for d, _ in alld) if len(alld) > 1 else alld[0][0], 0.84 if len(alld) == 1 else 0.6, alld[0][1].text, "only date on the page" if len(alld) == 1 else "earliest date found")
    if iss.ok() and due.ok() and due.value < iss.value and k == "slash":  # a day/month mix-up would put the due date before the issue date
        pass
    if not slash_order(full):
        for f in (iss, due):
            if f.ok() and ambiguous_slash(f.src): f.conf = min(f.conf, 0.6); f.how = "day and month could be swapped"
    out["issue_date"], out["due_date"] = iss, due

    # ---- PO and terms
    po = F(None)
    for l in lines:
        m = re.search(r"\b(?:po\s*(?:number|no\.?|#)|purchase\s*order)\s*:?\s*([A-Z0-9][A-Z0-9\-]{2,})", l.text, re.I)
        if m: po = F(m.group(1), _confidence(l, 0.92), l.text, "label"); break
    out["po"] = po
    tm = re.search(r"\b(net\s*\d{1,3}|due on receipt|\d{1,3}\s*days)\b", full, re.I)
    out["terms"] = F(tm.group(1) if tm else None, 0.85 if tm else 0)

    # ---- totals block: scan from the bottom, so the page footers and body do not confuse
    def find(label, exclude=None, bottom=True):
        hit = None
        for l in (reversed(lines) if bottom else lines):
            t = l.text; m = label.search(t)
            if not m or (exclude and exclude.search(t)): continue
            ms = money_in(t)
            if ms: hit = (l, ms[-1], m); break
        return hit
    sub = find(L_SUB, exclude=re.compile(r"tax\s*invoice|total", re.I) if False else None)
    # "Net 30" terms line has no money; "Net" labels on lines with money only
    tot = None
    for l in reversed(lines):
        t = l.text
        if L_SUB.search(t) and not re.search(r"total (due|payable|amount)|amount (due|payable)|balance|grand|incl", t, re.I): continue
        m = L_TOT.search(t)
        if m and money_in(t): tot = (l, money_in(t)[-1], m); break
    tax = None
    for l in reversed(lines):
        t = l.text; m = L_TAX.search(t)
        if m and money_in(t) and not (L_TOT.search(t) and not re.search(r"sales tax", t, re.I) and re.search(r"total", t, re.I)): tax = (l, money_in(t)[-1], m); break
    def fld(hit, base): return F(hit[1][0], _confidence(hit[0], base), hit[0].text, "label") if hit else F(None)
    out["subtotal"], out["tax"], out["total"] = fld(sub, .93), fld(tax, .9), fld(tot, .93)
    # a tax rate printed next to the label
    rate = F(None)
    if tax:
        rm = re.search(r"(\d+(?:[.,]\d+)?)\s?%", tax[0].text)
        if rm: rate = F(float(rm.group(1).replace(",", ".")) / 100, .85, tax[0].text)
    out["tax_rate"] = rate
    if not out["currency"].ok() and tot:
        pass

    # ---- line items: rows between the table header and the first totals row that end in a money value
    first_total_idx = len(lines)
    for i, l in enumerate(lines):
        if sub and l is sub[0] or tax and l is tax[0] or tot and l is tot[0]: first_total_idx = min(first_total_idx, i)
    start = 0
    for i, l in enumerate(lines):
        if ITEM_HEAD.search(l.text) or re.search(r"^\s*(pos\s+)?(description|item)\b", l.text, re.I): start = i + 1; break
    if start == 0:  # no header (receipts): items begin after the date line
        for i, l in enumerate(lines):
            if dates_in(l.text, dayfirst): start = i + 1; break
    items = []
    for l in lines[start:first_total_idx]:
        t = l.text
        if ITEM_HEAD.search(t) or re.search(r"\bpage\s+\d+\s+of\s+\d+\b", t, re.I) or re.match(r"^\s*(pos|description|item)\b", t, re.I): continue
        ms = money_in(t)
        if not ms or dates_in(t, dayfirst) and len(ms) == 0: continue
        amt = ms[-1]; head = t[:ms[0][2]].strip(); qty = None; unit = None
        mq = re.match(r"^(\d+)\s*x\s+(.*)$", head, re.I)
        if mq: qty, head = int(mq.group(1)), mq.group(2)
        else:
            mq = re.search(r"\s(-?\d{1,4})$", head)
            if mq and len(ms) >= 2: qty, head = int(mq.group(1)), head[:mq.start()]
            else:
                mq = re.search(r"\s+x\s?(\d+)$", head, re.I)
                if mq: qty, head = int(mq.group(1)), head[:mq.start()]
            mp = re.match(r"^(\d{1,2})\s+(?=[A-Za-z])", head)  # position column in some layouts
            if mp and len(ms) >= 2: head = head[mp.end():]
        if len(ms) >= 2: unit = ms[-2][0]
        if not head: continue
        items.append({"description": head.strip(" -|"), "qty": qty, "unit_price": float(unit) if unit is not None else None, "amount": float(amt[0]), "conf": _confidence(l, .9)})
    out["items"] = items
    out["_hits"] = {"sub": sub, "tax": tax, "tot": tot}
    return out
