"""Web Push без VAPID-ключей: сайт и внутренние уведомления должны работать как обычно.

Проверяем диагностику (`vapid_status`), поведение API (`configured: false`, 503 на подписку)
и вывод `flask --app app doctor` — чтобы включение Web Push не было обязательным для прода.
"""
from __future__ import annotations

import os

import pytest

from app.services.push import SUBJECT_PLACEHOLDERS, vapid_status, vapid_subject_ok


# ---------------------------------------------------------------------------
# Чистые функции
# ---------------------------------------------------------------------------
def test_vapid_subject_ok_accepts_owner_contact():
    assert vapid_subject_ok("mailto:owner@bulboz.example")
    assert vapid_subject_ok("https://schematoz-bulboz.org/contacts")
    assert vapid_subject_ok("mailto:owner@bulboz.example ")  # пробелы не мешают


def test_vapid_subject_ok_rejects_empty_scheme_and_placeholders():
    assert not vapid_subject_ok(None)
    assert not vapid_subject_ok("")
    assert not vapid_subject_ok("owner@bulboz.example"), "нужна схема mailto:/https://"
    for placeholder in SUBJECT_PLACEHOLDERS:
        assert not vapid_subject_ok(f"mailto:{placeholder}")


def test_vapid_status_reason_for_each_state():
    assert vapid_status({})[0] is False
    assert "VAPID_PUBLIC_KEY" in vapid_status({})[1]

    no_subject = {"VAPID_PUBLIC_KEY": "pub", "VAPID_PRIVATE_KEY": "base64:priv"}
    ok, reason = vapid_status(no_subject)
    assert ok is False and "VAPID_SUBJECT" in reason

    placeholder = {**no_subject, "VAPID_SUBJECT": "mailto:admin@example.com"}
    ok, reason = vapid_status(placeholder)
    assert ok is False and "VAPID_SUBJECT" in reason

    good = {**no_subject, "VAPID_SUBJECT": "mailto:owner@bulboz.example"}
    assert vapid_status(good) == (True, "")


def test_config_default_subject_is_empty_not_fake_address(app):
    if os.environ.get("VAPID_SUBJECT"):
        pytest.skip("VAPID_SUBJECT задан в окружении")
    assert app.config["VAPID_SUBJECT"] == "", "в конфиге не должно быть примера-заглушки"


# ---------------------------------------------------------------------------
# API: сайт работает, push выключен
# ---------------------------------------------------------------------------
def test_push_settings_report_not_configured(app, make_user):
    client, _user = make_user()
    r = client.get("/api/push/settings")
    assert r.status_code == 200, r.json
    data = r.json
    assert data["configured"] is False
    assert data["vapid_public_key"] is None
    assert data["enabled"] is False
    assert data["types"], "весь список категорий всё равно отдаётся"


def test_push_subscribe_is_503_when_not_configured(app, make_user):
    client, _user = make_user()
    r = client.post("/api/push/subscriptions", json={
        "endpoint": "https://push.example/sub/abc",
        "keys": {"p256dh": "p" * 40, "auth": "a" * 16},
    })
    assert r.status_code == 503, r.json
    assert r.json["error"] == "push_not_configured"
    assert "не настроен" in r.json["message"]


def test_push_settings_configured_only_with_real_contact(app, make_user):
    app.config.update(
        VAPID_PUBLIC_KEY="public-key",
        VAPID_PRIVATE_KEY="base64:private",
        VAPID_SUBJECT="mailto:owner@bulboz.example",
    )
    client, _user = make_user()
    data = client.get("/api/push/settings").json
    assert data["configured"] is True
    assert data["vapid_public_key"] == "public-key"

    # с реальными ключами подписка принимается (доставку выполняет планировщик)
    r = client.post("/api/push/subscriptions", json={
        "endpoint": "https://push.example/sub/abc",
        "keys": {"p256dh": "p" * 40, "auth": "a" * 16},
    })
    assert r.status_code == 200, r.json
    assert client.get("/api/push/settings").json["subscribed"] is True


# ---------------------------------------------------------------------------
# CLI: doctor объясняет, но не падает из-за выключенного push
# ---------------------------------------------------------------------------
def test_doctor_explains_disabled_web_push_without_failing(app):
    runner = app.test_cli_runner()
    res = runner.invoke(args=["doctor"])
    assert "⚪ Web Push выключен" in res.output
    assert "внутренние уведомления работают" in res.output
    assert "generate-vapid" in res.output  # точная команда включения
    assert "VAPID_* в .env" in res.output
    assert res.exit_code == 0, res.output


def test_doctor_reports_configured_web_push(app):
    app.config.update(
        VAPID_PUBLIC_KEY="public-key",
        VAPID_PRIVATE_KEY="base64:private",
        VAPID_SUBJECT="mailto:owner@bulboz.example",
    )
    res = app.test_cli_runner().invoke(args=["doctor"])
    assert "✅ Web Push: VAPID-ключи и контакт владельца на месте" in res.output
    assert res.exit_code == 0, res.output


def test_generate_vapid_rejects_placeholder_subject(app):
    res = app.test_cli_runner().invoke(args=["generate-vapid", "--subject", "mailto:admin@example.com"])
    assert res.exit_code != 0
    assert "RFC 8292" in res.output


def test_dispatch_pushes_without_keys_is_noop(app):
    import asyncio

    from app.services.push import dispatch_pushes

    with app.app_context():
        result = asyncio.run(dispatch_pushes())
    assert result["configured"] is False
    assert result["sent"] == result["deferred"] == result["failed"] == 0
    assert "VAPID" in result["reason"]
