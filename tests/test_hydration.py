from datetime import time

from app.models import User
from app.services import hydration


def test_build_hydration_schedule():
    user = User(
        telegram_id=1,
        desired_wake_time=time(7, 0),
        sleep_goal_minutes=420,
        hydration_goal_ml=2000,
    )
    schedule = hydration.build_hydration_schedule(user, time(7, 0))
    assert len(schedule) >= 4
    total = sum(dose.volume_ml for dose in schedule)
    assert total >= 150 * 4

