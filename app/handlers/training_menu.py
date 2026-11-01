"""Хэндлеры навигации: старт тренировки, список упражнений, открытие упражнения."""
from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkoutSession, WorkoutType
from app.db.queries import get_active_session
from app.keyboards.workout_kb import exercises_list_kb, workouts_list_kb
from app.services.training_service import (
    get_user, load_workout, render_approach_screen, render_list,
)

router = Router()


@router.callback_query(F.data.startswith("tr_start:"))
async def cb_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    wt_id = int(callback.data.split(":")[1])
    user = await get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await load_workout(session, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    # Проверка: в тренировке есть упражнения?
    if not wt.exercises:
        await callback.message.edit_text(
            "⚠️ <b>В тренировке нет упражнений!</b>\n\n"
            "Чтобы начать тренировку, сначала добавь в неё хотя бы одно упражнение.\n\n"
            "📋 Упражнения — <b>" + wt.name + "</b>",
            reply_markup=exercises_list_kb(wt.exercises, wt.id)
        )
        return await callback.answer("Список упражнений пуст", show_alert=True)

    # Проверка: нет ли уже активной тренировки?
    active = await get_active_session(session, user.id)
    if active:
        result = await session.execute(
            select(WorkoutType)
            .where(WorkoutType.user_id == user.id, WorkoutType.is_archived == False)
            .order_by(WorkoutType.sort_order)
        )
        workouts = list(result.scalars())

        await callback.message.edit_text(
            "⚠️ У тебя уже есть активная тренировка.\n\n"
            "Заверши её или продолжи с кнопки ▶️ на нужной тренировке.",
            reply_markup=workouts_list_kb(workouts, active_wt_id=active.workout_type_id),
        )
        return await callback.answer(
            "Сначала заверши активную тренировку", show_alert=True
        )

    # Создаём сессию
    ws = WorkoutSession(
        user_id=user.id,
        workout_type_id=wt_id,
        started_at=datetime.now(timezone.utc),
    )
    session.add(ws)
    await session.commit()
    await session.refresh(ws)

    text, kb = await render_list(session, ws.id, user.id)
    await callback.message.edit_text(
        "▶️ Тренировка начата!\n\n" + text, reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tr_list:"))
async def cb_list(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    session_id = int(callback.data.split(":")[1])
    ws = await session.get(WorkoutSession, session_id)
    if not ws:
        return await callback.answer("Не найдено", show_alert=True)

    text, kb = await render_list(session, session_id, ws.user_id)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("tr_ex:"))
async def cb_open_exercise(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    _, sess_str, ex_str = callback.data.split(":")
    session_id = int(sess_str)
    ex_id = int(ex_str)

    result = await render_approach_screen(session, session_id, ex_id)
    if result is None:
        ws = await session.get(WorkoutSession, session_id)
        if not ws:
            return await callback.answer("Недоступно", show_alert=True)
        text, kb = await render_list(session, session_id, ws.user_id)
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()
        return

    text, kb = result
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()
