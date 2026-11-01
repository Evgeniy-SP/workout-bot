"""Создание упражнения в тренировке (FSM)."""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Exercise, WorkoutType
from app.keyboards.workout_kb import cancel_kb, choose_kind_kb, confirm_duplicate_kb, exercises_list_kb
from app.states import WorkoutCreate
from app.utils import parse_minutes_to_seconds

router = Router()


async def _load_workout(session: AsyncSession, wt_id: int) -> WorkoutType | None:
    from app.db.models import Exercise

    result = await session.execute(
        select(WorkoutType)
        .where(WorkoutType.id == wt_id)
        .options(
            selectinload(WorkoutType.exercises.and_(Exercise.is_archived.is_(False)))
        )
    )
    return result.scalar_one_or_none()


# ─────── Шаг 1: выбрали «➕ Добавить упражнение» → показываем типы ───────

@router.callback_query(F.data.startswith("ex_new:"))
async def choose_kind(callback: CallbackQuery, state: FSMContext):
    wt_id = int(callback.data.split(":")[1])
    await state.update_data(wt_id=wt_id, return_to="ex_list")
    await state.set_state(WorkoutCreate.adding_exercise_kind)
    await callback.message.edit_text(
        "Какой тип упражнения?", reply_markup=choose_kind_kb(wt_id)
    )
    await callback.answer()


# ─────── Шаг 2: выбрали тип → спрашиваем название ───────

@router.callback_query(WorkoutCreate.adding_exercise_kind, F.data.startswith("ex_new_kind:"))
async def after_kind(callback: CallbackQuery, state: FSMContext):
    _, kind, wt_id = callback.data.split(":")
    await state.update_data(kind=kind, wt_id=int(wt_id))
    await state.set_state(WorkoutCreate.adding_exercise_name)
    await callback.message.edit_text(
        "Введи название упражнения :",
        reply_markup=cancel_kb()
    )
    await callback.answer()


# ─────── Шаг 3: название ───────

@router.message(WorkoutCreate.adding_exercise_name)
async def add_name(message: Message, state: FSMContext, session: AsyncSession):
    name = message.text.strip()
    if not name or len(name) > 128:
        return await message.answer("Название 1–128 символов. Попробуй ещё:")

    data = await state.get_data()
    wt_id = data["wt_id"]
    kind = data["kind"]

    # Проверяем, есть ли уже такое активное упражнение
    existing = await session.scalar(
        select(Exercise).where(
            Exercise.workout_type_id == wt_id,
            Exercise.is_archived == False,
            Exercise.kind == kind,
            func.lower(func.trim(Exercise.name)) == name.lower()
        )
    )

    if existing:
        await state.update_data(temp_name=name)
        await state.set_state(WorkoutCreate.confirming_duplicate)
        await message.answer(
            f"⚠️ Упражнение <b>{name}</b> уже есть в этой тренировке.\n\n"
            "Точно добавить ещё одно?",
            reply_markup=confirm_duplicate_kb()
        )
        return

    # Если дубликата нет — идем дальше как обычно
    await state.update_data(name=name)
    if kind == "strength":
        await state.set_state(WorkoutCreate.adding_exercise_sets)
        await message.answer("Сколько подходов? (целое число > 0):",
                             reply_markup=cancel_kb())
    else:
        await state.set_state(WorkoutCreate.adding_exercise_duration)
        await message.answer(
            "Длительность в минутах (можно дробное: <code>1.5</code> = 1 мин 30 сек):\n"
            "Или <code>-</code>, чтобы «по факту»:",
            reply_markup=cancel_kb()
        )


# --- Обработка кнопок дубликата ---

@router.callback_query(F.data == "dup_confirm",
                       WorkoutCreate.confirming_duplicate)
async def dup_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name = data["temp_name"]
    kind = data["kind"]

    await state.update_data(name=name)

    if kind == "strength":
        await state.set_state(WorkoutCreate.adding_exercise_sets)
        await callback.message.edit_text(
            "Сколько подходов? (целое число > 0):")
    else:
        await state.set_state(WorkoutCreate.adding_exercise_duration)
        await callback.message.edit_text(
            "Длительность в минутах (можно дробное: <code>1.5</code> = 1 мин 30 сек):\n"
            "Или <code>-</code>, чтобы «по факту»:"
        )
    await callback.answer()


@router.callback_query(F.data == "dup_cancel",
                       WorkoutCreate.confirming_duplicate)
async def dup_cancel(callback: CallbackQuery, state: FSMContext,
                     session: AsyncSession):
    from app.keyboards.workout_kb import exercises_list_kb
    from app.handlers.workout_menu import _load_workout_with_exercises

    # Достаем ID тренировки, куда мы добавляли упражнение
    data = await state.get_data()
    wt_id = data.get("wt_id")

    # Очищаем состояние
    await state.clear()

    # Возвращаемся в список упражнений
    if wt_id:
        wt = await _load_workout_with_exercises(session, wt_id)
        if wt:
            await callback.message.edit_text(
                f"❌ Добавление отменено.\n\n📋 Упражнения — <b>{wt.name}</b>",
                reply_markup=exercises_list_kb(wt.exercises, wt.id)
            )
            return await callback.answer()

    # Если что-то пошло не так (например, тренировку удалили) — просто пишем текст
    await callback.message.edit_text("❌ Добавление отменено.")
    await callback.answer()


# ─────── Силовое: подходы → повторения → вес ───────

@router.message(WorkoutCreate.adding_exercise_sets)
async def add_sets(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        return await message.answer(
            "Нужно целое число > 0. Попробуй ещё:",
            reply_markup=cancel_kb()
        )
    await state.update_data(sets=int(text))
    await state.set_state(WorkoutCreate.adding_exercise_reps)
    await message.answer(
        "Сколько повторений? (целое число > 0):",
        reply_markup=cancel_kb()
    )


@router.message(WorkoutCreate.adding_exercise_reps)
async def add_reps(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        return await message.answer(
            "Нужно целое число > 0. Попробуй ещё:",
            reply_markup=cancel_kb()
        )
    await state.update_data(reps=int(text))
    await state.set_state(WorkoutCreate.adding_exercise_weight)
    await message.answer(
        "Введи вес (например <code>12.5</code>) или текст "
        "(например <code>Своё тело</code>, <code>Резинка</code>).\n"
        "Или отправь <code>-</code>, чтобы оставить без веса:",
        reply_markup=cancel_kb(),
    )


@router.message(WorkoutCreate.adding_exercise_weight)
async def add_weight(message: Message, state: FSMContext,
                     session: AsyncSession):
    text = message.text.strip()

    # "-" или "0" -> без веса
    if text in {"-", "0", "0.0", "нет"}:
        weight = None
    else:
        # Принимаем любой текст!
        weight = text.replace(",",
                              ".")  # на всякий случай меняем запятую на точку

    await state.update_data(weight=weight)
    await _finish(message, state, session)


# ─────── Кардио: длительность ───────

@router.message(WorkoutCreate.adding_exercise_duration)
async def add_duration(message: Message, state: FSMContext, session: AsyncSession):
    text = message.text.strip()
    if text in {"-", "0"}:
        seconds = None
    else:
        seconds = parse_minutes_to_seconds(text)
        if seconds is None:
            return await message.answer(
                "Нужно положительное число (например 1.5 или 30) или «-». Попробуй ещё:",
                reply_markup=cancel_kb()
            )
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

    if return_session:
        from app.services.training_service import render_list
        from app.db.models import User
        uresult = await session.execute(
            select(User).where(User.tg_id == message.from_user.id)
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
