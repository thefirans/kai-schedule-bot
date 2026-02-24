"""
NAU Schedule Telegram Bot — Production version
Multi-user, SQLite-backed, with conversation registration flow.

Updated: now uses semester week numbers (1-18) from NAU cabinet
instead of the old bi-weekly (1/2) system. No more WEEK1_START env var.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from scraper import fetch_schedule, Lesson, DAYS_NORMALIZED
from database import (
    init_db, save_user, get_user, get_all_active_users,
    delete_user, update_reminder_minutes,
    cache_lessons, get_cached_lessons, User,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────
KYIV_TZ = ZoneInfo("Europe/Kyiv")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CACHE_TTL = timedelta(hours=6)

# ── Conversation states ─────────────────────────────────────────
ASK_USERNAME, ASK_PASSWORD, CONFIRM_LOGIN = range(3)
ASK_NEW_REMINDER = 100

DAY_MAP = {
    0: "Понеділок", 1: "Вівторок", 2: "Середа", 3: "Четвер",
    4: "П'ятниця", 5: "Субота", 6: "Неділя",
}

HELP_TEXT = (
    "*Команди:*\n"
    "/today — розклад на сьогодні\n"
    "/tomorrow — розклад на завтра\n"
    "/week — весь тиждень\n"
    "/nextweek — наступний тиждень\n"
    "/next — наступна пара\n"
    "/refresh — оновити розклад\n"
    "/settings — налаштування\n"
    "/logout — вийти з акаунту\n"
    "/help — список команд"
)


# ── Schedule helpers ────────────────────────────────────────────

def _lessons_from_cache(chat_id: int) -> list[Lesson]:
    rows = get_cached_lessons(chat_id)
    lessons = []
    for r in rows:
        tags = [t for t in r["tags"].split(",") if t] if r["tags"] else []
        lessons.append(Lesson(
            day=r["day"], time_start=r["time_start"], time_end=r["time_end"],
            name=r["name"], lesson_type=r["lesson_type"], teacher=r["teacher"],
            room=r["room"], groups=r["groups_info"], tags=tags, week=r["week"],
        ))
    return lessons


def _refresh_schedule(user: User) -> tuple[list[Lesson], int]:
    """Fetch schedule from NAU and update cache. Returns (lessons, active_week)."""
    lessons, active_week = fetch_schedule(user.nau_username, user.nau_password)
    cache_lessons(user.chat_id, lessons, active_week)
    return lessons, active_week


def _get_user_lessons(user: User) -> list[Lesson]:
    """Get lessons — from cache if fresh, otherwise re-fetch."""
    cached = get_cached_lessons(user.chat_id)
    if cached:
        cached_at = cached[0].get("cached_at", "")
        if cached_at:
            try:
                cache_time = datetime.fromisoformat(cached_at)
                if datetime.utcnow() - cache_time < CACHE_TTL:
                    return _lessons_from_cache(user.chat_id)
            except (ValueError, TypeError):
                pass
    lessons, active_week = _refresh_schedule(user)
    return lessons


def _get_current_week(user: User) -> int:
    """Get the current semester week for a user.
    Uses active_week stored in DB (updated every time schedule is fetched).
    Also adjusts if days have passed since last fetch."""
    return user.active_week


def _lessons_for_day(lessons: list[Lesson], day_name: str, week: int) -> list[Lesson]:
    return sorted(
        [l for l in lessons if l.day == day_name and l.week == week],
        key=lambda l: l.time_start,
    )


def _format_day_simple(day_name: str, lessons: list[Lesson], week: int) -> str:
    if not lessons:
        return f"📅 *{day_name}*\n\n_Пар немає! 🎉_"

    lines = [f"📅 *{day_name}*  ({week} тиждень)\n"]
    for i, l in enumerate(lessons, 1):
        tags = f"  _{', '.join(l.tags)}_" if l.tags else ""
        lines.append(
            f"*{i}. {l.name}* ({l.lesson_type}){tags}\n"
            f"    ⏰ {l.time_start} — {l.time_end}\n"
            f"    👨‍🏫 {l.teacher}\n"
            f"    🏫 Ауд. {l.room}"
        )
    return "\n\n".join(lines)


# ── Helper: require registered user ────────────────────────────

async def _require_user(update: Update) -> User | None:
    user = get_user(update.effective_chat.id)
    if not user:
        await update.message.reply_text(
            "⚠️ Ти ще не зареєстрований!\nНатисни /start щоб налаштувати бота.",
        )
        return None
    return user


# ── Delete helpers ──────────────────────────────────────────────

async def _try_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id,
        )
    except Exception:
        pass


async def _delete_messages(update: Update, context: ContextTypes.DEFAULT_TYPE, msg_ids: list[int]):
    chat_id = update.effective_chat.id
    for mid in msg_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
#  REGISTRATION CONVERSATION
# ═══════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    user = get_user(chat_id)

    if user:
        await update.message.reply_text(
            f"👋 З поверненням!\n\n"
            f"Ти вже зареєстрований як *{user.nau_username}*\n\n"
            f"{HELP_TEXT}",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 Привіт! Я бот розкладу *НАУ*.\n\n"
        "Я можу надсилати тобі розклад і нагадувати про пари.\n\n"
        "Для початку мені потрібні твої дані від cabinet.nau.edu.ua\n\n"
        "🔒 _Повідомлення з паролем буде видалено одразу після прочитання._\n\n"
        "Введи свій *логін* (username):",
        parse_mode="Markdown",
    )
    return ASK_USERNAME


async def ask_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["nau_username"] = update.message.text.strip()
    await update.message.reply_text(
        "✅ Тепер введи *пароль*:\n\n_Повідомлення буде видалено одразу_",
        parse_mode="Markdown",
    )
    return ASK_PASSWORD


async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    password = update.message.text.strip()
    context.user_data["nau_password"] = password

    await _try_delete(update, context)

    username = context.user_data["nau_username"]
    status_msg = await update.effective_chat.send_message("🔄 Перевіряю дані...")

    try:
        lessons, active_week = fetch_schedule(username, password)
    except RuntimeError as e:
        if "LOGIN_FAILED" in str(e):
            await status_msg.edit_text(
                "❌ Невірний логін або пароль. Спробуй ще раз.\n\nВведи свій *логін*:",
                parse_mode="Markdown",
            )
            return ASK_USERNAME
        else:
            await status_msg.edit_text(
                f"❌ Помилка з'єднання з cabinet.nau.edu.ua:\n`{e}`\n\nСпробуй пізніше: /start",
                parse_mode="Markdown",
            )
            return ConversationHandler.END
    except Exception as e:
        await status_msg.edit_text(
            f"❌ Щось пішло не так:\n`{e}`\n\nСпробуй пізніше: /start",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    user = User(
        chat_id=chat_id,
        nau_username=username,
        nau_password=password,
        reminder_minutes=10,
        is_active=True,
        active_week=active_week,
    )
    save_user(user)
    cache_lessons(chat_id, lessons, active_week)

    await status_msg.edit_text(
        f"✅ *Успішно!* Знайдено {len(lessons)} пар у розкладі.\n\n"
        f"{HELP_TEXT}\n\n"
        f"🔔 Нагадування: за *{user.reminder_minutes} хв* до пари",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Скасовано. Натисни /start щоб почати знову.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════
#  SCHEDULE COMMANDS
# ═══════════════════════════════════════════════════════════════

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _require_user(update)
    if not user:
        return

    now = datetime.now(KYIV_TZ)
    day_name = DAY_MAP[now.weekday()]
    week = _get_current_week(user)

    try:
        lessons = _get_user_lessons(user)
        # Refresh user in case active_week was updated
        user = get_user(user.chat_id)
        week = user.active_week
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка оновлення: {e}")
        return

    day_lessons = _lessons_for_day(lessons, day_name, week)
    text = _format_day_simple(day_name, day_lessons, week)
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _require_user(update)
    if not user:
        return

    tomorrow = datetime.now(KYIV_TZ) + timedelta(days=1)
    day_name = DAY_MAP[tomorrow.weekday()]

    try:
        lessons = _get_user_lessons(user)
        user = get_user(user.chat_id)
        week = user.active_week
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка оновлення: {e}")
        return

    # If tomorrow is Monday, it's the next week
    if tomorrow.weekday() == 0:
        week = week + 1

    day_lessons = _lessons_for_day(lessons, day_name, week)
    text = _format_day_simple(day_name, day_lessons, week)
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _require_user(update)
    if not user:
        return

    try:
        all_lessons = _get_user_lessons(user)
        user = get_user(user.chat_id)
        week = user.active_week
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка оновлення: {e}")
        return

    week_lessons = [l for l in all_lessons if l.week == week]

    if not week_lessons:
        await update.message.reply_text(f"{week} тиждень: пар не знайдено 🤷")
        return

    lines = [f"📋 *Розклад — {week} тиждень*\n"]
    for day_name in DAYS_NORMALIZED[:6]:
        day_l = _lessons_for_day(week_lessons, day_name, week)
        if day_l:
            lines.append(f"\n*── {day_name} ──*")
            for l in day_l:
                tags = f"  _{', '.join(l.tags)}_" if l.tags else ""
                lines.append(
                    f"\n  ⏰ {l.time_start}–{l.time_end}\n"
                    f"  *{l.name}* ({l.lesson_type}){tags}\n"
                    f"  👨‍🏫 {l.teacher} | 🏫 {l.room}"
                )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_nextweek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _require_user(update)
    if not user:
        return

    try:
        all_lessons = _get_user_lessons(user)
        user = get_user(user.chat_id)
        week = user.active_week + 1
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка оновлення: {e}")
        return

    week_lessons = [l for l in all_lessons if l.week == week]

    if not week_lessons:
        await update.message.reply_text(f"{week} тиждень: пар не знайдено 🤷")
        return

    lines = [f"📋 *Розклад — {week} тиждень* (наступний)\n"]
    for day_name in DAYS_NORMALIZED[:6]:
        day_l = _lessons_for_day(week_lessons, day_name, week)
        if day_l:
            lines.append(f"\n*── {day_name} ──*")
            for l in day_l:
                tags = f"  _{', '.join(l.tags)}_" if l.tags else ""
                lines.append(
                    f"\n  ⏰ {l.time_start}–{l.time_end}\n"
                    f"  *{l.name}* ({l.lesson_type}){tags}\n"
                    f"  👨‍🏫 {l.teacher} | 🏫 {l.room}"
                )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _require_user(update)
    if not user:
        return

    now = datetime.now(KYIV_TZ)
    day_name = DAY_MAP[now.weekday()]
    current_time = now.strftime("%H:%M")

    try:
        lessons = _get_user_lessons(user)
        user = get_user(user.chat_id)
        week = user.active_week
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка оновлення: {e}")
        return

    day_lessons = _lessons_for_day(lessons, day_name, week)
    upcoming = [l for l in day_lessons if l.time_start > current_time]

    if upcoming:
        l = upcoming[0]
        tags = f"\n_{', '.join(l.tags)}_" if l.tags else ""
        text = (
            f"⏭ *Наступна пара:*{tags}\n\n"
            f"📚 *{l.name}* ({l.lesson_type})\n"
            f"⏰ {l.time_start} — {l.time_end}\n"
            f"👨‍🏫 {l.teacher}\n"
            f"🏫 Ауд. {l.room}"
        )
    else:
        text = "✅ На сьогодні пар більше немає!"

    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _require_user(update)
    if not user:
        return

    status = await update.message.reply_text("🔄 Оновлюю розклад...")
    try:
        lessons, active_week = _refresh_schedule(user)
        await status.edit_text(
            f"✅ Розклад оновлено! Знайдено {len(lessons)} пар. Поточний тиждень: {active_week}."
        )
    except RuntimeError as e:
        if "LOGIN_FAILED" in str(e):
            await status.edit_text(
                "❌ Не вдалося увійти. Можливо, пароль змінився.\n"
                "Використай /logout і /start щоб оновити дані."
            )
        else:
            await status.edit_text(f"❌ Помилка: {e}")


# ═══════════════════════════════════════════════════════════════
#  SETTINGS
# ═══════════════════════════════════════════════════════════════

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _require_user(update)
    if not user:
        return

    keyboard = ReplyKeyboardMarkup(
        [["5 хв", "10 хв", "15 хв", "30 хв"], ["❌ Вимкнути нагадування", "↩️ Назад"]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )
    msg = await update.message.reply_text(
        f"⚙️ *Налаштування*\n\n"
        f"Акаунт: *{user.nau_username}*\n"
        f"Нагадування: *{user.reminder_minutes} хв* до пари\n\n"
        f"Обери час нагадування:",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    context.user_data["settings_msg_ids"] = [update.message.message_id, msg.message_id]
    return ASK_NEW_REMINDER


async def set_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.effective_chat.id

    msg_ids = context.user_data.get("settings_msg_ids", [])
    msg_ids.append(update.message.message_id)

    if "Назад" in text:
        await _delete_messages(update, context, msg_ids)
        await update.message.reply_text(
            HELP_TEXT, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    if "Вимкнути" in text:
        update_reminder_minutes(chat_id, 0)
        result_text = "🔕 Нагадування вимкнено."
    else:
        try:
            minutes = int(text.split()[0])
            update_reminder_minutes(chat_id, minutes)
            result_text = f"✅ Нагадування: за *{minutes} хв* до пари."
        except (ValueError, IndexError):
            await _delete_messages(update, context, msg_ids)
            await update.message.reply_text(
                "Не зрозумів. Спробуй ще: /settings",
                reply_markup=ReplyKeyboardRemove(),
            )
            return ConversationHandler.END

    await _delete_messages(update, context, msg_ids)
    await update.effective_chat.send_message(
        f"{result_text}\n\n{HELP_TEXT}",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("Ти і так не зареєстрований 🤷")
        return

    delete_user(chat_id)
    await update.message.reply_text(
        "✅ Дані видалено. Натисни /start щоб зареєструватися знову."
    )


# ═══════════════════════════════════════════════════════════════
#  BACKGROUND JOBS
# ═══════════════════════════════════════════════════════════════

async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(KYIV_TZ)
    day_name = DAY_MAP[now.weekday()]

    users = get_all_active_users()
    for user in users:
        if user.reminder_minutes <= 0:
            continue

        try:
            lessons = _lessons_from_cache(user.chat_id)
        except Exception:
            continue

        week = user.active_week
        day_lessons = _lessons_for_day(lessons, day_name, week)
        for l in day_lessons:
            h, m = map(int, l.time_start.split(":"))
            lesson_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            diff = (lesson_dt - now).total_seconds() / 60

            if user.reminder_minutes - 1 <= diff <= user.reminder_minutes:
                tags = f"\n_{', '.join(l.tags)}_" if l.tags else ""
                text = (
                    f"🔔 *Пара через {user.reminder_minutes} хв!*{tags}\n\n"
                    f"📚 *{l.name}* ({l.lesson_type})\n"
                    f"⏰ {l.time_start} — {l.time_end}\n"
                    f"👨‍🏫 {l.teacher}\n"
                    f"🏫 Ауд. {l.room}"
                )
                try:
                    await context.bot.send_message(
                        chat_id=user.chat_id, text=text, parse_mode="Markdown",
                    )
                    logger.info(f"Reminder → {user.chat_id}: {l.name} at {l.time_start}")
                except Exception as e:
                    logger.error(f"Failed to send reminder to {user.chat_id}: {e}")


async def cache_refresh_job(context: ContextTypes.DEFAULT_TYPE):
    users = get_all_active_users()
    for user in users:
        try:
            _refresh_schedule(user)
            logger.info(f"Cache refreshed for {user.chat_id}")
        except Exception as e:
            logger.error(f"Cache refresh failed for {user.chat_id}: {e}")


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("today", "Розклад на сьогодні"),
        BotCommand("tomorrow", "Розклад на завтра"),
        BotCommand("week", "Весь тиждень"),
        BotCommand("nextweek", "Наступний тиждень"),
        BotCommand("next", "Наступна пара"),
        BotCommand("refresh", "Оновити розклад"),
        BotCommand("settings", "Налаштування"),
        BotCommand("logout", "Вийти з акаунту"),
        BotCommand("help", "Список команд"),
    ])


def main():
    if not BOT_TOKEN:
        print("ERROR: Set BOT_TOKEN environment variable!")
        print("  export BOT_TOKEN='your_token_here'")
        return

    init_db()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    async def reg_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Реєстрацію скасовано. Натисни /start щоб почати знову.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            ASK_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_username)],
            ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_password)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.COMMAND, reg_fallback),
        ],
        allow_reentry=True,
    )

    async def settings_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "⚙️ Налаштування скасовано.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    settings_conv = ConversationHandler(
        entry_points=[CommandHandler("settings", cmd_settings)],
        states={
            ASK_NEW_REMINDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_reminder)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.COMMAND, settings_fallback),
        ],
        allow_reentry=True,
    )

    app.add_handler(reg_conv)
    app.add_handler(settings_conv)
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("tomorrow", cmd_tomorrow))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("nextweek", cmd_nextweek))
    app.add_handler(CommandHandler("next", cmd_next))
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CommandHandler("logout", cmd_logout))

    jq = app.job_queue
    jq.run_repeating(reminder_job, interval=60, first=10, name="reminders")
    jq.run_repeating(cache_refresh_job, interval=6 * 3600, first=3600, name="cache_refresh")

    logger.info("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()