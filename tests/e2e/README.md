# E2E smoke (jsdom)

Прогоняет настоящий `app.js` против живого сервера: лента, вопрос, вход через форму,
редактирование, поиск, подписки, уведомления, голосование (+5/−1 автора, ±1 остальных), ответ, холивар, комнаты, профиль,
мод-панель и все вкладки админки. Сценарий меняет данные, поэтому запускай на свежей БД.

```bash
./scripts/reset_dev_db.sh
DATABASE_URL=$(.venv/bin/python scripts/dev_pg.py) REDIS_URL=memory:// DEMO_MODE=1 ANTIBOT_DISABLED=1 \
  .venv/bin/hypercorn app.asgi:asgi_app --bind 127.0.0.1:8001 &
cd tests/e2e && npm i jsdom@24 && NODE_PATH=$PWD/node_modules node smoke.js
```

Дополнительно `node tilt_music_check.js` (тот же сервер и jsdom) проверяет мобильный наклон жидкости:
авто-включение датчика без нажатия, фолбэк-кнопку (iOS/без показаний датчика), отказ в разрешении
и отсутствие кнопок музыки.
