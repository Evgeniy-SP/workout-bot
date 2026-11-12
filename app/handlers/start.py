"""Хэндлеры: /start, /help, /done."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.workout_kb import main_reply_kb, start_inline_kb
from app.db.models import User

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession,
                    state: FSMContext) -> None:
    await state.clear()
    tg = message.from_user
    result = await session.execute(select(User).where(User.tg_id == tg.id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(tg_id=tg.id, username=tg.username, full_name=tg.full_name)
        session.add(user)
        await session.flush()
        await session.commit()

        # 1. Отправляем приветствие с нижней кнопкой
        await message.answer(
            f"👋 Привет, <b>{tg.full_name}</b>!\n\n"
            "Добро пожаловать в твой личный дневник тренировок! 🏋️‍♂️\n\n"
            "Здесь ты можешь планировать программы, записывать подходы и следить за прогрессом.\n\n"
            "📊 Твоя история тренировок всегда под рукой — нажми <b>«📊 История»</b> внизу экрана, чтобы посмотреть прошлые результаты!\n\n"
            "🏠 Для создания или запуска тренировок используй кнопку <b>«🏠 Главная»</b>."
            ,
            reply_markup=main_reply_kb()
        )
    else:
        user.username = tg.username
        user.full_name = tg.full_name
        await session.commit()

        await message.answer(
            f"С возвращением, <b>{tg.full_name}</b>!"
            "Добро пожаловать в твой личный дневник тренировок! 🏋️‍♂️\n\n"
            "📊 Твоя история тренировок всегда под рукой — нажми <b>«📊 История»</b> внизу экрана, чтобы посмотреть прошлые результаты!\n\n"
            "🏠 Для создания или запуска тренировок используй кнопку <b>«🏠 Главная»</b>."
            ,
            reply_markup=main_reply_kb()
        )

    # 2. Отправляем второе сообщение с inline-кнопкой "Справка"
    await message.answer(
        "💡 Если что-то забыл, вот шпаргалка:",
        reply_markup=start_inline_kb()
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "📖 <b>Как пользоваться ботом:</b>\n\n"
        "1️⃣ Нажми <b>«🏠 Главная»</b> внизу, чтобы открыть меню.\n" 
        "2️⃣ Выбери нужную тренировку и нажми <b>«▶️ Начать»</b>.\n"
        "3️⃣ Записывай подходы, используй таймеры и оставляй заметки.\n"
        "4️⃣ В конце нажми <b>«🏁 Завершить тренировку»</b>.\n\n"
        "<i>💡 Если бот ждет ввода текста, ты всегда можешь нажать кнопку «❌ Отмена» или написать /cancel.</i>"
    )


@router.callback_query(F.data == "show_help")
async def cb_show_help(callback: CallbackQuery):
    # Вызываем функцию справки (передаем сообщение)
    await cmd_help(callback.message)
    await callback.answer()
