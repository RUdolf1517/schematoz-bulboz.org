"""Shared Halloween raid teams, stage rewards, seasonal mushroom decay, and standings."""
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


def test_shared_raid_party_damage_stats_and_stage_badge(app, make_user, monkeypatch):
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
            "gifts": [{"id": "raid-test-badge", "stage": 1, "required_damage": 6,
                       "reward_type": "badge", "emoji": "🏅", "title": "Бейдж за вклад", "description": "Спасибо за бой!"}],
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
    fighter = state["available_mushrooms"][0]
    assert {"alive", "frozen", "mood", "stage", "mutations", "halloween_hat"} <= fighter.keys()
    assert {"size", "title"} <= fighter["stage"].keys()
    assert fighter["halloween_gone"] is False

    one = player.post("/api/events/halloween/raid/tap", json={"kombucha_ids": ids[:1]}).get_json()
    two = player.post("/api/events/halloween/raid/tap", json={"kombucha_ids": ids[:2]}).get_json()
    three_response = player.post("/api/events/halloween/raid/tap", json={"kombucha_ids": ids}).get_json()

    assert one["damage_dealt"] == 1 and one["hp"] == 5
    assert one["participants"] == 1 and one["my_rank"] == 1
    assert one["leaderboard"][0]["username"] == player_json["username"]
    assert one["leaderboard"][0]["is_me"] is True
    assert two["damage_dealt"] == 2 and two["hp"] == 3
    assert three_response["damage_dealt"] == 3
    assert three_response["defeated"] is True
    assert three_response["phase"] == 2 and three_response["stage_number"] == 2
    assert three_response["hp"] == three_response["max_hp"] == 9
    assert three_response["total_damage"] == 6
    assert three_response["gifts_received"][0]["id"] == "raid-test-badge"
    assert three_response["gifts_received"][0]["reward_type"] == "badge"
    assert three_response["gifts_received"][0]["badge_code"].startswith("hrb_")

    by_id = {item["id"]: item["stats"] for item in three_response["available_mushrooms"]}
    assert by_id[ids[0]] == {"sweet": 67, "tea": 67, "clean": 93, "happy": 73}
    assert by_id[ids[1]] == {"sweet": 68, "tea": 68, "clean": 92, "happy": 72}
    assert by_id[ids[2]] == {"sweet": 69, "tea": 69, "clean": 91, "happy": 71}


def test_shared_leaderboard_and_latest_completed_summary(app, make_user, monkeypatch):
    from app.api import events as event_api

    admin, _ = make_user(role="admin")
    first, first_user = make_user(username="raiderfirst")
    second, second_user = make_user(username="raidersecond")
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=1)
    end = now + timedelta(days=1)
    raid = {"boss_name": "Общий кошмар", "regen_per_minute": 0,
            "stages": [{"title": "Последняя ночь", "max_hp": 100,
                        "description": "Бейте вместе"}], "gifts": []}

    response = admin.put("/admin/events/halloween", json={
        "enabled": True, "start_at": start.isoformat(), "end_at": end.isoformat(), "raid": raid,
    })
    assert response.status_code == 200, response.get_json()
    monkeypatch.setattr(event_api, "RAID_TAP_COOLDOWN", timedelta(0))

    first_tap = first.post("/api/events/halloween/raid/tap", json={}).get_json()
    stronger_tap = first.post("/api/events/halloween/raid/tap", json={}).get_json()
    second_tap = second.post("/api/events/halloween/raid/tap", json={}).get_json()
    assert first_tap["active"] is True
    assert first_tap["participants"] == 1 and first_tap["my_rank"] == 1
    assert stronger_tap["my_damage"] == 2 and stronger_tap["my_rank"] == 1
    assert second_tap["participants"] == 2 and second_tap["my_rank"] == 2
    assert [entry["username"] for entry in second_tap["leaderboard"]] == [
        first_user["username"], second_user["username"],
    ]
    assert second_tap["leaderboard"][0]["damage"] == 2
    assert second_tap["leaderboard"][1]["damage"] == 1

    # End this season without changing its identity: the current summary must be visible.
    ended = now - timedelta(minutes=1)
    end_response = admin.put("/admin/events/halloween", json={
        "enabled": True, "start_at": start.isoformat(), "end_at": ended.isoformat(), "raid": raid,
    })
    assert end_response.status_code == 200, end_response.get_json()
    finished = first.get("/api/events/state").get_json()["raid_summary"]
    assert finished["boss"] == "Общий кошмар"
    assert finished["total_damage"] == 3
    assert finished["participants"] == 2
    assert finished["leaderboard"][0]["username"] == first_user["username"]
    assert finished["leaderboard"][0]["damage"] == 2

    # Scheduling the next raid archives the previous result and resets its contribution.
    next_start = now + timedelta(days=3)
    next_end = now + timedelta(days=4)
    next_response = admin.put("/admin/events/halloween", json={
        "enabled": True, "start_at": next_start.isoformat(), "end_at": next_end.isoformat(), "raid": raid,
    })
    assert next_response.status_code == 200, next_response.get_json()
    archived = second.get("/api/events/state").get_json()["raid_summary"]
    assert archived["event_key"] == start.isoformat()
    assert archived["total_damage"] == 3
    assert [entry["username"] for entry in archived["leaderboard"]] == [
        first_user["username"], second_user["username"],
    ]


def test_admin_badges_and_raid_archive(app, make_user, monkeypatch):
    from app.api import events as event_api

    admin, _ = make_user(role="admin")
    first, first_user = make_user(username="raidchampion")
    second, second_user = make_user(username="raidmedalist")
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=1)
    badge = {"id": "raid-badge", "stage": 1, "required_damage": 1, "reward_type": "badge",
             "emoji": "🦇", "title": "Ночной дозор", "description": "Внёс вклад в общий бой."}
    raid = {
        "boss_name": "Архивный кошмар", "regen_per_minute": 0,
        "stages": [{"title": "Последняя ночь", "max_hp": 4, "description": ""}],
        "gifts": [badge],
    }

    for removed_type in ("hat", "gift"):
        removed_raid = {**raid, "gifts": [{**badge, "reward_type": removed_type}]}
        rejected = admin.put("/admin/events/halloween", json={
            "enabled": True, "start_at": start.isoformat(),
            "end_at": (now + timedelta(days=1)).isoformat(), "raid": removed_raid,
        })
        assert rejected.status_code == 400

    configured = admin.put("/admin/events/halloween", json={
        "enabled": True, "start_at": start.isoformat(),
        "end_at": (now + timedelta(days=1)).isoformat(), "raid": raid,
    })
    assert configured.status_code == 200, configured.get_json()
    assert configured.get_json()["raid"]["gifts"][0]["reward_type"] == "badge"
    monkeypatch.setattr(event_api, "RAID_TAP_COOLDOWN", timedelta(0))

    first_hit = first.post("/api/events/halloween/raid/tap", json={}).get_json()
    assert first_hit["defeated"] is False
    badge_reward = next(item for item in first_hit["gifts_received"] if item["reward_type"] == "badge")
    assert badge_reward["badge_code"].startswith("hrb_")
    second.post("/api/events/halloween/raid/tap", json={})
    first.post("/api/events/halloween/raid/tap", json={})
    final_hit = second.post("/api/events/halloween/raid/tap", json={}).get_json()
    assert final_hit["defeated"] is True

    profile = first.get(f"/api/users/{first_user['username']}").get_json()
    profile_badge = next(item for item in profile["badges"] if item["code"] == badge_reward["badge_code"])
    assert profile_badge["title"] == "Ночной дозор"
    assert "raid_contributor" in {item["code"] for item in profile["badges"]}
    showcase = first.patch("/api/me/profile", json={"showcase_badges": [badge_reward["badge_code"]]})
    assert showcase.status_code == 200, showcase.get_json()

    ended = now - timedelta(minutes=1)
    end_response = admin.put("/admin/events/halloween", json={
        "enabled": True, "start_at": start.isoformat(), "end_at": ended.isoformat(), "raid": raid,
    })
    assert end_response.status_code == 200, end_response.get_json()
    summary = first.get("/api/events/state").get_json()["raid_summary"]
    assert summary["medals"][0]["medal"] == "🥇"
    assert summary["medals"][0]["username"] == first_user["username"]
    assert summary["medals"][1]["medal"] == "🥈"
    archive = first.get("/api/events/halloween/archive").get_json()
    assert archive["total"] == 1
    assert archive["records"]["total_damage"]["value"] == 4
    assert archive["records"]["participants"]["value"] == 2
    assert archive["items"][0]["event_key"] == start.isoformat()
    assert archive["items"][0]["contribution_rewards"] == [badge]
    assert "raid_champion" in {item["code"] for item in first.get(f"/api/users/{first_user['username']}").get_json()["badges"]}
    assert "raid_medalist" in {item["code"] for item in second.get(f"/api/users/{second_user['username']}").get_json()["badges"]}

    next_start = now + timedelta(days=3)
    next_event = admin.put("/admin/events/halloween", json={
        "enabled": True, "start_at": next_start.isoformat(),
        "end_at": (next_start + timedelta(days=1)).isoformat(), "raid": raid,
    })
    assert next_event.status_code == 200, next_event.get_json()
    history = first.get("/api/events/state").get_json()["raid_gifts"]
    assert {item["id"] for item in history} == {"raid-badge"}
    assert all(item["event_key"] == start.isoformat() for item in history)
