from flask import Blueprint

bp = Blueprint("api", __name__, url_prefix="/api")

from . import answers, auth, feed, profile, questions, reports  # noqa: E402,F401
