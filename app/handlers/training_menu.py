"""Хэндлеры навигации: старт тренировки, список упражнений, открытие упражнения."""

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkoutSession
from app.db.queries import get_active_session
from app.services.training_service import (
    get_user, load_workout, render_approach_screen, render_list,
)

router = Router()


@router.callback_query(F.data.startswith("tr_start:"))
async def cb_start(callback: CallbackQuery, session: AsyncSession,
                   state: FSMContext):
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
        from app.keyboards.workout_kb import exercises_list_kb
        try:
            await callback.message.edit_text(
                "⚠️ <b>В тренировке нет упражнений!</b>\n\n"
                "Чтобы начать тренировку, сначала добавь в неё хотя бы одно упражнение.\n\n"
                "📋 Упражнения — <b>" + wt.name + "</b>",
                reply_markup=exercises_list_kb(wt.exercises, wt.id)
            )
        except Exception:
            pass
        return await callback.answer("Список упражнений пуст", show_alert=True)

    # Проверка: нет ли уже активной тренировки?
    active = await get_active_session(session, user.id)
    if active:
        from app.keyboards.workout_kb import workouts_list_kb
        from app.handlers.workout_view import _get_sorted_workouts

        workouts, new_ids = await _get_sorted_workouts(session, user.id)
        try:
            await callback.message.edit_text(
                "⚠️ У тебя уже есть активная тренировка.\n\n"
                "Заверши её или продолжи с кнопки ▶️ на нужной тренировке.",
                reply_markup=workouts_list_kb(workouts,
                                              active_wt_id=active.workout_type_id,
                                              new_wt_ids=new_ids),
            )
        except Exception:
            pass
        return await callback.answer("Сначала заверши активную тренировку",
                                     show_alert=True)

    # Создаём сессию
    from datetime import datetime, timezone
    ws = WorkoutSession(
        user_id=user.id,
        workout_type_id=wt_id,
        started_at=datetime.now(timezone.utc),
    )
    session.add(ws)
    await session.commit()
    await session.refresh(ws)

    text, kb = await render_list(session, ws.id, user.id)
    try:
        await callback.message.edit_text(
            "▶️ Тренировка начата!\n\n" + text, reply_markup=kb
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("tr_list:"))
async def cb_list(callback: CallbackQuery, session: AsyncSession,
                  state: FSMContext):
    await state.clear()
    session_id = int(callback.data.split(":")[1])
    ws = await session.get(WorkoutSession, session_id)
    if not ws:
        return await callback.answer("Не найдено", show_alert=True)

    text, kb = await render_list(session, session_id, ws.user_id)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("tr_ex:"))
async def cb_open_exercise(callback: CallbackQuery, session: AsyncSession,
                           state: FSMContext):
    await state.clear()
    _, sess_str, ex_str = callback.data.split(":")
    session_id = int(sess_str)
    ex_id = int(ex_str)

    ws = await session.get(WorkoutSession, session_id)

    # ЗАЩИТА ОТ СТАРЫХ КНОПОК
    if not ws:
        return await callback.answer("Тренировка не найдена", show_alert=True)
    if ws.finished_at:
        return await callback.answer("Эта тренировка уже завершена",
                                     show_alert=True)

    result = await render_approach_screen(session, session_id, ex_id)
    if result is None:
        text, kb = await render_list(session, session_id, ws.user_id)
        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
        await callback.answer()
        return

    text, kb = result
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass

    await callback.answer()


@router.callback_query(F.data.startswith("tr_opt_list:"))
async def cb_optional_list(callback: CallbackQuery, session: AsyncSession,
                           state: FSMContext):
    await state.clear()
    session_id = int(callback.data.split(":")[1])
    ws = await session.get(WorkoutSession, session_id)
    if not ws:
        return await callback.answer("Не найдено", show_alert=True)

    from app.services.training_service import render_optional_list
    text, kb = await render_optional_list(session, session_id, ws.user_id)

    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass  # Если ничего не изменилось - просто игнорируем ошибку

    await callback.answer("Статусы обновлены")
