# TEMPMAIL

Telegram temporary-email bot and Mini App powered by [Mail.tm](https://mail.tm/).

## Included

- Telegram bot: create inboxes, choose a Mail.tm domain or random domain, list inboxes, view incoming messages and delete inboxes.
- Telegram Mini App: responsive Apple-inspired Liquid Glass interface, inbox creation, address copy, message list and plain-text message reader.
- FastAPI backend: Telegram Web App `initData` HMAC verification, inbox/message API, one-hour expiry, Telegram notifications for new messages and admin statistics endpoint.
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

All Mini App API calls require valid Telegram `initData`. Configure `ADMIN_IDS` to allow admin statistics access.

## Important security and provider notes

- Never commit `.env`, bot tokens, the SQLite database, or backups. The repository includes only a placeholder `.env.example`.
- The database directory must be on persistent storage; ephemeral container filesystems can erase inbox state on redeploy.
- The app displays plain-text email bodies only. It does not execute received HTML or expose attachments.
- Available domains are supplied by Mail.tm; arbitrary custom domains are not supported.
- Use temporary inboxes only for non-sensitive communications. Review Mail.tm documentation, rate limits and acceptable-use terms before public or commercial deployment.
- The project has not been end-to-end tested against a live Telegram bot token and live Mail.tm account in this environment. Configure secrets and test on your own deployment before public use.
