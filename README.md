# schematoz-bulboz.org

Тамагочи про чайный гриб: растишь гриба в банке, ловишь мутации, играешь в мини-игры, торгуешь грибами на рынке и меняешься с друзьями.
Оператор сервиса — ООО «СукИнЭндСын». Продуктовый документ: [`docs/CONCEPT.md`](docs/CONCEPT.md).

## Стек

- Python 3.12+, Flask 3 с async-вьюхами, ASGI через `asgiref.WsgiToAsgi` + Hypercorn
- PostgreSQL 16, SQLAlchemy 2.0 (async) + asyncpg, миграции Alembic (async env)
- Redis: сессии, кэш прав, rate limit, антиспам
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

**Установка на сервер одной командой** (Ubuntu 24.04 / Debian 12+, домен уже смотрит на сервер):

```bash
git clone https://github.com/RUdolf1517/schematoz-bulboz.org.git && cd schematoz-bulboz.org
sudo ./scripts/deploy.sh schematoz-bulboz.org you@mail.ru
```

Ставит PostgreSQL, Redis, Python 3.12, создаёт базу и `.env` со случайными секретами, миграции, админа (пароль печатается в конце), systemd-сервис, nginx + HTTPS, ежедневные бэкапы и файрвол. Обновление: `git pull && sudo ./scripts/deploy.sh --update`.

nginx перед приложением: `sudo ./scripts/install_nginx.sh твой-домен.ru почта@для-letsencrypt.ru` — ставит nginx, отдаёт `/static` и `/media` с диска, проксирует остальное на `127.0.0.1:8000`, rate limit на `/api`, HTTPS через certbot (если указан email).

```bash
cp .env.example .env              # DATABASE_URL (через PgBouncer, обычно :6432), REDIS_URL, SECRET_KEY
alembic upgrade head && flask --app app seed
flask --app app create-admin admin admin@example.com
hypercorn "app.asgi:asgi_app" --bind 0.0.0.0:8000
```

### Тестовые аккаунты (создаёт `scripts/demo_data.py`)

| Роль | Логин | Пароль |
|---|---|---|
| Администратор | `admin` | `admin-demo-2026` |
| Пользователь | `dasha`, `kotik_na_fizmate`, `artem`, `lena_2007` | `demo-password` |

С `DEMO_MODE=1` эта таблица показывается на странице входа. **В проде не запускать `demo_data.py` и не включать `DEMO_MODE`.**
Если сайт открыт в iframe на чужом домене (превью), добавь `COOKIE_CROSS_SITE=1`: cookie станут `SameSite=None; Secure`.

### Как устроен вход

1. «Войти» в хедере ведёт на `/login`. Там два способа:
   - ник или email и пароль;
   - **файл входа**: выбрать или перетащить `bulboz-ник.key`. Файл скачивается в своём профиле (блок «🔑 Файлы входа»): внутри ключ из 256 случайных бит, в БД хранится только его sha256. Одновременно можно держать до 5 файлов и отзывать их по одному. Потерянный файл — как утёкший пароль: отзови его.
2. Капча kremle-detect (задания ЕГЭ) включается только при подозрительной активности: 5+ неудачных входов (подбор пароля), частые регистрации, спам. Тогда API отвечает `captcha_required`, фронт уводит на `/captcha?next=…`, а пройденная капча тратится на одно действие.
3. Забаненный пользователь может войти, чтобы увидеть причину и подать апелляцию (`/banned`), но рынок, обмены, загрузки и правка профиля ему закрыты.

**Тесты** гоняются на настоящем PostgreSQL (pgserver) с миграциями Alembic:

```bash
pytest -q                 # 100 тестов: гриб, мутации, мини-игры, рынок, RBAC, модерация, апелляции, профиль, страницы
```

E2E smoke в jsdom (настоящий `app.js` против живого сервера): см. [`tests/e2e/README.md`](tests/e2e/README.md).

## Страницы

| Путь | Что |
|---|---|
| `/` | Гость — лендинг с живым грибом и топом банок. Вошедший — **мой гриб** (`kombucha.html`): уход, мутации, мини-игры, медитация, банки, полноэкранный режим |
| `/kombucha` | Редирект на `/` (старые ссылки) |
| `/g/<id>` | Дневник гриба: 🌳 родословная (предки, братья, дети, внуки) и лента событий, можно поделиться |
| `/market` | Грибной рынок и обмены/подарки |
| `/wallet` | «Деревянные» ($₽): баланс, как заработать, история |
| `/u/<username>` | Профиль грибовода: статистика, любимый гриб, подоконник, полка, бейджи |
| `/settings` | Настройка профиля с живым превью |
| `/notifications` | Бейджи, продажи, обмены, баны, апелляции |
| `/login`, `/register`, `/banned`, `/faq`, `/rules`, `/terms`, `/privacy`, `/requisites` | Вход, бан и апелляция, FAQ и юр. страницы (правит админ) |
| `/mod` | Редирект в админку (модераторов нет) |
| `/admin` | Аналитика, игроки и баны, апелляции, 💬 цитаты гриба, роли, капча, юр. страницы, лог, дебаг мутаций |

## Экономика $₽

$₽ начисляются **только** за уход за грибом, мини-игры и медитацию, ежедневный вход и «Бонус дня» (плюс мутации и отростки как часть ухода, и выручка с продажи). Правила — `EARN` в `app/services/wood.py`; журнал `wood_tx` с уникальным `(user, reason, ref)` не даёт начислить дважды, на фармовые причины есть дневные лимиты. Тратятся на банки, реанимацию и покупки на рынке (комиссия 5% сгорает).

## Важные решения

| Что | Как |
|---|---|
| Async во Flask | Каждая async-вьюха — в своём event loop, поэтому `NullPool` (пул держит PgBouncer) и сессия БД живёт внутри одной корутины |
| Redis | Синхронный `redis-py` |
| RBAC | Две роли — игрок и админ (`app/permissions.py`), модераторов нет (миграция `0013`). `@require_perm` проверяет вход, бан и права |
| Цитаты | Встроенный корпус в `services/quotes.py` + свои из админки (таблица `kombucha_quotes`, кэш в Redis, поднимается из БД после рестарта) |
| Капча | `@captcha_required()` только при подозрительной активности (подбор пароля, флуд регистраций, рынок) |
| Лог модерации | В той же транзакции, что и действие; триггер запрещает UPDATE/DELETE |
| Уровни | Уровень = 1 + (мутаций в коллекции) / 5, до 50; стрик — дни ухода подряд, раз в неделю заморозка |
| Футер | `app/templates/_footer.html` на всех страницах, из админки не редактируется |
| Q&A | Удалён полностью (миграция `0012`): вопросы, ответы, комнаты, холивары, репутация, стена, задания |

## Чайный гриб

- Логика — `app/services/kombucha.py`, мутации — `kombucha_mutations.py` (240 штук, по 40 на стадию, не больше 3 на стадию, каждая меняет внешний вид), дневник — `kombucha_diary.py`.
- Показатели падают раз в 12 часов, досчитываются при чтении. Деление — только на последней стадии.
- 🌱 Деление: на последней стадии, раз в 7 дней, не больше 3 раз за жизнь гриба, нужны 3 дня ухода. Плесень — шанс на каждой ступеньке: 10% в грязной банке (чистота < 20), 3% в чистой.
- 🎮 Мини-игры (`minigames.py`): «Налей», «Память», «Сахар или соль», «Мушки»; 🧘 медитация-ритм (`meditation.py`). Награды — $₽, мутации, счастье; без рекордов.
- 🤚 «Погладить» и облачко — спорные цитаты от первого лица, только на русском.
- Заморозка, полка, рынок, обмены и подарки — `app/api/market.py`.
- Админ-дебаг мутаций — вкладка «🍄 Грибы (дебаг)».

## Защита от автокликеров

`app/services/antibot.py`. Мини-игры и медитация проверяют:
- реакцию: больше 40% тапов быстрее 120 мс — бот;
- разброс: живой человек не попадает с отклонением меньше 8 мс (реакция) и 4 мс (ритм медитации);
- «Налей»: 6 почти идеальных наливов подряд при помехах;
- синтетические события: клиент считает `!e.isTrusted` и шлёт `meta.synthetic`.

Подозрительная партия ничего не приносит (точность 0, без $₽ и мутаций). 3 такие партии за сутки — следующая игра только после капчи kremle-detect. Админ видит 🤖 счётчик в поиске игроков. В e2e на jsdom клики синтетические — сервер для e2e запускай с `ANTIBOT_DISABLED=1` (на проде не включать!).

## PWA

`/manifest.webmanifest`, `/sw.js` (из `app/static/pwa/`), `/offline`. Статика и картинки — cache-first (версия кэша = хеш ассетов), страницы — из сети с офлайн-заглушкой, `/api` не кэшируется. Service worker работает только по HTTPS (или на localhost). Баннер «Установить» показывается один раз.

## API

| Метод | Путь | Право |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login`, `/api/auth/login-file`, `/api/auth/logout` · GET `/api/auth/me` | — |
| GET / POST / DELETE | `/api/auth/login-keys[/<id>]` | вход |
| POST | `/api/auth/password` — смена пароля `{current_password, new_password}`; остальные сессии отзываются, перебор → капча | вход |
| GET | `/api/kombucha` · `/api/kombucha/top` · `/api/wallet` | вход / — / вход |
| POST | `/api/kombucha/<id>/<sugar\|tea\|clean\|pet\|talk\|cure\|daily>` | вход |
| POST | `/api/kombucha/<id>/game/<pour\|memory\|sugar\|flies>/start\|finish`, `/meditate/start\|finish` | вход |
| PATCH / DELETE | `/api/kombucha/<id>` · POST `…/restart`, `…/revive`, `/api/kombucha/plant`, `/api/shop/jar` | вход |
| POST | `/api/kombucha/<id>/freeze\|unfreeze` | вход |
| POST / DELETE | `/api/kombucha/<id>/list` | `market.trade` |
| GET | `/api/market` · POST `/api/market/<id>/buy` | — · `market.trade` |
| GET / POST | `/api/trades` · POST `/api/trades/<id>/accept\|decline\|cancel` | вход / `market.trade` |
| GET | `/api/users/<username>` · `/api/users/<username>/shelf` · `/api/kombucha/<id>/card` · `/api/kombucha/<id>/tree` | — |
| GET / POST · PATCH / DELETE | `/admin/quotes` · `/admin/quotes/<id>` | `quotes.edit` |
| GET / PATCH | `/api/me/profile` | вход / `kombucha.play` |
| POST | `/api/uploads` | `kombucha.play` |
| GET | `/api/notifications` · POST `/api/notifications/read` | вход |
| GET | `/api/me/ban` · POST `/api/bans/<id>/appeal` | вход (бан не мешает) |
| GET | `/mod/users?q=` · POST `/mod/bans`, `/mod/bans/<id>/lift` | `ban.temporary` |
| GET | `/mod/appeals` · POST `/mod/appeals/<id>/decide` · GET `/mod/log` | `ban.temporary` · `modlog.read_own` |
| GET | `/admin/analytics` · `/admin/modlog` · `/admin/users?q=` · PUT `/admin/users/<id>/roles` | `analytics.read` · `modlog.read_all` · `role.assign` |
| GET / PUT | `/admin/settings/<captcha\|antispam>` · PUT `/admin/legal/<slug>` | `settings.*` · `legal.edit` |

---

<sub>разработано RUdolf1517 на основе технологий [rudolfzinovev.xyz](https://rudolfzinovev.xyz)</sub>
