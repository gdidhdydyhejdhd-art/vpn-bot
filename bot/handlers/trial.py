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

    # Убираем основную reply-клавиатуру, чтобы пользователь не мог нажимать параллельно
    proc_msg = await message.answer("⏳ Подготовка... (0%)", reply_markup=ReplyKeyboardRemove())

    # Атомарная резервация пробного в БД — вернёт True если удалось зарезервировать
    reserved = await mark_trial_used(tg_id)
    if not reserved:
        await proc_msg.edit_text("❌ Пробный период уже был использован или в данный момент занят другим запросом.")
        return

    try:
        # Прогресс 30%
        await proc_msg.edit_text("⏳ Резерв подтверждён (30%)\n\nИдёт создание аккаунта VPN...")

        sub_id = user["sub_id"]
        ok = await xui_api.add_client_to_all_inbounds(
            tg_id=tg_id,
            sub_id=sub_id,
            days=TRIAL_DAYS,
            is_trial=True,
        )

        # Прогресс 70%
        await proc_msg.edit_text("⏳ Применение настроек на сервере (70%)...")

        if ok:
            await update_subscription(tg_id, TRIAL_DAYS)
            # Прогресс 100% — финальное сообщение
            sub_url = f"{XUI_SUB_URL}/{sub_id}"
            end_date = (datetime.utcnow() + timedelta(days=TRIAL_DAYS)).strftime("%d.%m.%Y")
            await proc_msg.edit_text(
                f"✅ <b>Пробный период активирован!</b>\n\n"
                f"📅 Срок: <b>{TRIAL_DAYS} дней</b> (до {end_date})\n"
                f"📊 Трафик: <b>{TRIAL_GB} ГБ на каждый сервер</b>\n\n"
                f"🔗 Ссылка для подключения:\n<code>{sub_url}</code>\n\n"
                f"💡 Импортируй ссылку в VLESS/VMESS клиент:\n"
                f"• <b>Android:</b> v2rayNG, Hiddify\n"
                f"• <b>iOS:</b> Streisand, Shadowrocket\n"
                f"• <b>Windows/Mac:</b> Hiddify, v2rayN\n\n"
                f"⚠️ <b>Пробный период можно использовать только один раз!</b>\n",
                parse_mode="HTML",
            )
        else:
            # Внешний API упал — откатываем резервацию
            await unmark_trial_used(tg_id)
            await proc_msg.edit_text(
                f"⚠️ Ошибка при создании VPN-аккаунта.\n"
                f"Обратитесь в поддержку с ID: <code>{tg_id}</code>",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.exception("Trial provisioning failed for %s: %s", tg_id, e)
        # Откат при исключении
        await unmark_trial_used(tg_id)
        await proc_msg.edit_text("⚠️ Внутренняя ошибка при выдаче пробного периода. Попробуйте позже.")
