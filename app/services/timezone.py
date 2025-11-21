from __future__ import annotations

from typing import Optional


# Маппинг language_code на примерные timezone
LANGUAGE_TO_TIMEZONE = {
    "ru": "Europe/Moscow",
    "uk": "Europe/Kyiv",
    "be": "Europe/Minsk",
    "kz": "Asia/Almaty",
    "uz": "Asia/Tashkent",
    "en": "America/New_York",  # По умолчанию для английского
    "de": "Europe/Berlin",
    "fr": "Europe/Paris",
    "es": "Europe/Madrid",
    "it": "Europe/Rome",
    "pt": "America/Sao_Paulo",
    "pl": "Europe/Warsaw",
    "tr": "Europe/Istanbul",
    "ar": "Asia/Dubai",
    "zh": "Asia/Shanghai",
    "ja": "Asia/Tokyo",
    "ko": "Asia/Seoul",
    "th": "Asia/Bangkok",
    "vi": "Asia/Ho_Chi_Minh",
    "id": "Asia/Jakarta",
    "hi": "Asia/Kolkata",
}


def detect_timezone_from_user(language_code: Optional[str] = None) -> str:
    """
    Определяет timezone на основе language_code пользователя.
    Если language_code не указан или не найден, возвращает Europe/Moscow по умолчанию.
    """
    if not language_code:
        return "Europe/Moscow"
    
    # Берем первые 2 символа (например, "ru" из "ru-RU")
    lang = language_code.lower().split("-")[0].split("_")[0]
    return LANGUAGE_TO_TIMEZONE.get(lang, "Europe/Moscow")

