import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from config import XUI_SUB_URL, PLANS
from database import get_user, create_user, get_payment_history
from keyboards import profile_menu
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


def _sub_end_str(sub_end: str | None) -> str:
    if not sub_end:
        return "—"
    try:
        end = datetime.fromisoformat(sub_end)
        return end.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return sub_end[:16] if sub_end else "—"


async def _build_profile_text(tg_id: int, first_name: str) -> tuple[str, str | None]:
    user = await get_user(tg_id)
    if not user:
        user = await create_user(tg_id, None, first_name)

    sub_end = user.get("subscription_end")
    sub_id = user.get("sub_id", "")
    sub_url = f"{XUI_SUB_URL}/{sub_id}" if sub_id else None
    status_emoji = _status_emoji(sub_end)
    days_left = _days_left(sub_end)
    sub_end_str = _sub_end_str(sub_end)
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

    is_active = False
    if sub_end:
        try:
            end = datetime.fromisoformat(sub_end)
            is_active = end > datetime.utcnow()
        except Exception:
            pass

    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: <code>{tg_id}</code>\n"
        f"👤 Имя: {first_name}\n"
        f"📅 Регистрация: {reg_str}\n\n"
        f"{status_emoji} <b>Статус подписки:</b> {days_left}\n"
        f"📆 Действует до: <b>{sub_end_str}</b>\n"
        f"🎁 Пробный период: {trial_status}"
        f"{traffic_lines}"
    )

    if sub_url and is_active:
        text += f"\n\n🔗 <b>Ссылка подписки:</b>\n<code>{sub_url}</code>"
        return text, sub_url
    else:
        text += "\n\n▶️ Нажми 🛒 <b>Купить VPN</b> для оформления подписки."
        return text, None


@router.message(F.text == "👤 Профиль")
@router.message(Command("profile"))
async def cmd_profile(message: Message):
    tg_id = message.from_user.id
    first_name = message.from_user.first_name or "Пользователь"
    text, sub_url = await _build_profile_text(tg_id, first_name)
    await message.answer(text, parse_mode="HTML", reply_markup=profile_menu(sub_url))


@router.callback_query(F.data == "profile:refresh")
async def profile_refresh(call: CallbackQuery):
    tg_id = call.from_user.id
    first_name = call.from_user.first_name or "Пользователь"
    text, sub_url = await _build_profile_text(tg_id, first_name)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=profile_menu(sub_url))
    except Exception:
        pass
    await call.answer("Обновлено!")


@router.callback_query(F.data == "profile:copy_link")
async def profile_copy_link(call: CallbackQuery):
    await call.answer("Ссылка показана выше — нажми на неё чтобы скопировать", show_alert=True)


@router.callback_query(F.data == "profile:payments")
async def profile_payments(call: CallbackQuery):
    tg_id = call.from_user.id
    payments = await get_payment_history(tg_id, limit=10)
    if not payments:
        await call.answer("У тебя пока нет платежей.", show_alert=True)
        return

    lines = []
    for p in payments:
        plan = PLANS.get(p["plan"], {})
        label = plan.get("label", p["plan"])
        paid_at = p.get("paid_at", "")[:10]
        if p.get("is_gift"):
            lines.append(f"🎁 {paid_at} — {label} (подарок)")
        else:
            stars = p.get("stars", "?")
            lines.append(f"💳 {paid_at} — {label} ({stars} ⭐)")

    text = "💳 <b>История платежей:</b>\n\n" + "\n".join(lines)
    await call.message.answer(text, parse_mode="HTML")
    await call.answer()
