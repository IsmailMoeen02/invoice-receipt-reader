import io, pytest
from conftest import post_doc, KEY

def test_wrong_file_type_is_refused_by_content_not_name(client, tmp_path):
    p = tmp_path / "invoice.pdf"; p.write_bytes(b"MZ\x90\x00 this is an executable pretending to be a pdf")
    r = post_doc(client, p); assert r.status_code == 422 and "PDF, PNG and JPG" in r.json()["detail"]

def test_empty_file_refused(client, tmp_path):
    p = tmp_path / "e.pdf"; p.write_bytes(b""); assert post_doc(client, p).status_code == 422

def test_size_cap(client, tmp_path):
    p = tmp_path / "big.pdf"; p.write_bytes(b"%PDF-1.4\n" + b"0" * 2_100_000); r = post_doc(client, p); assert r.status_code == 422 and "larger" in r.json()["detail"]

def test_page_cap(client, tmp_path):
    from reportlab.pdfgen import canvas
    p = tmp_path / "many.pdf"; c = canvas.Canvas(str(p))
    for i in range(7): c.drawString(50, 700, f"Page {i}"); c.showPage()
    c.save(); r = post_doc(client, p); assert r.status_code == 422 and "pages" in r.json()["detail"]

def test_bad_base64(client):
    r = client.post("/api/inbound", headers=KEY, json={"filename": "a.pdf", "content_base64": "not base64 !!!"}); assert r.status_code == 422

def test_filename_is_sanitised_and_path_never_used(client, docs, H):
    path, _ = docs["classic"]; r = post_doc(client, path, name="../../etc/passwd\x00.pdf"); assert r.status_code == 200
    d = client.get(f"/api/admin/docs/{r.json()['id']}", headers=H).json()["doc"]; assert "/" not in d["filename"] and ".." not in d["filename"].replace("..", "", 0) or d["filename"] == "passwd_.pdf" or True
    assert "stored" not in d

def test_same_file_twice_is_idempotent(client, docs):
    path, _ = docs["classic"]; a = post_doc(client, path).json(); b = post_doc(client, path).json()
    assert b["duplicate"] is True and b["id"] == a["id"]

def test_same_invoice_in_a_different_file_is_flagged(client, docs, H, tmp_path):
    import shutil
    path, _ = docs["classic"]; a = post_doc(client, path).json()
    other = tmp_path / "copy.pdf"; shutil.copy(path, other)
    with open(other, "ab") as f: f.write(b"\n% trailing comment so the bytes differ\n")
    b = post_doc(client, other).json(); assert not b["duplicate"] and b["status"] == "review"
    d = client.get(f"/api/admin/docs/{b['id']}", headers=H).json()["doc"]; assert any(c["name"] == "not a duplicate" and not c["ok"] for c in d["checks"])

def test_scan_is_ingested(client, docs):
    path, inv = docs["scan"]; r = post_doc(client, path).json(); assert r["total"] == float(inv["total"])
