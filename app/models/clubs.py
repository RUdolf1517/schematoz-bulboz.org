from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Club(Base):
    """Грибной кооператив: название в кавычках («ООО „Пример“»), тег [ЧАЙ], герб-эмодзи и цвета.

    Всё «горячее» (показатели Танка, норма дня, стрик) живёт в ClubTank и считается лениво
    по времени — как у личного гриба (app/services/club_tank.py), без кронов на каждый шаг.
    """
    __tablename__ = "clubs"
    __table_args__ = (
        Index("uq_clubs_name_lower", text("lower(name)"), unique=True),
        Index("uq_clubs_tag_lower", text("lower(tag)"), unique=True),
        Index("ix_clubs_active", "status", text("last_active_at DESC")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(24))                   # внутри кавычек: «Пример»
    tag: Mapped[str] = mapped_column(String(5))                     # [ЧАЙ]
    emblem: Mapped[str] = mapped_column(String(16), default="🍄", server_default="🍄")
    color: Mapped[str] = mapped_column(String(9), default="#ff5a36", server_default="#ff5a36")
    color2: Mapped[str] = mapped_column(String(9), default="#ff8a3d", server_default="#ff8a3d")
    description: Mapped[str] = mapped_column(String(280), default="", server_default="")
    join_mode: Mapped[str] = mapped_column(String(8), default="open", server_default="open")   # open | request | invite
    min_level: Mapped[int] = mapped_column(default=1, server_default="1")
    leader_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    members: Mapped[int] = mapped_column(default=1, server_default="1")        # денормализованный счётчик для лимитов
    capacity: Mapped[int] = mapped_column(default=5, server_default="5")       # апгрейды: 5 → 40
    level: Mapped[int] = mapped_column(default=1, server_default="1")          # уровень клуба (ангар/косметика)
    xp: Mapped[int] = mapped_column(default=0, server_default="0")             # суммарный вклад за всю жизнь (для лиг)
    account: Mapped[int] = mapped_column(default=0, server_default="0")        # «копилка» в $₽ — вывести никому нельзя
    # пассивные перки: {"xp_bonus": 0.05, "mut_chance": 0.01, "decay_slow": 0.05}
    perks: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(12), default="active", server_default="active",
                                        index=True)  # active | banned | disbanded
    week_key: Mapped[str | None] = mapped_column(String(8))                    # ISO-неделя последнего пересчёта
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    disbanded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disband_reason: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ClubMember(Base):
    """Участник кооператива. Роли: leader (SEO), deputy (зам, до 3), member (грибник)."""
    __tablename__ = "club_members"
    __table_args__ = (Index("ix_club_members_user", "user_id"),)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(8), default="member", server_default="member")   # leader | deputy | member
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    contribution_week: Mapped[int] = mapped_column(default=0, server_default="0")
    contribution_total: Mapped[int] = mapped_column(default=0, server_default="0")
    contrib_week_key: Mapped[str | None] = mapped_column(String(8))
    last_contribution_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_help_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))   # «Позвать на помощь»
    warned_inactive: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class ClubJoinRequest(Base):
    """Заявка на вступление (для join_mode=request)."""
    __tablename__ = "club_join_requests"
    __table_args__ = (Index("ix_club_join_requests_club", "club_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    message: Mapped[str | None] = mapped_column(String(140))
    status: Mapped[str] = mapped_column(String(8), default="pending", server_default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ClubInvite(Base):
    """Инвайт-ссылка: /c/<тег>?invite=<code>. Одноразовые и многоразовые."""
    __tablename__ = "club_invites"
    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(24), unique=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    max_uses: Mapped[int] = mapped_column(default=1, server_default="1")
    uses: Mapped[int] = mapped_column(default=0, server_default="0")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClubTank(Base):
    """Гриб-Танк — общая 20-литровая банка клуба. Показатели хранятся «на момент updated_at»,
    убывание (шаги раз в 12 ч) досчитывается при чтении — club_tank.tick()."""
    __tablename__ = "club_tanks"
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), primary_key=True)
    xp: Mapped[int] = mapped_column(default=0, server_default="0")
    best_xp: Mapped[int] = mapped_column(default=0, server_default="0")
    sweet: Mapped[float] = mapped_column(default=70.0)
    tea: Mapped[float] = mapped_column(default=70.0)
    clean: Mapped[float] = mapped_column(default=90.0)
    happy: Mapped[float] = mapped_column(default=70.0)
    hp: Mapped[float] = mapped_column(default=100.0)
    hp_max: Mapped[float] = mapped_column(default=100.0)
    mold: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # лечение плесени: [{"user_id":…, "at": iso}] — нужно N разных участников за 24 ч
    mold_cures: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    alive: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    zero_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    died_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))     # закис — не возрождается
    # шрамы (из рейдов/войн): [{"code": "…", "at": iso, "note": "…"}]
    scars: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    cooldowns: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    born_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClubTankMutation(Base):
    """Клубная мутация Танка: до одной на стадию, добывается в лаборатории."""
    __tablename__ = "club_tank_mutations"
    __table_args__ = (UniqueConstraint("club_id", "stage", name="uq_club_tank_mutations_stage"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    stage: Mapped[int]
    crafted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    crafted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClubBankTx(Base):
    """Журнал копилки: взносы и траты. ref — идемпотентность повторов."""
    __tablename__ = "club_bank_tx"
    __table_args__ = (Index("uq_club_bank_tx_ref", "club_id", "reason", "ref", unique=True),
                      Index("ix_club_bank_tx_club", "club_id", text("id DESC")))
    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    delta: Mapped[int]
    reason: Mapped[str] = mapped_column(String(24))     # deposit | upgrade | streak_freeze | raid | perk | disband
    ref: Mapped[str] = mapped_column(String(64))
    balance_after: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClubPost(Base):
    """Лента клуба: автособытия (kind=auto) и короткие посты участников (kind=user, до 280 символов)."""
    __tablename__ = "club_posts"
    __table_args__ = (Index("ix_club_posts_feed", "club_id", text("id DESC")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(8), default="auto", server_default="auto")
    event: Mapped[str | None] = mapped_column(String(24))     # join | care | mutation | mold | legend | raid | war | post
    body: Mapped[str] = mapped_column(String(280))
    emoji: Mapped[str] = mapped_column(String(16), default="📝", server_default="📝")
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ClubReaction(Base):
    """Эмодзи-реакция участника на пост ленты: одна на юзера на пост на эмодзи."""
    __tablename__ = "club_reactions"
    __table_args__ = (UniqueConstraint("post_id", "user_id", "emoji", name="uq_club_reactions_post_user_emoji"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("club_posts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    emoji: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClubReport(Base):
    """Жалоба на пост ленты — разбирает админ во вкладке «Клубы»."""
    __tablename__ = "club_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), index=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("club_posts.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(8), default="open", server_default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ClubBannedUser(Base):
    """Локальный бан в клубе (кик с запретом возврата)."""
    __tablename__ = "club_banned_users"
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str | None] = mapped_column(String(140))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClubLabRun(Base):
    """«Комбуча в лабораторию»: участник обнуляет показатель своего гриба,
    через 12 ч получается препарат-перк, действующий 24 ч."""
    __tablename__ = "club_lab_runs"
    __table_args__ = (Index("ix_club_lab_runs_club", "club_id", "ready_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kombucha_id: Mapped[int] = mapped_column(ForeignKey("kombuchas.id", ondelete="CASCADE"))
    stat: Mapped[str] = mapped_column(String(8))           # обнулённый показатель: sweet|tea|clean|happy
    kind: Mapped[str] = mapped_column(String(12))          # xp_bonus | mut_chance | decay_slow
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ready_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClubLabCraft(Base):
    """Крафт боевой мутации Танка из мутаций грибов участников (до 3 грибов)."""
    __tablename__ = "club_lab_crafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(32))
    mushroom_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClubEventProgress(Base):
    """Прогресс клубного события: рейд «Великая плесень», войны, мировые ивенты, конкурс."""
    __tablename__ = "club_event_progress"
    __table_args__ = (Index("ix_club_event_progress_kind", "kind", "week_key"),
                      Index("ix_club_event_progress_club", "club_id", text("id DESC")))
    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(12))          # raid | war | world | beauty
    ref: Mapped[str] = mapped_column(String(32))           # код события/неделя — ключ идемпотентности
    week_key: Mapped[str | None] = mapped_column(String(8))
    hp: Mapped[int] = mapped_column(default=0, server_default="0")            # у босса/врага
    hp_max: Mapped[int] = mapped_column(default=0, server_default="0")
    score: Mapped[int] = mapped_column(default=0, server_default="0")
    state: Mapped[str] = mapped_column(String(10), default="running", server_default="running")  # running | won | lost
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class League(Base):
    """Лига клуба: бронза → серебро → золото → платина → алмаз."""
    __tablename__ = "club_leagues"
    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    title: Mapped[str] = mapped_column(String(32))
    order_no: Mapped[int]
    size: Mapped[int] = mapped_column(default=50, server_default="50")     # сколько клубов в дивизионе


class LeagueMembership(Base):
    """Клуб в лиге на конкретную ISO-неделю + итог недели (место, повышение/понижение)."""
    __tablename__ = "club_league_memberships"
    __table_args__ = (Index("uq_club_league_week", "club_id", "week_key", unique=True),
                      Index("ix_club_league_board", "league_code", "week_key", text("score DESC")))
    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"))
    league_code: Mapped[str] = mapped_column(ForeignKey("club_leagues.code"))
    week_key: Mapped[str] = mapped_column(String(8))
    score: Mapped[int] = mapped_column(default=0, server_default="0")
    rank: Mapped[int | None]
    outcome: Mapped[str | None] = mapped_column(String(8))    # stayed | up | down
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClubWar(Base):
    """Бизнес-война: неделя, автоподбор клубов похожего уровня, боевой состав выбирает SEO."""
    __tablename__ = "club_wars"
    __table_args__ = (Index("ix_club_wars_week", "week_key", "league_code"),
                      Index("ix_club_wars_club", "club_a_id", "club_b_id"))
    id: Mapped[int] = mapped_column(primary_key=True)
    week_key: Mapped[str] = mapped_column(String(8))
    league_code: Mapped[str | None] = mapped_column(String(12))
    club_a_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"))
    club_b_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(10), default="picking", server_default="picking")  # picking | resolved
    picks: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    log: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    score_a: Mapped[int] = mapped_column(default=0, server_default="0")
    score_b: Mapped[int] = mapped_column(default=0, server_default="0")
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id", ondelete="SET NULL"))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BeautyVote(Base):
    """Конкурс клубной красоты: голос за чужой клуб, один голос в неделю."""
    __tablename__ = "club_beauty_votes"
    __table_args__ = (UniqueConstraint("user_id", "week_key", name="uq_club_beauty_votes_user_week"),
                      Index("ix_club_beauty_votes_week", "week_key", "target_club_id"))
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id", ondelete="SET NULL"))
    target_club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"))
    week_key: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClubMuseumEntry(Base):
    """«Музей кооперативов»: расформированные клубы и их Танк — страница-мемориал."""
    __tablename__ = "club_museum"
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(String(24))
    tag: Mapped[str] = mapped_column(String(5))
    emblem: Mapped[str] = mapped_column(String(16))
    color: Mapped[str] = mapped_column(String(9))
    color2: Mapped[str] = mapped_column(String(9))
    stage: Mapped[int] = mapped_column(default=1, server_default="1")
    tank_xp: Mapped[int] = mapped_column(default=0, server_default="0")
    members_total: Mapped[int] = mapped_column(default=0, server_default="0")
    scars: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    reason: Mapped[str | None] = mapped_column(String(120))
    founded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disbanded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClubMembershipCooldown(Base):
    """Кулдаун на вступление в новый клуб после выхода (24 ч) — чтобы не прыгали за наградами."""
    __tablename__ = "club_membership_cooldowns"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    from_club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClubDayStat(Base):
    """Суточная статистика клуба: норма дня, стрик, вклад участников по показателям (антиабуз-потолки)."""
    __tablename__ = "club_day_stats"
    __table_args__ = (Index("uq_club_day_stat", "club_id", "day", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    norm_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    norm_target: Mapped[int] = mapped_column(default=3, server_default="3")
    contributors: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    care_counts: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    streak: Mapped[int] = mapped_column(default=0, server_default="0")
    frozen: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
