"""Картинки для сторис 1080×1920: ответ-«Схема», профиль (уровень, стрик, бейджи).
Рендер на Pillow, шрифт DejaVu (кириллица) лежит в app/static/fonts."""
from __future__ import annotations

import io
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
BG_TOP, BG_BOTTOM = (26, 18, 40), (14, 14, 18)
ACCENT = (255, 90, 54)
FG, MUTED, CARD = (242, 242, 245), (150, 150, 165), (34, 32, 44)
FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "fonts")
SITE = "schematoz-bulboz.org"


@lru_cache(maxsize=16)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)


def _background() -> Image.Image:
    img = Image.new("RGB", (W, H), BG_BOTTOM)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
    return img


def wrap(d: ImageDraw.ImageDraw, text: str, f, max_w: int, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if d.textlength(test, font=f) <= max_w:
            cur = test
            continue
        if cur:
            lines.append(cur)
        cur = w
        while d.textlength(cur, font=f) > max_w:  # очень длинное слово
            cut = len(cur)
            while cut > 1 and d.textlength(cur[:cut], font=f) > max_w:
                cut -= 1
            lines.append(cur[:cut])
            cur = cur[cut:]
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and d.textlength(lines[-1] + "…", font=f) > max_w:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def _header(d: ImageDraw.ImageDraw) -> None:
    d.text((80, 110), "schematoz", font=font(56, True), fill=FG)
    x = 80 + d.textlength("schematoz", font=font(56, True))
    d.text((x, 110), "·", font=font(56, True), fill=ACCENT)
    x += d.textlength("·", font=font(56, True))
    d.text((x, 110), "bulboz", font=font(56, True), fill=FG)


def _fit(d: ImageDraw.ImageDraw, text: str, size: int, max_w: int, bold: bool = True):
    while size > 20 and d.textlength(text, font=font(size, bold)) > max_w:
        size -= 2
    return font(size, bold)


def _footer(d: ImageDraw.ImageDraw, path: str, label: str) -> None:
    d.text((80, H - 190), label, font=font(36), fill=MUTED)
    url = f"{SITE}{path}"
    d.text((80, H - 140), url, font=_fit(d, url, 40, W - 160), fill=ACCENT)


def _to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def render_answer_card(*, question_title: str, answer_body: str, author: str, score: int,
                       is_scheme: bool, question_id: int) -> bytes:
    img = _background()
    d = ImageDraw.Draw(img)
    _header(d)
    y = 300
    d.text((80, y), "ВОПРОС", font=font(34, True), fill=ACCENT)
    y += 60
    for line in wrap(d, question_title, font(62, True), W - 160, 5):
        d.text((80, y), line, font=font(62, True), fill=FG)
        y += 80
    y += 50
    lines = wrap(d, answer_body, font(46), W - 240, 12)
    card_h = 150 + len(lines) * 62 + 110
    d.rounded_rectangle([60, y, W - 60, y + card_h], radius=44, fill=CARD)
    badge = "СХЕМА · +5 от автора" if is_scheme else "ОТВЕТ"
    bw = d.textlength(badge, font=font(32, True)) + 56
    d.rounded_rectangle([110, y + 50, 110 + bw, y + 110], radius=30,
                        fill=ACCENT if is_scheme else (60, 58, 72))
    d.text((138, y + 60), badge, font=font(32, True), fill=FG)
    ty = y + 150
    for line in lines:
        d.text((110, ty), line, font=font(46), fill=FG)
        ty += 62
    d.text((110, ty + 30), f"@{author}  ·  {score:+d}", font=font(36), fill=MUTED)
    _footer(d, f"/q/{question_id}", "Открой ответ целиком:")
    return _to_png(img)


def render_profile_card(*, username: str, level: int, level_name: str, streak: int,
                        reputation: int, schemes: int, badges: list[dict]) -> bytes:
    img = _background()
    d = ImageDraw.Draw(img)
    _header(d)
    d.text((80, 330), f"@{username}", font=_fit(d, f"@{username}", 80, W - 160), fill=FG)
    d.text((80, 440), f"Уровень {level} · {level_name}", font=font(48), fill=ACCENT)
    stats = [(str(streak), "дней стрик"), (str(reputation), "репутация"), (str(schemes), "схем")]
    x = 80
    for value, label in stats:
        d.rounded_rectangle([x, 560, x + 290, 800], radius=36, fill=CARD)
        d.text((x + 40, 600), value, font=font(88, True), fill=FG)
        d.text((x + 40, 720), label, font=font(34), fill=MUTED)
        x += 320
    y = 880
    d.text((80, y), "БЕЙДЖИ", font=font(34, True), fill=ACCENT)
    y += 70
    if not badges:
        d.text((80, y), "Скоро будут — я только начинаю", font=font(44), fill=MUTED)
    for b in badges[:8]:
        d.rounded_rectangle([80, y, W - 80, y + 100], radius=30, fill=CARD)
        d.text((120, y + 26), b["title"], font=font(44, True), fill=FG)
        d.text((W - 120 - d.textlength(b["description"][:26], font=font(28)), y + 38),
               b["description"][:26], font=font(28), fill=MUTED)
        y += 120
    _footer(d, f"/u/{username}", "Мой профиль:")
    return _to_png(img)
