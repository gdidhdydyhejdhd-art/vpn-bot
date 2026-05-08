import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import get_user, set_user_pin, remove_user_pin, set_user_locked
from keyboards import main_menu, settings_menu, pin_keyboard

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
        "При блокировке бот потребует ввести PIN с помощью цифровых кнопок.",
        parse_mode="HTML",
        reply_markup=settings_menu(has_pin),
    )


@router.callback_query(F.data == "settings:set_pin")
async def settings_set_pin(call: CallbackQuery, state: FSMContext):
    await state.set_state(SettingsState.waiting_for_pin)
    await call.message.answer(
        "🔐 <b>Установка PIN-кода</b>\n\n"
        "Введи новый PIN — <b>4 или 6 цифр</b> сообщением.\n\n"
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
            "❌ PIN должен содержать ровно <b>4 или 6 цифр</b>.\nПопробуй ещё раз:",
            parse_mode="HTML",
        )
        return

    await set_user_pin(tg_id, pin)
    await state.clear()

    await message.answer(
        f"✅ <b>PIN-код установлен!</b>\n\n"
        f"Теперь в меню есть кнопка 🔒 <b>Заблокировать</b>.\n"
        f"Нажми её — при следующем входе потребуется PIN через цифровые кнопки.",
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
        "✅ <b>PIN-код удалён.</b>\n\nБот больше не будет запрашивать пароль при входе.",
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
    pin_len = len(user["user_pin"])

    # Remove reply keyboard
    await message.answer("🔒", reply_markup=ReplyKeyboardRemove())
    # Show PIN pad
    await message.answer(
        f"🔒 <b>Бот заблокирован</b>\n\n{'○' * pin_len}",
        parse_mode="HTML",
        reply_markup=pin_keyboard("", pin_len),
    )


# ── PIN pad callbacks ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pin:"))
async def pin_digit_press(call: CallbackQuery):
    current = call.data[4:]  # text after "pin:"
    tg_id = call.from_user.id

    if len(current) > 6:
        await call.answer()
        return

    user = await get_user(tg_id)
    if not user:
        await call.answer("Ошибка", show_alert=True)
        return

    user_pin = user.get("user_pin", "")
    pin_len = len(user_pin) if user_pin else 4

    # Auto-verify when enough digits entered
    if len(current) == pin_len:
        if current == user_pin:
            await set_user_locked(tg_id, False)
            await call.answer("✅ Верно!")
            try:
                await call.message.delete()
            except Exception:
                pass
            await call.message.answer(
                "🔓 <b>Бот разблокирован!</b>\n\nВыбери действие:",
                parse_mode="HTML",
                reply_markup=main_menu(tg_id, has_pin=True),
            )
        else:
            await call.answer("❌ Неверный PIN!", show_alert=True)
            display = "❌ Неверный PIN — попробуй снова\n\n" + "○" * pin_len
            try:
                await call.message.edit_text(
                    f"🔒 <b>Бот заблокирован</b>\n\n{display}",
                    parse_mode="HTML",
                    reply_markup=pin_keyboard("", pin_len),
                )
            except Exception:
                pass
        return

    # 4 digits entered but PIN is 6 → continue entering
    if len(current) == 4 and pin_len == 6:
        display = "●" * 4 + "○" * 2
        await call.answer()
        try:
            await call.message.edit_text(
                f"🔒 <b>Бот заблокирован</b>\n\n{display}",
                parse_mode="HTML",
                reply_markup=pin_keyboard(current, pin_len),
            )
        except Exception:
            pass
        return

    # Show updated dots
    entered = len(current)
    remaining = max(0, pin_len - entered)
    display = "●" * entered + "○" * remaining
    await call.answer()
    try:
        await call.message.edit_text(
            f"🔒 <b>Бот заблокирован</b>\n\n{display}",
            parse_mode="HTML",
            reply_markup=pin_keyboard(current, pin_len),
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("pin_del:"))
async def pin_digit_delete(call: CallbackQuery):
    current = call.data[8:]  # text after "pin_del:"
    new = current[:-1] if current else ""
    tg_id = call.from_user.id

    user = await get_user(tg_id)
    pin_len = len((user or {}).get("user_pin", "") or "") or 4

    entered = len(new)
    remaining = max(0, pin_len - entered)
    display = "●" * entered + "○" * remaining if new else "○" * pin_len

    await call.answer()
    try:
        await call.message.edit_text(
            f"🔒 <b>Бот заблокирован</b>\n\n{display}",
            parse_mode="HTML",
            reply_markup=pin_keyboard(new, pin_len),
        )
    except Exception:
        pass
