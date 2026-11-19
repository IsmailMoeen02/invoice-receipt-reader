import sqlite3
from . import config

def connect():
    config.FILES_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH, check_same_thread=False, isolation_level=None)
    c.row_factory = sqlite3.Row; c.execute("pragma foreign_keys=on"); return c

def init():
    c = connect()
    c.executescript("""
    create table if not exists documents(
        id integer primary key, filename text, stored text, sha text unique, source text, mime text, pages integer, size integer,
        supplier text, invoice_no text, issue_date text, due_date text, currency text, po text, terms text, kind text default 'invoice',
        subtotal real, tax real, total real,
        status text, state text default 'pending',       -- status: ready | review | failed.  state: pending | approved | rejected
        overall real, meta text, engine text, portal_ref text, created text, reviewed text, reviewer_note text default '');
    create table if not exists items(id integer primary key, doc integer references documents(id) on delete cascade, pos integer, description text, qty real, unit_price real, amount real);
    create table if not exists activity(id integer primary key, doc integer, text text, ts text);
    create table if not exists statements(id integer primary key, ref text unique, supplier text, invoice_no text, amount real, stmt_date text, file text, scraped text);
    create index if not exists idx_doc_status on documents(status, state);
    create index if not exists idx_doc_inv on documents(supplier, invoice_no);
    create index if not exists idx_item_doc on items(doc);
    """); c.close()
