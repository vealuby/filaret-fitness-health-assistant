from __future__ import annotations

from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from app.services.modules import AVAILABLE_MODULES


def wake_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Я проснулся", callback_data="wake:confirmed")
    builder.button(text="Отложить 15 мин", callback_data="wake:snooze:15")
    builder.button(text="Отложить 30 мин", callback_data="wake:snooze:30")
    builder.button(text="Отложить 60 мин", callback_data="wake:snooze:60")
    builder.adjust(1)
    return builder


def hydration_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="50 мл", callback_data="water:add:50")
    builder.button(text="100 мл", callback_data="water:add:100")
    builder.button(text="200 мл", callback_data="water:add:200")
    builder.button(text="Я попил", callback_data="water:done")
    builder.button(text="Напомнить позже", callback_data="water:snooze")
    builder.adjust(3, 1, 1)
    return builder


def training_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Начать тренировку", callback_data="training:start")
    builder.button(text="Отменить", callback_data="training:cancel")
    builder.button(text="Закончил", callback_data="training:end")
    builder.adjust(1)
    return builder


def wellness_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for score in range(5):
        builder.button(text=str(score), callback_data=f"wellness:{score}")
    builder.adjust(5)
    return builder


def main_menu(active_modules: set[str] | None = None) -> ReplyKeyboardBuilder:
    if active_modules is None:
        active_modules = set()
    builder = ReplyKeyboardBuilder()
    # Первая строка: План на день / Вода
    builder.button(text="План на день")
    builder.button(text="Вода")
    # Вторая строка: Я покушал
    builder.button(text="Я покушал")
    # Третья строка: Тренировка (если заданы тренировки)
    if "training" in active_modules:
        builder.button(text="Тренировка")
    # Четвертая строка: У меня вопрос
    builder.button(text="У меня вопрос")
    # Пятая строка: Лекарства / Симптомы (в зависимости от модулей)
    if "meds" in active_modules and "symptoms" in active_modules:
        builder.button(text="Лекарства")
        builder.button(text="Симптомы")
    elif "meds" in active_modules:
        builder.button(text="Лекарства")
    elif "symptoms" in active_modules:
        builder.button(text="Симптомы")
    # Шестая строка: Профиль
    builder.button(text="Профиль")
    # Седьмая строка: Модули
    builder.button(text="Модули")
    # Настраиваем расположение кнопок
    if "training" in active_modules and "meds" in active_modules and "symptoms" in active_modules:
        builder.adjust(2, 1, 1, 1, 2, 1, 1)  # План/Вода, Покушал, Тренировка, Вопрос, Лекарства/Симптомы, Профиль, Модули
    elif "training" in active_modules and ("meds" in active_modules or "symptoms" in active_modules):
        builder.adjust(2, 1, 1, 1, 2, 1, 1)
    elif "training" in active_modules:
        builder.adjust(2, 1, 1, 1, 1, 1, 1)
    elif "meds" in active_modules and "symptoms" in active_modules:
        builder.adjust(2, 1, 1, 2, 1, 1)
    elif "meds" in active_modules or "symptoms" in active_modules:
        builder.adjust(2, 1, 1, 1, 1, 1, 1)
    else:
        builder.adjust(2, 1, 1, 1, 1, 1)
    return builder


def modules_keyboard(selected: set[str], context: str) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for module in AVAILABLE_MODULES:
        marker = "✅" if module["id"] in selected else "➕"
        builder.button(
            text=f"{marker} {module['label']}",
            callback_data=f"modules:{context}:toggle:{module['id']}",
        )
    builder.button(text="Готово", callback_data=f"modules:{context}:done")
    builder.adjust(1)
    return builder


def llm_cancel_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="llm:cancel")
    builder.adjust(1)
    return builder


def training_type_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="🏋️ Силовая", callback_data="training_log:type:strength")
    builder.button(text="🏃 Кардио", callback_data="training_log:type:cardio")
    builder.button(text="🧘 Мобилити/йога", callback_data="training_log:type:mobility")
    builder.button(text="Отмена", callback_data="training_log:cancel")
    builder.adjust(1)
    return builder


def medication_keyboard(reminder_id: int) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Принял", callback_data=f"meds:taken:{reminder_id}")
    builder.button(text="Пропустить", callback_data=f"meds:skip:{reminder_id}")
    builder.adjust(2)
    return builder


def timezone_keyboard() -> InlineKeyboardBuilder:
    """Создает клавиатуру с популярными часовыми поясами"""
    builder = InlineKeyboardBuilder()
    
    # Популярные часовые пояса для России и СНГ
    timezones = [
        ("🇷🇺 Москва (MSK)", "Europe/Moscow"),
        ("🇺🇦 Киев (EET)", "Europe/Kyiv"),
        ("🇧🇾 Минск (MSK)", "Europe/Minsk"),
        ("🇰🇿 Алматы (ALMT)", "Asia/Almaty"),
        ("🇺🇿 Ташкент (UZT)", "Asia/Tashkent"),
        ("🇪🇺 Берлин (CET)", "Europe/Berlin"),
        ("🇫🇷 Париж (CET)", "Europe/Paris"),
        ("🇬🇧 Лондон (GMT)", "Europe/London"),
        ("🇺🇸 Нью-Йорк (EST)", "America/New_York"),
        ("🇺🇸 Лос-Анджелес (PST)", "America/Los_Angeles"),
        ("🇨🇳 Пекин (CST)", "Asia/Shanghai"),
        ("🇯🇵 Токио (JST)", "Asia/Tokyo"),
    ]
    
    for label, tz in timezones:
        builder.button(text=label, callback_data=f"timezone:set:{tz}")
    
    builder.adjust(2)  # По 2 кнопки в ряд
    return builder

