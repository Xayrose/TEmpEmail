# TEMPMAIL

Telegram temporary-email bot and Mini App powered by [Mail.tm](https://mail.tm/).

## Included

- Telegram bot: create inboxes using available Mail.tm, Mail.gw and 1secmail domains, list inboxes, view incoming messages, refresh expiry timers and delete inboxes.
- Telegram Mini App: responsive Apple-inspired Liquid Glass interface, inbox creation, address copy, message list and plain-text message reader.
- FastAPI backend: Telegram Web App `initData` HMAC verification, inbox/message API, one-hour expiry, Telegram notifications for new messages and admin statistics endpoint. Admins also get a dashboard at `/static/admin.html`.
- SQLite storage and Docker deployment.

## Deploy

1. Create a bot with [@BotFather](https://t.me/BotFather).
2. Deploy this project to a server/container host with a persistent disk and public HTTPS URL. The Mini App and API are served from the **same origin** by FastAPI; GitHub Pages alone is not sufficient because it cannot run the Python API or bot.
3. Copy `.env.example` to `.env` and set:
   - `BOT_TOKEN`: Telegram bot token
   - `WEBAPP_URL`: public HTTPS URL of this app (for example `https://your-app.example.com`)
   - `ADMIN_IDS`: comma-separated numeric Telegram user IDs allowed to call the admin stats API
4. Run `docker compose up -d --build`.
5. In BotFather, set the Mini App/menu button URL to the same `WEBAPP_URL`.
6. Open the bot and send `/start`.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env
python bot.py
# in another terminal
uvicorn main:app --reload --port 8000
```

Telegram Mini Apps require HTTPS. For local testing, expose the server through a secure HTTPS tunnel and set `WEBAPP_URL` to that URL.

## Bot commands

- `/start` — main menu
- `/new` — create a temporary address
- `/mails` — list active inboxes
- `/app` — open the Mini App
- `/help` — command help

## API

- `GET /api/me`
- `GET /api/domains`
- `POST /api/inboxes` with `{"domain":"random"}` or an available domain
- `GET /api/inboxes`
- `DELETE /api/inboxes/{id}`
- `GET /api/inboxes/{id}/messages`
- `GET /api/inboxes/{id}/messages/{message_id}`
- `GET /api/admin/stats` (admins only)
- `GET /health`

All Mini App API calls require valid Telegram `initData`. Configure `ADMIN_IDS` to allow admin statistics access. The Mini App shows a dashboard link to authorized admins; the dashboard is served at `/static/admin.html`.

## Important security and provider notes

- Never commit `.env`, bot tokens, the SQLite database, or backups. The repository includes only a placeholder `.env.example`.
- The database directory must be on persistent storage; ephemeral container filesystems can erase inbox state on redeploy.
- The app displays plain-text email bodies only. It does not execute received HTML or expose attachments.
- The Mini App and Telegram bot aggregate currently available public domains from Mail.tm, Mail.gw and 1secmail. The list is dynamic and depends on each provider's live API response; arbitrary custom domains are not supported.
- The app enforces a one-hour local inbox lifetime for Mail.tm, Mail.gw and 1secmail addresses. Provider-side retention/deletion behavior may differ; the app removes expired inbox records and deletes Mail.tm/Mail.gw accounts where supported.
- The Mini App countdown is synchronized against server time and updates every second. Telegram messages show a snapshot; use the “Обновить таймер” button to refresh it.
- Use temporary inboxes only for non-sensitive communications. Review Mail.tm documentation, rate limits and acceptable-use terms before public or commercial deployment.
- The project has not been end-to-end tested against a live Telegram bot token and live Mail.tm account in this environment. Configure secrets and test on your own deployment before public use.
