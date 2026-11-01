"""Хэндлеры: /start, /help, /done."""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, WorkoutType

router = Router()


# Импорт create_default_workout можно убрать, если он больше нигде не нужен
# from app.db.seed import create_default_workout


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    tg = message.from_user
    result = await session.execute(select(User).where(User.tg_id == tg.id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(tg_id=tg.id, username=tg.username, full_name=tg.full_name)
        session.add(user)
        await session.flush()
        await session.commit()  # <--- Здесь больше нет вызова create_default_workout
        await message.answer(
            f"👋 Привет, <b>{tg.full_name}</b>!\n\n"
            "Добро пожаловать в бот для тренировок!\n\n"
            "У тебя пока нет созданных тренировок. "
            "Нажми /workout, чтобы создать свою первую программу."
        )
    else:
        user.username = tg.username
        user.full_name = tg.full_name
        await session.commit()
        await message.answer(f"С возвращением, <b>{tg.full_name}</b>! /workout — тренировки.")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "📖 <b>Команды:</b>\n\n"
        "/start — регистрация / приветствие\n"
        "/help — эта справка\n"
        "/workout — меню тренировок и упражнений\n"
        "/cancel — отменить текущий диалог ввода\n"
    )
