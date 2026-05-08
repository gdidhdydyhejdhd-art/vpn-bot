import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import get_user, set_user_pin, remove_user_pin, set_user_locked
from keyboards import main_menu, settings_menu

logger = logging.getLogger(__name__)
router = Router()


class SettingsState(StatesGroup):
    waiting_for_pin = State()


@router.message(F.text == "⚙️ Настройки")
async def cmd_settings(message: Message):
    tg_id = message.from_user.id
    user = await get_user(tg_id)
    has_pin = bool(user and user.get("user_pin"))
    await message.answer(
        "⚙️ <b>Настройки</b>\n\n"
        "🔐 <b>PIN-блокировка</b> — защити бота персональным кодом.\n"
        "После установки PIN в меню появится кнопка 🔒 <b>Заблокировать</b>.\n"
        "При блокировке бот потребует ввести PIN для продолжения.",
        parse_mode="HTML",
        reply_markup=settings_menu(has_pin),
    )


@router.callback_query(F.data == "settings:set_pin")
async def settings_set_pin(call: CallbackQuery, state: FSMContext):
    await state.set_state(SettingsState.waiting_for_pin)
    await call.message.answer(
        "🔐 <b>Установка PIN-кода</b>\n\n"
        "Введи новый PIN — <b>4 или 6 цифр</b>.\n\n"
        "⚠️ Не забудь свой PIN — без него не войдёшь в бота после блокировки.",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(SettingsState.waiting_for_pin)
async def process_new_pin(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    pin = (message.text or "").strip()

    if not pin.isdigit() or len(pin) not in (4, 6):
        await message.answer(
            "❌ PIN должен содержать ровно <b>4 или 6 цифр</b>.\n"
            "Попробуй ещё раз:",
            parse_mode="HTML",
        )
        return

    await set_user_pin(tg_id, pin)
    await state.clear()

    await message.answer(
        f"✅ <b>PIN-код установлен!</b>\n\n"
        f"Теперь в меню есть кнопка 🔒 <b>Заблокировать</b>.\n"
        f"Нажми её, чтобы заблокировать бота — при следующем входе потребуется PIN.",
        parse_mode="HTML",
        reply_markup=main_menu(tg_id, has_pin=True),
    )


@router.callback_query(F.data == "settings:remove_pin")
async def settings_remove_pin(call: CallbackQuery, state: FSMContext):
    tg_id = call.from_user.id
    await state.clear()
    await remove_user_pin(tg_id)
    await call.answer("PIN удалён ✅")
    await call.message.answer(
        "✅ <b>PIN-код удалён.</b>\n\n"
        "Бот больше не будет запрашивать пароль при входе.",
        parse_mode="HTML",
        reply_markup=main_menu(tg_id, has_pin=False),
    )


@router.message(F.text == "🔒 Заблокировать")
async def cmd_lock(message: Message):
    tg_id = message.from_user.id
    user = await get_user(tg_id)
    if not user or not user.get("user_pin"):
        await message.answer(
            "❌ Сначала установи PIN-код в ⚙️ <b>Настройках</b>.",
            parse_mode="HTML",
        )
        return
    await set_user_locked(tg_id, True)
    await message.answer(
        "🔒 <b>Бот заблокирован.</b>\n\n"
        "Для доступа введи свой PIN-код:",
        parse_mode="HTML",
    )
