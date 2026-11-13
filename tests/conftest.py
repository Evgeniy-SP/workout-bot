import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.db.base import Base
from app.db.models import User, WorkoutType, Exercise, WorkoutSession, SessionSet, SessionExerciseNote, SessionSkippedExercise

@pytest_asyncio.fixture(scope="function")
async def session():
    """Создает временную БД в памяти (SQLite) для каждого теста."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        yield session

    await engine.dispose()
