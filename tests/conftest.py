import sys, base64
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "data"))
NOW = "2026-11-05T09:30"

@pytest.fixture()
def env(tmp_path, monkeypatch):
    for k, v in {"DB_PATH": str(tmp_path / "t.db"), "FILES_DIR": str(tmp_path / "files"), "GROQ_API_KEY": "", "LLM_PROVIDER": "rules", "ADMIN_PASSWORD": "testpw", "SECRET_KEY": "k" * 32,
                 "INBOUND_KEY": "inbound-secret", "INBOUND_PER_MIN": "1000", "LOGIN_PER_MIN": "5", "FAKE_NOW": NOW, "MAX_UPLOAD": str(2_000_000), "MAX_PAGES": "5"}.items():
        monkeypatch.setenv(k, v)
    for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]: del sys.modules[m]
    return tmp_path

@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient
    import app.main as main
    return TestClient(main.app)

@pytest.fixture()
def H(client):
    return {"Authorization": "Bearer " + client.post("/api/admin/login", json={"password": "testpw"}).json()["token"]}
KEY = {"X-Inbound-Key": "inbound-secret"}

@pytest.fixture(scope="session")
def docs(tmp_path_factory):
    """A handful of generated documents (digital and scanned), built once."""
    import random, make_docs as md
    d = tmp_path_factory.mktemp("docs"); rng = random.Random(5); out = {}
    for name, layout, kw, scan in [("classic", "classic", {}, None), ("modern", "modern", {}, None), ("receipt", "receipt", {}, None), ("bill", "bill", {}, None), ("euro", "euro", {}, None), ("scan", "classic", {}, "medium")]:
        cur = "EUR" if layout == "euro" else "USD"; inv = md.make_invoice(rng, currency=cur); p = d / f"{name}.pdf"; md.LAYOUTS[layout](inv, p, **kw)
        if scan: dst = d / f"{name}.jpg"; md.as_scan(p, dst, rng, scan, "jpg"); p = dst
        out[name] = (p, inv)
    return out

def b64(path): return base64.b64encode(Path(path).read_bytes()).decode()
def post_doc(client, path, name=None, headers=KEY):
    return client.post("/api/inbound", headers=headers, json={"filename": name or Path(path).name, "content_base64": b64(path)})
