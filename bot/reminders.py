import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot

from config import XUI_SUB_URL
from database import get_users_expiring_soon, mark_reminder_sent
from keyboards import buy_menu

logger = logging.getLogger(__name__)


def _days_until(sub_end: str) -> int:
    try:
        end = datetime.fromisoformat(sub_end)
        delta = end - datetime.utcnow()
        return max(0, delta.days)
    except Exception:
        return 0


async def send_reminders(bot: Bot):
    """Check and send expiry reminders. Called every hour."""
    users = await get_users_expiring_soon()
    for user in users:
        tg_id = user["tg_id"]
        sub_end = user["subscription_end"]
        sub_id = user.get("sub_id", "")
        days_left = _days_until(sub_end)

        try:
            end_dt = datetime.fromisoformat(sub_end)
            end_str = end_dt.strftime("%d.%m.%Y")
        except Exception:
            end_str = sub_end[:10]

        if days_left <= 1:
            emoji = "🔴"
            text = (
                f"{emoji} <b>Подписка истекает завтра!</b>\n\n"
                f"📅 Срок действия: до {end_str}\n\n"
                "Продли прямо сейчас, чтобы не потерять доступ:"
            )
        elif days_left <= 3:
            emoji = "🟡"
            text = (
                f"{emoji} <b>Подписка истекает через {days_left} дня!</b>\n\n"
                f"📅 Срок действия: до {end_str}\n\n"
                "Не забудь продлить подписку:"
            )
        else:
            continue

        try:
            await bot.send_message(
                tg_id,
                text,
                reply_markup=buy_menu(),
                parse_mode="HTML",
            )
            await mark_reminder_sent(tg_id, sub_end)
            logger.info(f"Sent expiry reminder to {tg_id} ({days_left} days left)")
        except Exception as e:
            logger.warning(f"Failed to send reminder to {tg_id}: {e}")
            # Mark as sent anyway to avoid spam on blocked users
            await mark_reminder_sent(tg_id, sub_end)


async def reminder_loop(bot: Bot):
    """Background task: check reminders every hour."""
    logger.info("Reminder loop started")
    while True:
        try:
            await send_reminders(bot)
        except Exception as e:
            logger.error(f"Reminder loop error: {e}")
        await asyncio.sleep(3600)  # every hour
