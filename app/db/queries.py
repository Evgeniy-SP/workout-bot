"""Запросы к БД, специфичные для тренировок.

Вынесены отдельно от handlers/, чтобы не засорять логику.
"""
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SessionSet, SessionExerciseNote, WorkoutSession


async def get_active_session(session: AsyncSession, user_id: int) -> WorkoutSession | None:
    """Сессия без finished_at = активная (в процессе)."""
    result = await session.execute(
        select(WorkoutSession)
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.finished_at.is_(None),
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
    session: AsyncSession, user_id: int, exercise_id: int
) -> SessionSet | None:
    """Последний успешно выполненный подход этого упражнения (для «вес по умолчанию»)."""
    result = await session.execute(
        select(SessionSet)
        .join(WorkoutSession, WorkoutSession.id == SessionSet.session_id)
        .where(
            WorkoutSession.user_id == user_id,
            SessionSet.exercise_id == exercise_id,
            SessionSet.completed == True,
        )
        .order_by(SessionSet.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_last_note_for_exercise(
    session: AsyncSession, user_id: int, exercise_id: int, current_session_id: int
) -> str | None:
    """Возвращает заметку из последней тренировки (исключая текущую)."""
    result = await session.execute(
        select(SessionExerciseNote.note)
        .join(WorkoutSession, WorkoutSession.id == SessionExerciseNote.session_id)
        .where(
            WorkoutSession.user_id == user_id,
            SessionExerciseNote.exercise_id == exercise_id,
            SessionExerciseNote.session_id != current_session_id
        )
        .order_by(SessionExerciseNote.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()