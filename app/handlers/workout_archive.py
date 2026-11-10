"""Хэндлеры для работы с архивами тренировок и упражнений."""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Exercise, SessionExerciseNote, SessionSet, \
    WorkoutSession, WorkoutType
from app.keyboards.workout_kb import (
    archive_card_kb, archive_list_kb, archived_workout_card_kb,
    confirm_archive_delete_kb, confirm_workout_delete_kb,
    workout_card_kb, workouts_archive_list_kb, workouts_list_kb,
)
from app.render import render_workout_card
from app.services.training_service import get_user, load_workout_with_exercises

router = Router()


# ═══════════════════════════════════════════════════════════
#  АРХИВ ТРЕНИРОВОК
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "wt_arch_list")
async def cb_workouts_archive(callback: CallbackQuery, session: AsyncSession):
    user = await get_user(session, callback.from_user.id)
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
    wt_id = int(callback.data.split(":")[1])
    user = await get_user(session, callback.from_user.id)
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
    wt_id = int(callback.data.split(":")[1])
    user = await get_user(session, callback.from_user.id)
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
        result = await session.execute(
            select(WorkoutType)
            .where(WorkoutType.user_id == user.id,
                   WorkoutType.is_archived == False)
            .order_by(WorkoutType.sort_order)
        )
        workouts = list(result.scalars())
        await callback.message.edit_text(
            f"✅ Тренировка <b>{wt.name}</b> восстановлена!\n\n🏋️ Выбери тренировку:",
            reply_markup=workouts_list_kb(workouts)
        )
    else:
        await callback.message.edit_text(
            f"✅ Тренировка <b>{wt.name}</b> восстановлена!\n\n📦 <b>Остальные в архиве:</b>",
            reply_markup=workouts_archive_list_kb(archived)
        )
    await callback.answer("Восстановлено")


@router.callback_query(F.data.startswith("wt_merge:"))
async def cb_workout_merge(callback: CallbackQuery, session: AsyncSession):
    wt_id = int(callback.data.split(":")[1])
    user = await get_user(session, callback.from_user.id)
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

    # 1. Переносим сессии в активную тренировку
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

    new_ex_map = {(e.name.strip().lower(), e.kind): e for e in new_exs}

    for old_ex in old_exs:
        key = (old_ex.name.strip().lower(), old_ex.kind)
        if key in new_ex_map:
            new_ex = new_ex_map[key]
            await session.execute(
                update(SessionSet).where(
                    SessionSet.exercise_id == old_ex.id).values(
                    exercise_id=new_ex.id)
            )
            await session.execute(delete(SessionExerciseNote).where(
                SessionExerciseNote.exercise_id == old_ex.id))
            await session.delete(old_ex)
        else:
            old_ex.workout_type_id = active_dup.id

    # 3. Удаляем пустую архивную тренировку
    await session.delete(wt)
    await session.commit()

    # Возврат в архив
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
            f"✅ Тренировка объединена с <b>{active_dup.name}</b>!\n\n🏋️ Выбери тренировку:",
            reply_markup=workouts_list_kb(workouts)
        )
    else:
        await callback.message.edit_text(
            f"✅ Тренировка объединена с <b>{active_dup.name}</b>!\n\n📦 <b>Остальные в архиве:</b>",
            reply_markup=workouts_archive_list_kb(archived)
        )
    await callback.answer("Объединено")


@router.callback_query(F.data.startswith("wt_arch_del_ask:"))
async def cb_workout_arch_del_ask(callback: CallbackQuery,
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


# ═══════════════════════════════════════════════════════════
#  АРХИВ УПРАЖНЕНИЙ
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ex_arch_menu:"))
async def cb_archive_menu(callback: CallbackQuery, session: AsyncSession):
    wt_id = int(callback.data.split(":")[1])

    result = await session.execute(
        select(Exercise)
        .where(Exercise.workout_type_id == wt_id, Exercise.is_archived == True)
        .order_by(Exercise.sort_order)
    )
    archived = list(result.scalars())

    if not archived:
        return await callback.answer("В архиве пока пусто.", show_alert=True)

    grouped = {}
    for ex in archived:
        key = (ex.name.strip().lower(), ex.kind)
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(ex)

    grouped_list = [(exs[0], len(exs)) for exs in grouped.values()]

    await callback.message.edit_text(
        "📦 <b>Архив упражнений</b>\n\n"
        "Если в архиве есть дубликаты, они объединены в одну запись. "
        "При восстановлении их история склеится.\n\n"
        "Выбери упражнение:",
        reply_markup=archive_list_kb(grouped_list, wt_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ex_arch_view:"))
async def cb_archive_view(callback: CallbackQuery, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    name_clean = ex.name.strip()

    archived_count = await session.scalar(
        select(func.count())
        .select_from(Exercise)
        .where(
            Exercise.workout_type_id == ex.workout_type_id,
            Exercise.is_archived == True,
            Exercise.kind == ex.kind,
            func.lower(func.trim(Exercise.name)) == name_clean.lower()
        )
    ) or 0

    active_count = await session.scalar(
        select(func.count())
        .select_from(Exercise)
        .where(
            Exercise.workout_type_id == ex.workout_type_id,
            Exercise.is_archived == False,
            Exercise.kind == ex.kind,
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
        text += "При восстановлении их история объединится.\n\n"
    else:
        text += "Его параметры и история сохранены.\n\n"

    text += "Восстановить его в тренировку?"

    await callback.message.edit_text(
        text, reply_markup=archive_card_kb(ex, has_conflict=has_conflict)
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
        # Если активное есть, сливаем все архивные в него
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
        # Если активного нет, берем первое архивное как основное
        target_ex = archived_exs[0]
        target_ex.is_archived = False
        target_id = target_ex.id

        # Остальные удаляем, перенося их подходы и заметки
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

        # Красивый текст в зависимости от количества склеенных записей
        if len(archived_exs) > 1:
            msg = f"✅ Упражнение <b>{name_clean}</b> восстановлено (объединено {len(archived_exs)} записей)!"
        else:
            msg = f"✅ Упражнение <b>{name_clean}</b> восстановлено!"

    await session.commit()

    wt = await session.get(WorkoutType, wt_id)

    await callback.message.edit_text(
        msg,
        reply_markup=workout_card_kb(wt)
    )
    await callback.answer("Восстановлено")


@router.callback_query(F.data.startswith("ex_arch_del_ask:"))
async def cb_arch_del_ask(callback: CallbackQuery, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    sets_count = await session.scalar(
        select(func.count())
        .select_from(SessionSet)
        .where(SessionSet.exercise_id == ex_id)
    ) or 0

    text = (
        f"🔥 <b>Удалить упражнение «{ex.name}» навсегда?</b>\n\n"
        "⚠️ Это действие <b>необратимо</b>.\n"
    )
    if sets_count > 0:
        text += f"Вместе с упражнением будет удалена вся его история (<b>{sets_count}</b> подходов).\n"

    text += "\nЕсли ты не уверен, лучше оставь его в архиве."

    await callback.message.edit_text(text,
                                     reply_markup=confirm_archive_delete_kb(
                                         ex.id))
    await callback.answer()


@router.callback_query(F.data.startswith("ex_arch_del_yes:"))
async def cb_arch_del_yes(callback: CallbackQuery, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    wt_id = ex.workout_type_id
    name = ex.name

    await session.execute(
        delete(SessionSet).where(SessionSet.exercise_id == ex_id))
    await session.execute(delete(SessionExerciseNote).where(
        SessionExerciseNote.exercise_id == ex_id))
    await session.delete(ex)
    await session.commit()

    result = await session.execute(
        select(Exercise)
        .where(Exercise.workout_type_id == wt_id, Exercise.is_archived == True)
        .order_by(Exercise.sort_order)
    )
    archived = list(result.scalars())

    wt = await session.get(WorkoutType, wt_id)

    if not archived:
        await callback.message.edit_text(
            f"🗑 Упражнение <b>{name}</b> удалено навсегда.\n\n📦 Архив пуст.",
            reply_markup=workout_card_kb(wt)
        )
    else:
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
