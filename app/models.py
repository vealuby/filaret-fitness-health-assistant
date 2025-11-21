from __future__ import annotations

import json
from datetime import date, datetime, time
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class TrainingStatus(str, Enum):
    SCHEDULED = "scheduled"
    STARTED = "started"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MealType(str, Enum):
    BREAKFAST = "breakfast"
    SNACK = "snack"
    LUNCH = "lunch"
    DINNER = "dinner"
    POST_WORKOUT = "post_workout"


class ReminderType(str, Enum):
    MORNING_WAKE = "morning_wake"
    HYDRATION = "hydration"
    MEAL = "meal"
    TRAINING = "training"
    POST_WORKOUT = "post_workout"
    MEDICATION = "medication"
    WELLNESS_CHECK = "wellness_check"


class User(SQLModel, table=True):
    telegram_id: int = Field(primary_key=True, description="Telegram chat id")
    timezone: str = "Europe/Moscow"
    desired_wake_time: time = Field(default_factory=lambda: time(hour=8))
    sleep_goal_minutes: int = Field(default=450, description="Желаемая длительность сна в минутах")
    sleep_goal_cycles: Optional[int] = Field(default=None, description="Количество циклов по 90 минут")
    current_bedtime: Optional[time] = None
    average_bedtime: Optional[time] = None
    height_cm: Optional[int] = None
    weight_kg: Optional[float] = None
    age: Optional[int] = None
    sex: Optional[str] = Field(default=None, description="'m' для мужчин, 'f' для женщин")
    allergies: Optional[str] = None
    timezone_offset_minutes: int = 0
    work_start: Optional[time] = None
    work_end: Optional[time] = None
    workout_days_json: Optional[str] = Field(default=None, description="JSON с днями и временем тренировок")
    hydration_goal_ml: int = 2000
    hydration_start: Optional[time] = None
    hydration_end: Optional[time] = None
    goals: Optional[str] = None
    water_snooze_count: int = 0
    sleep_debt_minutes: int = 0
    modules_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)

    @property
    def workout_days(self) -> list[dict]:
        if not self.workout_days_json:
            return []
        return json.loads(self.workout_days_json)

    def set_workout_days(self, schedule: list[dict]) -> None:
        self.workout_days_json = json.dumps(schedule, ensure_ascii=False)

    def get_modules(self) -> list[str]:
        try:
            if not self.modules_json:
                return []
            return json.loads(self.modules_json)
        except json.JSONDecodeError:
            return []

    def set_modules(self, modules: list[str]) -> None:
        self.modules_json = json.dumps(sorted(set(modules)), ensure_ascii=False)


class SleepLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.telegram_id", index=True)
    log_date: date = Field(default_factory=date.today, index=True)
    bedtime: Optional[time] = None
    wake_time: Optional[time] = None
    duration_minutes: Optional[int] = None
    rating: Optional[int] = Field(default=None, description="Самочувствие после сна, 0-4")
    sleep_debt_delta: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TrainingSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.telegram_id", index=True)
    planned_time: datetime = Field(index=True)
    status: TrainingStatus = Field(default=TrainingStatus.SCHEDULED)
    reminder_sent: bool = False
    perceived_effort: Optional[int] = Field(default=None, description="Самооценка нагрузки 0-10")
    wellness_score: Optional[int] = Field(default=None, description="Post-workout 0-4")
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MealPlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.telegram_id", index=True)
    plan_date: date = Field(default_factory=date.today, index=True)
    payload: str = Field(description="JSON с временными окнами и советами")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def as_dict(self) -> list[dict]:
        return json.loads(self.payload)


class HydrationEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.telegram_id", index=True)
    plan_date: date = Field(default_factory=date.today, index=True)
    target_time: time
    completed: bool = False
    retries: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Reminder(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.telegram_id", index=True)
    reminder_type: ReminderType = Field(index=True)
    payload: Optional[str] = None
    scheduled_for: datetime = Field(index=True)
    completed: bool = False
    attempt: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MedicationSchedule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.telegram_id", index=True)
    name: str
    dosage: Optional[str] = None
    intake_time: time = Field(description="Время приёма")
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SymptomLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.telegram_id", index=True)
    description: str
    severity: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MealLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.telegram_id", index=True)
    log_date: date = Field(default_factory=date.today, index=True)
    meal_time: time
    description: str = Field(description="Описание того, что пользователь съел")
    created_at: datetime = Field(default_factory=datetime.utcnow)

