"""Сервисный слой для тренировок.

Здесь живут все 'мозги': загрузка данных из БД,
подготовка текстов и клавиатур для экранов.
Никаких @router.message или @router.callback_query здесь быть не должно.
"""
import random
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Exercise, SessionExerciseNote, SessionSet, User, \
    WorkoutSession, WorkoutType
from app.db.queries import (
    get_last_completed_set,
    get_last_note_for_exercise,
    get_last_workout_note,
    get_sets_grouped,
)
from app.keyboards.workout_kb import (
    approach_kb, optional_list_kb, training_list_kb,
)
from app.render import render_approach, render_training_list

# Глобальное хранилище активных таймеров: {session_id: dict}
ACTIVE_TIMERS = {}


async def get_user(session: AsyncSession, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


async def load_workout(session: AsyncSession,
                       wt_id: int) -> WorkoutType | None:
    """Загружаем тренировку с НЕархивными упражнениями."""
    result = await session.execute(
        select(WorkoutType)
        .where(WorkoutType.id == wt_id)
        .options(
            selectinload(
                WorkoutType.exercises.and_(Exercise.is_archived.is_(False)))
        )
    )
    return result.scalar_one_or_none()


def next_set_num(sets: list[SessionSet]) -> int:
    """Номер следующего подхода (1-based)."""
    return sum(1 for s in sets if s.completed) + 1


async def render_approach_screen(
        session: AsyncSession, session_id: int, ex_id: int
):
    from app.keyboards.workout_kb import cardio_done_kb, strength_summary_kb
    from app.render import render_strength_summary
    from app.utils import format_duration
    import random

    ws = await session.get(WorkoutSession, session_id)
    ex = await session.get(Exercise, ex_id)

    if not ws or not ex or ws.finished_at:
        return None

    wt = await load_workout(session, ws.workout_type_id)
    sets_by_ex = await get_sets_grouped(session, session_id)

    # ─── УМНЫЙ ПОИСК УПРАЖНЕНИЙ ───
    next_ex_id = None
    prev_ex_id = None
    if wt:
        main_exercises = sorted([e for e in wt.exercises if not e.is_optional],
                                key=lambda e: e.sort_order)
        current_idx = -1
        for i, e in enumerate(main_exercises):
            if e.id == ex_id:
                current_idx = i
                break

        if current_idx != -1:
            for i in range(current_idx + 1, len(main_exercises)):
                n_ex = main_exercises[i]
                n_sets = sets_by_ex.get(n_ex.id, [])
                n_done = sum(1 for s in n_sets if s.completed)
                n_plan = (n_ex.sets or 0) if n_ex.kind == "strength" else 1
                if n_done < n_plan:
                    next_ex_id = n_ex.id
                    break

            if not next_ex_id:
                for i in range(0, current_idx):
                    n_ex = main_exercises[i]
                    n_sets = sets_by_ex.get(n_ex.id, [])
                    n_done = sum(1 for s in n_sets if s.completed)
                    n_plan = (n_ex.sets or 0) if n_ex.kind == "strength" else 1
                    if n_done < n_plan:
                        next_ex_id = n_ex.id
                        break

            if not next_ex_id and len(main_exercises) > 1:
                if current_idx < len(main_exercises) - 1:
                    next_ex_id = main_exercises[current_idx + 1].id
                if current_idx > 0:
                    prev_ex_id = main_exercises[current_idx - 1].id
    # ─────────────────────────────────────────

    sets = sets_by_ex.get(ex_id, [])
    completed = [s for s in sets if s.completed]

    # Достаем заметку к упражнению (для текущей сессии)
    note_res = await session.execute(
        select(SessionExerciseNote).where(
            SessionExerciseNote.session_id == session_id,
            SessionExerciseNote.exercise_id == ex_id
        )
    )
    note_obj = note_res.scalar_one_or_none()

    text, kb = "", None

    # ─── КАРДИО ───
    if ex.kind != "strength":
        can_remove = not completed

        # Достаем историю ПРОШЛОЙ тренировки (исключая текущую!)
        last_set = await get_last_completed_set(session, ws.user_id, ex_id,
                                                current_session_id=session_id)
        last_duration = last_set.duration_seconds if last_set else None
        last_note = None
        last_date = None

        if last_set:
            last_note = await get_last_note_for_exercise(session, ex_id,
                                                         last_set.session_id)
            last_ws = await session.get(WorkoutSession, last_set.session_id)
            if last_ws and last_ws.started_at:
                from app.utils import to_msk
                last_date = to_msk(last_ws.started_at).strftime("%d.%m.%y")

        if completed:
            s = completed[0]
            duration = format_duration(
                s.duration_seconds) if s.duration_seconds else "—"

            phrases = [
                "🎉 <b>Отлично! Кардио выполнено!</b>",
                "💪 <b>Класс! Время записано!</b>",
                "🔥 <b>Хорошая работа! Кардио закрыто!</b>",
                "🚀 <b>Есть! Сделано!</b>"
            ]
            congrats = random.choice(phrases)

            note_text = ""
            if note_obj:
                note_text += f"\n\n📝 <i>Текущая заметка: {note_obj.note}</i>"
            if last_note:
                note_text += f"\n\n📝 <i>Прошлая заметка: {last_note}</i>"

            text = (
                    f"<b>{ex.name}</b>\n\n"
                    f"{congrats}\n\n"
                    f"✅ Выполнено: <b>{duration}</b>" + note_text
            )
            kb = cardio_done_kb(session_id, ex, can_remove=can_remove,
                                next_ex_id=next_ex_id, prev_ex_id=prev_ex_id)
        else:
            text = render_approach(
                ex, 1, None, None, ex.duration_seconds,
                last_note=last_note,
                last_duration=last_duration,
                current_note=note_obj.note if note_obj else None,
                last_date=last_date
            )
            kb = approach_kb(
                session_id, ex, 1, None, None,
                planned_duration=last_duration or ex.duration_seconds,
                can_remove=can_remove,
                use_history=bool(last_duration)
            )
        return text, kb

    # ─── СИЛОВОЕ ───
    plan = ex.sets or 0

    # Достаем историю ПРОШЛОЙ тренировки (исключая текущую!)
    last_set = await get_last_completed_set(session, ws.user_id, ex_id,
                                            current_session_id=session_id)
    last_reps = last_set.reps if last_set else None
    last_weight = last_set.weight_kg if last_set else None

    last_note = None
    last_date = None
    if last_set:
        last_note = await get_last_note_for_exercise(session, ex_id,
                                                     last_set.session_id)
        last_ws = await session.get(WorkoutSession, last_set.session_id)
        if last_ws and last_ws.started_at:
            from app.utils import to_msk
            last_date = to_msk(last_ws.started_at).strftime("%d.%m.%y")

    if plan > 0 and len(completed) >= plan:
        # Все подходы выполнены — показываем экран итогов
        text = render_strength_summary(
            ex, completed,
            current_note=note_obj.note if note_obj else None,
            last_note=last_note,
            last_reps=last_reps,
            last_weight=last_weight,
            last_date=last_date
        )
        kb = strength_summary_kb(session_id, ex, completed, next_ex_id=next_ex_id, prev_ex_id=prev_ex_id)
    else:
        # Есть еще подходы — показываем экран подхода
        set_num = len(completed) + 1

        rest_time_str = None
        timer_str = None

        if completed:
            last_completed = completed[-1]
            if last_completed.completed_at:
                delta = datetime.now(
                    timezone.utc) - last_completed.completed_at
                total_sec = int(delta.total_seconds())
                if total_sec >= 10:
                    m = total_sec // 60
                    sec = total_sec % 60
                    rest_time_str = f"{m} мин {sec} сек" if m > 0 else f"{sec} сек"

        if session_id in ACTIVE_TIMERS:
            remaining = int((ACTIVE_TIMERS[session_id][
                                 "end_time"] - datetime.now(
                timezone.utc)).total_seconds())
            if remaining > 0:
                timer_str = f"осталось {remaining} сек"

        current_last_set = completed[-1] if completed else None
        action_weight = current_last_set.weight_kg if current_last_set else (
            last_weight if last_weight else ex.weight_kg)
        action_reps = current_last_set.reps if current_last_set else (
            last_reps if last_reps else ex.reps)

        can_remove = not sets

        text = render_approach(
            ex, set_num, ex.reps, ex.weight_kg, ex.duration_seconds,
            last_reps=last_reps,
            last_weight=last_weight,
            last_note=last_note,
            rest_time_str=rest_time_str,
            timer_str=timer_str,
            current_note=note_obj.note if note_obj else None,
            last_date=last_date
        )

        kb = approach_kb(
            session_id, ex, set_num, action_reps, action_weight,
            ex.duration_seconds, can_remove=can_remove,
            use_history=bool(last_set),
            is_first_set=(len(completed) == 0),
            has_timer=(timer_str is not None),
            completed_sets=completed
        )

    return text, kb


async def render_list(session: AsyncSession, session_id: int, user_id: int):
    """Собирает (текст, клавиатуру) для экрана активной тренировки."""
    ws = await session.get(WorkoutSession, session_id)
    wt = await load_workout(session, ws.workout_type_id)

    exercises = sorted(wt.exercises, key=lambda e: e.sort_order)
    sets_by_ex = await get_sets_grouped(session, session_id)

    last_time = None
    last_ex_id = None
    for ex_id, sets in sets_by_ex.items():
        for s in sets:
            if s.completed and s.completed_at:
                if last_time is None or s.completed_at > last_time:
                    last_time = s.completed_at
                    last_ex_id = ex_id

    rest_time_str = None
    last_ex_name = None
    if last_time:
        delta = datetime.now(timezone.utc) - last_time
        total_sec = int(delta.total_seconds())
        if total_sec >= 10:
            m = total_sec // 60
            sec = total_sec % 60
            rest_time_str = f"{m} мин {sec} сек" if m > 0 else f"{sec} сек"
        if last_ex_id:
            for ex in wt.exercises:
                if ex.id == last_ex_id:
                    last_ex_name = ex.name
                    break

    timer_str = None
    if session_id in ACTIVE_TIMERS:
        remaining = int((ACTIVE_TIMERS[session_id]["end_time"] - datetime.now(
            timezone.utc)).total_seconds())
        if remaining > 0:
            timer_str = f"осталось {remaining} сек"

    visible_exercises = []
    for ex in exercises:
        sets = sets_by_ex.get(ex.id, [])
        if not ex.is_optional or sets:
            visible_exercises.append(ex)

    last_session_note = await get_last_workout_note(
        session,
        user_id,
        ws.workout_type_id,
        session_id,
    )
    # --------------------------------------------------------

    text = render_training_list(
        wt,
        exercises,
        visible_exercises,
        sets_by_ex,
        ws.started_at,
        rest_time_str=rest_time_str,
        timer_str=timer_str,
        last_exercise_name=last_ex_name,
        session_note=ws.notes,
        last_session_note=last_session_note
    )

    optional_count = sum(1 for e in exercises if e.is_optional)
    kb = training_list_kb(
        wt.id, session_id, exercises, sets_by_ex,
        has_timer=(timer_str is not None), optional_count=optional_count
    )
    return text, kb


async def render_optional_list(session: AsyncSession, session_id: int,
                               user_id: int):
    ws = await session.get(WorkoutSession, session_id)
    wt = await load_workout(session, ws.workout_type_id)
    sets_by_ex = await get_sets_grouped(session, session_id)

    opt_exercises = [ex for ex in wt.exercises if ex.is_optional]

    lines = [
        f"⚪ <b>Опциональные упражнения</b>",
        f"<i>{wt.name}</i>",
        ""
    ]

    for i, ex in enumerate(opt_exercises, start=1):
        sets = sets_by_ex.get(ex.id, [])
        done_sets = sum(1 for s in sets if s.completed)
        plan_sets = (ex.sets or 0) if ex.kind == "strength" else 1

        if done_sets == 0:
            icon = "⚪"
        elif done_sets >= plan_sets:
            icon = "✅"
        else:
            icon = "🟡"

        kind_icon = "🏋️" if ex.kind == "strength" else "🏃"

        lines.append(f"{icon} {i}. {kind_icon} <b>{ex.name}</b>")

    text = "\n".join(lines)
    kb = optional_list_kb(session_id, opt_exercises, sets_by_ex) # <-- Вернули как было
    return text, kb


async def load_workout_with_exercises(session: AsyncSession, wt_id: int):
    """Загружает тренировку со всеми (в т.ч. архивными) упражнениями."""
    from app.db.models import Exercise
    result = await session.execute(
        select(WorkoutType)
        .where(WorkoutType.id == wt_id)
        .options(
            selectinload(WorkoutType.exercises.and_(Exercise.is_archived.is_(False)))
        )
    )
    return result.scalar_one_or_none()
