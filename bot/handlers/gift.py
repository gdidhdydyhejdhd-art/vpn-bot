import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, LabeledPrice
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import PLANS, ADMIN_ID, XUI_SUB_URL, TON_WALLET, STARS_USD_RATE
from database import get_user, create_user
from keyboards import gift_plan_menu, gift_confirm_menu, main_menu
import xui_api

logger = logging.getLogger(__name__)
router = Router()


class GiftStates(StatesGroup):
    waiting_recipient = State()
    waiting_plan = State()


@router.message(F.text == "🎁 Подарить VPN")
@router.message(Command("gift"))
async def cmd_gift(message: Message, state: FSMContext):
    await state.set_state(GiftStates.waiting_recipient)
    await message.answer(
        "🎁 <b>Подарить VPN-подписку</b>\n\n"
        "Введи <b>Telegram ID</b> получателя.\n\n"
        "💡 Чтобы узнать ID — попроси друга написать боту /start, "
        "его ID появится в профиле.\n\n"
        "Для отмены: /cancel",
        parse_mode="HTML",
    )


@router.message(GiftStates.waiting_recipient)
async def gift_recipient_entered(message: Message, state: FSMContext):
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Отменено.")
        return

    try:
        recipient_id = int(message.text.strip())
    except ValueError:
        await message.answer(
            "❌ Неверный формат. Введи числовой <b>Telegram ID</b> получателя:",
            parse_mode="HTML",
        )
        return

    if recipient_id == message.from_user.id:
        await message.answer(
            "❌ Нельзя подарить подписку самому себе.\n"
            "Введи ID другого пользователя:",
        )
        return

    # Check recipient exists (optional — create on payment anyway)
    recipient = await get_user(recipient_id)
    recipient_name = recipient.get("first_name", f"ID {recipient_id}") if recipient else f"ID {recipient_id}"

    await state.update_data(recipient_id=recipient_id, recipient_name=recipient_name)
    await state.set_state(GiftStates.waiting_plan)

    await message.answer(
        f"🎁 <b>Получатель: {recipient_name}</b> (<code>{recipient_id}</code>)\n\n"
        f"Выбери тариф для подарка:",
        reply_markup=gift_plan_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("gift_plan:"))
async def gift_plan_selected(call: CallbackQuery, state: FSMContext):
    plan_key = call.data.split(":")[1]
    plan = PLANS.get(plan_key)
    if not plan:
        await call.answer("Неверный тариф", show_alert=True)
        return

    data = await state.get_data()
    recipient_id = data.get("recipient_id")
    recipient_name = data.get("recipient_name", f"ID {recipient_id}")

    if not recipient_id:
        await call.answer("Ошибка: начни заново", show_alert=True)
        await state.clear()
        return

    await state.clear()

    await call.message.edit_text(
        f"🎁 <b>Подтверждение подарка</b>\n\n"
        f"👤 Получатель: <b>{recipient_name}</b> (<code>{recipient_id}</code>)\n"
        f"📦 Тариф: <b>{plan['label']}</b>\n"
        f"💳 Стоимость: <b>{plan['stars']} ⭐ Stars</b>\n\n"
        f"Выбери способ оплаты:",
        reply_markup=gift_confirm_menu(plan_key, recipient_id),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("gift_pay_stars:"))
async def gift_pay_stars(call: CallbackQuery):
    parts = call.data.split(":")
    plan_key = parts[1]
    try:
        recipient_id = int(parts[2])
    except (IndexError, ValueError):
        await call.answer("Ошибка данных", show_alert=True)
        return

    plan = PLANS.get(plan_key)
    if not plan:
        await call.answer("Неверный тариф", show_alert=True)
        return

    gifter_id = call.from_user.id
    await call.answer()
    await call.bot.send_invoice(
        chat_id=gifter_id,
        title=f"🎁 Подарок VPN — {plan['label']}",
        description=f"Подарочная подписка VPN. {plan['label']}",
        payload=f"gift_{plan_key}_{recipient_id}_{gifter_id}",
        currency="XTR",
        prices=[LabeledPrice(label=f"Подарок: {plan['label']}", amount=plan["stars"])],
    )


@router.callback_query(F.data.startswith("gift_pay_ton:"))
async def gift_pay_ton(call: CallbackQuery):
    """Gift via TON — show payment details, check same as regular TON but with recipient."""
    from handlers.ton_pay import get_ton_price_usd, calc_ton_amount

    parts = call.data.split(":")
    plan_key = parts[1]
    try:
        recipient_id = int(parts[2])
    except (IndexError, ValueError):
        await call.answer("Ошибка данных", show_alert=True)
        return

    plan = PLANS.get(plan_key)
    if not plan:
        await call.answer("Неверный тариф", show_alert=True)
        return

    gifter_id = call.from_user.id
    comment = f"gift{gifter_id}"

    await call.answer()
    loading = await call.message.answer("⏳ <b>Получаю курс TON...</b>", parse_mode="HTML")

    ton_price = await get_ton_price_usd()
    ton_amount = calc_ton_amount(plan["stars"], ton_price)
    nanoton = int(ton_amount * 1_000_000_000)

    try:
        await loading.delete()
    except Exception:
        pass

    ton_link = f"https://app.tonkeeper.com/transfer/{TON_WALLET}?amount={nanoton}&text={comment}"
    stars_usd = round(plan["stars"] * STARS_USD_RATE, 2)
    ton_usd = round(ton_amount * ton_price, 2)

    from keyboards import ton_payment_keyboard
    await call.message.answer(
        f"💎 <b>Оплата подарка в TON</b>\n\n"
        f"📦 Тариф: <b>{plan['label']}</b>\n"
        f"🎁 Получатель ID: <code>{recipient_id}</code>\n"
        f"💎 Цена в TON: <b>{ton_amount} TON</b> (≈ ${ton_usd}) — <b>скидка 5%!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📬 <b>Кошелёк:</b>\n<code>{TON_WALLET}</code>\n\n"
        f"💬 <b>Комментарий (обязательно!):</b>\n<code>{comment}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"После оплаты нажми «✅ Проверить оплату»",
        parse_mode="HTML",
        reply_markup=ton_payment_keyboard(plan_key, ton_amount, comment, ton_link, recipient_id=recipient_id),
    )


@router.callback_query(F.data == "gift:cancel")
async def gift_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    tg_id = call.from_user.id
    user = await get_user(tg_id)
    has_pin = bool(user and user.get("user_pin")) if user else False
    await call.message.answer(
        "❌ Отменено.",
        reply_markup=main_menu(tg_id, has_pin=has_pin),
    )
    await call.answer()
