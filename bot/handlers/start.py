import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart

from database import get_user, create_user, get_public_stats
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
            "⚡ Высокая скорость, несколько серверов.\n"
            "🌍 Работает везде — обходит любые блокировки.\n\n"
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
        "По всем вопросам обращайтесь: @rl_highest\n\n"
        "⏱ Время ответа: обычно до 24 часов.",
        parse_mode="HTML",
    )


@router.message(F.text == "📊 Статистика")
async def cmd_stats(message: Message):
    stats = await get_public_stats()
    await message.answer(
        "📊 <b>Статистика сервиса</b>\n\n"
        f"👥 Пользователей: <b>{stats['total']}</b>\n"
        f"✅ Активных подписок: <b>{stats['active']}</b>\n"
        f"⭐ Stars заработано: <b>{stats['total_stars']}</b>\n\n"
        "🌐 Серверов: <b>7</b>\n"
        "🔒 Протоколы: VLESS, Shadowsocks, Hysteria2",
        parse_mode="HTML",
    )


@router.message(F.text == "📱 Инструкция")
async def cmd_instruction(message: Message):
    await message.answer(
        "📱 <b>Как подключиться к VPN</b>\n\n"
        "1️⃣ Получи ссылку подписки в разделе 👤 <b>Профиль</b>\n\n"
        "2️⃣ Скачай приложение для своего устройства:\n\n"
        "🤖 <b>Android:</b>\n"
        "• <a href='https://play.google.com/store/apps/details?id=com.v2ray.ang'>v2rayNG</a>\n"
        "• <a href='https://play.google.com/store/apps/details?id=app.hiddify.com'>Hiddify</a>\n"
        "• <a href='https://play.google.com/store/apps/details?id=com.incy.vpn'>INCY VPN</a>\n"
        "• <a href='https://play.google.com/store/apps/details?id=com.happvpn.app'>Happ</a>\n\n"
        "🍎 <b>iOS / iPhone:</b>\n"
        "• <a href='https://apps.apple.com/app/streisand/id6450534064'>Streisand</a>\n"
        "• <a href='https://apps.apple.com/app/shadowrocket/id932747118'>Shadowrocket</a> (платное)\n"
        "• <a href='https://apps.apple.com/app/v2raytun/id6476628951'>V2RayTun</a>\n"
        "• <a href='https://apps.apple.com/app/happ-proxy-utility/id6504287215'>Happ</a>\n"
        "• <a href='https://apps.apple.com/app/foxray/id6448898396'>FoXray</a>\n\n"
        "🖥 <b>Windows:</b>\n"
        "• <a href='https://github.com/hiddify/hiddify-app/releases/latest'>Hiddify</a>\n"
        "• <a href='https://github.com/2dust/v2rayN/releases/latest'>v2rayN</a>\n"
        "• <a href='https://github.com/nekoray/nekoray/releases/latest'>NekoRay</a>\n\n"
        "🍏 <b>macOS:</b>\n"
        "• <a href='https://github.com/hiddify/hiddify-app/releases/latest'>Hiddify</a>\n"
        "• <a href='https://github.com/yanue/V2rayU/releases/latest'>V2rayU</a>\n\n"
        "🐧 <b>Linux:</b>\n"
        "• <a href='https://github.com/hiddify/hiddify-app/releases/latest'>Hiddify</a>\n\n"
        "3️⃣ Нажми <b>«Импортировать из буфера обмена»</b> или\n"
        "   <b>«Add from URL»</b> и вставь свою ссылку.\n\n"
        "4️⃣ Нажми подключиться — готово! ✅\n\n"
        "❓ Вопросы — @rl_highest",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
