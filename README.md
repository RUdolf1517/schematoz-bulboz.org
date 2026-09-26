# schematoz-bulboz.org

Q&A нового поколения для зумеров: вертикальная лента «вопрос → лучший ответ», тематические комнаты, холивары, прозрачная репутация.
Оператор сервиса — ООО «СукИнЭндСын». Продуктовый документ: [`docs/CONCEPT.md`](docs/CONCEPT.md).

## Стек

- Python 3.12+, Flask 3 с async-вьюхами, ASGI через `asgiref.WsgiToAsgi` + Hypercorn
- PostgreSQL 16, SQLAlchemy 2.0 (async) + asyncpg, миграции Alembic (async env)
- Redis: сессии, кэш прав и флагов, rate limit, антиспам
- Капча и антибот: [kremle-detect](https://github.com/RUdolf1517/KremleXYZ-Detect) (`KremleFlask`)

## Быстрый старт

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env              # укажи DATABASE_URL и REDIS_URL
export $(grep -v '^#' .env | xargs)

alembic upgrade head              # схема БД
flask --app app seed              # роли, права, юр. страницы, стартовые комнаты
flask --app app create-admin admin admin@example.com

hypercorn "app.asgi:asgi_app" --bind 0.0.0.0:8000
```

**Без Docker, Postgres и Redis** (только для разработки):

```bash
./scripts/reset_dev_db.sh                         # PostgreSQL 16 из pip-пакета pgserver + миграции + seed + демо
export DATABASE_URL=$(python scripts/dev_pg.py) REDIS_URL=memory:// DEMO_MODE=1
hypercorn "app.asgi:asgi_app" --bind 0.0.0.0:8000
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

1. «Войти» в хедере ведёт на `/login`, оттуда на капчу kremle-detect (задания ЕГЭ), после решения обратно на `/login`.
2. Пройденная капча тратится на одну попытку входа или регистрации.
3. Забаненный пользователь может войти, чтобы увидеть причину и подать апелляцию (`/banned`), но любые действия ему закрыты.

**Тесты** гоняются на настоящем PostgreSQL (pgserver) с миграциями Alembic:

```bash
pytest -q                 # 77 тестов: API, RBAC, репутация, модерация, апелляции, страницы
```

E2E smoke в jsdom (настоящий `app.js` против живого сервера): см. [`tests/e2e/README.md`](tests/e2e/README.md).

## Страницы

| Путь | Что |
|---|---|
| `/` | Вертикальная лента со свайпами (scroll-snap, ↑↓ / j k, Enter — открыть). Вкладки: Горячее · Новое · Без ответа · Мои комнаты |
| `/q/<id>` | Вопрос: ответы, голосование (у автора кнопки 🔥 +5 / 👎 −1, у остальных ▲ +1 / ▼ −1), холивар-бар, форма ответа, жалобы, «В сторис» |
| `/ask` | Задать вопрос (мнение / знания / история / холивар, комната) |
| `/rooms`, `/r/<slug>` | Комнаты: вступить или выйти, лента комнаты |
| `/u/<username>` | Профиль: уровень, стрик, репутация по темам, бейджи, лучшие ответы, картинка для сторис |
| `/login`, `/register` | Вход и регистрация через капчу kremle-detect |
| `/banned` | Причина бана и апелляция |
| `/mod` | Жалобы с превью контента, апелляции (кроме своих банов), свой лог |
| `/admin` | Аналитика, роли, капча, фича-флаги, юридические страницы с версиями, комнаты и категории, полный лог |
| `/rules` `/terms` `/privacy` `/requisites` | Юридические страницы |

## Важные решения

| Что | Как |
|---|---|
| Async во Flask | Flask запускает каждую async-вьюху в отдельном event loop, поэтому engine работает с `NullPool` (пул держит PgBouncer). Сессия открывается и закрывается внутри одной корутины (`app/db.py`). План Б — Quart. |
| Redis | Синхронный `redis-py`: он не привязан к event loop, вызовы занимают микросекунды |
| Репутация | Автор вопроса ставит ответу **только +5 или −1**, остальные — **только ±1**. Правило проверяется в `app/services/reputation.py` и дублируется CHECK-ограничением в таблице `votes`. Ответ с +5 от автора становится «Схемой». |
| RBAC | Права вместо жёстких ролей (`app/permissions.py`). Декоратор `@require_perm(...)` проверяет вход, бан и права на уровне API. |
| Лог модерации | Пишется в той же транзакции, что и действие. Триггер в БД запрещает UPDATE и DELETE. |
| Капча | `@captcha_required(always=True)` на регистрации и входе. `@captcha_required()` включается, когда антиспам пометил клиента подозрительным. Пройденная капча тратится на одно действие. |
| Ответы | Сейчас только текст. Голосовые и видео подготовлены: enum `answer_content_type`, таблица `answer_media`, заглушки обработчиков в `app/services/answer_content/`, фича-флаги, `GET /api/answers/capabilities`. План внедрения описан в `media.py`. |
| Футер | `app/templates/_footer.html` подключается на всех HTML-страницах, из админки не редактируется. У страницы капчи свой шаблон на основе библиотечного, футер там тоже есть. |
| Геймификация | Стрик засчитывается за день, в который был хотя бы один ответ (дни по Москве). Уровни 1–50 с названиями, 10 бейджей (`app/services/gamification.py`). |

## API (MVP)

| Метод | Путь | Право |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login` | капча |
| POST | `/api/auth/logout` · GET `/api/auth/me` | — / вход |
| GET | `/api/feed?room_id=&cursor=` | — |
| POST | `/api/questions` | `question.create` |
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
| POST | `/mod/content/<question\|answer>/<id>/hide\|restore` | `content.hide` / `content.restore` |
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
