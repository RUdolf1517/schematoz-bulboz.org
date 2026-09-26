from __future__ import annotations

from ..features import feature_enabled
from .base import AnswerContentError, AnswerContentHandler
from .media import VideoAnswerHandler, VoiceAnswerHandler
from .text import TextAnswerHandler

_HANDLERS: dict[str, AnswerContentHandler] = {
    h.content_type: h for h in (TextAnswerHandler(), VoiceAnswerHandler(), VideoAnswerHandler())
}


async def get_handler(content_type: str) -> AnswerContentHandler:
    handler = _HANDLERS.get(content_type)
    if handler is None:
        raise AnswerContentError("Неизвестный тип ответа", "unknown_answer_type")
    if not await feature_enabled(handler.feature_flag):
        raise AnswerContentError("Этот тип ответа пока недоступен", "answer_type_disabled")
    return handler


async def enabled_types() -> list[str]:
    return [t for t, h in _HANDLERS.items() if await feature_enabled(h.feature_flag)]


def serialize_answer(answer) -> dict:
    """Сериализация не зависит от флагов: уже опубликованный ответ показываем всегда."""
    ct = answer.content_type.value if hasattr(answer.content_type, "value") else answer.content_type
    return _HANDLERS[ct].serialize(answer)
