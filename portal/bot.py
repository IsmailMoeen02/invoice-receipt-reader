"""Logs in to the supplier portal, walks every page of the statement, downloads each document and sends it to Document Desk.
  python portal/bot.py --portal http://127.0.0.1:8090 --desk http://127.0.0.1:8000 --key INBOUND_KEY
Uses a real headless browser, because that is how a person would reach these files. Run it on a schedule (cron, n8n) to keep the desk up to date."""
import argparse, base64, re, sys, json
from playwright.sync_api import sync_playwright
import urllib.request

def post(url, key, payload):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json", "X-Inbound-Key": key}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r: return json.loads(r.read())

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--portal", default="http://127.0.0.1:8090"); ap.add_argument("--desk", default="http://127.0.0.1:8000"); ap.add_argument("--key", required=True)
    ap.add_argument("--user", default="buyer"); ap.add_argument("--password", default="portal-demo"); a = ap.parse_args(); stmts, sent = [], []
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(); pg.goto(a.portal + "/login"); pg.fill("#user", a.user); pg.fill("#pw", a.password); pg.click("#go"); pg.wait_for_selector("#stmt")
        while True:
            for tr in pg.query_selector_all("#stmt tbody tr"):
                td = [t.inner_text().strip() for t in tr.query_selector_all("td")]; m = re.search(r"([\d,]+\.\d\d)", td[4]); link = tr.query_selector("a.dl")
                row = {"ref": td[0], "supplier": td[1], "invoice_no": td[2], "stmt_date": td[3], "amount": (-1 if "-" in td[4] else 1) * float(m.group(1).replace(",", "")), "file": None}
                if link:
                    with pg.expect_download() as dl: link.click()
                    path = dl.value.path(); fn = dl.value.suggested_filename; data = open(path, "rb").read(); row["file"] = fn
                    res = post(a.desk + "/api/inbound", a.key, {"filename": fn, "content_base64": base64.b64encode(data).decode(), "source": "portal", "portal_ref": row["ref"]}); sent.append((row["ref"], res.get("status"), res.get("duplicate")))
                stmts.append(row)
            nxt = pg.query_selector("a.next")
            if not nxt: break
            nxt.click(); pg.wait_for_load_state()
        b.close()
    post(a.desk + "/api/inbound/statements", a.key, stmts)
    print(f"statement lines read: {len(stmts)}; documents downloaded and sent: {len(sent)}; without a file: {len(stmts) - len(sent)}")

if __name__ == "__main__": main()
