"""Лиги клубов и конкурс красоты.

Неделя = ISO-неделя по Москве. Клуб попадает в дивизион (бронза…алмаз) и соревнуется с 49 соседями;
в конце недели лучшие 20% поднимаются, худшие 20% опускаются. Очки недели — суммарный вклад участников
(contribution_week), он же идёт в общий счёт клуба.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..models import BeautyVote, Club, ClubMember, League, LeagueMembership
from . import notifications

MSK = timezone(timedelta(hours=3))
UP_SHARE = 0.2
DOWN_SHARE = 0.2
LEAGUE_SEED = [("bronze", "Бронза", 1), ("silver", "Серебро", 2), ("gold", "Золото", 3),
               ("platinum", "Платина", 4), ("diamond", "Алмаз", 5)]
ORDER = {code: no for code, _, no in LEAGUE_SEED}


def now() -> datetime:
    return datetime.now(timezone.utc)


def week_key(at: datetime | None = None) -> str:
    iso = (at or now()).astimezone(MSK).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


async def ensure_leagues(s: AsyncSession) -> None:
    for code, title, no in LEAGUE_SEED:
        if await s.get(League, code) is None:
            s.add(League(code=code, title=title, order_no=no, size=50))
    await s.flush()


async def ensure_membership(s: AsyncSession, club: Club, week: str | None = None) -> LeagueMembership:
    week = week or week_key()
    row = await s.scalar(select(LeagueMembership).where(LeagueMembership.club_id == club.id,
                                                        LeagueMembership.week_key == week))
    if row is None:
        # Каталог дивизионов создаёт seed; без него вставка падала на FK и страница клуба
        # отвечала «Данные не прошли проверку». Досыпаем сами — идемпотентно.
        await ensure_leagues(s)
        last = await s.scalar(select(LeagueMembership).where(LeagueMembership.club_id == club.id)
                              .order_by(LeagueMembership.week_key.desc()))
        code = last.league_code if last and last.league_code in ORDER else "bronze"
        row = LeagueMembership(club_id=club.id, league_code=code, week_key=week, score=0)
        s.add(row)
        await s.flush()
    return row


async def add_score(s: AsyncSession, club: Club, amount: int) -> None:
    row = await ensure_membership(s, club)
    row.score += max(0, int(amount))


async def board(s: AsyncSession, club: Club, week: str | None = None) -> dict:
    week = week or week_key()
    mine = await ensure_membership(s, club, week)
    rows = (await s.scalars(select(LeagueMembership).where(LeagueMembership.league_code == mine.league_code,
                                                           LeagueMembership.week_key == week)
                            .order_by(LeagueMembership.score.desc()).limit(60))).all()
    rank = next((i + 1 for i, r in enumerate(rows) if r.club_id == club.id), None)
    clubs = {c.id: c for c in (await s.scalars(select(Club).where(
        Club.id.in_([r.club_id for r in rows or [0]])))).all()}
    return {"league": mine.league_code, "league_title": next((t for c, t, _ in LEAGUE_SEED if c == mine.league_code),
                                                             mine.league_code),
            "week": week, "score": mine.score, "rank": rank, "size": len(rows), "outcome": mine.outcome,
            "top": [{"tag": clubs[r.club_id].tag if r.club_id in clubs else "?",
                     "name": clubs[r.club_id].name if r.club_id in clubs else "?",
                     "emblem": clubs[r.club_id].emblem if r.club_id in clubs else "🍄",
                     "score": r.score, "me": r.club_id == club.id} for r in rows[:20]]}


async def settle_week(s: AsyncSession, week: str) -> int:
    """Повышение/понижение по итогам недели. Идемпотентно: outcome уже выставлен — пропускаем."""
    await ensure_leagues(s)
    codes = [c for c, _, _ in LEAGUE_SEED]
    changed = 0
    for code in codes:
        rows = (await s.scalars(select(LeagueMembership).where(LeagueMembership.league_code == code,
                                                               LeagueMembership.week_key == week)
                                .order_by(LeagueMembership.score.desc()))).all()
        if not rows:
            continue
        n = len(rows)
        up_n = max(1, int(n * UP_SHARE)) if n >= 3 else 0
        down_n = max(1, int(n * DOWN_SHARE)) if n >= 3 and code != "bronze" else 0
        for i, row in enumerate(rows):
            if row.outcome:
                continue
            row.rank = i + 1
            if i < up_n and ORDER[code] < len(codes):
                row.outcome = "up"
                new_code = codes[ORDER[code]]
                s.add(LeagueMembership(club_id=row.club_id, league_code=new_code, week_key=_next_week(week),
                                       score=0))
                club = await s.get(Club, row.club_id)
                if club is not None:
                    notifications.notify(s, club.leader_id, "club", club_id=club.id, event="league_up",
                                         league=new_code)
            elif i >= n - down_n:
                row.outcome = "down"
                new_code = codes[ORDER[code] - 2]
                s.add(LeagueMembership(club_id=row.club_id, league_code=new_code, week_key=_next_week(week),
                                       score=0))
            else:
                row.outcome = "stayed"
                s.add(LeagueMembership(club_id=row.club_id, league_code=code, week_key=_next_week(week), score=0))
            changed += 1
    return changed


def _next_week(week: str) -> str:
    year, num = week.split("-W")
    start = datetime.fromisocalendar(int(year), int(num), 1)
    nxt = start + timedelta(days=7)
    iso = nxt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


# ---------------------------------------------------------------- конкурс красоты
async def beauty_board(s: AsyncSession, week: str | None = None) -> list[dict]:
    week = week or week_key()
    rows = (await s.execute(select(BeautyVote.target_club_id, func.count(BeautyVote.id))
                            .where(BeautyVote.week_key == week)
                            .group_by(BeautyVote.target_club_id)
                            .order_by(func.count(BeautyVote.id).desc()).limit(20))).all()
    ids = [r[0] for r in rows]
    clubs = {c.id: c for c in (await s.scalars(select(Club).where(Club.id.in_(ids or [0])))).all()}
    return [{"club_id": cid, "tag": clubs[cid].tag if cid in clubs else "?", "name": clubs[cid].name if cid in clubs else "?",
             "emblem": clubs[cid].emblem if cid in clubs else "🍄", "color": clubs[cid].color if cid in clubs else "#888",
             "color2": clubs[cid].color2 if cid in clubs else "#aaa", "votes": n} for cid, n in rows]


async def vote_beauty(s: AsyncSession, user_id: int, club: Club, target_club_id: int) -> int:
    week = week_key()
    if target_club_id == club.id:
        raise ApiError("За свой клуб голосовать нельзя", 403, "club_vote_self")
    target = await s.get(Club, target_club_id)
    if target is None or target.status != "active":
        raise ApiError("Клуб не найден", 404, "club_not_found")
    if await s.scalar(select(BeautyVote.id).where(BeautyVote.user_id == user_id, BeautyVote.week_key == week)):
        raise ApiError("Один голос в неделю", 429, "club_vote_used")
    s.add(BeautyVote(user_id=user_id, club_id=club.id, target_club_id=target_club_id, week_key=week))
    return 0


async def settle_beauty(s: AsyncSession, week: str, prize: int = 1000) -> dict | None:
    board_ = await beauty_board(s, week)
    if not board_:
        return None
    winner_id = board_[0]["club_id"]
    club = await s.get(Club, winner_id)
    if club is not None:
        from . import clubs as clubs_svc
        clubs_svc._feed(s, club.id, None, "beauty", "👑 Наш клуб победил в конкурсе красоты недели!")
        club.settings = {**(club.settings or {}), "beauty_win_week": week, "beauty_prize": prize}
        club.account += prize
    return {"club_id": winner_id, "votes": board_[0]["votes"]}


async def weekly_score(s: AsyncSession, club: Club) -> int:
    total = await s.scalar(select(func.coalesce(func.sum(ClubMember.contribution_week), 0))
                           .where(ClubMember.club_id == club.id))
    return int(total or 0)
