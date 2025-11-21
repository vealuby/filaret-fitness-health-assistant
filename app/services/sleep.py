from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Sequence

from app.models import SleepLog, User


@dataclass(slots=True)
class BedtimePlan:
    target_bedtime: time
    wake_time: time
    sleep_duration: timedelta
    notes: str


def minutes_to_time(total_minutes: int) -> time:
    total_minutes %= 24 * 60
    hours, minutes = divmod(total_minutes, 60)
    return time(hour=hours, minute=minutes)


def calculate_sleep_goal_minutes(user: User) -> int:
    if user.sleep_goal_minutes:
        return user.sleep_goal_minutes
    if user.sleep_goal_cycles:
        return max(1, user.sleep_goal_cycles) * 90
    return 450


def calculate_bedtime(desired_wake: time, goal_minutes: int) -> time:
    total_wake_minutes = desired_wake.hour * 60 + desired_wake.minute
    bedtime_minutes = (total_wake_minutes - goal_minutes) % (24 * 60)
    return minutes_to_time(bedtime_minutes)


def suggest_chronotherapy(
    current_bedtime: time,
    target_bedtime: time,
    step_minutes: int = 30,
) -> list[tuple[int, time]]:
    current = current_bedtime.hour * 60 + current_bedtime.minute
    target = target_bedtime.hour * 60 + target_bedtime.minute
    plan: list[tuple[int, time]] = []
    day_offset = 0

    while current != target:
        if (target - current) % (24 * 60) > (12 * 60):
            # move backwards across midnight
            current = (current - step_minutes) % (24 * 60)
        else:
            current = (current + step_minutes) % (24 * 60)
        day_offset += 1
        plan.append((day_offset, minutes_to_time(current)))
        if day_offset > 14:  # safety guard
            break
    return plan


def build_bedtime_plan(user: User) -> BedtimePlan:
    goal_minutes = calculate_sleep_goal_minutes(user)
    wake = user.desired_wake_time
    bedtime = calculate_bedtime(wake, goal_minutes)
    duration = timedelta(minutes=goal_minutes)
    notes = "Рекомендуется поддерживать одинаковое время отхода ко сну и подъёма ежедневно."
    if user.sleep_debt_minutes > 60:
        extra = min(120, ((user.sleep_debt_minutes + 29) // 30) * 30)
        duration += timedelta(minutes=extra)
        bedtime = calculate_bedtime(wake, int(duration.total_seconds() // 60))
        notes = (
            "Обнаружен накопленный sleep debt. Временно увеличьте продолжительность сна "
            f"на {extra // 60} ч {extra % 60} мин и поддерживайте режим как минимум 3 дня."
        )
    elif user.average_bedtime and abs(_diff_minutes(user.average_bedtime, bedtime)) > 90:
        plan = suggest_chronotherapy(user.average_bedtime, bedtime)
        notes = (
            "Текущий режим сна сильно отличается от цели. Следуйте постепенному сдвигу:\n"
            + ", ".join(f"+{day} дн → {bt.strftime('%H:%M')}" for day, bt in plan)
        )
    return BedtimePlan(target_bedtime=bedtime, wake_time=wake, sleep_duration=duration, notes=notes)


def _diff_minutes(a: time, b: time) -> int:
    total_a = a.hour * 60 + a.minute
    total_b = b.hour * 60 + b.minute
    diff = total_b - total_a
    if diff > 720:
        diff -= 1440
    elif diff < -720:
        diff += 1440
    return diff


def compute_sleep_debt(logs: Sequence[SleepLog], goal_minutes: int) -> int:
    debt = 0
    for log in logs:
        if log.duration_minutes is None:
            continue
        delta = goal_minutes - log.duration_minutes
        debt += max(0, delta)
    return debt


def record_sleep_log(
    user: User,
    bedtime: time,
    wake_time: time,
    log_repo,
) -> SleepLog:
    duration = (
        (datetime.combine(date.today(), wake_time) - datetime.combine(date.today(), bedtime))
        .total_seconds()
        / 60
    )
    if duration < 0:
        duration += 24 * 60
    log = SleepLog(
        user_id=user.telegram_id,
        bedtime=bedtime,
        wake_time=wake_time,
        duration_minutes=int(duration),
    )
    log_repo.append(log)
    return log


def split_sleep_goal(goal_minutes: int, segments: int) -> list[int]:
    base = goal_minutes // segments
    remainder = goal_minutes % segments
    return [base + (1 if i < remainder else 0) for i in range(segments)]


def average_bedtime(logs: Iterable[SleepLog]) -> Optional[time]:
    minutes: list[int] = []
    for log in logs:
        if log.bedtime:
            minutes.append(log.bedtime.hour * 60 + log.bedtime.minute)
    if not minutes:
        return None
    avg = sum(minutes) // len(minutes)
    return minutes_to_time(avg)

