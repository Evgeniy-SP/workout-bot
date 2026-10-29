"""Хэндлеры: /start, /help, /done."""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, WorkoutType
from app.db.seed import create_default_workout

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()  # на случай, если пользователь застрял в FSM
    tg = message.from_user
    result = await session.execute(select(User).where(User.tg_id == tg.id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(tg_id=tg.id, username=tg.username, full_name=tg.full_name)
        session.add(user)
        await session.flush()
        await create_default_workout(session, user)
        await session.commit()
        await message.answer(
            f"👋 Привет, <b>{tg.full_name}</b>!\n\n"
            "Я создал твою первую тренировку <b>«Ноги и плечи»</b>.\n\n"
            "• /workout — меню тренировок\n"
            "• /done — отметить выполненной"
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
