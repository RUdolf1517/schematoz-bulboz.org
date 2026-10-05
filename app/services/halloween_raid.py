"""Shared Halloween raid standings and the latest completed event summary."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select, update

from ..models import HalloweenRaid, HalloweenRaidPlayer, Setting, User
from . import halloween

RAID_META_KEY = "halloween_raid_meta"
LEADERBOARD_SIZE = 10


def event_key(config: dict) -> str:
    """The scheduled start uniquely identifies a raid season."""
    return str(config.get("start_at") or "")[:64]


def _meta_value(config: dict, last_summary: dict | None) -> dict:
    return {
        "event_key": event_key(config),
        "enabled": bool(config.get("enabled")),
        "start_at": config.get("start_at"),
        "end_at": config.get("end_at"),
        "raid": halloween.normalize_raid_config(config.get("raid")),
        "last_summary": last_summary,
    }


def _config_from_meta(value: dict, fallback: dict) -> dict:
    return {
        "enabled": value.get("enabled", fallback.get("enabled", False)),
        "start_at": value.get("start_at", fallback.get("start_at")),
        "end_at": value.get("end_at", fallback.get("end_at")),
        "raid": value.get("raid", fallback.get("raid")),
    }


async def leaderboard(s, user_id: int | None = None,
                      player: HalloweenRaidPlayer | None = None, limit: int = LEADERBOARD_SIZE) -> dict:
    """Top contributors across the one shared raid, ordered by damage then account id."""
    participants = int(await s.scalar(
        select(func.count()).select_from(HalloweenRaidPlayer).where(HalloweenRaidPlayer.damage > 0)
    ) or 0)
    rows = (await s.execute(
        select(HalloweenRaidPlayer.user_id, User.username, HalloweenRaidPlayer.damage)
        .join(User, User.id == HalloweenRaidPlayer.user_id)
        .where(HalloweenRaidPlayer.damage > 0)
        .order_by(HalloweenRaidPlayer.damage.desc(), HalloweenRaidPlayer.user_id.asc())
        .limit(max(1, min(int(limit), 20)))
    )).all()
    entries = [{
        "rank": index,
        "username": username,
        "damage": int(damage),
        "is_me": user_id == participant_id if user_id is not None else False,
    } for index, (participant_id, username, damage) in enumerate(rows, 1)]

    my_rank = None
    if user_id is not None:
        if player is None:
            player = await s.get(HalloweenRaidPlayer, user_id)
        if player is not None and player.damage > 0:
            ahead = or_(
                HalloweenRaidPlayer.damage > player.damage,
                and_(HalloweenRaidPlayer.damage == player.damage,
                     HalloweenRaidPlayer.user_id < user_id),
            )
            my_rank = int(await s.scalar(
                select(func.count()).select_from(HalloweenRaidPlayer)
                .where(HalloweenRaidPlayer.damage > 0, ahead)
            ) or 0) + 1
    return {"leaderboard": entries, "participants": participants, "my_rank": my_rank}


async def make_summary(s, raid: HalloweenRaid | None, config: dict, key: str | None = None) -> dict:
    raid_config = halloween.normalize_raid_config(config.get("raid"))
    stage_count = len(raid_config["stages"])
    completed_stages = min(max(int(raid.phase or 1) - 1, 0), stage_count) if raid else 0
    standings = await leaderboard(s)
    return {
        "event_key": key or event_key(config),
        "start_at": config.get("start_at"),
        "end_at": config.get("end_at"),
        "boss": raid_config["boss_name"],
        "total_damage": max(0, int(raid.total_damage or 0)) if raid else 0,
        "completed_stages": completed_stages,
        "stage_count": stage_count,
        "boss_defeated": completed_stages >= stage_count,
        "participants": standings["participants"],
        "leaderboard": standings["leaderboard"],
    }


async def _has_contributions(s, raid: HalloweenRaid) -> bool:
    if int(raid.total_damage or 0) > 0:
        return True
    return bool(await s.scalar(
        select(HalloweenRaidPlayer.user_id).where(HalloweenRaidPlayer.damage > 0).limit(1)
    ))


async def _reset_raid(s, raid: HalloweenRaid | None, config: dict, at: datetime) -> None:
    stage, _ = halloween.stage_for(config, 1)
    if raid is not None:
        raid.hp = raid.max_hp = stage["max_hp"]
        raid.phase = 1
        raid.total_damage = 0
        raid.updated_at = at
    await s.execute(update(HalloweenRaidPlayer).values(
        last_tap_at=None, damage=0, kombucha_ids=[], stage_damage={}, gifts_received=[]
    ))


async def apply_config_change(s, old_config: dict, new_config: dict,
                              at: datetime | None = None) -> None:
    """Archive the previous season and reset shared progress only when its start changes."""
    at = at or datetime.now(timezone.utc)
    old_key, new_key = event_key(old_config), event_key(new_config)
    meta = await s.get(Setting, RAID_META_KEY, with_for_update=True)
    raid = await s.scalar(select(HalloweenRaid).where(HalloweenRaid.id == 1).with_for_update())
    saved = dict(meta.value or {}) if meta else {}
    current_key = str(saved.get("event_key") or old_key)
    last_summary = saved.get("last_summary")

    if current_key != new_key:
        previous_config = old_config if old_key == current_key else _config_from_meta(saved, old_config)
        has_contributions = raid is not None and await _has_contributions(s, raid)
        if has_contributions or _event_has_ended(previous_config, at):
            last_summary = await make_summary(s, raid, previous_config, current_key)
        await _reset_raid(s, raid, new_config, at)

    value = _meta_value(new_config, last_summary)
    if meta is None:
        s.add(Setting(key=RAID_META_KEY, value=value))
    else:
        meta.value = value


async def ensure_event_meta(s, config: dict, *, lock: bool) -> None:
    """Tag legacy/current progress on the first raid tap without resetting existing progress."""
    key = event_key(config)
    meta = await s.get(Setting, RAID_META_KEY, with_for_update=lock)
    if meta is None:
        if lock:
            s.add(Setting(key=RAID_META_KEY, value=_meta_value(config, None)))
        return
    saved = dict(meta.value or {})
    if saved.get("event_key") != key:
        # Configuration changes through the admin endpoint already roll seasons over.
        # Fail closed on an out-of-band config edit: reset on the next locked interaction.
        if lock:
            previous = _config_from_meta(saved, config)
            await apply_config_change(s, previous, config)
        return


def _event_has_ended(config: dict, at: datetime) -> bool:
    start = halloween._parse_dt(config.get("start_at"))
    end = halloween._parse_dt(config.get("end_at"))
    if start is None or start > at:
        return False
    return not bool(config.get("enabled")) or bool(end and end <= at)


async def inactive_summary(s, config: dict, at: datetime | None = None) -> dict | None:
    """Return the finished current season, or the most recently archived one."""
    at = at or datetime.now(timezone.utc)
    key = event_key(config)
    meta = await s.get(Setting, RAID_META_KEY)
    saved = dict(meta.value or {}) if meta else {}
    last_summary = saved.get("last_summary")
    saved_key = saved.get("event_key")
    if saved_key and saved_key != key:
        return last_summary

    raid = await s.get(HalloweenRaid, 1)
    ended = _event_has_ended(config, at)
    if raid is None:
        return await make_summary(s, None, config, key) if ended else last_summary
    has_contributions = await _has_contributions(s, raid)
    if not has_contributions and not ended:
        return last_summary

    return await make_summary(s, raid, config, key)
