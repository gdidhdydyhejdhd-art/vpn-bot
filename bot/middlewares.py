import logging
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_ID, ACCESS_PIN
from database import (
    get_user, create_user, has_active_subscription,
    set_channel_verified, set_pin_verified,
)

logger = logging.getLogger(__name__)

CHANNEL_USERNAME = "vpss_official"
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME}"

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
    global _channel_unavailable
    try:
        member = await bot.get_chat_member(chat_id=f"@{CHANNEL_USERNAME}", user_id=user_id)
        _channel_unavailable = False
        return member.status in ("member", "administrator", "creator", "restricted"), True
    except Exception as e:
        err = str(e).lower()
        if "inaccessible" in err or "not enough rights" in err or "administrator" in err:
            _channel_unavailable = True
            return False, False
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

        # Admin always passes everything
        if tg_id == ADMIN_ID:
            return await handler(event, data)

        # Ensure user exists in DB
        user_db = await get_user(tg_id)
        if not user_db:
            user_db = await create_user(tg_id, user.username, user.first_name or "")

        # ── PIN check ────────────────────────────────────────────────────────
        if ACCESS_PIN and not user_db.get("pin_verified"):
            if isinstance(event, Message) and event.text and event.text.strip() == ACCESS_PIN:
                await set_pin_verified(tg_id)
                from keyboards import main_menu
                await event.answer(
                    "✅ <b>PIN принят! Добро пожаловать!</b>\n\nВыбери действие:",
                    reply_markup=main_menu(tg_id),
                    parse_mode="HTML",
                )
                return
            # Show PIN prompt
            if isinstance(event, Message):
                await event.answer("🔐 Для доступа к боту введите цифровой PIN-код:")
            elif isinstance(event, CallbackQuery):
                await event.answer("🔐 Сначала введите PIN-код в чате с ботом", show_alert=True)
            return

        # ── Channel subscription check ───────────────────────────────────────
        # Skip if user already verified channel membership OR has active subscription
        if user_db.get("channel_verified") or await has_active_subscription(tg_id):
            return await handler(event, data)

        # Handle "✅ Я подписался" button
        if isinstance(event, CallbackQuery) and event.data == "check_subscription":
            try:
                subscribed, can_check = await _is_subscribed(bot, tg_id)

                if not can_check:
                    await _notify_admin_no_rights(bot)
                    subscribed = True  # Trust-based fallback

                if subscribed:
                    # Answer the callback FIRST so Telegram removes the loading indicator
                    await event.answer("✅ Отлично! Добро пожаловать!", show_alert=True)
                    await set_channel_verified(tg_id)
                    from keyboards import main_menu
                    name = user.first_name or "друг"
                    await event.message.answer(
                        f"👋 <b>Добро пожаловать, {name}!</b>\n\nВыбери действие:",
                        reply_markup=main_menu(tg_id),
                        parse_mode="HTML",
                    )
                else:
                    await event.answer(
                        f"❌ Подпишись на @{CHANNEL_USERNAME} и попробуй снова.",
                        show_alert=True,
                    )
            except Exception as e:
                logger.error(f"check_subscription error for {tg_id}: {e}")
                try:
                    await event.answer("⚠️ Ошибка. Попробуй ещё раз.", show_alert=True)
                except Exception:
                    pass
            return

        # Regular message — check subscription to channel
        subscribed, can_check = await _is_subscribed(bot, tg_id)

        if not can_check:
            await _notify_admin_no_rights(bot)
            await set_channel_verified(tg_id)  # Trust-based: mark verified
            return await handler(event, data)

        if subscribed:
            await set_channel_verified(tg_id)
            return await handler(event, data)

        # Not subscribed — block
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
