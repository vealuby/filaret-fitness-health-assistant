from __future__ import annotations

import pytest

from app.services.nutrition_calculator import (
    calculate_bmr,
    calculate_bmi,
    calculate_target_calories,
    calculate_tdee,
    calculate_water_ml,
    generate_nutrition_plan,
    get_activity_factor,
)


def test_calculate_bmi():
    """Тест расчета BMI"""
    bmi = calculate_bmi(80, 180)
    assert 24.0 < bmi < 25.0  # Примерно 24.7


def test_calculate_bmr_male():
    """Тест расчета BMR для мужчины"""
    bmr = calculate_bmr(80, 180, 28, 'm')
    # Ожидаемое значение: 10*80 + 6.25*180 - 5*28 + 5 = 800 + 1125 - 140 + 5 = 1790
    assert 1785 < bmr < 1795


def test_calculate_bmr_female():
    """Тест расчета BMR для женщины"""
    bmr = calculate_bmr(65, 165, 35, 'f')
    # Ожидаемое значение: 10*65 + 6.25*165 - 5*35 - 161 = 650 + 1031.25 - 175 - 161 = 1345.25
    assert 1340 < bmr < 1350


def test_get_activity_factor():
    """Тест коэффициентов активности"""
    assert get_activity_factor('sedentary') == 1.2
    assert get_activity_factor('light') == 1.375
    assert get_activity_factor('moderate') == 1.55
    assert get_activity_factor('high') == 1.725
    assert get_activity_factor('very_high') == 1.9


def test_calculate_tdee():
    """Тест расчета TDEE"""
    bmr = 1790
    tdee = calculate_tdee(bmr, 'moderate')
    # 1790 * 1.55 = 2774.5
    assert 2770 < tdee < 2780


def test_calculate_target_calories_maintain():
    """Тест целевых калорий для поддержания"""
    tdee = 2775
    calories = calculate_target_calories(tdee, 'maintain', 28)
    assert calories == tdee


def test_calculate_target_calories_lose():
    """Тест целевых калорий для похудения"""
    tdee = 2775
    calories = calculate_target_calories(tdee, 'lose', 28)
    # Должно быть tdee - 400 = 2375, но минимум 1200
    assert 2370 < calories < 2380
    assert calories >= 1200


def test_calculate_target_calories_gain():
    """Тест целевых калорий для набора массы"""
    tdee = 2775
    calories = calculate_target_calories(tdee, 'gain', 28)
    # Должно быть tdee + 300 = 3075
    assert 3070 < calories < 3080


def test_calculate_water_ml():
    """Тест расчета воды"""
    # Базовый расчет: 80 кг * 35 мл = 2800 мл
    water = calculate_water_ml(80, 'moderate', 0)
    assert 2750 < water < 2850
    
    # С тренировками: 60 минут = +400 мл
    water_with_training = calculate_water_ml(80, 'moderate', 60)
    assert 3150 < water_with_training < 3250


def test_generate_nutrition_plan_male_maintain():
    """Тест 1: Мужчина 28 лет, 80 кг, 180 см, moderate, maintain"""
    profile = {
        "sex": "m",
        "age": 28,
        "weight_kg": 80,
        "height_cm": 180,
        "activity": "moderate",
        "goal": "maintain",
    }
    
    plan = generate_nutrition_plan(profile)
    
    # Проверяем структуру
    assert "meta" in plan
    assert "numbers" in plan
    assert "schedule" in plan
    
    # Проверяем BMR (должно быть ~1790)
    assert 1785 < plan["numbers"]["bmr"] < 1795
    
    # Проверяем TDEE (должно быть ~2775)
    assert 2770 < plan["numbers"]["tdee"] < 2780
    
    # Проверяем калории (для maintain = TDEE)
    assert plan["numbers"]["calories"] == plan["numbers"]["tdee"]
    
    # Проверяем воду (должно быть ~2800 мл)
    assert 2750 < plan["numbers"]["water_ml"] < 2850
    
    # Проверяем макронутриенты
    assert "protein_g" in plan["numbers"]["macros"]
    assert "fat_g" in plan["numbers"]["macros"]
    assert "carb_g" in plan["numbers"]["macros"]
    
    # Проверяем расписание
    assert "meals" in plan["schedule"]
    assert len(plan["schedule"]["meals"]) > 0


def test_generate_nutrition_plan_female_lose():
    """Тест 2: Женщина 35 лет, 65 кг, 165 см, light, lose"""
    profile = {
        "sex": "f",
        "age": 35,
        "weight_kg": 65,
        "height_cm": 165,
        "activity": "light",
        "goal": "lose",
    }
    
    plan = generate_nutrition_plan(profile)
    
    # Проверяем, что калории меньше TDEE
    assert plan["numbers"]["calories"] < plan["numbers"]["tdee"]
    
    # Проверяем, что калории >= 1200
    assert plan["numbers"]["calories"] >= 1200
    
    # Проверяем макронутриенты
    macros = plan["numbers"]["macros"]
    assert macros["protein_g"] > 0
    assert macros["fat_g"] > 0
    assert macros["carb_g"] > 0


def test_generate_nutrition_plan_under_18():
    """Тест 3: Возраст 16 лет -> warning under_18 и consult_clinician true"""
    profile = {
        "sex": "m",
        "age": 16,
        "weight_kg": 70,
        "height_cm": 175,
        "activity": "moderate",
        "goal": "lose",
    }
    
    plan = generate_nutrition_plan(profile)
    
    # Проверяем предупреждения
    assert "under_18" in plan["meta"]["warnings"]
    assert plan["meta"]["consult_clinician"] is True
    
    # Проверяем, что дефицит ограничен (для несовершеннолетних)
    tdee = plan["numbers"]["tdee"]
    calories = plan["numbers"]["calories"]
    # Дефицит должен быть не более 300 ккал для несовершеннолетних
    assert tdee - calories <= 300


def test_generate_nutrition_plan_extreme_bmi():
    """Тест экстремального BMI"""
    # Низкий BMI
    profile_low = {
        "sex": "f",
        "age": 25,
        "weight_kg": 40,
        "height_cm": 170,
        "activity": "moderate",
        "goal": "maintain",
    }
    plan_low = generate_nutrition_plan(profile_low)
    bmi_low = calculate_bmi(40, 170)
    if bmi_low < 16:
        assert "extreme_bmi_low" in plan_low["meta"]["warnings"]
        assert plan_low["meta"]["consult_clinician"] is True
    
    # Высокий BMI
    profile_high = {
        "sex": "m",
        "age": 30,
        "weight_kg": 150,
        "height_cm": 170,
        "activity": "moderate",
        "goal": "maintain",
    }
    plan_high = generate_nutrition_plan(profile_high)
    bmi_high = calculate_bmi(150, 170)
    if bmi_high > 40:
        assert "extreme_bmi_high" in plan_high["meta"]["warnings"]
        assert plan_high["meta"]["consult_clinician"] is True


def test_generate_nutrition_plan_with_schedule():
    """Тест с расписанием (wake_time, work_start, work_end)"""
    profile = {
        "sex": "m",
        "age": 28,
        "weight_kg": 80,
        "height_cm": 180,
        "activity": "moderate",
        "goal": "maintain",
        "desired_wake_time": "08:00",
        "work_start": "09:00",
        "work_end": "18:00",
        "training_time": "20:00",
        "training_minutes": 60,
    }
    
    plan = generate_nutrition_plan(profile)
    
    # Проверяем расписание
    assert plan["schedule"]["wake_time"] == "08:00"
    assert len(plan["schedule"]["meals"]) > 0
    assert len(plan["schedule"]["water_reminders"]) > 0
    
    # Проверяем pre/post workout
    pre_post = plan["schedule"]["pre_post_workout"]
    assert pre_post["pre_workout"] is not None
    assert pre_post["post_workout"] is not None

