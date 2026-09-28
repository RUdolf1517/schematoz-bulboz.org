# schematoz-bulboz.org

Q&A нового поколения для зумеров: вертикальная лента «вопрос → лучший ответ», тематические комнаты, холивары, прозрачная репутация.
Оператор сервиса — ООО «СукИнЭндСын». Продуктовый документ: [`docs/CONCEPT.md`](docs/CONCEPT.md).

## Стек

- Python 3.12+, Flask 3 с async-вьюхами, ASGI через `asgiref.WsgiToAsgi` + Hypercorn
- PostgreSQL 16, SQLAlchemy 2.0 (async) + asyncpg, миграции Alembic (async env)
- Redis: сессии, кэш прав и флагов, rate limit, антиспам
- Капча и антибот: [kremle-detect](https://github.com/RUdolf1517/KremleXYZ-Detect) (`KremleFlask`)

## Быстрый старт

### Запуск на своём компьютере (Mac / Linux)

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

brew install postgresql@16 && brew services start postgresql@16   # если Postgres ещё нет (Mac)
./scripts/setup_local_pg.sh --demo     # .env, роль и база bulboz, миграции, seed, демо-данные
flask --app app create-admin admin admin@example.com

hypercorn "app.asgi:asgi_app" --bind 0.0.0.0:8000
```

- `.env` читается автоматически (python-dotenv) — `export` не нужен.
- Если Redis не запущен, скрипт сам поставит `REDIS_URL=memory://`, для разработки этого хватает.
- `flask --app app doctor` проверяет PostgreSQL, миграции, роли и Redis и подсказывает, что делать.
- Если база недоступна, CLI и сервер выводят одну понятную строку вместо traceback: например, «В PostgreSQL нет роли bulboz → createuser -P bulboz» или «Postgres не запущен → brew services start postgresql@16». API в этом случае отвечает `503 db_unavailable`.

**Без установки Postgres и Redis вообще** (PostgreSQL 16 из pip-пакета pgserver):

```bash
./scripts/reset_dev_db.sh                         # БД в .pgdata + миграции + seed + демо
export DATABASE_URL=$(python scripts/dev_pg.py) REDIS_URL=memory:// DEMO_MODE=1
hypercorn "app.asgi:asgi_app" --bind 0.0.0.0:8000
```

### Прод

```bash
cp .env.example .env              # DATABASE_URL (через PgBouncer, обычно :6432), REDIS_URL, SECRET_KEY
alembic upgrade head && flask --app app seed
flask --app app create-admin admin admin@example.com
hypercorn "app.asgi:asgi_app" --bind 0.0.0.0:8000
# cron раз в сутки: flask --app app recompute-ratings
```

### Тестовые аккаунты (создаёт `scripts/demo_data.py`)

| Роль | Логин | Пароль |
|---|---|---|
| Администратор (+ модератор) | `admin` | `admin-demo-2026` |
| Модератор | `moder` | `moder-demo-2026` |
| Пользователь | `dasha`, `kotik_na_fizmate`, `artem`, `lena_2007` | `demo-password` |

С `DEMO_MODE=1` эта таблица показывается на странице входа. **В проде не запускать `demo_data.py` и не включать `DEMO_MODE`.**
Если сайт открыт в iframe на чужом домене (превью), добавь `COOKIE_CROSS_SITE=1`: cookie станут `SameSite=None; Secure`.

### Как устроен вход

1. «Войти» в хедере ведёт на `/login`. Там два способа:
   - ник или email и пароль;
   - **файл входа**: выбрать или перетащить `bulboz-ник.key`. Файл скачивается в своём профиле (блок «🔑 Файлы входа»): внутри ключ из 256 случайных бит, в БД хранится только его sha256. Одновременно можно держать до 5 файлов и отзывать их по одному. Потерянный файл — как утёкший пароль: отзови его.
2. Капча kremle-detect (задания ЕГЭ) включается только при подозрительной активности: 5+ неудачных входов (подбор пароля), частые регистрации, спам. Тогда API отвечает `captcha_required`, фронт уводит на `/captcha?next=…`, а пройденная капча тратится на одно действие.
3. Забаненный пользователь может войти, чтобы увидеть причину и подать апелляцию (`/banned`), но любые действия ему закрыты.

**Тесты** гоняются на настоящем PostgreSQL (pgserver) с миграциями Alembic:

```bash
pytest -q                 # 104 теста: API, RBAC, репутация, модерация, апелляции, уведомления, подписки, поиск, правка, страницы
```

E2E smoke в jsdom (настоящий `app.js` против живого сервера): см. [`tests/e2e/README.md`](tests/e2e/README.md).

## Страницы

| Путь | Что |
|---|---|
| `/` | Вертикальная лента со свайпами (scroll-snap, ↑↓ / j k, Enter — открыть). Вкладки: Горячее · Новое · ⭐ Топ (чистый рейтинг) · ⚔️ Холивары · Без ответа · Мои комнаты · Подписки. У карточек рейтинг и обложка |
| `/q/<id>` | Вопрос: ответы, голосование (у автора кнопки 🔥 +5 / 👎 −1, у остальных ▲ +1 / ▼ −1), холивар-бар, ▲/▼ за вопрос, комментарии к ответам (до 200 символов, markdown), форма ответа с markdown-панелью и 📷, жалобы, «В сторис», «изменить/удалить» на своём (с пометкой «изменено») |
| `/ask` | Задать вопрос: тип, обложка, markdown с картинками, комната. Холивар — только модеры и админы |
| `/debates` | Лента холиваров (ссылка в футере сразу после ленты) |
| `/rooms`, `/r/<slug>` | Комнаты: вступить или выйти, лента комнаты |
| `/u/<username>` | Профиль: уровень, стрик, репутация по темам, бейджи, лучшие ответы, картинка для сторис, подписка и счётчики, «❄️ заморозка доступна» |
| `/login`, `/register` | Вход по паролю или файлом входа, регистрация (капча — только при подозрительной активности) |
| `/notifications` | Уведомления: ответ на вопрос, «Схема», бейдж, подписчик, бан, решение по апелляции. Колокольчик в хедере с числом непрочитанных |
| `/search?q=` | Поиск по вопросам: полнотекстовый (русская морфология), если пусто — по подстроке |
| `/banned` | Причина бана и апелляция |
| `/mod` | Жалобы с превью контента, апелляции (кроме своих банов), свой лог |
| `/admin` | Аналитика, роли, капча, фича-флаги, юридические страницы с версиями, комнаты и категории, полный лог |
| `/rules` `/terms` `/privacy` `/requisites` | Юридические страницы |

- `/faq` — частые вопросы: аккордеон с поиском. Админ правит в админке → «Юр. страницы» → FAQ, каждый вопрос с новой строки `## Вопрос?`.
- `/settings` — настройки профиля с живым превью:
  - имя, био, статус с эмодзи, город, местоимения, «о себе» в markdown;
  - аватар и обложка (только из своих загрузок);
  - 10 тем, свой акцентный цвет, шрифт, стиль карточек, раскладка;
  - рамки аватара, открываются уровнем: неон 2, огонь 3, золото 5, радуга 8;
  - интересы, до 5 ссылок, витрина из 3 бейджей, закреплённый ответ;
  - скрытие разделов профиля (скрытое сервер чужим не отдаёт);
  - ключи входа.
  Сервер принимает только значения из белых списков, произвольный CSS/HTML запрещён. API: `GET/PATCH /api/me/profile`.

- `/kombucha` — мини-игра «Чайный гриб» (тамагочи), логика в `app/services/kombucha.py`:
  - показатели падают ступенькой раз в 12 часов, досчитывается при чтении, крон не нужен;
  - несколько грибов: 1 банка бесплатно, ещё до 4 покупаются за $₽; имя гриба уникально на весь сайт;
  - Легенда + 7 дней ухода = отросток (новый гриб, наследует мутацию);
  - 120 мутаций (по 20 на стадию, 4 редкости, номер экземпляра), заморозка и полка в профиле, грибной рынок, обмен и подарки, достижения, стена в профиле на всех стадиях, выпадают случайно по условиям, копятся в коллекции (`kombucha_codex`);
  - смерть → реанимация за $₽ / новое поколение / выбросить.
- `/wallet` — «Деревянные» ($₽), `app/services/wood.py`: начисляются за заход раз в день, вопросы, ответы, комментарии, холивары, «Схемы», уход за грибом и мутации. Журнал `wood_tx` с уникальным `(user, reason, ref)` не даёт начислить дважды, на «фармовые» причины есть дневные лимиты.

## Важные решения

| Что | Как |
|---|---|
| Async во Flask | Flask запускает каждую async-вьюху в отдельном event loop, поэтому engine работает с `NullPool` (пул держит PgBouncer). Сессия открывается и закрывается внутри одной корутины (`app/db.py`). План Б — Quart. |
| Redis | Синхронный `redis-py`: он не привязан к event loop, вызовы занимают микросекунды |
| Репутация | Автор вопроса ставит ответу **только +5 или −1**, остальные — **только ±1**. Правило проверяется в `app/services/reputation.py` и дублируется CHECK-ограничением в таблице `votes`. Ответ с +5 от автора становится «Схемой». |
| RBAC | Права вместо жёстких ролей (`app/permissions.py`). Декоратор `@require_perm(...)` проверяет вход, бан и права на уровне API. |
| Лог модерации | Пишется в той же транзакции, что и действие. Триггер в БД запрещает UPDATE и DELETE. |
| Капча | Только `@captcha_required()`: включается, когда антиспам пометил клиента подозрительным (подбор пароля, флуд регистраций, спам). Пройденная капча тратится на одно действие. |
| Рейтинги | Формулы — в `app/services/rating.py` (подробно — `docs/CONCEPT.md`, раздел «Рейтинги»). Юзер: «Бульбоз-индекс» из активности, ответов и их оценок, «Схем», вопросов, комментариев; у админа и модера ∞ (`rating_tier` 2 и 1). Вопрос: голоса ±1 + 2×ответы + 0.5×комментарии. Ответы и комментарии сортируются по tier автора, потом по рейтингу. Раз в сутки — `flask recompute-ratings` (cron), чтобы «свежесть» таяла |
| Markdown и картинки | Рендер на сервере + nh3. Картинки только свои (`/media/…webp`, загрузка `POST /api/uploads`): пережимаются в WebP ≤1600px, EXIF/геометки удаляются. Внешние `<img>` вырезаются — не утекают IP читателей |
| Правка и удаление | Заголовок вопроса нельзя менять после первого ответа (`title_locked`), подробности — можно. Вопрос со «Схемой» удалить нельзя (`has_scheme`). Удалённый контент скрывается (soft delete), репутация за него не откатывается. |
| Заморозка стрика | Раз в ISO-неделю один пропущенный день не сбрасывает стрик — заморозка тратится автоматически. |
| Ответы | Сейчас только текст. Голосовые и видео подготовлены: enum `answer_content_type`, таблица `answer_media`, заглушки обработчиков в `app/services/answer_content/`, фича-флаги, `GET /api/answers/capabilities`. План внедрения описан в `media.py`. |
| Футер | `app/templates/_footer.html` подключается на всех HTML-страницах, из админки не редактируется. У страницы капчи свой шаблон на основе библиотечного, футер там тоже есть. |
| Геймификация | Стрик засчитывается за день, в который был хотя бы один ответ (дни по Москве). Уровни 1–50 с названиями, 10 бейджей (`app/services/gamification.py`). |

## API (MVP)

| Метод | Путь | Право |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login` | — (капча при подозрительной активности) |
| PATCH / DELETE | `/api/questions/<id>`, `/api/answers/<id>` | автор |
| PUT / DELETE | `/api/questions/<id>/vote` `{"value": 1 \| -1}` | `vote.cast`, не свой вопрос |
| POST | `/api/answers/<id>/comments` `{"body"}` (≤200) · PATCH / DELETE `/api/comments/<id>` | `answer.create` / автор |
| POST | `/api/uploads` (multipart `file`, ≤8 МБ, JPEG/PNG/WebP/GIF) → `{url, markdown}` · GET `/media/<name>` | `answer.create` |
| GET / POST | `/api/auth/login-keys` (POST отдаёт содержимое файла один раз) · DELETE `/api/auth/login-keys/<id>` | вход |
| POST | `/api/auth/login-file` `{"key": "sbk_…"}` или `{"file": {...}}` | — (капча после 5 промахов) |
| GET | `/api/notifications` · POST `/api/notifications/read` `{"ids": [...]}` (без ids — все) | вход |
| PUT / DELETE | `/api/users/<username>/follow` | вход |
| GET | `/api/search?q=` (ответ содержит `mode`: `fulltext` \| `substring`) | — |
| POST | `/api/auth/logout` · GET `/api/auth/me` | — / вход |
| GET | `/api/feed?tab=hot\|new\|top\|debates\|unanswered\|my_rooms\|following&room=` | — |
| POST | `/api/questions` (`cover_url`; `kind=debate` — нужно `debate.create`) | `question.create` |
| GET | `/api/questions/<id>` | — |
| POST | `/api/questions/<id>/answers` | `answer.create` |
| GET | `/api/answers/capabilities` | — |
| PUT / DELETE | `/api/answers/<id>/vote` `{"value": 5 \| -1 \| 1}` | `vote.cast` |
| POST | `/api/reports` | `report.create` |
| GET | `/api/users/<username>` (репутация по темам, бейджи, лучшие ответы) | — |
| GET | `/api/rooms`, `/api/rooms/<slug>`, `/api/categories` | — |
| POST / DELETE | `/api/rooms/<slug>/join` | вход |
| PUT | `/api/questions/<id>/debate-vote` `{"side": "a" \| "b"}` | `vote.cast` |
| GET | `/api/me/ban` · POST `/api/bans/<id>/appeal` | вход (бан не мешает) |
| GET | `/api/share/answer/<id>.png`, `/api/share/user/<username>.png` (1080×1920) | — |
| GET | `/mod/appeals` · POST `/mod/appeals/<ban_id>/decide` | `report.review`, не свой бан |
| GET | `/mod/reports` · POST `/mod/reports/<id>/resolve` | `report.review` |
| POST | `/mod/content/<question\|answer\|comment>/<id>/hide\|restore` | `content.hide` / `content.restore` |
| POST | `/mod/bans` (≤30 дней; перманент — `ban.permanent`) · `/mod/bans/<id>/lift` | `ban.temporary` |
| GET | `/mod/log` | `modlog.read_own` |
| GET | `/admin/modlog` · `/admin/analytics` · `/admin/users?q=` | `modlog.read_all` · `analytics.read` · `role.assign` |
| PUT | `/admin/users/<id>/roles` | `role.assign` |
| POST | `/admin/categories` · `/admin/rooms` | `category.manage` · `room.manage` |
| GET / PUT | `/admin/settings/<captcha\|antispam\|features>` | `settings.*` |
| PUT | `/admin/legal/<rules\|terms\|privacy\|requisites>` · GET `…/versions` | `legal.edit` |
| GET | `/rules` `/terms` `/privacy` `/requisites` (HTML), `/api/legal/<slug>` | — |

---

<sub>разработано RUdolf1517 на основе технологий [rudolfzinovev.xyz](https://rudolfzinovev.xyz)</sub>


## Чайный гриб: хардкор, цитаты, задания (13-й заход)

- **Хардкор:** показатели падают сильнее, гриб закисает через 12 ч на нуле, до «Легенды» нужно 4000 XP, при показателе ниже 30 опыт режется вдвое. **Плесень** заводится в грязной банке и лечится уксусной ванной.
- **Деление раз в неделю** на последней стадии (нужны 7 дней ухода и отсутствие плесени).
- **240 мутаций (гриб получает только мутации своей текущей стадии, не больше 3 на стадию — итого до 18)** (по 40 на стадию) с номерами экземпляров и тиражом.
- **🤚 Погладить** — цитаты сомнительных личностей, **💭 Поговорить с грибом** — диалоги из философских книг. Все цитаты только на русском: ответ API принимается, если в нём кириллица. Внешние API задаются в `QUOTES_DUBIOUS_URLS` (по умолчанию пусто — встроенный корпус) и `QUOTES_PHILO_URLS` (по умолчанию Forismatic, `lang=ru`), выключатель — `QUOTES_REMOTE`. В облачке гриб цитирует тех же сомнительных личностей, что и по кнопке «Погладить», кроме сахарной комы. Таймаут 1,5 с, кэш в Redis, после ошибки пауза 10 минут, запасной вариант — встроенный русский корпус.
- **Подарки как в Telegram:** подпись к подарку, публичная карточка гриба (`GET /api/kombucha/<id>/card`) с номерами мутаций и историей владельцев.
- **Задания за $₽** (`/tasks`): эскроу «награда × места + 10% комиссии», отклики, зачёт или отказ с причиной, автозачёт через 72 ч, спор у модератора, возврат остатка. API: `GET/POST /api/tasks`, `GET /api/tasks/<id>`, `POST /api/tasks/<id>/submit|close`, `POST /api/task-submissions/<id>/approve|reject|dispute`, `GET /api/mod/task-disputes`, `POST /api/mod/task-submissions/<id>/approve|reject`, `POST /api/mod/tasks/<id>/remove`.
- **Стена в профиле** (с 12-го захода): писать может любой вошедший.
- Миграция `0010_tasks_hardcore`.
