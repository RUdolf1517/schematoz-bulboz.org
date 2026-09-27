"""schematoz-bulboz.org — фабрика приложения."""
from __future__ import annotations

from datetime import date

from flask import Flask

from .config import Config
from .db import init_engine
from .errors import register_error_handlers
from .extensions import init_redis


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    app.json.ensure_ascii = False
    # версия статики: меняется при каждом изменении app.js/site.css — браузер не держит старый код в кэше
    import hashlib
    import os
    _h = hashlib.sha1()
    for _f in ("app.js", "site.css"):
        try:
            with open(os.path.join(app.static_folder, _f), "rb") as fh:
                _h.update(fh.read())
        except OSError:
            pass
    app.jinja_env.globals["asset_v"] = _h.hexdigest()[:10]
    if config:
        app.config.update(config)

    init_engine(app.config["DATABASE_URL"])
    init_redis(app)

    from .services.captcha import init_captcha
    init_captcha(app)

    from .admin import bp as admin_bp
    from .api import bp as api_bp
    from .legal import bp as legal_bp
    from .moderation import bp as mod_bp
    from .web import bp as web_bp
    for bp in (api_bp, mod_bp, admin_bp, legal_bp, web_bp):
        app.register_blueprint(bp)

    register_error_handlers(app)

    from .cli import register_cli
    register_cli(app)

    @app.context_processor
    def _ctx():
        from .auth.sessions import current_user_id
        return {"now_year": date.today().year, "logged_in": current_user_id() is not None}

    @app.get("/healthz", endpoint="health")
    def health():
        return {"ok": True}

    return app
