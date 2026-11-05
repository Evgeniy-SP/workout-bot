"""Навигация и просмотр тренировок и упражнений."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Exercise
from app.db.queries import get_active_session
from app.keyboards.workout_kb import (
    exercise_card_kb, exercises_list_kb, workout_card_kb, workouts_list_kb,
)
from app.render import render_exercise_card, render_workout_card
from app.services.training_service import (
    get_user, load_workout_with_exercises, load_workout,
)

router = Router()


@router.message(Command("workout"))
@router.message(F.text == "🏠 Главная")
async def cmd_workout(message: Message, session: AsyncSession,
                      state: FSMContext):
    await state.clear()
    user = await get_user(session, message.from_user.id)
    if not user:
        return await message.answer("Сначала нажми /start")

    workouts, new_wt_ids = await _get_sorted_workouts(session, user.id)

    if not workouts:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Новая тренировка", callback_data="wt_new")
        return await message.answer(
            "У тебя пока нет тренировок.\nДавай создадим первую!",
            reply_markup=kb.as_markup()
        )

    active = await get_active_session(session, user.id)
    active_wt_id = active.workout_type_id if active else None

    await message.answer(
        "🏋️ <b>Выбери тренировку:</b>\n\n",
        reply_markup=workouts_list_kb(workouts, active_wt_id=active_wt_id, new_wt_ids=new_wt_ids),
    )


@router.callback_query(F.data == "wt_list")
async def cb_workouts_list(callback: CallbackQuery, session: AsyncSession,
                           state: FSMContext):
    await state.clear()
    user = await get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    workouts, new_wt_ids = await _get_sorted_workouts(session, user.id)

    active = await get_active_session(session, user.id)
    active_wt_id = active.workout_type_id if active else None

    await callback.message.edit_text(
        "🏋️ <b>Выбери тренировку:</b>\n\n",
        reply_markup=workouts_list_kb(workouts, active_wt_id=active_wt_id, new_wt_ids=new_wt_ids),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("wt:"))
async def cb_workout_card(callback: CallbackQuery, session: AsyncSession,
                          state: FSMContext):
    await state.clear()
    wt_id = int(callback.data.split(":")[1])
    user = await get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await load_workout(session, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    active = await get_active_session(session, user.id)
    active_session_id = active.id if (
                active and active.workout_type_id == wt_id) else None

    await callback.message.edit_text(
        render_workout_card(wt),
        reply_markup=workout_card_kb(wt, active_session_id=active_session_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("wt_ex:"))
async def cb_exercises_list(callback: CallbackQuery, session: AsyncSession,
                            state: FSMContext):
    await state.clear()
    wt_id = int(callback.data.split(":")[1])
    user = await get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await load_workout_with_exercises(session, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    await callback.message.edit_text(
        f"📋 Упражнения — <b>{wt.name}</b>\n\n"
        "<i>💡 Нажми на упражнение, чтобы отредактировать или убрать</i>",
        reply_markup=exercises_list_kb(wt.exercises, wt.id),
    )
    await callback.answer()


# Вспомогательная функция (БЕЗ декораторов @router)
async def _render_card(session: AsyncSession, ex: Exercise, msg):
    """Вспомогательная функция для отрисовки карточки с позицией."""
    result = await session.execute(
        select(Exercise.id)
        .where(Exercise.workout_type_id == ex.workout_type_id,
               Exercise.is_archived == False)
        .order_by(Exercise.sort_order)
    )
    ids = list(result.scalars())

    text = render_exercise_card(ex)
    if ex.id in ids:
        text += f"\n\n📌 <i>Позиция: {ids.index(ex.id) + 1} из {len(ids)}</i>"

    await msg.edit_text(text, reply_markup=exercise_card_kb(ex))


# Обработчик кнопки (декоратор ЗДЕСЬ)
@router.callback_query(F.data.startswith("ex:"))
async def cb_exercise_card(callback: CallbackQuery, session: AsyncSession,
                           state: FSMContext):
    await state.clear()
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    await _render_card(session, ex, callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith("ex_move_up:"))
async def cb_ex_move_up(callback: CallbackQuery, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    result = await session.execute(
        select(Exercise)
        .where(Exercise.workout_type_id == ex.workout_type_id,
               Exercise.is_archived == False)
        .order_by(Exercise.sort_order, Exercise.id)
    )
    exercises = list(result.scalars())

    try:
        idx = exercises.index(ex)
    except ValueError:
        return await callback.answer("Ошибка", show_alert=True)

    if idx == 0:
        return await callback.answer("Упражнение уже первое", show_alert=True)

    exercises[idx], exercises[idx - 1] = exercises[idx - 1], exercises[idx]

    for i, e in enumerate(exercises):
        e.sort_order = i
    await session.commit()

    await _render_card(session, ex, callback.message)
    await callback.answer("Перемещено вверх ⬆️")


@router.callback_query(F.data.startswith("ex_move_down:"))
async def cb_ex_move_down(callback: CallbackQuery, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    result = await session.execute(
        select(Exercise)
        .where(Exercise.workout_type_id == ex.workout_type_id,
               Exercise.is_archived == False)
        .order_by(Exercise.sort_order, Exercise.id)
    )
    exercises = list(result.scalars())

    try:
        idx = exercises.index(ex)
    except ValueError:
        return await callback.answer("Ошибка", show_alert=True)

    if idx == len(exercises) - 1:
        return await callback.answer("Упражнение уже последнее",
                                     show_alert=True)

    exercises[idx], exercises[idx + 1] = exercises[idx + 1], exercises[idx]

    for i, e in enumerate(exercises):
        e.sort_order = i
    await session.commit()

    await _render_card(session, ex, callback.message)
    await callback.answer("Перемещено вниз ⬇️")


from sqlalchemy import select, func
from app.db.models import WorkoutType, WorkoutSession


async def _get_sorted_workouts(session: AsyncSession, user_id: int) -> tuple[
    list[WorkoutType], set[int]]:
    # 1. Получаем все активные тренировки
    result = await session.execute(
        select(WorkoutType)
        .where(WorkoutType.user_id == user_id,
               WorkoutType.is_archived == False)
    )
    workouts = list(result.scalars())

    # 2. Получаем даты последних выполнений для каждой
    dates_result = await session.execute(
        select(WorkoutSession.workout_type_id,
               func.max(WorkoutSession.started_at))
        .where(WorkoutSession.user_id == user_id)
        .group_by(WorkoutSession.workout_type_id)
    )
    last_dates = dict(dates_result.all())  # {wt_id: last_date}

    # 3. Делим на две группы
    in_rotation = [w for w in workouts if w.is_in_rotation]
    others = [w for w in workouts if not w.is_in_rotation]

    # 4. Сортируем группу "В ротации"
    from datetime import datetime, timezone
    min_date = datetime.min.replace(tzinfo=timezone.utc)

    in_rotation.sort(key=lambda w: last_dates.get(w.id, min_date))

    # 5. Остальные сортируем по sort_order
    others.sort(key=lambda w: w.sort_order)

    # 6. Собираем ID новых тренировок (у которых нет истории)
    new_wt_ids = {w.id for w in workouts if w.id not in last_dates}

    return in_rotation + others, new_wt_ids
