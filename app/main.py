from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from app.bot.routers import commands, meds, onboarding, reminders, training, symptoms
from app.config import settings
from app.database import init_db
from app.scheduler import ReminderScheduler


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


async def setup_bot_commands(bot: Bot) -> None:
    """Устанавливает меню команд для бота"""
    commands_list = [
        BotCommand(command="start", description="Начать работу с ботом"),
        BotCommand(command="help", description="Показать справку"),
        BotCommand(command="profile", description="Показать профиль"),
        BotCommand(command="plan", description="План питания на день"),
        BotCommand(command="summary", description="Сводка за 3 дня с анализом"),
        BotCommand(command="ask", description="Задать вопрос LLM"),
        BotCommand(command="training", description="Записать тренировку"),
        BotCommand(command="meds", description="Управление лекарствами"),
        BotCommand(command="symptoms", description="Записать симптомы"),
        BotCommand(command="symptoms_summary", description="Сводка по самочувствию"),
        BotCommand(command="modules", description="Управление модулями"),
        BotCommand(command="fix_timezone", description="Исправить часовой пояс"),
        BotCommand(command="delete_data", description="Удалить все данные"),
    ]
    await bot.set_my_commands(commands_list)


async def main() -> None:
    await init_db()
    bot = Bot(
        token=settings.telegram_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    # Устанавливаем меню команд
    await setup_bot_commands(bot)
    dp = Dispatcher()
    dp.include_router(onboarding.router)
    dp.include_router(reminders.router)
    dp.include_router(training.router)
    dp.include_router(meds.router)
    dp.include_router(symptoms.router)
    dp.include_router(commands.router)
    reminder_scheduler = ReminderScheduler(bot)
    reminder_scheduler.start()
    try:
        await dp.start_polling(bot)
    finally:
        reminder_scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

