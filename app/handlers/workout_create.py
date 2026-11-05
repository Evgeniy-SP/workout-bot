"""Создание нового типа тренировки."""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, WorkoutType
from app.keyboards.workout_kb import cancel_kb, workout_card_kb, workout_description_kb
from app.render import render_workout_card
from app.states import WorkoutCreate

router = Router()


async def _get_user(session: AsyncSession, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


@router.callback_query(F.data == "wt_new")
async def new_workout_start(callback: CallbackQuery, state: FSMContext):
    await state.update_data(return_to="wt_list")
    await state.set_state(WorkoutCreate.adding_type_name)
    await callback.message.edit_text(
        "➕ Введи название новой тренировки:",
        reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(WorkoutCreate.adding_type_name)
async def new_workout_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name or len(name) > 64:
        return await message.answer(
            "Название 1–64 символа. Попробуй ещё:",
            reply_markup=cancel_kb()
        )

    await state.update_data(type_name=name)
    await state.set_state(WorkoutCreate.adding_type_description)
    await message.answer(
        "Добавь описание тренировки (например, «день ног и плеч») — оно будет видно в карточке:",
        reply_markup=workout_description_kb()
    )


@router.message(WorkoutCreate.adding_type_description)
async def new_workout_description(message: Message, state: FSMContext, session: AsyncSession):
    text = message.text.strip()
    # Оставляем поддержку дефиса на всякий случай, но основной способ — кнопка
    description = None if text in {"-", "—"} else text[:500]
    await _finish_creation(message, state, session, message.from_user.id, description)


@router.callback_query(F.data == "wt_desc_skip", WorkoutCreate.adding_type_description)
async def cb_skip_description(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    # Просто вызываем функцию сохранения с description=None
    await _finish_creation(callback.message, state, session, callback.from_user.id, None)
    await callback.answer()


@router.callback_query(F.data == "wt_desc_back",
                       WorkoutCreate.adding_type_description)
async def cb_desc_back(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу названия тренировки."""
    data = await state.get_data()
    old_name = data.get("type_name", "")

    await state.set_state(WorkoutCreate.adding_type_name)
    await callback.message.edit_text(
        f"➕ Введи название новой тренировки:\n\n"
        f"<i>Прошлое название (нажми на него, чтобы скопировать):</i>\n"
        f"<b><code>{old_name}</code></b>"
    )
    await callback.answer()


async def _finish_creation(message: Message, state: FSMContext, session: AsyncSession, user_id: int, description: str | None):
    """Общая логика сохранения тренировки (для текста и для кнопки Пропустить)."""
    data = await state.get_data()
    name = data.get("type_name", "Без названия")

    user = await _get_user(session, user_id)
    if not user:
        await state.clear()
        return await message.answer("Сначала /start")

    result = await session.execute(
        select(WorkoutType.sort_order).where(WorkoutType.user_id == user.id)
    )
    max_order = max((r[0] for r in result.all()), default=-1)

    wt = WorkoutType(
        user_id=user.id,
        name=name,
        description=description,
        sort_order=max_order + 1,
    )
    session.add(wt)
    await session.commit()
    await session.refresh(wt)

    await state.clear()
    await message.answer(
        "✅ Тренировка создана. Открой «Упражнения», чтобы добавить в неё упражнения:\n\n"
        + render_workout_card(wt),
        reply_markup=workout_card_kb(wt)
    )
