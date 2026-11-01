"""Навигация по тренировкам и упражнениям через inline-кнопки."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Exercise, SessionExerciseNote, SessionSet, User, WorkoutSession, WorkoutType
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


async def _render_ex_card(session: AsyncSession, ex: Exercise) -> str:
    """Рендер карточки упражнения с добавлением позиции в списке."""
    text = render_exercise_card(ex)

    # Считаем позицию среди активных упражнений
    result = await session.execute(
        select(Exercise.id)
        .where(Exercise.workout_type_id == ex.workout_type_id,
               Exercise.is_archived == False)
        .order_by(Exercise.sort_order)
    )
    ids = list(result.scalars())
    if ex.id in ids:
        text += f"\n\n📌 <i>Позиция: {ids.index(ex.id) + 1} из {len(ids)}</i>"
    return text


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
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Новая тренировка", callback_data="wt_new")
        return await message.answer(
            "У тебя пока нет тренировок.\nДавай создадим первую!",
            reply_markup=kb.as_markup()
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
        await _render_ex_card(session, ex), reply_markup=exercise_card_kb(ex)
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
        text, reply_markup=confirm_delete_kb(ex.id, has_history=(history_count > 0))
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
    """Архивация: скрываем тренировку и убиваем активную сессию, если она была."""
    wt_id = int(callback.data.split(":")[1])
    user = await _get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await session.get(WorkoutType, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    # 1. Ставим флаг архивации
    wt.is_archived = True
    await session.commit()

    # 2. Ищем активную сессию и удаляем её
    active_session = await session.scalar(
        select(WorkoutSession).where(
            WorkoutSession.workout_type_id == wt_id,
            WorkoutSession.finished_at.is_(None)
        )
    )
    if active_session:
        await session.delete(active_session)
        await session.commit()

    # 3. Возвращаемся к списку тренировок
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
async def cb_workout_delete_confirm(callback: CallbackQuery,
                                    session: AsyncSession):
    """Жёсткое удаление: сначала чистим историю, потом удаляем тренировку."""
    wt_id = int(callback.data.split(":")[1])
    user = await _get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await session.get(WorkoutType, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    # 1. Получаем ID всех упражнений этой тренировки
    result = await session.execute(
        select(Exercise.id).where(Exercise.workout_type_id == wt_id))
    ex_ids = list(result.scalars())

    # 2. Удаляем подходы и заметки (чтобы снять блокировку)
    if ex_ids:
        await session.execute(
            delete(SessionSet).where(SessionSet.exercise_id.in_(ex_ids)))
        await session.execute(delete(SessionExerciseNote).where(
            SessionExerciseNote.exercise_id.in_(ex_ids)))

    # 3. Удаляем сессии
    await session.execute(
        delete(WorkoutSession).where(WorkoutSession.workout_type_id == wt_id))

    # 4. Удаляем саму тренировку (упражнения удалятся каскадно)
    await session.delete(wt)
    await session.commit()

    # Возвращаемся к списку тренировок
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

    # Группируем по имени И типу (kind)
    grouped = {}
    for ex in archived:
        key = (ex.name.strip().lower(), ex.kind)
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(ex)

    grouped_list = [(exs[0], len(exs)) for exs in grouped.values()]

    await callback.message.edit_text(
        "📦 <b>Архив упражнений</b>\n\n"
        "Если в архиве есть дубликаты (например, несколько «Жимов» одного типа), "
        "они объединены в одну запись. При восстановлении их история склеится.\n\n"
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

    name_clean = ex.name.strip()

    # 1. Считаем архивные дубликаты ТОГО ЖЕ ТИПА
    archived_count = await session.scalar(
        select(func.count())
        .select_from(Exercise)
        .where(
            Exercise.workout_type_id == ex.workout_type_id,
            Exercise.is_archived == True,
            Exercise.kind == ex.kind,  # <--- проверяем тип!
            func.lower(func.trim(Exercise.name)) == name_clean.lower()
        )
    ) or 0

    # 2. Проверяем активный дубликат ТОГО ЖЕ ТИПА
    active_count = await session.scalar(
        select(func.count())
        .select_from(Exercise)
        .where(
            Exercise.workout_type_id == ex.workout_type_id,
            Exercise.is_archived == False,
            Exercise.kind == ex.kind,  # <--- проверяем тип!
            func.lower(func.trim(Exercise.name)) == name_clean.lower()
        )
    ) or 0

    text = f"📦 Упражнение <b>{ex.name}</b> в архиве.\n\n"
    has_conflict = (active_count > 0) or (archived_count > 1)

    if active_count > 0:
        text += f"⚠️ В тренировке уже есть <b>активное</b> {'силовое' if ex.kind == 'strength' else 'кардио'} упражнение с таким названием.\n"
        text += "При восстановлении история объединится с ним.\n\n"
    elif archived_count > 1:
        text += f"⚠️ Найдено <b>{archived_count}</b> архивных записей этого типа с таким названием.\n"
        text += "При восстановлении их история объединится в одно упражнение.\n\n"
    else:
        text += "Его параметры и история сохранены.\n\n"

    text += "Восстановить его в тренировку?"

    await callback.message.edit_text(
        text,
        reply_markup=archive_card_kb(ex, has_conflict=has_conflict)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ex_restore_merge:"))
async def cb_restore_merge(callback: CallbackQuery, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    name_clean = ex.name.strip()
    wt_id = ex.workout_type_id

    # Ищем все архивные записи с таким же именем И ТИПОМ
    result = await session.execute(
        select(Exercise).where(
            Exercise.workout_type_id == wt_id,
            Exercise.is_archived == True,
            Exercise.kind == ex.kind,
            func.lower(func.trim(Exercise.name)) == name_clean.lower()
        )
    )
    archived_exs = list(result.scalars())

    if not archived_exs:
        return await callback.answer("Не найдено в архиве", show_alert=True)

    # Проверяем, есть ли уже активное упражнение с таким именем И ТИПОМ
    result = await session.execute(
        select(Exercise).where(
            Exercise.workout_type_id == wt_id,
            Exercise.is_archived == False,
            Exercise.kind == ex.kind,
            func.lower(func.trim(Exercise.name)) == name_clean.lower()
        )
    )
    active_ex = result.scalars().first()

    if active_ex:
        target_id = active_ex.id
        for e in archived_exs:
            await session.execute(
                update(SessionSet).where(
                    SessionSet.exercise_id == e.id).values(
                    exercise_id=target_id)
            )
            await session.execute(
                update(SessionExerciseNote).where(
                    SessionExerciseNote.exercise_id == e.id).values(
                    exercise_id=target_id)
            )
            await session.delete(e)
        msg = f"✅ История объединена с активным упражнением <b>{name_clean}</b>!"
    else:
        target_ex = archived_exs[0]
        target_ex.is_archived = False
        target_id = target_ex.id

        for e in archived_exs[1:]:
            await session.execute(
                update(SessionSet).where(
                    SessionSet.exercise_id == e.id).values(
                    exercise_id=target_id)
            )
            await session.execute(
                update(SessionExerciseNote).where(
                    SessionExerciseNote.exercise_id == e.id).values(
                    exercise_id=target_id)
            )
            await session.delete(e)
        msg = f"✅ Упражнение <b>{name_clean}</b> восстановлено (объединено {len(archived_exs)} записей)!"

    await session.commit()

    await callback.message.edit_text(
        msg,
        reply_markup=workout_card_kb(wt_id)
    )
    await callback.answer("Восстановлено")


# ═══════════════════════════════════════════════════════════
#  Перемещение упражнений (сортировка)
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ex_move_up:"))
async def cb_ex_move_up(callback: CallbackQuery, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    # Ищем упражнение, которое идет ПЕРЕД ним (только среди активных)
    result = await session.execute(
        select(Exercise)
        .where(
            Exercise.workout_type_id == ex.workout_type_id,
            Exercise.sort_order < ex.sort_order,
            Exercise.is_archived == False
        )
        .order_by(Exercise.sort_order.desc())
        .limit(1)
    )
    prev_ex = result.scalar_one_or_none()

    if not prev_ex:
        return await callback.answer("Упражнение уже первое", show_alert=True)

    # Меняем местами
    ex.sort_order, prev_ex.sort_order = prev_ex.sort_order, ex.sort_order
    await session.commit()

    await callback.message.edit_text(
        await _render_ex_card(session, ex), reply_markup=exercise_card_kb(ex)
    )
    await callback.answer("Перемещено вверх ⬆️")


@router.callback_query(F.data.startswith("ex_move_down:"))
async def cb_ex_move_down(callback: CallbackQuery, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    # Ищем упражнение, которое идет ПОСЛЕ него (только среди активных)
    result = await session.execute(
        select(Exercise)
        .where(
            Exercise.workout_type_id == ex.workout_type_id,
            Exercise.sort_order > ex.sort_order,
            Exercise.is_archived == False
        )
        .order_by(Exercise.sort_order.asc())
        .limit(1)
    )
    next_ex = result.scalar_one_or_none()

    if not next_ex:
        return await callback.answer("Упражнение уже последнее", show_alert=True)

    # Меняем местами
    ex.sort_order, next_ex.sort_order = next_ex.sort_order, ex.sort_order
    await session.commit()

    await callback.message.edit_text(
        await _render_ex_card(session, ex), reply_markup=exercise_card_kb(ex)
    )
    await callback.answer("Перемещено вниз ⬇️")


@router.callback_query(F.data.startswith("ex_arch_del_ask:"))
async def cb_arch_del_ask(callback: CallbackQuery, session: AsyncSession):
    from sqlalchemy import func as sa_func
    from app.keyboards.workout_kb import confirm_archive_delete_kb

    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    # Считаем, сколько подходов в истории
    sets_count = await session.scalar(
        select(sa_func.count())
        .select_from(SessionSet)
        .where(SessionSet.exercise_id == ex_id)
    ) or 0

    text = (
        f"🔥 <b>Удалить упражнение «{ex.name}» навсегда?</b>\n\n"
        "⚠️ Это действие <b>необратимо</b>.\n"
    )
    if sets_count > 0:
        text += f"Вместе с упражнением будет удалена вся его история (<b>{sets_count}</b> подходов из прошлых тренировок).\n"

    text += "\nЕсли ты не уверен, лучше оставь его в архиве."

    await callback.message.edit_text(
        text, reply_markup=confirm_archive_delete_kb(ex.id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ex_arch_del_yes:"))
async def cb_arch_del_yes(callback: CallbackQuery, session: AsyncSession):
    from app.keyboards.workout_kb import workouts_list_kb, archive_list_kb

    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    wt_id = ex.workout_type_id
    name = ex.name

    # 1. Удаляем историю подходов (чтобы база разрешила удалить упражнение)
    await session.execute(
        delete(SessionSet).where(SessionSet.exercise_id == ex_id))
    # 2. Удаляем заметки (на всякий случай)
    await session.execute(delete(SessionExerciseNote).where(
        SessionExerciseNote.exercise_id == ex_id))

    # 3. Удаляем само упражнение
    await session.delete(ex)
    await session.commit()

    # Возвращаемся в архив и проверяем, остались ли там еще упражнения
    result = await session.execute(
        select(Exercise)
        .where(Exercise.workout_type_id == wt_id, Exercise.is_archived == True)
        .order_by(Exercise.sort_order)
    )
    archived = list(result.scalars())

    if not archived:
        # Если архив пуст, возвращаемся в карточку тренировки
        await callback.message.edit_text(
            f"🗑 Упражнение <b>{name}</b> удалено навсегда.\n\n📦 Архив пуст.",
            reply_markup=workout_card_kb(wt_id)
        )
    else:
        # Перестраиваем архив (группируем дубликаты)
        grouped = {}
        for e in archived:
            key = (e.name.strip().lower(), e.kind)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(e)
        grouped_list = [(exs[0], len(exs)) for exs in grouped.values()]

        await callback.message.edit_text(
            f"🗑 Упражнение <b>{name}</b> удалено навсегда.\n\n"
            "📦 <b>Архив упражнений</b>\nВыбери упражнение:",
            reply_markup=archive_list_kb(grouped_list, wt_id)
        )

    await callback.answer("Удалено")


# ═══════════════════════════════════════════════════════════
#  Архив тренировок
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "wt_arch_list")
async def cb_workouts_archive(callback: CallbackQuery, session: AsyncSession):
    from app.keyboards.workout_kb import workouts_archive_list_kb
    user = await _get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    result = await session.execute(
        select(WorkoutType)
        .where(WorkoutType.user_id == user.id, WorkoutType.is_archived == True)
        .order_by(WorkoutType.sort_order)
    )
    archived = list(result.scalars())

    if not archived:
        return await callback.answer("Архив тренировок пуст.", show_alert=True)

    await callback.message.edit_text(
        "📦 <b>Архив тренировок</b>\n\n"
        "Здесь лежат тренировки, которые ты убрал. Выбери, чтобы восстановить или удалить навсегда:",
        reply_markup=workouts_archive_list_kb(archived)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("wt_arch_view:"))
async def cb_workout_arch_card(callback: CallbackQuery, session: AsyncSession):
    from app.keyboards.workout_kb import archived_workout_card_kb
    wt_id = int(callback.data.split(":")[1])
    user = await _get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await session.get(WorkoutType, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    # Проверяем, есть ли активный дубликат
    active_dup = await session.scalar(
        select(WorkoutType).where(
            WorkoutType.user_id == user.id,
            WorkoutType.is_archived == False,
            func.lower(func.trim(WorkoutType.name)) == wt.name.strip().lower()
        )
    )

    sessions_count = await session.scalar(
        select(func.count())
        .select_from(WorkoutSession)
        .where(WorkoutSession.workout_type_id == wt_id)
    ) or 0

    text = f"📦 <b>{wt.name}</b>\n\n"
    if wt.description:
        text += f"{wt.description}\n\n"

    if sessions_count > 0:
        text += f"📊 Выполнялась: <b>{sessions_count}</b> раз(а)\n"
    else:
        text += "📊 История выполнения отсутствует.\n"

    if active_dup:
        text += "\n⚠️ У тебя уже есть <b>активная</b> тренировка с таким названием.\n"
        text += "При восстановлении история и упражнения объединятся с ней.\n"
    else:
        text += "\nЧто сделать с тренировкой?"

    await callback.message.edit_text(
        text, reply_markup=archived_workout_card_kb(wt.id, has_conflict=bool(
            active_dup))
    )
    await callback.answer()


@router.callback_query(F.data.startswith("wt_restore:"))
async def cb_workout_restore(callback: CallbackQuery, session: AsyncSession):
    from app.keyboards.workout_kb import workouts_archive_list_kb
    wt_id = int(callback.data.split(":")[1])
    user = await _get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await session.get(WorkoutType, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    wt.is_archived = False
    await session.commit()

    # Проверяем, остались ли еще архивные
    result = await session.execute(
        select(WorkoutType)
        .where(WorkoutType.user_id == user.id, WorkoutType.is_archived == True)
        .order_by(WorkoutType.sort_order)
    )
    archived = list(result.scalars())

    if not archived:
        # Если архив пуст — показываем список всех тренировок
        result = await session.execute(
            select(WorkoutType)
            .where(WorkoutType.user_id == user.id, WorkoutType.is_archived == False)
            .order_by(WorkoutType.sort_order)
        )
        workouts = list(result.scalars())
        await callback.message.edit_text(
            f"✅ Тренировка <b>{wt.name}</b> восстановлена!\n\n"
            "🏋️ Выбери тренировку:",
            reply_markup=workouts_list_kb(workouts)
        )
    else:
        await callback.message.edit_text(
            f"✅ Тренировка <b>{wt.name}</b> восстановлена!\n\n📦 <b>Остальные в архиве:</b>",
            reply_markup=workouts_archive_list_kb(archived)
        )
    await callback.answer("Восстановлено")


@router.callback_query(F.data.startswith("wt_arch_del_ask:"))
async def cb_workout_arch_del_ask(callback: CallbackQuery,
                                  session: AsyncSession):
    # Используем существующую клавиатуру подтверждения, но добавим логику
    from app.keyboards.workout_kb import confirm_workout_delete_kb
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

    text = (
        f"🔥 <b>Удалить тренировку «{wt.name}» навсегда?</b>\n\n"
        "⚠️ Это действие <b>необратимо</b>.\n"
    )
    if sessions_count > 0:
        text += f"Вместе с тренировкой удалится вся история (<b>{sessions_count}</b> записей) и все упражнения.\n"
    text += "\nТочно удалить?"

    await callback.message.edit_text(
        text, reply_markup=confirm_workout_delete_kb(wt_id, has_history=(
                    sessions_count > 0))
    )
    await callback.answer()


@router.callback_query(F.data.startswith("wt_merge:"))
async def cb_workout_merge(callback: CallbackQuery, session: AsyncSession):
    from app.keyboards.workout_kb import workouts_archive_list_kb, \
        workouts_list_kb

    wt_id = int(callback.data.split(":")[1])
    user = await _get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await session.get(WorkoutType, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    active_dup = await session.scalar(
        select(WorkoutType).where(
            WorkoutType.user_id == user.id,
            WorkoutType.is_archived == False,
            func.lower(func.trim(WorkoutType.name)) == wt.name.strip().lower()
        )
    )
    if not active_dup:
        return await callback.answer("Активная тренировка не найдена",
                                     show_alert=True)

    # 1. Переносим сессии (историю выполнения) в активную тренировку
    await session.execute(
        update(WorkoutSession)
        .where(WorkoutSession.workout_type_id == wt.id)
        .values(workout_type_id=active_dup.id)
    )

    # 2. Переносим упражнения
    old_exs = list((await session.execute(
        select(Exercise).where(Exercise.workout_type_id == wt.id))).scalars())
    new_exs = list((await session.execute(select(Exercise).where(
        Exercise.workout_type_id == active_dup.id))).scalars())

    # Карта активных упражнений по (имя, тип)
    new_ex_map = {(e.name.strip().lower(), e.kind): e for e in new_exs}

    for old_ex in old_exs:
        key = (old_ex.name.strip().lower(), old_ex.kind)
        if key in new_ex_map:
            # Если упражнение уже есть в активной, склеиваем их историю
            new_ex = new_ex_map[key]
            await session.execute(
                update(SessionSet).where(
                    SessionSet.exercise_id == old_ex.id).values(
                    exercise_id=new_ex.id)
            )
            # Заметки удаляем (чтобы не было конфликта уникальности)
            await session.execute(delete(SessionExerciseNote).where(
                SessionExerciseNote.exercise_id == old_ex.id))
            await session.delete(old_ex)
        else:
            # Если нет — просто перепривязываем к активной тренировке
            old_ex.workout_type_id = active_dup.id

    # 3. Удаляем пустую архивную тренировку
    await session.delete(wt)
    await session.commit()

    # 4. Возвращаемся в архив
    result = await session.execute(
        select(WorkoutType)
        .where(WorkoutType.user_id == user.id, WorkoutType.is_archived == True)
        .order_by(WorkoutType.sort_order)
    )
    archived = list(result.scalars())

    if not archived:
        result = await session.execute(
            select(WorkoutType)
            .where(WorkoutType.user_id == user.id,
                   WorkoutType.is_archived == False)
            .order_by(WorkoutType.sort_order)
        )
        workouts = list(result.scalars())
        await callback.message.edit_text(
            f"✅ Тренировка объединена с <b>{active_dup.name}</b>!\n\n"
            "🏋️ Выбери тренировку:",
            reply_markup=workouts_list_kb(workouts)
        )
    else:
        await callback.message.edit_text(
            f"✅ Тренировка объединена с <b>{active_dup.name}</b>!\n\n📦 <b>Остальные в архиве:</b>",
            reply_markup=workouts_archive_list_kb(archived)
        )
    await callback.answer("Объединено")
