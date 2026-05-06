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


def _bar(pct: int) -> str:
    filled = int(10 * pct / 100)
    return "▓" * filled + "░" * (10 - filled)


async def _set_progress(msg, label: str, pct: int):
    try:
        await msg.edit_text(
            f"⏳ <b>{label}</b>\n\n{_bar(pct)} {pct}%",
            parse_mode="HTML",
        )
    except Exception:
        pass


async def _animate(msg, label: str, start: int, end: int, stop_event: asyncio.Event):
    pct = start
    while not stop_event.is_set() and pct < end:
        await _set_progress(msg, label, pct)
        await asyncio.sleep(0.7)
        pct = min(pct + 2, end)


async def _run_with_bar(msg, coro, label: str, start: int = 5, end: int = 90):
    stop = asyncio.Event()
    anim = asyncio.create_task(_animate(msg, label, start, end, stop))
    try:
        result = await coro
    finally:
        stop.set()
        anim.cancel()
        try:
            await anim
        except asyncio.CancelledError:
            pass
    return result


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

    proc_msg = await message.answer(
        f"⏳ <b>Подготовка...</b>\n\n{_bar(0)} 0%",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )

    reserved = await mark_trial_used(tg_id)
    if not reserved:
        await proc_msg.edit_text("❌ Пробный период уже был использован или в данный момент занят другим запросом.")
        return

    try:
        sub_id = user["sub_id"]

        ok = await _run_with_bar(
            proc_msg,
            xui_api.add_client_to_all_inbounds(
                tg_id=tg_id,
                sub_id=sub_id,
                days=TRIAL_DAYS,
                is_trial=True,
            ),
            label="Создание VPN-аккаунта",
            start=10,
            end=90,
        )

        await _set_progress(proc_msg, "Применение настроек...", 95)
        await asyncio.sleep(0.4)

        if ok:
            await update_subscription(tg_id, TRIAL_DAYS)
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
            await unmark_trial_used(tg_id)
            await proc_msg.edit_text(
                f"⚠️ Ошибка при создании VPN-аккаунта.\n"
                f"Обратитесь в поддержку с ID: <code>{tg_id}</code>",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.exception("Trial provisioning failed for %s: %s", tg_id, e)
        await unmark_trial_used(tg_id)
        await proc_msg.edit_text("⚠️ Внутренняя ошибка при выдаче пробного периода. Попробуйте позже.")
