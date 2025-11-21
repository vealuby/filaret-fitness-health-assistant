# Развёртывание

## Требования

- Python 3.11+
- Docker 24+ (для варианта с контейнерами)
- Токены: `TELEGRAM_TOKEN`, `OPENAI_API_KEY`

## Конфигурация

1. Скопируйте `.env.example` → `.env` и заполните токены.
2. При необходимости скорректируйте `TIMEZONE`, `DATABASE_URL`, `WEBHOOK_URL`.

## Запуск в Docker

```bash
docker compose up --build
```

Бот стартует в режиме polling. База (`storage/bot.db`) монтируется как volume.

## Локальный запуск (systemd)

1. Установите зависимости:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

2. Создайте unit-файл `/etc/systemd/system/sleepbot.service`:

```
[Unit]
Description=Sleep Coach Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/FilaretFitnessBot
EnvironmentFile=/opt/FilaretFitnessBot/.env
ExecStart=/opt/FilaretFitnessBot/.venv/bin/python -m app.main
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

3. Перезапустите systemd:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sleepbot.service
```

## Бэкап SQLite

```bash
sqlite3 storage/bot.db \".backup 'storage/bot.db.bak'\"
```

Рекомендуется настроить cron на ежедневный бэкап.

