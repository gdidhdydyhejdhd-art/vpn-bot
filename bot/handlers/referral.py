import logging
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from config import ADMIN_ID
from database import get_user, create_user, get_referral_stats

logger = logging.getLogger(__name__)
router = Router()

REFERRAL_BONUS_DAYS = 7


def _referral_link(tg_id: int) -> str:
    return f"https://t.me/Vpss_robot?start=ref_{tg_id}"


def _ref_keyboard(tg_id: int) -> InlineKeyboardMarkup:
    link = _referral_link(tg_id)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться с другом", switch_inline_query=f"Присоединяйся к VPN сервису по моей ссылке: {link}")],
        [InlineKeyboardButton(text="🔗 Моя реферальная ссылка", url=link)],
    ])


@router.message(F.text.in_({"👥 Рефералы", "👥 Реферальная программа"}))
@router.message(Command("ref"))
async def cmd_referral(message: Message):
    tg_id = message.from_user.id
    user = await get_user(tg_id)
    if not user:
        user = await create_user(tg_id, message.from_user.username, message.from_user.first_name or "")

    stats = await get_referral_stats(tg_id)
    link = _referral_link(tg_id)
    pending = stats["total"] - stats["rewarded"]

    text = (
        f"👥 <b>Реферальная программа</b>\n\n"
        f"Приглашай друзей и получай бонусы!\n\n"
        f"💡 <b>Как это работает:</b>\n"
        f"1. Поделись своей ссылкой с другом\n"
        f"2. Друг регистрируется и делает <b>первую оплату</b>\n"
        f"3. Тебе автоматически начисляется <b>+{REFERRAL_BONUS_DAYS} дней</b>\n\n"
        f"📊 <b>Твоя статистика:</b>\n"
        f"• Приглашено друзей: <b>{stats['total']}</b>\n"
        f"• Получено бонусов: <b>{stats['rewarded']}</b> (+{stats['rewarded'] * REFERRAL_BONUS_DAYS} дней)\n"
        f"• Ожидают оплаты: <b>{pending}</b>\n\n"
        f"🔗 <b>Твоя реферальная ссылка:</b>\n"
        f"<code>{link}</code>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=_ref_keyboard(tg_id))
