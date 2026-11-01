"""Сервис навигации для возврата пользователя на нужный экран при отмене."""
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Exercise, User, WorkoutSession, WorkoutType
from app.keyboards.workout_kb import (
    exercise_card_kb, exercises_list_kb, workout_card_kb, workouts_list_kb,
)
from app.render import render_exercise_card, render_workout_card
from app.services.training_service import (
    load_workout_with_exercises, render_approach_screen, render_list,
)


async def resolve_cancel_view(
    state: FSMContext, session: AsyncSession, user_tg_id: int
) -> tuple[str, InlineKeyboardMarkup | None] | None:
    """Возвращает (текст, клавиатура) для возврата при отмене, либо None."""
    if await state.get_state() is None:
        return None

    data = await state.get_data()
    return_to = data.get("return_to")
    await state.clear()

    # 1. Подход в активной тренировке
    if return_to in ("tr_ex_card", "tr_strength_summary") and "ex_id" in data and "session_id" in data:
        result = await render_approach_screen(session, data["session_id"], data["ex_id"])
        if result:
            return "❌ Отменено.\n\n" + result[0], result[1]
        ws = await session.get(WorkoutSession, data["session_id"])
        if ws:
            text, kb = await render_list(session, data["session_id"], ws.user_id)
            return "❌ Отменено.\n\n" + text, kb
        return "❌ Отменено.", None

    # 2. Карточка упражнения
    if return_to == "ex_card" and "ex_id" in data:
        ex = await session.get(Exercise, data["ex_id"])
        if ex:
            return "❌ Отменено.\n\n" + render_exercise_card(ex), exercise_card_kb(ex)
        return "❌ Отменено.", None

    # 3. Список упражнений
    if return_to == "ex_list" and "wt_id" in data:
        wt = await load_workout_with_exercises(session, data["wt_id"])
        if wt:
            return (
                f"❌ Отменено.\n\n📋 Упражнения — <b>{wt.name}</b>",
                exercises_list_kb(wt.exercises, wt.id),
            )
        return "❌ Отменено.", None

    # 4. Экран активной тренировки
    if return_to == "tr_list" and "return_to_session" in data:
        session_id = data["return_to_session"]
        ws = await session.get(WorkoutSession, session_id)
        if ws:
            text, kb = await render_list(session, session_id, ws.user_id)
            return "❌ Отменено.\n\n" + text, kb
        return "❌ Отменено.", None

    # 5. Карточка тренировки
    if return_to == "wt_card" and "wt_id" in data:
        wt = await session.get(WorkoutType, data["wt_id"])
        if wt:
            return "❌ Отменено.\n\n" + render_workout_card(wt), workout_card_kb(wt.id)
        return "❌ Отменено.", None

    # 6. Список тренировок
    if return_to == "wt_list":
        user = (await session.execute(
            select(User).where(User.tg_id == user_tg_id)
        )).scalar_one_or_none()
        if user:
            workouts = list((await session.execute(
                select(WorkoutType)
                .where(WorkoutType.user_id == user.id, WorkoutType.is_archived == False)
                .order_by(WorkoutType.sort_order)
            )).scalars())
            if workouts:
                return "❌ Отменено.\n\n🏋️ Выбери тренировку:", workouts_list_kb(workouts)
        return "❌ Отменено.", None

    return "❌ Отменено.", None
