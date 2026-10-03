"""Markdown для вопросов, ответов и комментариев.

Рендерим на сервере и чистим через nh3 (белый список тегов). Картинки разрешены только
свои — из /media/ (загрузка через /api/uploads): чужие <img> утекают IP читателей и
позволяют трекинг. Ссылки получают rel="nofollow ugc noopener".
"""
from __future__ import annotations

import re

import markdown as md
import nh3

MEDIA_RE = re.compile(r"^/media/[a-f0-9]{32}\.webp$")

BLOCK_TAGS = {"p", "br", "strong", "b", "em", "i", "del", "s", "code", "pre", "blockquote",
              "ul", "ol", "li", "a", "img", "h3", "h4", "hr", "table", "thead", "tbody", "tr", "th", "td"}
INLINE_TAGS = {"p", "br", "strong", "b", "em", "i", "del", "s", "code", "a", "img"}
ATTRS = {"a": {"href", "title"}, "img": {"src", "alt", "title", "loading"}}


def _attr_filter(tag: str, attr: str, value: str) -> str | None:
    if tag == "img" and attr == "src":
        return value if MEDIA_RE.match(value) else None
    return value


def render(text: str | None, *, inline: bool = False) -> str:
    """inline=True — для комментариев: без заголовков, списков, таблиц и блоков кода."""
    if not text:
        return ""
    # заголовки #/## превращаются в h1/h2 — в ленте это крик; понижаем до h3/h4
    html = md.markdown(text, extensions=["fenced_code", "sane_lists", "nl2br", "tables"],
                       output_format="html")
    html = re.sub(r"<(/?)h[12]>", r"<\1h3>", html)
    html = re.sub(r"<(/?)h[56]>", r"<\1h4>", html)
    html = html.replace("<img ", '<img loading="lazy" ')
    clean = nh3.clean(html, tags=INLINE_TAGS if inline else BLOCK_TAGS, attributes=ATTRS,
                      attribute_filter=_attr_filter, link_rel="nofollow ugc noopener",
                      url_schemes={"http", "https", "mailto"})
    # <img> без src (чужая картинка) — выбрасываем целиком
    return re.sub(r"<img(?![^>]*\bsrc=)[^>]*>", "", clean)
