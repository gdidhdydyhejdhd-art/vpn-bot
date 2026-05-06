import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram import F

from config import BOT_TOKEN, ADMIN_ID
from database import init_db, get_user, create_user, add_referral
from handlers import start, buy, trial, profile, admin
from handlers import referral as referral_handler
from handlers import subscription as subscription_handler
from middlewares import ChannelSubscriptionMiddleware
from reminders import reminder_loop
import xui_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def probe_xui(bot: Bot):
    await asyncio.sleep(1)
    inbounds = await xui_api.get_inbounds()
    if inbounds:
        logger.info(f"x-ui probe OK: {len(inbounds)} inbounds, path={xui_api._working_inbounds_path}")
        try:
            await bot.send_message(
                ADMIN_ID,
                f"✅ <b>Бот запущен</b>\n"
                f"🔌 x-ui подключён\n"
                f"📡 Инбаундов: <b>{len(inbounds)}</b>\n"
                f"🛣 API путь: <code>{xui_api._working_inbounds_path}</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass
    else:
        logger.error("x-ui probe FAILED")
        try:
            await bot.send_message(ADMIN_ID, "⚠️ <b>Бот запущен, но x-ui не отвечает!</b>", parse_mode="HTML")
        except Exception:
            pass


async def main():
    logger.info("Starting VPN bot...")
    await init_db()
    logger.info("Database initialized")

    logged_in = await xui_api.login()
    if not logged_in:
        logger.warning("x-ui login failed on startup — will retry later")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # ── /start with referral parameter ───────────────────────────────────────
    @dp.message(CommandStart(deep_link=True))
    async def cmd_start_with_ref(message: Message):
        args = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""
        tg_id = message.from_user.id

        referrer_id: int | None = None
        if args.startswith("ref_"):
            try:
                referrer_id = int(args[4:])
                if referrer_id == tg_id:
                    referrer_id = None
            except ValueError:
                referrer_id = None

        user = await get_user(tg_id)
        if not user:
            user = await create_user(
                tg_id,
                message.from_user.username,
                message.from_user.first_name or "",
                referred_by=referrer_id,
            )
            if referrer_id:
                await add_referral(referrer_id, tg_id)

        from keyboards import main_menu
        name = message.from_user.first_name or "друг"

        if referrer_id and user.get("referred_by") is None:
            await message.answer(
                f"👋 Привет, <b>{name}</b>!\n\n"
                f"Ты пришёл по реферальной ссылке 🎉\n"
                f"Когда ты совершишь первую покупку, твой друг получит бонус!\n\n"
                f"Выбери действие:",
                reply_markup=main_menu(tg_id),
                parse_mode="HTML",
            )
        else:
            await message.answer(
                f"👋 Привет, <b>{name}</b>! Выбери действие:",
                reply_markup=main_menu(tg_id),
                parse_mode="HTML",
            )

    # ── Middleware ────────────────────────────────────────────────────────────
    dp.message.middleware(ChannelSubscriptionMiddleware())
    dp.callback_query.middleware(ChannelSubscriptionMiddleware())

    # ── Routers ───────────────────────────────────────────────────────────────
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(buy.router)
    dp.include_router(trial.router)
    dp.include_router(profile.router)
    dp.include_router(subscription_handler.router)
    dp.include_router(referral_handler.router)

    async def on_startup():
        await probe_xui(bot)
        asyncio.create_task(reminder_loop(bot))

    asyncio.create_task(on_startup())

    logger.info("Bot polling started")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
