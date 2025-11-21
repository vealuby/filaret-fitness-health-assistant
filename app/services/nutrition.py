from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional

from app.models import MealType, TrainingSession, User
from app.services.sleep import minutes_to_time

MEAL_LABELS = {
    MealType.BREAKFAST: "Завтрак",
    MealType.SNACK: "Перекус",
    MealType.LUNCH: "Обед",
    MealType.DINNER: "Ужин",
    MealType.POST_WORKOUT: "Приём после тренировки",
}


@dataclass(slots=True)
class MealSlot:
    meal_type: MealType
    target_time: time
    window_start: time
    window_end: time
    recommendation: str


def _add_minutes(base: time, minutes: int) -> time:
    return minutes_to_time(base.hour * 60 + base.minute + minutes)


def generate_daily_plan(
    user: User,
    wake_time: time,
    work_start: Optional[time],
    work_end: Optional[time],
    trainings: Iterable[TrainingSession],
    target_calories: Optional[int] = None,
) -> list[MealSlot]:
    """
    Генерирует план питания на день с распределением калорий.
    Если target_calories указан, калории распределяются пропорционально между приёмами пищи.
    """
    plan: list[MealSlot] = []
    today = date.today()
    training: Optional[TrainingSession] = next(
        (t for t in trainings if t.planned_time.date() == today), None
    )
    
    # Определяем базовые пропорции калорий для разных сценариев
    if training:
        # С тренировкой: завтрак 25%, обед 30%, ужин 20%, перекус 10%, после тренировки 15%
        base_distribution = {
            MealType.BREAKFAST: 0.25,
            MealType.LUNCH: 0.30,
            MealType.DINNER: 0.20,
            MealType.SNACK: 0.10,
            MealType.POST_WORKOUT: 0.15,
        }
    else:
        # Без тренировки: завтрак 30%, обед 35%, ужин 30%, перекус 5%
        base_distribution = {
            MealType.BREAKFAST: 0.30,
            MealType.LUNCH: 0.35,
            MealType.DINNER: 0.30,
            MealType.SNACK: 0.05,
        }
    
    # Если target_calories не указан, используем дефолтные значения
    if target_calories is None:
        target_calories = 2000  # Дефолтное значение
    
    # Рассчитываем калории для каждого приёма пищи
    breakfast_kcal = int(target_calories * base_distribution[MealType.BREAKFAST])
    lunch_kcal = int(target_calories * base_distribution[MealType.LUNCH])
    dinner_kcal = int(target_calories * base_distribution[MealType.DINNER])
    
    # Рассчитываем БЖУ для завтрака (30/25/45%)
    breakfast_protein = int(breakfast_kcal * 0.30 / 4)
    breakfast_fat = int(breakfast_kcal * 0.25 / 9)
    breakfast_carbs = int(breakfast_kcal * 0.45 / 4)
    
    breakfast_time = _add_minutes(wake_time, 45)
    plan.append(
        MealSlot(
            meal_type=MealType.BREAKFAST,
            target_time=breakfast_time,
            window_start=_add_minutes(wake_time, 15),
            window_end=_add_minutes(wake_time, 75),
            recommendation=(
                f"Плотный завтрак в течение часа после пробуждения. Пример: омлет с овощами, "
                f"цельнозерновой тост и ягоды. ~{breakfast_kcal} ккал, Б/Ж/У {breakfast_protein}/{breakfast_fat}/{breakfast_carbs} г."
            ),
        )
    )

    if work_start and work_end:
        midpoint = minutes_to_time(
            (work_start.hour * 60 + work_start.minute + work_end.hour * 60 + work_end.minute) // 2
        )
        lunch_protein = int(lunch_kcal * 0.30 / 4)
        lunch_fat = int(lunch_kcal * 0.25 / 9)
        lunch_carbs = int(lunch_kcal * 0.45 / 4)
        plan.append(
            MealSlot(
                meal_type=MealType.LUNCH,
                target_time=midpoint,
                window_start=_add_minutes(midpoint, -45),
                window_end=_add_minutes(midpoint, 45),
                recommendation=(
                    f"Сбалансированный обед в рабочем окне. Пример: запечённая курица, киноа и салат "
                    f"с оливковым маслом. ~{lunch_kcal} ккал, Б/Ж/У {lunch_protein}/{lunch_fat}/{lunch_carbs} г."
                ),
            )
        )
    else:
        lunch_protein = int(lunch_kcal * 0.30 / 4)
        lunch_fat = int(lunch_kcal * 0.25 / 9)
        lunch_carbs = int(lunch_kcal * 0.45 / 4)
        plan.append(
            MealSlot(
                meal_type=MealType.LUNCH,
                target_time=_add_minutes(wake_time, 300),
                window_start=_add_minutes(wake_time, 240),
                window_end=_add_minutes(wake_time, 360),
                recommendation=(
                    f"Сбалансированный обед. Пример: рыба на пару, бурый рис и тушёные овощи. "
                    f"~{lunch_kcal} ккал, Б/Ж/У {lunch_protein}/{lunch_fat}/{lunch_carbs} г."
                ),
            )
        )

    if training:
        training_time = training.planned_time.time()
        dinner_time = minutes_to_time(training_time.hour * 60 + training_time.minute - 150)
        dinner_protein = int(dinner_kcal * 0.35 / 4)
        dinner_fat = int(dinner_kcal * 0.25 / 9)
        dinner_carbs = int(dinner_kcal * 0.40 / 4)
        plan.append(
            MealSlot(
                meal_type=MealType.DINNER,
                target_time=dinner_time,
                window_start=_add_minutes(dinner_time, -30),
                window_end=_add_minutes(dinner_time, 30),
                recommendation=(
                    f"Ужин за 2–3 часа до тренировки. Пример: гречка с индейкой и овощами. "
                    f"~{dinner_kcal} ккал, Б/Ж/У {dinner_protein}/{dinner_fat}/{dinner_carbs} г."
                ),
            )
        )
        pre_workout = minutes_to_time(training_time.hour * 60 + training_time.minute - 45)
        snack_kcal = int(target_calories * base_distribution[MealType.SNACK])
        snack_protein = int(snack_kcal * 0.20 / 4)
        snack_fat = int(snack_kcal * 0.20 / 9)
        snack_carbs = int(snack_kcal * 0.60 / 4)
        plan.append(
            MealSlot(
                meal_type=MealType.SNACK,
                target_time=pre_workout,
                window_start=_add_minutes(pre_workout, -15),
                window_end=_add_minutes(pre_workout, 15),
                recommendation=(
                    f"Перекус за 30–60 минут до тренировки. Пример: банан + греческий йогурт или смузи. "
                    f"~{snack_kcal} ккал, Б/Ж/У {snack_protein}/{snack_fat}/{snack_carbs} г."
                ),
            )
        )
        post = minutes_to_time(training_time.hour * 60 + training_time.minute + 30)
        post_kcal = int(target_calories * base_distribution[MealType.POST_WORKOUT])
        post_protein = int(post_kcal * 0.40 / 4)
        post_fat = int(post_kcal * 0.20 / 9)
        post_carbs = int(post_kcal * 0.40 / 4)
        plan.append(
            MealSlot(
                meal_type=MealType.POST_WORKOUT,
                target_time=post,
                window_start=post,
                window_end=_add_minutes(post, 60),
                recommendation=(
                    f"Восстановительный приём пищи в течение часа после тренировки. "
                    f"Пример: творог с ягодами и мёдом или протеиновый коктейль + банан. "
                    f"~{post_kcal} ккал, Б/Ж/У {post_protein}/{post_fat}/{post_carbs} г."
                ),
            )
        )
    else:
        dinner = _add_minutes(wake_time, 12 * 60)
        dinner_protein = int(dinner_kcal * 0.30 / 4)
        dinner_fat = int(dinner_kcal * 0.25 / 9)
        dinner_carbs = int(dinner_kcal * 0.45 / 4)
        plan.append(
            MealSlot(
                meal_type=MealType.DINNER,
                target_time=dinner,
                window_start=_add_minutes(dinner, -45),
                window_end=_add_minutes(dinner, 45),
                recommendation=(
                    f"Ужин за 2–3 часа до сна. Пример: запечённый лосось с овощами и стакан кефира. "
                    f"~{dinner_kcal} ккал, Б/Ж/У {dinner_protein}/{dinner_fat}/{dinner_carbs} г."
                ),
            )
        )
        # Добавляем перекус между обедом и ужином, если нет тренировки
        snack_time = _add_minutes(wake_time, 8 * 60)  # Примерно через 8 часов после пробуждения
        snack_kcal = int(target_calories * base_distribution[MealType.SNACK])
        snack_protein = int(snack_kcal * 0.25 / 4)
        snack_fat = int(snack_kcal * 0.30 / 9)
        snack_carbs = int(snack_kcal * 0.45 / 4)
        plan.append(
            MealSlot(
                meal_type=MealType.SNACK,
                target_time=snack_time,
                window_start=_add_minutes(snack_time, -30),
                window_end=_add_minutes(snack_time, 30),
                recommendation=(
                    f"Перекус между обедом и ужином. Пример: орехи, фрукт или йогурт. "
                    f"~{snack_kcal} ккал, Б/Ж/У {snack_protein}/{snack_fat}/{snack_carbs} г."
                ),
            )
        )

    plan.sort(key=lambda slot: slot.target_time)
    return plan


def adapt_plan_after_training_cancel(plan: list[MealSlot]) -> list[MealSlot]:
    filtered = [slot for slot in plan if slot.meal_type not in (MealType.SNACK, MealType.POST_WORKOUT)]
    for slot in filtered:
        if slot.meal_type == MealType.DINNER:
            slot.recommendation = "Сместите ужин ближе к концу рабочего дня, фокус на белок+овощи."
    return filtered


def serialize_plan(plan: list[MealSlot]) -> str:
    return json.dumps(
        [
            {
                "meal_type": slot.meal_type.value,
                "target_time": slot.target_time.strftime("%H:%M"),
                "window_start": slot.window_start.strftime("%H:%M"),
                "window_end": slot.window_end.strftime("%H:%M"),
                "recommendation": slot.recommendation,
            }
            for slot in plan
        ],
        ensure_ascii=False,
    )


def deserialize_plan(payload: str) -> list[MealSlot]:
    data = json.loads(payload)
    plan: list[MealSlot] = []
    for item in data:
        plan.append(
            MealSlot(
                meal_type=MealType(item["meal_type"]),
                target_time=datetime.strptime(item["target_time"], "%H:%M").time(),
                window_start=datetime.strptime(item["window_start"], "%H:%M").time(),
                window_end=datetime.strptime(item["window_end"], "%H:%M").time(),
                recommendation=item["recommendation"],
            )
        )
    return plan

