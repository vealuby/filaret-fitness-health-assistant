from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from typing import Any, Optional

from app.services.llm import llm_client


def calculate_bmi(weight_kg: float, height_cm: float) -> float:
    """Рассчитывает BMI"""
    height_m = height_cm / 100
    return weight_kg / (height_m ** 2)


def calculate_bmr(weight_kg: float, height_cm: float, age: int, sex: str) -> int:
    """
    Рассчитывает BMR по формуле Миффлина-Сан Жеора.
    
    Args:
        weight_kg: Вес в кг
        height_cm: Рост в см
        age: Возраст в годах
        sex: 'm' для мужчин, 'f' для женщин
    
    Returns:
        BMR в ккал
    """
    if sex == 'm':
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    else:  # 'f'
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161
    return int(round(bmr))


def get_activity_factor(activity: str) -> float:
    """Возвращает коэффициент активности"""
    factors = {
        'sedentary': 1.2,
        'light': 1.375,
        'moderate': 1.55,
        'high': 1.725,
        'very_high': 1.9,
    }
    return factors.get(activity, 1.55)  # По умолчанию moderate


def calculate_tdee(bmr: int, activity: str) -> int:
    """Рассчитывает TDEE (Total Daily Energy Expenditure)"""
    factor = get_activity_factor(activity)
    return int(round(bmr * factor))


def calculate_target_calories(tdee: int, goal: str, age: int) -> int:
    """
    Рассчитывает целевые калории в зависимости от цели.
    
    Args:
        tdee: TDEE в ккал
        goal: 'maintain', 'lose', или 'gain'
        age: Возраст (для проверки безопасности)
    
    Returns:
        Целевые калории в ккал
    """
    if goal == 'maintain':
        return tdee
    elif goal == 'lose':
        # Дефицит 400 ккал, минимум 1200
        # Для несовершеннолетних ограничиваем дефицит до 300
        deficit = 300 if age < 18 else 400
        return max(1200, tdee - deficit)
    elif goal == 'gain':
        # Профицит 300 ккал
        return tdee + 300
    else:
        return tdee


def calculate_macros(total_kcal: int, weight_kg: float, goal: str) -> dict[str, Any]:
    """
    Рассчитывает макронутриенты в граммах и ккал.
    
    Args:
        total_kcal: Общее количество калорий
        weight_kg: Вес в кг
        goal: Цель ('maintain', 'lose', 'gain')
    
    Returns:
        Словарь с макронутриентами
    """
    # Белок: 1.6 г/кг для maintain/lose, 1.8 г/кг для gain
    protein_per_kg = 1.8 if goal == 'gain' else 1.6
    protein_g = round(protein_per_kg * weight_kg)
    protein_kcal = protein_g * 4
    
    # Жиры: 25% от общего количества калорий
    fat_pct = 0.25
    fat_kcal = int(round(total_kcal * fat_pct))
    fat_g = round(fat_kcal / 9)
    
    # Углеводы: остаток
    carb_kcal = total_kcal - protein_kcal - fat_kcal
    carb_g = round(max(0, carb_kcal / 4))
    
    return {
        "protein_g": int(protein_g),
        "fat_g": int(fat_g),
        "carb_g": int(carb_g),
        "protein_kcal": int(protein_kcal),
        "fat_kcal": int(fat_kcal),
        "carb_kcal": int(carb_kcal),
    }


def calculate_water_ml(
    weight_kg: float,
    activity: str,
    training_minutes: int = 0,
) -> int:
    """
    Рассчитывает суточную норму воды в мл.
    
    Args:
        weight_kg: Вес в кг
        activity: Уровень активности
        training_minutes: Минуты тренировок в день
    
    Returns:
        Норма воды в мл
    """
    # Базовая норма: 35 мл на кг веса
    base_ml = weight_kg * 35
    
    # Корректировка по активности
    activity_multipliers = {
        'sedentary': 0.95,
        'light': 1.0,
        'moderate': 1.0,
        'high': 1.02,
        'very_high': 1.05,
    }
    multiplier = activity_multipliers.get(activity, 1.0)
    base_ml_adjusted = base_ml * multiplier
    
    # Дополнительно для тренировок: 400 мл на 60 минут
    extra_ml = (400 / 60) * training_minutes
    
    water_ml = int(round(base_ml_adjusted + extra_ml))
    return water_ml


def parse_time(time_str: Optional[str]) -> Optional[time]:
    """Парсит время из строки 'HH:MM'"""
    if not time_str:
        return None
    try:
        hour, minute = map(int, time_str.split(':'))
        return time(hour=hour, minute=minute)
    except (ValueError, AttributeError):
        return None


def add_minutes(t: time, minutes: int) -> time:
    """Добавляет минуты к времени"""
    dt = datetime.combine(datetime.today(), t)
    dt += timedelta(minutes=minutes)
    return dt.time()


def generate_meal_schedule(
    calories: int,
    macros: dict[str, Any],
    wake_time: Optional[time] = None,
    work_start: Optional[time] = None,
    work_end: Optional[time] = None,
    training_time: Optional[time] = None,
    training_minutes: int = 0,
) -> dict[str, Any]:
    """
    Генерирует расписание приёмов пищи.
    
    Returns:
        Словарь с meals и pre_post_workout
    """
    meals = []
    
    # Распределение калорий: завтрак 25%, обед 35%, ужин 30%, перекус 10%
    breakfast_kcal = int(round(calories * 0.25))
    lunch_kcal = int(round(calories * 0.35))
    dinner_kcal = int(round(calories * 0.30))
    snack_kcal = calories - breakfast_kcal - lunch_kcal - dinner_kcal
    
    # Распределение макронутриентов пропорционально
    total_protein = macros['protein_g']
    total_fat = macros['fat_g']
    total_carb = macros['carb_g']
    
    breakfast_protein = int(round(total_protein * 0.25))
    breakfast_fat = int(round(total_fat * 0.25))
    breakfast_carb = int(round(total_carb * 0.25))
    
    lunch_protein = int(round(total_protein * 0.35))
    lunch_fat = int(round(total_fat * 0.35))
    lunch_carb = int(round(total_carb * 0.35))
    
    dinner_protein = int(round(total_protein * 0.30))
    dinner_fat = int(round(total_fat * 0.30))
    dinner_carb = int(round(total_carb * 0.30))
    
    snack_protein = total_protein - breakfast_protein - lunch_protein - dinner_protein
    snack_fat = total_fat - breakfast_fat - lunch_fat - dinner_fat
    snack_carb = total_carb - breakfast_carb - lunch_carb - dinner_carb
    
    # Время завтрака: через 30 минут после пробуждения
    if wake_time:
        breakfast_time = add_minutes(wake_time, 30)
    else:
        breakfast_time = time(8, 0)  # По умолчанию 08:00
    
    meals.append({
        "name": "Breakfast",
        "time": breakfast_time.strftime("%H:%M"),
        "kcal": breakfast_kcal,
        "protein_g": breakfast_protein,
        "fat_g": breakfast_fat,
        "carb_g": breakfast_carb,
        "example": "Омлет с овощами, цельнозерновой тост",
    })
    
    # Время обеда: середина рабочего дня или 13:00
    if work_start and work_end:
        # Середина рабочего дня
        work_start_dt = datetime.combine(datetime.today(), work_start)
        work_end_dt = datetime.combine(datetime.today(), work_end)
        midpoint_dt = work_start_dt + (work_end_dt - work_start_dt) / 2
        lunch_time = midpoint_dt.time()
    else:
        lunch_time = time(13, 0)  # По умолчанию 13:00
    
    meals.append({
        "name": "Lunch",
        "time": lunch_time.strftime("%H:%M"),
        "kcal": lunch_kcal,
        "protein_g": lunch_protein,
        "fat_g": lunch_fat,
        "carb_g": lunch_carb,
        "example": "Запечённая курица, киноа, салат с оливковым маслом",
    })
    
    # Время ужина: за 3 часа до сна (предполагаем сон в 23:00, если не указано)
    if wake_time:
        # Предполагаем 8 часов сна
        bedtime = add_minutes(wake_time, -8 * 60)
        dinner_time = add_minutes(bedtime, -3 * 60)
    else:
        dinner_time = time(20, 0)  # По умолчанию 20:00
    
    meals.append({
        "name": "Dinner",
        "time": dinner_time.strftime("%H:%M"),
        "kcal": dinner_kcal,
        "protein_g": dinner_protein,
        "fat_g": dinner_fat,
        "carb_g": dinner_carb,
        "example": "Запечённый лосось с овощами",
    })
    
    # Перекус: между обедом и ужином
    if lunch_time and dinner_time:
        snack_dt = datetime.combine(datetime.today(), lunch_time)
        dinner_dt = datetime.combine(datetime.today(), dinner_time)
        snack_dt = snack_dt + (dinner_dt - snack_dt) / 2
        snack_time = snack_dt.time()
    else:
        snack_time = time(16, 0)  # По умолчанию 16:00
    
    meals.append({
        "name": "Snack",
        "time": snack_time.strftime("%H:%M"),
        "kcal": snack_kcal,
        "protein_g": snack_protein,
        "fat_g": snack_fat,
        "carb_g": snack_carb,
        "example": "Греческий йогурт с ягодами",
    })
    
    # Pre/post workout
    pre_workout = None
    post_workout = None
    
    if training_time and training_minutes > 0:
        # Pre-workout: за 30-60 минут до тренировки
        pre_time = add_minutes(training_time, -45)
        pre_workout = {
            "time": pre_time.strftime("%H:%M"),
            "type": "snack",
            "example": "Банан или небольшой энергетический батончик",
        }
        
        # Post-workout: через 30-60 минут после тренировки
        post_time = add_minutes(training_time, training_minutes + 30)
        post_workout = {
            "time": post_time.strftime("%H:%M"),
            "type": "recovery",
            "example": "Протеиновый коктейль или куриная грудка с рисом",
        }
    
    return {
        "meals": meals,
        "pre_post_workout": {
            "pre_workout": pre_workout,
            "post_workout": post_workout,
        },
    }


def generate_water_schedule(
    water_ml: int,
    wake_time: Optional[time] = None,
    bedtime: Optional[time] = None,
    n_reminders: int = 8,
) -> list[dict[str, Any]]:
    """
    Генерирует расписание напоминаний о воде.
    
    Args:
        water_ml: Общее количество воды в мл
        wake_time: Время пробуждения
        bedtime: Время отхода ко сну
        n_reminders: Количество напоминаний
    
    Returns:
        Список напоминаний с временем и количеством мл
    """
    if not wake_time:
        wake_time = time(8, 0)
    if not bedtime:
        # Предполагаем 16 часов бодрствования
        bedtime = add_minutes(wake_time, 16 * 60)
    
    # Рассчитываем интервал между напоминаниями
    wake_dt = datetime.combine(datetime.today(), wake_time)
    bed_dt = datetime.combine(datetime.today(), bedtime)
    if bed_dt < wake_dt:
        bed_dt += timedelta(days=1)
    
    total_minutes = int((bed_dt - wake_dt).total_seconds() / 60)
    interval_minutes = total_minutes // (n_reminders + 1)
    
    ml_per_reminder = water_ml // n_reminders
    
    reminders = []
    current_time = wake_time
    for i in range(n_reminders):
        current_time = add_minutes(current_time, interval_minutes)
        reminders.append({
            "time": current_time.strftime("%H:%M"),
            "ml": ml_per_reminder,
        })
    
    return reminders


def generate_nutrition_plan(profile: dict[str, Any]) -> dict[str, Any]:
    """
    Генерирует детальный план питания и гидратации.
    
    Args:
        profile: Словарь с данными пользователя:
            - sex: 'm'|'f'
            - age: int
            - weight_kg: float
            - height_cm: float
            - activity: 'sedentary'|'light'|'moderate'|'high'|'very_high'
            - goal: 'maintain'|'lose'|'gain'
            - desired_wake_time: 'HH:MM' (optional)
            - work_start: 'HH:MM' (optional)
            - work_end: 'HH:MM' (optional)
            - training_minutes: int (optional)
            - training_time: 'HH:MM' (optional)
    
    Returns:
        Словарь с полным планом питания
    """
    # Валидация входных данных
    warnings = []
    consult_clinician = False
    
    age = profile.get('age', 30)
    weight_kg = profile.get('weight_kg')
    height_cm = profile.get('height_cm')
    sex = profile.get('sex', 'm')
    
    if not weight_kg or not height_cm:
        raise ValueError("weight_kg and height_cm are required")
    
    # Проверка возраста
    if age < 18:
        warnings.append("under_18")
        consult_clinician = True
    
    # Проверка BMI
    bmi = calculate_bmi(weight_kg, height_cm)
    if bmi < 16:
        warnings.append("extreme_bmi_low")
        consult_clinician = True
    elif bmi > 40:
        warnings.append("extreme_bmi_high")
        consult_clinician = True
    
    # Рассчитываем BMR и TDEE
    bmr = calculate_bmr(weight_kg, height_cm, age, sex)
    activity = profile.get('activity', 'moderate')
    tdee = calculate_tdee(bmr, activity)
    
    # Рассчитываем целевые калории
    goal = profile.get('goal', 'maintain')
    calories = calculate_target_calories(tdee, goal, age)
    
    # Рассчитываем макронутриенты
    macros = calculate_macros(calories, weight_kg, goal)
    
    # Рассчитываем воду
    training_minutes = profile.get('training_minutes', 0)
    water_ml = calculate_water_ml(weight_kg, activity, training_minutes)
    
    # Генерируем расписание приёмов пищи
    wake_time = parse_time(profile.get('desired_wake_time'))
    work_start = parse_time(profile.get('work_start'))
    work_end = parse_time(profile.get('work_end'))
    training_time = parse_time(profile.get('training_time'))
    
    meal_schedule = generate_meal_schedule(
        calories,
        macros,
        wake_time,
        work_start,
        work_end,
        training_time,
        training_minutes,
    )
    
    # Генерируем расписание воды
    bedtime = None
    if wake_time:
        # Предполагаем 8 часов сна
        bedtime = add_minutes(wake_time, -8 * 60)
    
    water_reminders = generate_water_schedule(water_ml, wake_time, bedtime)
    
    # Формируем результат
    result = {
        "meta": {
            "timestamp": datetime.utcnow().isoformat(),
            "input_profile": profile,
            "warnings": warnings,
            "consult_clinician": consult_clinician,
            "deterministic_version": "mifflin_v1",
        },
        "numbers": {
            "bmr": bmr,
            "tdee": tdee,
            "calories": calories,
            "macros": macros,
            "water_ml": water_ml,
        },
        "schedule": {
            "wake_time": wake_time.strftime("%H:%M") if wake_time else None,
            "bedtime": bedtime.strftime("%H:%M") if bedtime else None,
            "meals": meal_schedule["meals"],
            "water_reminders": water_reminders,
            "pre_post_workout": meal_schedule["pre_post_workout"],
        },
        "llm_prompt": "",  # Будет заполнено при вызове LLM
        "llm_response": None,
        "human_text": "",
    }
    
    return result


async def enrich_with_llm(plan: dict[str, Any]) -> dict[str, Any]:
    """
    Обогащает план ответом от LLM.
    
    Args:
        plan: Результат generate_nutrition_plan
    
    Returns:
        План с добавленными llm_prompt и llm_response
    """
    if not llm_client.enabled:
        plan["human_text"] = (
            f"Ваш план: {plan['numbers']['calories']} ккал, "
            f"Б/Ж/У {plan['numbers']['macros']['protein_g']}/{plan['numbers']['macros']['fat_g']}/{plan['numbers']['macros']['carb_g']} г, "
            f"вода {plan['numbers']['water_ml']} мл."
        )
        return plan
    
    # Формируем промпт для LLM
    system_prompt = (
        "You are a professional non-medical nutrition and lifestyle assistant. "
        "Always begin with a short disclaimer: 'I am not a doctor. This information is general advice.' "
        "Keep responses concise, practical, and actionable. "
        "If profile contains 'under_18' or other red flags, instruct the user to consult a clinician "
        "and avoid giving prescriptive plans."
    )
    
    user_prompt = f"""Context: {json.dumps(plan['meta']['input_profile'], ensure_ascii=False, indent=2)}

Deterministic results: {json.dumps(plan['numbers'], ensure_ascii=False, indent=2)}
Schedule: {json.dumps(plan['schedule'], ensure_ascii=False, indent=2)}

TASKS:
1) Produce a 2-4 sentence user-friendly summary reporting calories, macros and water.
2) Suggest realistic meal examples matching each meal's macro targets.
3) Provide a simple water reminder schedule text (human-readable) matching the schedule.
4) Give 3 sleep-improvement tips (if wake_time provided).
5) Output structured JSON with keys: summary, meals (list), water_schedule (list), sleep_tips (list), disclaimer.
Return only JSON."""
    
    plan["llm_prompt"] = user_prompt
    
    try:
        # Вызываем LLM
        if not llm_client._client:
            raise ValueError("LLM client not available")
        
        import asyncio
        response = await asyncio.to_thread(
            llm_client._client.chat.completions.create,
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        
        content = response.choices[0].message.content.strip()
        # Пытаемся распарсить JSON из ответа
        try:
            llm_json = json.loads(content)
            plan["llm_response"] = llm_json
            plan["human_text"] = llm_json.get("summary", plan["human_text"])
        except json.JSONDecodeError:
            # Если не JSON, используем как есть
            plan["llm_response"] = {"raw": content}
            plan["human_text"] = content
    except Exception:
        # В случае ошибки используем базовый текст
        plan["human_text"] = (
            f"Ваш план: {plan['numbers']['calories']} ккал, "
            f"Б/Ж/У {plan['numbers']['macros']['protein_g']}/{plan['numbers']['macros']['fat_g']}/{plan['numbers']['macros']['carb_g']} г, "
            f"вода {plan['numbers']['water_ml']} мл."
        )
    
    return plan

