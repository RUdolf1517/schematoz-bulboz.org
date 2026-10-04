from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class UserBadge(Base):
    """Выданный бейдж. Каталог бейджей — в коде (app/services/badges.py),
    чтобы названия/описания правились без миграций."""
    __tablename__ = "user_badges"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    """Уведомление внутри сайта. kind: answer | scheme | badge | ban | appeal | follow.
    payload — всё, что нужно для текста и ссылки (question_id, answer_id, username, code…)."""
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user", "user_id", "is_read", text("id DESC")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    dedupe_key: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Kombucha(Base):
    """Мини-игра «Чайный гриб». У юзера может быть несколько грибов — по одному на банку.
    Показатели хранятся «на момент updated_at», убывание (шагами раз в 12 ч) досчитывается
    при чтении (app/services/kombucha.py) — никаких кронов. Имя уникально на весь сайт."""
    __tablename__ = "kombuchas"
    __table_args__ = (Index("uq_kombuchas_name_lower", text("lower(name)"), unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("kombuchas.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(32))
    xp: Mapped[int] = mapped_column(default=0, server_default="0")
    best_xp: Mapped[int] = mapped_column(default=0, server_default="0")
    generation: Mapped[int] = mapped_column(default=1, server_default="1")
    sweet: Mapped[float] = mapped_column(default=70.0)
    tea: Mapped[float] = mapped_column(default=70.0)
    clean: Mapped[float] = mapped_column(default=90.0)
    happy: Mapped[float] = mapped_column(default=70.0)
    alive: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    zero_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cooldowns: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    # мутации этого гриба: [{"code": ..., "at": iso}]
    mutations: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    care_days: Mapped[int] = mapped_column(default=0, server_default="0")     # дней, когда за грибом ухаживали
    last_care_day: Mapped[date | None]
    pet_count: Mapped[int] = mapped_column(default=0, server_default="0")
    sprouted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    sprout_pending: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # заморозка: не убывает, не занимает банку, стоит на полке в профиле; продавать/менять можно только замороженных
    mold: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")          # плесень
    last_sprout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sprout_count: Mapped[int] = mapped_column(default=0, server_default="0")
    talk_count: Mapped[int] = mapped_column(default=0, server_default="0")
    owners: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))  # провенанс
    # Хэллоуинская косметика переживает окончание события; эффекты и исчезновение временные.
    halloween_hat: Mapped[str | None] = mapped_column(String(24))
    halloween_mutations: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    halloween_gone_day: Mapped[date | None] = mapped_column(Date)
    halloween_gone: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    halloween_web_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    frozen: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    price: Mapped[int | None]                     # выставлен на рынок за столько $₽
    listed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    born_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    died_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KombuchaCodex(Base):
    """Коллекция открытых мутаций юзера — сохраняется навсегда, даже если гриб закис."""
    __tablename__ = "kombucha_codex"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    kombucha_name: Mapped[str | None] = mapped_column(String(32))
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WoodTx(Base):
    """Журнал «Деревянных» ($₽). ref — идемпотентность: одно и то же событие
    (ответ №5, вход 2026-09-27…) не начислится дважды."""
    __tablename__ = "wood_tx"
    __table_args__ = (Index("uq_wood_tx_ref", "user_id", "reason", "ref", unique=True),
                      Index("ix_wood_tx_user", "user_id", text("id DESC")))
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    delta: Mapped[int]
    reason: Mapped[str] = mapped_column(String(32))
    ref: Mapped[str] = mapped_column(String(64))
    balance_after: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MutationCounter(Base):
    """Сколько экземпляров каждой мутации выпало на сайте — даёт номер «#17» как у подарков в Telegram."""
    __tablename__ = "mutation_counters"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    issued: Mapped[int] = mapped_column(default=0, server_default="0")


class KombuchaTrade(Base):
    """Предложение обмена: отдаю give_id, хочу want_id (или ничего — это подарок).
    status: pending | accepted | declined | cancelled."""
    __tablename__ = "kombucha_trades"
    __table_args__ = (Index("ix_kombucha_trades_to", "to_user_id", "status"),
                      Index("ix_kombucha_trades_from", "from_user_id", "status"))
    id: Mapped[int] = mapped_column(primary_key=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    give_id: Mapped[int] = mapped_column(ForeignKey("kombuchas.id", ondelete="CASCADE"))
    want_id: Mapped[int | None] = mapped_column(ForeignKey("kombuchas.id", ondelete="CASCADE"))
    message: Mapped[str | None] = mapped_column(String(140))     # подпись к подарку/обмену
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KombuchaEvent(Base):
    """Дневник гриба: «родился», «вырос», «мутировал», «чуть не помер»… Публичный, им можно поделиться.
    Смерть пишется лениво (tick() работает без сессии) — её досчитывает services/kombucha_diary.py."""
    __tablename__ = "kombucha_events"
    __table_args__ = (Index("ix_kombucha_events_kb", "kombucha_id", text("id DESC")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kombucha_id: Mapped[int] = mapped_column(ForeignKey("kombuchas.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24))
    body: Mapped[str] = mapped_column(String(300))
    emoji: Mapped[str] = mapped_column(String(16), default="📝", server_default="📝")
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
