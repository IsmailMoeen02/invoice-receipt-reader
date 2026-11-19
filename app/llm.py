"""Optional language-model help for fields the rules could not read. Off unless GROQ_API_KEY is set.
Safety rule: the model must quote each value as it is written in the document. If the quote is not in the text, the value is dropped.
The value itself is then read by the same parser as everything else, so the model can never invent a number or a date."""
from __future__ import annotations
import json, re
from . import config, parse

ASK = ["supplier", "invoice_no", "issue_date", "due_date", "subtotal", "tax", "total"]
norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())

def _post(prompt: str):
    import httpx
    r = httpx.post(config.GROQ_URL, headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"}, timeout=20,
                   json={"model": config.GROQ_MODEL, "temperature": 0, "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status(); return r.json()["choices"][0]["message"]["content"]

def build_prompt(text: str, want: list) -> str:
    return ("Read this invoice text. For each field below return {\"as_written\": the exact characters as they appear in the text} or null if it is not there. "
            "Do not calculate or reformat anything. Fields: " + ", ".join(want) + ".\nReturn one JSON object.\n\n" + text[:6000])

def accept(text: str, field: str, quote, day_first=False):
    """Returns the value read from the quote, or None. The quote must be in the text."""
    if not isinstance(quote, dict): return None
    q = quote.get("as_written")
    if not isinstance(q, str) or not q.strip() or norm(q) not in norm(text): return None
    q = q.strip()
    if field in ("subtotal", "tax", "total"):
        m = parse.money_in(q); return float(m[-1][0]) if m else None
    if field in ("issue_date", "due_date"):
        d = parse.dates_in(q, day_first); return d[0][0].isoformat() if d else None
    return q

class GroqFiller:
    def __init__(self, call=None): self.call = call or _post
    def fill(self, text: str, fields: dict) -> list:
        want = [k for k in ASK if fields[k]["value"] is None or fields[k]["conf"] < 0.8]
        if not want: return []
        raw = self.call(build_prompt(text, want)); data = json.loads(raw); changed = []
        df = parse.day_first_hint(text, fields["currency"]["value"])
        for k in want:
            v = accept(text, k, data.get(k), df)
            if v is not None: fields[k].update(value=v, conf=0.7, how="language model (quote checked)"); changed.append(k)
        return changed

def make():
    if config.LLM_PROVIDER == "rules": return None
    if config.GROQ_API_KEY: return GroqFiller()
    return None
