from __future__ import annotations

from typing import Optional

from app.models import User
from app.services.nutrition_calculator import (
    calculate_water_ml,
    generate_nutrition_plan,
)


def estimate_calories(user: User) -> Optional[dict]:
    """
    Оценивает калории и макронутриенты для пользователя.
    Использует новый модуль nutrition_calculator.
    """
    if not user.weight_kg or not user.height_cm:
        return None
    
    # Определяем активность на основе модулей
    modules = user.get_modules()
    activity = "moderate"  # По умолчанию
    if "training" in modules:
        activity = "high"
    
    # Определяем цель на основе goals
    goals_text = (user.goals or "").lower()
    goal = "maintain"
    if "похуд" in goals_text or "сниж" in goals_text or "вес" in goals_text:
        goal = "lose"
    elif "мышц" in goals_text or "масс" in goals_text or "набор" in goals_text:
        goal = "gain"
    
    # Создаём профиль для нового модуля
    profile = {
        "sex": user.sex or "m",  # По умолчанию мужчина
        "age": user.age or 30,  # По умолчанию 30 лет
        "weight_kg": user.weight_kg,
        "height_cm": user.height_cm,
        "activity": activity,
        "goal": goal,
    }
    
    # Используем новый модуль
    plan = generate_nutrition_plan(profile)
    
    # Форматируем макронутриенты для обратной совместимости
    macros = plan["numbers"]["macros"]
    macro_str = f"Б/Ж/У {macros['protein_g']}/{macros['fat_g']}/{macros['carb_g']} г"
    
    return {
        "maintenance": plan["numbers"]["tdee"],
        "target": plan["numbers"]["calories"],
        "macro": macro_str,
    }


def calculate_hydration_goal(user: User) -> int:
    """
    Рассчитывает цель по воде на основе нового модуля.
    """
    if not user.weight_kg:
        return 2000  # По умолчанию
    
    # Определяем активность
    modules = user.get_modules()
    activity = "moderate"
    if "training" in modules:
        activity = "high"
    
    # Оцениваем время тренировок (если есть тренировки, предполагаем 60 минут)
    training_minutes = 60 if "training" in modules else 0
    
    # Используем новый модуль
    water_ml = calculate_water_ml(user.weight_kg, activity, training_minutes)
    return water_ml

