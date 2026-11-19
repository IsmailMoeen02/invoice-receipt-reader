"""Fills a fresh database with the demo documents (dummy suppliers, dummy amounts) and the portal statement lines.
  DB_PATH=... FILES_DIR=... python scripts/seed.py"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from app import db, ingest, config

def main():
    db.init(); portal = {r["file"]: r["ref"] for r in json.loads((ROOT / "portal" / "data.json").read_text()) if r["file"]}
    for n in sorted((ROOT / "data" / "docs" / "dev").glob("*")):
        ingest.process(n.read_bytes(), n.name, "portal" if n.name in portal else "mailbox", portal.get(n.name))
    for n in sorted((ROOT / "data" / "docs" / "heldout").glob("*"))[:8]: ingest.process(n.read_bytes(), n.name, "upload")
    c = db.connect()
    for r in json.loads((ROOT / "portal" / "data.json").read_text()):
        c.execute("insert or ignore into statements(ref,supplier,invoice_no,amount,stmt_date,file,scraped) values(?,?,?,?,?,?,?)", (r["ref"], r["supplier"], r["invoice_no"], r["amount"], r["date"], r["file"], config.now().isoformat(timespec="seconds")))
    # a few already decided, so the demo has history
    ids = [r[0] for r in c.execute("select id from documents where status='ready' order by id limit 6")]
    for i in ids[:4]: c.execute("update documents set state='approved', reviewed=? where id=?", (config.now().isoformat(timespec="seconds"), i)); ingest.log(c, i, "Approved")
    c.execute("update documents set state='rejected', reviewed=?, reviewer_note='Not our supplier' where id=?", (config.now().isoformat(timespec="seconds"), ids[4])); ingest.log(c, ids[4], "Rejected: Not our supplier")
    print("seeded", c.execute("select count(*) from documents").fetchone()[0], "documents")
if __name__ == "__main__": main()
