"""Хэндлеры для заметок к упражнениям во время тренировки."""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SessionExerciseNote, WorkoutSession
from app.keyboards.workout_kb import cancel_kb, note_edit_kb
from app.services.training_service import render_approach_screen, render_list
from app.states import TrainingFSM

router = Router()


@router.callback_query(F.data.startswith("tr_note_ex:"))
async def cb_note_ex_start(callback: CallbackQuery, session: AsyncSession,
                           state: FSMContext):
    _, sess_str, ex_str = callback.data.split(":")
    session_id = int(sess_str)
    ex_id = int(ex_str)

    await state.clear()
    await state.set_state(TrainingFSM.entering_exercise_note)
    await state.update_data(session_id=session_id, ex_id=ex_id,
                            return_to="tr_ex_card")

    existing = await session.execute(
        select(SessionExerciseNote).where(
            SessionExerciseNote.session_id == session_id,
            SessionExerciseNote.exercise_id == ex_id
        )
    )
    note = existing.scalar_one_or_none()

    if note:
        text = (
            f"✏️ <b>Редактирование заметки</b>\n\n"
            f"Текущая заметка:\n<b><code>{note.note}</code></b>\n\n"
            "Введи новый текст (нажми на старую заметку, чтобы скопировать):"
        )
    else:
        text = (
            "📝 <b>Новая заметка к упражнению</b>\n\n"
            "Напиши текст заметки:"
        )

    await callback.message.edit_text(
        text,
        reply_markup=note_edit_kb(session_id, ex_id, has_note=bool(note))
    )
    await callback.answer()


@router.message(TrainingFSM.entering_exercise_note)
async def fsm_note_ex_save(message: Message, state: FSMContext,
                           session: AsyncSession):
    data = await state.get_data()
    session_id = data["session_id"]
    ex_id = data["ex_id"]

    # Удаляем старую заметку (если была)
    await session.execute(
        delete(SessionExerciseNote).where(
            SessionExerciseNote.session_id == session_id,
            SessionExerciseNote.exercise_id == ex_id
        )
    )

    text = message.text.strip()
    if text:
        session.add(SessionExerciseNote(
            session_id=session_id,
            exercise_id=ex_id,
            note=text[:1000]
        ))

    await session.commit()
    await state.clear()

    # Возвращаемся в экран подхода или итогов
    result = await render_approach_screen(session, session_id, ex_id)
    if result:
        msg_text, kb = result
        await message.answer(f"✅ Заметка сохранена.\n\n{msg_text}",
                             reply_markup=kb)
    else:
        ws = await session.get(WorkoutSession, session_id)
        text_screen, kb = await render_list(session, session_id, ws.user_id)
        await message.answer("✅ Заметка сохранена.\n\n" + text_screen,
                             reply_markup=kb)


@router.callback_query(F.data.startswith("tr_note_del:"))
async def cb_note_ex_delete(callback: CallbackQuery, session: AsyncSession,
                            state: FSMContext):
    await state.clear()
    _, sess_str, ex_str = callback.data.split(":")
    session_id = int(sess_str)
    ex_id = int(ex_str)

    await session.execute(
        delete(SessionExerciseNote).where(
            SessionExerciseNote.session_id == session_id,
            SessionExerciseNote.exercise_id == ex_id
        )
    )
    await session.commit()

    result = await render_approach_screen(session, session_id, ex_id)
    if result:
        text, kb = result
        await callback.message.edit_text(f"🗑 Заметка удалена.\n\n{text}",
                                         reply_markup=kb)

    await callback.answer("Удалено")


@router.callback_query(F.data.startswith("tr_sess_note:"))
async def cb_session_note_start(callback: CallbackQuery, session: AsyncSession,
                                state: FSMContext):
    session_id = int(callback.data.split(":")[1])
    ws = await session.get(WorkoutSession, session_id)
    if not ws:
        return await callback.answer("Тренировка не найдена", show_alert=True)

    await state.clear()
    await state.set_state(TrainingFSM.entering_session_note)
    await state.update_data(session_id=session_id, return_to="tr_list",
                            return_to_session=session_id)

    from app.keyboards.workout_kb import session_note_kb

    if ws.notes:
        text = (
            f"✏️ <b>Редактирование общей заметки</b>\n\n"
            f"Текущая заметка:\n<b><code>{ws.notes}</code></b>\n\n"
            "Введи новый текст (нажми на старую заметку, чтобы скопировать):"
        )
    else:
        text = (
            "📝 <b>Новая общая заметка</b>\n\n"
            "Напиши текст заметки (например, «плохо спал», «болит плечо»):"
        )

    await callback.message.edit_text(
        text,
        reply_markup=session_note_kb(session_id, has_note=bool(ws.notes))
    )
    await callback.answer()


@router.message(TrainingFSM.entering_session_note)
async def fsm_session_note_save(message: Message, state: FSMContext,
                                session: AsyncSession):
    data = await state.get_data()
    session_id = data["session_id"]

    ws = await session.get(WorkoutSession, session_id)
    if ws:
        text = message.text.strip()
        ws.notes = text if text else None
        await session.commit()

    await state.clear()

    from app.services.training_service import render_list
    text_screen, kb = await render_list(session, session_id, ws.user_id)
    await message.answer(
        "✅ Заметка сохранена.\n\n" + text_screen,
        reply_markup=kb
    )


@router.callback_query(F.data.startswith("tr_sess_note_del:"))
async def cb_session_note_delete(callback: CallbackQuery,
                                 session: AsyncSession, state: FSMContext):
    await state.clear()
    session_id = int(callback.data.split(":")[1])

    ws = await session.get(WorkoutSession, session_id)
    if ws:
        ws.notes = None
        await session.commit()

        from app.services.training_service import render_list
        text, kb = await render_list(session, session_id, ws.user_id)
        await callback.message.edit_text("🗑 Заметка удалена.\n\n" + text,
                                         reply_markup=kb)

    await callback.answer("Удалено")
