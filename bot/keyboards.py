from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from config import PLANS, ADMIN_ID


def main_menu(tg_id: int = 0, has_pin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🛒 Купить VPN"), KeyboardButton(text="🎁 Пробный период")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="💼 Подписка")],
        [KeyboardButton(text="👥 Рефералы"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="📱 Инструкция"), KeyboardButton(text="⚙️ Настройки")],
    ]
    if has_pin:
        rows.append([KeyboardButton(text="🔒 Заблокировать")])
    if tg_id == ADMIN_ID:
        rows.append([KeyboardButton(text="🔧 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def pin_keyboard(current: str = "", pin_len: int = 4) -> InlineKeyboardMarkup:
    """Numeric PIN pad inline keyboard."""
    entered = len(current)
    remaining = max(0, pin_len - entered)
    display_row = "●" * entered + "○" * remaining if entered else "○" * pin_len

    def btn(digit: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=digit, callback_data=f"pin:{current}{digit}")

    def del_btn() -> InlineKeyboardButton:
        return InlineKeyboardButton(text="⌫", callback_data=f"pin_del:{current}")

    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("1"), btn("2"), btn("3")],
        [btn("4"), btn("5"), btn("6")],
        [btn("7"), btn("8"), btn("9")],
        [del_btn(), btn("0")],
    ])


def settings_menu(has_pin: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    if has_pin:
        buttons.append([InlineKeyboardButton(text="🔑 Изменить PIN", callback_data="settings:set_pin")])
        buttons.append([InlineKeyboardButton(text="🗑 Удалить PIN", callback_data="settings:remove_pin")])
    else:
        buttons.append([InlineKeyboardButton(text="🔐 Установить PIN-код", callback_data="settings:set_pin")])
    buttons.append([InlineKeyboardButton(text="📞 Поддержка: @rl_highest", url="https://t.me/rl_highest")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


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
        [InlineKeyboardButton(
            text="💎 Оплатить TON (скидка 5%)",
            callback_data=f"buy_ton:{plan_key}",
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_buy")],
    ])


def ton_payment_keyboard(plan_key: str, ton_amount: float, comment: str, ton_link: str) -> InlineKeyboardMarkup:
    cb = f"ton_check:{plan_key}:{ton_amount:.2f}:{comment}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Открыть Tonkeeper", url=ton_link)],
        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=cb)],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"buy:{plan_key}")],
    ])


def profile_menu(sub_url: str | None = None) -> InlineKeyboardMarkup:
    buttons = []
    if sub_url:
        buttons.append([InlineKeyboardButton(text="🔗 Открыть ссылку подписки", url=sub_url)])
        buttons.append([InlineKeyboardButton(text="📋 Скопировать ссылку", callback_data="profile:copy_link")])
    buttons.append([InlineKeyboardButton(text="💳 История платежей", callback_data="profile:payments")])
    buttons.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="profile:refresh")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def subscription_menu(is_frozen: bool = False, has_sub: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    if is_frozen:
        buttons.append([InlineKeyboardButton(text="🔓 Разморозить подписку", callback_data="sub:unfreeze")])
    elif has_sub:
        buttons.append([InlineKeyboardButton(text="🛒 Продлить подписку", callback_data="sub:extend")])
        buttons.append([InlineKeyboardButton(text="🧊 Заморозить подписку", callback_data="sub:freeze")])
    else:
        buttons.append([InlineKeyboardButton(text="🛒 Купить подписку", callback_data="sub:extend")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="👥 Все пользователи", callback_data="admin:users")],
        [InlineKeyboardButton(text="🎁 Выдать подписку", callback_data="admin:give")],
        [InlineKeyboardButton(text="🔧 Бесплатная покупка", callback_data="admin:free_buy")],
        [InlineKeyboardButton(text="🔄 Сбросить проверку подписки", callback_data="admin:reset_sub")],
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
