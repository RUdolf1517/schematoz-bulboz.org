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

SLUGS = ("rules", "terms", "privacy", "requisites")


def render_md(text: str) -> Markup:
    html = markdown.markdown(text, extensions=["tables", "sane_lists"])
    return Markup(nh3.clean(html))


async def load_page(slug: str):
    async with session_scope() as s:
        return (await s.execute(
            select(LegalPage, LegalPageVersion)
            .join(LegalPageVersion, (LegalPageVersion.page_id == LegalPage.id)
                  & (LegalPageVersion.version == LegalPage.current_version))
            .where(LegalPage.slug == slug)
        )).first()


@bp.get("/<any(rules, terms, privacy, requisites):slug>")
async def page(slug: str):
    row = await load_page(slug)
    if row is None:
        abort(404)
    p, v = row
    return render_template("legal/page.html", page=p, version=v, content=render_md(v.body_md))


@bp.get("/api/legal/<any(rules, terms, privacy, requisites):slug>")
async def page_json(slug: str):
    row = await load_page(slug)
    if row is None:
        abort(404)
    p, v = row
    return {"slug": p.slug, "title": p.title, "version": v.version, "body_md": v.body_md,
            "html": str(render_md(v.body_md)), "updated_at": v.created_at.isoformat()}
