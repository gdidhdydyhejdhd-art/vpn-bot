import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_ID, PLANS, XUI_SUB_URL
from database import get_user, create_user, get_all_users, get_stats, update_subscription, add_payment
from keyboards import admin_menu, admin_free_buy_menu
import xui_api

logger = logging.getLogger(__name__)
router = Router()


class AdminStates(StatesGroup):
    waiting_give_user_id = State()
    waiting_give_plan = State()
    waiting_broadcast = State()


def is_admin(tg_id: int) -> bool:
    return tg_id == ADMIN_ID


@router.message(F.text == "🔧 Админ-панель")
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "🔧 <b>Панель администратора</b>",
        reply_markup=admin_menu(),
        parse_mode="HTML",
    )


@router.message(Command("ping"))
async def cmd_ping(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("⏳ Проверяю соединение с x-ui...")
    inbounds = await xui_api.get_inbounds()
    if inbounds:
        names = [f"• <code>{ib.get('remark', ib.get('id'))}</code>" for ib in inbounds]
        await message.answer(
            f"✅ <b>x-ui работает</b>\n\n"
            f"📡 Инбаундов: <b>{len(inbounds)}</b>\n"
            f"🛣 API путь: <code>{xui_api._working_inbounds_path}</code>\n\n"
            f"<b>Список инбаундов:</b>\n" + "\n".join(names),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "❌ <b>x-ui не отвечает</b>\n\n"
            "Возможные причины:\n"
            "• Истекла сессия\n"
            "• Панель недоступна\n"
            "• Неверный логин/пароль",
            parse_mode="HTML",
        )


@router.callback_query(F.data == "admin:stats")
async def admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    stats = await get_stats()
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Всего пользователей: <b>{stats['total']}</b>\n"
        f"✅ Активных подписок: <b>{stats['active']}</b>\n"
        f"🎁 Использовали триал: <b>{stats['trials']}</b>\n"
        f"⭐ Stars заработано: <b>{stats['total_stars']}</b>\n"
        f"👥 Рефералов всего: <b>{stats['total_refs']}</b>\n"
        f"🎁 Рефералов вознаграждено: <b>{stats['rewarded_refs']}</b>"
    )
    await call.message.edit_text(text, reply_markup=admin_menu(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "admin:users")
async def admin_users(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    users = await get_all_users()
    if not users:
        await call.answer("Пользователей нет", show_alert=True)
        return

    lines = []
    for u in users[:30]:
        sub_end = u.get("subscription_end", "")
        if sub_end:
            try:
                end = datetime.fromisoformat(sub_end)
                status = "✅" if end > datetime.utcnow() else "❌"
                date_str = end.strftime("%d.%m.%Y")
            except Exception:
                status = "?"
                date_str = sub_end[:10]
        else:
            status = "❌"
            date_str = "нет"

        uname = f"@{u['username']}" if u.get("username") else u.get("first_name", "?")
        lines.append(f"{status} <code>{u['tg_id']}</code> {uname} — {date_str}")

    text = f"👥 <b>Пользователи ({len(users)} чел.)</b>\n\n" + "\n".join(lines)
    if len(users) > 30:
        text += f"\n\n...и ещё {len(users) - 30} чел."

    await call.message.edit_text(text, reply_markup=admin_menu(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "admin:give")
async def admin_give_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_give_user_id)
    await call.message.answer(
        "👤 Введи <b>Telegram ID</b> пользователя, которому выдать подписку:",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(AdminStates.waiting_give_user_id)
async def admin_give_user_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный ID. Введи числовой Telegram ID.")
        return
    await state.update_data(target_id=target_id)
    await state.set_state(AdminStates.waiting_give_plan)
    buttons_text = "\n".join(f"• <code>{k}</code> — {v['label']}" for k, v in PLANS.items())
    await message.answer(
        f"📦 Выбери тариф:\n\n{buttons_text}\n\nОтправь код тарифа:",
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_give_plan)
async def admin_give_plan(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    plan_key = message.text.strip()
    plan = PLANS.get(plan_key)
    if not plan:
        await message.answer("❌ Неверный тариф. Попробуй: 7days / 1month / 3months / 1year")
        return

    data = await state.get_data()
    target_id = data["target_id"]
    await state.clear()

    user = await get_user(target_id)
    if not user:
        user = await create_user(target_id, None, f"User{target_id}")

    sub_id = user["sub_id"]
    current_expiry = await xui_api.get_expiry_for_user(target_id)
    now_ms = int(datetime.utcnow().timestamp() * 1000)
    extend = current_expiry is not None and current_expiry > now_ms

    ok = await xui_api.add_client_to_all_inbounds(
        tg_id=target_id,
        sub_id=sub_id,
        days=plan["days"],
        is_trial=False,
        extend=extend,
        current_expiry_ms=current_expiry,
    )
    await update_subscription(target_id, plan["days"])
    await add_payment(target_id, plan_key, 0, "admin_gift", is_gift=1, gifted_by=ADMIN_ID)

    sub_url = f"{XUI_SUB_URL}/{sub_id}"
    if ok:
        await message.answer(
            f"✅ Подписка <b>{plan['label']}</b> выдана пользователю <code>{target_id}</code>\n"
            f"🔗 Ссылка: <code>{sub_url}</code>",
            parse_mode="HTML",
        )
        try:
            await message.bot.send_message(
                target_id,
                f"🎁 <b>Вам выдана подписка!</b>\n\n"
                f"📦 Тариф: {plan['label']}\n"
                f"🔗 Ссылка: <code>{sub_url}</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass
    else:
        await message.answer("❌ Ошибка при создании VPN-аккаунта. Проверь x-ui панель.")


@router.callback_query(F.data == "admin:free_buy")
async def admin_free_buy(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await call.message.edit_text(
        "🔧 <b>Бесплатная покупка (тест)</b>\n\nВыбери тариф:",
        reply_markup=admin_free_buy_menu(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin_free:"))
async def admin_free_activate(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    plan_key = call.data.split(":")[1]
    plan = PLANS.get(plan_key)
    if not plan:
        await call.answer("Неверный тариф", show_alert=True)
        return

    tg_id = call.from_user.id
    user = await get_user(tg_id)
    if not user:
        user = await create_user(tg_id, call.from_user.username, call.from_user.first_name or "")

    sub_id = user["sub_id"]
    current_expiry = await xui_api.get_expiry_for_user(tg_id)
    now_ms = int(datetime.utcnow().timestamp() * 1000)
    extend = current_expiry is not None and current_expiry > now_ms

    await call.message.edit_text("⏳ Активирую...", parse_mode="HTML")
    ok = await xui_api.add_client_to_all_inbounds(
        tg_id=tg_id,
        sub_id=sub_id,
        days=plan["days"],
        is_trial=False,
        extend=extend,
        current_expiry_ms=current_expiry,
    )
    await update_subscription(tg_id, plan["days"])
    await add_payment(tg_id, plan_key, 0, "admin_free_test", is_gift=1, gifted_by=tg_id)

    sub_url = f"{XUI_SUB_URL}/{sub_id}"
    if ok:
        await call.message.edit_text(
            f"✅ <b>Бесплатная подписка активирована!</b>\n\n"
            f"📦 Тариф: {plan['label']}\n"
            f"🔗 Ссылка: <code>{sub_url}</code>",
            reply_markup=admin_menu(),
            parse_mode="HTML",
        )
    else:
        await call.message.edit_text(
            "❌ Ошибка при создании аккаунта.",
            reply_markup=admin_menu(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_broadcast)
    await call.message.answer(
        "📢 <b>Рассылка всем пользователям</b>\n\n"
        "Отправь текст сообщения. Поддерживается <b>HTML</b> разметка.\n\n"
        "Для отмены напиши /cancel",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(AdminStates.waiting_broadcast)
async def admin_broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Рассылка отменена.")
        return

    await state.clear()
    users = await get_all_users()
    text = message.text or ""

    sent = 0
    failed = 0
    status_msg = await message.answer(f"⏳ Начинаю рассылку {len(users)} пользователям...")

    for user in users:
        try:
            await message.bot.send_message(user["tg_id"], text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📤 Отправлено: <b>{sent}</b>\n"
        f"❌ Не доставлено: <b>{failed}</b>",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:back")
async def admin_back(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await call.message.edit_text(
        "🔧 <b>Панель администратора</b>",
        reply_markup=admin_menu(),
        parse_mode="HTML",
    )
    await call.answer()
