import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

from config import TRIAL_DAYS, TRIAL_GB, XUI_SUB_URL
from database import get_user, create_user, update_subscription, mark_trial_used, can_use_trial
import xui_api

logger = logging.getLogger(__name__)
router = Router()


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

    await message.answer("⏳ Активирую пробный период...")

    sub_id = user["sub_id"]
    ok = await xui_api.add_client_to_all_inbounds(
        tg_id=tg_id,
        sub_id=sub_id,
        days=TRIAL_DAYS,
        is_trial=True,
    )

    if ok:
        await update_subscription(tg_id, TRIAL_DAYS)
        await mark_trial_used(tg_id)

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
            f"⚠️ <b>Пробный период можно использовать только один раз!</b>\n"
            f"После окончания купи подписку 🛒",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"⚠️ Ошибка при создании VPN-аккаунта.\n"
            f"Обратитесь в поддержку @rl_highest с ID: <code>{tg_id}</code>",
            parse_mode="HTML",
        )
