"""HTML-страницы. Данные подгружаются из JSON API (static/app.js),
сервер отдаёт только каркас — один источник правды для веба и мобилки."""
from __future__ import annotations

import os
from urllib.parse import urlparse

from flask import Blueprint, abort, send_from_directory, current_app, redirect, render_template, request, session, url_for
from kremle_detect.integrations.flask_ext import NEXT_KEY

from ..auth.sessions import current_user_id

bp = Blueprint("web", __name__)


def _safe_next(url: str | None, default: str = "/") -> str:
    """Только относительные пути на этом же сайте — защита от open redirect."""
    if not url:
        return default
    p = urlparse(url)
    if p.scheme or p.netloc or not url.startswith("/") or url.startswith("//"):
        return default
    return url


def page(template: str, name: str, **ctx):
    return render_template(template, page_name=name, **ctx)


@bp.get("/", endpoint="index")
def index():
    """Главная — это сам тамагочи. Гостю — лендинг с грибом и кнопкой «Завести»."""
    if not current_user_id():
        return page("home.html", "home")
    return page("kombucha.html", "kombucha")


@bp.get("/sw.js")
def service_worker():
    """SW должен лежать в корне, чтобы управлять всем сайтом. Версия = хеш ассетов → старый кэш сбрасывается."""
    import os
    from flask import Response
    with open(os.path.join(current_app.static_folder, "pwa", "sw.js"), encoding="utf-8") as f:
        body = f.read().replace("__V__", current_app.jinja_env.globals.get("asset_v", "1"))
    return Response(body, mimetype="application/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@bp.get("/manifest.webmanifest")
def manifest():
    r = send_from_directory(os.path.join(current_app.static_folder, "pwa"), "manifest.webmanifest",
                            mimetype="application/manifest+json")
    r.headers["Cache-Control"] = "public, max-age=3600"
    return r


@bp.get("/offline")
def offline():
    return page("offline.html", "offline")


@bp.get("/media/<name>")
def media(name: str):
    from ..services.markdown import MEDIA_RE
    if not MEDIA_RE.match(f"/media/{name}"):
        abort(404)
    resp = send_from_directory(current_app.config["UPLOAD_DIR"], name, mimetype="image/webp", max_age=31536000)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@bp.get("/kombucha")
def kombucha():
    return redirect(url_for("web.index"))


@bp.get("/g/<int:kid>")
def kombucha_diary(kid: int):
    return page("diary.html", "diary", kombucha_id=kid)


@bp.get("/market")
def market():
    return page("market.html", "market")


@bp.get("/wallet")
def wallet():
    if not current_user_id():
        return redirect(url_for("web.login", next="/wallet"))
    return page("wallet.html", "wallet")


@bp.get("/settings")
def settings():
    if not current_user_id():
        return redirect(url_for("web.login", next="/settings"))
    return page("settings.html", "settings")


@bp.get("/notifications")
def notifications():
    if not current_user_id():
        return redirect(url_for("web.login", next="/notifications"))
    return page("notifications.html", "notifications")


@bp.get("/u/<username>")
def profile(username: str):
    return page("profile.html", "profile", username=username)


@bp.get("/login")
def login():
    return page("auth.html", "login", mode="login",
                next=_safe_next(request.args.get("next")),
                demo=current_app.config.get("DEMO_MODE"))


@bp.get("/register")
def register():
    return page("auth.html", "register", mode="register",
                next=_safe_next(request.args.get("next")),
                demo=current_app.config.get("DEMO_MODE"))


@bp.get("/captcha")
def captcha():
    """Отправляет на капчу kremle-detect и после решения возвращает обратно."""
    session[NEXT_KEY] = _safe_next(request.args.get("next"))
    return redirect(url_for("kremle.challenge"))


@bp.get("/banned")
def banned():
    return page("banned.html", "banned")


@bp.get("/mod")
def mod():
    """Модераторов больше нет — баны и апелляции живут в админке."""
    return redirect("/admin#users", code=301)


@bp.get("/admin")
def admin_panel():
    return page("admin.html", "admin")
