# schematoz-bulboz.org — Q&A нового поколения для зумеров

> Концепт и ТЗ для MVP. Оператор сервиса: ООО «СукИнЭндСын».
> Версия 0.3, 26.09.2026.
>
> **Изменения в 0.3:** автор вопроса ставит ответу **только +5 или −1** (без промежуточных оценок). Началась реализация: см. `README.md` и код в `app/`.
>
> **Что изменилось с 0.1:** проект получил название — **schematoz-bulboz.org**. Убраны все AI-фичи и анонимные вопросы. Ответы пока только текстом, но код и БД уже готовы к голосовым и видео. Новая шкала репутации (уточнена в 0.3): автор вопроса ставит ответу +5 или −1, остальные ставят ±1.

---

## 0. Название и позиционирование

**schematoz-bulboz.org** (в речи — «Схематоз», в мемах — «Бульбоз»).

Название звучит абсурдно, и это плюс. Его невозможно забыть, оно легко становится мемом и отсылает к рунету времён «как пожарить воду». Зумеры хорошо принимают бренды с ироничными нечитаемыми названиями.

**Позиционирование:** «Лента, где вместо рилсов — вопросы. Свайпнул, ответил, словил +5». Серьёзные ответы («Знания», ЕГЭ) и угар («Золотой фонд») живут в одной ленте. Отличаемся от перезапущенных «Ответов» тремя вещами: вертикальный формат, прозрачная репутация, жёсткий антиспам.

Внутренние названия разделов:
- **«Холивар»** — дебат-режим «за/против»;
- **«Золотой фонд»** — подборка самых абсурдных вопросов недели;
- **«Схема»** — ответ, который автор вопроса признал лучшим («рабочая схема»). Отсюда и название.

---

## 1. Концепция в одном абзаце

schematoz-bulboz.org — это вертикальная лента карточек «вопрос → лучшие ответы». Её листают как TikTok, а не читают как форум 2009 года. Вопрос можно задать в общую ленту или в тематическую комнату (фэндом, игра, ЕГЭ по физике). Ответы оценивают все, но у автора вопроса голос весит больше: до +5. Поэтому репутацию зарабатывают тем, что реально помогли человеку, а не спамом. Репутация прозрачная: в профиле написано не «14 832 балла», а «эксперт по ЕГЭ-физике: 43 ответа, которые авторы оценили на +5». Бейджи, стрики и уровни одной кнопкой превращаются в картинку для сторис. Капча — задание из ЕГЭ: боты страдают, а школьники заодно готовятся к экзамену. Здесь только живые люди, никаких нейросетей в ленте.

---

## 2. Архитектура

### 2.1. Высокоуровневая схема

```
 [Мобилка (React Native/Expo)]   [Веб (Next.js / SvelteKit, SSR для SEO)]
              \                         /
               \        HTTPS          /
                ▼                     ▼
           [Nginx / Caddy — TLS, rate limit L7, статика]
                          │
                          ▼
      [Hypercorn (ASGI) ← asgiref.WsgiToAsgi ← Flask 3.x app]
         │  async views, RBAC-декораторы, KremleFlask
         │
   ┌─────┼──────────────────┬───────────────────────┐
   ▼     ▼                  ▼                       ▼
[PostgreSQL 16]        [Redis 7]              [Воркеры (arq / RQ)]
 SQLAlchemy 2.0 async   • сессии               • пересчёт ленты
 + asyncpg              • кэш ленты            • антиспам-скоринг (правила)
 Alembic миграции       • rate limit           • картинки для сторис
                        • очереди (Streams)    • пуши, почта
                        • счётчики/стрики      • агрегаты аналитики
                                  │            • [будущее] транскодинг медиа
                                  ▼
                   [S3-совместимое хранилище: аватарки, картинки,
                    в будущем — аудио/видео ответов]
```

### 2.2. Backend: Flask + async — как не выстрелить себе в ногу

- **Python 3.12+, Flask 3.x** с `async def` вьюхами (`pip install "flask[async]"`).
- Запуск: `hypercorn "app.asgi:asgi_app" --bind 0.0.0.0:8000 --workers 4`, где `asgi_app = WsgiToAsgi(create_app())` из `asgiref.wsgi`.
- ⚠️ **Важный нюанс.** Flask выполняет каждую async-вьюху в *отдельном* event loop (через `asgiref.async_to_sync`). Пул соединений asyncpg работает только в том loop, где его создали. Поэтому:
  - **вариант А** (MVP, просто): `create_async_engine(..., poolclass=NullPool)` и **PgBouncer** в transaction mode перед Postgres. Пул живёт в PgBouncer, а не в процессе приложения;
  - **вариант Б** (если упрёмся в производительность): переезд на **Quart**. API почти такой же, как у Flask (`from quart import Quart`), один event loop на воркер, нормальный пул asyncpg. Вьюхи и декораторы пишем так, чтобы переезд свёлся к замене импортов. Это и есть «Quart-совместимый режим» из требований.

**Структура проекта:**

```
app/
  __init__.py          # create_app(), регистрация blueprints, KremleFlask
  asgi.py              # asgi_app = WsgiToAsgi(create_app())
  config.py            # в т.ч. фича-флаги ANSWER_VOICE_ENABLED / ANSWER_VIDEO_ENABLED
  db.py                # async engine, async_sessionmaker
  models/              # SQLAlchemy 2.0 Declarative (Mapped[...])
  auth/                # регистрация, вход, сессии, RBAC
    rbac.py            # @require_perm
  api/
    feed.py questions.py answers.py votes.py rooms.py
    debates.py reports.py profile.py
  moderation/          # blueprint /mod/*
  admin/               # blueprint /admin/*
  legal/               # публичные юр. страницы и их редактирование
  services/
    reputation.py      # правила голосов и начислений
    feed_ranker.py     # ранжирование ленты (формулы, не ML)
    antispam.py        # правила, rate limit, simhash
    captcha.py         # адаптер над kremle-detect
    answer_content/    # ← заготовка под типы ответов (раздел 4)
      base.py text.py voice.py video.py registry.py
  workers/
migrations/            # Alembic (async env.py)
```

**БД-сессия:**

```python
# app/db.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

engine = create_async_engine(settings.DATABASE_URL,  # postgresql+asyncpg://...
                             poolclass=NullPool)      # см. нюанс выше
Session = async_sessionmaker(engine, expire_on_commit=False)
```

**Alembic** с асинхронным шаблоном: `alembic init -t async migrations`. Миграции попадают в проект только через PR. `alembic upgrade head` выполняется в CI/CD перед выкаткой.

### 2.3. Redis — за что отвечает

| Ключ / структура | Зачем |
|---|---|
| `sess:{id}` (hash, TTL 30 дней) | серверные сессии (cookie `HttpOnly; Secure; SameSite=Lax`) |
| `rl:{route}:{user\|ip}` | rate limit (sliding window) |
| `feed:{user_id}` (zset) | готовая персональная лента, TTL 10 мин |
| `streak:{user_id}` | текущий стрик и дата последней активности |
| `hot:room:{id}` (zset) | горячие вопросы комнаты |
| `susp:{user\|ip}` | счётчик подозрительности → триггер капчи |
| Streams `jobs:*` | очереди для воркеров |
| `perm:{user_id}` | кэш набора прав (сбрасывается при смене роли) |

### 2.4. Капча и антибот: kremle-detect

- Подключается через `KremleFlask` из [KremleXYZ-Detect](https://github.com/RUdolf1517/KremleXYZ-Detect): инициализация в `create_app()`, подключение к нужным роутам.
- **Где капча обязательна:** регистрация, вход, восстановление пароля.
- **Где она включается при подозрительной активности.** Решает `services/antispam.py` по счётчикам `susp:*` в Redis, логика — обычные правила, без ML:
  - больше N вопросов или ответов за минуту;
  - много одинаковых текстов подряд (simhash);
  - аккаунт младше 24 часов отправляет ссылки;
  - kremle-detect пометил клиент или источник трафика как бот или «специфичный источник»;
  - больше 5 неудачных входов.
- Капча — задания ЕГЭ по математике, физике, русскому и литературе. После решения показываем: «Кстати, это задание №7 из ЕГЭ по физике. Ты справился за 12 секунд 💪».
- Настройки (включение по роутам, пороги, предметы, сложность) задаются в админке, хранятся в таблице `settings` и кэшируются в Redis.
- Точные имена методов `KremleFlask` сверяем с README библиотеки при реализации. Весь код обращается к ней только через тонкий адаптер `services/captcha.py`.

### 2.5. Роли и RBAC

Три базовые роли плюс отдельные права (permissions). Так позже можно без боли добавить, например, «модератора комнаты».

| Право | user | moderator | admin |
|---|:-:|:-:|:-:|
| `question.create`, `answer.create`, `vote.cast`, `report.create` | ✅ | ✅ | ✅ |
| `report.review`, `content.hide`, `content.restore` | — | ✅ | ✅ |
| `ban.temporary` (до 30 дней) | — | ✅ | ✅ |
| `ban.permanent`, `ban.lift_any` | — | — | ✅ |
| `modlog.read_own` | — | ✅ | ✅ |
| `modlog.read_all` | — | — | ✅ |
| `role.assign`, `category.manage`, `room.manage` | — | — | ✅ |
| `settings.captcha`, `settings.antispam`, `settings.features` | — | — | ✅ |
| `analytics.read` | — | — | ✅ |
| `legal.edit` | — | — | ✅ |

```python
# app/auth/rbac.py
from functools import wraps
from flask import g, abort

def require_perm(*perms: str):
    def deco(view):
        @wraps(view)
        async def wrapper(*args, **kwargs):
            user = g.get("user")
            if user is None:
                abort(401)
            if await is_banned(user.id):
                abort(403, "banned")
            granted = await get_user_perms(user.id)   # Redis-кэш → БД
            if not set(perms) <= granted:
                abort(403)
            return await view(*args, **kwargs)
        return wrapper
    return deco

@bp.post("/mod/content/<int:cid>/hide")
@require_perm("content.hide")
async def hide_content(cid: int): ...
```

- Проверка на уровне API — единственный источник правды. Фронт только прячет кнопки.
- Каждое действие с правами `content.*`, `ban.*`, `role.*`, `settings.*`, `legal.edit` пишет запись в `mod_actions` в той же транзакции. Нет записи в логе — нет действия.

### 2.6. Юридический раздел

- Страницы: `/rules` (Правила сообщества), `/terms` (Пользовательское соглашение), `/privacy` (Политика конфиденциальности), `/requisites` (Реквизиты, оператор — **ООО «СукИнЭндСын»**).
- Хранение: `legal_pages` + `legal_page_versions` (история правок, автор, время, diff). Редактор на Markdown с превью, HTML санитизируется через nh3.
- После изменения `/terms` или `/privacy` показываем баннер «Мы обновили соглашение» и просим согласие заново при следующем входе. Согласие фиксируем в `user_consents`: версия, время, IP.
- Правила сообщества описывают:
  - что запрещено: буллинг, деанон, NSFW, наркотики, суицидальный контент, спам, реклама без пометки;
  - лестницу банов: предупреждение → 24 ч → 7 дней → 30 дней → перманент;
  - **процедуру апелляции**: кнопка в уведомлении о бане → очередь апелляций. Рассматривает *другой* модератор или админ.
- Политика конфиденциальности написана под 152-ФЗ: ПД хранятся в РФ, перечислены данные, цели, сроки, право на удаление. Регистрация младше 14 лет закрыта.
- **Футер на всех страницах** — общий компонент, из админки не редактируется, чтобы его случайно не снесли:
  > разработано RUdolf1517 на основе технологий [rudolfzinovev.xyz](https://rudolfzinovev.xyz)

  Рядом ссылки: Правила · Соглашение · Конфиденциальность · Реквизиты.

---

## 3. Схема БД верхнего уровня

> Весь доступ к БД **асинхронный**: SQLAlchemy 2.0 `AsyncEngine`/`AsyncSession` поверх драйвера **asyncpg**, PostgreSQL 16. Синхронных сессий в коде запросов нет. Миграции через Alembic (async env).

```
┌──────────────┐      ┌───────────────┐      ┌──────────────┐
│    roles     │◄─────│  user_roles   │─────►│    users     │
└──────┬───────┘      └───────────────┘      └──────┬───────┘
       │ role_permissions                           │ 1:N
┌──────┴───────┐                     ┌──────────────┼──────────────┬───────────────┐
│ permissions  │                     ▼              ▼              ▼               ▼
└──────────────┘               ┌───────────┐  ┌───────────┐  ┌──────────┐   ┌───────────┐
                               │ questions │◄─│  answers  │  │ reports  │   │   bans    │
                               └─────┬─────┘  └──┬─────┬──┘  └────┬─────┘   └───────────┘
                                     │           │     │          ▼
                                     ▼           ▼     ▼     ┌────────────┐
                              rooms/categories votes answer_media │ mod_actions│
                                                     (будущее)    └────────────┘
```

### users
| поле | тип | примечание |
|---|---|---|
| id | bigint PK | |
| username | citext UNIQUE | `@nick` |
| email | citext UNIQUE | |
| password_hash | text | argon2id |
| display_name, avatar_url, bio | text | |
| birth_year | smallint | для возрастных ограничений |
| reputation | int default 0 | денормализованный итог; источник правды — `reputation_events` |
| level | smallint | вычисляется из reputation |
| streak_days, streak_last_date | int, date | дублирует Redis для надёжности |
| created_at, last_seen_at | timestamptz | |

### roles / permissions / user_roles / role_permissions
| таблица | поля |
|---|---|
| roles | id, code (`user`/`moderator`/`admin`), title |
| permissions | id, code (`content.hide`, …) |
| role_permissions | role_id, permission_id (составной PK) |
| user_roles | user_id, role_id, granted_by, granted_at (PK user_id + role_id) |

### questions
| поле | тип | примечание |
|---|---|---|
| id | bigint PK | |
| author_id | FK users | всегда публичный, анонимных вопросов нет |
| kind | enum | `opinion` / `knowledge` / `story` / `debate` |
| room_id | FK rooms NULL | тематическая комната |
| category_id | FK categories NULL | |
| title | varchar(300) | |
| body | text NULL | |
| media | jsonb | картинки к вопросу, опрос |
| debate_side_a, debate_side_b | varchar(80) NULL | для `debate`: подписи сторон |
| status | enum | `active` / `hidden` / `deleted` / `pending` (премодерация) |
| best_answer_id | FK answers NULL | «Схема» — ответ с оценкой автора +5 |
| score_hot | real | для ранжирования, пересчитывает воркер |
| answers_count, views_count | int | |
| created_at, updated_at | timestamptz | |

Индексы: `(room_id, score_hot DESC)`, `(author_id, created_at DESC)`, GIN по `to_tsvector('russian', title || ' ' || coalesce(body,''))`.

### answers (готовы к медиа)
| поле | тип | примечание |
|---|---|---|
| id | bigint PK | |
| question_id | FK questions | |
| author_id | FK users | |
| content_type | enum `answer_content_type` | `text` / `voice` / `video`. **В MVP разрешён только `text`** (CHECK + сервисная проверка) |
| body | text NULL | текст ответа; для голосовых и видео в будущем — подпись или расшифровка, введённая автором |
| debate_side | enum NULL | `a` / `b` — чью сторону ответ занимает в холиваре |
| status | enum | `active` / `hidden` / `deleted` / `processing` (для будущего транскодинга) |
| score | int | сумма голосов (денормализовано) |
| created_at, updated_at | timestamptz | |

```sql
-- MVP: тип enum уже содержит все значения, но разрешён только text.
-- Когда запустим медиа, эту проверку снимет отдельная миграция, ALTER TYPE не понадобится.
ALTER TABLE answers ADD CONSTRAINT answers_text_only_mvp
  CHECK (content_type = 'text' AND body IS NOT NULL AND length(body) BETWEEN 1 AND 5000);
```

### answer_media (создаётся сейчас, пустая до запуска медиа)
| поле | тип | примечание |
|---|---|---|
| id | bigint PK | |
| answer_id | FK answers UNIQUE | один медиафайл на ответ |
| kind | enum | `voice` / `video` |
| storage_key | text | ключ в S3 |
| mime_type | varchar(64) | `audio/ogg`, `video/mp4` … |
| duration_ms | int | лимит 60 000 |
| size_bytes | bigint | |
| width, height | int NULL | для видео |
| waveform | jsonb NULL | для отрисовки голосового |
| thumbnail_key | text NULL | превью видео |
| processing_status | enum | `uploaded` / `transcoding` / `ready` / `failed` |
| created_at | timestamptz | |

### votes (ядро репутации)
| поле | тип | примечание |
|---|---|---|
| answer_id | FK answers | PK (answer_id, voter_id): один голос на ответ |
| voter_id | FK users | |
| value | smallint | |
| is_author_vote | bool | голос автора вопроса; ставит сервер, а не клиент |
| created_at, updated_at | timestamptz | |

Правило репутации проверяется в самой БД:
```sql
ALTER TABLE votes ADD CONSTRAINT votes_value_rule CHECK (
  (is_author_vote     AND value IN (5, -1))
  OR
  (NOT is_author_vote AND value IN (-1, 1))
);
```
Дополнительно сервис проверяет, что голосовать за свой ответ нельзя.

### reputation_events (прозрачная репутация)
| поле | тип | примечание |
|---|---|---|
| id | bigint PK | |
| user_id | FK users | кто получил или потерял очки |
| delta | int | +5 или −1 от автора, ±1 от остальных |
| reason | enum | `author_vote`, `upvote`, `downvote`, `vote_revoked`, `mod_penalty` |
| answer_id, question_id | FK NULL | за что именно |
| room_id, category_id | FK NULL | для расчёта экспертности по теме |
| created_at | timestamptz | |

### reports (жалобы)
| поле | тип | примечание |
|---|---|---|
| id | bigint PK | |
| reporter_id | FK users | |
| target_type | enum | `question` / `answer` / `user` |
| target_id | bigint | |
| reason | enum | `spam`, `bullying`, `nsfw`, `doxxing`, `self_harm`, `illegal`, `other` |
| comment | text NULL | |
| status | enum | `open` / `in_review` / `resolved` / `rejected` |
| priority | smallint | `self_harm` и `doxxing` идут наверх очереди |
| assigned_to | FK users NULL | модератор |
| resolved_by, resolved_at | FK users, timestamptz | |
| created_at | timestamptz | |

Индекс `(status, priority DESC, created_at)`. Уникальность `(reporter_id, target_type, target_id)` — чтобы одна обиженка не накидала 50 жалоб.

### bans
| поле | тип | примечание |
|---|---|---|
| id | bigint PK | |
| user_id | FK users | |
| issued_by | FK users | модератор или админ |
| reason | text | |
| report_id | FK reports NULL | |
| scope | enum | `global` / `room` |
| room_id | FK rooms NULL | |
| starts_at, ends_at | timestamptz | `ends_at IS NULL` = перманент (только admin) |
| lifted_by, lifted_at | FK users, timestamptz NULL | |
| appeal_status | enum | `none` / `pending` / `accepted` / `rejected` |

### Вспомогательные таблицы
- `rooms` (id, slug, title, category_id, is_official, member_count), `room_members`
- `categories` (id, slug, title, parent_id, sort) — управляет админ
- `mod_actions` (id, actor_id, action, target_type, target_id, payload jsonb, created_at) — **только добавление**: UPDATE и DELETE запрещены правами роли БД
- `badges`, `user_badges`, `follows`, `notifications`
- `debate_votes` (question_id, user_id, side) — голос «за/против» в холиваре, отдельно от оценок ответов
- `legal_pages`, `legal_page_versions`, `user_consents`
- `settings` (key, value jsonb, updated_by) — капча, антиспам, фича-флаги

---

## 4. Ответы: только текст сейчас, медиа потом (ТЗ + код-заготовка)

**Принцип:** в MVP всё, что связано с медиа, уже есть в схеме, в API-контракте и в коде. Всё это выключено фича-флагами. Чтобы запустить голосовые, нужно:
1. реализовать `VoiceAnswerHandler`;
2. одной миграцией снять CHECK `answers_text_only_mvp`;
3. включить флаг в админке.

Переписывать ленту, репутацию и модерацию не придётся.

### 4.1. Фича-флаги

```python
# app/config.py
class Features:
    ANSWER_TEXT_ENABLED  = True
    ANSWER_VOICE_ENABLED = False   # переключается в админке (settings.features), кэш в Redis
    ANSWER_VIDEO_ENABLED = False
    ANSWER_MEDIA_MAX_DURATION_MS = 60_000
```

### 4.2. Модель

```python
# app/models/answer.py
import enum
from sqlalchemy import Enum, ForeignKey, Text, CheckConstraint, String, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin

class AnswerContentType(str, enum.Enum):
    TEXT = "text"
    VOICE = "voice"   # зарезервировано
    VIDEO = "video"   # зарезервировано

class Answer(TimestampMixin, Base):
    __tablename__ = "answers"
    __table_args__ = (
        CheckConstraint(
            "content_type = 'text' AND body IS NOT NULL "
            "AND length(body) BETWEEN 1 AND 5000",
            name="answers_text_only_mvp",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    content_type: Mapped[AnswerContentType] = mapped_column(
        Enum(AnswerContentType, name="answer_content_type"),
        default=AnswerContentType.TEXT,
    )
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")
    score: Mapped[int] = mapped_column(default=0)

    media: Mapped["AnswerMedia | None"] = relationship(
        back_populates="answer", uselist=False, lazy="raise"
    )
```

### 4.3. Реестр обработчиков типов ответа

```python
# app/services/answer_content/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

class AnswerContentError(ValueError): ...

@dataclass(slots=True)
class AnswerDraft:
    content_type: str
    body: str | None = None
    upload_id: str | None = None   # для медиа: id заранее загруженного в S3 файла

class AnswerContentHandler(ABC):
    content_type: str
    feature_flag: str

    @abstractmethod
    async def validate(self, draft: AnswerDraft) -> None: ...

    @abstractmethod
    async def persist(self, session, answer, draft: AnswerDraft) -> None:
        """Дописать тип-специфичные данные (например, answer_media)."""

    def serialize(self, answer) -> dict:
        return {"type": self.content_type, "body": answer.body}
```

```python
# app/services/answer_content/text.py
from .base import AnswerContentHandler, AnswerContentError, AnswerDraft

class TextAnswerHandler(AnswerContentHandler):
    content_type = "text"
    feature_flag = "ANSWER_TEXT_ENABLED"

    async def validate(self, draft: AnswerDraft) -> None:
        body = (draft.body or "").strip()
        if not 1 <= len(body) <= 5000:
            raise AnswerContentError("Ответ должен быть от 1 до 5000 символов")
        if draft.upload_id:
            raise AnswerContentError("К текстовому ответу нельзя прикрепить медиа")
        draft.body = body

    async def persist(self, session, answer, draft: AnswerDraft) -> None:
        pass  # весь текст уже лежит в answers.body
```

```python
# app/services/answer_content/voice.py  (video.py — такой же по структуре)
from .base import AnswerContentHandler, AnswerDraft

class VoiceAnswerHandler(AnswerContentHandler):
    """Заготовка. Включается флагом ANSWER_VOICE_ENABLED после реализации."""
    content_type = "voice"
    feature_flag = "ANSWER_VOICE_ENABLED"

    async def validate(self, draft: AnswerDraft) -> None:
        # TODO: проверить upload_id, mime (audio/ogg|audio/mp4), длительность ≤ 60с
        raise NotImplementedError

    async def persist(self, session, answer, draft: AnswerDraft) -> None:
        # TODO: создать AnswerMedia(processing_status="uploaded"),
        #       answer.status = "processing", поставить задачу транскодинга в Redis Stream
        raise NotImplementedError

    def serialize(self, answer) -> dict:
        m = answer.media
        return {"type": "voice", "body": answer.body,
                "media": m and {"url": presign(m.storage_key),
                                "duration_ms": m.duration_ms,
                                "waveform": m.waveform}}
```

```python
# app/services/answer_content/registry.py
from .base import AnswerContentError
from .text import TextAnswerHandler
from .voice import VoiceAnswerHandler
from .video import VideoAnswerHandler

_HANDLERS = {h.content_type: h for h in
             (TextAnswerHandler(), VoiceAnswerHandler(), VideoAnswerHandler())}

async def get_handler(content_type: str):
    handler = _HANDLERS.get(content_type)
    if handler is None:
        raise AnswerContentError("Неизвестный тип ответа")
    if not await feature_enabled(handler.feature_flag):   # settings → Redis
        raise AnswerContentError("Этот тип ответа пока недоступен")
    return handler

async def enabled_types() -> list[str]:
    return [t for t, h in _HANDLERS.items() if await feature_enabled(h.feature_flag)]
```

### 4.4. API-контракт (уже рассчитан на медиа)

```python
# app/api/answers.py
@bp.post("/api/questions/<int:qid>/answers")
@require_perm("answer.create")
@antispam_guard("answer")                       # может потребовать капчу
async def create_answer(qid: int):
    data = await parse_json(AnswerIn)           # {"content_type": "text", "body": "..."}
    draft = AnswerDraft(content_type=data.content_type or "text",
                        body=data.body, upload_id=data.upload_id)
    handler = await get_handler(draft.content_type)   # voice/video → 422 в MVP
    await handler.validate(draft)
    async with Session() as s, s.begin():
        answer = Answer(question_id=qid, author_id=g.user.id,
                        content_type=draft.content_type, body=draft.body)
        s.add(answer)
        await s.flush()
        await handler.persist(s, answer, draft)
    return {"answer": handler.serialize(answer)}, 201

@bp.get("/api/answers/capabilities")
async def capabilities():
    # клиент рисует кнопки «🎤» и «🎥» только если тип есть в списке
    return {"types": await enabled_types(), "max_media_ms": 60_000}

# Зарезервировано, в MVP отвечает 404/422:
# POST /api/uploads/answer-media → presigned URL в S3 + upload_id
```

**Фронт и мобилка:** рендер ответа идёт через `switch (answer.type)`. Есть компонент `TextAnswer`, заглушки `VoiceAnswer` и `VideoAnswer` и фолбэк «Обнови приложение, чтобы посмотреть ответ». Старые клиенты не сломаются, когда появятся медиа.

**Модерация:** очередь жалоб уже умеет `content_type`. Для медиа будет плеер в карточке жалобы, скрытие работает через тот же `answers.status`.

---

## 5. Механика репутации (ТЗ)

| Кто голосует за ответ | Возможные значения | Как в UI |
|---|---|---|
| **Автор вопроса** | **+5** или **−1** — и только они | 🔥 «Схема!» (+5) · 👎 «Мимо» (−1) |
| **Все остальные** | **+1** или **−1** | стрелка вверх / вниз |

- У автора всего две кнопки: +5 или −1. Промежуточных оценок нет.
- Ответ с оценкой автора **+5** становится «Схемой» (`best_answer_id`). В одном вопросе может быть только одна «Схема». Если автор поставит +5 другому ответу, прошлый ответ сохраняет свои +5, но теряет статус. *(Если нужно ограничить +5 одним ответом, это делается одним флагом в `settings`.)*
- Один пользователь — один голос на ответ. Голос можно изменить: старое начисление компенсирует событие `vote_revoked`, новое записывается отдельно. Менять голос можно не чаще раза в 10 минут, чтобы не было качелей.
- Голосовать за свой ответ нельзя.
- **Антиабуз** работает на правилах, без ML:
  - голоса аккаунтов младше 24 часов пишутся с `delta = 0`, пока аккаунт не «прогреется»;
  - «кольца» взаимных голосов (одни и те же 3–5 аккаунтов плюсуют друг друга) находит SQL-отчёт по графу голосов, и модератор их проверяет;
  - резкие скачки репутации подсвечиваются в админке.
- Репутация в профиле не показывается ниже 0, но внутри хранится как есть. Спамер с −300 продолжает триггерить капчу.

```python
# app/services/reputation.py
AUTHOR_VALUES = {5, -1}
USER_VALUES = {-1, 1}

async def cast_vote(s, voter, answer, value: int) -> None:
    if answer.author_id == voter.id:
        raise VoteError("Нельзя оценивать свой ответ")
    question = await s.get(Question, answer.question_id)
    is_author = question.author_id == voter.id
    allowed = AUTHOR_VALUES if is_author else USER_VALUES
    if value not in allowed:
        raise VoteError("Недопустимая оценка")
    await upsert_vote(s, answer, voter, value, is_author)   # + reputation_events
    if is_author and value == 5:
        question.best_answer_id = answer.id
```

**Прозрачность.** В профиле вместо одного числа — разбивка по темам:

```
@kotik_na_fizmate   Уровень 12 · 🔥 стрик 34 дня
────────────────────────────────────────────
⚡ Эксперт: ЕГЭ Физика
   • 43 ответа — «Схема» (+5 от автора)
   • 91% ответов в плюсе
   [посмотреть лучшие ответы →]
🎮 Знаток: Genshin Impact  · 17 «Схем»
📚 Новичок: Литература     · 3 ответа
```

Экспертный статус в теме: не меньше 15 «Схем» за 90 дней и доля минусов меньше 15%. Любой может нажать и увидеть сами эти ответы.

---

## 6. Core-фичи MVP (≈ 3–4 месяца; команда: 2 бэкенд, 2 фронт/мобилка, 1 дизайнер, 0.5 QA)

1. **Регистрация и вход.** Email и пароль, VK ID / Telegram (OAuth), капча kremle-detect, год рождения.
2. **Вертикальная лента карточек.** Одна карточка — вопрос и его лучший ответ. Жесты:
   - свайп вверх — следующий вопрос;
   - свайп влево — все ответы;
   - двойной тап — +1 лучшему ответу;
   - долгий тап — «хочу ответить».

   Вкладки: «Для тебя», «Подписки», «Комнаты». На вебе — колонка как в Twitter/X с навигацией ↑↓. Ранжирование по формулам (свежесть, голоса, подписки, комнаты), без ML.
3. **Вопросы:** «Мнение», «Знания», «История» и «Холивар» (дебат). Заголовок до 300 символов, чтобы было похоже на твит, а не на простыню.
4. **Ответы только текстом** (до 5000 символов, простая разметка). Медиа заготовлены (раздел 4).
5. **Голосование:** автор ставит +5 или −1, остальные ±1. «Схема» вопроса.
6. **Тематические комнаты:** на старте 30–50 официальных (ЕГЭ по предметам, топ-игры, топ-фэндомы, «Первый курс», «Отношения», «Золотой фонд»). В комнату можно вступить, у неё есть своя лента и свои правила.
7. **Профиль** с прозрачной репутацией, уровнем, стриком и 10–15 базовыми бейджами. Подписки на людей.
8. **Жалобы** на вопросы, ответы и пользователей.
9. **Модераторская панель `/mod`:**
   - очередь жалоб с приоритетом;
   - контент в контексте обсуждения;
   - быстрые действия: скрыть, восстановить, предупредить, бан на 1/7/30 дней;
   - история нарушений пользователя и лог своих действий.
10. **Админка `/admin`:**
    - роли, категории, комнаты;
    - настройки капчи, антиспама и фича-флагов;
    - редактор юридических страниц с версиями;
    - полный лог модерации;
    - аналитика: DAU/MAU, вопросы и ответы в день, доля вопросов с ответом за 10 минут, очередь жалоб, конверсия капчи.
11. **Юридический раздел и футер** (раздел 2.6).
12. **Шаринг в сторис.** Картинка 1080×1920 с карточкой вопроса или ответа, бейджем или стриком и диплинком.
13. **Пуши:** «тебе ответили», «твой ответ стал Схемой», «стрик сгорит через 3 часа».

---

## 7. Фичи второй волны

- **Голосовые и видео-ответы до 60 секунд** — ответ «кружочком». Код уже заготовлен (раздел 4): нужно реализовать обработчики, транскодинг в воркере (ffmpeg), плеер и модерацию медиа.
- **Модераторы комнат** — роль `room_moderator`. Ради неё RBAC изначально построен на правах.
- **Лайв-холивары.** Дебат с таймером на 1 час, счётчик голосов в реальном времени (WebSocket через Redis pub/sub), итоговая картинка «Шаверма победила: 64% / 36%».
- **Бот «Вопрос дня»** для школьных чатов в Telegram и VK.
- **«Золотой фонд» недели** — редакторская подборка самых абсурдных вопросов (с согласия авторов).
- **«Учёба».** Разборы заданий ЕГЭ от верифицированных экспертов (учителя, стобалльники) и связка с капчей: «Решил капчу? Хочешь ещё 5 таких?»
- **Кросспостинг** во ВК и Telegram-каналы.
- **Поиск:** сначала Postgres FTS, потом Meilisearch или OpenSearch.

---

## 8. Механики удержания и виральности

**Удержание**
- **Стрики.** День засчитывается, если ответил хотя бы на один вопрос, а не просто зашёл. Одна бесплатная «заморозка» в неделю. Огонёк растёт на отметках 7, 30, 100 и 365 дней.
- **Уровни 1–50** с названиями в духе рунета: «Нуб» → «Шарящий» → «Мудрец с подъезда» → «Легенда форума» → «Тот самый с Ответов».
- **Бейджи за конкретные вещи:**
  - «Спас перед контрольной» — «Схема» в комнате ЕГЭ меньше чем за 30 минут до 8:00;
  - «Ночной дозор» — ответы с 2 до 5 ночи;
  - «Дипломат» — ответ в холиваре, который плюсуют обе стороны;
  - «Как пожарить воду» — вопрос попал в Золотой фонд;
  - «Схематозник» — 100 «Схем».
- **Быстрая обратная связь.** Цель — медиана первого ответа меньше 5 минут. Для этого есть лента «Без ответа», где свежие вопросы поднимаются выше первые 10 минут. На ценность голосов это не влияет: правило +5 / ±1 не меняется.
- **Дайджест по пятницам:** «На этой неделе ты помог 12 людям, твои ответы прочитали 3400 раз».

**Виральность**
- Ссылка на профиль `schematoz-bulboz.org/@nick` с витриной бейджей и лучших ответов — чтобы ставить в био.
- В каждой картинке для сторис есть диплинк и QR. Переходы засчитываются пользователю: за 5 приглашённых — бейдж «Амбассадор».
- Итоги холиваров и Золотой фонд — готовые мемы для пабликов. Экспорт «в мем» одной кнопкой.
- SEO на вебе: каждый вопрос из «Знаний» — отдельная SSR-страница. Старый добрый поисковый трафик, на котором «Ответы» жили 15 лет.

---

## 9. Монетизация

Принцип: репутацию не продаём. Никогда.

1. **Подписка «Бульбоз+»** (~149 ₽/мес): кастомные темы профиля и карточек, анимированные бейджи, 3 заморозки стрика в неделю, расширенная статистика ответов.
2. **Косметика разовыми покупками:** рамки аватарок, стили карточек, стикеры.
3. **Нативная реклама в ленте** — карточка-вопрос от бренда с меткой «Реклама» и маркировкой по закону о рекламе (ERID).
4. **Образовательные партнёрства:** онлайн-школы подготовки к ЕГЭ спонсируют комнаты и бейджи. Реклама помечена и живёт отдельно, экспертность не продаётся.
5. **Бренд-холивары:** официальный дебат «Кола или Пепси?» с призом. Это игра, поэтому её не скипают.

---

## 10. Риски и митигация

| Риск | Почему опасно | Что делаем |
|---|---|---|
| **Буллинг в ответах и холиварах** | подростковая аудитория, претензии регуляторов | все пишут под своим ником; словарный фильтр оскорблений (правила и стоп-листы, без ML) отправляет ответ в премодерацию; «пожаловаться и заблокировать» в один тап; бан на комнату или глобальный |
| **Суицидальный / self-harm контент** | дети, закон, репутация | приоритет P0 в очереди; стоп-слова → мгновенное скрытие до проверки и контакты телефона доверия; SLA модерации P0 — 15 минут |
| **Спам и боты** | то, за что ругают перезапущенные «Ответы» | kremle-detect на входе и по триггерам, rate limit в Redis, simhash-дубли, ссылки от новых аккаунтов — в премодерацию, теневой бан для явных спамеров |
| **Накрутка репутации** | обесценивает прозрачность | голоса новых аккаунтов с `delta = 0`, отчёт по кольцам голосов, одна «Схема» на вопрос, аудит скачков в админке |
| **Законодательство РФ** (152-ФЗ, защита детей от вредной информации, ОРИ, маркировка рекламы) | штрафы, блокировка | ПД хранятся в РФ, юрист на этапе ТЗ, возрастная маркировка, регистрация в реестрах при необходимости; юридические страницы редактируются и версионируются |
| **Токсичность холиваров** | дебат превращается в срач | голосовать «за/против» можно только после просмотра хотя бы одного аргумента каждой стороны; бейдж «Дипломат»; более жёсткий порог модерации |
| **Пустая лента на старте** | Q&A без ответов мёртв | 30–50 комнат и амбассадоры-модераторы из фэндомов; «вопрос дня» от редакции; запуск к сезону ЕГЭ (март–май) |
| **Медиа позже сломают клиентов или БД** | долгий рефакторинг | enum и `answer_media` есть с первого дня, фича-флаги, эндпоинт `/capabilities`, фолбэк-рендер на клиентах (раздел 4) |
| **Производительность async-Flask** | отдельный event loop на запрос, пул asyncpg | NullPool + PgBouncer в MVP, нагрузочный тест (locust) до релиза, план Б — Quart без переписывания бизнес-логики |
| **Капча бесит людей** | отток на регистрации | лёгкие задания по умолчанию, выбор предмета, «пропустить и решить другую», A/B-тест порогов, конверсия капчи в админке |
| **Модераторы выгорают или злоупотребляют** | произвол | лог, в который можно только добавлять; админ видит всё; апелляции рассматривает другой модератор; баны дольше 7 дней — только с подтверждением админа |

---

## 11. Пользовательские сценарии

### 11.1. Зумер: Даша, 16 лет, 10 класс, фанатка Honkai: Star Rail

> 23:40. Завтра контрольная по физике, а Даша вообще не вдупляет, почему шарик падает с ускорением, а не с постоянной скоростью. Она открывает schematoz-bulboz.org и свайпает пару карточек в ленте «Для тебя». Одна из них — «Можно ли пожарить воду, если очень хочется?» из Золотого фонда. Поржала, плюсанула.
>
> Даша заходит в комнату «Физика 10 класс» и пишет вопрос. Через три минуты приходит текстовый ответ от @kotik_na_fizmate с пошаговым объяснением. Ещё один ответ — «ну это гравитация лол». Даша ставит первому 🔥🔥🔥🔥🔥: он получает +5 и становится «Схемой», а @kotik продвигается к бейджу «Спас перед контрольной». Второму — 👎 (−1). Ещё двое плюсуют «Схему» по +1.
>
> Перед сном Даша нажимает «Поделиться»: получается картинка «Мой вопрос решили за 3 минуты» с огоньком «стрик 12 дней», и она улетает в сторис ВК. Двое одноклассников переходят по QR и регистрируются, решив капчу. Один жалуется в чат, что «даже на сайте ЕГЭ заставляют решать», и это становится мемом класса.

### 11.2. Модератор: Артём, 21 год, студент, модерирует игровые комнаты

> После пар Артём заходит в `/mod`. В очереди 27 жалоб, сверху красная P0: в комнате «Отношения» ответ со словами из стоп-листа про самоповреждение. Система уже скрыла его и показала автору контакты помощи, но ждёт решения. Артём проверяет контекст, подтверждает скрытие и эскалирует к админу по регламенту. Действие записано в лог.
>
> Дальше рутина. На один ответ в холиваре «Дота vs Лига» пришло 8 жалоб. Это не оскорбление, просто неудобное мнение, и все жалобы от одной стороны холивара. Артём отклоняет все восемь, жалобщикам приходит «Нарушений не найдено». Следующий — спамер со ссылками на «бесплатные крутки». Перманент Артём дать не может, поэтому ставит 30 дней и отмечает «Рекомендую перманент» — это увидит админ. Через неделю один из забаненных подаёт апелляцию. Она уходит не Артёму, а другому модератору: никто не судит свои же решения.

### 11.3. Администратор: Лена, 27 лет, комьюнити-лид ООО «СукИнЭндСын»

> Понедельник. Лена открывает `/admin/analytics`. За выходные регистраций стало на 40% больше, но конверсия на шаге капчи упала с 82% до 64%. В разбивке видно, что массово валятся на литературе: «Кто автор „Бедной Лизы“?» внезапно не знает никто. Лена в `/admin/settings/captcha` убирает литературу из регистрации, оставляет её только для подозрительной активности и снижает сложность математики. Изменение пишется в лог под её ником.
>
> В логах модерации Лена видит, что Артём и ещё двое модераторов рекомендуют перманент одному спам-аккаунту, и подтверждает бан. Юрист прислал новую редакцию Политики конфиденциальности. Лена вставляет текст в `/admin/legal/privacy`, сверяет diff с прошлой версией и публикует. При следующем входе пользователи увидят «Мы обновили политику». В `/admin/settings/features` флаг «Голосовые ответы» пока серый — «ждём релиз 1.3».
>
> Напоследок Лена назначает Артёму роль `moderator` для новой комнаты «Genshin 5.x» и создаёт категорию «Профориентация»: до ЕГЭ месяц, народ будет спрашивать, куда поступать.

---

## 12. Нефункциональные требования

- p95 для API ленты — меньше 200 мс (кэш Redis), p95 для записи — меньше 400 мс.
- Доступность 99.5% на MVP.
- **Безопасность:** argon2id, CSRF-токены для cookie-сессий, CSP, санитизация пользовательского HTML, rate limit, логирование доступа к ПД, ежедневные бэкапы Postgres с PITR.
- **Наблюдаемость:** Sentry, Prometheus + Grafana, структурные логи.
- **CI:** ruff + mypy + pytest (pytest-asyncio, testcontainers с Postgres и Redis), `alembic upgrade head` на чистой БД в каждом PR. Отдельный тест: API отклоняет `content_type = voice/video`, пока флаг выключен.
- **Доступность (a11y):** контраст, крупные тап-зоны, поддержка VoiceOver и TalkBack.

---

<sub>разработано RUdolf1517 на основе технологий [rudolfzinovev.xyz](https://rudolfzinovev.xyz)</sub>
