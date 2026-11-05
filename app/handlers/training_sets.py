"""Хэндлеры для сохранения подходов (кнопки «Как планировал» и «Ввести фактически»)."""
from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Exercise, SessionSet, WorkoutSession
from app.db.queries import get_last_completed_set, get_sets_grouped
from app.keyboards.workout_kb import approach_kb, cancel_kb, edit_set_kb
from app.render import render_approach
from app.services.training_service import (
    next_set_num, render_approach_screen, render_list,
)
from app.states import TrainingFSM
from app.utils import format_duration, format_weight, parse_minutes_to_seconds

router = Router()


@router.callback_query(F.data.startswith("tr_save_planned:"))
async def cb_save_planned(callback: CallbackQuery, session: AsyncSession,
                          state: FSMContext):
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
    set_num = next_set_num(sets)

    # Определяем плановые значения
    last_set = await get_last_completed_set(session, ws.user_id, ex_id)
    planned_weight = last_set.weight_kg if last_set and last_set.weight_kg else ex.weight_kg
    planned_reps = last_set.reps if last_set and last_set.reps else ex.reps

    if ex.kind != "strength":
        planned_duration = last_set.duration_seconds if last_set and last_set.duration_seconds else ex.duration_seconds
    else:
        planned_duration = None

    new_set = SessionSet(
        session_id=session_id,
        exercise_id=ex_id,
        set_number=set_num,
        reps=planned_reps if ex.kind == "strength" else None,
        weight_kg=planned_weight if ex.kind == "strength" else None,
        duration_seconds=planned_duration,
        completed=True,
        completed_at=datetime.now(timezone.utc)
    )
    session.add(new_set)
    await session.commit()

    # Обновляем экран (следующий подход или итоги)
    result_screen = await render_approach_screen(session, session_id, ex.id)
    if result_screen:
        text, kb = result_screen
        await callback.message.edit_text(text, reply_markup=kb)
    else:
        text, kb = await render_list(session, session_id, ws.user_id)
        await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("tr_custom:"))
async def cb_custom_start(callback: CallbackQuery, session: AsyncSession,
                          state: FSMContext):
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
        editing_set_id=existing_id,
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
            plan_text = format_duration(
                ex.duration_seconds) if ex.duration_seconds else "по факту"
            await callback.message.edit_text(
                f"<b>{ex.name}</b>\n\n"
                f"План: <b>{plan_text}</b>\n\n"
                "Сколько минут заняло? Введи число (можно 1.5 = 1 мин 30 сек):",
                reply_markup=cancel_kb(),
            )
    await callback.answer()


@router.message(TrainingFSM.entering_reps)
async def fsm_enter_reps(message: Message, state: FSMContext,
                         session: AsyncSession):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        return await message.answer("Нужно целое число > 0. Попробуй ещё:",
                                    reply_markup=cancel_kb())

    data = await state.get_data()
    await state.update_data(custom_reps=int(text))

    await state.set_state(TrainingFSM.entering_weight)

    editing_set_id = data.get("editing_set_id")

    if editing_set_id:
        # Если редактируем существующий подход — берем ЕГО вес
        target = await session.get(SessionSet, editing_set_id)
        suggested = target.weight_kg if target else None
        prefix = "Сейчас"
    else:
        # Если делаем новый — берем из прошлой тренировки или плана
        ex = await session.get(Exercise, data["ex_id"])
        ws = await session.get(WorkoutSession, data["session_id"])
        last_set = await get_last_completed_set(session, ws.user_id,
                                                data["ex_id"])
        suggested = last_set.weight_kg if last_set and last_set.weight_kg else ex.weight_kg
        prefix = "По умолчанию"

    suggestion = format_weight(suggested) if suggested else "без веса"

    await message.answer(
        f"Сколько весил снаряд?\n"
        f"<i>{prefix}: {suggestion}</i>\n\n"
        "Введи число или текст (например «Своё тело»). Или отправь «-», чтобы без веса:",
        reply_markup=cancel_kb(),
    )


@router.message(TrainingFSM.entering_weight)
async def fsm_enter_weight(message: Message, state: FSMContext,
                           session: AsyncSession):
    text = message.text.strip()
    if text in {"-", "0", "0.0", "нет"}:
        weight = None
    else:
        weight = text.replace(",", ".")

    data = await state.get_data()
    await _save_custom_set(message, state, session, data,
                           data.get("custom_reps"), weight)


@router.message(TrainingFSM.entering_duration)
async def fsm_enter_duration(message: Message, state: FSMContext,
                             session: AsyncSession):
    text = message.text.strip()
    if text in {"-", "0"}:
        seconds = None
    else:
        seconds = parse_minutes_to_seconds(text)
        if seconds is None:
            return await message.answer(
                "Нужно положительное число или «-». Попробуй ещё:",
                reply_markup=cancel_kb())

    data = await state.get_data()
    await _save_custom_set(message, state, session, data, None, None,
                           duration=seconds)


async def _save_custom_set(message: Message, state: FSMContext,
                           session: AsyncSession,
                           data: dict, reps: int | None, weight: str | None,
                           duration: int | None = None):
    """Создаёт новый или обновляет существующий подход."""
    session_id = data["session_id"]
    ex_id = data["ex_id"]
    editing_set_id = data.get("editing_set_id")

    ex = await session.get(Exercise, ex_id)

    if editing_set_id:
        target = await session.get(SessionSet, editing_set_id)
        if not target:
            await state.clear()
            return await message.answer("Подход не найден.")

        old_reps = target.reps
        old_weight = target.weight_kg
        old_duration = target.duration_seconds

        target.reps = reps
        target.weight_kg = weight
        target.duration_seconds = duration
        target.completed_at = datetime.now(timezone.utc)
        await session.commit()

        parts = []
        if ex.kind == "strength":
            if old_reps != reps:
                parts.append(f"повторы: <b>{old_reps} → {reps}</b>")
            if old_weight != weight:
                parts.append(
                    f"вес: <b>{format_weight(old_weight)} → {format_weight(weight)}</b>")
        else:
            if old_duration != duration:
                parts.append(
                    f"время: <b>{format_duration(old_duration)} → {format_duration(duration)}</b>")

        change_text = "✅ Обновлено.\n" + "\n".join(
            parts) if parts else "✅ Сохранено (без изменений)."
        await state.clear()

        result_screen = await render_approach_screen(session, session_id,
                                                     ex_id)
        if result_screen:
            text, kb = result_screen
            await message.answer(change_text + "\n\n" + text, reply_markup=kb)
        else:
            ws = await session.get(WorkoutSession, session_id)
            text, kb = await render_list(session, session_id, ws.user_id)
            await message.answer(change_text + "\n\n" + text, reply_markup=kb)
        return

    # Создание нового подхода
    sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
    set_num = next_set_num(sets)

    new_set = SessionSet(
        session_id=session_id,
        exercise_id=ex_id,
        set_number=set_num,
        reps=reps,
        weight_kg=weight,
        duration_seconds=duration,
        completed=True,
        completed_at=datetime.now(timezone.utc)
    )
    session.add(new_set)
    await session.commit()

    all_sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
    done = sum(1 for s in all_sets if s.completed)
    plan = (ex.sets or 1) if ex.kind == "strength" else 1

    await state.clear()

    if done >= plan:
        result_screen = await render_approach_screen(session, session_id,
                                                     ex.id)
        if result_screen:
            text, kb = result_screen
            await message.answer(f"✅ {ex.name} готово\n\n" + text,
                                 reply_markup=kb)
        else:
            ws = await session.get(WorkoutSession, session_id)
            text, kb = await render_list(session, session_id, ws.user_id)
            await message.answer(text, reply_markup=kb)
        return

    ws = await session.get(WorkoutSession, session_id)
    last_set = await get_last_completed_set(session, ws.user_id, ex_id)
    planned_weight = last_set.weight_kg if last_set and last_set.weight_kg else ex.weight_kg
    planned_reps = last_set.reps if last_set and last_set.reps else ex.reps
    next_num = done + 1

    text = render_approach(
        ex, next_num, planned_reps, planned_weight, ex.duration_seconds,
        last_weight=last_set.weight_kg if last_set else None,
    )
    kb = approach_kb(session_id, ex, next_num, planned_reps, planned_weight,
                     ex.duration_seconds)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("tr_edit_set:"))
async def cb_edit_set(callback: CallbackQuery, session: AsyncSession,
                      state: FSMContext):
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

    # Разрешаем удаление ТОЛЬКО если это подход сверх плана
    plan = ex.sets or 0
    can_delete = (ex.kind == "strength") and (target.set_number > plan)

    await state.update_data(
        session_id=session_id,
        ex_id=ex.id,
        editing_set_id=set_id,
        return_to="tr_strength_summary",
    )
    await state.set_state(TrainingFSM.entering_reps)
    await callback.message.edit_text(
        f"<b>{ex.name}</b> — подход {target.set_number}\n\n"
        f"Сейчас:\n<b><code>{target.reps} × {weight_text}</code></b>\n\n"
        "Сколько повторов сделал на самом деле? Введи число:",
        reply_markup=edit_set_kb(session_id, set_id, can_delete=can_delete),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tr_add_set:"))
async def cb_add_set(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Добавление подхода сверх плана (силовое)."""
    _, sess_str, ex_str = callback.data.split(":")
    session_id = int(sess_str)
    ex_id = int(ex_str)

    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    await state.update_data(
        session_id=session_id,
        ex_id=ex_id,
        editing_set_id=None,   # создаём новый
        return_to="tr_strength_summary",
    )
    await state.set_state(TrainingFSM.entering_reps)
    await callback.message.edit_text(
        f"<b>{ex.name}</b> — новый подход\n\n"
        "Сколько повторов сделал? Введи число:",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tr_delete_set:"))
async def cb_delete_set(callback: CallbackQuery, session: AsyncSession,
                        state: FSMContext):
    await state.clear()
    _, sess_str, set_str = callback.data.split(":")
    session_id = int(sess_str)
    set_id = int(set_str)

    target = await session.get(SessionSet, set_id)
    if not target:
        return await callback.answer("Подход уже удален", show_alert=True)

    ex_id = target.exercise_id
    await session.delete(target)
    await session.commit()

    # Перенумеровываем оставшиеся подходы, чтобы они шли 1, 2, 3... (без дырок)
    sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
    for idx, s in enumerate(sets, start=1):
        s.set_number = idx
    await session.commit()

    # Возвращаемся на экран подхода/итогов
    result = await render_approach_screen(session, session_id, ex_id)
    if result:
        text, kb = result
        await callback.message.edit_text("🗑 Подход удален.\n\n" + text,
                                         reply_markup=kb)
    else:
        ws = await session.get(WorkoutSession, session_id)
        text, kb = await render_list(session, session_id, ws.user_id)
        await callback.message.edit_text("🗑 Подход удален.\n\n" + text,
                                         reply_markup=kb)

    await callback.answer("Подход удален")
