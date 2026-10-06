from flask import Blueprint

bp = Blueprint("api", __name__, url_prefix="/api")

from . import appeals, auth, kombucha, login_keys, market, profile, push, social, uploads, events  # noqa: E402,F401
