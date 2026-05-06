import asyncio
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from config import XUI_SUB_URL
from database import (
    get_user, create_user, freeze_subscription, unfreeze_subscription,
    cancel_subscription, update_subscription,
)
from keyboards import subscription_menu, cancel_confirm_menu, buy_menu
import xui_api

logger = logging.getLogger(__name__)
router = Router()


def _days_left(sub_end: str | None) -> str:
    if not sub_end:
        return "нет подписки"
    try:
        end = datetime.fromisoformat(sub_end)
        delta = end - datetime.utcnow()
        if delta.total_seconds() <= 0:
            return "истекла"
        days = delta.days
        hours = delta.seconds // 3600
        if days > 0:
            return f"{days} дн. {hours} ч."
        return f"{hours} ч."
    except Exception:
        return "?"


def _sub_end_str(sub_end: str | None) -> str:
    if not sub_end:
        return "—"
    try:
        end = datetime.fromisoformat(sub_end)
        return end.strftime("%d.%m.%Y")
    except Exception:
        return sub_end[:10] if sub_end else "—"


async def _build_sub_text(tg_id: int) -> tuple[str, bool, bool]:
    """Returns (text, is_frozen, has_sub)"""
    user = await get_user(tg_id)
    if not user:
        return "❌ Профиль не найден.", False, False

    sub_end = user.get("subscription_end")
    frozen_until = user.get("frozen_until")
    frozen_at = user.get("frozen_at")
    sub_id = user.get("sub_id", "")
    sub_url = f"{XUI_SUB_URL}/{sub_id}" if sub_id else None

    is_frozen = bool(frozen_until and not sub_end)

    if is_frozen:
        # Calculate days remaining at freeze time
        try:
            fu = datetime.fromisoformat(frozen_until)
            fa = datetime.fromisoformat(frozen_at)
            days_frozen = (datetime.utcnow() - fa).days
            remaining_at_freeze = max(0, (fu - fa).days)
            remaining_now = remaining_at_freeze  # will be extended on unfreeze
        except Exception:
            remaining_at_freeze = 0
            days_frozen = 0

        text = (
            "🧊 <b>Подписка заморожена</b>\n\n"
            f"📅 Заморозка с: <b>{_sub_end_str(frozen_at)}</b>\n"
            f"📆 Истекала бы: <b>{_sub_end_str(frozen_until)}</b>\n\n"
            f"⏸ Дней заморожено: <b>{days_frozen}</b>\n"
            f"💡 При разморозке подписка будет продлена на {days_frozen} дн.\n\n"
        )
        if sub_url:
            text += f"🔗 Ссылка подписки:\n<code>{sub_url}</code>"
        return text, True, False

    has_active = False
    if sub_end:
        try:
            end = datetime.fromisoformat(sub_end)
            has_active = end > datetime.utcnow()
        except Exception:
            pass

    if has_active:
        text = (
            "✅ <b>Управление подпиской</b>\n\n"
            f"📅 Активна до: <b>{_sub_end_str(sub_end)}</b>\n"
            f"⏳ Осталось: <b>{_days_left(sub_end)}</b>\n\n"
        )
        if sub_url:
            text += f"🔗 Ссылка подписки:\n<code>{sub_url}</code>\n\n"
        text += "Выбери действие:"
        return text, False, True
    else:
        text = (
            "💼 <b>Управление подпиской</b>\n\n"
            "❌ У тебя нет активной подписки.\n\n"
            "Нажми <b>Купить подписку</b> чтобы оформить:"
        )
        return text, False, False


@router.message(F.text == "💼 Подписка")
async def cmd_subscription(message: Message):
    tg_id = message.from_user.id
    text, is_frozen, has_sub = await _build_sub_text(tg_id)
    await message.answer(text, parse_mode="HTML", reply_markup=subscription_menu(is_frozen, has_sub))


@router.callback_query(F.data == "sub:back")
async def sub_back(call: CallbackQuery):
    tg_id = call.from_user.id
    text, is_frozen, has_sub = await _build_sub_text(tg_id)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=subscription_menu(is_frozen, has_sub))
    except Exception:
        await call.message.answer(text, parse_mode="HTML", reply_markup=subscription_menu(is_frozen, has_sub))
    await call.answer()


@router.callback_query(F.data == "sub:extend")
async def sub_extend(call: CallbackQuery):
    await call.message.answer(
        "🛒 <b>Выбери план подписки:</b>",
        parse_mode="HTML",
        reply_markup=buy_menu(),
    )
    await call.answer()


@router.callback_query(F.data == "sub:freeze")
async def sub_freeze(call: CallbackQuery):
    tg_id = call.from_user.id
    ok = await freeze_subscription(tg_id)
    if not ok:
        await call.answer("❌ Нет активной подписки для заморозки.", show_alert=True)
        return

    user = await get_user(tg_id)
    sub_id = user.get("sub_id", "")
    await xui_api.login()
    await asyncio.wait_for(
        xui_api.toggle_client_in_all_inbounds(tg_id, sub_id, enable=False),
        timeout=60,
    )

    text, is_frozen, has_sub = await _build_sub_text(tg_id)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=subscription_menu(is_frozen, has_sub))
    except Exception:
        await call.message.answer(text, parse_mode="HTML", reply_markup=subscription_menu(is_frozen, has_sub))
    await call.answer("🧊 Подписка заморожена!")


@router.callback_query(F.data == "sub:unfreeze")
async def sub_unfreeze(call: CallbackQuery):
    tg_id = call.from_user.id
    ok, new_end = await unfreeze_subscription(tg_id)
    if not ok:
        await call.answer("❌ Нет замороженной подписки.", show_alert=True)
        return

    user = await get_user(tg_id)
    sub_id = user.get("sub_id", "")
    sub_end = user.get("subscription_end")

    await xui_api.login()
    days_left = max(1, (new_end - datetime.utcnow()).days) if new_end else 1
    await asyncio.wait_for(
        xui_api.add_client_to_all_inbounds(tg_id=tg_id, sub_id=sub_id, days=days_left, is_trial=False),
        timeout=60,
    )

    text, is_frozen, has_sub = await _build_sub_text(tg_id)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=subscription_menu(is_frozen, has_sub))
    except Exception:
        await call.message.answer(text, parse_mode="HTML", reply_markup=subscription_menu(is_frozen, has_sub))
    await call.answer("🔓 Подписка разморожена!")


@router.callback_query(F.data == "sub:cancel_confirm")
async def sub_cancel_confirm(call: CallbackQuery):
    try:
        await call.message.edit_text(
            "⚠️ <b>Удалить подписку?</b>\n\n"
            "Это отключит VPN-доступ. Деньги не возвращаются.\n\n"
            "Ты уверен?",
            parse_mode="HTML",
            reply_markup=cancel_confirm_menu(),
        )
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data == "sub:cancel_do")
async def sub_cancel_do(call: CallbackQuery):
    tg_id = call.from_user.id
    user = await get_user(tg_id)
    sub_id = user.get("sub_id", "") if user else ""

    await cancel_subscription(tg_id)

    if sub_id:
        try:
            await xui_api.login()
            await asyncio.wait_for(
                xui_api.toggle_client_in_all_inbounds(tg_id, sub_id, enable=False),
                timeout=60,
            )
        except Exception as e:
            logger.warning(f"Failed to disable x-ui clients for {tg_id}: {e}")

    try:
        await call.message.edit_text(
            "✅ <b>Подписка удалена.</b>\n\n"
            "VPN-доступ отключён. Ты всегда можешь купить новую подписку 🛒",
            parse_mode="HTML",
            reply_markup=subscription_menu(False, False),
        )
    except Exception:
        await call.message.answer("✅ Подписка удалена.")
    await call.answer("Подписка удалена")
