import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config
import db
from handlers import admin, chat
from scheduler import scheduler


async def main():
    logging.basicConfig(level=logging.INFO)
    db.init(config.DB_PATH)
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_routers(admin.reg_router, admin.router, chat.router)
    task = asyncio.create_task(scheduler(bot))  # ссылка нужна, иначе задачу соберёт GC
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
