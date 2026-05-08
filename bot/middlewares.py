import logging
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove

from config import ADMIN_ID, ACCESS_PIN
from database import (
    get_user, create_user, has_active_subscription,
    set_channel_verified, reset_channel_verified_user,
    set_pin_verified, set_user_locked,
)

logger = logging.getLogger(__name__)

CHANNEL_USERNAME = "vpss_official"
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME}"

_admin_notified: bool = False


def _channel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📢 Подписаться на @{CHANNEL_USERNAME}", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")],
    ])


def _channel_text() -> str:
    return (
        f"📢 <b>Для использования бота подпишись на наш канал:</b>\n\n"
        f"👉 @{CHANNEL_USERNAME}\n\n"
        f"После подписки нажми кнопку ниже 👇\n\n"
        f"💡 <i>Если меню не появилось после нажатия — напишите /start</i>"
    )


async def _notify_admin_no_rights(bot) -> None:
    global _admin_notified
    if _admin_notified:
        return
    _admin_notified = True
    try:
        await bot.send_message(
            ADMIN_ID,
            f"⚠️ <b>Бот не может проверять подписку на канал!</b>\n\n"
            f"Добавь бота как администратора канала @{CHANNEL_USERNAME}.\n\n"
            f"Пока бот не администратор — подписка не проверяется вживую, "
            f"пользователи верифицируются только нажатием «Я подписался».",
            parse_mode="HTML",
        )
    except Exception:
        pass


async def _check_channel_membership(bot, user_id: int) -> tuple[bool, bool]:
    """
    Returns (is_subscribed, can_check).
    can_check=False means bot has no admin rights to verify.
    Always makes a live API call — no caching.
    """
    try:
        member = await bot.get_chat_member(
            chat_id=f"@{CHANNEL_USERNAME}", user_id=user_id
        )
        status = member.status
        # "left" and "kicked" mean not subscribed
        subscribed = status in ("member", "administrator", "creator", "restricted")
        return subscribed, True
    except Exception as e:
        err = str(e).lower()
        if any(k in err for k in ("not enough rights", "administrator", "inaccessible", "chat not found", "forbidden")):
            return False, False
        # Transient error — treat as can't check
        logger.warning(f"Channel check error for {user_id}: {e}")
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

        # ── Admin always passes ──────────────────────────────────────────────
        if tg_id == ADMIN_ID:
            return await handler(event, data)

        # ── Ensure user exists in DB ─────────────────────────────────────────
        user_db = await get_user(tg_id)
        if not user_db:
            user_db = await create_user(tg_id, user.username, user.first_name or "")

        # ── Global ACCESS_PIN check ──────────────────────────────────────────
        if ACCESS_PIN and not user_db.get("pin_verified"):
            if isinstance(event, Message) and event.text and event.text.strip() == ACCESS_PIN:
                await set_pin_verified(tg_id)
                from keyboards import main_menu
                has_pin = bool(user_db.get("user_pin"))
                await event.answer(
                    "✅ <b>PIN принят! Добро пожаловать!</b>\n\nВыбери действие:",
                    reply_markup=main_menu(tg_id, has_pin=has_pin),
                    parse_mode="HTML",
                )
                return
            if isinstance(event, Message):
                await event.answer("🔐 Для доступа к боту введите цифровой PIN-код:")
            elif isinstance(event, CallbackQuery):
                await event.answer("🔐 Сначала введите PIN-код в чате с ботом", show_alert=True)
            return

        # ── Per-user lock check ──────────────────────────────────────────────
        if user_db.get("is_locked") and user_db.get("user_pin"):
            if isinstance(event, CallbackQuery):
                if event.data.startswith("pin:") or event.data.startswith("pin_del:"):
                    return await handler(event, data)
                await event.answer("🔒 Введи PIN-код на экране", show_alert=True)
                return
            if isinstance(event, Message):
                from keyboards import pin_keyboard
                pin_len = len(user_db["user_pin"])
                await event.answer("🔒", reply_markup=ReplyKeyboardRemove())
                await event.answer(
                    f"🔒 <b>Бот заблокирован</b>\n\n{'○' * pin_len}",
                    parse_mode="HTML",
                    reply_markup=pin_keyboard("", pin_len),
                )
                return
            return

        # ── Paying users always pass (no channel check needed) ───────────────
        if await has_active_subscription(tg_id):
            return await handler(event, data)

        # ── Handle "✅ Я подписался" button ──────────────────────────────────
        if isinstance(event, CallbackQuery) and event.data == "check_subscription":
            subscribed, can_check = await _check_channel_membership(bot, tg_id)

            if not can_check:
                # Bot has no rights — trust the button click, notify admin once
                await _notify_admin_no_rights(bot)
                subscribed = True

            if subscribed:
                await set_channel_verified(tg_id)
                await event.answer("✅ Отлично! Добро пожаловать!", show_alert=True)
                from keyboards import main_menu
                has_pin = bool(user_db.get("user_pin"))
                name = user.first_name or "друг"
                await event.message.answer(
                    f"👋 <b>Добро пожаловать, {name}!</b>\n\n"
                    f"Выбери действие:\n\n"
                    f"<i>Если кнопки не отобразились — напишите /start</i>",
                    reply_markup=main_menu(tg_id, has_pin=has_pin),
                    parse_mode="HTML",
                )
            else:
                await event.answer(
                    f"❌ Ты ещё не подписан на @{CHANNEL_USERNAME}.\n"
                    f"Подпишись и нажми кнопку снова!",
                    show_alert=True,
                )
            return

        # ── Live channel membership check for every message ──────────────────
        subscribed, can_check = await _check_channel_membership(bot, tg_id)

        if not can_check:
            # Bot can't verify — notify admin and fall back to cached flag
            await _notify_admin_no_rights(bot)
            if user_db.get("channel_verified"):
                # Previously verified via button — allow through
                return await handler(event, data)
            # Never verified — show subscription prompt
            if isinstance(event, Message):
                await event.answer(_channel_text(), reply_markup=_channel_keyboard(), parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                await event.answer(f"Сначала подпишись на @{CHANNEL_USERNAME}!", show_alert=True)
                try:
                    await event.message.answer(
                        _channel_text(), reply_markup=_channel_keyboard(), parse_mode="HTML"
                    )
                except Exception:
                    pass
            return

        if subscribed:
            # User IS subscribed — update cache and allow
            if not user_db.get("channel_verified"):
                await set_channel_verified(tg_id)
            return await handler(event, data)
        else:
            # User is NOT subscribed (or was subscribed but unsubscribed)
            if user_db.get("channel_verified"):
                # Had cached verification — clear it since they unsubscribed
                await reset_channel_verified_user(tg_id)
            # Block and show subscription prompt
            if isinstance(event, Message):
                await event.answer(_channel_text(), reply_markup=_channel_keyboard(), parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    f"❌ Ты отписался от @{CHANNEL_USERNAME}! Подпишись снова.",
                    show_alert=True,
                )
                try:
                    await event.message.answer(
                        _channel_text(), reply_markup=_channel_keyboard(), parse_mode="HTML"
                    )
                except Exception:
                    pass
            return
