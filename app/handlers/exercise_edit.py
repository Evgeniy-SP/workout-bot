"""FSM-редактирование полей тренировки и упражнений.

Каждое поле — своё состояние. Пока state активен, все текстовые
сообщения пользователя ловятся соответствующим @router.message(State).
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Exercise, WorkoutType
from app.keyboards.workout_kb import cancel_kb, exercise_card_kb, \
    workout_card_kb
from app.render import render_exercise_card, render_workout_card
from app.states import WorkoutEdit
from app.utils import format_weight, parse_minutes_to_seconds

router = Router()


# ─────────────── /cancel — отмена в любом состоянии ───────────────
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, session: AsyncSession):
    from app.services.navigation_service import resolve_cancel_view
    result = await resolve_cancel_view(state, session, message.from_user.id)
    if result is None:
        return await message.answer("Нечего отменять.")
    text, kb = result
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "fsm_cancel")
async def cb_fsm_cancel(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    from app.services.navigation_service import resolve_cancel_view
    result = await resolve_cancel_view(state, session, callback.from_user.id)
    if result is None:
        return await callback.answer("Нечего отменять.", show_alert=True)
    text, kb = result
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


# ═══════════════════════════════════════════════════════════
#  Переименование тренировки
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("wt_ren:"))
async def rename_workout_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    wt_id = int(callback.data.split(":")[1])
    wt = await session.get(WorkoutType, wt_id)
    if not wt:
        return await callback.answer("Не найдено", show_alert=True)

    await state.update_data(wt_id=wt_id, return_to="wt_card")
    await state.set_state(WorkoutEdit.renaming_type)
    await callback.message.edit_text(
        f"✏️ Текущее название: <b>{wt.name}</b>\n\n"
        "Введи новое название :",
        reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(WorkoutEdit.renaming_type)
async def rename_workout_save(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    wt = await session.get(WorkoutType, data["wt_id"])
    if not wt:
        await state.clear()
        return await message.answer(
            "Тренировка не найдена.",
            reply_markup=cancel_kb()
        )

    new_name = message.text.strip()
    if not new_name or len(new_name) > 64:
        return await message.answer(
            "Название 1–64 символа. Попробуй ещё:",
            reply_markup=cancel_kb()
        )

    wt.name = new_name
    await session.commit()
    await state.clear()
    await message.answer(
        "✅ Название обновлено.\n\n" + render_workout_card(wt),
        reply_markup=workout_card_kb(wt.id),
    )


# ═══════════════════════════════════════════════════════════
#  Название упражнения
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ex_edit_name:"))
async def edit_name_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    await state.update_data(ex_id=ex_id, return_to="ex_card")
    await state.set_state(WorkoutEdit.editing_exercise_name)
    await callback.message.edit_text(
        f"✏️ Текущее: <b>{ex.name}</b>\n\nВведи новое название:",
        reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(WorkoutEdit.editing_exercise_name)
async def edit_name_save(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    ex = await session.get(Exercise, data["ex_id"])
    if not ex:
        await state.clear()
        return await message.answer(
            "Упражнение не найдено.",
            reply_markup=cancel_kb()
        )

    new_name = message.text.strip()
    if not new_name or len(new_name) > 128:
        return await message.answer(
            "Название 1–128 символов. Попробуй ещё:",
            reply_markup=cancel_kb()
        )

    ex.name = new_name
    await session.commit()
    await state.clear()
    await message.answer(
        "✅ Сохранено.\n\n" + render_exercise_card(ex),
        reply_markup=exercise_card_kb(ex),
    )


# ═══════════════════════════════════════════════════════════
#  Подходы
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ex_edit_sets:"))
async def edit_sets_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    await state.update_data(ex_id=ex_id, return_to="ex_card")
    await state.set_state(WorkoutEdit.editing_exercise_sets)
    await callback.message.edit_text(
        f"🔢 Текущее количество подходов: <b>{ex.sets}</b>\n\n"
        "Введи новое число (целое, больше 0):",
        reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(WorkoutEdit.editing_exercise_sets)
async def edit_sets_save(message: Message, state: FSMContext, session: AsyncSession):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        return await message.answer(
            "Нужно целое число больше 0. Попробуй ещё:",
            reply_markup=cancel_kb()
        )

    data = await state.get_data()
    ex = await session.get(Exercise, data["ex_id"])
    if not ex:
        await state.clear()
        return await message.answer(
            "Упражнение не найдено.",
            reply_markup=cancel_kb()
        )

    ex.sets = int(text)
    await session.commit()
    await state.clear()
    await message.answer(
        "✅ Сохранено.\n\n" + render_exercise_card(ex),
        reply_markup=exercise_card_kb(ex),
    )


# ═══════════════════════════════════════════════════════════
#  Повторения
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ex_edit_reps:"))
async def edit_reps_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    await state.update_data(ex_id=ex_id, return_to="ex_card")
    await state.set_state(WorkoutEdit.editing_exercise_reps)
    await callback.message.edit_text(
        f"🔁 Текущее количество повторений: <b>{ex.reps}</b>\n\n"
        "Введи новое число (целое, больше 0):",
        reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(WorkoutEdit.editing_exercise_reps)
async def edit_reps_save(message: Message, state: FSMContext, session: AsyncSession):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        return await message.answer(
            "Нужно целое число больше 0. Попробуй ещё:",
            reply_markup=cancel_kb()
        )

    data = await state.get_data()
    ex = await session.get(Exercise, data["ex_id"])
    if not ex:
        await state.clear()
        return await message.answer(
            "Упражнение не найдено.",
            reply_markup=cancel_kb()
        )

    ex.reps = int(text)
    await session.commit()
    await state.clear()
    await message.answer(
        "✅ Сохранено.\n\n" + render_exercise_card(ex),
        reply_markup=exercise_card_kb(ex),
    )


# ═══════════════════════════════════════════════════════════
#  Вес (можно ввести "0" или "-" чтобы убрать)
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ex_edit_weight:"))
async def edit_weight_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    current = format_weight(ex.weight_kg)
    await state.update_data(ex_id=ex_id, return_to="ex_card")
    await state.set_state(WorkoutEdit.editing_exercise_weight)
    await callback.message.edit_text(
        f"⚖️ Текущий вес: <b>{current}</b>\n\n"
        "Введи новый вес (например <code>12.5</code>) или текст "
        "(например <code>Своё тело</code>, <code>Резинка</code>).\n"
        "Или отправь <code>-</code>, чтобы убрать вес совсем:",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(WorkoutEdit.editing_exercise_weight)
async def edit_weight_save(message: Message, state: FSMContext,
                           session: AsyncSession):
    text = message.text.strip()

    if text in {"-", "0", "0.0", "нет"}:
        weight = None
    else:
        weight = text.replace(",", ".")

    data = await state.get_data()
    ex = await session.get(Exercise, data["ex_id"])
    if not ex:
        await state.clear()
        return await message.answer("Упражнение не найдено.")

    ex.weight_kg = weight
    await session.commit()
    await state.clear()
    await message.answer(
        "✅ Сохранено.\n\n" + render_exercise_card(ex),
        reply_markup=exercise_card_kb(ex),
    )


# ═══════════════════════════════════════════════════════════
#  Длительность (для разминки/заминки), в минутах
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ex_edit_duration:"))
async def edit_duration_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    ex_id = int(callback.data.split(":")[1])
    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Не найдено", show_alert=True)

    from app.utils import format_duration
    current = format_duration(ex.duration_seconds)
    await state.update_data(ex_id=ex_id, return_to="ex_card")
    await state.set_state(WorkoutEdit.editing_exercise_duration)
    await callback.message.edit_text(
        f"⏱ Текущая длительность: <b>{current}</b>\n\n"
        "Введи новую длительность в минутах (можно дробное: <code>1.5</code> = 1 мин 30 сек).\n"
        "Или <code>0</code> / <code>-</code>, чтобы «по факту»:",
        reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(WorkoutEdit.editing_exercise_duration)
async def edit_duration_save(message: Message, state: FSMContext, session: AsyncSession):
    text = message.text.strip()

    if text in {"-", "0"}:
        seconds = None
    else:
        seconds = parse_minutes_to_seconds(text)
        if seconds is None:
            return await message.answer(
                "Нужно положительное число (например 1.5 или 30). Попробуй ещё:",
                reply_markup=cancel_kb()
            )

    data = await state.get_data()
    ex = await session.get(Exercise, data["ex_id"])
    if not ex:
        await state.clear()
        return await message.answer(
            "Упражнение не найдено.",
            reply_markup=cancel_kb()
        )

    ex.duration_seconds = seconds
    await session.commit()
    await state.clear()
    await message.answer(
        "✅ Сохранено.\n\n" + render_exercise_card(ex),
        reply_markup=exercise_card_kb(ex),
    )

# ═══════════════════════════════════════════════════════════
#  Переключатель «опциональное / обязательное»
# ═══════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith("ex_toggle_opt:"))
async def toggle_optional(callback: CallbackQuery, session: AsyncSession):
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
