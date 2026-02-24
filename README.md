# NAU Schedule Bot 🎓

Telegram bot that scrapes your schedule from `cabinet.nau.edu.ua` and sends reminders before lessons.

## Features

- **Multi-user** — share with friends, each person links their own NAU account
- **In-chat registration** — no config files, just `/start` and enter credentials
- **Password auto-delete** — credential messages are deleted from chat immediately
- **Smart caching** — schedule is cached in SQLite, refreshed every 6 hours
- 🔔 Configurable reminders (5/10/15/30 min before lesson)
- 🌅 Morning schedule at 07:00 every day
- Bi-weekly schedule support (тиждень 1 / тиждень 2)

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Register or see help |
| `/today` | Today's schedule |
| `/tomorrow` | Tomorrow's schedule |
| `/week` | Full current week |
| `/next` | Next upcoming lesson |
| `/refresh` | Force re-fetch from NAU |
| `/settings` | Change reminder timing |
| `/logout` | Delete your data |

## Quick Start

### 1. Create a Telegram bot

1. Open Telegram → find **@BotFather**
2. Send `/newbot`, pick a name
3. Copy the token

### 2. Install & run

```bash
pip install -r requirements.txt

# Set your bot token and week reference
export BOT_TOKEN="your_token_from_botfather"
export WEEK1_START="2026-02-02"   # any Monday that is week 1

python3 bot.py
```

### 3. Configure the week

`WEEK1_START` should be any Monday that falls on "1 тиждень" in your schedule.
Look at your cabinet — if the current week shows "2 тиждень" and today is
Tuesday Feb 11, then last Monday (Feb 2) was week 1. So set `WEEK1_START=2026-02-02`.

## Run on a Server

### Using systemd

```bash
sudo tee /etc/systemd/system/nau-bot.service << EOF
[Unit]
Description=NAU Schedule Bot
After=network.target

[Service]
User=$USER
WorkingDirectory=/path/to/nau-schedule-bot
Environment=BOT_TOKEN=your_token_here
Environment=WEEK1_START=2026-02-02
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now nau-bot
```

### Using Docker (optional)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python3", "bot.py"]
```

```bash
docker build -t nau-bot .
docker run -d --name nau-bot \
  -e BOT_TOKEN="your_token" \
  -e WEEK1_START="2026-02-02" \
  -v nau-bot-data:/app \
  nau-bot
```

## How It Works

1. User sends `/start` → bot asks for NAU username and password
2. Password message is immediately deleted from chat
3. Bot logs into cabinet.nau.edu.ua, fetches schedule HTML
4. Schedule is parsed and cached in SQLite (`bot.db`)
5. Every 60 seconds, bot checks if any user has a lesson coming up
6. Every morning at 07:00, bot sends the day's schedule
7. Cache refreshes every 6 hours automatically

## Troubleshooting

**Login fails?** The login form field names might differ. Open browser DevTools →
Network tab → log in manually → check the POST payload field names.
Update `scraper.py` accordingly.

**Wrong week shown?** Adjust `WEEK1_START` — it must be a Monday that is "1 тиждень".

**Bot can't delete messages?** In group chats the bot needs admin "delete messages" permission.
In private chats it should work automatically.

## Files

```
bot.py          — main bot logic, commands, jobs
scraper.py      — NAU login + HTML schedule parser
database.py     — SQLite storage for users and cached schedules
requirements.txt
```
