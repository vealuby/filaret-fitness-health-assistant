from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlmodel import select

from app.database import get_session
from app.models import SymptomLog, User
from app.services.llm import llm_client
from app.services.modules import DEFAULT_MODULES


router = Router(name="symptoms")


class SymptomStates(StatesGroup):
    description = State()
    severity = State()


@router.message(Command("symptoms"))
@router.message(F.text.lower() == "симптомы")
async def symptoms_entry(message: Message, state: FSMContext) -> None:
    user = await _fetch_user(message.from_user.id)
    if not user:
        await message.answer("Профиль не найден. Используйте /start.")
        return
    if "symptoms" not in (user.get_modules() or DEFAULT_MODULES):
        await message.answer("Модуль симптомов отключён. Включите его через /modules.")
        return
    await state.update_data(user_id=user.telegram_id)
    await state.set_state(SymptomStates.description)
    await message.answer("Опишите симптомы или самочувствие (можно несколькими предложениями).")


@router.message(SymptomStates.description, F.text)
async def symptoms_description(message: Message, state: FSMContext) -> None:
    await state.update_data(description=message.text.strip())
    await state.set_state(SymptomStates.severity)
    await message.answer("Насколько выражены симптомы? Оцените от 0 (минимально) до 3 (требует внимания).")


@router.message(SymptomStates.severity, F.text)
async def symptoms_severity(message: Message, state: FSMContext) -> None:
    try:
        severity = int(message.text.strip())
        if severity < 0 or severity > 3:
            raise ValueError
    except ValueError:
        await message.answer("Введите число от 0 до 3.")
        return
    data = await state.get_data()
    description = data.get("description", "")
    async with get_session() as session:
        log = SymptomLog(
            user_id=message.from_user.id,
            description=description,
            severity=severity,
        )
        session.add(log)
        await session.commit()
    user = await _fetch_user(message.from_user.id)
    if user and description:
        advice = await _symptom_response(user, description, severity)
        await message.answer(advice)
    else:
        await message.answer("Записал симптомы. При ухудшении обратитесь к врачу.")
    await state.clear()


async def _symptom_response(user: User, description: str, severity: int) -> str:
    if llm_client.enabled:
        try:
            question = (
                f"Симптомы: {description}. Уровень выраженности: {severity} (0-3). "
                "Дай рекомендации самонаблюдения и когда срочно обратиться к врачу."
            )
            answer = await llm_client.ask(user, question)
            return answer
        except Exception:
            pass
    return (
        "Записал симптомы. Отдыхайте, отслеживайте динамику и при усилении "
        "обратитесь к врачу или вызовите скорую помощь."
    )


@router.message(Command("symptoms_summary"))
async def symptoms_summary(message: Message) -> None:
    user = await _fetch_user(message.from_user.id)
    if not user:
        await message.answer("Профиль не найден. Используйте /start.")
        return
    if "symptoms" not in (user.get_modules() or DEFAULT_MODULES):
        await message.answer("Модуль симптомов отключён. Включите его через /modules.")
        return
    
    async with get_session() as session:
        # Получаем симптомы за последние 7 дней
        week_ago = date.today() - timedelta(days=7)
        result = await session.exec(
            select(SymptomLog)
            .where(SymptomLog.user_id == user.telegram_id)
            .where(SymptomLog.created_at >= datetime.combine(week_ago, datetime.min.time()))
            .order_by(SymptomLog.created_at.desc())
        )
        logs = result.all()
    
    if not logs:
        await message.answer("За последние 7 дней записей о симптомах нет.")
        return
    
    # Группируем по дням
    logs_by_date: dict[date, list[SymptomLog]] = {}
    for log in logs:
        log_date = log.created_at.date()
        if log_date not in logs_by_date:
            logs_by_date[log_date] = []
        logs_by_date[log_date].append(log)
    
    # Формируем сводку
    lines = ["Сводка по самочувствию за последние 7 дней:\n"]
    for log_date in sorted(logs_by_date.keys(), reverse=True):
        day_logs = logs_by_date[log_date]
        date_str = log_date.strftime("%d.%m")
        lines.append(f"📅 {date_str}:")
        for log in day_logs:
            severity_str = f" (выраженность: {log.severity}/3)" if log.severity is not None else ""
            lines.append(f"  • {log.description}{severity_str}")
        lines.append("")
    
    # Статистика за последние 3 дня
    three_days_ago = date.today() - timedelta(days=3)
    recent_logs = [log for log in logs if log.created_at.date() >= three_days_ago]
    if recent_logs:
        avg_severity = sum(log.severity for log in recent_logs if log.severity is not None) / len(
            [log for log in recent_logs if log.severity is not None]
        ) if any(log.severity is not None for log in recent_logs) else None
        lines.append(f"За последние 3 дня: {len(recent_logs)} записей")
        if avg_severity is not None:
            lines.append(f"Средняя выраженность: {avg_severity:.1f}/3")
    
    await message.answer("\n".join(lines))


async def _fetch_user(telegram_id: int) -> Optional[User]:
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == telegram_id))
        return result.first()

