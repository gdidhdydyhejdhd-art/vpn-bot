import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.filters import Command

from config import TRIAL_DAYS, TRIAL_GB, XUI_SUB_URL
from database import get_user, create_user, update_subscription, mark_trial_used, unmark_trial_used, can_use_trial
import xui_api

logger = logging.getLogger(__name__)
router = Router()

XUI_TIMEOUT = 120


@router.message(F.text == "🎁 Пробный период")
@router.message(Command("trial"))
async def cmd_trial(message: Message):
    tg_id = message.from_user.id

    user = await get_user(tg_id)
    if not user:
        user = await create_user(tg_id, message.from_user.username, message.from_user.first_name or "")

    allowed, reason = can_use_trial(user)
    if not allowed:
        await message.answer(
            f"❌ <b>Пробный период недоступен.</b>\n\n"
            f"⏳ {reason}\n\n"
            "Купи подписку нажав 🛒 <b>Купить VPN</b>",
            parse_mode="HTML",
        )
        return

    # Persistent trial check: even if DB was reset, check x-ui for existing clients
    try:
        already_in_xui = await asyncio.wait_for(xui_api.user_exists_in_xui(tg_id), timeout=15)
        if already_in_xui:
            # User already has VPN account — deny trial and mark as used in DB
            await mark_trial_used(tg_id)
            await message.answer(
                "❌ <b>Пробный период недоступен.</b>\n\n"
                "Ты уже использовал пробный период ранее.\n\n"
                "Купи подписку нажав 🛒 <b>Купить VPN</b>",
                parse_mode="HTML",
            )
            return
    except asyncio.TimeoutError:
        logger.warning("x-ui existence check timed out for %s, proceeding anyway", tg_id)

    # Remove keyboard in separate message (avoid edit_text issues)
    await message.answer("⏳ Создаю VPN-аккаунт, подождите...", reply_markup=ReplyKeyboardRemove())

    reserved = await mark_trial_used(tg_id)
    if not reserved:
        await message.answer("❌ Пробный период уже был использован.")
        return

    try:
        await xui_api.login()

        sub_id = user["sub_id"]
        try:
            ok = await asyncio.wait_for(
                xui_api.add_client_to_all_inbounds(
                    tg_id=tg_id,
                    sub_id=sub_id,
                    days=TRIAL_DAYS,
                    is_trial=True,
                ),
                timeout=XUI_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error("Trial xui timeout for user %s", tg_id)
            await unmark_trial_used(tg_id)
            await message.answer(
                f"⚠️ Сервер VPN не ответил вовремя.\n"
                f"Попробуйте ещё раз или обратитесь в поддержку: @rl_highest\n"
                f"ID: <code>{tg_id}</code>",
                parse_mode="HTML",
            )
            return

        if ok:
            await update_subscription(tg_id, TRIAL_DAYS)
            sub_url = f"{XUI_SUB_URL}/{sub_id}"
            end_date = (datetime.utcnow() + timedelta(days=TRIAL_DAYS)).strftime("%d.%m.%Y")
            await message.answer(
                f"✅ <b>Пробный период активирован!</b>\n\n"
                f"📅 Срок: <b>{TRIAL_DAYS} дней</b> (до {end_date})\n"
                f"📊 Трафик: <b>{TRIAL_GB} ГБ на каждый сервер</b>\n\n"
                f"🔗 Ссылка для подключения:\n<code>{sub_url}</code>\n\n"
                f"💡 Импортируй ссылку в VLESS/VMESS клиент:\n"
                f"• <b>Android:</b> v2rayNG, Hiddify\n"
                f"• <b>iOS:</b> Streisand, Shadowrocket\n"
                f"• <b>Windows/Mac:</b> Hiddify, v2rayN\n\n"
                f"⚠️ <b>Пробный период можно использовать только один раз!</b>",
                parse_mode="HTML",
            )
        else:
            await unmark_trial_used(tg_id)
            await message.answer(
                f"⚠️ Ошибка при создании VPN-аккаунта.\n"
                f"Обратитесь в поддержку с ID: <code>{tg_id}</code>",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.exception("Trial provisioning failed for %s: %s", tg_id, e)
        await unmark_trial_used(tg_id)
        await message.answer("⚠️ Внутренняя ошибка при выдаче пробного периода. Попробуйте позже.")
