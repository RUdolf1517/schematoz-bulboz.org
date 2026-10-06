from flask import Blueprint

bp = Blueprint("api", __name__, url_prefix="/api")

from . import (appeals, auth, clubs, events, kombucha, login_keys, market, profile, push, social,  # noqa: E402,F401
               uploads)
