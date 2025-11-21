from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, List, Optional

from app.models import TrainingSession, TrainingStatus, User


WEEKDAY_INDEX = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


@dataclass(slots=True)
class TrainingNotification:
    session_id: int
    action: str
    message: str


def _parse_time(value: str) -> time:
    hour, minute = map(int, value.split(":"))
    return time(hour=hour, minute=minute)


def plan_week_sessions(user: User, today: date) -> list[datetime]:
    schedule = []
    for day_info in user.workout_days:
        weekday = WEEKDAY_INDEX.get(day_info.get("day", "").lower())
        if weekday is None:
            continue
        occurs_in = (weekday - today.weekday()) % 7
        target_date = today + timedelta(days=occurs_in)
        when = _parse_time(day_info.get("time", "19:00"))
        schedule.append(datetime.combine(target_date, when))
    return sorted(schedule)


def mark_training(session: TrainingSession, status: TrainingStatus) -> TrainingSession:
    session.status = status
    session.updated_at = datetime.utcnow()
    return session


def should_reschedule(session: TrainingSession) -> bool:
    return session.status == TrainingStatus.CANCELLED


def summarize_training_day(sessions: Iterable[TrainingSession]) -> str:
    summary = []
    for session in sessions:
        status = session.status.value
        time_str = session.planned_time.strftime("%H:%M")
        summary.append(f"{time_str} — {status}")
    if not summary:
        return "Сегодня тренировка не запланирована."
    return "\n".join(summary)

