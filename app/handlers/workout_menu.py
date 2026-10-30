"""Навигация по тренировкам и упражнениям через inline-кнопки."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Exercise, SessionSet, User, WorkoutSession, WorkoutType
from app.keyboards.workout_kb import (
    confirm_delete_kb,
    confirm_workout_delete_kb,
    exercise_card_kb,
    exercises_list_kb,
    workout_card_kb,
    workouts_list_kb,
)
from app.render import render_exercise_card, render_workout_card

router = Router()


# ─────────────── helpers ───────────────

async def _get_user(session: AsyncSession, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


async def _load_workout_with_exercises(session: AsyncSession, wt_id: int):
    """Загружаем тренировку с НЕархивными упражнениями (см. комментарий в training.py)."""
    from app.db.models import Exercise  # локально

    result = await session.execute(
        select(WorkoutType)
        .where(WorkoutType.id == wt_id)
        .options(
            selectinload(WorkoutType.exercises.and_(Exercise.is_archived.is_(False)))
        )
    )
    return result.scalar_one_or_none()


# ─────────────── /workout — список активных тренировок ───────────────

@router.message(Command("workout"))
async def cmd_workout(message: Message, session: AsyncSession, state: FSMContext):
    await state.clear()
    user = await _get_user(session, message.from_user.id)
    if not user:
        return await message.answer("Сначала нажми /start")

    result = await session.execute(
        select(WorkoutType)
        .where(WorkoutType.user_id == user.id, WorkoutType.is_archived == False)
        .order_by(WorkoutType.sort_order)
    )
    workouts = list(result.scalars())
    if not workouts:
        return await message.answer(
            "У тебя нет активных тренировок.\n"
            "Создай новую: /workout → «➕ Новая тренировка»"
        )

    from app.db.queries import get_active_session
    active = await get_active_session(session, user.id)
    active_wt_id = active.workout_type_id if active else None

    await message.answer(
        "🏋️ Выбери тренировку:",
        reply_markup=workouts_list_kb(workouts, active_wt_id=active_wt_id),
    )


@router.callback_query(F.data == "wt_list")
async def cb_workouts_list(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    user = await _get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    result = await session.execute(
        select(WorkoutType)
        .where(WorkoutType.user_id == user.id, WorkoutType.is_archived == False)
        .order_by(WorkoutType.sort_order)
    )
    workouts = list(result.scalars())

    from app.db.queries import get_active_session
    active = await get_active_session(session, user.id)
    active_wt_id = active.workout_type_id if active else None

    await callback.message.edit_text(
        "🏋️ Выбери тренировку:",
        reply_markup=workouts_list_kb(workouts, active_wt_id=active_wt_id),
    )
    await callback.answer()


# ─────────────── карточка тренировки ───────────────

@router.callback_query(F.data.startswith("wt:"))
async def cb_workout_card(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    wt_id = int(callback.data.split(":")[1])
    user = await _get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await session.get(WorkoutType, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    # Активная сессия — только если она для этой тренировки
    from app.db.queries import get_active_session
    active = await get_active_session(session, user.id)
    active_session_id = active.id if (active and active.workout_type_id == wt_id) else None

    await callback.message.edit_text(
        render_workout_card(wt),
        reply_markup=workout_card_kb(wt.id, active_session_id=active_session_id),
    )
    await callback.answer()


# ─────────────── список упражнений ───────────────

@router.callback_query(F.data.startswith("wt_ex:"))
async def cb_exercises_list(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    wt_id = int(callback.data.split(":")[1])
    user = await _get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await _load_workout_with_exercises(session, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    await callback.message.edit_text(
        f"📋 Упражнения — <b>{wt.name}</b>\n\n"
        "<i>💡 Нажми на упражнение, чтобы отредактировать или убрать</i>",
        reply_markup=exercises_list_kb(wt.exercises, wt.id),
    )
    await callback.answer()


# ─────────────── карточка упражнения ───────────────

@router.callback_query(F.data.startswith("ex:"))
async def cb_exercise_card(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    await callback.message.edit_text(
        render_exercise_card(ex), reply_markup=exercise_card_kb(ex)
    )
    await callback.answer()


# ─────────────── удаление упражнения ───────────────

@router.callback_query(F.data.startswith("ex_del:"))
async def cb_delete_ask(callback: CallbackQuery, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    # Проверяем историю: в скольких ТРЕНИРОВКАХ встречается упражнение
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
        text, reply_markup=confirm_delete_kb(ex.id)
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

    wt = await _load_workout_with_exercises(session, wt_id)
    if wt:
        await callback.message.edit_text(
            f"{action}\n\n📋 Упражнения — <b>{wt.name}</b>",
            reply_markup=exercises_list_kb(wt.exercises, wt.id),
        )
    await callback.answer("Готово")


# ═══════════════════════════════════════════════════════════
#  Удаление типа тренировки (с архивом при наличии истории)
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("wt_del:"))
async def cb_workout_delete_ask(callback: CallbackQuery, session: AsyncSession):
    """Показываем подтверждение. Если есть история — предлагаем архив."""
    wt_id = int(callback.data.split(":")[1])
    user = await _get_user(session, callback.from_user.id)
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
            "но история сохранится (её можно будет посмотреть позже).\n\n"
            "🔥 <b>Удалить со всей историей</b> — исчезнет всё, "
            "включая записи о выполнении. Необратимо."
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


@router.callback_query(F.data.startswith("wt_archive:"))
async def cb_workout_archive(callback: CallbackQuery, session: AsyncSession):
    """Помечаем is_archived=True. Строка в БД остаётся, история сохраняется."""
    wt_id = int(callback.data.split(":")[1])
    user = await _get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await session.get(WorkoutType, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    wt.is_archived = True
    await session.commit()

    result = await session.execute(
        select(WorkoutType)
        .where(WorkoutType.user_id == user.id, WorkoutType.is_archived == False)
        .order_by(WorkoutType.sort_order)
    )
    workouts = list(result.scalars())

    if not workouts:
        await callback.message.edit_text(
            "📦 Тренировка в архиве. История сохранена.\n\n"
            "У тебя больше нет активных тренировок.\n"
            "Создать новую: /workout → «➕ Новая тренировка»"
        )
    else:
        await callback.message.edit_text(
            "📦 Тренировка в архиве. История сохранена.\n\n"
            "🏋️ Выбери тренировку:",
            reply_markup=workouts_list_kb(workouts),
        )
    await callback.answer("Архивировано")


@router.callback_query(F.data.startswith("wt_del_yes:"))
async def cb_workout_delete_confirm(callback: CallbackQuery, session: AsyncSession):
    """Жёсткое удаление: сначала сессии, потом сама тренировка (упражнения каскадно)."""
    wt_id = int(callback.data.split(":")[1])
    user = await _get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await session.get(WorkoutType, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    await session.execute(
        delete(WorkoutSession).where(WorkoutSession.workout_type_id == wt_id)
    )
    await session.delete(wt)
    await session.commit()

    result = await session.execute(
        select(WorkoutType)
        .where(WorkoutType.user_id == user.id, WorkoutType.is_archived == False)
        .order_by(WorkoutType.sort_order)
    )
    workouts = list(result.scalars())

    if not workouts:
        await callback.message.edit_text(
            "🗑 Тренировка удалена вместе с историей.\n\n"
            "У тебя больше нет активных тренировок.\n"
            "Создай новую: /workout → «➕ Новая тренировка»"
        )
    else:
        await callback.message.edit_text(
            "🗑 Тренировка удалена вместе с историей.\n\n"
            "🏋️ Выбери тренировку:",
            reply_markup=workouts_list_kb(workouts),
        )
    await callback.answer("Удалено")


@router.callback_query(F.data.startswith("wt_del_no:"))
async def cb_workout_delete_cancel(callback: CallbackQuery, session: AsyncSession):
    """Отмена удаления — возвращаемся в карточку тренировки."""
    wt_id = int(callback.data.split(":")[1])
    wt = await session.get(WorkoutType, wt_id)
    if not wt:
        return await callback.answer("Не найдено", show_alert=True)

    await callback.message.edit_text(
        render_workout_card(wt), reply_markup=workout_card_kb(wt.id)
    )
    await callback.answer("Отменено")


# ═══════════════════════════════════════════════════════════
#  Архив упражнений
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ex_arch_menu:"))
async def cb_archive_menu(callback: CallbackQuery, session: AsyncSession):
    from app.keyboards.workout_kb import archive_list_kb
    wt_id = int(callback.data.split(":")[1])

    result = await session.execute(
        select(Exercise)
        .where(Exercise.workout_type_id == wt_id, Exercise.is_archived == True)
        .order_by(Exercise.sort_order)
    )
    archived = list(result.scalars())

    if not archived:
        return await callback.answer("В архиве пока пусто.", show_alert=True)

    # Группируем по имени (без учета регистра)
    grouped = {}
    for ex in archived:
        key = ex.name.lower()
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(ex)

    # Создаем список: (представитель, количество)
    grouped_list = [(exs[0], len(exs)) for exs in grouped.values()]

    await callback.message.edit_text(
        "📦 <b>Архив упражнений</b>\n\n"
        "Если в архиве есть дубликаты (например, несколько «Жимов»), "
        "они объединены в одну запись. При восстановлении их история склеится в одно упражнение.\n\n"
        "Выбери упражнение:",
        reply_markup=archive_list_kb(grouped_list, wt_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ex_arch_view:"))
async def cb_archive_view(callback: CallbackQuery, session: AsyncSession):
    from app.keyboards.workout_kb import archive_card_kb
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    # Считаем дубликаты по имени
    result = await session.execute(
        select(func.count())
        .select_from(Exercise)
        .where(
            Exercise.workout_type_id == ex.workout_type_id,
            Exercise.is_archived == True,
            func.lower(Exercise.name) == ex.name.lower()
        )
    )
    dup_count = result.scalar() or 1

    text = f"📦 Упражнение <b>{ex.name}</b> в архиве.\n\n"
    if dup_count > 1:
        text += f"⚠️ Найдено <b>{dup_count}</b> архивных записей с этим названием.\n"
        text += "При восстановлении их история будет объединена в одно упражнение.\n\n"
    else:
        text += "Его параметры и история сохранены.\n\n"

    text += "Восстановить его в тренировку?"

    await callback.message.edit_text(
        text,
        reply_markup=archive_card_kb(ex, dup_count)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ex_restore:"))
async def cb_restore_exercise(callback: CallbackQuery, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    # Снимаем флаг архивации
    ex.is_archived = False
    await session.commit()

    await callback.message.edit_text(
        f"✅ Упражнение <b>{ex.name}</b> восстановлено!\n\n"
        "Оно снова появилось в списке упражнений вместе со всей историей.",
        reply_markup=workout_card_kb(ex.workout_type_id)
    )
    await callback.answer("Восстановлено")


@router.callback_query(F.data.startswith("ex_restore_merge:"))
async def cb_restore_merge(callback: CallbackQuery, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    name = ex.name
    wt_id = ex.workout_type_id

    # Ищем все архивные записи с таким же именем
    result = await session.execute(
        select(Exercise).where(
            Exercise.workout_type_id == wt_id,
            Exercise.is_archived == True,
            func.lower(Exercise.name) == name.lower()
        )
    )
    archived_exs = list(result.scalars())

    if not archived_exs:
        return await callback.answer("Ошибка: запись не найдена в архиве",
                                     show_alert=True)

    # Проверяем, есть ли уже активное упражнение с таким именем
    result = await session.execute(
        select(Exercise).where(
            Exercise.workout_type_id == wt_id,
            Exercise.is_archived == False,
            func.lower(Exercise.name) == name.lower()
        )
    )
    active_ex = result.scalars().first()

    if active_ex:
        # Если активное есть, сливаем все архивные в него
        target_id = active_ex.id
        for e in archived_exs:
            await session.execute(
                update(SessionSet)
                .where(SessionSet.exercise_id == e.id)
                .values(exercise_id=target_id)
            )
            await session.delete(e)
        msg = f"✅ История ({len(archived_exs)} шт.) объединена с активным упражнением <b>{name}</b>!"
    else:
        # Если активного нет, берем первое архивное как основное
        target_ex = archived_exs[0]
        target_ex.is_archived = False
        target_id = target_ex.id

        # Остальные удаляем, перенося их подходы
        for e in archived_exs[1:]:
            await session.execute(
                update(SessionSet)
                .where(SessionSet.exercise_id == e.id)
                .values(exercise_id=target_id)
            )
            await session.delete(e)
        msg = f"✅ Упражнение <b>{name}</b> восстановлено (объединено {len(archived_exs)} записей)!"

    await session.commit()

    await callback.message.edit_text(
        msg,
        reply_markup=workout_card_kb(wt_id)
    )
    await callback.answer("Восстановлено")
