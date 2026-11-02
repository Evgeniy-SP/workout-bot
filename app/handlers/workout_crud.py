"""Хэндлеры для удаления, архивации и настройки тренировок/упражнений."""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Exercise, SessionExerciseNote, SessionSet, \
    WorkoutSession, WorkoutType
from app.keyboards.workout_kb import (
    confirm_delete_kb, confirm_workout_delete_kb, exercise_card_kb,
    exercises_list_kb, workouts_list_kb,
)
from app.render import render_exercise_card
from app.services.training_service import get_user, load_workout_with_exercises
from app.utils import fmt_msk_date

router = Router()


# ═══════════════════════════════════════════════════════════
#  Удаление / архивация УПРАЖНЕНИЯ
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ex_del:"))
async def cb_delete_ask(callback: CallbackQuery, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    history_count = await session.scalar(
        select(func.count(func.distinct(SessionSet.session_id)))
        .select_from(SessionSet)
        .where(SessionSet.exercise_id == ex_id)
    ) or 0

    if history_count > 0:
        text = (
            f"Убрать упражнение <b>{ex.name}</b> из шаблона?\n\n"
            f"Упражнение выполнялось в <b>{history_count}</b> "
            f"тренировк{'е' if history_count == 1 else 'ах'} — история сохранится.\n\n"
            "📦 Упражнение скроется из шаблона."
        )
    else:
        text = (
            f"Удалить упражнение <b>{ex.name}</b>?\n\n"
            "Истории нет — удалится полностью."
        )

    await callback.message.edit_text(
        text,
        reply_markup=confirm_delete_kb(ex.id, has_history=(history_count > 0))
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ex_del_yes:"))
async def cb_delete_confirm(callback: CallbackQuery, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)
    wt_id = ex.workout_type_id

    history_count = await session.scalar(
        select(func.count(func.distinct(SessionSet.session_id)))
        .select_from(SessionSet)
        .where(SessionSet.exercise_id == ex_id)
    ) or 0

    if history_count > 0:
        ex.is_archived = True
        await session.commit()
        action = "📦 Упражнение скрыто из шаблона. История сохранена."
    else:
        await session.delete(ex)
        await session.commit()
        action = "🗑 Упражнение удалено."

    wt = await load_workout_with_exercises(session, wt_id)
    if wt:
        await callback.message.edit_text(
            f"{action}\n\n📋 Упражнения — <b>{wt.name}</b>",
            reply_markup=exercises_list_kb(wt.exercises, wt.id),
        )
    await callback.answer("Готово")


@router.callback_query(F.data.startswith("ex_toggle_opt:"))
async def cb_ex_toggle_opt(callback: CallbackQuery, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    ex.is_optional = not ex.is_optional
    await session.commit()

    await callback.message.edit_text(
        render_exercise_card(ex), reply_markup=exercise_card_kb(ex)
    )
    await callback.answer("Обновлено")


# ═══════════════════════════════════════════════════════════
#  Удаление / архивация ТРЕНИРОВКИ
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("wt_del:"))
async def cb_workout_delete_ask(callback: CallbackQuery,
                                session: AsyncSession):
    wt_id = int(callback.data.split(":")[1])
    user = await get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await session.get(WorkoutType, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    sessions_count = await session.scalar(
        select(func.count())
        .select_from(WorkoutSession)
        .where(WorkoutSession.workout_type_id == wt_id)
    ) or 0

    if sessions_count > 0:
        text = (
            f"Удалить тренировку <b>{wt.name}</b>?\n\n"
            f"У этой тренировки есть история — <b>{sessions_count}</b> "
            f"записей о выполнении.\n\n"
            "📦 <b>Архивировать</b> — тренировка скроется из списка, "
            "но история сохранится.\n\n"
            "🔥 <b>Удалить со всей историей</b> — исчезнет всё."
        )
    else:
        text = (
            f"Удалить тренировку <b>{wt.name}</b>?\n\n"
            "Все упражнения в ней будут удалены. "
            "Истории выполнения нет — терять нечего."
        )

    await callback.message.edit_text(
        text, reply_markup=confirm_workout_delete_kb(wt_id, sessions_count > 0)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("wt_del_yes:"))
async def cb_workout_delete_confirm(callback: CallbackQuery,
                                    session: AsyncSession):
    wt_id = int(callback.data.split(":")[1])
    user = await get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await session.get(WorkoutType, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    result = await session.execute(
        select(Exercise.id).where(Exercise.workout_type_id == wt_id))
    ex_ids = list(result.scalars())

    if ex_ids:
        await session.execute(
            delete(SessionSet).where(SessionSet.exercise_id.in_(ex_ids)))
        await session.execute(delete(SessionExerciseNote).where(
            SessionExerciseNote.exercise_id.in_(ex_ids)))

    await session.execute(
        delete(WorkoutSession).where(WorkoutSession.workout_type_id == wt_id))
    await session.delete(wt)
    await session.commit()

    result = await session.execute(
        select(WorkoutType)
        .where(WorkoutType.user_id == user.id,
               WorkoutType.is_archived == False)
        .order_by(WorkoutType.sort_order)
    )
    workouts = list(result.scalars())

    if not workouts:
        await callback.message.edit_text(
            "🗑 Тренировка удалена вместе с историей.\n\n"
            "У тебя больше нет активных тренировок."
        )
    else:
        await callback.message.edit_text(
            "🗑 Тренировка удалена вместе с историей.\n\n"
            "🏋️ Выбери тренировку:",
            reply_markup=workouts_list_kb(workouts),
        )
    await callback.answer("Удалено")


@router.callback_query(F.data.startswith("wt_del_no:"))
async def cb_workout_delete_cancel(callback: CallbackQuery,
                                   session: AsyncSession):
    wt_id = int(callback.data.split(":")[1])
    wt = await session.get(WorkoutType, wt_id)
    if not wt:
        return await callback.answer("Не найдено", show_alert=True)

    from app.keyboards.workout_kb import workout_card_kb
    from app.render import render_workout_card

    await callback.message.edit_text(
        render_workout_card(wt), reply_markup=workout_card_kb(wt)
    )
    await callback.answer("Отменено")


@router.callback_query(F.data.startswith("wt_archive:"))
async def cb_workout_archive(callback: CallbackQuery, session: AsyncSession):
    wt_id = int(callback.data.split(":")[1])
    user = await get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await session.get(WorkoutType, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    wt.is_archived = True
    await session.commit()

    active_session = await session.scalar(
        select(WorkoutSession).where(
            WorkoutSession.workout_type_id == wt_id,
            WorkoutSession.finished_at.is_(None)
        )
    )
    if active_session:
        await session.delete(active_session)
        await session.commit()

    result = await session.execute(
        select(WorkoutType)
        .where(WorkoutType.user_id == user.id,
               WorkoutType.is_archived == False)
        .order_by(WorkoutType.sort_order)
    )
    workouts = list(result.scalars())

    if not workouts:
        await callback.message.edit_text(
            "📦 Тренировка в архиве. История сохранена.\n\n"
            "У тебя больше нет активных тренировок."
        )
    else:
        await callback.message.edit_text(
            "📦 Тренировка в архиве. История сохранена.\n\n"
            "🏋️ Выбери тренировку:",
            reply_markup=workouts_list_kb(workouts),
        )
    await callback.answer("Архивировано")


@router.callback_query(F.data.startswith("wt_toggle_rot:"))
async def cb_toggle_rotation(callback: CallbackQuery, session: AsyncSession):
    wt_id = int(callback.data.split(":")[1])
    wt = await session.get(WorkoutType, wt_id)
    if not wt:
        return await callback.answer("Не найдено", show_alert=True)

    wt.is_in_rotation = not wt.is_in_rotation
    await session.commit()

    from app.keyboards.workout_kb import workout_card_kb
    from app.render import render_workout_card

    await callback.message.edit_text(
        render_workout_card(wt),
        reply_markup=workout_card_kb(wt)
    )
    await callback.answer("Обновлено")
