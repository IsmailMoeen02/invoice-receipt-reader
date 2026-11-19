"""Settings, all from environment variables. No secrets live in the code."""
import os, secrets, datetime as dt
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("DB_PATH", str(BASE / "docdesk.db"))
FILES_DIR = Path(os.environ.get("FILES_DIR", str(BASE / "files")))
COMPANY = os.environ.get("COMPANY_NAME", "Fernhill Bakery Group")

# Optional language model for fields the rules could not read. Off unless a key is set.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL = os.environ.get("GROQ_URL", "https://api.groq.com/openai/v1/chat/completions")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "auto")   # auto | groq | rules

INBOUND_KEY = os.environ.get("INBOUND_KEY", "")
DEMO_MODE = os.environ.get("DEMO_MODE", "0") == "1"
_pw = os.environ.get("ADMIN_PASSWORD")
if not _pw:
    _pw = "demo" if DEMO_MODE else secrets.token_urlsafe(9)
    GENERATED_PASSWORD = None if DEMO_MODE else _pw
else: GENERATED_PASSWORD = None
ADMIN_PASSWORD = _pw
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
TOKEN_TTL = int(os.environ.get("TOKEN_TTL", str(12 * 3600)))

MAX_UPLOAD = int(os.environ.get("MAX_UPLOAD", str(10 * 1024 * 1024)))
MAX_PAGES = int(os.environ.get("MAX_PAGES", "20"))
INBOUND_PER_MIN = int(os.environ.get("INBOUND_PER_MIN", "60"))
LOGIN_PER_MIN = int(os.environ.get("LOGIN_PER_MIN", "5"))
FAKE_NOW = os.environ.get("FAKE_NOW", "")

def now() -> dt.datetime: return dt.datetime.fromisoformat(FAKE_NOW) if FAKE_NOW else dt.datetime.now()
def wall() -> dt.datetime: return dt.datetime.now()
