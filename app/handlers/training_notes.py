"""Хэндлеры для заметок к упражнениям во время тренировки."""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SessionExerciseNote, WorkoutSession
from app.keyboards.workout_kb import note_edit_kb
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
    await state.update_data(session_id=session_id, ex_id=ex_id)

    # Проверяем, есть ли уже заметка
    existing = await session.execute(
        select(SessionExerciseNote).where(
            SessionExerciseNote.session_id == session_id,
            SessionExerciseNote.exercise_id == ex_id
        )
    )
    note = existing.scalar_one_or_none()
    current_text = f"\n\n<i>Текущая: {note.note}</i>" if note else ""

    await callback.message.edit_text(
        f"📝 <b>Заметка к упражнению</b>{current_text}\n\n"
        "Напиши что-нибудь (например, «3-й подход не дожал»).",
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
