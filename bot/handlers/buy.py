import asyncio
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice,
    PreCheckoutQuery,
)
from aiogram.filters import Command

from config import PLANS, ADMIN_ID, XUI_SUB_URL
from database import (
    get_user, create_user, update_subscription, add_payment,
    count_user_payments, get_unrewarded_referral, mark_referral_rewarded,
)
from keyboards import buy_menu, confirm_buy
import xui_api

logger = logging.getLogger(__name__)
router = Router()

REFERRAL_BONUS_DAYS = 7


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
    direction = 1
    while not stop_event.is_set():
        await _set_progress(msg, label, pct)
        await asyncio.sleep(0.7)
        pct += direction * 3
        if pct >= end:
            pct = end
            direction = -1
        elif pct <= start:
            pct = start
            direction = 1


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


@router.message(F.text == "🛒 Купить VPN")
@router.message(Command("buy"))
async def cmd_buy(message: Message):
    await message.answer(
        "💳 <b>Выбери тарифный план:</b>\n\n"
        "🔹 <b>50 ⭐</b> — 7 дней\n"
        "🔹 <b>100 ⭐</b> — 1 месяц\n"
        "🔹 <b>250 ⭐</b> — 3 месяца\n"
        "🔹 <b>500 ⭐</b> — 1 год\n\n"
        "⭐ Оплата через Telegram Stars",
        reply_markup=buy_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("buy:"))
async def on_plan_select(call: CallbackQuery):
    plan_key = call.data.split(":")[1]
    plan = PLANS.get(plan_key)
    if not plan:
        await call.answer("Неизвестный тариф", show_alert=True)
        return

    text = (
        f"📦 <b>{plan['label']}</b>\n\n"
        f"✅ Неограниченный трафик\n"
        f"✅ Несколько серверов\n"
        f"✅ Один ключ — все серверы\n\n"
        f"💳 Стоимость: <b>{plan['stars']} ⭐ Stars</b>"
    )
    await call.message.edit_text(text, reply_markup=confirm_buy(plan_key), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "back_to_buy")
async def on_back_to_buy(call: CallbackQuery):
    await call.message.edit_text(
        "💳 <b>Выбери тарифный план:</b>",
        reply_markup=buy_menu(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("confirm_buy:"))
async def on_confirm_buy(call: CallbackQuery):
    plan_key = call.data.split(":")[1]
    plan = PLANS.get(plan_key)
    if not plan:
        await call.answer("Неизвестный тариф", show_alert=True)
        return

    await call.answer()
    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title=f"VPN — {plan['label']}",
        description=f"Безлимитный VPN доступ. {plan['label']}",
        payload=f"vpn_{plan_key}_{call.from_user.id}",
        currency="XTR",
        prices=[LabeledPrice(label=plan["label"], amount=plan["stars"])],
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    charge_id = payment.telegram_payment_charge_id
    tg_id = message.from_user.id

    parts = payload.split("_")
    plan_key = parts[1] if len(parts) >= 2 else ""
    plan = PLANS.get(plan_key)
    if not plan:
        await message.answer("❌ Ошибка обработки платежа. Обратитесь в поддержку @rl_highest")
        return

    user = await get_user(tg_id)
    if not user:
        user = await create_user(tg_id, message.from_user.username, message.from_user.first_name or "")

    # Count BEFORE recording this payment (to detect first purchase)
    previous_payments = await count_user_payments(tg_id)

    proc_msg = await message.answer(
        f"⏳ <b>Активация подписки...</b>\n\n{_bar(0)} 0%",
        parse_mode="HTML",
    )

    sub_id = user["sub_id"]
    current_expiry = await xui_api.get_expiry_for_user(tg_id)
    now_ms = int(datetime.utcnow().timestamp() * 1000)
    extend = current_expiry is not None and current_expiry > now_ms

    ok = await _run_with_bar(
        proc_msg,
        xui_api.add_client_to_all_inbounds(
            tg_id=tg_id,
            sub_id=sub_id,
            days=plan["days"],
            is_trial=False,
            extend=extend,
            current_expiry_ms=current_expiry,
        ),
        label="Активация подписки",
        start=10,
        end=90,
    )

    await _set_progress(proc_msg, "Сохранение данных...", 95)
    await asyncio.sleep(0.4)

    await update_subscription(tg_id, plan["days"])
    await add_payment(tg_id, plan_key, plan["stars"], charge_id)

    sub_url = f"{XUI_SUB_URL}/{sub_id}"

    if ok:
        await proc_msg.edit_text(
            f"✅ <b>Подписка активирована!</b>\n\n"
            f"📦 Тариф: <b>{plan['label']}</b>\n"
            f"🔗 Ссылка для подключения:\n<code>{sub_url}</code>\n\n"
            f"💡 Импортируй эту ссылку в любой VLESS-клиент:\n"
            f"• <b>Android:</b> v2rayNG, Hiddify\n"
            f"• <b>iOS:</b> Streisand, Shadowrocket\n"
            f"• <b>Windows/Mac:</b> Hiddify, v2rayN",
            parse_mode="HTML",
        )
    else:
        await proc_msg.edit_text(
            f"⚠️ Оплата прошла, но возникла ошибка при создании VPN-аккаунта.\n"
            f"Обратитесь в поддержку @rl_highest с вашим ID: <code>{tg_id}</code>",
            parse_mode="HTML",
        )

    # ── Referral reward on first purchase ────────────────────────────────────
    if previous_payments == 0:
        referral = await get_unrewarded_referral(tg_id)
        if referral:
            referrer_id = referral["referrer_id"]
            referrer = await get_user(referrer_id)
            if referrer:
                await update_subscription(referrer_id, REFERRAL_BONUS_DAYS)
                referrer_sub_id = referrer["sub_id"]
                referrer_expiry = await xui_api.get_expiry_for_user(referrer_id)
                referrer_expiry_ms = referrer_expiry if referrer_expiry else None
                referrer_now_ms = int(datetime.utcnow().timestamp() * 1000)
                referrer_extend = referrer_expiry_ms is not None and referrer_expiry_ms > referrer_now_ms
                await xui_api.add_client_to_all_inbounds(
                    tg_id=referrer_id,
                    sub_id=referrer_sub_id,
                    days=REFERRAL_BONUS_DAYS,
                    is_trial=False,
                    extend=referrer_extend,
                    current_expiry_ms=referrer_expiry_ms,
                )
                await mark_referral_rewarded(referral["id"])
                try:
                    await message.bot.send_message(
                        referrer_id,
                        f"🎉 <b>Реферальный бонус!</b>\n\n"
                        f"Твой друг совершил первую покупку.\n"
                        f"Тебе начислено <b>+{REFERRAL_BONUS_DAYS} дней</b> к подписке! 🚀",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

    # ── Admin notification ────────────────────────────────────────────────────
    try:
        await message.bot.send_message(
            ADMIN_ID,
            f"💰 <b>Новая оплата!</b>\n"
            f"👤 ID: <code>{tg_id}</code>\n"
            f"👤 Ник: @{message.from_user.username or '-'}\n"
            f"📦 Тариф: {plan['label']}\n"
            f"⭐ Stars: {plan['stars']}",
            parse_mode="HTML",
        )
    except Exception:
        pass
