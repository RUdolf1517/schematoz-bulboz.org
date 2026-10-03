"""Публичные юридические страницы (HTML)."""
from __future__ import annotations

import markdown
import nh3
from flask import Blueprint, abort, render_template
from markupsafe import Markup
from sqlalchemy import select

from ..db import session_scope
from ..models import LegalPage, LegalPageVersion

bp = Blueprint("legal", __name__)

SLUGS = ("rules", "terms", "privacy", "requisites", "faq")


def render_md(text: str) -> Markup:
    html = markdown.markdown(text, extensions=["tables", "sane_lists"])
    return Markup(nh3.clean(html))


def faq_split(md_text: str) -> tuple[str, list[tuple[str, str]]]:
    """FAQ в markdown: каждый «## Вопрос» + текст под ним = один пункт-аккордеон."""
    intro, items, cur_q, buf = [], [], None, []
    for line in md_text.splitlines():
        if line.startswith("## "):
            if cur_q is not None:
                items.append((cur_q, "\n".join(buf).strip()))
            cur_q, buf = line[3:].strip(), []
        elif cur_q is None:
            intro.append(line)
        else:
            buf.append(line)
    if cur_q is not None:
        items.append((cur_q, "\n".join(buf).strip()))
    return "\n".join(intro).strip(), items


async def load_page(slug: str):
    async with session_scope() as s:
        return (await s.execute(
            select(LegalPage, LegalPageVersion)
            .join(LegalPageVersion, (LegalPageVersion.page_id == LegalPage.id)
                  & (LegalPageVersion.version == LegalPage.current_version))
            .where(LegalPage.slug == slug)
        )).first()


@bp.get("/<any(rules, terms, privacy, requisites, faq):slug>")
async def page(slug: str):
    row = await load_page(slug)
    if row is None:
        abort(404)
    p, v = row
    if slug == "faq":
        return render_template("faq.html", page_name="faq", page=p, version=v, intro=render_md(faq_split(v.body_md)[0]),
                               items=[(q, render_md(a)) for q, a in faq_split(v.body_md)[1]])
    return render_template("legal/page.html", page=p, version=v, content=render_md(v.body_md))


@bp.get("/api/legal/<any(rules, terms, privacy, requisites, faq):slug>")
async def page_json(slug: str):
    row = await load_page(slug)
    if row is None:
        abort(404)
    p, v = row
    return {"slug": p.slug, "title": p.title, "version": v.version, "body_md": v.body_md,
            "html": str(render_md(v.body_md)), "updated_at": v.created_at.isoformat()}
