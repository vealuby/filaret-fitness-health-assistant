from __future__ import annotations

from datetime import datetime, time
from typing import Any, Dict, Optional

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlmodel import select

from app.bot.keyboards.common import modules_keyboard
from app.database import get_session
from app.models import User
from app.services.onboarding_parser import parse_freeform_profile
from app.services.modules import DEFAULT_MODULES, modules_from_text, normalize_modules
from app.services.sleep import build_bedtime_plan
from app.services.timezone import detect_timezone_from_user


router = Router(name="onboarding")


class OnboardingStates(StatesGroup):
    wake_time = State()
    sleep_goal = State()
    physical = State()
    age_sex = State()
    allergies = State()
    timezone = State()
    work_hours = State()
    training_schedule = State()
    goal = State()  # Цель: похудение, набор мышц, энергия, поддержание
    hydration = State()
    modules = State()


class QuickStartState(StatesGroup):
    waiting = State()


@router.message(CommandStart())
async def start_onboarding(message: Message, state: FSMContext) -> None:
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == message.from_user.id))
        user = result.first()
        if user:
            plan = build_bedtime_plan(user)
            await message.answer(
                "С возвращением! Текущий расчёт сна:\n"
                f"- Отбой: {plan.target_bedtime.strftime('%H:%M')}\n"
                f"- Подъём: {plan.wake_time.strftime('%H:%M')}\n"
                f"- Длительность: {int(plan.sleep_duration.total_seconds() // 3600)} ч\n"
                f"{plan.notes}"
            )
            await state.clear()
            return

    # Автоматически определяем timezone из language_code пользователя
    detected_tz = detect_timezone_from_user(message.from_user.language_code)
    await state.update_data(timezone=detected_tz)
    await _prompt_quickstart(message, state)


@router.message(OnboardingStates.wake_time, F.text)
async def set_wake_time(message: Message, state: FSMContext) -> None:
    try:
        desired_wake = _parse_time(message.text)
    except ValueError:
        await message.answer("Введите время в формате ЧЧ:ММ, например 07:30.")
        return
    await state.update_data(desired_wake_time=desired_wake.strftime("%H:%M"))
    await message.answer("Сколько часов сна вы целитесь? (пример: 7.5)")
    await state.set_state(OnboardingStates.sleep_goal)


@router.message(OnboardingStates.sleep_goal, F.text)
async def set_sleep_goal(message: Message, state: FSMContext) -> None:
    try:
        hours = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Введите число, например 7.5")
        return
    await state.update_data(sleep_goal_minutes=int(hours * 60))
    await message.answer("Укажите рост и вес через пробел (пример: 178 74).")
    await state.set_state(OnboardingStates.physical)


@router.message(OnboardingStates.physical, F.text)
async def set_physical(message: Message, state: FSMContext) -> None:
    parts = message.text.replace(",", " ").split()
    try:
        height = int(parts[0])
        weight = float(parts[1])
    except (ValueError, IndexError):
        await message.answer("Формат: 178 74")
        return
    await state.update_data(height_cm=height, weight_kg=weight)
    await message.answer("Укажите возраст и пол (формат: 30 м или 25 ж). Если не хотите указывать — отправьте 'пропустить'.")
    await state.set_state(OnboardingStates.age_sex)


@router.message(OnboardingStates.age_sex, F.text)
async def set_age_sex(message: Message, state: FSMContext) -> None:
    text = message.text.strip().lower()
    if text in ("пропустить", "пропустить", "skip", "ок", "ok"):
        await state.update_data(age=None, sex=None)
    else:
        parts = text.split()
        age = None
        sex = None
        for part in parts:
            # Пытаемся найти возраст
            try:
                age_val = int(part)
                if 10 <= age_val <= 100:
                    age = age_val
            except ValueError:
                pass
            # Пытаемся найти пол
            if part in ("м", "m", "муж", "мужской"):
                sex = "m"
            elif part in ("ж", "f", "жен", "женский"):
                sex = "f"
        await state.update_data(age=age, sex=sex)
    await message.answer("Есть ли аллергии или ограничения? Если нет — напишите «нет».")
    await state.set_state(OnboardingStates.allergies)


@router.message(OnboardingStates.allergies, F.text)
async def set_allergies(message: Message, state: FSMContext) -> None:
    await state.update_data(allergies=message.text.strip())
    # Автоматически определяем timezone
    detected_tz = detect_timezone_from_user(message.from_user.language_code)
    await state.update_data(timezone=detected_tz)
    await message.answer(
        f"Часовой пояс определён автоматически: {detected_tz}.\n"
        "Если нужно изменить, напишите другой (например: Europe/Moscow), иначе отправьте 'ок'."
    )
    await state.set_state(OnboardingStates.timezone)


@router.message(OnboardingStates.timezone, F.text)
async def set_timezone(message: Message, state: FSMContext) -> None:
    text = message.text.strip().lower()
    if text not in ("ок", "ok", "подтвердить", "да"):
        # Пользователь указал свой timezone
        tz = message.text.strip()
        await state.update_data(timezone=tz)
    # Иначе используем автоматически определённый
    await message.answer("Ваши рабочие часы? Формат 09:00-18:00.")
    await state.set_state(OnboardingStates.work_hours)


@router.message(OnboardingStates.work_hours, F.text)
async def set_work_schedule(message: Message, state: FSMContext) -> None:
    try:
        start_text, end_text = message.text.split("-")
        work_start = _parse_time(start_text)
        work_end = _parse_time(end_text)
    except Exception:
        await message.answer("Укажите время как 09:00-18:00")
        return
    await state.update_data(work_start=work_start.strftime("%H:%M"), work_end=work_end.strftime("%H:%M"))
    await message.answer(
        "Перечислите тренировки (пример: пн 19:00, чт 20:00). Если нет — напишите «нет»."
    )
    await state.set_state(OnboardingStates.training_schedule)


@router.message(OnboardingStates.training_schedule, F.text)
async def set_workouts(message: Message, state: FSMContext) -> None:
    text = message.text.lower()
    schedule = []
    if text != "нет":
        for item in text.split(","):
            parts = item.strip().split()
            if len(parts) != 2:
                continue
            schedule.append({"day": parts[0][:3], "time": parts[1]})
    await state.update_data(workouts=schedule)
    await message.answer(
        "Какова ваша основная цель?\n"
        "1. Похудение / Снижение веса\n"
        "2. Набор мышц / Набор массы\n"
        "3. Энергия / Бодрость\n"
        "4. Поддержание веса\n"
        "Напишите номер или название цели."
    )
    await state.set_state(OnboardingStates.goal)


@router.message(OnboardingStates.goal, F.text)
async def set_goal(message: Message, state: FSMContext) -> None:
    text = message.text.strip().lower()
    goal_map = {
        "1": "похудение",
        "2": "набор мышц",
        "3": "энергия",
        "4": "поддержание веса",
        "похуд": "похудение",
        "сниж": "снижение веса",
        "вес": "снижение веса",
        "мышц": "набор мышц",
        "масс": "набор мышц",
        "энерг": "энергия",
        "бодр": "энергия",
        "поддерж": "поддержание веса",
    }
    goal = None
    for key, value in goal_map.items():
        if key in text:
            goal = value
            break
    if not goal:
        goal = text  # Сохраняем как есть, если не распознали
    await state.update_data(goal=goal)
    # Рассчитываем цель по воде на основе роста/веса и цели
    from app.services.nutrition_calculator import generate_nutrition_plan
    data = await state.get_data()
    if data.get("weight_kg") and data.get("height_cm"):
        # Создаём профиль для расчета через новый модуль
        activity = "moderate"
        goal_text = (goal or "").lower()
        if "тренировк" in goal_text:
            activity = "high"
        
        calc_goal = "maintain"
        if "похуд" in goal_text or "сниж" in goal_text:
            calc_goal = "lose"
        elif "мышц" in goal_text or "масс" in goal_text:
            calc_goal = "gain"
        
        nutrition_profile = {
            "sex": data.get("sex") or "m",
            "age": data.get("age") or 30,
            "weight_kg": data.get("weight_kg"),
            "height_cm": data.get("height_cm"),
            "activity": activity,
            "goal": calc_goal,
        }
        
        try:
            nutrition_plan = generate_nutrition_plan(nutrition_profile)
            calculated_goal = nutrition_plan["numbers"]["water_ml"]
            calories = nutrition_plan["numbers"]["calories"]
            macros = nutrition_plan["numbers"]["macros"]
            await message.answer(
                f"Рассчитанная цель по воде: {calculated_goal} мл.\n"
                f"Рекомендуемые калории: ~{calories} ккал (Б/Ж/У {macros['protein_g']}/{macros['fat_g']}/{macros['carb_g']} г).\n"
                f"Хотите изменить воду? (напишите новое значение в мл или отправьте 'ок' для подтверждения)"
            )
            await state.update_data(hydration_goal_ml=calculated_goal)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to calculate nutrition plan: {e}")
            # Fallback
            from app.services.personalization import calculate_hydration_goal
            from app.models import User
            temp_user = User(
                telegram_id=0,
                weight_kg=data.get("weight_kg"),
                height_cm=data.get("height_cm"),
                goals=goal,
            )
            calculated_goal = calculate_hydration_goal(temp_user)
            await message.answer(
                f"Рассчитанная цель по воде: {calculated_goal} мл.\n"
                f"Хотите изменить? (напишите новое значение в мл или отправьте 'ок' для подтверждения)"
            )
            await state.update_data(hydration_goal_ml=calculated_goal)
    else:
        await message.answer("Цель по воде в мл? (пример: 2200)")
    await state.set_state(OnboardingStates.hydration)


@router.message(OnboardingStates.hydration, F.text)
async def finalize(message: Message, state: FSMContext) -> None:
    text = message.text.strip().lower()
    if text not in ("ок", "ok", "подтвердить", "да"):
        try:
            hydration = int(text)
            await state.update_data(hydration_goal_ml=hydration)
        except ValueError:
            await message.answer("Введите целое число, например 2200, или 'ок' для подтверждения.")
            return
    await state.update_data(modules=DEFAULT_MODULES.copy())
    await message.answer(
        "Выберите, какие модули включить. Нажимайте несколько раз для выбора/отмены, затем «Готово».",
        reply_markup=modules_keyboard(set(DEFAULT_MODULES), "onboarding").as_markup(),
    )
    await state.set_state(OnboardingStates.modules)


@router.message(Command("quickstart"))
async def quickstart(message: Message, state: FSMContext) -> None:
    await _prompt_quickstart(message, state)


@router.message(Command("setup"))
async def setup_flow(message: Message, state: FSMContext) -> None:
    await state.set_state(OnboardingStates.wake_time)
    await message.answer(
        "Пошаговый режим. Начнём с желаемого времени подъёма (формат 07:30). "
        "В любой момент можно вернуться к быстрому режиму командой /quickstart."
    )


@router.message(QuickStartState.waiting, F.text)
async def quickstart_process(message: Message, state: FSMContext) -> None:
    parsed = await parse_freeform_profile(message.text)
    if not parsed.desired_wake_time or not parsed.sleep_goal_minutes:
        await message.answer(
            "Не удалось распознать время подъёма или цель сна. Уточните эти параметры "
            "или пройдите пошаговый /start."
        )
        return
    modules = modules_from_text(" ".join(parsed.goals)) if parsed.goals else DEFAULT_MODULES
    # Автоматически определяем timezone, если не указан
    detected_tz = detect_timezone_from_user(message.from_user.language_code)
    
    # Определяем цель из parsed.goals
    goal = None
    if parsed.goals:
        goals_text = " ".join(parsed.goals).lower()
        if any(kw in goals_text for kw in ["похуд", "сниж", "вес"]):
            goal = "похудение"
        elif any(kw in goals_text for kw in ["мышц", "масс", "набор"]):
            goal = "набор мышц"
        elif any(kw in goals_text for kw in ["энерг", "бодр"]):
            goal = "энергия"
        else:
            goal = parsed.goals[0] if parsed.goals else None
    
    # Рассчитываем цель по воде и КБЖУ через новый модуль
    from app.services.nutrition_calculator import generate_nutrition_plan
    hydration_goal = parsed.hydration_goal_ml
    
    # Создаём профиль для расчета
    if parsed.weight_kg and parsed.height_cm:
        # Определяем активность
        activity = "moderate"
        if "тренировк" in " ".join(parsed.goals).lower() if parsed.goals else "":
            activity = "high"
        
        # Определяем цель для расчета
        calc_goal = "maintain"
        if goal:
            goals_lower = goal.lower()
            if "похуд" in goals_lower or "сниж" in goals_lower:
                calc_goal = "lose"
            elif "мышц" in goals_lower or "масс" in goals_lower or "набор" in goals_lower:
                calc_goal = "gain"
        
        nutrition_profile = {
            "sex": parsed.sex or "m",
            "age": parsed.age or 30,
            "weight_kg": parsed.weight_kg,
            "height_cm": parsed.height_cm,
            "activity": activity,
            "goal": calc_goal,
        }
        
        try:
            nutrition_plan = generate_nutrition_plan(nutrition_profile)
            # Используем рассчитанную воду, если пользователь не указал явно
            if not hydration_goal:
                hydration_goal = nutrition_plan["numbers"]["water_ml"]
            # Если LLM вернул значение, но оно кажется неправильным, используем расчет
            elif hydration_goal > 5000:
                hydration_goal = nutrition_plan["numbers"]["water_ml"]
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to calculate nutrition plan: {e}")
            # Fallback на старый метод
            from app.services.personalization import calculate_hydration_goal
            from app.models import User
            temp_user = User(
                telegram_id=0,
                weight_kg=parsed.weight_kg,
                height_cm=parsed.height_cm or 170,
                goals=goal or "",
            )
            hydration_goal = hydration_goal or calculate_hydration_goal(temp_user) or 2000
    else:
        hydration_goal = hydration_goal or 2000
    
    # Используем detected_tz, а не parsed.timezone (LLM может вернуть неправильный timezone)
    payload = {
        "telegram_id": message.from_user.id,
        "timezone": detected_tz,  # Всегда используем автоматически определенный timezone
        "desired_wake_time": parsed.desired_wake_time,
        "sleep_goal_minutes": parsed.sleep_goal_minutes,
        "height_cm": parsed.height_cm,
        "weight_kg": parsed.weight_kg,
        "age": parsed.age,
        "sex": parsed.sex,
        "allergies": parsed.allergies,
        "work_start": parsed.work_start,
        "work_end": parsed.work_end,
        "hydration_goal_ml": hydration_goal or 2000,
        "modules": modules,
        "workouts": parsed.workouts,
        "goal": goal,
        "goals_text": goal or ", ".join(parsed.goals) if parsed.goals else None,
    }
    user = await _persist_user(payload)
    plan = build_bedtime_plan(user)
    from app.bot.keyboards.common import main_menu
    await message.answer(
        "Отлично, данные сохранены!\n"
        f"Отбой: {plan.target_bedtime.strftime('%H:%M')} при подъёме {plan.wake_time.strftime('%H:%M')}.\n"
        f"{plan.notes}",
        reply_markup=main_menu().as_markup(resize_keyboard=True),
    )
    await state.clear()


@router.callback_query(OnboardingStates.modules, F.data.startswith("modules:onboarding:toggle:"))
async def onboarding_modules_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    module_id = callback.data.split(":")[-1]
    data = await state.get_data()
    modules = set(data.get("modules", DEFAULT_MODULES))
    if module_id in modules:
        modules.remove(module_id)
    else:
        modules.add(module_id)
    normalized = normalize_modules(modules)
    await state.update_data(modules=normalized)
    await callback.message.edit_reply_markup(
        reply_markup=modules_keyboard(set(normalized), "onboarding").as_markup()
    )
    await callback.answer("Обновлено")


@router.callback_query(OnboardingStates.modules, F.data == "modules:onboarding:done")
async def onboarding_modules_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    modules = data.get("modules", DEFAULT_MODULES)
    # Автоматически определяем timezone, если не указан
    detected_tz = detect_timezone_from_user(callback.from_user.language_code)
    
    payload = {
        "telegram_id": callback.from_user.id,
        "timezone": data.get("timezone") or detected_tz,
        "desired_wake_time": data.get("desired_wake_time"),
        "sleep_goal_minutes": data.get("sleep_goal_minutes"),
        "height_cm": data.get("height_cm"),
        "weight_kg": data.get("weight_kg"),
        "allergies": data.get("allergies"),
        "work_start": data.get("work_start"),
        "work_end": data.get("work_end"),
        "hydration_goal_ml": data.get("hydration_goal_ml"),
        "modules": modules,
        "workouts": data.get("workouts", []),
        "goal": data.get("goal"),  # Сохраняем цель отдельно
        "goals_text": data.get("goal") or ", ".join(modules),
    }
    user = await _persist_user(payload)
    plan = build_bedtime_plan(user)
    from app.bot.keyboards.common import main_menu
    # Удаляем сообщение с клавиатурой модулей
    await callback.message.delete()
    await callback.message.answer(
        "Отлично, профиль сохранён!\n"
        f"Рекомендуемый отбой: {plan.target_bedtime.strftime('%H:%M')} "
        f"при подъёме {plan.wake_time.strftime('%H:%M')}.\n"
        f"{plan.notes}",
        reply_markup=main_menu(set(modules)).as_markup(resize_keyboard=True),
    )
    await callback.answer()
    await state.clear()


def _parse_time(value: str) -> time:
    return datetime.strptime(value.strip(), "%H:%M").time()


def _ensure_time_value(value: Optional[time | str]) -> Optional[time]:
    if value is None:
        return None
    if isinstance(value, time):
        return value
    return _parse_time(value)


async def _persist_user(payload: Dict[str, Any]) -> User:
    desired_wake = _ensure_time_value(payload.get("desired_wake_time"))
    if desired_wake is None:
        raise ValueError("desired_wake_time is required")
    modules = normalize_modules(payload.get("modules", DEFAULT_MODULES))
    # Убеждаемся, что timezone установлен
    default_tz = detect_timezone_from_user(None)  # Получим дефолтный
    async with get_session() as session:
        # Проверяем, существует ли пользователь
        result = await session.exec(select(User).where(User.telegram_id == payload["telegram_id"]))
        user = result.first()
        
        if user:
            # Обновляем существующего пользователя
            user.timezone = payload.get("timezone") or user.timezone or default_tz
            user.desired_wake_time = desired_wake
            user.sleep_goal_minutes = payload.get("sleep_goal_minutes", user.sleep_goal_minutes or 450)
            if payload.get("height_cm") is not None:
                user.height_cm = payload["height_cm"]
            if payload.get("weight_kg") is not None:
                user.weight_kg = payload["weight_kg"]
            if payload.get("age") is not None:
                user.age = payload["age"]
            if payload.get("sex") is not None:
                user.sex = payload["sex"]
            if payload.get("allergies") is not None:
                user.allergies = payload["allergies"]
            if payload.get("work_start") is not None:
                user.work_start = _ensure_time_value(payload.get("work_start"))
            if payload.get("work_end") is not None:
                user.work_end = _ensure_time_value(payload.get("work_end"))
            if payload.get("hydration_goal_ml") is not None:
                user.hydration_goal_ml = payload["hydration_goal_ml"]
            if payload.get("goals_text"):
                user.goals = payload["goals_text"]
            user.set_modules(modules)
            workouts = payload.get("workouts") or []
            if workouts:
                user.set_workout_days(workouts)
        else:
            # Создаём нового пользователя
            user = User(
                telegram_id=payload["telegram_id"],
                timezone=payload.get("timezone") or default_tz,
                desired_wake_time=desired_wake,
                sleep_goal_minutes=payload.get("sleep_goal_minutes", 450),
                height_cm=payload.get("height_cm"),
                weight_kg=payload.get("weight_kg"),
                age=payload.get("age"),
                sex=payload.get("sex"),
                allergies=payload.get("allergies"),
                work_start=_ensure_time_value(payload.get("work_start")),
                work_end=_ensure_time_value(payload.get("work_end")),
                hydration_goal_ml=payload.get("hydration_goal_ml", 2000),
                goals=payload.get("goals_text") or ", ".join(modules),
            )
            user.set_modules(modules)
            workouts = payload.get("workouts") or []
            if workouts:
                user.set_workout_days(workouts)
            session.add(user)
        
        await session.commit()
        await session.refresh(user)
        return user


async def _prompt_quickstart(message: Message, state: FSMContext) -> None:
    await state.set_state(QuickStartState.waiting)
    await message.answer(
        "Опишите одним сообщением свои цели: когда хотите просыпаться, сколько спать, "
        "рабочие часы, тренировки (дни и время), пол, возраст, рост и вес, аллергии и цель по воде (при наличии).\n"
        "Пример: «Обычно встаю в 08:00, работаю с 09 до 18, тренировки пн/ср/пт в 19:00, "
        "хочу похудеть и следить за питанием, рост 178 вес 74, хочу пить 2200 мл воды».\n"
        "Если нужна пошаговая настройка — используйте /setup."
    )

