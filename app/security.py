import base64, hashlib, hmac, secrets, time
from collections import defaultdict, deque
from . import config

class RateLimiter:
    """Sliding window, in memory. Fine for one process; use Redis if you scale out."""
    def __init__(self, limit, window=60): self.limit, self.window, self.hits = limit, window, defaultdict(deque)
    def allow(self, key):
        now = time.monotonic(); q = self.hits[key]
        while q and now - q[0] > self.window: q.popleft()
        if len(q) >= self.limit: return False
        q.append(now); return True

_salt = secrets.token_bytes(16)
_pw_hash = hashlib.pbkdf2_hmac("sha256", config.ADMIN_PASSWORD.encode(), _salt, 200_000)

def check_password(pw: str) -> bool:
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), _salt, 200_000), _pw_hash)

def make_token(now=None) -> str:
    exp = str(int((time.time() if now is None else now) + config.TOKEN_TTL)).encode()
    sig = hmac.new(config.SECRET_KEY.encode(), exp, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(exp + b"." + sig).decode()

def verify_token(tok: str, now=None) -> bool:
    try:
        exp, sig = base64.urlsafe_b64decode(tok.encode()).split(b".", 1)
        good = hmac.new(config.SECRET_KEY.encode(), exp, hashlib.sha256).digest()
        return hmac.compare_digest(sig, good) and int(exp) > (time.time() if now is None else now)
    except Exception:
        return False
