"""Хэндлеры: /start, /help, /done."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.workout_kb import main_reply_kb
from app.db.models import User

router = Router()


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
            "Нажми кнопку внизу, чтобы начать",
            reply_markup=main_reply_kb()
        )
    else:
        user.username = tg.username
        user.full_name = tg.full_name
        await session.commit()
        await message.answer(
            f"С возвращением, <b>{tg.full_name}</b>!",
            reply_markup=main_reply_kb()
        )


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message) -> None:
    await message.answer(
        "📖 <b>Как пользоваться ботом:</b>\n\n"
        "1️⃣ Нажми <b>«🏋️ Тренировки»</b> внизу, чтобы открыть меню.\n"
        "2️⃣ Выбери нужную тренировку и нажми <b>«▶️ Начать»</b>.\n"
        "3️⃣ Записывай подходы, используй таймеры и оставляй заметки.\n"
        "4️⃣ В конце нажми <b>«🏁 Завершить тренировку»</b>.\n\n"
        "<i>💡 Если бот ждет ввода текста, ты всегда можешь нажать кнопку «❌ Отмена» или написать /cancel.</i>"
    )
