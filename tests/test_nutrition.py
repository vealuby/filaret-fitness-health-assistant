from datetime import datetime, time

from app.models import MealType, TrainingSession, TrainingStatus, User
from app.services import nutrition


def test_generate_daily_plan_without_training():
    user = User(
        telegram_id=1,
        desired_wake_time=time(7, 0),
        sleep_goal_minutes=420,
        work_start=time(9, 0),
        work_end=time(18, 0),
    )
    plan = nutrition.generate_daily_plan(user, user.desired_wake_time, user.work_start, user.work_end, [])
    types = [slot.meal_type for slot in plan]
    assert MealType.BREAKFAST in types
    assert MealType.LUNCH in types
    assert MealType.DINNER in types


def test_adapt_plan_after_training_cancel():
    user = User(
        telegram_id=1,
        desired_wake_time=time(7, 0),
        sleep_goal_minutes=420,
    )
    training = TrainingSession(
        id=1,
        user_id=1,
        planned_time=datetime.utcnow(),
        status=TrainingStatus.SCHEDULED,
    )
    plan = nutrition.generate_daily_plan(user, user.desired_wake_time, None, None, [training])
    adapted = nutrition.adapt_plan_after_training_cancel(plan)
    types = [slot.meal_type for slot in adapted]
    assert MealType.SNACK not in types
    assert MealType.POST_WORKOUT not in types

