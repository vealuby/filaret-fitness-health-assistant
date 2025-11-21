from __future__ import annotations
from datetime import date
from typing import List

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlmodel import delete, select

from app.bot.keyboards.common import (
    hydration_keyboard,
    llm_cancel_keyboard,
    main_menu,
    modules_keyboard,
    wake_keyboard,
)
from app.database import get_session
from app.models import (
    HydrationEvent,
    MealLog,
    MealPlan,
    MealType,
    Reminder,
    ReminderType,
    SleepLog,
    SymptomLog,
    TrainingSession,
    User,
)
from app.services.llm import llm_client
from app.services.nutrition import (
    MealSlot,
    MEAL_LABELS,
    adapt_plan_after_training_cancel,
    deserialize_plan,
    generate_daily_plan,
    serialize_plan,
)
from app.services.modules import DEFAULT_MODULES, normalize_modules
from app.services.sleep import build_bedtime_plan
from app.services.personalization import estimate_calories
from app.services.training import summarize_training_day

router = Router(name="commands")

class LLMStates(StatesGroup):
    waiting = State()



@router.callback_query(F.data == "llm:cancel")
async def llm_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Отменено")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Я помогу оптимизировать режим сна, питания, воды и тренировок.\n"
        "/start — онбординг или обновление данных\n"
        "/profile — показать текущие цели\n"
        "/plan — план на сегодня\n"
        "/ask — задать вопрос LLM\n"
        "/training — записать прошедшую тренировку\n"
        "/meds — управлять напоминаниями о лекарствах\n"
        "/symptoms — зафиксировать симптомы\n"
        "/modules — включить или отключить модули\n"
        "/fix_timezone — исправить часовой пояс\n"
        "/delete_data — удалить профиль",
        reply_markup=main_menu().as_markup(resize_keyboard=True),
    )


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == message.from_user.id))
        user = result.first()
        if not user:
            await message.answer("Профиль не найден. Отправьте /start для начала.")
            return
        plan = build_bedtime_plan(user)
        modules = ", ".join(user.get_modules() or DEFAULT_MODULES)
        
        # Форматируем рабочие часы
        work_hours_str = "Не указано"
        if user.work_start and user.work_end:
            work_hours_str = f"{user.work_start.strftime('%H:%M')}–{user.work_end.strftime('%H:%M')}"
        elif user.work_start:
            work_hours_str = f"{user.work_start.strftime('%H:%M')}–?"
        elif user.work_end:
            work_hours_str = f"?–{user.work_end.strftime('%H:%M')}"
        
        # Рассчитываем КБЖУ
        calories_info = estimate_calories(user)
        kbju_str = "Не рассчитано"
        if calories_info:
            kbju_str = f"~{calories_info['target']} ккал ({calories_info['macro']})"
        
        # Форматируем возраст и пол
        age_sex_str = "Не указано"
        if user.age:
            sex_str = "м" if user.sex == "m" else "ж" if user.sex == "f" else ""
            age_sex_str = f"{user.age} {sex_str}".strip()
        
        # Форматируем рост и вес
        physical_str = "Не указано"
        if user.height_cm and user.weight_kg:
            physical_str = f"{user.height_cm} см, {user.weight_kg} кг"
        elif user.height_cm:
            physical_str = f"{user.height_cm} см"
        elif user.weight_kg:
            physical_str = f"{user.weight_kg} кг"
        
        # Форматируем цели
        goals_str = user.goals or "Не указаны"
        
        # Экранируем HTML-символы
        def escape_html(text: str) -> str:
            """Экранирует HTML-символы"""
            if not text:
                return text
            return (
                text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
        
        profile_text = (
            "📋 <b>Ваш профиль</b>\n\n"
            "⏰ <b>Сон:</b>\n"
            f"• Подъём: {user.desired_wake_time.strftime('%H:%M')}\n"
            f"• Цель сна: {user.sleep_goal_minutes // 60} ч\n"
            f"• Рекомендуемый отбой: {plan.target_bedtime.strftime('%H:%M')}\n\n"
            "👤 <b>Физические данные:</b>\n"
            f"• Возраст/пол: {escape_html(age_sex_str)}\n"
            f"• Рост/вес: {escape_html(physical_str)}\n\n"
            "💧 <b>Гидратация:</b>\n"
            f"• Цель: {user.hydration_goal_ml} мл/день\n\n"
            "🍽️ <b>Питание:</b>\n"
            f"• КБЖУ: {escape_html(kbju_str)}\n\n"
            "💼 <b>Работа:</b>\n"
            f"• Часы: {escape_html(work_hours_str)}\n\n"
            "🎯 <b>Цели:</b>\n"
            f"• {escape_html(goals_str)}\n\n"
            "⚙️ <b>Модули:</b>\n"
            f"• {escape_html(modules)}\n\n"
            f"💡 {escape_html(plan.notes)}"
        )
        
        await message.answer(profile_text, parse_mode="HTML")


@router.message(Command("plan"))
async def cmd_plan(message: Message) -> None:
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == message.from_user.id))
        user = result.first()
        if not user:
            await message.answer("Профиль не найден. Используйте /start.")
            return
        training_result = await session.exec(
            select(TrainingSession).where(TrainingSession.user_id == user.telegram_id)
        )
        trainings = training_result.all()
        calories = estimate_calories(user)
        target_cal = calories["target"] if calories else None
        meal_plan = await _get_or_generate_meal_plan(session, user, trainings, target_cal)
        training_summary = summarize_training_day(trainings)

    meals_lines = []
    total_plan_calories = 0
    import re
    for slot in meal_plan:
        label = MEAL_LABELS.get(slot.meal_type, slot.meal_type.value)
        # Извлекаем калории из рекомендации (пример: "~450 ккал")
        kcal_match = re.search(r"~(\d+)\s*ккал", slot.recommendation)
        if kcal_match:
            total_plan_calories += int(kcal_match.group(1))
        meals_lines.append(
            f"- {label} в {slot.target_time.strftime('%H:%M')}: {slot.recommendation}"
        )
    meals_text = "\n".join(meals_lines)
    calorie_line = ""
    if calories:
        diff = calories['target'] - total_plan_calories
        if abs(diff) > 50:  # Если разница больше 50 ккал, показываем предупреждение
            calorie_line = (
                f"Целевой коридор: ~{calories['target']} ккал/день "
                f"(поддержание {calories['maintenance']} ккал, {calories['macro']}).\n"
                f"В плане: ~{total_plan_calories} ккал. "
                f"{'Добавьте перекусы' if diff > 0 else 'Скорректируйте порции'} "
                f"для достижения цели.\n\n"
            )
        else:
            calorie_line = (
                f"Целевой коридор: ~{calories['target']} ккал/день "
                f"(поддержание {calories['maintenance']} ккал, {calories['macro']}).\n"
                f"В плане: ~{total_plan_calories} ккал.\n\n"
            )
    from app.bot.keyboards.common import main_menu
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == message.from_user.id))
        user = result.first()
    active_modules = set(user.get_modules() or DEFAULT_MODULES) if user else set(DEFAULT_MODULES)
    await message.answer(
        f"{calorie_line}План питания:\n{meals_text}\n\n{training_summary}",
        reply_markup=main_menu(active_modules).as_markup(resize_keyboard=True),
    )


@router.message(Command("ask"))
async def cmd_ask(message: Message, state: FSMContext) -> None:
    question = message.text.split(maxsplit=1)
    if len(question) == 1:
        await _prompt_llm(message, state)
        return
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == message.from_user.id))
        user = result.first()
    if not user:
        await message.answer("Сначала пройдите onboarding (/start).")
        return
    answer = await llm_client.ask(user, question[1])
    await message.answer(answer)


@router.message(Command("fix_timezone"))
async def cmd_fix_timezone(message: Message) -> None:
    """Позволяет выбрать часовой пояс через inline кнопки"""
    from app.bot.keyboards.common import timezone_keyboard
    
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == message.from_user.id))
        user = result.first()
        if not user:
            await message.answer("Профиль не найден. Используйте /start.")
            return
        
        await message.answer(
            f"Текущий часовой пояс: {user.timezone}\n\n"
            "Выберите ваш часовой пояс:",
            reply_markup=timezone_keyboard().as_markup()
        )


@router.callback_query(F.data.startswith("timezone:set:"))
async def timezone_set_callback(callback: CallbackQuery) -> None:
    """Обработчик выбора часового пояса"""
    timezone = callback.data.split(":")[-1]
    
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.first()
        if not user:
            await callback.answer("Профиль не найден. Используйте /start.")
            return
        
        old_tz = user.timezone
        user.timezone = timezone
        session.add(user)
        await session.commit()
        
        await callback.message.edit_text(
            f"✅ Часовой пояс изменён:\n"
            f"Было: {old_tz}\n"
            f"Стало: {timezone}\n\n"
            f"Напоминания будут создаваться с учетом нового часового пояса."
        )
        await callback.answer(f"Часовой пояс установлен: {timezone}")


@router.message(Command("delete_data"))
async def cmd_delete(message: Message) -> None:
    async with get_session() as session:
        await session.exec(delete(Reminder).where(Reminder.user_id == message.from_user.id))
        await session.exec(delete(MealPlan).where(MealPlan.user_id == message.from_user.id))
        await session.exec(delete(TrainingSession).where(TrainingSession.user_id == message.from_user.id))
        await session.exec(delete(User).where(User.telegram_id == message.from_user.id))
        await session.commit()
    await message.answer("Данные удалены. При необходимости начните заново через /start.")


@router.message(Command("summary"))
async def cmd_summary(message: Message) -> None:
    """
    Выводит сводку за последние 3 дня с анализом от LLM.
    """
    from datetime import date, datetime, time, timedelta
    
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == message.from_user.id))
        user = result.first()
        if not user:
            await message.answer("Профиль не найден. Используйте /start.")
            return
        
        # Период: последние 3 дня
        today = date.today()
        start_date = today - timedelta(days=3)
        
        # Собираем данные о сне
        sleep_logs = await session.exec(
            select(SleepLog).where(
                SleepLog.user_id == user.telegram_id,
                SleepLog.log_date >= start_date,
            )
        )
        sleep_data = []
        total_sleep_minutes = 0
        sleep_count = 0
        for log in sleep_logs.all():
            sleep_data.append({
                "date": log.log_date.isoformat(),
                "bedtime": log.bedtime.strftime("%H:%M") if log.bedtime else None,
                "wake_time": log.wake_time.strftime("%H:%M") if log.wake_time else None,
                "duration_minutes": log.duration_minutes,
                "rating": log.rating,
                "sleep_debt_delta": log.sleep_debt_delta,
            })
            if log.duration_minutes:
                total_sleep_minutes += log.duration_minutes
                sleep_count += 1
        
        avg_sleep_hours = (total_sleep_minutes / sleep_count) if sleep_count > 0 else 0
        
        # Собираем данные о еде
        meal_logs = await session.exec(
            select(MealLog).where(
                MealLog.user_id == user.telegram_id,
                MealLog.log_date >= start_date,
            )
        )
        meals_data = []
        for log in meal_logs.all():
            meals_data.append({
                "date": log.log_date.isoformat(),
                "time": log.meal_time.strftime("%H:%M"),
                "description": log.description,
            })
        
        # Собираем данные о воде
        hydration_events = await session.exec(
            select(HydrationEvent).where(
                HydrationEvent.user_id == user.telegram_id,
                HydrationEvent.plan_date >= start_date,
            )
        )
        hydration_data = []
        total_water_ml = 0
        for event in hydration_events.all():
            if event.completed:
                # Примерная оценка: каждое событие = ~200 мл
                water_ml = 200
                hydration_data.append({
                    "date": event.plan_date.isoformat(),
                    "time": event.target_time.strftime("%H:%M"),
                })
                total_water_ml += water_ml
        
        # Собираем данные о тренировках
        training_sessions = await session.exec(
            select(TrainingSession).where(
                TrainingSession.user_id == user.telegram_id,
                TrainingSession.created_at >= datetime.combine(start_date, time.min),
            )
        )
        trainings_data = []
        for session_obj in training_sessions.all():
            trainings_data.append({
                "date": session_obj.planned_time.date().isoformat(),
                "time": session_obj.planned_time.time().strftime("%H:%M"),
                "status": session_obj.status.value,
                "perceived_effort": session_obj.perceived_effort,
                "wellness_score": session_obj.wellness_score,
                "notes": session_obj.notes,
            })
        
        # Собираем данные о симптомах
        symptom_logs = await session.exec(
            select(SymptomLog).where(
                SymptomLog.user_id == user.telegram_id,
                SymptomLog.created_at >= datetime.combine(start_date, time.min),
            )
        )
        symptoms_data = []
        for log in symptom_logs.all():
            symptoms_data.append({
                "date": log.created_at.date().isoformat(),
                "description": log.description,
                "severity": log.severity,
            })
        
        # Формируем сводку для LLM
        summary_data = {
            "period_days": 3,
            "sleep": {
                "logs": sleep_data,
                "average_hours": round(avg_sleep_hours / 60, 1) if sleep_count > 0 else 0,
                "goal_hours": user.sleep_goal_minutes / 60,
                "total_logs": sleep_count,
            },
            "meals": {
                "logs": meals_data,
                "total_meals": len(meals_data),
            },
            "hydration": {
                "events": hydration_data,
                "total_ml": total_water_ml,
                "goal_ml": user.hydration_goal_ml,
                "goal_percentage": round((total_water_ml / user.hydration_goal_ml * 100) if user.hydration_goal_ml > 0 else 0, 1),
            },
            "training": {
                "sessions": trainings_data,
                "total_sessions": len([t for t in trainings_data if t["status"] == "completed"]),
                "cancelled": len([t for t in trainings_data if t["status"] == "cancelled"]),
            },
            "symptoms": {
                "logs": symptoms_data,
                "total": len(symptoms_data),
            },
        }
        
        # Формируем текстовую сводку для пользователя
        summary_text = f"📊 **Сводка за последние 3 дня**\n\n"
        
        # Сон
        summary_text += f"😴 **Сон:**\n"
        if sleep_count > 0:
            summary_text += f"  • Средняя длительность: {avg_sleep_hours / 60:.1f} ч (цель: {user.sleep_goal_minutes / 60:.1f} ч)\n"
            summary_text += f"  • Записей: {sleep_count}\n"
        else:
            summary_text += f"  • Нет данных\n"
        
        # Еда
        summary_text += f"\n🍽️ **Питание:**\n"
        summary_text += f"  • Записей о приёмах пищи: {len(meals_data)}\n"
        
        # Вода
        summary_text += f"\n💧 **Гидратация:**\n"
        summary_text += f"  • Выпито: ~{total_water_ml} мл (цель: {user.hydration_goal_ml} мл)\n"
        summary_text += f"  • Выполнение цели: {summary_data['hydration']['goal_percentage']}%\n"
        
        # Тренировки
        summary_text += f"\n💪 **Тренировки:**\n"
        summary_text += f"  • Завершено: {summary_data['training']['total_sessions']}\n"
        summary_text += f"  • Отменено: {summary_data['training']['cancelled']}\n"
        
        # Симптомы
        summary_text += f"\n🏥 **Самочувствие:**\n"
        summary_text += f"  • Записей о симптомах: {len(symptoms_data)}\n"
        
        await message.answer(summary_text, parse_mode="Markdown")
        
        # Генерируем LLM-анализ
        try:
            llm_analysis = await llm_client.generate_summary(user, summary_data)
            await message.answer(llm_analysis)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to generate LLM summary: {e}")
            await message.answer("Не удалось сгенерировать анализ. Проверьте настройки LLM.")


@router.message(F.text.lower() == "план на день")
async def menu_plan(message: Message) -> None:
    await cmd_plan(message)


@router.message(F.text.lower() == "профиль")
async def menu_profile(message: Message) -> None:
    await cmd_profile(message)


@router.message(F.text.lower() == "тренировка")
async def menu_training(message: Message, state: FSMContext) -> None:
    # Используем тот же обработчик, что и для "Я был на тренировке"
    from app.bot.routers.training import training_entry
    await training_entry(message, state)


@router.message(F.text.lower() == "вода")
async def menu_water(message: Message) -> None:
    from datetime import date
    from app.models import HydrationEvent
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == message.from_user.id))
        user = result.first()
        if not user:
            await message.answer("Профиль не найден. Используйте /start.")
            return
        
        # Подсчитываем выпитую воду сегодня
        today = date.today()
        events_result = await session.exec(
            select(HydrationEvent).where(
                HydrationEvent.user_id == user.telegram_id,
                HydrationEvent.plan_date == today,
                HydrationEvent.completed == True,
            )
        )
        completed_events = events_result.all()
        # Примерный объём порции (можно улучшить, если хранить объём в HydrationEvent)
        portion_ml = max(150, user.hydration_goal_ml // 8)  # Примерно 8 порций в день
        drank_ml = len(completed_events) * portion_ml
        progress = (drank_ml / user.hydration_goal_ml * 100) if user.hydration_goal_ml > 0 else 0
        
        status_text = (
            f"Выпито сегодня: {drank_ml} мл из {user.hydration_goal_ml} мл "
            f"({progress:.0f}%)\n\n"
            "Держите под рукой воду. Нажмите, когда выпьете порцию."
        )
        await message.answer(
            status_text,
            reply_markup=hydration_keyboard().as_markup(),
        )


@router.message(F.text.lower() == "у меня вопрос")
async def menu_llm(message: Message, state: FSMContext) -> None:
    await _prompt_llm(message, state)


@router.message(F.text.lower() == "я покушал")
async def menu_meal_log(message: Message, state: FSMContext) -> None:
    from app.bot.keyboards.common import main_menu
    from app.models import MealLog
    from datetime import datetime
    from app.services.modules import DEFAULT_MODULES
    
    await state.set_state(LLMStates.waiting)  # Переиспользуем состояние для ввода текста
    await state.update_data(action="meal_log")
    await message.answer(
        "Опишите, что вы съели. Например: 'Омлет с овощами и тост с авокадо' или 'Куриная грудка с рисом и салатом'."
    )


@router.message(LLMStates.waiting, F.text)
async def handle_llm_question(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    action = data.get("action")
    
    if action == "meal_log":
        from app.models import MealLog
        from datetime import datetime
        async with get_session() as session:
            result = await session.exec(select(User).where(User.telegram_id == message.from_user.id))
            user = result.first()
            if not user:
                await message.answer("Профиль не найден. Используйте /start.")
                await state.clear()
                return
            
            meal_log = MealLog(
                user_id=user.telegram_id,
                meal_time=datetime.now().time(),
                description=message.text.strip(),
            )
            session.add(meal_log)
            await session.commit()
        
        await message.answer("Записал приём пищи. Спасибо!")
        await state.clear()
        return
    
    # Обычная обработка LLM вопроса
    question = message.text.strip()
    if not question:
        await message.answer("Опишите вопрос текстом.")
        return
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == message.from_user.id))
        user = result.first()
    if not user:
        await message.answer("Профиль не найден. Используйте /start.")
        await state.clear()
        return
    answer = await llm_client.ask(user, question)
    await message.answer(answer)
    await state.clear()


@router.message(Command("modules"))
async def cmd_modules(message: Message) -> None:
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == message.from_user.id))
        user = result.first()
        if not user:
            await message.answer("Профиль не найден. Отправьте /start.")
            return
        modules = set(user.get_modules() or DEFAULT_MODULES)
    await message.answer(
        "Выберите активные модули.",
        reply_markup=modules_keyboard(modules, "manage").as_markup(),
    )


@router.message(F.text.lower() == "модули")
async def menu_modules(message: Message) -> None:
    await cmd_modules(message)


@router.callback_query(F.data.startswith("modules:manage:toggle:"))
async def modules_manage_toggle(callback: CallbackQuery) -> None:
    module_id = callback.data.split(":")[-1]
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.first()
        if not user:
            await callback.answer("Сначала пройдите /start", show_alert=True)
            return
        modules = set(user.get_modules() or DEFAULT_MODULES)
        if module_id in modules:
            modules.remove(module_id)
        else:
            modules.add(module_id)
        updated = normalize_modules(modules)
        user.set_modules(updated)
        session.add(user)
        await session.commit()
    await callback.message.edit_reply_markup(
        reply_markup=modules_keyboard(set(updated), "manage").as_markup()
    )
    await callback.answer("Сохранено")


@router.callback_query(F.data == "modules:manage:done")
async def modules_manage_done(callback: CallbackQuery) -> None:
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.first()
        if not user:
            await callback.answer("Профиль не найден", show_alert=True)
            return
        active_modules = set(user.get_modules() or DEFAULT_MODULES)
    # Удаляем сообщение с клавиатурой модулей
    await callback.message.delete()
    await callback.message.answer(
        "Настройки модулей сохранены.",
        reply_markup=main_menu(active_modules).as_markup(resize_keyboard=True),
    )
    await callback.answer()


async def _prompt_llm(message: Message, state: FSMContext) -> None:
    await state.set_state(LLMStates.waiting)
    await message.answer(
        "Напишите вопрос про сон, питание или тренировки одним сообщением. "
        "Добавлю дисклеймер и отвечу в пределах образовательных рекомендаций.",
        reply_markup=llm_cancel_keyboard().as_markup(),
    )


async def _get_or_generate_meal_plan(
    session, user: User, trainings: list[TrainingSession], target_calories: Optional[int] = None
) -> List[MealSlot]:
    result = await session.exec(
        select(MealPlan).where(
            MealPlan.user_id == user.telegram_id,
            MealPlan.plan_date == date.today(),
        )
    )
    meal_plan = result.first()
    if meal_plan:
        return deserialize_plan(meal_plan.payload)
    plan = generate_daily_plan(
        user,
        user.desired_wake_time,
        user.work_start,
        user.work_end,
        trainings,
        target_calories=target_calories,
    )
    meal_plan = MealPlan(
        user_id=user.telegram_id,
        plan_date=date.today(),
        payload=serialize_plan(plan),
    )
    session.add(meal_plan)
    await session.commit()
    return plan

