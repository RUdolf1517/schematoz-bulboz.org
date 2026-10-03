import enum


class QuestionKind(str, enum.Enum):
    OPINION = "opinion"
    KNOWLEDGE = "knowledge"
    STORY = "story"
    DEBATE = "debate"


class ContentStatus(str, enum.Enum):
    ACTIVE = "active"
    HIDDEN = "hidden"
    DELETED = "deleted"
    PENDING = "pending"        # премодерация
    PROCESSING = "processing"  # зарезервировано: транскодинг медиа-ответов


class AnswerContentType(str, enum.Enum):
    TEXT = "text"
    VOICE = "voice"  # зарезервировано, выключено фича-флагом
    VIDEO = "video"  # зарезервировано, выключено фича-флагом


class MediaKind(str, enum.Enum):
    VOICE = "voice"
    VIDEO = "video"


class MediaProcessingStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    TRANSCODING = "transcoding"
    READY = "ready"
    FAILED = "failed"


class DebateSide(str, enum.Enum):
    A = "a"
    B = "b"


class RepReason(str, enum.Enum):
    AUTHOR_VOTE = "author_vote"
    UPVOTE = "upvote"
    DOWNVOTE = "downvote"
    VOTE_REVOKED = "vote_revoked"
    MOD_PENALTY = "mod_penalty"


class ReportTarget(str, enum.Enum):
    QUESTION = "question"
    ANSWER = "answer"
    COMMENT = "comment"
    USER = "user"


class ReportReason(str, enum.Enum):
    SPAM = "spam"
    BULLYING = "bullying"
    NSFW = "nsfw"
    DOXXING = "doxxing"
    SELF_HARM = "self_harm"
    ILLEGAL = "illegal"
    OTHER = "other"


class ReportStatus(str, enum.Enum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class BanScope(str, enum.Enum):
    GLOBAL = "global"
    ROOM = "room"


class AppealStatus(str, enum.Enum):
    NONE = "none"
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
