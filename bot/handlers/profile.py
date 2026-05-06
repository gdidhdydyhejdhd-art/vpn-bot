import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

from config import XUI_SUB_URL
from database import get_user, create_user
from keyboards import sub_link_button
import xui_api

logger = logging.getLogger(__name__)
router = Router()


def _status_emoji(sub_end: str | None) -> str:
    if not sub_end:
        return "❌"
    try:
        end = datetime.fromisoformat(sub_end)
        if end > datetime.utcnow():
            return "✅"
    except Exception:
        pass
    return "❌"


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


@router.message(F.text == "👤 Профиль")
@router.message(Command("profile"))
async def cmd_profile(message: Message):
    tg_id = message.from_user.id

    user = await get_user(tg_id)
    if not user:
        user = await create_user(tg_id, message.from_user.username, message.from_user.first_name or "")

    sub_end = user.get("subscription_end")
    sub_id = user.get("sub_id", "")
    sub_url = f"{XUI_SUB_URL}/{sub_id}" if sub_id else None
    status_emoji = _status_emoji(sub_end)
    days_left = _days_left(sub_end)
    trial_status = "✅ использован" if user.get("trial_used") else "🎁 доступен"

    reg_date = user.get("registered_at", "")
    try:
        reg_dt = datetime.fromisoformat(reg_date)
        reg_str = reg_dt.strftime("%d.%m.%Y")
    except Exception:
        reg_str = reg_date[:10] if reg_date else "?"

    traffic_lines = ""
    try:
        traffics = await xui_api.get_all_clients_traffic(tg_id)
        if traffics:
            total_up = sum(t.get("up", 0) for t in traffics)
            total_down = sum(t.get("down", 0) for t in traffics)
            total_used = total_up + total_down
            traffic_lines = (
                f"\n\n📊 <b>Трафик (все серверы):</b>\n"
                f"  ⬆️ Отправлено: <b>{xui_api.fmt_bytes(total_up)}</b>\n"
                f"  ⬇️ Получено: <b>{xui_api.fmt_bytes(total_down)}</b>\n"
                f"  📦 Итого: <b>{xui_api.fmt_bytes(total_used)}</b>"
            )
    except Exception as e:
        logger.warning(f"Traffic fetch failed: {e}")

    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: <code>{tg_id}</code>\n"
        f"👤 Имя: {message.from_user.first_name}\n"
        f"📅 Регистрация: {reg_str}\n\n"
        f"{status_emoji} <b>Подписка:</b> {days_left}\n"
        f"🎁 Пробный: {trial_status}"
        f"{traffic_lines}"
    )

    is_active = False
    if sub_end:
        try:
            end = datetime.fromisoformat(sub_end)
            is_active = end > datetime.utcnow()
        except Exception:
            pass

    if sub_url and is_active:
        text += f"\n\n🔗 Ссылка подписки:\n<code>{sub_url}</code>"
        await message.answer(text, parse_mode="HTML", reply_markup=sub_link_button(sub_url))
    else:
        text += "\n\nНажми 🛒 <b>Купить VPN</b> для оформления подписки."
        await message.answer(text, parse_mode="HTML")
