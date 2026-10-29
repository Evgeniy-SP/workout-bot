"""Точка входа. Запускает бота: python bot.py"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import settings
from app.db.session import init_db
from app.handlers import (exercise_create, exercise_edit, start, training,
                          workout_create, workout_menu
                          )
from app.middlewares.db import DbSessionMiddleware

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.update.middleware(DbSessionMiddleware())
    # Порядок роутеров важен: общие команды → навигация → FSM-редактирование
    dp.include_routers(
        start.router,
        exercise_edit.router,
        training.router,
        workout_menu.router,
        workout_create.router,
        exercise_create.router,
    )

    logging.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
