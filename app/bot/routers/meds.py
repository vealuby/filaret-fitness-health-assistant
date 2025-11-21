from __future__ import annotations

from datetime import datetime
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlmodel import delete, select

from app.database import get_session
from app.models import MedicationSchedule, Reminder, User
from app.services.modules import DEFAULT_MODULES


router = Router(name="meds")


class MedsStates(StatesGroup):
    name = State()
    dosage = State()
    time = State()


@router.message(Command("meds"))
@router.message(F.text.lower() == "лекарства")
async def meds_entry(message: Message, state: FSMContext) -> None:
    user = await _fetch_user(message.from_user.id)
    if not user:
        await message.answer("Профиль не найден. Используйте /start.")
        return
    if "meds" not in (user.get_modules() or DEFAULT_MODULES):
        await message.answer("Модуль лекарств отключён. Включите его через /modules.")
        return
    await _send_meds_list(message, user)


@router.callback_query(F.data == "meds:add")
async def meds_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(user_id=callback.from_user.id)
    await state.set_state(MedsStates.name)
    await callback.message.answer("Введите название препарата.")
    await callback.answer()


@router.message(MedsStates.name, F.text)
async def meds_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip())
    await state.set_state(MedsStates.dosage)
    await message.answer("Укажите дозировку или комментарий (можно пропустить, отправив «-»).")


@router.message(MedsStates.dosage, F.text)
async def meds_dosage(message: Message, state: FSMContext) -> None:
    dosage = message.text.strip()
    await state.update_data(dosage=None if dosage == "-" else dosage)
    await state.set_state(MedsStates.time)
    await message.answer("Во сколько принимать? Формат ЧЧ:ММ.")


@router.message(MedsStates.time, F.text)
async def meds_time(message: Message, state: FSMContext) -> None:
    try:
        intake_time = datetime.strptime(message.text.strip(), "%H:%M").time()
    except ValueError:
        await message.answer("Введите время в формате 08:30.")
        return
    data = await state.get_data()
    async with get_session() as session:
        schedule = MedicationSchedule(
            user_id=message.from_user.id,
            name=data.get("name", "Препарат"),
            dosage=data.get("dosage"),
            intake_time=intake_time,
        )
        session.add(schedule)
        await session.commit()
    await message.answer("Напоминание сохранено.")
    await state.clear()
    user = await _fetch_user(message.from_user.id)
    if user:
        await _send_meds_list(message, user)


@router.callback_query(F.data.startswith("meds:delete:"))
async def meds_delete(callback: CallbackQuery) -> None:
    med_id = int(callback.data.split(":")[-1])
    async with get_session() as session:
        await session.exec(
            delete(MedicationSchedule).where(
                MedicationSchedule.id == med_id,
                MedicationSchedule.user_id == callback.from_user.id,
            )
        )
        await session.commit()
    await callback.answer("Удалено")
    user = await _fetch_user(callback.from_user.id)
    if user:
        await _send_meds_list(callback.message, user, edit=True)


async def _send_meds_list(message: Message, user: User, edit: bool = False) -> None:
    async with get_session() as session:
        result = await session.exec(
            select(MedicationSchedule).where(MedicationSchedule.user_id == user.telegram_id)
        )
        meds = result.all()
    if meds:
        lines = [
            f"{idx+1}. {med.intake_time.strftime('%H:%M')} — {med.name}"
            + (f" ({med.dosage})" if med.dosage else "")
            for idx, med in enumerate(meds)
        ]
        text = "Текущие напоминания о лекарствах:\n" + "\n".join(lines)
    else:
        text = "Напоминания о лекарствах не найдены."
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить напоминание", callback_data="meds:add")
    for med in meds:
        builder.button(text=f"Удалить {med.name}", callback_data=f"meds:delete:{med.id}")
    builder.adjust(1)
    if edit and message:
        await message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("meds:taken:"))
async def meds_taken(callback: CallbackQuery) -> None:
    reminder_id = int(callback.data.split(":")[-1])
    async with get_session() as session:
        result = await session.exec(select(Reminder).where(Reminder.id == reminder_id))
        reminder = result.first()
        if reminder:
            reminder.completed = True
            session.add(reminder)
            await session.commit()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Отмечено как принятое. Спасибо!")
    await callback.answer()


@router.callback_query(F.data.startswith("meds:skip:"))
async def meds_skip(callback: CallbackQuery) -> None:
    reminder_id = int(callback.data.split(":")[-1])
    async with get_session() as session:
        result = await session.exec(select(Reminder).where(Reminder.id == reminder_id))
        reminder = result.first()
        if reminder:
            reminder.completed = True
            session.add(reminder)
            await session.commit()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Отмечено как пропущенное.")
    await callback.answer()


async def _fetch_user(telegram_id: int) -> Optional[User]:
    async with get_session() as session:
        result = await session.exec(select(User).where(User.telegram_id == telegram_id))
        return result.first()

