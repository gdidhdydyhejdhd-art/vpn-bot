import os

BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]

XUI_URL: str = "https://2.26.22.74:65535/YwC494ue7Vw6AMvI3B"
XUI_SUB_URL: str = "https://2.26.22.74:2096/sub"
XUI_LOGIN: str = os.environ["XUI_LOGIN"]
XUI_PASSWORD: str = os.environ["XUI_PASSWORD"]

ADMIN_ID: int = 8291123248
ADMIN_USERNAME: str = "rl_highest"

DB_PATH: str = "bot/vpn_bot.db"

PLANS: dict = {
    "7days": {"stars": 50, "days": 7, "label": "7 дней — 50 ⭐"},
    "1month": {"stars": 100, "days": 30, "label": "1 месяц — 100 ⭐"},
    "3months": {"stars": 250, "days": 90, "label": "3 месяца — 250 ⭐"},
    "1year": {"stars": 500, "days": 365, "label": "1 год — 500 ⭐"},
}

TRIAL_DAYS: int = 7
TRIAL_GB: int = 1
