import pytest
from datetime import datetime, timezone, timedelta
from app.db.models import User, WorkoutType, WorkoutSession
from app.db.queries import get_user_sessions, get_user_sessions_count


@pytest.mark.asyncio
async def test_get_user_sessions_empty(session):
    """Проверяем, что пустая история возвращает пустой список."""
    user = User(tg_id=1, full_name="Test")
    session.add(user)
    await session.commit()

    sessions = await get_user_sessions(session, user.id, 0, 5)
    count = await get_user_sessions_count(session, user.id)

    assert len(sessions) == 0
    assert count == 0


@pytest.mark.asyncio
async def test_get_user_sessions_pagination(session):
    """Проверяем, что пагинация работает корректно."""
    user = User(tg_id=1, full_name="Test")
    wt = WorkoutType(user=user, name="Test Workout")
    session.add_all([user, wt])
    await session.commit()

    # Создаем 7 завершенных тренировок
    now = datetime.now(timezone.utc)
    for i in range(7):
        ws = WorkoutSession(
            user_id=user.id,
            workout_type_id=wt.id,
            started_at=now - timedelta(days=i),
            finished_at=now - timedelta(days=i) + timedelta(hours=1)
        )
        session.add(ws)
    await session.commit()

    # Тест 1: Первая страница (должно быть 5)
    page1 = await get_user_sessions(session, user.id, 0, 5)
    assert len(page1) == 5
    # Самая свежая должна быть первой (i=0)
    assert page1[0].started_at.date() == now.date()

    # Тест 2: Вторая страница (должно быть 2)
    page2 = await get_user_sessions(session, user.id, 5, 5)
    assert len(page2) == 2

    # Тест 3: Общее количество
    count = await get_user_sessions_count(session, user.id)
    assert count == 7
