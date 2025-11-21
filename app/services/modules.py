from __future__ import annotations

import json
import json
from typing import Iterable, List


AVAILABLE_MODULES = [
    {"id": "sleep", "label": "🛌 Сон", "description": "Поддержание режима и расчёт bedtime"},
    {"id": "hydration", "label": "💧 Вода", "description": "Напоминания о воде и цели"},
    {"id": "training", "label": "🏃‍♂️ Тренировки", "description": "Учёт тренировок и питательных окон"},
    {"id": "meds", "label": "💊 Лекарства", "description": "Напоминания о приёме лекарств"},
    {"id": "symptoms", "label": "🩺 Симптомы", "description": "Самооценка симптомов и дискламеры"},
]

DEFAULT_MODULES = ["sleep", "hydration", "training"]

MODULE_KEYWORDS = {
    "сон": "sleep",
    "энерг": "energy",
    "вес": "weight_loss",
    "похуд": "weight_loss",
    "мышц": "muscle_gain",
    "масса": "muscle_gain",
    "вода": "hydration",
    "трен": "training",
    "спорт": "training",
    "лекар": "meds",
    "таблет": "meds",
    "симп": "symptoms",
}


def normalize_modules(modules: Iterable[str]) -> list[str]:
    allowed = {item["id"] for item in AVAILABLE_MODULES}
    normal = [module for module in modules if module in allowed]
    if not normal:
        return DEFAULT_MODULES.copy()
    return sorted(set(normal))


def modules_from_text(text: str) -> list[str]:
    lowered = text.lower()
    detected = {module for key, module in MODULE_KEYWORDS.items() if key in lowered}
    return normalize_modules(detected)


def dumps_modules(modules: Iterable[str]) -> str:
    return json.dumps(normalize_modules(modules), ensure_ascii=False)


def loads_modules(payload: str | None) -> List[str]:
    if not payload:
        return DEFAULT_MODULES.copy()
    try:
        parsed = json.loads(payload)
        if isinstance(parsed, list):
            return normalize_modules(parsed)
    except json.JSONDecodeError:
        pass
    return DEFAULT_MODULES.copy()

