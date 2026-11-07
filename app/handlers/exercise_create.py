"""Создание упражнения в тренировке (FSM)."""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Exercise, WorkoutType
from app.keyboards.workout_kb import (
    cancel_kb, choose_kind_kb, exercises_list_kb,
    numeric_keypad_kb, weight_keypad_kb
)
from app.states import WorkoutCreate
from app.utils import parse_minutes_to_seconds

router = Router()


async def _load_workout(session: AsyncSession, wt_id: int) -> WorkoutType | None:
    result = await session.execute(
        select(WorkoutType).where(WorkoutType.id == wt_id)
        .options(selectinload(WorkoutType.exercises))
    )
    return result.scalar_one_or_none()


# ─────── Шаг 1: Выбор типа упражнения ───────

@router.callback_query(F.data.startswith("ex_new:"))
async def choose_kind(callback: CallbackQuery, state: FSMContext):
    wt_id = int(callback.data.split(":")[1])
    await state.update_data(wt_id=wt_id, temp_num="", temp_weight="")
    await state.set_state(WorkoutCreate.adding_exercise_kind)
    await callback.message.edit_text(
        "Какой тип упражнения?", reply_markup=choose_kind_kb(wt_id)
    )
    await callback.answer()


@router.callback_query(WorkoutCreate.adding_exercise_kind, F.data.startswith("ex_new_kind:"))
async def after_kind(callback: CallbackQuery, state: FSMContext):
    _, kind, wt_id = callback.data.split(":")
    await state.update_data(kind=kind, wt_id=int(wt_id))
    await state.set_state(WorkoutCreate.adding_exercise_name)
    await callback.message.edit_text("Введи название упражнения (или /cancel):")
    await callback.answer()


# ─────── Шаг 2: Ввод названия ───────

@router.message(WorkoutCreate.adding_exercise_name)
async def add_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name or len(name) > 128:
        return await message.answer("Название 1–128 символов. Попробуй ещё:")

    await state.update_data(name=name)
    data = await state.get_data()

    if data["kind"] == "strength":
        await state.set_state(WorkoutCreate.adding_exercise_sets)
        await message.answer(
            "Сколько подходов? (целое число > 0):",
            reply_markup=numeric_keypad_kb(prefix="cr_num") # <-- КЛАВИАТУРА
        )
    else:
        await state.set_state(WorkoutCreate.adding_exercise_duration)
        await message.answer(
            "Длительность в минутах (можно 1.5 = 1 мин 30 сек):",
            reply_markup=weight_keypad_kb(prefix="cr_t_num") # <-- КЛАВИАТУРА С ТОЧКОЙ
        )


# ─────── Шаг 3: Ввод чисел через клавиатуру ───────

@router.callback_query(F.data.startswith("cr_num:"))
async def cb_cr_numeric(callback: CallbackQuery, state: FSMContext):
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
            return await callback.answer("Введи число!", show_alert=True)

        current_state = await state.get_state()
        if current_state == WorkoutCreate.adding_exercise_sets:
            await state.update_data(sets=int(current_val), temp_num="")
            await state.set_state(WorkoutCreate.adding_exercise_reps)
            await callback.message.edit_text(
                "Сколько повторений? (целое число > 0):",
                reply_markup=numeric_keypad_kb(prefix="cr_num")
            )
        elif current_state == WorkoutCreate.adding_exercise_reps:
            await state.update_data(reps=int(current_val), temp_weight="")
            await state.set_state(WorkoutCreate.adding_exercise_weight)
            await callback.message.edit_text(
                "Введи вес (например 12.5) или нажми «Ввести текстом»:",
                reply_markup=weight_keypad_kb(prefix="cr_w_num")
            )
        await callback.answer()
        return

    field_name = "подходов" if await state.get_state() == WorkoutCreate.adding_exercise_sets else "повторений"
    await callback.message.edit_text(
        f"Ввод {field_name}: <code>{current_val or '0'}</code>",
        reply_markup=numeric_keypad_kb(prefix="cr_num")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cr_w_num:"))
async def cb_cr_weight(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    current_val = data.get("temp_weight", "")

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
            "📝 Напиши вес текстом (например «Своё тело»):",
            reply_markup=cancel_kb()
        )
        await callback.answer()
        return
    elif action == "done":
        if not current_val:
            return await callback.answer("Введи вес!", show_alert=True)

        weight_str = current_val.replace(",", ".")
        await state.update_data(weight=weight_str)

        # Сохраняем упражнение
        await _finish(callback.message, state, session)
        await callback.answer()
        return

    await callback.message.edit_text(
        f"Ввод веса: <code>{current_val or '0'}</code>",
        reply_markup=weight_keypad_kb(prefix="cr_w_num")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cr_t_num:"))
async def cb_cr_time(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    current_val = data.get("temp_num", "")

    if action == "add":
        digit = callback.data.split(":")[2]
        if len(current_val) < 5:
            current_val += digit
            await state.update_data(temp_num=current_val)
    elif action == "del":
        current_val = current_val[:-1]
        await state.update_data(temp_num=current_val)
    elif action == "done":
        if not current_val:
            return await callback.answer("Введи время!", show_alert=True)

        seconds = parse_minutes_to_seconds(current_val)
        if seconds is None:
            return await callback.answer("Ошибка в времени", show_alert=True)

        await state.update_data(duration=seconds)
        await _finish(callback.message, state, session)
        await callback.answer()
        return

    await callback.message.edit_text(
        f"Ввод времени (мин): <code>{current_val or '0'}</code>",
        reply_markup=weight_keypad_kb(prefix="cr_t_num")
    )
    await callback.answer()


# ─────── Шаг 4: Текстовый ввод (fallback на случай, если клавиатура не используется) ───────

@router.message(WorkoutCreate.adding_exercise_sets)
async def add_sets(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        return await message.answer("Нужно целое число > 0:")
    await state.update_data(sets=int(text))
    await state.set_state(WorkoutCreate.adding_exercise_reps)
    await message.answer("Сколько повторений?", reply_markup=numeric_keypad_kb(prefix="cr_num"))


@router.message(WorkoutCreate.adding_exercise_reps)
async def add_reps(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        return await message.answer("Нужно целое число > 0:")
    await state.update_data(reps=int(text))
    await state.set_state(WorkoutCreate.adding_exercise_weight)
    await message.answer("Введи вес:", reply_markup=weight_keypad_kb(prefix="cr_w_num"))


@router.message(WorkoutCreate.adding_exercise_weight)
async def add_weight(message: Message, state: FSMContext, session: AsyncSession):
    text = message.text.strip()
    weight = None if text in {"-", "0", "0.0", "нет"} else text.replace(",", ".")
    await state.update_data(weight=weight)
    await _finish(message, state, session)


@router.message(WorkoutCreate.adding_exercise_duration)
async def add_duration(message: Message, state: FSMContext, session: AsyncSession):
    text = message.text.strip()
    seconds = None if text in {"-", "0"} else parse_minutes_to_seconds(text)
    if seconds is None and text not in {"-", "0"}:
        return await message.answer("Нужно положительное число или «-»:")
    await state.update_data(duration=seconds)
    await _finish(message, state, session)


# ─────── Общее завершение ───────

async def _finish(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    wt_id = data["wt_id"]
    return_session = data.get("return_to_session")

    # sort_order = последний + 1
    result = await session.execute(
        select(Exercise.sort_order).where(Exercise.workout_type_id == wt_id)
    )
    max_order = max((r[0] for r in result.all()), default=-1)

    ex = Exercise(
        workout_type_id=wt_id,
        name=data["name"],
        kind=data["kind"],
        sets=data.get("sets"),
        reps=data.get("reps"),
        weight_kg=data.get("weight"),
        duration_seconds=data.get("duration"),
        is_optional=False,
        sort_order=max_order + 1,
    )
    session.add(ex)
    await session.commit()
    await state.clear()

    # Возврат в тренировку или справочник
    if return_session:
        from app.db.models import User
        from app.services.training_service import \
            render_list

        # Ищем пользователя по правильному ID
        uresult = await session.execute(
            select(User).where(User.tg_id == message.from_user.id)
            # <-- ИСПРАВИЛИ
        )
        user = uresult.scalar_one_or_none()

        if user:
            text, kb = await render_list(session, return_session, user.id)
            await message.answer(
                f"✅ Добавлено: <b>{ex.name}</b>\n\n" + text,
                reply_markup=kb,
            )
            return

    wt = await _load_workout(session, wt_id)
    await message.answer(
        f"✅ Добавлено: <b>{ex.name}</b>",
        reply_markup=exercises_list_kb(wt.exercises, wt.id),
    )
