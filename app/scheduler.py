from __future__ import annotations

import json
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import select

from app.config import settings
from app.database import get_session
from app.models import MedicationSchedule, Reminder, ReminderType, User
from app.services.hydration import build_hydration_schedule, next_retry_allowed


class ReminderScheduler:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        # Используем zoneinfo вместо pytz (стандартная библиотека Python 3.9+)
        from zoneinfo import ZoneInfo
        self.scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.timezone))

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.add_job(
                self._tick,
                trigger=IntervalTrigger(seconds=settings.scheduler_tick_seconds),
                id="reminder_tick",
                max_instances=1,
                misfire_grace_time=30,
            )
            self.scheduler.start()

    async def _tick(self) -> None:
        import logging
        logger = logging.getLogger(__name__)
        
        async with get_session() as session:
            # Сначала создаём напоминания на сегодня (если их ещё нет)
            await self._ensure_daily_reminders(session)
            await session.commit()  # Сохраняем созданные напоминания
            
            # Используем UTC для сравнения с БД
            now_utc = datetime.utcnow()
            # Ищем напоминания, которые должны быть отправлены (включая небольшое окно в прошлом для пропущенных)
            cutoff_time = now_utc + timedelta(seconds=settings.scheduler_tick_seconds)
            # Также ищем напоминания, которые уже должны были быть отправлены (до 5 минут назад)
            past_cutoff = now_utc - timedelta(minutes=5)
            
            # Для диагностики: проверим все незавершенные напоминания
            all_pending = await session.exec(
                select(Reminder).where(Reminder.completed.is_(False))
            )
            all_pending_list = all_pending.all()
            if all_pending_list:
                logger.debug(f"All pending reminders: {[(r.id, r.reminder_type, r.scheduled_for, r.user_id) for r in all_pending_list]}")
            
            statement = select(Reminder).where(
                Reminder.scheduled_for <= cutoff_time,
                Reminder.scheduled_for >= past_cutoff,  # Не отправляем очень старые напоминания
                Reminder.completed.is_(False),
            )
            reminders = (await session.exec(statement)).all()
            
            # Логируем детали для лекарств для отладки
            med_reminders = [r for r in reminders if r.reminder_type == ReminderType.MEDICATION]
            if med_reminders:
                logger.info(
                    f"_tick: found {len(med_reminders)} medication reminders to dispatch: "
                    f"{[(r.id, r.scheduled_for, r.payload) for r in med_reminders]}"
                )
            
            logger.info(
                f"_tick: found {len(reminders)} reminders to dispatch at {now_utc} "
                f"(cutoff: {cutoff_time}, past_cutoff: {past_cutoff}, total pending: {len(all_pending_list)})"
            )
            
            # Если есть pending, но не найдены для отправки, логируем детали только для debug
            # (напоминания, запланированные на завтра, это нормально)
            if all_pending_list and not reminders:
                for r in all_pending_list:
                    diff_seconds = (r.scheduled_for - now_utc).total_seconds()
                    in_past = r.scheduled_for >= past_cutoff
                    in_future = r.scheduled_for <= cutoff_time
                    in_range = in_past and in_future
                    # Логируем только если напоминание должно было быть отправлено (в прошлом)
                    # или если оно в ближайшем будущем (в пределах часа)
                    if diff_seconds < 0 or (diff_seconds > 0 and diff_seconds < 3600):
                        logger.debug(
                            f"Pending reminder {r.id} (type={r.reminder_type}, user={r.user_id}) "
                            f"scheduled_for={r.scheduled_for}, now_utc={now_utc}, "
                            f"diff={diff_seconds:.0f}s, past_cutoff={past_cutoff}, cutoff={cutoff_time}, "
                            f"in_range={in_range} (past={in_past}, future={in_future})"
                        )
            
            for reminder in reminders:
                try:
                    diff_seconds = (reminder.scheduled_for - now_utc).total_seconds()
                    logger.info(
                        f"Dispatching reminder {reminder.id}: type={reminder.reminder_type}, "
                        f"user={reminder.user_id}, scheduled_for={reminder.scheduled_for}, "
                        f"payload={reminder.payload}, now_utc={now_utc}, diff={diff_seconds:.0f}s"
                    )
                    await self._dispatch(reminder)
                    reminder.completed = True
                    session.add(reminder)
                except TelegramAPIError as e:
                    # Логируем ошибку, но продолжаем
                    logger.error(f"Failed to send reminder {reminder.id}: {e}", exc_info=True)
                    if reminder.reminder_type == ReminderType.HYDRATION and next_retry_allowed(reminder.attempt):
                        reminder.attempt += 1
                        reminder.scheduled_for = now_utc + timedelta(minutes=15)
                    else:
                        reminder.completed = True
                    session.add(reminder)
                except Exception as e:
                    # Логируем любые другие ошибки
                    logger.error(f"Unexpected error sending reminder {reminder.id}: {e}", exc_info=True)
                    reminder.completed = True
                    session.add(reminder)
            await session.commit()

    async def _ensure_daily_reminders(self, session) -> None:
        """
        Создаёт ежедневные напоминания для всех пользователей.
        Вызывается каждый тик, но создаёт напоминания только если их ещё нет на сегодня.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        users = (await session.exec(select(User))).all()
        now = datetime.utcnow()
        logger.debug(f"_ensure_daily_reminders: processing {len(users)} users at {now}")
        
        for user in users:
            modules = set(user.get_modules() or [])
            logger.debug(f"User {user.telegram_id}: modules={modules}")
            
            # Утреннее пробуждение (только если модуль sleep активен)
            if "sleep" in modules or not modules:  # По умолчанию включен
                await self._ensure_reminder(
                    session,
                    user_id=user.telegram_id,
                    reminder_type=ReminderType.MORNING_WAKE,
                    target_time=user.desired_wake_time,
                    now=now,
                )
            
            # Напоминания о воде (только если модуль hydration активен)
            if "hydration" in modules or not modules:  # По умолчанию включен
                hydration_schedule = build_hydration_schedule(user, user.desired_wake_time)
                # Пропускаем первое напоминание, если оно совпадает с временем пробуждения
                # Первое напоминание о воде должно быть через 30-60 минут после пробуждения
                for idx, dose in enumerate(hydration_schedule):
                    # Если это первое напоминание и оно совпадает с временем пробуждения, пропускаем его
                    if idx == 0 and dose.target_time == user.desired_wake_time:
                        # Создаем первое напоминание через 30 минут после пробуждения
                        from datetime import timedelta
                        wake_minutes = user.desired_wake_time.hour * 60 + user.desired_wake_time.minute
                        first_water_minutes = (wake_minutes + 30) % (24 * 60)
                        from app.services.sleep import minutes_to_time
                        first_water_time = minutes_to_time(first_water_minutes)
                        await self._ensure_reminder(
                            session,
                            user_id=user.telegram_id,
                            reminder_type=ReminderType.HYDRATION,
                            target_time=first_water_time,
                            now=now,
                        )
                    else:
                        await self._ensure_reminder(
                            session,
                            user_id=user.telegram_id,
                            reminder_type=ReminderType.HYDRATION,
                            target_time=dose.target_time,
                            now=now,
                        )
            
            # Напоминания о лекарствах
            if "meds" in modules:
                meds_result = await session.exec(
                    select(MedicationSchedule).where(MedicationSchedule.user_id == user.telegram_id)
                )
                meds_list = meds_result.all()
                logger.info(f"User {user.telegram_id}: found {len(meds_list)} medication schedules")
                for med in meds_list:
                    payload = json.dumps({"name": med.name, "dosage": med.dosage}, ensure_ascii=False)
                    logger.info(
                        f"Creating reminder for {med.name} at {med.intake_time} (local time) "
                        f"for user {user.telegram_id} in timezone {user.timezone}"
                    )
                    await self._ensure_reminder(
                        session,
                        user_id=user.telegram_id,
                        reminder_type=ReminderType.MEDICATION,
                        target_time=med.intake_time,
                        now=now,
                        payload=payload,
                        user_timezone=user.timezone,
                    )
            else:
                logger.debug(f"User {user.telegram_id}: 'meds' module not active")
            # Добавляем опрос о самочувствии за час до сна (если модуль symptoms активен)
            if "symptoms" in modules:
                # Вычисляем время отхода ко сну на основе желаемого времени подъёма и цели сна
                from app.services.sleep import build_bedtime_plan
                plan = build_bedtime_plan(user)
                bedtime = plan.target_bedtime
                # Вычитаем час
                bedtime_dt = datetime.combine(now.date(), bedtime)
                wellness_time_dt = bedtime_dt - timedelta(hours=1)
                if wellness_time_dt < now:
                    wellness_time_dt += timedelta(days=1)
                wellness_time = wellness_time_dt.time()
                await self._ensure_reminder(
                    session,
                    user_id=user.telegram_id,
                    reminder_type=ReminderType.WELLNESS_CHECK,
                    target_time=wellness_time,
                    now=now,
                    user_timezone=user.timezone,
                )

    async def _ensure_reminder(
        self,
        session,
        user_id: int,
        reminder_type: ReminderType,
        target_time: time,
        now: datetime,
        payload: str | None = None,
        user_timezone: str | None = None,
    ) -> None:
        """
        Создаёт напоминание, если его ещё нет на сегодня.
        Для лекарств проверяем также payload, чтобы различать разные препараты.
        
        Args:
            user_timezone: Часовой пояс пользователя (например, 'Europe/Moscow').
                          Если не указан, используется timezone из настроек.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Получаем timezone пользователя
        tz_str = user_timezone or settings.timezone
        try:
            user_tz = ZoneInfo(tz_str)
        except Exception:
            logger.warning(f"Invalid timezone {tz_str}, using UTC")
            user_tz = ZoneInfo("UTC")
        
        # Создаём datetime в локальном времени пользователя
        # Используем текущее время в UTC и конвертируем в timezone пользователя
        now_utc = datetime.utcnow()
        now_utc_tz = now_utc.replace(tzinfo=ZoneInfo("UTC"))
        user_now = now_utc_tz.astimezone(user_tz)
        
        # Создаём целевое время на сегодня в timezone пользователя
        target_dt_local = datetime.combine(user_now.date(), target_time).replace(tzinfo=user_tz)
        
        # Если время уже прошло сегодня в локальном времени, планируем на завтра
        if target_dt_local < user_now:
            target_dt_local += timedelta(days=1)
        
        # Конвертируем в UTC для хранения в БД
        target_dt_utc = target_dt_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        
        logger.info(
            f"Creating reminder: local_time={target_dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')}, "
            f"utc_time={target_dt_utc.strftime('%Y-%m-%d %H:%M:%S')}, "
            f"user_tz={tz_str}, now_utc={now_utc.strftime('%Y-%m-%d %H:%M:%S')}, "
            f"user_now={user_now.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )
        
        # Для лекарств нужно проверять также payload, чтобы различать разные препараты
        # Также проверяем напоминания на сегодня и завтра, чтобы не создавать дубликаты
        if reminder_type == ReminderType.MEDICATION:
            # Для лекарств проверяем более широкий диапазон (сегодня и завтра)
            today_start = target_dt_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow_end = today_start + timedelta(days=2)
            exists_stmt = select(Reminder).where(
                Reminder.user_id == user_id,
                Reminder.reminder_type == reminder_type,
                Reminder.completed.is_(False),
                Reminder.scheduled_for >= today_start,
                Reminder.scheduled_for < tomorrow_end,
                Reminder.payload == payload,  # Проверяем также payload для лекарств
            )
        else:
            # Для других типов проверяем более узкий диапазон
            exists_stmt = select(Reminder).where(
                Reminder.user_id == user_id,
                Reminder.reminder_type == reminder_type,
                Reminder.completed.is_(False),
                Reminder.scheduled_for.between(target_dt_utc - timedelta(minutes=5), target_dt_utc + timedelta(minutes=5)),
            )
        exists = (await session.exec(exists_stmt)).first()
        if exists:
            logger.debug(f"Reminder already exists: user={user_id}, type={reminder_type}, time={target_time}, scheduled_for={exists.scheduled_for}")
            return
        
        reminder = Reminder(
            user_id=user_id,
            reminder_type=reminder_type,
            scheduled_for=target_dt_utc,
            payload=payload,
        )
        session.add(reminder)
        logger.info(
            f"Created reminder: user={user_id}, type={reminder_type}, "
            f"scheduled_for_utc={target_dt_utc}, scheduled_for_local={target_dt_local.strftime('%Y-%m-%d %H:%M:%S')}, "
            f"payload={payload}"
        )

    async def _dispatch(self, reminder: Reminder) -> None:
        if reminder.reminder_type == ReminderType.MORNING_WAKE:
            from app.bot.keyboards.common import wake_keyboard
            await self.bot.send_message(
                reminder.user_id,
                "Доброе утро! Нажмите «Я проснулся» или выберите время отложить напоминание.",
                reply_markup=wake_keyboard().as_markup(),
            )
        elif reminder.reminder_type == ReminderType.HYDRATION:
            from app.bot.keyboards.common import hydration_keyboard
            await self.bot.send_message(
                reminder.user_id,
                "Напоминание о воде: сделайте пару глотков и нажмите «Я попил».",
                reply_markup=hydration_keyboard().as_markup(),
            )
        elif reminder.reminder_type == ReminderType.MEAL:
            await self.bot.send_message(
                reminder.user_id,
                "Время приёма пищи из сегодняшнего плана.",
            )
        elif reminder.reminder_type == ReminderType.TRAINING:
            await self.bot.send_message(
                reminder.user_id,
                "Тренировка скоро начнётся. Нажмите «Начать» или «Отменить».",
            )
        elif reminder.reminder_type == ReminderType.POST_WORKOUT:
            await self.bot.send_message(
                reminder.user_id,
                "Как самочувствие после тренировки? Оцените по шкале 0–4.",
            )
        elif reminder.reminder_type == ReminderType.MEDICATION:
            import logging
            logger = logging.getLogger(__name__)
            
            details = {}
            if reminder.payload:
                try:
                    details = json.loads(reminder.payload)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse medication payload: {reminder.payload}")
                    details = {}
            name = details.get("name", "препарат")
            dosage = details.get("dosage")
            text = f"Напоминание о приёме {name}"
            if dosage:
                text += f" ({dosage})"
            from app.bot.keyboards.common import medication_keyboard
            logger.info(f"Sending medication reminder to user {reminder.user_id}: {text}")
            try:
                await self.bot.send_message(
                    reminder.user_id,
                    f"{text}. Пожалуйста, подтвердите приём.",
                    reply_markup=medication_keyboard(reminder.id).as_markup(),
                )
                logger.info(f"Successfully sent medication reminder {reminder.id} to user {reminder.user_id}")
            except Exception as e:
                logger.error(f"Error sending medication reminder {reminder.id}: {e}", exc_info=True)
                raise
        elif reminder.reminder_type == ReminderType.WELLNESS_CHECK:
            await self.bot.send_message(
                reminder.user_id,
                "Как вы себя чувствуете? Опишите самочувствие или используйте /symptoms для детального описания.",
            )

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

