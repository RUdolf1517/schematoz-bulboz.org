from __future__ import annotations

from flask import current_app

from .base import AnswerContentError, AnswerContentHandler, AnswerDraft


class TextAnswerHandler(AnswerContentHandler):
    content_type = "text"
    feature_flag = "ANSWER_TEXT_ENABLED"

    async def validate(self, draft: AnswerDraft) -> None:
        body = (draft.body or "").strip()
        max_len = current_app.config["ANSWER_TEXT_MAX_LEN"]
        if not 1 <= len(body) <= max_len:
            raise AnswerContentError(f"Ответ должен быть от 1 до {max_len} символов")
        if draft.upload_id:
            raise AnswerContentError("К текстовому ответу нельзя прикрепить медиа")
        draft.body = body

    async def persist(self, s, answer, draft: AnswerDraft) -> None:
        return None  # текст уже лежит в answers.body
