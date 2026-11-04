#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VALORANT (无畏契约) match score reader: screen capture + OCR of the top HUD.

Reads only the top band of the primary screen; no game memory, no injection.
"""
import re
import subprocess
import threading
import time
from pathlib import Path

from PIL import Image, ImageGrab

import lyrics_screen as L

PROCESS = "VALORANT-Win64-Shipping.exe"
DEBUG_DIR = L.WORK / "valorant"

_cache = {"t": 0.0, "data": None}
_worker = threading.Event()


_proc_cache = {"t": 0.0, "v": False}


def game_running():
    now = time.time()
    if now - _proc_cache["t"] < 5.0:
        return _proc_cache["v"]
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {PROCESS}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, encoding="gbk", errors="ignore",
                             creationflags=0x08000000).stdout
        value = PROCESS.lower() in out.lower()
        _proc_cache.update({"t": now, "v": value})
        return value
    except Exception:
        return False


def _screen_size():
    try:
        import ctypes
        u = ctypes.windll.user32
        return u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    except Exception:
        return 1920, 1080


def capture_band(frac=0.24):
    w, h = _screen_size()
    box = (0, 0, w, int(h * frac))
    img = ImageGrab.grab(bbox=box, all_screens=True)
    return img


async def _ocr_words_async(img):
    import asyncio, io
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.storage.streams import InMemoryRandomAccessStream, DataWriter
    buf = io.BytesIO()
    img.save(buf, "PNG")
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(buf.getvalue())
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bmp = await decoder.get_software_bitmap_async()
    eng = L.ocr_engine()
    if eng is None:
        return []
    res = await eng.recognize_async(bmp)
    words = []
    for line in res.lines:
        for w in line.words:
            r = w.bounding_rect
            words.append((w.text.strip(), float(r.x), float(r.y + r.height / 2)))
    return words


def _words(img):
    try:
        import asyncio
        return asyncio.run(_ocr_words_async(img))
    except Exception as exc:
        L.dbg(f"valorant ocr failed: {exc}")
        return []


_TEMPLATES = None
_FONT = r"C:\Windows\Fonts\bahnschrift.ttf"


def _norm_glyph(gl, size=96):
    from PIL import Image
    import numpy as np
    k = size / max(gl.width, gl.height)
    gl = gl.resize((max(1, int(gl.width * k)), max(1, int(gl.height * k))), Image.LANCZOS)
    canvas = Image.new("L", (size, size), 0)
    canvas.paste(gl, ((size - gl.width) // 2, (size - gl.height) // 2))
    return np.asarray(canvas, dtype="float32") / 255.0


def _templates():
    global _TEMPLATES
    if _TEMPLATES is not None:
        return _TEMPLATES
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
    out = {}
    try:
        font = ImageFont.truetype(_FONT, 200)
    except Exception:
        return {}
    for ch in "0123456789":
        im = Image.new("L", (300, 300), 0)
        ImageDraw.Draw(im).text((50, 30), ch, font=font, fill=255)
        bbox = im.getbbox()
        if not bbox:
            continue
        out[ch] = _norm_glyph(im.crop(bbox))
    _TEMPLATES = out
    return out


def _digit(panel):
    """Classify one score panel (may contain 1-2 digits) with template matching."""
    import numpy as np
    from PIL import Image
    tpl = _templates()
    if not tpl or panel is None:
        return None
    g = panel.convert("L")
    mask = g.point(lambda v: 255 if v >= 170 else 0)
    bbox = mask.getbbox()
    if not bbox:
        return None
    mask = mask.crop(bbox)
    cols = (np.asarray(mask) > 0).sum(axis=0)
    groups, start = [], None
    for i, c in enumerate(cols):
        if c > 0 and start is None:
            start = i
        elif c == 0 and start is not None:
            if i - start >= 6:
                groups.append((start, i))
            start = None
    if start is not None:
        groups.append((start, len(cols)))
    # merge groups closer than 6 px (parts of one glyph)
    merged = []
    for a, b in groups:
        if merged and a - merged[-1][1] < 8:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    if not merged or len(merged) > 2:
        return None
    digits = []
    for a, b in merged:
        sub = mask.crop((max(0, a - 3), 0, min(mask.width, b + 3), mask.height))
        if sub.width < 4 or sub.height < 8:
            continue
        v = _norm_glyph(sub)
        best, best_s = None, 0.0
        for ch, t in tpl.items():
            inter = np.minimum(v, t).sum()
            union = np.maximum(v, t).sum()
            iou = float(inter / union) if union else 0.0
            if iou > best_s:
                best, best_s = ch, iou
        if best is None or best_s < 0.55:
            return None
        digits.append(best)
    if not digits:
        return None
    try:
        return int("".join(digits))
    except Exception:
        return None


def _components(mask):
    """Connected components of a binary PIL image -> list of (x0,y0,x1,y1,area)."""
    import numpy as np
    arr = np.asarray(mask) > 0
    h, w = arr.shape
    seen = np.zeros_like(arr, dtype=bool)
    boxes = []
    for y0 in range(h):
        for x0 in range(w):
            if not arr[y0, x0] or seen[y0, x0]:
                continue
            stack = [(y0, x0)]
            seen[y0, x0] = True
            minx = maxx = x0
            miny = maxy = y0
            area = 0
            while stack:
                y, x = stack.pop()
                area += 1
                if x < minx: minx = x
                if x > maxx: maxx = x
                if y < miny: miny = y
                if y > maxy: maxy = y
                for ny, nx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
                    if 0 <= ny < h and 0 <= nx < w and arr[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if area >= 40:
                boxes.append((minx, miny, maxx + 1, maxy + 1, area))
    return boxes


def _classify(sub):
    import numpy as np
    tpl = _templates()
    if not tpl:
        return None, 0.0
    v = _norm_glyph(sub)
    best, best_s = None, 0.0
    for ch, t in tpl.items():
        inter = np.minimum(v, t).sum()
        union = np.maximum(v, t).sum()
        iou = float(inter / union) if union else 0.0
        if iou > best_s:
            best, best_s = ch, iou
    return best, best_s


THRESHOLDS = (150, 210, 235)


def _digits(img, box, thresholds=THRESHOLDS):
    """Digit candidates inside box; several thresholds so bright HUDs still work."""
    from PIL import Image
    box = (max(0, int(box[0])), max(0, int(box[1])), int(box[2]), int(box[3]))
    strip = img.crop(box).convert("L")
    out = []
    seen = []
    for th in thresholds:
        mask = strip.point(lambda v: 255 if v >= th else 0)
        for (x0, y0, x1, y1, area) in _components(mask):
            w, h = x1 - x0, y1 - y0
            if h < 18 or w < 5 or w > 70:
                continue
            if not (0.20 <= w / h <= 1.3):
                continue
            cx, cy = box[0] + (x0 + x1) / 2, box[1] + (y0 + y1) / 2
            if any(abs(cx - sx) < 8 and abs(cy - sy) < 8 for sx, sy in seen):
                continue
            ch, score = _classify(mask.crop((x0, y0, x1, y1)))
            if ch is None or score < 0.58:
                continue
            seen.append((cx, cy))
            out.append((cx, cy, ch, score))
    return out


def find_scores(img, ax, ay):
    """Digits either side of the timer anchor."""
    W, H = img.size
    box = (ax - 0.13 * W, ay - 55, ax + 0.13 * W, ay + 55)
    cands = [c for c in _digits(img, box) if abs(c[0] - ax) > 45]
    left = [c for c in cands if c[0] < ax]
    right = [c for c in cands if c[0] > ax]
    if not left or not right:
        return None
    ally = max(left, key=lambda c: c[0])
    enemy = min(right, key=lambda c: c[0])
    try:
        return int(_widen(cands, ally, -1)), int(_widen(cands, enemy, 1))
    except Exception:
        return None


def find_scores_global(img):
    """No OCR: find the two score digits either side of the screen centre."""
    W, H = img.size
    box = (W * 0.30, 20, W * 0.70, min(H, 150))
    cands = _digits(img, box)
    centre = W / 2
    left = [c for c in cands if c[0] < centre - 45]
    right = [c for c in cands if c[0] > centre + 45]
    best = None
    for l in left:
        for r in right:
            if abs(l[1] - r[1]) > 14:
                continue
            gap = r[0] - l[0]
            if not (60 < gap < 0.40 * W):
                continue
            sym = abs((l[0] + r[0]) / 2 - centre)
            if sym > 0.10 * W:
                continue
            score = l[3] + r[3] - sym / W * 2
            if best is None or score > best[0]:
                best = (score, l, r)
    if best is None:
        return None
    _, l, r = best
    try:
        left_value = int(_widen(cands, l, -1))
        right_value = int(_widen(cands, r, 1))
    except Exception:
        left_value, right_value = int(l[2]), int(r[2])

    # the round timer sits between the two scores in the same font
    middle = sorted([c for c in cands if l[0] < c[0] < r[0]], key=lambda c: c[0])
    timer = None
    digits = "".join(c[2] for c in middle)
    if len(digits) == 3:
        timer = f"{digits[0]}:{digits[1:]}"
    elif len(digits) == 4:
        timer = f"{digits[:2]}:{digits[2:]}"
    return left_value, right_value, ((l[0] + r[0]) / 2, (l[1] + r[1]) / 2), timer


def _read_timer(img, ax, ay):
    """OCR just the timer box (upscaled) when the word pass split it apart."""
    from PIL import Image
    box = (max(0, int(ax - 110)), max(0, int(ay - 45)), int(ax + 110), int(ay + 45))
    crop = img.crop(box).convert("L")
    crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    texts = L.ocr_lines(crop.convert("RGB"))
    joined = re.sub(r"\s+", "", " ".join(texts))
    m = re.search(r"(\d{1,2})[:：](\d{2})", joined)
    if m:
        return f"{int(m.group(1))}:{m.group(2)}"
    return None


def _widen(cands, base, sign):
    """Attach a second digit ("10", "13") sitting right next to the base one."""
    text = base[2]
    x, y = base[0], base[1]
    for _ in range(1):
        extra = None
        for c in cands:
            if c is base or abs(c[1] - y) > 10:
                continue
            dx = (c[0] - x) * sign
            if 0 < dx < 46:
                if extra is None or dx < (extra[0] - x) * sign:
                    extra = c
        if extra is None:
            break
        text = (extra[2] + text) if sign < 0 else (text + extra[2])
        x = extra[0]
    return text


def parse_words(words, img=None):
    """Read the score: OCR gives the timer anchor when it can, shapes do the rest."""
    if img is None:
        return None

    W, _ = img.size
    colon = None
    best = None
    for text, x, y in words or []:
        if ":" not in text and "：" not in text:
            continue
        if y < 20:
            continue
        score = abs(x - W / 2)
        if best is None or score < best:
            best, colon = score, (x, y)

    if colon is not None:
        ax, ay = colon
        minutes = seconds = None
        for text, x, y in words:
            t = text.strip()
            if abs(y - ay) > 25:
                continue
            if re.fullmatch(r"\d{1,2}", t) and x < ax - 2:
                if minutes is None or x > minutes[1]:
                    minutes = (t, x)
            if re.fullmatch(r"\d{2}", t) and x > ax + 2:
                if seconds is None or x < seconds[1]:
                    seconds = (t, x)
        found = find_scores(img, ax, ay)
        if found is not None:
            timer = f"{int(minutes[0])}:{seconds[0]}" if minutes and seconds else _read_timer(img, ax, ay)
            return {"ally": found[0], "enemy": found[1], "timer": timer, "text": "hud"}

    g = find_scores_global(img)
    if g is None:
        return None
    ally, enemy, (cx, cy), hud_timer = g
    timer = hud_timer or _read_timer(img, int(cx), int(cy))
    return {"ally": ally, "enemy": enemy, "timer": timer, "text": "hud"}


def parse(texts):
    """Fallback: look for an explicit x:y / x-y score string."""
    compact = re.sub(r"\s+", "", " ".join(t.strip() for t in texts if t.strip()))
    for m in re.finditer(r"(\d{1,2})[:：\-](\d{1,2})", compact):
        a_raw, b_raw = m.group(1), m.group(2)
        a, b = int(a_raw), int(b_raw)
        if len(b_raw) == 2 and b_raw.startswith("0"):
            continue
        if b >= 14 or a > 13:
            continue
        return {"ally": a, "enemy": b, "timer": None, "text": compact}
    return None


def _read_once():
    """Capture a few frames and vote; returns data or None. Blocking."""
    samples = []
    img = None
    started = time.time()
    for _ in range(3):
        try:
            img = capture_band()
            words = _words(img)
            data = parse_words(words, img)
            if data is None:
                data = parse([w[0] for w in words])
        except Exception as exc:
            L.dbg(f"valorant read failed: {exc}")
            data = None
        if data:
            samples.append(data)
            if (len(samples) >= 2 and samples[-1]["ally"] == samples[-2]["ally"]
                    and samples[-1]["enemy"] == samples[-2]["enemy"]):
                break
        time.sleep(0.12)

    if not samples:
        if img is not None:
            _dump(img, [])
        L.dbg(f"valorant no data after 3 frames ({time.time()-started:.1f}s)")
        return None

    from collections import Counter
    counts = Counter((s["ally"], s["enemy"]) for s in samples)
    (ally, enemy), votes = counts.most_common(1)[0]
    if votes < 2 and len(samples) >= 2:
        L.dbg(f"valorant ambiguous: {[(s['ally'], s['enemy']) for s in samples]}")
        return None
    best = next(s for s in samples if (s["ally"], s["enemy"]) == (ally, enemy))
    L.dbg(f"valorant ok {ally}:{enemy} votes={votes} timer={best.get('timer')} "
          f"({time.time()-started:.1f}s)")
    return {"ally": ally, "enemy": enemy, "timer": best.get("timer"), "votes": votes}


def _store(data):
    _cache.update({"t": time.time(), "data": data})
    _worker.clear()


def _kick():
    _worker.set()
    threading.Thread(target=lambda: _store(_safe_read()), daemon=True).start()


def _safe_read():
    try:
        return _read_once()
    except Exception as exc:
        L.dbg(f"valorant worker failed: {exc}")
        return None


def game_running_cached():
    return game_running()


def read(force=False, ttl=2.0, max_age=25.0):
    """Never blocks: a background worker refreshes the cache.

    force=True still runs inline (UI 'test' button) but with a hard 4s cap.
    """
    now = time.time()
    if force:
        if not _worker.is_set():
            _worker.set()
            t = threading.Thread(target=lambda: _store(_safe_read()), daemon=True)
            t.start()
            t.join(4.0)
            if t.is_alive():
                L.dbg("valorant read timeout")
        return _cache["data"]

    if not game_running():
        _cache.update({"t": now, "data": None})
        return None
    if not _worker.is_set() and now - _cache["t"] >= ttl:
        _kick()
    data = _cache["data"]
    if data and now - _cache["t"] > max_age:
        return None
    return data


def _dump(img, texts):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        img.save(DEBUG_DIR / time.strftime("band_%H%M%S.png"))
        with open(DEBUG_DIR / "ocr.log", "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%H:%M:%S ") + repr(texts) + "\n")
    except Exception:
        pass


def render(cfg, data, out_path):
    from PIL import Image, ImageDraw, ImageFont
    ally_color = (43, 217, 168)
    enemy_color = (255, 70, 85)
    bg = (11, 13, 18)
    base = L.module_bg(cfg, "val", veil=0.55)
    img = base.copy() if base is not None else Image.new("RGB", (480, 360), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 480, 4], fill=(255, 70, 85))

    # team-tinted halves
    overlay = Image.new("RGBA", (480, 360), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    tint = 30 if base is not None else 46
    for x in range(0, 240):
        a = int(tint * (1 - x / 240))
        od.line([(x, 0), (x, 360)], fill=ally_color + (a,))
    for x in range(240, 480):
        a = int(tint * ((x - 240) / 240))
        od.line([(x, 0), (x, 360)], fill=enemy_color + (a,))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    d = ImageDraw.Draw(img)

    f_title = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 17)
    f_score = ImageFont.truetype(r"C:\Windows\Fonts\bahnschrift.ttf", 128)
    f_timer = ImageFont.truetype(r"C:\Windows\Fonts\bahnschrift.ttf", 34)
    f_tag = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 15)

    # header
    d.text((240, 34), "无畏契约", font=f_title, fill=(180, 186, 200), anchor="mm")
    d.ellipse([236, 50, 244, 58], fill=(255, 70, 85))

    # scores
    d.text((196, 150), str(data["ally"]), font=f_score, fill=ally_color, anchor="rm")
    d.ellipse([232, 132, 248, 148], fill=(110, 116, 130))
    d.ellipse([232, 168, 248, 184], fill=(110, 116, 130))
    d.text((284, 150), str(data["enemy"]), font=f_score, fill=enemy_color, anchor="lm")

    # team tags
    d.text((120, 243), "我方", font=f_tag, fill=(110, 210, 180), anchor="mm")
    d.text((360, 243), "敌方", font=f_tag, fill=(220, 120, 130), anchor="mm")

    # timer pill
    timer = data.get("timer") or "--:--"
    tw = d.textlength(timer, font=f_timer)
    x0, x1 = 240 - tw / 2 - 22, 240 + tw / 2 + 22
    d.rounded_rectangle([x0, 268, x1, 316], radius=24, outline=(70, 76, 92), width=2)
    d.text((240, 292), timer, font=f_timer, fill=(240, 242, 248), anchor="mm")

    d.text((240, 336), "屏幕识别 · 仅供参考", font=ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 10),
           fill=(90, 96, 110), anchor="mm")

    img.save(out_path, "JPEG", quality=52, optimize=True, progressive=False, subsampling=2)
    return out_path.stat().st_size
