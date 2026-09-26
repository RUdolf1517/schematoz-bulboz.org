"""ASGI-точка входа: hypercorn "app.asgi:asgi_app" --bind 0.0.0.0:8000"""
from asgiref.wsgi import WsgiToAsgi

from . import create_app

flask_app = create_app()
asgi_app = WsgiToAsgi(flask_app)
