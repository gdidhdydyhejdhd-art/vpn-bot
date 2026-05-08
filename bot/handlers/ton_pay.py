import logging
from datetime import datetime, timezone
import aiohttp
from aiogram import Router, F
from aiogram.types import CallbackQuery

from config import PLANS, ADMIN_ID, XUI_SUB_URL, TON_WALLET, STARS_USD_RATE
from database import (
    get_user, create_user, update_subscription, add_payment,
    count_user_payments, get_unrewarded_referral, mark_referral_rewarded,
)
from keyboards import ton_payment_keyboard
import xui_api

logger = logging.getLogger(__name__)
router = Router()

REFERRAL_BONUS_DAYS = 7


async def get_ton_price_usd() -> float:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                data = await resp.json(content_type=None)
                return float(data["the-open-network"]["usd"])
    except Exception as e:
        logger.warning(f"TON price fetch failed: {e}")
        return 5.0  # fallback price


def calc_ton_amount(stars: int, ton_price_usd: float) -> float:
    usd_amount = stars * STARS_USD_RATE
    discounted = usd_amount * 0.95  # 5% discount
    return round(discounted / ton_price_usd, 2)


async def check_ton_payment_received(expected_ton: float, comment: str) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://toncenter.com/api/v2/getTransactions",
                params={"address": TON_WALLET, "limit": 20},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json(content_type=None)
                if not data.get("ok"):
                    return False

                now = datetime.now(timezone.utc)
                for tx in data.get("result", []):
                    in_msg = tx.get("in_msg", {})
                    msg_text = str(in_msg.get("message", "") or "")
                    value_nano = int(in_msg.get("value", 0))
                    value_ton = value_nano / 1_000_000_000
                    utime = tx.get("utime", 0)

                    tx_time = datetime.fromtimestamp(utime, tz=timezone.utc)
                    age_minutes = (now - tx_time).total_seconds() / 60

                    if age_minutes > 90:
                        continue
                    if comment not in msg_text:
                        continue
                    # 15% tolerance to cover price fluctuation
                    if value_ton > 0 and abs(value_ton - expected_ton) / max(expected_ton, 0.001) <= 0.15:
                        return True
        return False
    except Exception as e:
        logger.warning(f"TonCenter check error: {e}")
        return False


@router.callback_query(F.data.startswith("buy_ton:"))
async def on_ton_plan_select(call: CallbackQuery):
    plan_key = call.data.split(":")[1]
    plan = PLANS.get(plan_key)
    if not plan:
        await call.answer("Неизвестный тариф", show_alert=True)
        return

    await call.answer()
    tg_id = call.from_user.id
    comment = str(tg_id)

    loading_msg = await call.message.answer("⏳ <b>Получаю актуальный курс TON...</b>", parse_mode="HTML")

    ton_price = await get_ton_price_usd()
    ton_amount = calc_ton_amount(plan["stars"], ton_price)
    nanoton = int(ton_amount * 1_000_000_000)
    ton_link = f"ton://transfer/{TON_WALLET}?amount={nanoton}&text={comment}"

    try:
        await loading_msg.delete()
    except Exception:
        pass

    stars_price = plan["stars"]
    stars_usd = round(stars_price * STARS_USD_RATE, 2)
    ton_usd = round(ton_amount * ton_price, 2)

    await call.message.answer(
        f"💎 <b>Оплата в TON</b>\n\n"
        f"📦 Тариф: <b>{plan['label']}</b>\n"
        f"💳 Цена в Stars: {stars_price} ⭐ (≈ ${stars_usd})\n"
        f"💎 Цена в TON: <b>{ton_amount} TON</b> (≈ ${ton_usd}) — <b>скидка 5%!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📬 <b>Кошелёк для перевода:</b>\n"
        f"<code>{TON_WALLET}</code>\n\n"
        f"💬 <b>Комментарий (обязательно!):</b>\n"
        f"<code>{comment}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Как оплатить:</b>\n"
        f"1️⃣ Нажми «💎 Открыть TON-кошелёк» — данные заполнятся автоматически\n"
        f"2️⃣ Или переведи вручную: <b>{ton_amount} TON</b> с комментарием <code>{comment}</code>\n"
        f"3️⃣ После отправки нажми «✅ Проверить оплату»\n\n"
        f"⚠️ <b>Без комментария оплата не определится!</b>\n"
        f"💡 Курс TON: ${ton_price:.2f} | Проверка работает до 90 минут после оплаты",
        parse_mode="HTML",
        reply_markup=ton_payment_keyboard(plan_key, ton_amount, comment, ton_link),
    )


@router.callback_query(F.data.startswith("ton_check:"))
async def on_ton_check(call: CallbackQuery):
    parts = call.data.split(":")
    if len(parts) < 4:
        await call.answer("Ошибка данных. Начни заново.", show_alert=True)
        return

    plan_key = parts[1]
    try:
        ton_amount = float(parts[2])
    except ValueError:
        await call.answer("Ошибка суммы. Начни заново.", show_alert=True)
        return
    comment = parts[3]
    tg_id = call.from_user.id

    plan = PLANS.get(plan_key)
    if not plan:
        await call.answer("Неизвестный тариф", show_alert=True)
        return

    await call.answer("🔍 Проверяю блокчейн...")
    check_msg = await call.message.answer(
        "🔍 <b>Проверяю поступление платежа в блокчейне TON...</b>\n"
        "<i>Это может занять несколько секунд.</i>",
        parse_mode="HTML",
    )

    found = await check_ton_payment_received(ton_amount, comment)

    try:
        await check_msg.delete()
    except Exception:
        pass

    if found:
        user = await get_user(tg_id)
        if not user:
            user = await create_user(tg_id, call.from_user.username, call.from_user.first_name or "")

        previous_payments = await count_user_payments(tg_id)
        sub_id = user["sub_id"]
        current_expiry = await xui_api.get_expiry_for_user(tg_id)
        now_ms = int(datetime.utcnow().timestamp() * 1000)
        extend = current_expiry is not None and current_expiry > now_ms

        ok = await xui_api.add_client_to_all_inbounds(
            tg_id=tg_id, sub_id=sub_id, days=plan["days"],
            is_trial=False, extend=extend, current_expiry_ms=current_expiry,
        )
        await update_subscription(tg_id, plan["days"])
        await add_payment(tg_id, plan_key, 0, f"TON:{ton_amount:.2f}")

        sub_url = f"{XUI_SUB_URL}/{sub_id}"
        if ok:
            await call.message.answer(
                f"✅ <b>Оплата подтверждена! Подписка активирована!</b>\n\n"
                f"📦 Тариф: <b>{plan['label']}</b>\n"
                f"💎 Оплачено: <b>{ton_amount} TON</b>\n\n"
                f"🔗 Ссылка для подключения:\n<code>{sub_url}</code>\n\n"
                f"💡 Импортируй ссылку в клиент:\n"
                f"🤖 <b>Android:</b> v2rayNG, Hiddify, Happ, INCY VPN\n"
                f"🍎 <b>iOS:</b> Streisand, V2RayTun, Happ, FoXray\n"
                f"🖥 <b>Windows/Mac:</b> Hiddify, v2rayN, NekoRay",
                parse_mode="HTML",
            )
        else:
            await call.message.answer(
                f"⚠️ Оплата найдена, но ошибка при активации подписки.\n"
                f"Обратитесь к @rl_highest с ID: <code>{tg_id}</code>",
                parse_mode="HTML",
            )

        # Referral bonus
        if previous_payments == 0:
            referral = await get_unrewarded_referral(tg_id)
            if referral:
                referrer_id = referral["referrer_id"]
                referrer = await get_user(referrer_id)
                if referrer:
                    await update_subscription(referrer_id, REFERRAL_BONUS_DAYS)
                    r_sub_id = referrer["sub_id"]
                    r_expiry = await xui_api.get_expiry_for_user(referrer_id)
                    r_now_ms = int(datetime.utcnow().timestamp() * 1000)
                    r_extend = r_expiry is not None and r_expiry > r_now_ms
                    await xui_api.add_client_to_all_inbounds(
                        tg_id=referrer_id, sub_id=r_sub_id, days=REFERRAL_BONUS_DAYS,
                        is_trial=False, extend=r_extend, current_expiry_ms=r_expiry,
                    )
                    await mark_referral_rewarded(referral["id"])
                    try:
                        await call.bot.send_message(
                            referrer_id,
                            f"🎉 <b>Реферальный бонус!</b>\n\n"
                            f"Твой друг совершил первую покупку.\n"
                            f"Тебе начислено <b>+{REFERRAL_BONUS_DAYS} дней</b> к подписке! 🚀",
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass

        # Admin notification
        try:
            await call.bot.send_message(
                ADMIN_ID,
                f"💎 <b>Оплата TON!</b>\n"
                f"👤 ID: <code>{tg_id}</code>\n"
                f"👤 Ник: @{call.from_user.username or '-'}\n"
                f"📦 Тариф: {plan['label']}\n"
                f"💰 TON: {ton_amount:.2f}",
                parse_mode="HTML",
            )
        except Exception:
            pass

    else:
        nanoton = int(ton_amount * 1_000_000_000)
        ton_link = f"ton://transfer/{TON_WALLET}?amount={nanoton}&text={comment}"
        await call.message.answer(
            f"❌ <b>Платёж не найден.</b>\n\n"
            f"Убедись, что:\n"
            f"• Отправил ровно <b>{ton_amount} TON</b>\n"
            f"• Указал комментарий: <code>{comment}</code>\n"
            f"• Прошло минимум 1-2 минуты после отправки\n\n"
            f"Попробуй снова через пару минут.\n"
            f"Если проблема остаётся — напиши @rl_highest и укажи свой ID: <code>{tg_id}</code>",
            parse_mode="HTML",
            reply_markup=ton_payment_keyboard(plan_key, ton_amount, comment, ton_link),
        )
