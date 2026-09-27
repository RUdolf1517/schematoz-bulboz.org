from flask import Blueprint

bp = Blueprint("api", __name__, url_prefix="/api")

from . import answers, appeals, kombucha, comments, editing, auth, login_keys, uploads, debates, feed, profile, questions, reports, rooms, share, social, market, wall  # noqa: E402,F401
