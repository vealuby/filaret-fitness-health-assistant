from __future__ import annotations

from datetime import date, datetime, timedelta, time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlmodel import select

from app.database import get_session
from app.models import MealPlan, Reminder, ReminderType, SleepLog, TrainingSession, TrainingStatus, User
from app.services.nutrition import adapt_plan_after_training_cancel, deserialize_plan, serialize_plan
from app.services.sleep import calculate_sleep_goal_minutes


router = Router(name="reminders")


class BedtimeState(StatesGroup):
    waiting = State()


@router.callback_query(F.data.startswith("wake:"))
async def handle_wake(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":")[1:]
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.first()
        if not user:
            await callback.answer("Сначала пройдите onboarding через /start.", show_alert=True)
            return
        if action[0] == "confirmed":
            # Спрашиваем о времени отхода ко сну
            await callback.message.answer(
                "Отлично! Во сколько вы легли спать вчера? (формат ЧЧ:ММ, например 23:30)"
            )
            # Сохраняем user_id и время пробуждения в состоянии
            await state.set_state(BedtimeState.waiting)
            await state.update_data(user_id=user.telegram_id, wake_time=datetime.now().time())
            await callback.answer("Хорошего дня!")
        elif action[0] == "snooze":
            minutes = int(action[1])
            reminder = Reminder(
                user_id=user.telegram_id,
                reminder_type=ReminderType.MORNING_WAKE,
                scheduled_for=datetime.utcnow() + timedelta(minutes=minutes),
            )
            session.add(reminder)
            await callback.answer(f"Напомню через {minutes} минут.")
        await session.commit()


@router.callback_query(F.data.startswith("water:add:"))
async def handle_water_add(callback: CallbackQuery) -> None:
    """Обработчик для добавления конкретного количества воды"""
    ml = int(callback.data.split(":")[-1])
    from app.models import HydrationEvent
    from datetime import date
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.first()
        if not user:
            await callback.answer("Профиль не найден", show_alert=True)
            return
        
        # Создаём запись о выпитой воде
        hydration_event = HydrationEvent(
            user_id=user.telegram_id,
            plan_date=date.today(),
            target_time=datetime.now().time(),
            completed=True,
        )
        session.add(hydration_event)
        await session.commit()
        
        # Подсчитываем выпитую воду (примерно 200 мл на событие)
        events_result = await session.exec(
            select(HydrationEvent).where(
                HydrationEvent.user_id == user.telegram_id,
                HydrationEvent.plan_date == date.today(),
                HydrationEvent.completed == True,
            )
        )
        completed_events = events_result.all()
        portion_ml = 200  # Примерная порция на событие
        drank_ml = len(completed_events) * portion_ml
        progress = (drank_ml / user.hydration_goal_ml * 100) if user.hydration_goal_ml > 0 else 0
        
        await callback.answer(f"Добавлено {ml} мл воды! 💧")
        # Проверяем, достигнута ли цель
        if drank_ml >= user.hydration_goal_ml:
            await callback.message.answer(
                f"🎉 Отлично! Вы достигли цели по воде: ~{drank_ml} мл из {user.hydration_goal_ml} мл!\n"
                f"Продолжайте поддерживать водный баланс в течение дня."
            )
        else:
            await callback.message.answer(
                f"Записал порцию воды. Выпито: ~{drank_ml} мл из {user.hydration_goal_ml} мл ({progress:.0f}%)"
            )


@router.callback_query(F.data == "water:done")
async def handle_water_done(callback: CallbackQuery) -> None:
    from app.models import HydrationEvent
    from datetime import date
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.first()
        if not user:
            await callback.answer("Профиль не найден", show_alert=True)
            return
        
        # Создаём запись о выпитой воде
        hydration_event = HydrationEvent(
            user_id=user.telegram_id,
            plan_date=date.today(),
            target_time=datetime.now().time(),
            completed=True,
        )
        session.add(hydration_event)
        await session.commit()
        
        # Подсчитываем выпитую воду
        events_result = await session.exec(
            select(HydrationEvent).where(
                HydrationEvent.user_id == user.telegram_id,
                HydrationEvent.plan_date == date.today(),
                HydrationEvent.completed == True,
            )
        )
        completed_events = events_result.all()
        portion_ml = max(150, user.hydration_goal_ml // 8)
        drank_ml = len(completed_events) * portion_ml
        progress = (drank_ml / user.hydration_goal_ml * 100) if user.hydration_goal_ml > 0 else 0
        
        await callback.answer("Хорошо!")
        # Проверяем, достигнута ли цель
        if drank_ml >= user.hydration_goal_ml:
            await callback.message.answer(
                f"🎉 Отлично! Вы достигли цели по воде: {drank_ml} мл из {user.hydration_goal_ml} мл!\n"
                f"Продолжайте поддерживать водный баланс в течение дня."
            )
        else:
            await callback.message.answer(
                f"Записал порцию воды. Выпито: {drank_ml} мл из {user.hydration_goal_ml} мл ({progress:.0f}%)"
            )


@router.callback_query(F.data == "water:snooze")
async def handle_water_snooze(callback: CallbackQuery) -> None:
    reminder = Reminder(
        user_id=callback.from_user.id,
        reminder_type=ReminderType.HYDRATION,
        scheduled_for=datetime.utcnow() + timedelta(minutes=15),
    )
    async with get_session() as session:
        session.add(reminder)
        await session.commit()
    await callback.answer("Напомню через 15 минут.")


@router.callback_query(F.data.startswith("training:"))
async def handle_training(callback: CallbackQuery) -> None:
    action = callback.data.split(":")[1]
    async with get_session() as session:
        result = await session.exec(
            select(TrainingSession)
            .where(TrainingSession.user_id == callback.from_user.id)
            .order_by(TrainingSession.planned_time.desc())
        )
        session_obj = result.first()
        if not session_obj:
            await callback.answer("Нет актуальной тренировки.", show_alert=True)
            return
        if action == "start":
            session_obj.status = TrainingStatus.STARTED
            await callback.message.answer("Отлично! Удачной тренировки.")
        elif action == "cancel":
            session_obj.status = TrainingStatus.CANCELLED
            await callback.message.answer("Отмечаю тренировку как отменённую. Пересчитаю план питания.")
            meal_result = await session.exec(
                select(MealPlan).where(
                    MealPlan.user_id == session_obj.user_id,
                    MealPlan.plan_date == datetime.utcnow().date(),
                )
            )
            meal_plan = meal_result.first()
            if meal_plan:
                slots = adapt_plan_after_training_cancel(deserialize_plan(meal_plan.payload))
                meal_plan.payload = serialize_plan(slots)
                session.add(meal_plan)
        elif action == "end":
            session_obj.status = TrainingStatus.COMPLETED
            reminder = Reminder(
                user_id=callback.from_user.id,
                reminder_type=ReminderType.POST_WORKOUT,
                scheduled_for=datetime.utcnow() + timedelta(minutes=30),
            )
            session.add(reminder)
            await callback.message.answer("Как только будете готовы — поделитесь самочувствием (0–4).")
        session.add(session_obj)
        await session.commit()
    await callback.answer()


@router.message(BedtimeState.waiting, F.text)
async def handle_bedtime(message: Message, state: FSMContext) -> None:
    try:
        bedtime = datetime.strptime(message.text.strip(), "%H:%M").time()
    except ValueError:
        await message.answer("Введите время в формате ЧЧ:ММ, например 23:30")
        return
    
    data = await state.get_data()
    user_id = data.get("user_id", message.from_user.id)
    wake_time = data.get("wake_time")
    
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == user_id))
        user = result.first()
        if not user:
            await message.answer("Профиль не найден.")
            await state.clear()
            return
        
        # Вычисляем длительность сна
        bedtime_dt = datetime.combine(date.today() - timedelta(days=1), bedtime)
        wake_dt = datetime.combine(date.today(), wake_time) if wake_time else datetime.now()
        duration = (wake_dt - bedtime_dt).total_seconds() / 60
        
        # Создаём запись в SleepLog
        sleep_log = SleepLog(
            user_id=user_id,
            log_date=date.today() - timedelta(days=1),
            bedtime=bedtime,
            wake_time=wake_time,
            duration_minutes=int(duration),
        )
        session.add(sleep_log)
        
        # Обновляем долг по сну
        goal_minutes = calculate_sleep_goal_minutes(user)
        sleep_debt_delta = goal_minutes - int(duration)
        user.sleep_debt_minutes = max(0, user.sleep_debt_minutes + sleep_debt_delta)
        session.add(user)
        await session.commit()
    
    debt_hours = user.sleep_debt_minutes // 60
    debt_mins = user.sleep_debt_minutes % 60
    await message.answer(
        f"Записал: отбой в {bedtime.strftime('%H:%M')}, подъём в {wake_time.strftime('%H:%M') if wake_time else 'сегодня'}.\n"
        f"Длительность сна: {int(duration // 60)} ч {int(duration % 60)} мин.\n"
        f"Текущий долг по сну: {debt_hours} ч {debt_mins} мин."
    )
    await state.clear()


@router.callback_query(F.data.startswith("wellness:"))
async def handle_wellness(callback: CallbackQuery) -> None:
    score = int(callback.data.split(":")[1])
    async with get_session() as session:
        result = await session.exec(
            select(TrainingSession)
            .where(TrainingSession.user_id == callback.from_user.id)
            .order_by(TrainingSession.planned_time.desc())
        )
        training = result.first()
        if training:
            training.wellness_score = score
            session.add(training)
            await session.commit()
    await callback.answer("Спасибо! Отдыхайте и восстановитесь.")

