from datetime import time

from app.models import User
from app.services import sleep


def make_user() -> User:
    return User(
        telegram_id=1,
        desired_wake_time=time(hour=7),
        sleep_goal_minutes=420,
    )


def test_calculate_bedtime_basic():
    user = make_user()
    bedtime = sleep.calculate_bedtime(user.desired_wake_time, user.sleep_goal_minutes)
    assert bedtime == time(hour=0)


def test_chronotherapy_plan():
    plan = sleep.suggest_chronotherapy(time(3, 0), time(23, 0), step_minutes=30)
    assert plan, "Plan should not be empty"
    assert plan[-1][1] == time(23, 0)

