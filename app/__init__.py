"""schematoz-bulboz.org — фабрика приложения."""
from __future__ import annotations

from datetime import date

from flask import Flask, render_template

from .config import Config
from .db import init_engine
from .errors import register_error_handlers
from .extensions import init_redis


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    app.json.ensure_ascii = False
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
    for bp in (api_bp, mod_bp, admin_bp, legal_bp):
        app.register_blueprint(bp)

    register_error_handlers(app)

    from .cli import register_cli
    register_cli(app)

    @app.context_processor
    def _ctx():
        return {"now_year": date.today().year}

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/healthz", endpoint="health")
    def health():
        return {"ok": True}

    return app
