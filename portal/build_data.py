"""Builds the dummy supplier portal's data: 18 statement lines, files copied from the dev set. Three lines are made to disagree on purpose (two amounts differ, one has no file)."""
import json, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
T = json.loads((ROOT / "data" / "dev_truth.json").read_text()); names = sorted(T)
use = [n for n in names if "scan" not in n or n.endswith((".jpg", ".png", ".pdf"))][:18]
rows = []; (ROOT / "portal" / "files").mkdir(exist_ok=True)
for i, n in enumerate(use, 1):
    t = T[n]; amount = t["total"]; file = n
    if i == 5: amount = round(amount + 12.40, 2)        # statement says more than the invoice
    if i == 11: amount = round(amount - 30.00, 2)       # statement says less
    if i == 14: file = None                             # on the statement, no PDF to download
    if file: shutil.copy(ROOT / "data" / "docs" / "dev" / n, ROOT / "portal" / "files" / n)
    rows.append({"ref": f"ST-{1000 + i}", "supplier": t["supplier"], "invoice_no": t["invoice_no"], "date": t["issue_date"], "amount": amount, "currency": t["currency"], "file": file})
(ROOT / "portal" / "data.json").write_text(json.dumps(rows, indent=1)); print(len(rows), "statement lines")
