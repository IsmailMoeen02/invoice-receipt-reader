"""Turns a PDF or an image into lines of words with positions. Digital PDFs are read directly. Scans go through: 300 dpi render, deskew, light denoise, Tesseract.
Both paths give the same structure so the parser does not care where the text came from."""
from __future__ import annotations
import io, statistics, subprocess, tempfile
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class Word:
    text: str; x0: float; y0: float; x1: float; y1: float; conf: float = 100.0; page: int = 0
@dataclass
class Line:
    words: list; page: int
    @property
    def text(self): return " ".join(w.text for w in self.words)
    @property
    def y(self): return statistics.mean((w.y0 + w.y1) / 2 for w in self.words)
    @property
    def h(self): return statistics.mean(w.y1 - w.y0 for w in self.words)
    @property
    def conf(self): return statistics.mean(w.conf for w in self.words)
    def segments(self, gap=2.2):
        """Split a line into chunks where there is a wide gap (two columns on one row)."""
        out, cur = [], [self.words[0]]
        for a, b in zip(self.words, self.words[1:]):
            cw = max(1.0, (a.x1 - a.x0) / max(1, len(a.text)))
            (out.append(cur) or cur.clear()) if False else None
            if b.x0 - a.x1 > gap * cw * 3.2: out.append(cur); cur = [b]
            else: cur.append(b)
        out.append(cur); return [" ".join(w.text for w in c) for c in out]

@dataclass
class Doc:
    lines: list; source: str; pages: int; mean_conf: float = 100.0; notes: list = field(default_factory=list)
    @property
    def text(self): return "\n".join(l.text for l in self.lines)

def group_lines(words):
    out = []
    for pg in sorted({w.page for w in words}):
        ws = sorted((w for w in words if w.page == pg), key=lambda w: (w.y0 + w.y1) / 2)
        if not ws: continue
        med = statistics.median(w.y1 - w.y0 for w in ws); cur = [ws[0]]
        for w in ws[1:]:
            cy = statistics.mean((x.y0 + x.y1) / 2 for x in cur)
            if abs((w.y0 + w.y1) / 2 - cy) > 0.55 * med: out.append(Line(sorted(cur, key=lambda x: x.x0), pg)); cur = [w]
            else: cur.append(w)
        out.append(Line(sorted(cur, key=lambda x: x.x0), pg))
    return out

def kind_of(data: bytes):
    if data[:5] == b"%PDF-": return "pdf"
    if data[:8] == b"\x89PNG\r\n\x1a\n": return "png"
    if data[:3] == b"\xff\xd8\xff": return "jpg"
    return None

def _pdf_words(path, max_pages):
    import pdfplumber
    words = []
    with pdfplumber.open(path) as pdf:
        n = len(pdf.pages)
        for i, pg in enumerate(pdf.pages[:max_pages]):
            for w in pg.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5):
                words.append(Word(w["text"], w["x0"], w["top"], w["x1"], w["bottom"], 100.0, i))
    return words, n

def _render(path, dpi=300, max_pages=20):
    import cv2, numpy as np
    d = tempfile.mkdtemp(); subprocess.run(["pdftoppm", "-r", str(dpi), "-l", str(max_pages), "-gray", "-png", str(path), f"{d}/p"], check=True, timeout=120)
    return [cv2.imread(str(f), cv2.IMREAD_GRAYSCALE) for f in sorted(Path(d).glob("p*.png"))]

def deskew(gray):
    import cv2, numpy as np
    inv = cv2.bitwise_not(cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1])
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3)); blob = cv2.dilate(inv, k, iterations=1)
    cnts, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE); angs = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w > 120 and h < 80 and w > 3 * h:
            a = cv2.minAreaRect(c)[2]; a = a - 90 if a > 45 else a; a = a + 90 if a < -45 else a
            if abs(a) < 15: angs.append((a, w))
    if not angs: return gray, 0.0
    ang = float(np.average([a for a, _ in angs], weights=[w for _, w in angs]))
    if abs(ang) < 0.15: return gray, ang
    h, w = gray.shape; M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    return cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE), ang

def clean(gray):
    import cv2
    g = cv2.fastNlMeansDenoising(gray, None, 9, 7, 21)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)

def _ocr_page(gray, page):
    import pytesseract
    from pytesseract import Output
    g, ang = deskew(gray); g = clean(g)
    d = pytesseract.image_to_data(g, lang="eng", config="--psm 6", output_type=Output.DICT, timeout=90)
    words = []
    for i, t in enumerate(d["text"]):
        t = t.strip()
        if not t or float(d["conf"][i]) < 0: continue
        words.append(Word(t, d["left"][i], d["top"][i], d["left"][i] + d["width"][i], d["top"][i] + d["height"][i], float(d["conf"][i]), page))
    return words, ang

def read(path, max_pages=20):
    path = Path(path); data = path.read_bytes()[:16]; kind = kind_of(data); notes = []
    if kind == "pdf":
        words, n = _pdf_words(path, max_pages)
        if sum(len(w.text) for w in words) >= 40:
            return Doc(group_lines(words), "digital", min(n, max_pages), 100.0, ["text layer read directly"])
        pages = _render(path, 300, max_pages); src = "scan-pdf"
    elif kind in ("png", "jpg"):
        import cv2
        im = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if im is None: raise ValueError("cannot decode image")
        h, w = im.shape; s = 2480 / max(w, 1)
        if s > 1.2 or s < 0.8: im = cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
        pages = [im]; src = "image"
    else: raise ValueError("unsupported file type")
    words = []; angs = []
    for i, g in enumerate(pages):
        w, a = _ocr_page(g, i); words += w; angs.append(a)
    if not words: raise ValueError("no text found")
    mc = statistics.mean(w.conf for w in words)
    return Doc(group_lines(words), src, len(pages), mc, [f"OCR, mean word confidence {mc:.0f}", f"deskewed by {angs[0]:+.1f} degrees"])
