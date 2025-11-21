from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Optional

from dateutil import parser as date_parser

from app.services.llm import llm_client

TIME_REGEX = re.compile(r"(?P<hour>\d{1,2}):(?P<minute>\d{2})")
NUMBER_REGEX = re.compile(r"\d+(?:[.,]\d+)?")

WEEKDAY_ALIASES = {
    "пн": "mon",
    "вт": "tue",
    "ср": "wed",
    "чт": "thu",
    "пт": "fri",
    "сб": "sat",
    "вс": "sun",
}


@dataclass(slots=True)
class ParsedProfile:
    desired_wake_time: Optional[time] = None
    sleep_goal_minutes: Optional[int] = None
    height_cm: Optional[int] = None
    weight_kg: Optional[float] = None
    age: Optional[int] = None
    sex: Optional[str] = None
    allergies: Optional[str] = None
    timezone: Optional[str] = None
    work_start: Optional[time] = None
    work_end: Optional[time] = None
    hydration_goal_ml: Optional[int] = None
    workouts: list[dict[str, Any]] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)


def _to_time(value: str) -> Optional[time]:
    if not value:
        return None
    try:
        # Пытаемся распарсить через dateutil
        parsed = date_parser.parse(value, default=datetime(2000, 1, 1))
        result = parsed.time().replace(second=0, microsecond=0)
        # Если час >= 20 и нет явного указания "вечера", но есть "утра" в исходном тексте,
        # это может быть ошибка парсера - проверяем контекст
        if result.hour >= 20 and isinstance(value, str) and "утра" in value.lower():
            # Скорее всего это утро, а не вечер
            result = time(hour=result.hour - 12 if result.hour >= 12 else result.hour, minute=result.minute)
        return result
    except (ValueError, TypeError, OverflowError):
        # Fallback: пытаемся распарсить вручную формат HH:MM
        match = TIME_REGEX.search(value)
        if match:
            hour = int(match.group("hour"))
            minute = int(match.group("minute"))
            # Если час >= 20 и в тексте есть "утра", это ошибка - должно быть утро
            if hour >= 20 and "утра" in value.lower():
                hour = hour - 12
            return time(hour=hour % 24, minute=minute % 60)
        return None


def heuristic_parse(text: str) -> ParsedProfile:
    data = ParsedProfile()
    lowered = text.lower()

    # Парсим время подъёма с учётом контекста "утра" / "вечера"
    wake_patterns = [
        re.compile(r"встаю?\s+в\s+(\d{1,2}):?(\d{2})?"),
        re.compile(r"подъ[её]м\s+в\s+(\d{1,2}):?(\d{2})?"),
        re.compile(r"(\d{1,2}):?(\d{2})?\s+утра"),
        re.compile(r"(\d{1,2}):?(\d{2})?\s+утром"),
    ]
    is_morning_context = "утра" in lowered or "утром" in lowered
    is_evening_context = "вечера" in lowered or "вечером" in lowered
    
    for pattern in wake_patterns:
        match = pattern.search(lowered)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            # Если указано "утра" или "утром", час остаётся как есть (0-11)
            # Если указано "вечера" или "вечером", добавляем 12 к часам (если < 12)
            if is_morning_context:
                # "8 утра" = 08:00
                data.desired_wake_time = time(hour=hour % 12 if hour >= 12 else hour, minute=minute % 60)
            elif is_evening_context:
                # "8 вечера" = 20:00
                data.desired_wake_time = time(hour=(hour % 12) + 12 if hour < 12 else hour, minute=minute % 60)
            else:
                # По умолчанию: если час 1-11, считаем утро; если 12+, считаем как есть
                if 1 <= hour <= 11:
                    data.desired_wake_time = time(hour=hour, minute=minute % 60)
                else:
                    data.desired_wake_time = time(hour=hour % 24, minute=minute % 60)
            break
    
    # Если не нашли через паттерны, пробуем просто первое время
    if not data.desired_wake_time:
        times = TIME_REGEX.findall(text)
        if times:
            first = times[0]
            hour = int(first[0])
            minute = int(first[1])
            # По умолчанию для часов 1-11 считаем утро, для 12+ - как есть (может быть вечер)
            if 1 <= hour <= 11:
                data.desired_wake_time = time(hour=hour, minute=minute)
            else:
                data.desired_wake_time = time(hour=hour % 24, minute=minute)
    # Парсим цель сна: "сплю 8 часов" или "8 ч" или "8 часов"
    sleep_patterns = [
        re.compile(r"сплю\s+(\d+(?:[.,]\d+)?)\s*ч"),
        re.compile(r"(\d+(?:[.,]\d+)?)\s*ч(?:ас(?:ов|а)?)?\s+сна"),
    ]
    for pattern in sleep_patterns:
        sleep_match = pattern.search(lowered)
        if sleep_match:
            hours = float(sleep_match.group(1).replace(",", "."))
            if 4 <= hours <= 12:
                data.sleep_goal_minutes = int(hours * 60)
                break
    # Fallback: ищем числа в диапазоне 4-10
    if not data.sleep_goal_minutes:
        matches = NUMBER_REGEX.findall(text)
        numbers = [float(num.replace(",", ".")) for num in matches]
        if numbers:
            hours = next((num for num in numbers if 4 <= num <= 10), None)
            if hours:
                data.sleep_goal_minutes = int(hours * 60)
    # Парсим рост и вес с учетом контекста
    if "рост" in lowered or "вес" in lowered:
        # Ищем паттерны "рост X" и "вес Y"
        height_patterns = [
            re.compile(r"рост\s*(\d+(?:[.,]\d+)?)"),
            re.compile(r"(\d+(?:[.,]\d+)?)\s*см"),
        ]
        weight_patterns = [
            re.compile(r"вес\s*(\d+(?:[.,]\d+)?)"),
            re.compile(r"(\d+(?:[.,]\d+)?)\s*кг"),
        ]
        
        # Сначала ищем по паттернам с контекстом
        for pattern in height_patterns:
            match = pattern.search(lowered)
            if match:
                height_val = float(match.group(1).replace(",", "."))
                if 130 <= height_val <= 220:
                    data.height_cm = int(height_val)
                    break
        
        for pattern in weight_patterns:
            match = pattern.search(lowered)
            if match:
                weight_val = float(match.group(1).replace(",", "."))
                if 40 <= weight_val <= 200:
                    data.weight_kg = weight_val
                    break
        
        # Если не нашли по паттернам, используем эвристику: ищем числа в правильных диапазонах
        # Но исключаем уже найденные значения
        if not data.height_cm and not data.weight_kg:
            maybe_height = next((num for num in numbers if 130 <= num <= 220), None)
            maybe_weight = next((num for num in numbers if 40 <= num <= 200 and num != maybe_height), None)
            if maybe_height:
                data.height_cm = int(maybe_height)
            if maybe_weight:
                data.weight_kg = maybe_weight
        elif not data.height_cm:
            # Если вес найден, ищем рост (исключая вес)
            maybe_height = next((num for num in numbers if 130 <= num <= 220 and num != data.weight_kg), None)
            if maybe_height:
                data.height_cm = int(maybe_height)
        elif not data.weight_kg:
            # Если рост найден, ищем вес (исключая рост)
            maybe_weight = next((num for num in numbers if 40 <= num <= 200 and num != data.height_cm), None)
            if maybe_weight:
                data.weight_kg = maybe_weight
    
    # Парсим возраст
    age_patterns = [
        re.compile(r"(\d{1,2})\s*лет"),
        re.compile(r"возраст\s*(\d{1,2})"),
        re.compile(r"мне\s*(\d{1,2})"),
    ]
    for pattern in age_patterns:
        age_match = pattern.search(lowered)
        if age_match:
            age = int(age_match.group(1))
            if 10 <= age <= 100:
                data.age = age
                break
    
    # Парсим пол
    if "муж" in lowered or "парень" in lowered or "m" in lowered.lower():
        data.sex = "m"
    elif "жен" in lowered or "девушка" in lowered or "f" in lowered.lower():
        data.sex = "f"
    if "аллер" in lowered:
        start = lowered.find("аллер")
        data.allergies = text[start:].split(".")[0].strip()
    # Парсим тренировки: "пн/ср/пт в 20:00" или "пн 20:00, ср 20:00"
    # Сначала ищем паттерн "пн/ср/пт в 20:00"
    multi_day_match = re.search(r"([пвс][нт])(?:/([пвс][нт]))+(?:\s+в\s+)?(\d{1,2}:\d{2})", lowered)
    if multi_day_match:
        base_day = multi_day_match.group(1)
        time_str = multi_day_match.group(3)
        # Находим все дни в паттерне
        days_str = multi_day_match.group(0).split()[0]  # "пн/ср/пт"
        for day_abbr in days_str.split("/"):
            if day_abbr in WEEKDAY_ALIASES:
                data.workouts.append({"day": WEEKDAY_ALIASES[day_abbr], "time": time_str})
    else:
        # Обычный паттерн: "пн 20:00, ср 20:00"
        for alias, eng in WEEKDAY_ALIASES.items():
            pattern = re.compile(rf"{alias}\s*(\d{{1,2}}:\d{{2}})")
            for match in pattern.findall(lowered):
                data.workouts.append({"day": eng, "time": match})
    if "вода" in lowered:
        # Парсим "2 литра" или "2000 мл" или "2л"
        water_patterns = [
            re.compile(r"(\d+(?:[.,]\d+)?)\s*л(?:итров?|итра)?"),
            re.compile(r"(\d{3,4})\s*мл"),
        ]
        for pattern in water_patterns:
            water_match = pattern.search(lowered)
            if water_match:
                value = float(water_match.group(1).replace(",", "."))
                if "л" in water_match.group(0).lower():
                    data.hydration_goal_ml = int(value * 1000)
                else:
                    data.hydration_goal_ml = int(value)
                break
    # Парсим рабочие часы: "работаю с 9 до 18" или "9-18" или "09:00-18:00" или "с 9 до 18"
    work_patterns = [
        re.compile(r"(?:работаю\s+)?с\s+(\d{1,2}):?(\d{2})?\s+до\s+(\d{1,2}):?(\d{2})?"),
        re.compile(r"(\d{1,2}):?(\d{2})?\s*[-–]\s*(\d{1,2}):?(\d{2})?"),
        re.compile(r"работаю\s+(\d{1,2}):?(\d{2})?\s+(\d{1,2}):?(\d{2})?"),
    ]
    for pattern in work_patterns:
        work_match = pattern.search(lowered)
        if work_match:
            start_hour = int(work_match.group(1))
            start_min = int(work_match.group(2)) if work_match.group(2) else 0
            end_hour = int(work_match.group(3))
            end_min = int(work_match.group(4)) if len(work_match.groups()) >= 4 and work_match.group(4) else 0
            data.work_start = time(hour=start_hour % 24, minute=start_min % 60)
            data.work_end = time(hour=end_hour % 24, minute=end_min % 60)
            break
    # Парсим цели: "хочу похудеть", "снижение веса", "набор мышц", "энергия"
    goal_keywords = {
        "похуд": "weight_loss",
        "сниж": "weight_loss",
        "вес": "weight_loss",
        "мышц": "muscle_gain",
        "масс": "muscle_gain",
        "энерг": "energy",
        "бодр": "energy",
        "сон": "sleep",
        "питани": "nutrition",
        "тренировк": "training",
    }
    detected_goals = []
    for keyword, goal_id in goal_keywords.items():
        if keyword in lowered:
            detected_goals.append(goal_id)
    if detected_goals:
        data.goals = list(set(detected_goals))
    elif "goal" in lowered or "цель" in lowered:
        sentences = [s.strip() for s in re.split(r"[.!]", text) if "цель" in s.lower()]
        if sentences:
            data.goals = [sentences[0]]
    return data


async def parse_freeform_profile(text: str) -> ParsedProfile:
    parsed = heuristic_parse(text)
    if llm_client.enabled:
        try:
            llm_data = await llm_client.parse_profile(text)
            
            # Преобразуем новую схему в старую структуру
            if llm_data.get("desired_wake_time"):
                parsed.desired_wake_time = parsed.desired_wake_time or _to_time(llm_data["desired_wake_time"])
            
            # sleep_goal_h -> sleep_goal_minutes
            if llm_data.get("sleep_goal_h"):
                parsed.sleep_goal_minutes = int(llm_data["sleep_goal_h"] * 60)
            
            # Используем данные из LLM, если они есть (они более точные)
            if llm_data.get("height_cm") is not None:
                parsed.height_cm = llm_data["height_cm"]
            if llm_data.get("weight_kg") is not None:
                parsed.weight_kg = llm_data["weight_kg"]
            if llm_data.get("age") is not None:
                parsed.age = llm_data["age"]
            if llm_data.get("sex"):
                parsed.sex = llm_data["sex"]
            
            # water_goal_ml -> hydration_goal_ml
            if llm_data.get("water_goal_ml") is not None:
                parsed.hydration_goal_ml = llm_data["water_goal_ml"]
            
            if llm_data.get("allergies"):
                parsed.allergies = llm_data["allergies"]
            
            # Преобразуем trainings в workouts
            if llm_data.get("trainings"):
                workouts = []
                for training in llm_data["trainings"]:
                    # Преобразуем день из Mon/Tue/etc в формат для workouts
                    day_map = {
                        "Mon": "mon", "Tue": "tue", "Wed": "wed", "Thu": "thu",
                        "Fri": "fri", "Sat": "sat", "Sun": "sun"
                    }
                    day = day_map.get(training.get("day", "").capitalize())
                    if day and training.get("time"):
                        workouts.append({"day": day, "time": training["time"]})
                if workouts:
                    parsed.workouts = workouts
            
            if llm_data.get("work_start"):
                parsed.work_start = parsed.work_start or _to_time(llm_data["work_start"])
            if llm_data.get("work_end"):
                parsed.work_end = parsed.work_end or _to_time(llm_data["work_end"])
            
            if llm_data.get("goals"):
                parsed.goals = llm_data["goals"]
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"LLM parsing failed: {e}, using heuristic result")
            # Fallback to heuristic result silently
            pass
    return parsed

