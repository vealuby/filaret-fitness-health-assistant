from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlmodel import select

from app.bot.keyboards.common import training_type_keyboard
from app.database import get_session
from app.models import TrainingSession, TrainingStatus, User
from app.services.modules import DEFAULT_MODULES


router = Router(name="training-log")


class TrainingLogStates(StatesGroup):
    time = State()
    training_type = State()
    duration = State()
    intensity = State()
    wellness = State()


@router.message(Command("training"))
@router.message(F.text.lower() == "я был на тренировке")
async def training_entry(message: Message, state: FSMContext) -> None:
    user = await _fetch_user(message.from_user.id)
    if not user:
        await message.answer("Профиль не найден. Используйте /start.")
        return
    if "training" not in (user.get_modules() or DEFAULT_MODULES):
        await message.answer("Модуль тренировок отключён. Включите его через /modules.")
        return
    await state.update_data(user_id=user.telegram_id)
    await state.set_state(TrainingLogStates.time)
    await message.answer("Во сколько закончилась тренировка? Укажите время в формате 19:30.")


@router.message(TrainingLogStates.time, F.text)
async def training_time(message: Message, state: FSMContext) -> None:
    try:
        logged_time = datetime.strptime(message.text.strip(), "%H:%M").time()
    except ValueError:
        await message.answer("Введите время в формате ЧЧ:ММ, например 19:30.")
        return
    await state.update_data(log_time=logged_time)
    await state.set_state(TrainingLogStates.training_type)
    await message.answer(
        "Выберите тип тренировки:",
        reply_markup=training_type_keyboard().as_markup(),
    )


@router.callback_query(TrainingLogStates.training_type, F.data.startswith("training_log:type:"))
async def training_type(callback: CallbackQuery, state: FSMContext) -> None:
    training_type = callback.data.split(":")[-1]
    await state.update_data(training_type=training_type)
    await state.set_state(TrainingLogStates.duration)
    await callback.message.edit_text("Сколько минут длилась тренировка?")
    await callback.answer()


@router.message(TrainingLogStates.duration, F.text)
async def training_duration(message: Message, state: FSMContext) -> None:
    try:
        duration = int(message.text.strip())
        if duration <= 0 or duration > 240:
            raise ValueError
    except ValueError:
        await message.answer("Введите длительность в минутах (например, 60).")
        return
    await state.update_data(duration=duration)
    await state.set_state(TrainingLogStates.intensity)
    await message.answer("Оцените интенсивность по шкале 1–10.")


@router.message(TrainingLogStates.intensity, F.text)
async def training_intensity(message: Message, state: FSMContext) -> None:
    try:
        intensity = int(message.text.strip())
        if not 1 <= intensity <= 10:
            raise ValueError
    except ValueError:
        await message.answer("Введите число от 1 до 10.")
        return
    await state.update_data(intensity=intensity)
    await state.set_state(TrainingLogStates.wellness)
    await message.answer("Как самочувствие после тренировки? Оцените по шкале 0–4.")


@router.message(TrainingLogStates.wellness, F.text)
async def training_wellness(message: Message, state: FSMContext) -> None:
    try:
        wellness = int(message.text.strip())
        if wellness < 0 or wellness > 4:
            raise ValueError
    except ValueError:
        await message.answer("Введите число от 0 до 4.")
        return
    data = await state.get_data()
    user = await _fetch_user(message.from_user.id)
    if not user:
        await message.answer("Профиль не найден. Используйте /start.")
        await state.clear()
        return
    await _store_training_session(
        user,
        data.get("log_time"),
        data.get("training_type"),
        data.get("duration"),
        data.get("intensity"),
        wellness,
    )
    await message.answer(
        "Спасибо! Тренировка записана. "
        "Не забудьте про восстановительный приём пищи и воду в течение ближайшего часа."
    )
    await state.clear()


@router.callback_query(F.data == "training_log:cancel")
async def training_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Отменено")
    await callback.message.edit_text("Регистрация тренировки отменена.")


async def _fetch_user(telegram_id: int) -> Optional[User]:
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == telegram_id))
        return result.first()


async def _store_training_session(
    user: User,
    log_time: Optional[time],
    training_type: Optional[str],
    duration: Optional[int],
    intensity: Optional[int],
    wellness: int,
) -> None:
    if log_time is None or duration is None or intensity is None or training_type is None:
        return
    planned_time = datetime.combine(date.today(), log_time)
    async with get_session() as session:
        session_obj = TrainingSession(
            user_id=user.telegram_id,
            planned_time=planned_time,
            status=TrainingStatus.COMPLETED,
            perceived_effort=intensity,
            wellness_score=wellness,
            notes=f"{training_type}, {duration} мин",
        )
        session.add(session_obj)
        await session.commit()

