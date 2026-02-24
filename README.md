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

## Files

```
bot.py          — main bot logic, commands, jobs
scraper.py      — NAU login + HTML schedule parser
database.py     — SQLite storage for users and cached schedules
requirements.txt
```
