import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart

from database import get_user, create_user
from keyboards import main_menu

logger = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    tg_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name or "Пользователь"

    user = await get_user(tg_id)
    if not user:
        await create_user(tg_id, username, first_name)
        welcome = (
            f"👋 Привет, <b>{first_name}</b>!\n\n"
            "Добро пожаловать в <b>VPN сервис</b>.\n\n"
            "🔒 Безопасность и анонимность — наш приоритет.\n"
            "⚡ Высокая скорость, несколько серверов.\n\n"
            "Выбери действие ниже:"
        )
    else:
        welcome = (
            f"👋 С возвращением, <b>{first_name}</b>!\n\n"
            "Выбери действие:"
        )

    await message.answer(welcome, reply_markup=main_menu(tg_id), parse_mode="HTML")


@router.message(F.text == "📞 Поддержка")
async def support(message: Message):
    await message.answer(
        "📞 <b>Поддержка</b>\n\n"
        "По всем вопросам обращайтесь: @rl_highest",
        parse_mode="HTML",
    )
