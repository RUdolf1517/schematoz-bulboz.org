"""Картинки: пережимаем в WebP (≤1600px по длинной стороне), EXIF и геометки выкидываем."""
from __future__ import annotations

import io
import os
import secrets

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError

from ..errors import ApiError

MAX_BYTES = 8 * 1024 * 1024
MAX_SIDE = 1600
MAX_PIXELS = 40_000_000  # защита от «декомпрессионных бомб»
ALLOWED = {"JPEG", "PNG", "WEBP", "GIF"}


def upload_dir() -> str:
    d = current_app.config["UPLOAD_DIR"]
    os.makedirs(d, exist_ok=True)
    return d


def process_image(raw: bytes) -> tuple[str, int, int, int]:
    if len(raw) > MAX_BYTES:
        raise ApiError("Картинка больше 8 МБ", 413, "too_large")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        img = Image.open(io.BytesIO(raw))
        fmt = img.format
        img.verify()
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        raise ApiError("Это не картинка", 400, "invalid_image")
    if fmt not in ALLOWED:
        raise ApiError("Поддерживаются JPEG, PNG, WebP и GIF", 400, "invalid_image")
    img = ImageOps.exif_transpose(img)  # повернуть по EXIF, пока он ещё есть
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "WEBP", quality=82, method=4)  # без exif= → метаданные не сохраняются
    name = secrets.token_hex(16) + ".webp"
    data = out.getvalue()
    with open(os.path.join(upload_dir(), name), "wb") as f:
        f.write(data)
    return name, img.width, img.height, len(data)
