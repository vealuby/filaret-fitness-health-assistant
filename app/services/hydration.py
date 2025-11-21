from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import List

from app.models import User
from app.services.sleep import minutes_to_time


@dataclass(slots=True)
class HydrationDose:
    target_time: time
    volume_ml: int
    message: str


def _time_to_minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def build_hydration_schedule(user: User, wake_time: time) -> List[HydrationDose]:
    start = user.hydration_start or wake_time
    end_default = minutes_to_time(_time_to_minutes(wake_time) + 14 * 60)
    end = user.hydration_end or end_default
    total_minutes = (_time_to_minutes(end) - _time_to_minutes(start)) % (24 * 60)
    if total_minutes <= 0:
        total_minutes = 12 * 60
    portions = max(4, total_minutes // 120)
    volume = max(150, user.hydration_goal_ml // portions)
    doses: list[HydrationDose] = []
    for idx in range(portions):
        minutes = _time_to_minutes(start) + idx * (total_minutes // portions)
        t = minutes_to_time(minutes)
        doses.append(
            HydrationDose(
                target_time=t,
                volume_ml=volume,
                message=f"Порция воды ~{volume} мл. Нажмите «Я попил».",
            )
        )
    return doses


def next_retry_allowed(retries: int) -> bool:
    return retries < 2

