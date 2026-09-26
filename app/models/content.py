from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, SmallInteger,
    String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, pg_enum
from .enums import (
    AnswerContentType, ContentStatus, DebateSide, MediaKind, MediaProcessingStatus,
    QuestionKind, RepReason,
)


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(128))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    sort: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Room(TimestampMixin, Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    is_official: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    member_count: Mapped[int] = mapped_column(default=0, server_default="0")


class RoomMember(Base):
    __tablename__ = "room_members"
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Question(TimestampMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint(
            "kind <> 'debate' OR (debate_side_a IS NOT NULL AND debate_side_b IS NOT NULL)",
            name="debate_sides",
        ),
        Index("ix_questions_room_hot", "room_id", text("score_hot DESC")),
        Index("ix_questions_author_created", "author_id", text("created_at DESC")),
        Index(
            "ix_questions_fts",
            text("to_tsvector('russian', title || ' ' || coalesce(body, ''))"),
            postgresql_using="gin",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[QuestionKind] = mapped_column(pg_enum(QuestionKind, "question_kind"))
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text)
    media: Mapped[dict | None] = mapped_column(JSONB)
    debate_side_a: Mapped[str | None] = mapped_column(String(80))
    debate_side_b: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[ContentStatus] = mapped_column(
        pg_enum(ContentStatus, "content_status"), default=ContentStatus.ACTIVE,
        server_default=ContentStatus.ACTIVE.value,
    )
    # «Схема» — ответ, которому автор вопроса поставил +5
    best_answer_id: Mapped[int | None] = mapped_column(
        ForeignKey("answers.id", use_alter=True, ondelete="SET NULL")
    )
    score_hot: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    answers_count: Mapped[int] = mapped_column(default=0, server_default="0")
    views_count: Mapped[int] = mapped_column(default=0, server_default="0")


class Answer(TimestampMixin, Base):
    __tablename__ = "answers"
    __table_args__ = (
        # MVP: только текст. Enum уже содержит voice/video — при запуске медиа
        # отдельная миграция снимет этот CHECK (ALTER TYPE не понадобится).
        CheckConstraint(
            "content_type = 'text' AND body IS NOT NULL AND length(body) BETWEEN 1 AND 5000",
            name="text_only_mvp",
        ),
        Index("ix_answers_question_score", "question_id", text("score DESC")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    content_type: Mapped[AnswerContentType] = mapped_column(
        pg_enum(AnswerContentType, "answer_content_type"),
        default=AnswerContentType.TEXT, server_default=AnswerContentType.TEXT.value,
    )
    body: Mapped[str | None] = mapped_column(Text)
    debate_side: Mapped[DebateSide | None] = mapped_column(pg_enum(DebateSide, "debate_side"))
    status: Mapped[ContentStatus] = mapped_column(
        pg_enum(ContentStatus, "content_status"), default=ContentStatus.ACTIVE,
        server_default=ContentStatus.ACTIVE.value,
    )
    score: Mapped[int] = mapped_column(default=0, server_default="0")

    media: Mapped["AnswerMedia | None"] = relationship(
        back_populates="answer", uselist=False, lazy="noload"
    )


class AnswerMedia(Base):
    """Заготовка под голосовые/видео-ответы. В MVP таблица пустая."""
    __tablename__ = "answer_media"
    __table_args__ = (CheckConstraint("duration_ms > 0 AND duration_ms <= 60000", name="duration"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int] = mapped_column(ForeignKey("answers.id", ondelete="CASCADE"), unique=True)
    kind: Mapped[MediaKind] = mapped_column(pg_enum(MediaKind, "media_kind"))
    storage_key: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(64))
    duration_ms: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int]
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    waveform: Mapped[list | None] = mapped_column(JSONB)
    thumbnail_key: Mapped[str | None] = mapped_column(Text)
    processing_status: Mapped[MediaProcessingStatus] = mapped_column(
        pg_enum(MediaProcessingStatus, "media_processing_status"),
        default=MediaProcessingStatus.UPLOADED,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    answer: Mapped[Answer] = relationship(back_populates="media")


class Vote(TimestampMixin, Base):
    """Оценка ответа. Правило репутации зашито в CHECK:
    автор вопроса — только +5 или −1, остальные — только +1 или −1."""
    __tablename__ = "votes"
    __table_args__ = (
        CheckConstraint(
            "(is_author_vote AND value IN (5, -1)) OR (NOT is_author_vote AND value IN (1, -1))",
            name="value_rule",
        ),
    )
    answer_id: Mapped[int] = mapped_column(ForeignKey("answers.id", ondelete="CASCADE"), primary_key=True)
    voter_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    value: Mapped[int] = mapped_column(SmallInteger)
    is_author_vote: Mapped[bool] = mapped_column(Boolean)
    counted: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class ReputationEvent(Base):
    __tablename__ = "reputation_events"
    __table_args__ = (Index("ix_rep_user_created", "user_id", text("created_at DESC")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[RepReason] = mapped_column(pg_enum(RepReason, "rep_reason"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    answer_id: Mapped[int | None] = mapped_column(ForeignKey("answers.id", ondelete="SET NULL"))
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id", ondelete="SET NULL"))
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DebateVote(Base):
    __tablename__ = "debate_votes"
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    side: Mapped[DebateSide] = mapped_column(pg_enum(DebateSide, "debate_side"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Follow(Base):
    __tablename__ = "follows"
    __table_args__ = (CheckConstraint("follower_id <> followee_id", name="no_self_follow"),)
    follower_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    followee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
