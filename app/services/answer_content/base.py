"""Обработчики типов ответа. Сейчас работает только текст; голос и видео —
заготовки, которые включаются фича-флагами после реализации."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ...errors import ApiError


class AnswerContentError(ApiError):
    def __init__(self, message: str, code: str = "invalid_answer"):
        super().__init__(message, 422, code)


@dataclass(slots=True)
class AnswerDraft:
    content_type: str
    body: str | None = None
    upload_id: str | None = None  # для медиа: id файла, заранее загруженного в S3


class AnswerContentHandler(ABC):
    content_type: str
    feature_flag: str

    @abstractmethod
    async def validate(self, draft: AnswerDraft) -> None: ...

    @abstractmethod
    async def persist(self, s: AsyncSession, answer, draft: AnswerDraft) -> None:
        """Сохранить данные, специфичные для типа (например, строку answer_media)."""

    def serialize(self, answer) -> dict:
        return {"type": self.content_type, "body": answer.body}
