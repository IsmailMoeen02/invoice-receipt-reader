import csv, io
from conftest import post_doc, KEY

def test_inbound_needs_a_key(client, docs):
    path, _ = docs["classic"]
    assert post_doc(client, path, headers={}).status_code == 401
    assert post_doc(client, path, headers={"X-Inbound-Key": "wrong"}).status_code == 401

def test_unset_inbound_key_never_means_open(env, monkeypatch, docs):
    monkeypatch.setenv("INBOUND_KEY", "")
    for m in [m for m in __import__("sys").modules if m == "app" or m.startswith("app.")]: del __import__("sys").modules[m]
    from fastapi.testclient import TestClient; import app.main as main
    c = TestClient(main.app); path, _ = docs["classic"]
    assert post_doc(c, path, headers={"X-Inbound-Key": ""}).status_code == 401 and post_doc(c, path, headers={}).status_code == 401

def test_admin_routes_need_login(client):
    for p in ("/api/admin/stats", "/api/admin/docs", "/api/admin/reconcile", "/api/admin/export.csv"): assert client.get(p).status_code == 401
    assert client.get("/api/admin/docs", headers={"Authorization": "Bearer nonsense"}).status_code == 401

def test_login_wrong_password_and_rate_limit(client):
    assert client.post("/api/admin/login", json={"password": "nope"}).status_code == 401
    codes = [client.post("/api/admin/login", json={"password": "nope"}).status_code for _ in range(8)]; assert 429 in codes

def test_security_headers(client):
    h = client.get("/health").headers; assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and "default-src 'self'" in h["content-security-policy"]

def test_upload_through_the_dashboard_route(client, docs, H):
    path, inv = docs["modern"]; r = client.post("/api/admin/upload", headers=H, files={"file": ("m.pdf", path.read_bytes(), "application/pdf")})
    assert r.status_code == 200 and r.json()["total"] == float(inv["total"])
    assert client.post("/api/admin/upload", files={"file": ("m.pdf", b"x")}).status_code == 401

def test_list_filter_search_and_detail(client, docs, H):
    for n in ("classic", "modern", "receipt"): post_doc(client, docs[n][0])
    assert len(client.get("/api/admin/docs", headers=H).json()) == 3
    sup = docs["classic"][1]["supplier"].split()[0]; hits = client.get("/api/admin/docs", headers=H, params={"q": sup}).json(); assert hits and all(sup.lower() in (h["supplier"] or "").lower() or sup.lower() in h["filename"].lower() for h in hits)
    d = client.get(f"/api/admin/docs/{hits[0]['id']}", headers=H).json(); assert d["items"] and d["doc"]["checks"] and d["activity"]
    assert client.get("/api/admin/docs/9999", headers=H).status_code == 404

def test_preview_and_original_file(client, docs, H):
    i = post_doc(client, docs["classic"][0]).json()["id"]
    r = client.get(f"/api/admin/docs/{i}/preview/1", headers=H); assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert client.get(f"/api/admin/docs/{i}/preview/9", headers=H).status_code == 404
    f = client.get(f"/api/admin/docs/{i}/file", headers=H); assert f.content[:5] == b"%PDF-" and "attachment" in f.headers["content-disposition"]

def test_correct_then_approve(client, docs, H):
    i = post_doc(client, docs["classic"][0]).json()["id"]
    r = client.patch(f"/api/admin/docs/{i}", headers=H, json={"fields": {"supplier": "Corrected Name Ltd", "po": "PO-1"}}); assert r.status_code == 200
    d = client.get(f"/api/admin/docs/{i}", headers=H).json(); assert d["doc"]["supplier"] == "Corrected Name Ltd" and d["doc"]["conf"]["supplier"] == 1.0 and any("Corrected" in a["text"] for a in d["activity"])
    assert client.post(f"/api/admin/docs/{i}/approve", headers=H).json()["state"] == "approved"
    assert client.post(f"/api/admin/docs/{i}/approve", headers=H).status_code == 409
    assert client.patch(f"/api/admin/docs/{i}", headers=H, json={"fields": {"supplier": "x"}}).status_code == 409

def test_a_wrong_total_goes_to_review_until_fixed(client, docs, H):
    i = post_doc(client, docs["classic"][0]).json()["id"]; d = client.get(f"/api/admin/docs/{i}", headers=H).json()["doc"]
    r = client.patch(f"/api/admin/docs/{i}", headers=H, json={"fields": {"total": d["total"] + 5}}).json(); assert r["status"] == "review"
    r = client.patch(f"/api/admin/docs/{i}", headers=H, json={"fields": {"total": d["total"]}}).json(); assert r["status"] == "ready"

def test_bad_edits_are_refused(client, docs, H):
    i = post_doc(client, docs["classic"][0]).json()["id"]
    for body in ({"fields": {"issue_date": "05/11/2026"}}, {"fields": {"total": "abc"}}, {"fields": {"nonsense": 1}}, {"fields": {"currency": "XXX"}}, {"fields": {"kind": "refund"}}):
        assert client.patch(f"/api/admin/docs/{i}", headers=H, json=body).status_code in (400, 422), body

def test_reject_and_stats(client, docs, H):
    a = post_doc(client, docs["classic"][0]).json()["id"]; b = post_doc(client, docs["modern"][0]).json()["id"]
    client.post(f"/api/admin/docs/{a}/approve", headers=H); client.post(f"/api/admin/docs/{b}/reject", headers=H, json={"note": "wrong company"})
    s = client.get("/api/admin/stats", headers=H).json(); assert s["approved"] == 1 and s["rejected"] == 1 and s["approved_value"] > 0

def test_export_csv_only_approved_and_blocks_formula_injection(client, docs, H):
    a = post_doc(client, docs["classic"][0]).json()["id"]; b = post_doc(client, docs["modern"][0]).json()["id"]
    client.patch(f"/api/admin/docs/{a}", headers=H, json={"fields": {"supplier": "=HYPERLINK(\"http://x\",\"y\")"}}); client.post(f"/api/admin/docs/{a}/approve", headers=H)
    rows = list(csv.reader(io.StringIO(client.get("/api/admin/export.csv", headers=H).text))); assert len(rows) == 2 and rows[1][1].startswith("'=")
    assert len(list(csv.reader(io.StringIO(client.get("/api/admin/export.csv?state=all", headers=H).text)))) == 3

def test_export_xlsx_opens(client, docs, H):
    a = post_doc(client, docs["classic"][0]).json()["id"]; client.post(f"/api/admin/docs/{a}/approve", headers=H)
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(client.get("/api/admin/export.xlsx", headers=H).content)); assert wb.active.max_row == 2 and wb.active["B1"].value == "supplier"

def test_reconcile_match_mismatch_missing_unlisted(client, docs, H):
    a = docs["classic"][1]; post_doc(client, docs["classic"][0]); post_doc(client, docs["modern"][0]); post_doc(client, docs["bill"][0])
    ids = {d["supplier"]: d for d in client.get("/api/admin/docs", headers=H).json()}
    m = docs["modern"][1]; b = docs["bill"][1]
    rows = [{"ref": "S1", "supplier": a["supplier"], "invoice_no": a["invoice_no"], "amount": float(a["total"])},
            {"ref": "S2", "supplier": m["supplier"], "invoice_no": m["invoice_no"], "amount": float(m["total"]) + 10},
            {"ref": "S3", "supplier": "Ghost Supplies", "invoice_no": "G-1", "amount": 5.0}]
    assert client.post("/api/inbound/statements", headers=KEY, json=rows).status_code == 200
    r = client.get("/api/admin/reconcile", headers=H).json()["counts"]; assert r == {"match": 1, "mismatch": 1, "missing": 1, "unlisted": 1}

def test_statements_need_the_key(client): assert client.post("/api/inbound/statements", json=[]).status_code == 401

def test_static_dashboard_served(client): assert "Document Desk" in client.get("/").text
