"""ТОЛЬКО для e2e-стенда: подписанная Flask-сессия с пройденной капчей kremle.
Правильные ответы kremle хранит на сервере, поэтому автотест не может «решить» капчу честно.
Работает, только если знаешь SECRET_KEY стенда (по умолчанию dev-ключ)."""
import os
import sys

from flask import Flask
from kremle_detect.integrations.flask_ext import SESSION_KEY

app = Flask("e2e")
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
print(app.session_interface.get_signing_serializer(app).dumps({SESSION_KEY: True}), end="")
sys.exit(0)
