from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from config import PLANS, ADMIN_ID


def main_menu(tg_id: int = 0) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🛒 Купить VPN"), KeyboardButton(text="🎁 Пробный период")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="👥 Рефералы")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📱 Инструкция")],
        [KeyboardButton(text="📞 Поддержка")],
    ]
    if tg_id == ADMIN_ID:
        rows.append([KeyboardButton(text="🔧 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def buy_menu() -> InlineKeyboardMarkup:
    buttons = []
    for key, plan in PLANS.items():
        buttons.append([InlineKeyboardButton(text=plan["label"], callback_data=f"buy:{key}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_buy(plan_key: str) -> InlineKeyboardMarkup:
    plan = PLANS[plan_key]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"💳 Оплатить {plan['stars']} ⭐ Stars",
            callback_data=f"confirm_buy:{plan_key}",
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_buy")],
    ])


def profile_menu(sub_url: str | None = None) -> InlineKeyboardMarkup:
    buttons = []
    if sub_url:
        buttons.append([InlineKeyboardButton(text="🔗 Открыть ссылку подписки", url=sub_url)])
        buttons.append([InlineKeyboardButton(text="📋 Скопировать ссылку", callback_data="profile:copy_link")])
    buttons.append([InlineKeyboardButton(text="💳 История платежей", callback_data="profile:payments")])
    buttons.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="profile:refresh")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="👥 Все пользователи", callback_data="admin:users")],
        [InlineKeyboardButton(text="🎁 Выдать подписку", callback_data="admin:give")],
        [InlineKeyboardButton(text="🔧 Бесплатная покупка", callback_data="admin:free_buy")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")],
    ])


def admin_free_buy_menu() -> InlineKeyboardMarkup:
    buttons = []
    for key, plan in PLANS.items():
        buttons.append([InlineKeyboardButton(text=plan["label"], callback_data=f"admin_free:{key}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def sub_link_button(sub_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Открыть ссылку подписки", url=sub_url)],
    ])
