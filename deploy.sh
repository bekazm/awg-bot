#!/usr/bin/env bash
# deploy.sh — деплой awg-bot на сервер
set -euo pipefail

SERVER="root@72.56.109.180"
REMOTE_DIR="/opt/awg-bot"
CONFIG_DIR="/etc/awg-bot"
SERVICE="awg-bot"

echo "=== Деплой awg-bot ==="

# 1. Копируем бот
scp -o StrictHostKeyChecking=no bot.py "$SERVER:$REMOTE_DIR/bot.py"

# 2. Создаём структуру, если первый деплой
ssh -o StrictHostKeyChecking=no "$SERVER" bash << 'REMOTE'
set -e

# Venv и зависимости
if [ ! -d /opt/awg-bot/venv ]; then
    echo "Создаём venv..."
    apt-get install -y python3-venv qrencode 2>/dev/null
    python3 -m venv /opt/awg-bot/venv
fi

/opt/awg-bot/venv/bin/pip install -q --upgrade pip
/opt/awg-bot/venv/bin/pip install -q "python-telegram-bot>=21.0"

# Директории конфига
mkdir -p /etc/awg-bot/clients

# Systemd сервис
cat > /etc/systemd/system/awg-bot.service << 'SERVICE'
[Unit]
Description=AmneziaWG Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/awg-bot
ExecStart=/opt/awg-bot/venv/bin/python3 /opt/awg-bot/bot.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/awg-bot.log
StandardError=append:/var/log/awg-bot.log

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable awg-bot
echo "Systemd OK"
REMOTE

# 3. Перезапускаем
ssh -o StrictHostKeyChecking=no "$SERVER" "systemctl restart $SERVICE && sleep 2 && systemctl is-active $SERVICE"

echo "=== Деплой завершён ==="
