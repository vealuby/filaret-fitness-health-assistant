# Filaret Fitness Bot

Телеграм-бот для поддержки сна, питания, воды и тренировок по научно обоснованным рекомендациям (AASM, chrononutrition).

## Возможности

- Онбординг с профилем (сон, антропометрия, график работы, тренировки, вода, цели) + быстрый режим `/quickstart`.
- Система модулей (`/modules`): сон, энергия, питание, тренировки, лекарства, симптомы и т.д.
- Расчёт bedtime, учёт sleep debt, предложения по chronotherapy и персонализированный калораж.
- Дневной план питания на русском языке с примерами блюд, калориями и БЖУ.
- Напоминания о воде, лекарствах (`/meds`) и утренних подъёмах с управлением повторов.
- Управление тренировками: напоминания, ручное логирование «Я был на тренировке», пост-тренировочный опрос.
- Лог симптомов `/symptoms` с подсказками от LLM и дисклеймерами.
- Интеграция OpenAI (`/ask`) через кнопку и FSM.
- Команды `/profile`, `/plan`, `/delete_data`, `/help`, `/training`, `/modules`, `/meds`, `/symptoms`.
- Docker / systemd развёртывание, APScheduler для напоминаний.

## Быстрый старт

```bash
cp .env.example .env
# заполните TELEGRAM_TOKEN и OPENAI_API_KEY
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m app.main
```

### Docker

```bash
docker compose up --build
```

## Тесты и качество кода

```bash
pytest
ruff check .
mypy app
```

## Документация

- `docs/deployment.md` — инструкции по запуску и systemd unit.
- `docs/algorithms.md` — описание алгоритмов сна, питания, воды и тренировок.

