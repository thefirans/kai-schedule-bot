"""
Configuration for NAU Schedule Bot.
Copy this file to config.py and fill in your values:

    cp config.example.py config.py
"""
from datetime import date

# ── Telegram Bot ──
# 1. Message @BotFather on Telegram, send /newbot, follow steps
# 2. Copy the token here
BOT_TOKEN = "8580521337:AAFZ5WZ_sghOne-Zm73_-xgn_poYtBNTqww"

# Your personal Telegram chat ID.
# To find it: message @userinfobot or @RawDataBot on Telegram
CHAT_ID = 332356894

# ── NAU Cabinet credentials ──
NAU_USERNAME = "7447512"
NAU_PASSWORD = "0669499079sasha*"

# ── Schedule settings ──
# How many minutes before a lesson to send a reminder
REMINDER_MINUTES = 5

# A Monday that falls on week 1 of your schedule.
# Look at your current schedule — if this week is "1 тиждень",
# set this to the Monday of this week. If it's "2 тиждень",
# set it to LAST Monday.
# Example: if Feb 10, 2026 (Tuesday) is week 2, then
# Feb 2, 2026 (Monday) was week 1 start.
WEEK1_START_DATE = date(2026, 2, 2)
