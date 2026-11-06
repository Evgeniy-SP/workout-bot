"""Запросы к БД, специфичные для тренировок.

Вынесены отдельно от handlers/, чтобы не засорять логику.
"""
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SessionSet, SessionExerciseNote, WorkoutSession


async def get_active_session(session: AsyncSession,
                             user_id: int) -> WorkoutSession | None:
    """Сессия без finished_at = активная. Ищем только среди неархивных тренировок."""
    from app.db.models import WorkoutType

    result = await session.execute(
        select(WorkoutSession)
        .join(WorkoutType,
              WorkoutType.id == WorkoutSession.workout_type_id)  # <--- ДЖОИН
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.finished_at.is_(None),
            WorkoutType.is_archived == False,  # <--- ПРОВЕРКА НА АРХИВ
        )
        .order_by(WorkoutSession.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_sets_grouped(session: AsyncSession, session_id: int) -> dict[int, list[SessionSet]]:
    """Все подходы сессии, сгруппированные по exercise_id."""
    result = await session.execute(
        select(SessionSet)
        .where(SessionSet.session_id == session_id)
        .order_by(SessionSet.exercise_id, SessionSet.set_number)
    )
    grouped: dict[int, list[SessionSet]] = defaultdict(list)
    for s in result.scalars():
        grouped[s.exercise_id].append(s)
    return dict(grouped)


async def get_last_completed_set(
        session: AsyncSession, user_id: int, exercise_id: int,
        current_session_id: int | None = None
) -> SessionSet | None:
    """Последний успешно выполненный подход (исключая текущую сессию)."""
    stmt = (
        select(SessionSet)
        .join(WorkoutSession, WorkoutSession.id == SessionSet.session_id)
        .where(
            WorkoutSession.user_id == user_id,
            SessionSet.exercise_id == exercise_id,
            SessionSet.completed == True,
        )
    )

    # Если передали ID текущей сессии, исключаем её из поиска
    if current_session_id:
        stmt = stmt.where(SessionSet.session_id != current_session_id)

    result = await session.execute(
        stmt.order_by(SessionSet.id.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def get_last_note_for_exercise(
    session: AsyncSession, exercise_id: int, last_session_id: int
) -> str | None:
    """Возвращает заметку из конкретной (последней) тренировки."""
    result = await session.execute(
        select(SessionExerciseNote.note)
        .where(
            SessionExerciseNote.exercise_id == exercise_id,
            SessionExerciseNote.session_id == last_session_id
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_last_workout_note(
        session: AsyncSession, user_id: int, workout_type_id: int,
        current_session_id: int
) -> str | None:
    """Возвращает заметку из ПРЕДЫДУЩЕЙ тренировки этого типа.

    Если в предыдущей тренировке заметки не было, возвращает None.
    """
    result = await session.execute(
        select(WorkoutSession.notes)
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.workout_type_id == workout_type_id,
            WorkoutSession.id != current_session_id,
        )
        .order_by(WorkoutSession.started_at.desc())
        .limit(1)  # Берем ровно одну (предыдущую) тренировку
    )
    note = result.scalar_one_or_none()

    # Если заметка есть и она не пустая - возвращаем, иначе None
    return note if note else None
