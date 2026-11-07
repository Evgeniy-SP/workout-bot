from datetime import datetime, timezone
from app.render import render_training_list
from app.db.models import Exercise, WorkoutType, SessionSet


def test_render_training_list_progress():
    """Проверяем, что опциональные упражнения не портят прогресс, если не сделаны."""

    # 1. Создаем фейковые объекты (без базы данных, просто в памяти)
    wt = WorkoutType(name="Тестовая тренировка")

    # Обязательное упражнение (сделано 1 из 1)
    ex1 = Exercise(id=1, name="Присед", kind="strength", sets=1, reps=10,
                   is_optional=False)

    # Опциональное упражнение (не сделано)
    ex2 = Exercise(id=2, name="Заминка", kind="cardio", is_optional=True)

    # Создаем выполненные подходы (только для первого упражнения)
    set1 = SessionSet(id=1, exercise_id=1, reps=10, weight_kg="50",
                      completed=True)

    sets_by_ex = {1: [set1], 2: []}

    # Передаем только обязательные упражнения в видимые (как в нашем боте)
    visible_exercises = [ex1]

    # 2. Вызываем функцию
    text = render_training_list(
        wt=wt,
        all_exercises=[ex1, ex2],
        visible_exercises=visible_exercises,
        sets_by_ex=sets_by_ex,
        session_started=datetime.now(timezone.utc)
    )

    # 3. Проверяем результат
    # В тексте должно быть "Выполнено: 1 / 1" (опциональная заминка не пошла в знаменатель)
    assert "Выполнено: <b>1 / 1</b>" in text


def test_render_training_list_with_optional_done():
    """Проверяем, что если опциональное СДЕЛАНО, оно идет в прогресс."""

    wt = WorkoutType(name="Тестовая тренировка")
    ex1 = Exercise(id=1, name="Присед", kind="strength", sets=1, reps=10,
                   is_optional=False)
    ex2 = Exercise(id=2, name="Заминка", kind="cardio", is_optional=True)

    set1 = SessionSet(id=1, exercise_id=1, reps=10, weight_kg="50",
                      completed=True)
    # Заминка тоже сделана
    set2 = SessionSet(id=2, exercise_id=2, duration_seconds=300,
                      completed=True)

    sets_by_ex = {1: [set1], 2: [set2]}
    visible_exercises = [ex1, ex2]  # Оба видны

    text = render_training_list(
        wt=wt,
        all_exercises=[ex1, ex2],
        visible_exercises=visible_exercises,
        sets_by_ex=sets_by_ex,
        session_started=datetime.now(timezone.utc)
    )

    # Теперь прогресс должен быть 2 / 2
    assert "Выполнено: <b>2 / 2</b>" in text
