"""Shared Halloween raid teams, stage rewards, and seasonal mushroom decay."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Kombucha, User
from app.services import kombucha as kb


def _db(app, fn):
    from app.db import session_scope

    async def run():
        async with session_scope() as s:
            return await fn(s)

    with app.app_context():
        return asyncio.run(run())


def test_halloween_decay_doubles_cleanliness_and_happiness(monkeypatch):
    at = datetime.now(timezone.utc)
    kombucha = Kombucha(alive=True, frozen=False, mold=False, sweet=70.0, tea=70.0,
                        clean=90.0, happy=70.0, updated_at=at - kb.PERIOD)
    monkeypatch.setattr(kb.rng, "random", lambda: 0.999)

    kb.tick(kombucha, at, halloween_active=True)

    assert kombucha.sweet == 50
    assert kombucha.tea == 55
    assert kombucha.clean == 70
    assert kombucha.happy == 40


def test_shared_raid_party_damage_stats_and_stage_gift(app, make_user, monkeypatch):
    from app.api import events as event_api
    from app.db import session_scope
    from app.services import kombucha as kb

    admin, _ = make_user(role="admin")
    player, player_json = make_user()
    now = datetime.now(timezone.utc)
    setup = admin.put("/admin/events/halloween", json={
        "enabled": True,
        "start_at": (now - timedelta(days=1)).isoformat(),
        "end_at": (now + timedelta(days=2)).isoformat(),
        "raid": {
            "boss_name": "Плесневый король",
            "regen_per_minute": 0,
            "stages": [
                {"title": "Первая волна", "max_hp": 6, "description": "Проверка команды"},
                {"title": "Финал", "max_hp": 9, "description": "Последняя стадия"},
            ],
            "gifts": [{"id": "raid-test-gift", "stage": 1, "required_damage": 6,
                       "emoji": "🎁", "title": "Награда за вклад", "description": "Спасибо за бой!"}],
        },
    })
    assert setup.status_code == 200, setup.get_json()

    first_state = player.get("/api/kombucha").get_json()
    first_id = first_state["items"][0]["id"]

    async def add_mushrooms(s):
        user = await s.get(User, player_json["id"])
        user.jars = 3
        second = await kb.plant(s, user, "Raid Fungus Two")
        third = await kb.plant(s, user, "Raid Fungus Three")
        return [first_id, second.id, third.id]

    ids = _db(app, add_mushrooms)
    monkeypatch.setattr(event_api, "RAID_TAP_COOLDOWN", timedelta(0))

    state = player.get("/api/events/halloween/raid").get_json()
    assert state["active"] is True
    assert len(state["available_mushrooms"]) == 3

    one = player.post("/api/events/halloween/raid/tap", json={"kombucha_ids": ids[:1]}).get_json()
    two = player.post("/api/events/halloween/raid/tap", json={"kombucha_ids": ids[:2]}).get_json()
    three_response = player.post("/api/events/halloween/raid/tap", json={"kombucha_ids": ids}).get_json()

    assert one["damage_dealt"] == 1 and one["hp"] == 5
    assert two["damage_dealt"] == 2 and two["hp"] == 3
    assert three_response["damage_dealt"] == 3
    assert three_response["defeated"] is True
    assert three_response["phase"] == 2 and three_response["stage_number"] == 2
    assert three_response["hp"] == three_response["max_hp"] == 9
    assert three_response["total_damage"] == 6
    assert three_response["gifts_received"][0]["id"] == "raid-test-gift"

    by_id = {item["id"]: item["stats"] for item in three_response["available_mushrooms"]}
    assert by_id[ids[0]] == {"sweet": 67, "tea": 67, "clean": 93, "happy": 73}
    assert by_id[ids[1]] == {"sweet": 68, "tea": 68, "clean": 92, "happy": 72}
    assert by_id[ids[2]] == {"sweet": 69, "tea": 69, "clean": 91, "happy": 71}
