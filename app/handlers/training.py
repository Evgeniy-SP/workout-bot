"""Процесс тренировки: начать → пройти по упражнениям → завершить.

Храним данные в WorkoutSession (одна строка) и SessionSet (по строке на подход).
"""
import random
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Exercise, SessionSet, User, WorkoutSession, WorkoutType
from app.db.queries import (
    get_active_session, get_last_completed_set, get_sets_grouped,
)
from app.keyboards.workout_kb import (
    approach_kb, cancel_kb, finish_confirm_kb, strength_summary_kb,
    training_list_kb, workouts_list_kb, training_remove_menu_kb,
)
from app.render import (
    render_approach, render_strength_summary, render_training_list,
)
from app.states import TrainingFSM
from app.utils import format_duration, format_weight, parse_minutes_to_seconds

router = Router()


# ─────────────── helpers ───────────────

async def _get_user(session: AsyncSession, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


async def _load_workout(session: AsyncSession, wt_id: int) -> WorkoutType | None:
    """Загружаем тренировку с НЕархивными упражнениями.

    Фильтр на уровне selectinload — нельзя фильтровать через
    присваивание wt.exercises = [...], т.к. cascade="all, delete-orphan"
    воспримет это как удаление архивных упражнений.
    """
    from app.db.models import Exercise  # локально, чтобы не засорять шапку

    result = await session.execute(
        select(WorkoutType)
        .where(WorkoutType.id == wt_id)
        .options(
            selectinload(WorkoutType.exercises.and_(Exercise.is_archived.is_(False)))
        )
    )
    return result.scalar_one_or_none()


async def _render_list(session: AsyncSession, session_id: int, user_id: int):
    """Собрать (текст, клавиатуру) для экрана активной тренировки."""
    ws = await session.get(WorkoutSession, session_id)
    wt = await _load_workout(session, ws.workout_type_id)

    # Сортируем: сначала обязательные (is_optional=False), потом опциональные.
    # Внутри групп сохраняется исходный порядок (sort_order).
    exercises = sorted(wt.exercises,
                       key=lambda e: (e.is_optional, e.sort_order))

    sets_by_ex = await get_sets_grouped(session, session_id)
    text = render_training_list(wt, exercises, sets_by_ex, ws.started_at)
    kb = training_list_kb(wt.id, session_id, exercises, sets_by_ex)
    return text, kb


def _next_set_num(sets: list[SessionSet]) -> int:
    """Номер следующего подхода (1-based)."""
    return sum(1 for s in sets if s.completed) + 1


async def render_approach_screen(
    session: AsyncSession, session_id: int, ex_id: int
):
    """Готовит (текст, клавиатуру) для экрана подхода/итогов.

    - Кардио: сделано — экран с временем, не сделано — «план».
    - Силовое: не все подходы — экран очередного, все — экран итогов.
    Возвращает None, только если упражнение/сессия недоступны.
    """
    from app.keyboards.workout_kb import cardio_done_kb, strength_summary_kb
    from app.render import render_strength_summary
    from app.utils import format_duration

    ws = await session.get(WorkoutSession, session_id)
    ex = await session.get(Exercise, ex_id)
    if not ws or not ex or ws.finished_at:
        return None

    sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
    completed = [s for s in sets if s.completed]

    # ─── КАРДИО ───
    if ex.kind != "strength":
        can_remove = not completed  # можно убрать, если ещё не сделано
        if completed:
            s = completed[0]
            duration = format_duration(s.duration_seconds) if s.duration_seconds else "—"
            text = (
                f"<b>{ex.name}</b>\n\n"
                f"✅ Выполнено: <b>{duration}</b>\n\n"
                "Можно изменить время, если ошиблись."
            )
            return text, cardio_done_kb(session_id, ex, can_remove=can_remove)
        text = (
            f"<b>{ex.name}</b>\n\n"
            f"План: <b>{format_duration(ex.duration_seconds)}</b>"
        )
        kb = approach_kb(
            session_id, ex, 1, None, None, ex.duration_seconds,
            can_remove=can_remove,
        )
        return text, kb

    # ─── СИЛОВОЕ ───
    plan = ex.sets or 0

    # Все подходы сделаны — экран итогов
    if plan > 0 and len(completed) >= plan:
        text = render_strength_summary(ex, completed)
        kb = strength_summary_kb(session_id, ex, completed)
        return text, kb

    # Иначе — очередной подход
    set_num = len(completed) + 1
    last_set = await get_last_completed_set(session, ws.user_id, ex_id)
    planned_weight = last_set.weight_kg if last_set and last_set.weight_kg else ex.weight_kg
    planned_reps = last_set.reps if last_set and last_set.reps else ex.reps

    # Кнопку «Убрать» показываем всегда, если в этой тренировке ещё не начинали.
    # Логика «удалить или архивировать» — внутри cb_training_remove_ex.
    can_remove = not sets

    text = render_approach(
        ex, set_num, planned_reps, planned_weight, ex.duration_seconds,
        last_weight=last_set.weight_kg if last_set else None,
    )
    kb = approach_kb(
        session_id, ex, set_num, planned_reps, planned_weight,
        ex.duration_seconds, can_remove=can_remove,
    )
    return text, kb

# ═══════════════════════════════════════════════════════════
#  Начать тренировку
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("tr_start:"))
async def cb_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    wt_id = int(callback.data.split(":")[1])
    user = await _get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    wt = await _load_workout(session, wt_id)
    if not wt or wt.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    # Если уже есть активная — предупредить и вернуть в список тренировок
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

    # Создаём новую сессию
    ws = WorkoutSession(
        user_id=user.id,
        workout_type_id=wt_id,
        started_at=datetime.now(timezone.utc),
    )
    session.add(ws)
    await session.commit()
    await session.refresh(ws)

    text, kb = await _render_list(session, ws.id, user.id)
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

    text, kb = await _render_list(session, session_id, ws.user_id)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# ═══════════════════════════════════════════════════════════
#  Открыли упражнение
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("tr_ex:"))
async def cb_open_exercise(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    _, sess_str, ex_str = callback.data.split(":")
    session_id = int(sess_str)
    ex_id = int(ex_str)

    result = await render_approach_screen(session, session_id, ex_id)
    if result is None:
        # всё сделано или недоступно — в список
        ws = await session.get(WorkoutSession, session_id)
        if not ws:
            return await callback.answer("Недоступно", show_alert=True)
        text, kb = await _render_list(session, session_id, ws.user_id)
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()
        return

    text, kb = result
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# ═══════════════════════════════════════════════════════════
#  Сохранение подхода «как планировал»
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("tr_save_planned:"))
async def cb_save_planned(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    # 1. СРАЗУ отвечаем Telegram, чтобы убрать часики с кнопки
    await callback.answer("✅ Сохранено")
    await state.clear()

    _, sess_str, ex_str = callback.data.split(":")
    session_id = int(sess_str)
    ex_id = int(ex_str)

    ws = await session.get(WorkoutSession, session_id)
    ex = await session.get(Exercise, ex_id)
    if not ws or not ex:
        return

    sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
    set_num = _next_set_num(sets)

    # Определяем плановые значения
    last_set = await get_last_completed_set(session, ws.user_id, ex_id)
    planned_weight = last_set.weight_kg if last_set and last_set.weight_kg else ex.weight_kg
    planned_reps = last_set.reps if last_set and last_set.reps else ex.reps

    new_set = SessionSet(
        session_id=session_id,
        exercise_id=ex_id,
        set_number=set_num,
        reps=planned_reps if ex.kind == "strength" else None,
        weight_kg=planned_weight if ex.kind == "strength" else None,
        duration_seconds=ex.duration_seconds if ex.kind != "strength" else None,
        completed=True,
    )
    session.add(new_set)
    await session.commit()

    # Собираем обновлённый список подходов
    all_sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
    done = sum(1 for s in all_sets if s.completed)
    plan = ex.sets or 1 if ex.kind == "strength" else 1

    # 2. Теперь спокойно обновляем сообщение (без вызова других хэндлеров)
    if done >= plan:
        if ex.kind == "strength":
            completed_now = [s for s in all_sets if s.completed]
            text = render_strength_summary(ex, completed_now)
            kb = strength_summary_kb(session_id, ex, completed_now)
            await callback.message.edit_text(
                f"✅ {ex.name} готово\n\n" + text, reply_markup=kb
            )
        else:
            result_screen = await render_approach_screen(session, session_id, ex.id)
            if result_screen:
                text, kb = result_screen
                await callback.message.edit_text(text, reply_markup=kb)
            else:
                text, kb = await _render_list(session, session_id, ws.user_id)
                await callback.message.edit_text(text, reply_markup=kb)
    else:
        # Показываем следующий подход
        result = await render_approach_screen(session, session_id, ex_id)
        if result is None:
            text, kb = await _render_list(session, session_id, ws.user_id)
            await callback.message.edit_text(text, reply_markup=kb)
        else:
            text, kb = result
            await callback.message.edit_text(text, reply_markup=kb)


# ═══════════════════════════════════════════════════════════
#  Ввод фактических значений (FSM)
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("tr_custom:"))
async def cb_custom_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    from app.keyboards.workout_kb import cancel_kb

    _, sess_str, ex_str = callback.data.split(":")
    session_id = int(sess_str)
    ex_id = int(ex_str)

    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    # Для кардио: если уже есть completed подход — редактируем, а не создаём
    existing_id = None
    if ex.kind != "strength":
        sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
        completed = [s for s in sets if s.completed]
        if completed:
            existing_id = completed[0].id

    await state.update_data(
        session_id=session_id,
        ex_id=ex_id,
        editing_set_id=existing_id,      # ← None если создаём новый
        return_to="tr_ex_card",
    )

    if ex.kind == "strength":
        await state.set_state(TrainingFSM.entering_reps)
        await callback.message.edit_text(
            f"<b>{ex.name}</b>\n\nСколько повторов сделал? Введи число:",
            reply_markup=cancel_kb(),
        )
    else:
        await state.set_state(TrainingFSM.entering_duration)

        if existing_id:
            # Редактирование — показываем «Сейчас: X мин»
            current_set = await session.get(SessionSet, existing_id)
            current_text = (
                format_duration(current_set.duration_seconds)
                if current_set and current_set.duration_seconds
                else "не задано"
            )
            await callback.message.edit_text(
                f"<b>{ex.name}</b>\n\n"
                f"Сейчас: <b>{current_text}</b>\n\n"
                "Введи новое время в минутах (можно 1.5 = 1 мин 30 сек):",
                reply_markup=cancel_kb(),
            )
        else:
            # Первое выполнение — показываем «План: X мин»
            plan_text = (
                format_duration(ex.duration_seconds)
                if ex.duration_seconds
                else "по факту"
            )
            await callback.message.edit_text(
                f"<b>{ex.name}</b>\n\n"
                f"План: <b>{plan_text}</b>\n\n"
                "Сколько минут заняло? Введи число "
                "(можно 1.5 = 1 мин 30 сек):",
                reply_markup=cancel_kb(),
            )
    await callback.answer()


@router.callback_query(F.data.startswith("tr_edit_set:"))
async def cb_edit_set(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Редактирование существующего подхода (силовое)."""

    _, sess_str, set_str = callback.data.split(":")
    session_id = int(sess_str)
    set_id = int(set_str)

    target = await session.get(SessionSet, set_id)
    if not target:
        return await callback.answer("Подход не найден", show_alert=True)

    ex = await session.get(Exercise, target.exercise_id)
    if not ex:
        return await callback.answer("Упражнение не найдено", show_alert=True)

    weight_text = format_weight(target.weight_kg)

    await state.update_data(
        session_id=session_id,
        ex_id=ex.id,
        editing_set_id=set_id,
        return_to="tr_strength_summary",
    )
    await state.set_state(TrainingFSM.entering_reps)
    await callback.message.edit_text(
        f"<b>{ex.name}</b> — подход {target.set_number}\n\n"
        f"Сейчас: <b>{target.reps} × {weight_text}</b>\n\n"
        "Сколько повторов сделал на самом деле? Введи число:",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tr_add_set:"))
async def cb_add_set(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Добавление подхода сверх плана (силовое)."""
    from app.keyboards.workout_kb import cancel_kb

    _, sess_str, ex_str = callback.data.split(":")
    session_id = int(sess_str)
    ex_id = int(ex_str)

    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    await state.update_data(
        session_id=session_id,
        ex_id=ex_id,
        editing_set_id=None,   # ← создаём новый
        return_to="tr_strength_summary",
    )
    await state.set_state(TrainingFSM.entering_reps)
    await callback.message.edit_text(
        f"<b>{ex.name}</b> — новый подход\n\n"
        "Сколько повторов сделал? Введи число:",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(TrainingFSM.entering_reps)
async def fsm_enter_reps(message: Message, state: FSMContext, session: AsyncSession):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        return await message.answer(
            "Нужно целое число > 0. Попробуй ещё:",
            reply_markup=cancel_kb(),
        )

    data = await state.get_data()
    await state.update_data(custom_reps=int(text))

    # Теперь спросим вес
    await state.set_state(TrainingFSM.entering_weight)
    ex = await session.get(Exercise, data["ex_id"])
    ws = await session.get(WorkoutSession, data["session_id"])
    last_set = await get_last_completed_set(session, ws.user_id, data["ex_id"])
    suggested = last_set.weight_kg if last_set and last_set.weight_kg else ex.weight_kg
    suggestion = format_weight(suggested) if suggested else "без веса"
    await message.answer(
        f"Сколько весил снаряд?\n"
        f"<i>По умолчанию: {suggestion}</i>\n\n"
        "Введи число (например <code>15</code>) или текст (например <code>Своё тело</code>).\n"
        "Или отправь <code>-</code>, чтобы без веса:",
        reply_markup=cancel_kb(),
    )


@router.message(TrainingFSM.entering_weight)
async def fsm_enter_weight(message: Message, state: FSMContext,
                           session: AsyncSession):
    data = await state.get_data()
    text = message.text.strip()

    if text in {"-", "0", "0.0", "нет"}:
        weight = None
    else:
        weight = text.replace(",", ".")

    await _save_custom_set(message, state, session, data,
                           data.get("custom_reps"), weight)


@router.message(TrainingFSM.entering_duration)
async def fsm_enter_duration(message: Message, state: FSMContext, session: AsyncSession):
    text = message.text.strip()
    if text == "-":
        seconds = None
    else:
        seconds = parse_minutes_to_seconds(text)
        if seconds is None:
            return await message.answer(
                "Нужно целое число > 0. Попробуй ещё:",
                reply_markup=cancel_kb(),
            )

    data = await state.get_data()
    await _save_custom_set(message, state, session, data, None, None, duration=seconds)


async def _save_custom_set(message: Message, state: FSMContext, session: AsyncSession,
                           data: dict, reps: int | None, weight: float | None,
                           duration: int | None = None):
    """Сохраняет подход: создаёт новый или обновляет существующий (editing_set_id)."""
    from app.utils import format_duration

    session_id = data["session_id"]
    ex_id = data["ex_id"]
    editing_set_id = data.get("editing_set_id")

    ex = await session.get(Exercise, ex_id)

    if editing_set_id:
        # ─── ОБНОВЛЕНИЕ существующего подхода ───
        target = await session.get(SessionSet, editing_set_id)
        if not target:
            await state.clear()
            return await message.answer("Подход не найден.")

        # Запоминаем «было»
        old_reps = target.reps
        old_weight = target.weight_kg
        old_duration = target.duration_seconds

        # Применяем «стало»
        target.reps = reps
        target.weight_kg = weight
        target.duration_seconds = duration
        await session.commit()

        # Формируем сообщение «было → стало»
        parts = []
        if ex.kind == "strength":
            if old_reps != reps:
                parts.append(f"повторы: <b>{old_reps} → {reps}</b>")
            if old_weight != weight:
                ow = format_weight(old_weight)
                nw = format_weight(weight)
                parts.append(f"вес: <b>{ow} → {nw}</b>")
        else:
            if old_duration != duration:
                od = format_duration(old_duration)
                nd = format_duration(duration)
                parts.append(f"время: <b>{od} → {nd}</b>")

        if not parts:
            change_text = "✅ Сохранено (без изменений)."
        else:
            change_text = "✅ Обновлено.\n" + "\n".join(parts)

        await state.clear()

        # Для силового — экран итогов упражнения
        if ex.kind == "strength":
            sets_now = (await get_sets_grouped(session, session_id)).get(ex_id, [])
            completed_now = [s for s in sets_now if s.completed]
            text = render_strength_summary(ex, completed_now)
            kb = strength_summary_kb(session_id, ex, completed_now)
            await message.answer(change_text + "\n\n" + text, reply_markup=kb)
            return

        # Кардио — экран «выполнено» с возможностью изменить ещё раз
        result_screen = await render_approach_screen(session, session_id, ex_id)
        if result_screen:
            text, kb = result_screen
            await message.answer(change_text + "\n\n" + text, reply_markup=kb)
        else:
            ws = await session.get(WorkoutSession, session_id)
            text, kb = await _render_list(session, session_id, ws.user_id)
            await message.answer(change_text + "\n\n" + text, reply_markup=kb)
        return

    # ─── СОЗДАНИЕ нового подхода ───
    sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
    set_num = _next_set_num(sets)

    new_set = SessionSet(
        session_id=session_id,
        exercise_id=ex_id,
        set_number=set_num,
        reps=reps,
        weight_kg=weight,
        duration_seconds=duration,
        completed=True,
    )
    session.add(new_set)
    await session.commit()

    all_sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
    done = sum(1 for s in all_sets if s.completed)
    plan = (ex.sets or 1) if ex.kind == "strength" else 1

    await state.clear()

    if done >= plan:
        # Всё сделано — экран итогов (для силового) / список (для кардио)
        if ex.kind == "strength":
            completed_now = [s for s in all_sets if s.completed]
            text = render_strength_summary(ex, completed_now)
            kb = strength_summary_kb(session_id, ex, completed_now)
            await message.answer(f"✅ {ex.name} готово\n\n" + text, reply_markup=kb)
        else:
            # Кардио: экран «выполнено» с возможностью изменить время
            result_screen = await render_approach_screen(session, session_id,
                                                         ex.id)
            if result_screen:
                text, kb = result_screen
                await message.answer(text, reply_markup=kb)
            else:
                ws = await session.get(WorkoutSession, session_id)
                text, kb = await _render_list(session, session_id, ws.user_id)
                await message.answer(text, reply_markup=kb)
        return

    # Ещё не всё — показываем следующий подход (только для силового)
    ws = await session.get(WorkoutSession, session_id)
    last_set = await get_last_completed_set(session, ws.user_id, ex_id)
    planned_weight = last_set.weight_kg if last_set and last_set.weight_kg else ex.weight_kg
    planned_reps = last_set.reps if last_set and last_set.reps else ex.reps
    next_num = done + 1

    text = render_approach(
        ex, next_num, planned_reps, planned_weight, ex.duration_seconds,
        last_weight=last_set.weight_kg if last_set else None,
    )
    kb = approach_kb(session_id, ex, next_num, planned_reps, planned_weight, ex.duration_seconds)
    await message.answer(text, reply_markup=kb)


# ═══════════════════════════════════════════════════════════
#  Пропустить упражнение
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("tr_skip:"))
async def cb_skip(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    _, sess_str, ex_str = callback.data.split(":")
    session_id = int(sess_str)

    ws = await session.get(WorkoutSession, session_id)
    if not ws:
        return await callback.answer("Не найдено", show_alert=True)

    text, kb = await _render_list(session, session_id, ws.user_id)
    await callback.message.edit_text("⏭ Пропущено\n\n" + text, reply_markup=kb)
    await callback.answer()


# ═══════════════════════════════════════════════════════════
#  Завершение тренировки
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("tr_finish:"))
async def cb_finish_ask(callback: CallbackQuery, session: AsyncSession):
    session_id = int(callback.data.split(":")[1])
    ws = await session.get(WorkoutSession, session_id)
    if not ws:
        return await callback.answer("Не найдено", show_alert=True)

    # Считаем невыполненные
    wt = await _load_workout(session, ws.workout_type_id)
    sets_by_ex = await get_sets_grouped(session, session_id)

    total_ex = 0
    not_done = 0
    for ex in wt.exercises:
        sets = sets_by_ex.get(ex.id, [])
        done = sum(1 for s in sets if s.completed)
        plan = (ex.sets or 0) if ex.kind == "strength" else 1
        is_done = done >= plan

        if not ex.is_optional or done > 0:
            total_ex += 1
            if not is_done:
                not_done += 1

    if not_done > 0:
        text = (
            f"🏁 <b>Завершить тренировку?</b>\n\n"
            f"⚠️ Не выполнено: <b>{not_done} из {total_ex}</b> упражнений.\n\n"
            "Тренировка сохранится в истории, но по этим упражнениям "
            "не будет записано ни одного подхода.\n\n"
            "Точно завершить?"
        )
    else:
        text = (
            "🏁 <b>Завершить тренировку?</b>\n\n"
            "✅ Все упражнения выполнены. Отличная работа!"
        )

    await callback.message.edit_text(text, reply_markup=finish_confirm_kb(session_id))
    await callback.answer()


@router.callback_query(F.data.startswith("tr_finish_yes:"))
async def cb_finish_confirm(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    import random

    await state.clear()
    session_id = int(callback.data.split(":")[1])
    ws = await session.get(WorkoutSession, session_id)
    if not ws:
        return await callback.answer("Не найдено", show_alert=True)

    ws.finished_at = datetime.now(timezone.utc)
    await session.commit()

    wt = await _load_workout(session, ws.workout_type_id)
    sets_by_ex = await get_sets_grouped(session, session_id)

    # ── 1. Подсчёт прогресса: опциональные не портят статистику ──
    total_ex = 0
    done_ex = 0
    for ex in wt.exercises:
        sets = sets_by_ex.get(ex.id, [])
        done = sum(1 for s in sets if s.completed)
        plan = (ex.sets or 0) if ex.kind == "strength" else 1
        is_done = done >= plan

        # Обязательные всегда в знаменателе, опциональные — только если начаты
        if not ex.is_optional or done > 0:
            total_ex += 1
        if is_done:
            done_ex += 1

    ratio = done_ex / total_ex if total_ex else 0

    duration_sec = int((ws.finished_at - ws.started_at).total_seconds())
    minutes = duration_sec // 60

    # ── 2. Инициализация списка строк отчёта ──
    # ВАЖНО: lines объявляется ДО цикла, ниже цикл дописывает в него
    lines = [
        f"🏁 <b>{wt.name}</b> — завершена!",
        "",
        f"⏱ Длительность: ~{minutes} мин",
        f"📊 Выполнено: {done_ex} из {total_ex} упражнений",
        "",
    ]

    # ── 3. Строки по каждому упражнению ──
    for ex in wt.exercises:
        sets = sets_by_ex.get(ex.id, [])
        done = sum(1 for s in sets if s.completed)
        plan = (ex.sets or 0) if ex.kind == "strength" else 1
        is_done = done >= plan

        if is_done:
            lines.append(f"✅ {ex.name}")
        elif done > 0:
            lines.append(f"🟡 {ex.name}: {done}/{plan}")
        elif ex.is_optional:
            lines.append(f"⚪ {ex.name} <i>(опц., пропущено — так и планировалось)</i>")
        else:
            lines.append(f"⚪ {ex.name}")

    # ── 4. Вариативная концовка ──
    if ratio >= 1.0:
        phrases = [
            "🏆 Идеальная тренировка! Все упражнения выполнены.",
            "🔥 Ты на пике формы! 100% выполнения.",
            "💎 Безупречно! Так держать.",
        ]
    elif ratio >= 0.7:
        phrases = [
            "💪 Отличная работа! Большая часть программы сделана.",
            "🔥 Хороший результат — прогресс налицо.",
            "👊 Ты выложился! Продолжай в том же духе.",
        ]
    elif ratio >= 0.4:
        phrases = [
            "👍 Хорошо поработал! Каждый подход важен.",
            "📈 Ты движешься вперёд. Не останавливайся.",
            "💡 Половина пути пройдена — продолжай!",
        ]
    else:
        phrases = [
            "🌱 Главное — не сдаваться. Каждый шаг важен.",
            "🚶 Лучше что-то, чем ничего. Ты начал!",
            "⏳ Сегодня так, завтра — больше. Главное — регулярность.",
        ]

    lines.append("")
    lines.append(f"<i>{random.choice(phrases)}</i>")

    # ── 5. Отправка ──
    from app.keyboards.workout_kb import after_finish_kb
    await callback.message.edit_text("\n".join(lines), reply_markup=after_finish_kb())
    await callback.answer("Тренировка завершена")


# ═══════════════════════════════════════════════════════════
#  Добавление упражнения во время тренировки
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("tr_ex_add:"))
async def cb_training_add_ex(callback: CallbackQuery, session: AsyncSession,
                             state: FSMContext):
    """Переходим в FSM создания упражнения, но с возвратом в тренировку."""
    from app.keyboards.workout_kb import choose_kind_kb
    from app.states import WorkoutCreate

    session_id = int(callback.data.split(":")[1])
    ws = await session.get(WorkoutSession, session_id)
    if not ws or ws.finished_at:
        return await callback.answer("Тренировка не активна", show_alert=True)

    user = await _get_user(session, callback.from_user.id)
    if not user or ws.user_id != user.id:
        return await callback.answer("Не найдено", show_alert=True)

    # Ключевой момент: запоминаем, куда вернуться
    await state.update_data(
        wt_id=ws.workout_type_id,
        return_to_session=session_id,
        return_to="tr_list",
    )
    await state.set_state(WorkoutCreate.adding_exercise_kind)
    await callback.message.edit_text(
        "Какой тип упражнения?",
        reply_markup=choose_kind_kb(ws.workout_type_id)
    )
    await callback.answer()


# ═══════════════════════════════════════════════════════════
#  Удаление упражнения из шаблона во время тренировки
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("tr_remove:"))
async def cb_training_remove_ex(callback: CallbackQuery, session: AsyncSession):
    """Убираем упражнение из шаблона.

    - Нет истории → удалить физически
    - Есть история → архивировать (скрыть из шаблона, история остаётся)

    Работает из двух мест:
    - карточка упражнения (callback без :menu)
    - экран «Убрать упражнение» (callback с :menu)
    """
    from sqlalchemy import func as sa_func

    parts = callback.data.split(":")
    session_id = int(parts[1])
    ex_id = int(parts[2])
    from_menu = len(parts) > 3 and parts[3] == "menu"

    ws = await session.get(WorkoutSession, session_id)
    ex = await session.get(Exercise, ex_id)
    if not ws or not ex or ws.finished_at:
        return await callback.answer("Недоступно", show_alert=True)

    # Защита: если в этой тренировке уже начали — убирать нельзя, только пропустить
    current_sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
    if current_sets:
        return await callback.answer(
            "По упражнению уже есть подходы в этой тренировке. "
            "Используйте «⏭ Пропустить».",
            show_alert=True,
        )

    name = ex.name
    history_count = await session.scalar(
        select(sa_func.count())
        .select_from(SessionSet)
        .where(SessionSet.exercise_id == ex_id)
    ) or 0

    if history_count > 0:
        # Архивируем — история сохраняется
        ex.is_archived = True
        await session.commit()
        action = "📦 Убрано из шаблона (история сохранена)"
    else:
        # Удаляем физически
        await session.delete(ex)
        await session.commit()
        action = "🗑 Удалено"

    # ─── Возврат: в меню удаления или в список тренировки ───
    if from_menu:
        wt = await _load_workout(session, ws.workout_type_id)
        sets_by_ex = await get_sets_grouped(session, session_id)

        # Пересобираем список «что ещё можно убрать» — все без подходов в текущей
        removable = [e for e in wt.exercises if not sets_by_ex.get(e.id)]

        if removable:
            await callback.message.edit_text(
                f"{action}: <b>{name}</b>\n\nМожно убрать ещё:",
                reply_markup=training_remove_menu_kb(session_id, removable),
            )
        else:
            text, kb = await _render_list(session, session_id, ws.user_id)
            await callback.message.edit_text(
                f"{action}: <b>{name}</b>\n\n" + text, reply_markup=kb
            )
        await callback.answer("Готово")
        return

    text, kb = await _render_list(session, session_id, ws.user_id)
    await callback.message.edit_text(
        f"{action}: <b>{name}</b>\n\n" + text, reply_markup=kb
    )
    await callback.answer("Готово")


@router.callback_query(F.data.startswith("tr_remove_menu:"))
async def cb_training_remove_menu(callback: CallbackQuery, session: AsyncSession):
    """Экран «Убрать упражнение» — все, где в ЭТОЙ тренировке ещё нет подходов."""
    session_id = int(callback.data.split(":")[1])
    ws = await session.get(WorkoutSession, session_id)
    if not ws or ws.finished_at:
        return await callback.answer("Тренировка не активна", show_alert=True)

    wt = await _load_workout(session, ws.workout_type_id)
    sets_by_ex = await get_sets_grouped(session, session_id)

    # Все упражнения, по которым в этой сессии ещё не было подходов
    removable = [ex for ex in wt.exercises if not sets_by_ex.get(ex.id)]

    if not removable:
        text, kb = await _render_list(session, session_id, ws.user_id)
        reason = (
            "Все упражнения уже начаты в этой тренировке."
            if wt.exercises
            else "В тренировке нет упражнений."
        )
        await callback.message.edit_text(
            f"{reason}\n\n" + text, reply_markup=kb
        )
        return await callback.answer()

    await callback.message.edit_text(
        "🗑 <b>Убрать упражнение из шаблона</b>\n\n"
        "Оно пропадёт из этой и будущих тренировок. "
        "Если есть история выполнения — она сохранится.\n\n"
        "Если просто хочешь пропустить сейчас — вернись и нажми на упражнение → «⏭ Пропустить».",
        reply_markup=training_remove_menu_kb(session_id, removable),
    )
    await callback.answer()
