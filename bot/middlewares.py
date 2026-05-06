import logging
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_ID
from database import has_active_subscription

logger = logging.getLogger(__name__)

CHANNEL_USERNAME = "vpss_official"
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME}"

# True when bot lacks admin rights to check channel members
_channel_unavailable: bool = False
_admin_notified: bool = False


def _channel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📢 Подписаться на @{CHANNEL_USERNAME}", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")],
    ])


async def _notify_admin_no_rights(bot) -> None:
    global _admin_notified
    if _admin_notified:
        return
    _admin_notified = True
    try:
        await bot.send_message(
            ADMIN_ID,
            f"⚠️ <b>Бот не может проверять подписку на канал!</b>\n\n"
            f"Добавь <b>@Vpss_robot</b> как администратора канала <b>@{CHANNEL_USERNAME}</b>.\n\n"
            f"До этого момента кнопка «Я подписался» будет работать на доверии.",
            parse_mode="HTML",
        )
    except Exception:
        pass


async def _is_subscribed(bot, user_id: int) -> tuple[bool, bool]:
    """
    Returns (subscribed, can_check).
    can_check=False means bot lacks permission — we can't verify.
    """
    global _channel_unavailable
    try:
        member = await bot.get_chat_member(chat_id=f"@{CHANNEL_USERNAME}", user_id=user_id)
        _channel_unavailable = False
        return member.status in ("member", "administrator", "creator"), True
    except Exception as e:
        err = str(e).lower()
        if "inaccessible" in err or "not enough rights" in err or "administrator" in err:
            _channel_unavailable = True
            return False, False  # can't check
        # Other transient errors — treat as "can't check" to avoid blocking
        logger.warning(f"Channel check transient error for {user_id}: {e}")
        return False, False


class ChannelSubscriptionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        user = event.from_user
        if user is None:
            return await handler(event, data)

        tg_id = user.id
        bot = data["bot"]

        # Admin always passes
        if tg_id == ADMIN_ID:
            return await handler(event, data)

        # Active subscribers always pass
        if await has_active_subscription(tg_id):
            return await handler(event, data)

        # "Я подписался" button
        if isinstance(event, CallbackQuery) and event.data == "check_subscription":
            subscribed, can_check = await _is_subscribed(bot, tg_id)

            if not can_check:
                # Bot can't verify — notify admin once, then trust the user
                await _notify_admin_no_rights(bot)
                # Let the user through (trust-based fallback)
                subscribed = True

            if subscribed:
                await event.answer("✅ Отлично! Добро пожаловать!", show_alert=True)
                from keyboards import main_menu
                from database import get_user, create_user
                u = await get_user(tg_id)
                if not u:
                    await create_user(tg_id, user.username, user.first_name or "")
                await event.message.answer(
                    "👋 <b>Добро пожаловать!</b>\n\nВыбери действие:",
                    reply_markup=main_menu(tg_id),
                    parse_mode="HTML",
                )
            else:
                await event.answer(
                    f"❌ Подпишись на @{CHANNEL_USERNAME} и попробуй снова.",
                    show_alert=True,
                )
            return

        # Regular message/callback — check subscription
        subscribed, can_check = await _is_subscribed(bot, tg_id)

        if not can_check:
            # Bot can't verify — notify admin, let user through
            await _notify_admin_no_rights(bot)
            return await handler(event, data)

        if subscribed:
            return await handler(event, data)

        # Not subscribed — block with subscription prompt
        text = (
            f"📢 <b>Для использования бота подпишись на наш канал:</b>\n\n"
            f"👉 @{CHANNEL_USERNAME}\n\n"
            "После подписки нажми кнопку ниже 👇"
        )
        if isinstance(event, Message):
            await event.answer(text, reply_markup=_channel_keyboard(), parse_mode="HTML")
        elif isinstance(event, CallbackQuery):
            await event.answer(f"Сначала подпишись на @{CHANNEL_USERNAME}!", show_alert=True)
            try:
                await event.message.answer(text, reply_markup=_channel_keyboard(), parse_mode="HTML")
            except Exception:
                pass
