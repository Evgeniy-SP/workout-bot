"""Хэндлеры для сохранения подходов (кнопки «Как планировал» и «Ввести фактически»)."""
from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Exercise, SessionSet, WorkoutSession
from app.db.queries import get_last_completed_set, get_sets_grouped
from app.keyboards.workout_kb import (
    cancel_kb,
    edit_set_kb,
    numeric_keypad_kb,
    weight_keypad_kb,
    text_weight_kb,
)
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

    # Проверяем, редактируем мы существующий подход или создаем новый
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
        temp_num="",  # <-- Очищаем буфер для цифр
        temp_weight=""  # <-- Очищаем буфер для веса
    )

    if ex.kind == "strength":
        # Достаем данные для подсказки
        sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
        completed = [s for s in sets if s.completed]
        set_num = len(completed) + 1

        await state.set_state(TrainingFSM.entering_reps)

        # Получаем подсказку по прошлому разу
        ws = await session.get(WorkoutSession, session_id)
        last_set = await get_last_completed_set(session, ws.user_id, ex_id,
                                                current_session_id=session_id)

        if last_set:
            history = f"🕰 Прошлый раз: <b>{last_set.reps} × {format_weight(last_set.weight_kg)}</b>"
        else:
            history = f"📋 План: <b>{ex.reps} × {format_weight(ex.weight_kg)}</b>"

        # Выводим красивый текст с подсказкой и цифровую клавиатуру
        await callback.message.edit_text(
            f"🏋️ <b>{ex.name}</b> — подход {set_num}\n\n"
            f"{history}\n\n"
            f"Сколько повторов сделал? Введи число:",
            reply_markup=numeric_keypad_kb()
        )

    else:
        # Логика для КАРДИО (остается без изменений)
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
                reply_markup=weight_keypad_kb(prefix="t_num"),
            )
        else:
            plan_text = format_duration(
                ex.duration_seconds) if ex.duration_seconds else "по факту"
            await callback.message.edit_text(
                f"<b>{ex.name}</b>\n\n"
                f"План: <b>{plan_text}</b>\n\n"
                "Сколько минут заняло? Введи число (можно 1.5 = 1 мин 30 сек):",
                reply_markup=weight_keypad_kb(prefix="t_num"),
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

    # Получаем подсказку по весу
    ex = await session.get(Exercise, data["ex_id"])
    ws = await session.get(WorkoutSession, data["session_id"])

    last_set = await get_last_completed_set(session, ws.user_id, data["ex_id"])
    suggested = last_set.weight_kg if last_set and last_set.weight_kg else ex.weight_kg
    suggestion = format_weight(suggested) if suggested else "без веса"

    await state.set_state(TrainingFSM.entering_weight)

    # Выводим с названием упражнения для ширины
    await message.answer(
        f"🏋️ <b>{ex.name}</b>\n\n"
        f"Повторов: <b>{text}</b>.\n"
        f"Теперь введи вес (снаряд).\n"
        f"<i>По умолчанию:</i> <code>{suggestion}</code>\n\n"
        f"<i>(Нажми на значение по умолчанию, чтобы скопировать)</i>",
        reply_markup=weight_keypad_kb()
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
    from datetime import datetime, timezone
    from app.db.models import SessionSet, WorkoutSession, Exercise
    from app.db.queries import get_sets_grouped
    from app.services.training_service import render_approach_screen, \
        render_list

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
                from app.utils import format_weight
                parts.append(
                    f"вес: <b>{format_weight(old_weight)} → {format_weight(weight)}</b>")
        else:
            if old_duration != duration:
                from app.utils import format_duration
                parts.append(
                    f"время: <b>{format_duration(old_duration)} → {format_duration(duration)}</b>")

        if parts:
            change_text = f"✅ <b>Подход {target.set_number} обновлен.</b>\n" + "\n".join(
                parts)
        else:
            change_text = f"✅ <b>Подход {target.set_number}: сохранено (без изменений).</b>"

        await state.clear()

        # Используем единую функцию для отрисовки
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
    from app.services.training_service import next_set_num
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

    # ВАЖНО: Вместо ручного кода, вызываем нашу единую умную функцию!
    result_screen = await render_approach_screen(session, session_id, ex_id)
    if result_screen:
        text, kb = result_screen
        await message.answer(text, reply_markup=kb)
    else:
        ws = await session.get(WorkoutSession, session_id)
        text, kb = await render_list(session, session_id, ws.user_id)
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

    await state.update_data(
        session_id=session_id,
        ex_id=ex.id,
        editing_set_id=set_id,
        return_to="tr_strength_summary",
        temp_num=""  # <-- ОЧИСТИЛИ БУФЕР
    )
    await state.set_state(TrainingFSM.entering_reps)

    await callback.message.edit_text(
        f"<b>{ex.name}</b> — подход {target.set_number}\n\n"
        f"Текущее значение: <code>{target.reps} × {weight_text}</code>\n\n"
        "Введи новое количество повторов:",
        reply_markup=numeric_keypad_kb(),  # <-- ПОКАЗАЛИ КЛАВИАТУРУ
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tr_add_set:"))
async def cb_add_set(callback: CallbackQuery, session: AsyncSession,
                     state: FSMContext):
    _, sess_str, ex_str = callback.data.split(":")
    session_id = int(sess_str)
    ex_id = int(ex_str)

    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
    completed = [s for s in sets if s.completed]
    set_num = len(completed) + 1

    ws = await session.get(WorkoutSession, session_id)
    last_set = await get_last_completed_set(session, ws.user_id, ex_id,
                                            current_session_id=session_id)

    if last_set:
        history = f"🕰 Прошлый раз: <b>{last_set.reps} × {format_weight(last_set.weight_kg)}</b>"
    else:
        history = f"📋 План: <b>{ex.reps} × {format_weight(ex.weight_kg)}</b>"

    await state.update_data(
        session_id=session_id,
        ex_id=ex_id,
        editing_set_id=None,
        return_to="tr_strength_summary",
        temp_num=""
    )
    await state.set_state(TrainingFSM.entering_reps)

    await callback.message.edit_text(
        f"🏋️ <b>{ex.name}</b> — подход {set_num}\n\n"
        f"{history}\n\n"
        f"Сколько повторов сделал?",
        reply_markup=numeric_keypad_kb()
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


@router.callback_query(F.data.startswith("tr_edit_menu:"))
async def cb_edit_menu(callback: CallbackQuery, session: AsyncSession):
    """Меню выбора подхода для редактирования."""
    _, sess_str, ex_str = callback.data.split(":")
    session_id = int(sess_str)
    ex_id = int(ex_str)

    sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
    completed = [s for s in sets if s.completed]

    if not completed:
        return await callback.answer("Нет выполненных подходов",
                                     show_alert=True)

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    sizes = []

    # Выводим все выполненные подходы в виде кнопок
    for s in completed:
        weight_text = format_weight(s.weight_kg)
        kb.button(
            text=f"✏️ Подход {s.set_number}: {s.reps}×{weight_text}",
            callback_data=f"tr_edit_set:{session_id}:{s.id}"
        )

    # Логика группировки по 2 в ряд
    num_sets = len(completed)
    while num_sets > 0:
        row_size = min(num_sets, 2)
        sizes.append(row_size)
        num_sets -= row_size

    # Кнопка возврата (всегда одна в ряду)
    kb.button(text="⬅️ Назад к упражнению",
              callback_data=f"tr_ex:{session_id}:{ex_id}")
    sizes.append(1)

    kb.adjust(*sizes)
    await callback.message.edit_text(
        "📝 <b>Выбери подход для редактирования:</b>",
        reply_markup=kb.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("num:"))
async def cb_numeric_input(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    if "session_id" not in data:
        return await callback.answer("Устаревшая кнопка. Открой упражнение заново.", show_alert=True)
    action = callback.data.split(":")[1]
    data = await state.get_data()
    current_val = data.get("temp_num", "")

    if action == "add":
        digit = callback.data.split(":")[2]
        if len(current_val) < 3:
            current_val += digit
            await state.update_data(temp_num=current_val)

    elif action == "del":
        current_val = current_val[:-1]
        await state.update_data(temp_num=current_val)

    elif action == "done":
        if not current_val:
            return await callback.answer("Введи хотя бы одну цифру!",
                                         show_alert=True)

        await state.update_data(custom_reps=int(current_val))
        await state.update_data(temp_weight="")
        await state.set_state(TrainingFSM.entering_weight)

        ex = await session.get(Exercise, data["ex_id"])
        ws = await session.get(WorkoutSession, data["session_id"])

        last_set = await get_last_completed_set(session, ws.user_id,
                                                data["ex_id"])
        suggested = last_set.weight_kg if last_set and last_set.weight_kg else ex.weight_kg
        suggestion = format_weight(suggested) if suggested else "без веса"

        await callback.message.edit_text(
            f"🏋️ <b>{ex.name}</b>\n\n"
            f"Повторов: <b>{current_val}</b>.\n"
            f"Теперь введи вес (снаряд).\n"
            f"<i>По умолчанию:</i> <code>{suggestion}</code>\n\n"
            f"<i>(Нажми на значение по умолчанию, чтобы скопировать)</i>",
            reply_markup=weight_keypad_kb()
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        f"<b>Ввод повторов</b>\n\nТекущее значение: <b>{current_val or '0'}</b>",
        reply_markup=numeric_keypad_kb()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("w_num:"))
async def cb_weight_input(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    if "session_id" not in data:
        return await callback.answer("Устаревшая кнопка. Открой упражнение заново.", show_alert=True)
    action = callback.data.split(":")[1]
    data = await state.get_data()
    current_val = data.get("temp_weight", "")
    reps = data.get("custom_reps")

    if action == "add":
        digit = callback.data.split(":")[2]
        if len(current_val) < 5:
            current_val += digit
            await state.update_data(temp_weight=current_val)

    elif action == "del":
        current_val = current_val[:-1]
        await state.update_data(temp_weight=current_val)

    elif action == "text":
        await callback.message.edit_text(
            "📝 Напиши вес текстом (например «Своё тело», «Резинка») или отправь число:",
            reply_markup=text_weight_kb()
        )
        await callback.answer()
        return

    elif action == "back":
        await state.set_state(TrainingFSM.entering_reps)
        await callback.message.edit_text(
            f"<b>Ввод повторов</b>\n\nТекущее значение: <b>{reps}</b>",
            reply_markup=numeric_keypad_kb()
        )
        await callback.answer()
        return

    elif action == "done":
        if not current_val:
            return await callback.answer(
                "Введи вес или нажми 'Ввести текстом'", show_alert=True)

        weight_str = current_val.replace(",", ".")

        from datetime import datetime, timezone
        from app.db.models import SessionSet

        session_id = data["session_id"]
        ex_id = data["ex_id"]
        editing_set_id = data.get("editing_set_id")

        if editing_set_id:
            target = await session.get(SessionSet, editing_set_id)
            target.reps = reps
            target.weight_kg = weight_str
            target.completed_at = datetime.now(timezone.utc)
            await session.commit()
        else:
            sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
            new_set = SessionSet(
                session_id=session_id, exercise_id=ex_id,
                set_number=next_set_num(sets),
                reps=reps, weight_kg=weight_str, completed=True,
                completed_at=datetime.now(timezone.utc)
            )
            session.add(new_set)
            await session.commit()

        await state.clear()

        result = await render_approach_screen(session, session_id, ex_id)
        if result:
            text, kb = result
            await callback.message.edit_text(text, reply_markup=kb)
        else:
            ws = await session.get(WorkoutSession, session_id)
            text, kb = await render_list(session, session_id, ws.user_id)
            await callback.message.edit_text(text, reply_markup=kb)

        await callback.answer()
        return

    # Выводим с названием упражнения
    ex = await session.get(Exercise, data["ex_id"])
    ex_name = ex.name if ex else "Упражнение"

    await callback.message.edit_text(
        f"🏋️ <b>{ex_name}</b>\n\n"
        f"Повторов: <b>{reps}</b>.\n"
        f"Ввод веса: <code>{current_val or '0'}</code>\n\n"
        f"<i>Выбери цифры на панели ниже или нажми «Готово»</i>",
        reply_markup=weight_keypad_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "w_num:back_from_text")
async def cb_back_from_text(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    if "session_id" not in data:
        return await callback.answer("Устаревшая кнопка.", show_alert=True)
    data = await state.get_data()
    current_val = data.get("temp_weight", "")
    reps = data.get("custom_reps")
    ex_id = data.get("ex_id")

    ex = await session.get(Exercise, ex_id)
    ex_name = ex.name if ex else "Упражнение"

    await state.set_state(TrainingFSM.entering_weight)

    await callback.message.edit_text(
        f"🏋️ <b>{ex_name}</b>\n\n"
        f"Повторов: <b>{reps}</b>.\n"
        f"Ввод веса: <code>{current_val or '0'}</code>\n\n"
        f"<i>Выбери цифры на панели ниже или нажми «Готово»</i>",
        reply_markup=weight_keypad_kb()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("t_num:"))
async def cb_time_input(callback: CallbackQuery, state: FSMContext,
                        session: AsyncSession):
    """Ввод времени кардио через цифровую клавиатуру."""
    action = callback.data.split(":")[1]
    data = await state.get_data()

    if "session_id" not in data:
        return await callback.answer(
            "Устаревшая кнопка. Открой упражнение заново.", show_alert=True)

    current_val = data.get("temp_num",
                           "")  # используем тот же буфер, что и для повторов

    if action == "add":
        digit = callback.data.split(":")[2]
        if len(current_val) < 5:
            current_val += digit
            await state.update_data(temp_num=current_val)
    elif action == "del":
        current_val = current_val[:-1]
        await state.update_data(temp_num=current_val)
    elif action == "text":
        await callback.message.edit_text(
            "📝 Напиши время текстом (например «30» или «1.5»):",
            reply_markup=cancel_kb()
        )
        await callback.answer()
        return
    elif action == "done":
        if not current_val:
            return await callback.answer("Введи время!", show_alert=True)

        from app.utils import parse_minutes_to_seconds
        seconds = parse_minutes_to_seconds(current_val)
        if seconds is None:
            return await callback.answer("Некорректное время", show_alert=True)

        session_id = data["session_id"]
        ex_id = data["ex_id"]
        editing_set_id = data.get("editing_set_id")

        from datetime import datetime, timezone
        from app.db.models import SessionSet
        from app.db.queries import get_sets_grouped
        from app.services.training_service import next_set_num, \
            render_approach_screen, render_list

        if editing_set_id:
            target = await session.get(SessionSet, editing_set_id)
            target.duration_seconds = seconds
            target.completed_at = datetime.now(timezone.utc)
            await session.commit()
        else:
            sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
            new_set = SessionSet(
                session_id=session_id, exercise_id=ex_id,
                set_number=next_set_num(sets),
                duration_seconds=seconds, completed=True,
                completed_at=datetime.now(timezone.utc)
            )
            session.add(new_set)
            await session.commit()

        await state.clear()

        result = await render_approach_screen(session, session_id, ex_id)
        if result:
            text, kb = result
            await callback.message.edit_text(text, reply_markup=kb)
        else:
            ws = await session.get(WorkoutSession, session_id)
            text, kb = await render_list(session, session_id, ws.user_id)
            await callback.message.edit_text(text, reply_markup=kb)

        await callback.answer()
        return

    ex = await session.get(Exercise, data["ex_id"])
    ex_name = ex.name if ex else "Кардио"

    await callback.message.edit_text(
        f"🏃 <b>{ex_name}</b>\n\n"
        f"Ввод времени: <code>{current_val or '0'}</code>\n\n"
        f"<i>Выбери цифры на панели ниже или нажми «Готово»</i>",
        reply_markup=weight_keypad_kb(prefix="t_num")
    )
    await callback.answer()
