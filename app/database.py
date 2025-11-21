from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
# Импортируем все модели, чтобы они были зарегистрированы в SQLModel.metadata
from app.models import (  # noqa: F401
    HydrationEvent,
    MealLog,
    MealPlan,
    MedicationSchedule,
    Reminder,
    SleepLog,
    SymptomLog,
    TrainingSession,
    User,
)


engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)
async_session_factory = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    session = async_session_factory()
    try:
        yield session
    finally:
        await session.close()


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

