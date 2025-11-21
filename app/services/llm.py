from __future__ import annotations

import asyncio
import json
from textwrap import dedent
from typing import Optional

from openai import OpenAI

from app.config import settings
from app.models import User


SYSTEM_PROMPT = dedent(
    """
    Ты — дружелюбный бот-коуч по сну, питанию и тренировкам.
    Даёшь образовательные советы на основе научных источников (AASM, chrononutrition).
    Не ставь диагнозы и не назначай лечение. При любых медицинских симптомах советуй обратиться к врачу.
    Отвечай кратко (до 5-6 предложений) и по существу, на русском языке.
    """
).strip()

DISCLAIMER = (
    "Внимание: информация носит образовательный характер и не заменяет консультацию "
    "врача. При ухудшении самочувствия обратитесь к специалисту."
)


PROFILE_SCHEMA = {
    "name": "profile",
    "schema": {
        "type": "object",
        "properties": {
            "desired_wake_time": {"type": "string", "description": "HH:MM or null"},
            "sleep_goal_h": {"type": "number", "description": "Sleep goal in hours (float) or null"},
            "work_start": {"type": "string", "description": "HH:MM or null"},
            "work_end": {"type": "string", "description": "HH:MM or null"},
            "trainings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "day": {"type": "string", "enum": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]},
                        "time": {"type": "string", "description": "HH:MM"},
                    },
                    "required": ["day", "time"],
                },
            },
            "height_cm": {"type": "integer", "description": "Height in cm or null"},
            "weight_kg": {"type": "number", "description": "Weight in kg (float) or null"},
            "age": {"type": "integer", "description": "Age in years or null"},
            "sex": {"type": ["string", "null"], "description": "m for male, f for female, other, or null"},
            "water_goal_ml": {"type": "integer", "description": "Water goal in ml or null"},
            "goals": {
                "type": "array",
                "items": {"type": "string"},
            },
            "allergies": {"type": "string", "description": "Allergies or null"},
            "parse_warnings": {
                "type": "array",
                "items": {"type": "string"},
            },
            "raw_text": {"type": "string"},
        },
        # Не делаем поля обязательными, чтобы можно было вернуть null
    },
}


class LLMClient:
    def __init__(self, api_key: Optional[str]) -> None:
        self.enabled = bool(api_key)
        self._client: Optional[OpenAI] = None
        if api_key:
            self._client = OpenAI(api_key=api_key)

    async def ask(self, user: User, question: str) -> str:
        if not self.enabled or not self._client:
            return "LLM недоступна. Проверьте API-ключ. " + DISCLAIMER

        content = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": dedent(
                    f"""
                    Пользователь: {user.goals or 'без цели'}
                    Сон: пробуждение {user.desired_wake_time.strftime('%H:%M')}, цель сна {user.sleep_goal_minutes // 60} ч.
                    Вопрос: {question}
                    """
                ).strip(),
            },
        ]
        response = await asyncio.to_thread(
            self._client.chat.completions.create,
            model="gpt-4o-mini",
            messages=content,
        )
        answer = response.choices[0].message.content.strip()
        return f"{answer}\n\n{DISCLAIMER}"

    async def parse_profile(self, raw_text: str) -> dict:
        if not self.enabled or not self._client:
            raise RuntimeError("LLM недоступна")
        
        system_prompt = dedent(
            """
            You are a precise JSON-extraction assistant. User will provide one short free-form Russian text 
            describing their daily routine: wake time, desired sleep duration, working hours, training days 
            and times, height, weight, age, sex, allergies, water goal and goals. Your job: extract values 
            and return a single JSON object that EXACTLY matches the schema provided in the User prompt. 
            Do NOT output any explanatory text. If a field cannot be determined, set it to null. 
            If something looks implausible, include an entry in parse_warnings. Use 24-hour HH:MM times. 
            Days must be Mon,Tue,Wed,Thu,Fri,Sat,Sun. Keep numbers as integers (except sleep_goal_h can be float). 
            The JSON must be valid.
            """
        ).strip()
        
        user_prompt = f"""Schema:
{json.dumps(PROFILE_SCHEMA["schema"], indent=2, ensure_ascii=False)}

User message:
"{raw_text}"

Instructions:
- Extract fields from the raw text and output only the JSON object matching the Schema.
- Normalize times to HH:MM.
- Normalize days to Mon..Sun (Russian day names map as: пн->Mon, вт->Tue, ср->Wed, чт->Thu, пт->Fri, сб->Sat, вс->Sun).
- If a single time is present and multiple days are listed without times, apply that time to each listed day.
- If weight looks like it's equal to height or obviously swapped, still output both numbers but add 'possible_height_weight_swap' to parse_warnings.
- If a numeric field is implausible (see validation rules), include 'implausible_<field>' in parse_warnings.
- Put the original raw message into raw_text.
- If user says '8 утра' or '8 утром', this is 08:00, not 20:00.
- If user says '8 вечера' or '20:00', this is 20:00.
- If user says 'с 9 до 18' or 'работаю с 9 до 18', this is work_start: '09:00' and work_end: '18:00'.
- If user says '9-18', this is also work_start: '09:00' and work_end: '18:00'.
- If user says '2 литра' or '2л', this is 2000 ml.
- If user says 'мужчина' or 'м', sex is 'm'.
- If user says 'женщина' or 'ж', sex is 'f'.
- If water goal is not explicitly mentioned, set water_goal_ml to null.
"""
        
        response = await asyncio.to_thread(
            self._client.chat.completions.create,
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "user_profile",
                    **PROFILE_SCHEMA["schema"]
                }
            },
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Пустой ответ от LLM")
        parsed = json.loads(content)
        
        # Проверяем предупреждения о возможной перестановке роста и веса
        warnings = parsed.get("parse_warnings", [])
        if "possible_height_weight_swap" in warnings:
            # Меняем местами рост и вес
            if parsed.get("height_cm") and parsed.get("weight_kg"):
                height = parsed["height_cm"]
                weight = parsed["weight_kg"]
                # Если рост больше веса и это выглядит неправильно, меняем местами
                if height > weight and height > 100:  # Рост не должен быть больше веса в кг
                    parsed["height_cm"], parsed["weight_kg"] = weight, height
        
        # Дополнительная проверка: если вес равен росту или очень близок, это подозрительно
        if parsed.get("height_cm") and parsed.get("weight_kg"):
            height = parsed["height_cm"]
            weight = parsed["weight_kg"]
            # Если вес равен росту (например, оба 172), это явная ошибка
            # Обычно рост 150-220 см, вес 40-150 кг
            if height == weight or abs(height - weight) < 10:
                # Если оба значения в диапазоне роста (150-220), то большее - рост, меньшее - вес
                if 150 <= height <= 220 and 150 <= weight <= 220:
                    # Оба в диапазоне роста - это ошибка, нужно поменять местами
                    if height > weight:
                        # height больше, значит это действительно рост, weight должен быть меньше
                        # Но если weight тоже в диапазоне роста, это ошибка
                        # В этом случае оставляем как есть, но логируем предупреждение
                        pass
                    else:
                        # weight больше height, но оба в диапазоне роста - явная ошибка
                        parsed["height_cm"], parsed["weight_kg"] = weight, height
                # Если height в диапазоне веса (40-150) и weight в диапазоне роста (150-220), перепутаны
                elif 40 <= height <= 150 and 150 <= weight <= 200:
                    parsed["height_cm"], parsed["weight_kg"] = weight, height
                # Если weight в диапазоне роста (150-220) и height тоже, но weight больше - возможно перепутаны
                elif 150 <= weight <= 220 and 150 <= height <= 220 and weight > height:
                    # weight больше height, но оба в диапазоне роста - возможно перепутаны
                    # Но если разница большая, то weight может быть правильным ростом
                    if weight - height > 20:
                        # Большая разница - скорее всего weight это рост
                        parsed["height_cm"], parsed["weight_kg"] = weight, height
        
        return parsed

    async def generate_summary(
        self,
        user: User,
        summary_data: dict,
    ) -> str:
        """
        Генерирует сводку за последние дни с рекомендациями и похвалой.
        
        Args:
            user: Пользователь
            summary_data: Словарь с данными за период (sleep, meals, hydration, training, symptoms)
        """
        if not self.enabled or not self._client:
            return "LLM недоступна. Проверьте API-ключ."

        summary_prompt = dedent(
            f"""
            Проанализируй данные пользователя за последние 3 дня и создай дружелюбную сводку с:
            1. Кратким обзором достижений (похвала за успехи)
            2. Областями для улучшения (конструктивная критика)
            3. Конкретными рекомендациями на основе данных
            
            Профиль пользователя:
            - Цели: {user.goals or 'не указаны'}
            - Рост: {user.height_cm or 'не указан'} см
            - Вес: {user.weight_kg or 'не указан'} кг
            - Цель сна: {user.sleep_goal_minutes // 60} часов
            - Цель воды: {user.hydration_goal_ml} мл
            
            Данные за последние 3 дня:
            {json.dumps(summary_data, ensure_ascii=False, indent=2)}
            
            Будь позитивным, но честным. Используй эмодзи для визуального оформления.
            Ответ должен быть на русском языке, объёмом 10-15 предложений.
            """
        ).strip()

        content = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": summary_prompt},
        ]
        response = await asyncio.to_thread(
            self._client.chat.completions.create,
            model="gpt-4o-mini",
            messages=content,
        )
        answer = response.choices[0].message.content.strip()
        return f"{answer}\n\n{DISCLAIMER}"


llm_client = LLMClient(api_key=settings.openai_api_key.get_secret_value() if settings.openai_api_key else None)

