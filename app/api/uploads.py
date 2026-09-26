"""POST /api/uploads — загрузка картинки (обложка вопроса, картинки в markdown)."""
from __future__ import annotations

from flask import g, request
from sqlalchemy import select

from ..auth.rbac import require_perm
from ..db import session_scope
from ..errors import ApiError
from ..models import Upload
from ..services import antispam
from ..services.markdown import MEDIA_RE
from ..services.uploads import process_image
from . import bp

UPLOADS_PER_HOUR = 60


@bp.post("/uploads")
@require_perm("answer.create")  # грузить могут все, кто может писать (забаненные — нет)
async def upload_image():
    f = request.files.get("file")
    if f is None:
        raise ApiError("Нужен файл в поле file", 400, "validation_error", field="file")
    if antispam.hit_rate("upload", f"u:{g.user.id}", UPLOADS_PER_HOUR, 3600):
        raise ApiError("Слишком много картинок за час — передохни", 429, "rate_limited")
    name, w, h, size = process_image(f.read())
    async with session_scope() as s:
        s.add(Upload(user_id=g.user.id, name=name, width=w, height=h, size_bytes=size))
    url = f"/media/{name}"
    return {"url": url, "width": w, "height": h, "markdown": f"![]({url})"}, 201


async def check_cover(s, url, user_id: int) -> str | None:
    """Обложка — только своя загруженная картинка."""
    if url in (None, ""):
        return None
    if not isinstance(url, str) or not MEDIA_RE.match(url):
        raise ApiError("Обложка — картинка, загруженная через /api/uploads", 400, "validation_error",
                       field="cover_url")
    owner = await s.scalar(select(Upload.user_id).where(Upload.name == url.rsplit("/", 1)[1]))
    if owner != user_id:
        raise ApiError("Картинка не найдена", 400, "validation_error", field="cover_url")
    return url
