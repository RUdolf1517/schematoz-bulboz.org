"""ЗАГОТОВКА под голосовые и видео-ответы. Не используется, пока флаги
ANSWER_VOICE_ENABLED / ANSWER_VIDEO_ENABLED выключены (registry отдаёт 422).

План внедрения:
  1. POST /api/uploads/answer-media → presigned URL в S3 + upload_id (Redis, TTL 1 ч).
  2. validate(): upload_id существует, mime из ALLOWED_MIME, duration ≤ 60 с.
  3. persist(): AnswerMedia(processing_status=UPLOADED), answer.status=PROCESSING,
     задача транскодинга (ffmpeg) в Redis Stream `jobs:media`.
  4. Воркер: транскодинг, waveform/превью, status=READY, answer.status=ACTIVE.
  5. Миграция: снять CHECK ck_answers_text_only_mvp, заменить на правило
     «text → body обязателен; voice/video → есть answer_media».
"""
from __future__ import annotations

from .base import AnswerContentHandler, AnswerDraft


class _MediaAnswerHandler(AnswerContentHandler):
    ALLOWED_MIME: frozenset[str] = frozenset()

    async def validate(self, draft: AnswerDraft) -> None:
        raise NotImplementedError(f"{self.content_type}-ответы ещё не реализованы")

    async def persist(self, s, answer, draft: AnswerDraft) -> None:
        raise NotImplementedError(f"{self.content_type}-ответы ещё не реализованы")

    def serialize(self, answer) -> dict:
        m = answer.media
        return {
            "type": self.content_type,
            "body": answer.body,  # подпись/расшифровка от автора
            "media": None if m is None else {
                "storage_key": m.storage_key,  # TODO: presigned URL
                "duration_ms": m.duration_ms,
                "waveform": m.waveform,
                "thumbnail_key": m.thumbnail_key,
                "status": m.processing_status.value,
            },
        }


class VoiceAnswerHandler(_MediaAnswerHandler):
    content_type = "voice"
    feature_flag = "ANSWER_VOICE_ENABLED"
    ALLOWED_MIME = frozenset({"audio/ogg", "audio/mp4", "audio/webm"})


class VideoAnswerHandler(_MediaAnswerHandler):
    content_type = "video"
    feature_flag = "ANSWER_VIDEO_ENABLED"
    ALLOWED_MIME = frozenset({"video/mp4", "video/webm"})
