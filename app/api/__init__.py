from flask import Blueprint

bp = Blueprint("api", __name__, url_prefix="/api")

from . import answers, appeals, auth, debates, feed, profile, questions, reports, rooms, share  # noqa: E402,F401
