"""Грибные кооперативы и Гриб-Танк: создание, роли, норма дня, беды, копилка, ивенты, лиги."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Club, ClubMember, ClubTank, User
from app.services import club_tank as tank
from app.services import clubs as clubs_svc


def _db(app, fn):
    from app.db import session_scope

    async def run():
        async with session_scope() as s:
            return await fn(s)
    with app.app_context():
        return asyncio.run(run())


def _give_wood(app, user_id, amount):
    from app.services import wood

    async def fn(s):
        await wood.earn(s, user_id, "mutation", f"test{amount}", amount)
    _db(app, fn)


def _edit_user(app, user_id, **fields):
    async def fn(s):
        u = await s.get(User, user_id)
        for key, value in fields.items():
            setattr(u, key, value)
    _db(app, fn)


def _alive(app):
    """Сделать аккаунт «живым» для вклада: возраст 4 дня и личный стрик."""
    async def fn(s):
        rows = (await s.execute(__import__("sqlalchemy").select(User))).scalars().all()
        for u in rows:
            u.created_at -= timedelta(days=4)
            u.streak_days = max(1, u.streak_days or 0)
            u.level = max(u.level or 1, 3)
    _db(app, fn)


def _edit_tank(app, club_id, **fields):
    async def fn(s):
        t = await s.get(ClubTank, club_id)
        for key, value in fields.items():
            setattr(t, key, value)
    _db(app, fn)


def _first_club(app):
    async def fn(s):
        return await s.scalar(__import__("sqlalchemy").select(Club).order_by(Club.id))
    return _db(app, fn)


_IP = __import__("itertools").count(1)


def _user(make_user, role="user"):
    """Тестовый клиент с собственным адресом: антиабуз клубов считает аккаунты на IP."""
    client, user = make_user(role)
    client.environ_base["REMOTE_ADDR"] = f"10.9.{next(_IP) // 250}.{next(_IP) % 250 + 1}"
    return client, user


def _make_club(client, user, name="Пример", tag="ЧАЙ"):
    return client.post("/api/clubs", json={"name": name, "tag": tag, "emblem": "🍵",
                                           "color": "#33cc88", "color2": "#1188ff",
                                           "join_mode": "open", "min_level": 1, "description": "тест"})


# ---------------------------------------------------------------- создание и вступление
def test_create_club_costs_and_unique_names(app, make_user):
    c, u = _user(make_user)
    # игрок вписывает только имя — «ООО и кавычки» подставляет сервер (проверяется ниже)
    assert c.post("/api/clubs", json={"name": "Тест", "tag": "ТЕ"}).status_code == 402          # нет $₽
    _give_wood(app, u["id"], 700)
    r = _make_club(c, u)
    assert r.status_code == 201, r.get_json()
    club = r.get_json()["club"]
    assert club["members"] == 1 and club["account"] == 0
    assert club["perks"]["xp_bonus"] == 0 and club["perks"]["active"] == []   # перки не выдаются сами
    assert club["capacity"] == 5
    assert club["tank"]["stage"]["title"] == "Спора-Танк"
    # уникальность названия и тега
    _give_wood(app, u["id"], 600)
    assert c.post("/api/clubs", json={"name": "Пример", "tag": "ДРУГ"}).status_code == 409
    # полная форма с «ООО» тоже ловится как дубль: имя после нормализации то же
    assert c.post("/api/clubs", json={"name": 'ООО "Пример"', "tag": "ДРУГ"}).status_code == 409
    # кулдаун смены клуба: выйти и создать/вступить нельзя сутки
    assert c.post(f"/api/clubs/{club['tag']}/leave", json={}).status_code == 200
    _give_wood(app, u["id"], 600)
    r = _make_club(c, u, name="Второй", tag="ВТ")
    assert r.status_code == 429 and r.get_json()["error"] == "club_cooldown"


def test_join_limits_and_request_flow(app, make_user):
    owner, o = _user(make_user)
    _give_wood(app, o["id"], 600)
    club = _make_club(owner, o).get_json()["club"]
    tag = club["tag"]
    # закрываем места: поднимаем счётчик до capacity
    async def shrink(s):
        row = await s.scalar(__import__("sqlalchemy").select(Club).where(Club.tag == tag))
        row.capacity = 1
    _db(app, shrink)
    other, _ = _user(make_user)
    r = other.post(f"/api/clubs/{tag}/join", json={})
    assert r.status_code == 409 and r.get_json()["error"] == "club_full"
    # режим «по заявке»
    async def to_request(s):
        row = await s.scalar(__import__("sqlalchemy").select(Club).where(Club.tag == tag))
        row.join_mode, row.capacity = "request", 5
    _db(app, to_request)
    r = other.post(f"/api/clubs/{tag}/join", json={"message": "Пустите"})
    assert r.status_code == 200 and r.get_json()["state"] == "requested"
    reqs = owner.get(f"/api/clubs/{tag}/requests").get_json()["items"]
    assert len(reqs) == 1 and reqs[0]["message"] == "Пустите"
    assert other.post(f"/api/clubs/{tag}/requests/{reqs[0]['id']}", json={"approve": True}).status_code == 403
    assert owner.post(f"/api/clubs/{tag}/requests/{reqs[0]['id']}", json={"approve": True}).status_code == 200
    assert other.get(f"/api/clubs/{tag}").get_json()["me"]["member"] is True
    # участник не может исключать
    assert other.delete(f"/api/clubs/{tag}/members/{o['id']}").status_code == 403


def test_one_club_per_account(app, make_user):
    """Один аккаунт — один кооператив: второй клуб создать или вступить нельзя."""
    c, u = _user(make_user)
    _give_wood(app, u["id"], 4000)
    first = _make_club(c, u)
    assert first.status_code == 201, first.get_json()

    second = c.post("/api/clubs", json={"name": "Второй", "tag": "ВТ"})
    assert second.status_code == 409 and second.get_json()["error"] == "already_in_club", second.get_json()

    # в чужой клуб тоже не пускает
    other, o = _user(make_user)
    _give_wood(app, o["id"], 600)
    other_tag = _make_club(other, o, name="Соседний", tag="СОС").get_json()["club"]["tag"]
    r = c.post(f"/api/clubs/{other_tag}/join", json={})
    assert r.status_code == 409 and r.get_json()["error"] == "already_in_club"

    # в БД ровно одно участие, даже если кто-то пытается вставить второе напрямую
    from sqlalchemy.exc import IntegrityError

    async def dup(s):
        s.add(ClubMember(club_id=__import__("sqlalchemy").select(Club.id)
                         .where(Club.tag == other_tag).scalar_subquery(), user_id=u["id"], role="member"))
        await s.flush()
    with pytest.raises(IntegrityError):
        _db(app, dup)

    async def memberships(s):
        return (await s.scalars(__import__("sqlalchemy").select(ClubMember.club_id)
                                .where(ClubMember.user_id == u["id"]))).all()
    assert len(_db(app, memberships)) == 1


def test_approved_request_of_moved_player_is_stopped(app, make_user):
    """Заявку нельзя одобрить тому, кто за это время уже основал свой кооператив."""
    owner, o = _user(make_user)
    _give_wood(app, o["id"], 600)
    club = _make_club(owner, o, name="Заявочный", tag="ЗАЯ").get_json()["club"]
    tag = club["tag"]

    async def to_request(s):
        row = await s.scalar(__import__("sqlalchemy").select(Club).where(Club.tag == tag))
        row.join_mode = "request"
    _db(app, to_request)

    guest, g = _user(make_user)
    _give_wood(app, g["id"], 4000)
    assert guest.post(f"/api/clubs/{tag}/join", json={"message": "Пустите"}).status_code == 200

    # пока заявка висела, игрок основал свой клуб
    own = _make_club(guest, g, name="Свой", tag="СВО")
    assert own.status_code == 201, own.get_json()

    reqs = owner.get(f"/api/clubs/{tag}/requests").get_json()["items"]
    assert len(reqs) == 1
    r = owner.post(f"/api/clubs/{tag}/requests/{reqs[0]['id']}", json={"approve": True})
    assert r.status_code == 409 and r.get_json()["error"] == "already_in_club", r.get_json()

    async def memberships(s):
        return (await s.scalars(__import__("sqlalchemy").select(ClubMember.club_id)
                                .where(ClubMember.user_id == g["id"]))).all()
    only = _db(app, memberships)
    assert len(only) == 1 and only[0] == own.get_json()["club"]["id"]


def test_roles_and_transfer(app, make_user):
    owner, o = _user(make_user)
    _give_wood(app, o["id"], 600)
    tag = _make_club(owner, o).get_json()["club"]["tag"]
    m1, u1 = _user(make_user)
    assert m1.post(f"/api/clubs/{tag}/join", json={}).status_code == 201
    # замов не больше трёх
    assert owner.patch(f"/api/clubs/{tag}/members/{u1['id']}", json={"role": "deputy"}).status_code == 200
    assert owner.patch(f"/api/clubs/{tag}/members/{u1['id']}", json={"role": "deputy"}).status_code == 200
    # передача главенства
    assert owner.patch(f"/api/clubs/{tag}/members/{u1['id']}", json={"role": "leader"}).status_code == 200
    club = owner.get(f"/api/clubs/{tag}").get_json()
    assert club["leader_id"] == u1["id"]
    assert club["me"]["role"] == "deputy"          # прежний глава стал замом
    # новый глава может исключить прежнего
    assert m1.delete(f"/api/clubs/{tag}/members/{o['id']}").status_code == 200


def test_norm_of_day_and_antiabuse(app, make_user):
    owner, o = _user(make_user)
    _give_wood(app, o["id"], 600)
    tag = _make_club(owner, o).get_json()["club"]["tag"]
    members = []
    for _ in range(2):
        c, u = _user(make_user)
        c.post(f"/api/clubs/{tag}/join", json={})
        members.append((c, u))
    # норму считаем только с живых аккаунтов
    r = owner.post(f"/api/clubs/{tag}/tank/sugar", json={})
    assert r.status_code == 403 and r.get_json()["error"] == "club_contribution_blocked"
    _alive(app)
    # вклад пошёл, норма из 3 участников выполнена
    for client, _ in [(owner, o)] + members:
        assert client.post(f"/api/clubs/{tag}/tank/pet", json={}).status_code == 200
    state = owner.get(f"/api/clubs/{tag}").get_json()["tank"]
    assert state["norm"]["done"] == 3 and state["norm"]["ok"] is True
    # суточный потолок вклада в показатель
    codes = []
    for _ in range(tank.TANK_DAILY_PER_STAT):
        codes.append(owner.post(f"/api/clubs/{tag}/tank/sugar", json={}).status_code)
    assert 429 in codes and owner.post(f"/api/clubs/{tag}/tank/sugar", json={}).get_json()["error"] in ("club_cap", "cooldown")


def test_tank_decay_and_party_scale(app, make_user):
    owner, o = _user(make_user)
    _give_wood(app, o["id"], 600)
    tag = _make_club(owner, o).get_json()["club"]["tag"]
    club_id = _first_club(app).id
    c2, _ = _user(make_user)
    c2.post(f"/api/clubs/{tag}/join", json={})
    before = owner.get(f"/api/clubs/{tag}").get_json()["tank"]
    _edit_tank(app, club_id, updated_at=datetime.now(timezone.utc) - tank.PERIOD)
    after = owner.get(f"/api/clubs/{tag}").get_json()["tank"]
    assert after["stats"]["sweet"] < before["stats"]["sweet"]     # ступенька упала
    assert after["party_scale"] > 1.0
    # масштаб от состава растёт
    assert tank.party_scale(40) == pytest.approx(1.5) and tank.party_scale(1) == 1.0
    # «Танк на последней стадии не делится» — деления у Танка нет вовсе
    assert not hasattr(tank, "split")


def test_mold_needs_three_members_and_tank_dies_forever(app, make_user):
    owner, o = _user(make_user)
    _give_wood(app, o["id"], 600)
    tag = _make_club(owner, o).get_json()["club"]["tag"]
    club_id = _first_club(app).id
    c2, _ = _user(make_user)
    c2.post(f"/api/clubs/{tag}/join", json={})
    c3, _ = _user(make_user)
    c3.post(f"/api/clubs/{tag}/join", json={})
    _alive(app)
    _edit_tank(app, club_id, mold=True, clean=10.0)
    first = owner.post(f"/api/clubs/{tag}/tank/clean", json={})
    assert first.status_code == 200 and first.get_json()["cured"] is False
    second = c2.post(f"/api/clubs/{tag}/tank/clean", json={})
    assert second.status_code == 200 and second.get_json()["cured"] is False
    r = c3.post(f"/api/clubs/{tag}/tank/clean", json={}).get_json()
    assert r["cured"] is True and r["tank"]["mold"] is False
    # закисший Танк не возрождается
    _edit_tank(app, club_id, alive=False, mold=False)
    r = owner.post(f"/api/clubs/{tag}/tank/sugar", json={})
    assert r.status_code == 409 and r.get_json()["error"] == "tank_dead"


def test_bank_cannot_be_withdrawn(app, make_user):
    owner, o = _user(make_user)
    _give_wood(app, o["id"], 1600)
    tag = _make_club(owner, o).get_json()["club"]["tag"]
    assert owner.post(f"/api/clubs/{tag}/bank", json={"amount": 40}).status_code == 400     # меньше 50
    assert owner.post(f"/api/clubs/{tag}/bank", json={"amount": 300}).get_json()["account"] == 300
    bank = owner.get(f"/api/clubs/{tag}/bank").get_json()
    assert bank["items"][0]["delta"] == 300 and bank["items"][0]["reason_title"] == "взнос"
    # апгрейд мест и уровня
    _give_wood(app, o["id"], 500)
    assert owner.post(f"/api/clubs/{tag}/bank", json={"amount": 500}).status_code == 200
    lvl = owner.post(f"/api/clubs/{tag}/upgrades", json={"kind": "level"})
    cap = owner.post(f"/api/clubs/{tag}/upgrades", json={"kind": "capacity"})
    assert (lvl.status_code, cap.status_code) == (200, 200), (lvl.get_json(), cap.get_json())
    assert lvl.get_json()["level"] == 2 and cap.get_json()["capacity"] == 10
    # вывода из копилки нет ни у кого: тратят только на апгрейды/ивенты
    assert not hasattr(clubs_svc, "withdraw")


def test_perks_exist_only_while_lab_prep_lasts(app, make_user):
    """Перк — не пассивка: он есть только пока действует собранный в лаборатории препарат."""
    owner, o = _user(make_user)
    _alive(app)
    _give_wood(app, o["id"], 6000)
    tag = _make_club(owner, o, name="Лабораторный", tag="ЛАБ").get_json()["club"]["tag"]

    async def personal_bonus(s):
        return float((await clubs_svc.club_bonus_for(s, o["id"])).get("xp_bonus", 0.0))

    # без препарата у персонального гриба нет клубных бонусов
    assert owner.get(f"/api/clubs/{tag}").get_json()["perks"]["xp_bonus"] == 0
    assert _db(app, personal_bonus) == 0

    async def set_prep(s, until_iso):
        row = await s.scalar(__import__("sqlalchemy").select(Club).where(Club.tag == tag))
        row.settings = {**(row.settings or {}), "lab": [{"kind": "xp_bonus", "value": 0.5, "until": until_iso}]}
    future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    _db(app, lambda s: set_prep(s, future))
    perks = owner.get(f"/api/clubs/{tag}").get_json()["perks"]
    assert perks["xp_bonus"] > 0 and perks["active"]
    assert _db(app, personal_bonus) > 0

    # время вышло — препарат больше ничего не даёт, хотя запись в настройках осталась
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    _db(app, lambda s: set_prep(s, past))
    assert owner.get(f"/api/clubs/{tag}").get_json()["perks"]["xp_bonus"] == 0
    assert _db(app, personal_bonus) == 0


def test_raid_and_wars_and_league_and_beauty(app, make_user):
    owner, o = _user(make_user)
    _give_wood(app, o["id"], 900)
    tag = _make_club(owner, o).get_json()["club"]["tag"]
    _alive(app)
    # рейд: урон от ухода уменьшает HP босса
    r = owner.post(f"/api/clubs/{tag}/events/raid/start", json={})
    assert r.status_code == 200 and r.get_json()["hp"] > 0
    before = owner.get(f"/api/clubs/{tag}/events").get_json()["raid"]["hp"]
    owner.post(f"/api/clubs/{tag}/tank/sugar", json={})
    after = owner.get(f"/api/clubs/{tag}/events").get_json()["raid"]["hp"]
    assert after < before
    # лиги: клуб видит себя в бронзе с очками недели
    league = owner.get(f"/api/clubs/{tag}/league").get_json()
    assert league["league"] == "bronze" and league["rank"] >= 1
    # конкурс: за свой клуб нельзя
    club_id = owner.get(f"/api/clubs/{tag}").get_json()["id"]
    r = owner.post(f"/api/clubs/{tag}/beauty", json={"club_id": club_id})
    assert r.status_code == 403 and r.get_json()["error"] == "club_vote_self"
    # войны: подбор пар и потолок очков на человека
    c2, u2 = _user(make_user)
    _give_wood(app, u2["id"], 600)
    tag2 = _make_club(c2, u2, name='ООО "Соседи"', tag="СОС").get_json()["club"]["tag"]
    assert owner.post("/admin/events/world/raid/run", json={}).status_code in (401, 403)   # не админ
    from app.services import club_events

    async def make_war(s):
        return await club_events.start_week(s, club_events.week_key())

    assert _db(app, make_war) >= 1
    war = owner.get(f"/api/clubs/{tag}/events").get_json()["war"]
    assert war and war["enemy"]["tag"] == tag2
    # глава выбирает состав (гриб не из клуба — отказ)
    bad = owner.post(f"/api/clubs/{tag}/war/team", json={"mushroom_ids": [999999]})
    assert bad.status_code == 404 and bad.get_json()["error"] == "club_war_mushroom_missing"


def test_lab_prep_and_mutation_craft(app, make_user):
    owner, o = _user(make_user)
    _give_wood(app, o["id"], 600)
    tag = _make_club(owner, o).get_json()["club"]["tag"]
    _give_wood(app, o["id"], 6000)
    for _ in range(3):
        assert owner.post("/api/shop/jar", json={}).status_code == 200     # три банки под грибы участников
    kid = owner.get("/api/kombucha").get_json()["items"][0]["id"]
    r = owner.post(f"/api/clubs/{tag}/lab/drain", json={"kombucha_id": kid, "kind": "xp_bonus"})
    assert r.status_code == 200 and r.get_json()["ready_at"]
    run_id = r.get_json()["id"]
    # сразу собрать нельзя
    assert owner.post(f"/api/clubs/{tag}/lab/collect/{run_id}", json={}).status_code == 429
    # 48-часовой кулдаун на слив
    assert owner.post(f"/api/clubs/{tag}/lab/drain", json={"kombucha_id": kid, "kind": "xp_bonus"}).status_code == 429

    async def ready(s):
        from app.models import ClubLabRun
        run = await s.get(ClubLabRun, run_id)
        run.ready_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    _db(app, ready)
    prep = owner.post(f"/api/clubs/{tag}/lab/collect/{run_id}", json={}).get_json()["prep"]
    assert prep["kind"] == "xp_bonus" and prep["value"] > 0
    page = owner.get(f"/api/clubs/{tag}").get_json()
    perks = page["perks"]
    assert perks["xp_bonus"] == prep["value"] > 0       # перк дал ровно препарат из лаборатории
    assert perks["active"] and perks["active"][0]["kind"] == "xp_bonus"

    # крафт мутации Танка: три гриба клуба отдают мутации, грибы получают «Раненого»
    names = []
    for i in range(3):
        names.append(owner.post("/api/kombucha/plant", json={"name": f"Лаба{i}"}).get_json()["kombucha"])
    async def muts(s):
        from app.models import Kombucha
        from app.services import kombucha as kb
        rows = []
        for n in names:
            k = await s.get(Kombucha, n["id"])
            await kb.add_mutation(s, k, kb.MUT_BY_CODE["sparkle"], kb.now())
            rows.append(k.id)
        return rows
    ids = _db(app, muts)
    r = owner.post(f"/api/clubs/{tag}/lab/craft", json={"mushroom_ids": ids, "stage": 1})
    assert r.status_code == 201, r.get_json()
    data = owner.get(f"/api/clubs/{tag}").get_json()["tank"]
    assert len(data["mutations"]) == 1 and data["mutations"][0]["stage"] == 1
    assert data["attack"] >= 5
    async def wounded(s):
        from app.models import Kombucha
        for kid in ids:
            k = await s.get(Kombucha, kid)
            assert k.wounded_until is not None and not (k.mutations or [])
    _db(app, wounded)


def test_notification_and_help_call(app, make_user):
    owner, o = _user(make_user)
    _give_wood(app, o["id"], 600)
    tag = _make_club(owner, o).get_json()["club"]["tag"]
    c2, u2 = _user(make_user)
    c2.post(f"/api/clubs/{tag}/join", json={})
    assert c2.post(f"/api/clubs/{tag}/tank/help", json={}).get_json()["sent"] == 1
    assert c2.post(f"/api/clubs/{tag}/tank/help", json={}).status_code == 429      # раз в 6 часов
    notif = owner.get("/api/notifications").get_json()
    kinds = {n["kind"] for n in notif.get("items", [])}
    assert "club" in kinds


def test_disband_goes_to_museum(app, make_user):
    owner, o = _user(make_user)
    _give_wood(app, o["id"], 600)
    tag = _make_club(owner, o).get_json()["club"]["tag"]
    async def old(s):
        row = await s.scalar(__import__("sqlalchemy").select(Club).where(Club.tag == tag))
        row.last_active_at = datetime.now(timezone.utc) - timedelta(days=31)
        await clubs_svc.check_inactive(s, row)
    _db(app, old)
    assert owner.get(f"/api/clubs/{tag}").status_code == 404
    museum = owner.get("/api/clubs/museum").get_json()["items"]
    assert museum and museum[0]["tag"] == tag


def test_ip_limit_blocks_third_account(app, make_user):
    """«Не больше 2 аккаунтов на IP/устройство» — реальная проверка (в тестах антибот не отключён)."""
    owner, o = _user(make_user)
    _give_wood(app, o["id"], 600)
    tag = _make_club(owner, o).get_json()["club"]["tag"]
    addr = "10.77.0.1"
    second, _ = _user(make_user)
    second.environ_base["REMOTE_ADDR"] = addr
    third, _ = _user(make_user)
    third.environ_base["REMOTE_ADDR"] = addr
    assert second.post(f"/api/clubs/{tag}/join", json={}).status_code == 201
    assert third.post(f"/api/clubs/{tag}/join", json={}).status_code == 201     # ровно два аккаунта с адреса
    fourth, _ = _user(make_user)
    fourth.environ_base["REMOTE_ADDR"] = addr
    r = fourth.post(f"/api/clubs/{tag}/join", json={})
    assert r.status_code == 403 and r.get_json()["error"] == "club_ip_limit", r.get_json()


def test_demo_grant_is_hidden_without_demo_mode(app, make_user):
    """Демо-пополнение кошелька существует только в DEMO_MODE (превью/e2e)."""
    c, _ = make_user()
    assert c.post("/api/clubs/dev/grant", json={"amount": 100}).status_code == 404


def test_club_reminders_via_notification_jobs(app, make_user):
    """Планировщик шлёт клубные напоминания: плесень, голод, норма дня за 4 часа, стрик под угрозой."""
    from app.services import notification_jobs as jobs
    from app.services.club_tank import MSK

    owner, o = _user(make_user)
    _give_wood(app, o["id"], 600)
    tag = _make_club(owner, o).get_json()["club"]["tag"]
    club_id = _first_club(app).id
    _edit_tank(app, club_id, mold=True, clean=12.0)

    late = datetime.combine((datetime.now(MSK) + timedelta(days=2)).date(), datetime.min.time(),
                            tzinfo=MSK) - timedelta(hours=2)   # 22:00 МСК следующего дня

    async def run(s):
        return await jobs.scan_notifications(at=late)
    jobs_created = _db(app, run)
    assert jobs_created["created"] >= 1

    async def reminders(s):
        from app.models import Notification
        rows = (await s.execute(__import__("sqlalchemy").select(Notification))).scalars().all()
        return [(r.payload or {}).get("text", "") for r in rows if r.kind == "club"]
    texts = _db(app, reminders)
    assert any("плесень" in t.lower() for t in texts), texts
    assert any("норма дня" in t.lower() for t in texts), texts


def test_raid_and_war_rewards_are_badges_for_starters(app, make_user):
    """Награды ивентов — только бейджи и только стартовому составу (никаких «шапок»)."""
    from app.services import club_events
    from app.models import ClubWar, UserBadge

    owner, o = _user(make_user)
    _give_wood(app, o["id"], 600)
    tag = _make_club(owner, o).get_json()["club"]["tag"]
    _alive(app)
    started = owner.post(f"/api/clubs/{tag}/events/raid/start", json={}).get_json()
    # Поздний участник: вступил уже после старта рейда — бейджа не получит.
    late, lu = _user(make_user)
    late.post(f"/api/clubs/{tag}/join", json={})

    async def almost_dead(s):
        from app.models import ClubEventProgress
        raid = await s.get(ClubEventProgress, started["id"])
        raid.hp = 1
    _db(app, almost_dead)
    owner.post(f"/api/clubs/{tag}/tank/sugar", json={})       # урон добивает босса

    async def badges(s):
        rows = (await s.execute(__import__("sqlalchemy").select(UserBadge))).scalars().all()
        return [(r.user_id, r.code) for r in rows]
    got = _db(app, badges)
    assert (o["id"], "club_raid_win") in got
    assert (lu["id"], "club_raid_win") not in got                 # поздний не в стартовом составе
    assert all(code != "club_war_win" for _, code in got)

    async def profiles(s):
        rows = (await s.execute(__import__("sqlalchemy").select(User))).scalars().all()
        return [u.profile or {} for u in rows]
    assert all("club_hat" not in p for p in _db(app, profiles))    # шапок клубов не существует
    assert not hasattr(club_events.tank_svc, "grant_hat_all")

    # Война: бейдж победителю — тоже по снапшоту состава.
    other, ou = _user(make_user)
    _give_wood(app, ou["id"], 600)
    _make_club(other, ou, name='ООО "Соперник"', tag="СОП")

    async def run_war(s):
        week = club_events.week_key()
        assert await club_events.start_week(s, week) >= 1
        war = await s.scalar(__import__("sqlalchemy").select(ClubWar).order_by(ClubWar.id.desc()))
        war.state = "picking"                      # состав не выбран: бой идёт «по умолчанию»
        await s.flush()
        return await club_events.settle_wars(s, week)
    assert _db(app, run_war) >= 1
    after = _db(app, badges)
    assert any(code == "club_war_win" for _, code in after), after


def test_name_is_wrapped_into_ooo_format(app, make_user):
    """Игрок вписывает только имя — «ООО "…"» сервер подставляет сам."""
    c, u = _user(make_user)
    _give_wood(app, u["id"], 4000)
    r = c.post("/api/clubs", json={"name": "Ромашка", "tag": "РОМ"})
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["club"]["name"] == 'ООО "Ромашка"'
    # пустое/слишком короткое/слишком длинное имя и запрещённый символ — отказ с подсказкой про формат
    for bad in ("", "Я", "О" * 19, "имя!"):
        r = c.post("/api/clubs", json={"name": bad, "tag": "БАД"})
        assert r.status_code == 400 and r.get_json()["error"] == "validation_error", (bad, r.get_json())
        assert "ООО" in r.get_json()["message"]


def test_full_name_form_is_not_doubled(app, make_user):
    """Если игрок всё-таки вписал «ООО "Имя"» — префикс не удваиваем."""
    c, u = _user(make_user)
    _give_wood(app, u["id"], 4000)
    r = c.post("/api/clubs", json={"name": 'ООО "Ромашка"', "tag": "РОМ"})
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["club"]["name"] == 'ООО "Ромашка"'


def test_typographic_quotes_are_stripped(app, make_user):
    """«Имя» в типографских кавычках — тоже просто имя."""
    c, u = _user(make_user)
    _give_wood(app, u["id"], 4000)
    r = c.post("/api/clubs", json={"name": "«Василёк»", "tag": "ВАС"})
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["club"]["name"] == 'ООО "Василёк"'


def _balance(app, uid):
    from app.db import session_scope
    from app.services import wood

    async def fn(s):
        return await wood.balance(s, uid)
    return _db(app, fn)


def test_admins_create_clubs_for_free(app, make_user):
    """Администраторы основывают кооперативы без списания 500 $₽."""
    admin, a = _user(make_user, "admin")
    plain, pu = _user(make_user)

    admin_before = _balance(app, a["id"])
    assert admin_before < 500                                  # денег на создание заведомо не хватает
    r = admin.post("/api/clubs", json={"name": "Бесплатный", "tag": "БЕС"})
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["free"] is True
    assert _balance(app, a["id"]) == admin_before               # ничего не списали

    # Обычный игрок по-прежнему платит: без денег — 402.
    plain_before = _balance(app, pu["id"])
    assert plain_before < 500
    assert plain.post("/api/clubs", json={"name": "Платный", "tag": "ПЛА"}).status_code == 402
    # и «free» из тела запроса игнорируется — флаг считает только сервер по правам
    assert plain.post("/api/clubs", json={"name": "Хитрый", "tag": "ХИТ", "free": True}).status_code == 402


def test_admin_gets_new_perms_without_reseed(app, make_user):
    """Жалоба «админ, а бесплатно создать не могу, ивенты и дебаг клубов недоступны».

    Причина — в БД/кэше прав нет новых прав из каталога (`clubs.manage`, `events.manage`).
    После деплоя они должны появиться сами: без ручного `flask --app app seed` и без
    ожидания истечения старого кэша прав в Redis.
    """
    from sqlalchemy import select, text

    from app.auth import rbac
    from app.extensions import get_redis

    admin, a = _user(make_user, "admin")

    async def wipe(s):
        await s.execute(text("delete from role_permissions rp using permissions p "
                             "where rp.permission_id = p.id and p.code in ('clubs.manage','events.manage')"))
        await s.execute(text("delete from permissions where code in ('clubs.manage','events.manage')"))
    _db(app, wipe)

    with app.app_context():                      # старый кэш прав (ключ без версии каталога)
        r = get_redis()
        r.sadd(f"perm:{a['id']}", "kombucha.play", "market.trade")
        r.expire(f"perm:{a['id']}", 300)
    getattr(rbac, "reset_catalog_cache", lambda: None)()   # как в свежем процессе после деплоя

    got = admin.get("/api/auth/me").get_json()["permissions"]
    assert "clubs.manage" in got and "events.manage" in got, got

    async def catalog(s):
        from app.models import Permission
        rows = (await s.scalars(select(Permission.code))).all()
        return set(rows)
    assert {"clubs.manage", "events.manage"} <= _db(app, catalog)   # каталог досыпан сам

    assert admin.get("/admin/clubs").status_code == 200
    assert admin.get("/admin/events/world").status_code == 200
    r = admin.post("/api/clubs", json={"name": "Бесплатный", "tag": "БЕС"})
    assert r.status_code == 201 and r.get_json()["free"] is True, r.get_json()


def test_club_page_self_heals_missing_league_catalog(app, make_user):
    """«Данные не прошли проверку» после создания клуба: пустой каталог дивизионов.

    Страница клуба (GET /api/clubs/<tag>) заводит клуб в лигу, а вставка ссылается на
    справочник club_leagues. Если seed не наполнял справочник — раньше падал FK и игрок
    видел безликую ошибку на своей же новой странице. Теперь справочник досыпается сам.
    """
    from sqlalchemy import text

    c, u = _user(make_user)
    _give_wood(app, u["id"], 700)
    r = _make_club(c, u)
    assert r.status_code == 201, r.get_json()
    tag = r.get_json()["club"]["tag"]

    async def wipe(s):
        await s.execute(text("delete from club_league_memberships"))
        await s.execute(text("delete from club_leagues"))
    _db(app, wipe)

    page = c.get(f"/api/clubs/{tag}")
    assert page.status_code == 200, page.get_json()
    assert page.get_json()["tank"]["league"]["league"] == "bronze"

    async def codes(s):
        from app.models import League
        return set((await s.scalars(__import__("sqlalchemy").select(League.code))).all())
    assert "bronze" in _db(app, codes)                     # справочник восстановлен


def test_dev_reset_only_in_demo_mode(app, make_user):
    """DEMO_MODE-хелпер сбрасывает участие и кулдаун; в проде его нет."""
    c, u = _user(make_user)
    assert c.post("/api/clubs/dev/reset", json={}).status_code == 404
