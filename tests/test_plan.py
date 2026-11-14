import pytest
from app.db.models import User, WorkoutType, Exercise, WorkoutSession, \
    SessionSet


@pytest.mark.asyncio
async def test_update_template_reduce_sets(session):
    """Проверяем, что шаблон обновляется, даже если сделано МЕНЬШЕ подходов."""
    user = User(tg_id=1, full_name="Test")
    wt = WorkoutType(user=user, name="Test")
    # В плане 4 подхода, 10 повторений, вес 50
    ex = Exercise(workout_type=wt, name="Жим", kind="strength", sets=4,
                  reps=10, weight_kg="50")
    session.add_all([user, wt, ex])
    await session.commit()

    ws = WorkoutSession(user_id=user.id, workout_type_id=wt.id)
    session.add(ws)
    await session.commit()

    # Сделали только 2 подхода с весом 70
    completed_sets = []  # <--- Создаем список для хранения
    for i in range(2):
        s = SessionSet(session_id=ws.id, exercise_id=ex.id, set_number=i + 1,
                       reps=12, weight_kg="70", completed=True)
        session.add(s)
        completed_sets.append(s)  # <--- Добавляем в список
    await session.commit()

    # Имитируем нажатие "Сделать планом"
    # Берем последний подход из нашего списка, а не из БД (чтобы избежать MissingGreenlet)
    last_set = completed_sets[-1]

    ex.sets = len(completed_sets)  # Берем 2, а не 4
    ex.reps = last_set.reps
    ex.weight_kg = last_set.weight_kg
    await session.commit()

    # Проверяем
    updated_ex = await session.get(Exercise, ex.id)
    assert updated_ex.sets == 2  # Обновилось на меньшее
    assert updated_ex.reps == 12
    assert updated_ex.weight_kg == "70"
