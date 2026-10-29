"""Начальные данные: тренировка «Ноги и плечи»."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Exercise, ExerciseKind, User, WorkoutType

# (name, kind, sets, reps, weight, duration_sec, is_optional)
LEGS_AND_SHOULDERS = [
    ("Разминка (кардио)",         ExerciseKind.WARMUP,   None, None, None, 1800, False),
    ("Выпады",                    ExerciseKind.STRENGTH,   3,   12, 10.0, None, False),
    ("Кубик",                     ExerciseKind.STRENGTH,   3,   12, 10.0, None, False),
    ("Разгибания ног сидя",       ExerciseKind.STRENGTH,   3,   12, 20.0, None, False),
    ("Сгибания ног в тренажёре",  ExerciseKind.STRENGTH,   3,   12, 20.0, None, False),
    ("Выжигания",                 ExerciseKind.STRENGTH,   3,   15, None, None, False),
    ("Подъём гантелей на плечи",  ExerciseKind.STRENGTH,   3,   10,  8.0, None, False),
    ("Обратная бабочка",          ExerciseKind.STRENGTH,   3,   12, 10.0, None, False),
    ("Кардио «заминка»",          ExerciseKind.CARDIO,     None, None, None, None, True),
]


async def create_default_workout(session: AsyncSession, user: User) -> WorkoutType:
    workout = WorkoutType(
        user_id=user.id,
        name="Ноги и плечи",
        description="Тренировка на ноги и плечи. Редактируется через меню.",
    )
    session.add(workout)
    await session.flush()

    for idx, (name, kind, sets, reps, weight, duration, optional) in enumerate(LEGS_AND_SHOULDERS):
        session.add(Exercise(
            workout_type_id=workout.id,
            name=name,
            kind=kind.value,
            sets=sets,
            reps=reps,
            weight_kg=weight,
            duration_seconds=duration,
            is_optional=optional,
            sort_order=idx,
        ))

    await session.flush()
    return workout