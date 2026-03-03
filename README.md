# awg-bot 🛡

🇷🇺 [Русский](#русский) | 🇬🇧 [English](#english)

---

<a name="русский"></a>
## 🇷🇺 Русский

Telegram-бот для управления VPN-сервером на базе [AmneziaWG](https://github.com/amnezia-vpn/amneziawg-linux-kernel-module) — форка WireGuard с защитой от DPI/блокировок.

Полностью кнопочный интерфейс, никаких команд вводить не нужно.

---

## Интерфейс

```
┌─────────────────────────────────┐
│   🛡 AmneziaWG Bot              │
│   Выбери действие:              │
│                                 │
│  [📊 Статус сервера]            │
│  [👥 Клиенты]  [➕ Добавить]   │
│  [💾 Бэкап]    [🔄 Рестарт]    │
│  [📋 Audit log]                 │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│  👤 ivan                        │
│                                 │
│  📍 VPN IP: 10.66.66.3          │
│  📶 Статус: 🟢 Онлайн           │
│  🤝 Handshake: 2026-03-03 18:22 │
│  📥 Rx: 142.3 MB                │
│  📤 Tx: 23.1 MB                 │
│  ⏱ Доступ: до 2026-03-10 12:00  │
│                                 │
│  [📄 .conf]  [📱 QR-код]       │
│  [⛔ Отключить]  [🔑 Ротация]  │
│  [⏱ Срок доступа]  [🗑 Удалить]│
└─────────────────────────────────┘
```

---

## Возможности

### 👥 Управление клиентами
- Добавить клиента — вводи `@никнейм` или просто имя
- Удалить клиента с подтверждением
- Включить / отключить без удаления
- Статистика: трафик Rx/Tx, точное время последнего handshake, IP

### ⏱ Временный доступ
- Выдать доступ на **1 / 7 / 30 дней** или сделать бессрочным
- При истечении срока — пир **автоматически отключается** и в Telegram приходит уведомление

### 📱 Подключение клиентов
- Скачать готовый `.conf` файл одной кнопкой
- QR-код для мобильных устройств (iOS/Android)
- Конфиги совместимы с [AmneziaVPN](https://amnezia.org/ru/downloads)
- Junk-параметры AmneziaWG добавляются автоматически

### 🔑 Ротация ключей
- Перегенерировать ключи клиенту без смены IP
- Новый `.conf` и QR отправляются автоматически

### 💾 Резервное копирование
- Кнопка **💾 Бэкап** — файл `awg0.conf` с timestamp прямо в Telegram

### 📊 Мониторинг сервера
- CPU, RAM, disk usage в реальном времени
- Количество активных клиентов (по handshake < 3 мин)
- Load average, uptime

### 🔔 Автоматические уведомления

| Событие | Алёрт |
|---------|-------|
| `awg0` интерфейс упал | 🔴 + кнопка «Перезапустить» |
| `awg0` интерфейс поднялся | 🟢 |
| CPU > 80% | 🔴 CPU алёрт |
| RAM > 90% | 🔴 RAM алёрт |
| Клиент подключился | 🔔 имя + IP |
| Срок доступа истёк | ⏱ клиент автоотключён |

### 📋 Audit log
- Все действия записываются в `/var/log/awg-bot-audit.log`
- Просмотр последних 30 записей прямо в боте

---

## Требования

- Ubuntu 20.04+ / Debian 11+
- Python 3.10+
- [AmneziaWG](https://github.com/amnezia-vpn/amneziawg-linux-kernel-module) установлен, интерфейс `awg0` поднят
- `qrencode` (для QR-кодов — скрипт установит автоматически)
- Telegram Bot Token от [@BotFather](https://t.me/BotFather)

---

## Установка

### 1. Создать бота

1. Напиши [@BotFather](https://t.me/BotFather) → `/newbot`
2. Получи токен вида `1234567890:AAH...`

### 2. Узнать свой Telegram ID

Напиши [@userinfobot](https://t.me/userinfobot) — пришлёт числовой ID.

### 3. Создать конфиг на сервере

```bash
mkdir -p /etc/awg-bot/clients

cat > /etc/awg-bot/config.json << 'EOF'
{
  "bot_token": "ВАШ_ТОКЕН_ОТ_BOTFATHER",
  "admin_ids": [ВАШ_TELEGRAM_ID],
  "server_ip": "IP_ВАШЕГО_СЕРВЕРА",
  "server_vpn_ip": "10.66.66.1",
  "vpn_subnet": "10.66.66.0/24",
  "dns": "1.1.1.1"
}
EOF

chmod 600 /etc/awg-bot/config.json
```

> `admin_ids` — только эти Telegram User ID получат доступ. Остальные увидят `⛔ Нет доступа`.

### 4. Деплой

```bash
git clone https://github.com/YOUR_USERNAME/awg-bot.git
cd awg-bot
chmod +x deploy.sh
./deploy.sh
```

Скрипт автоматически:
- Установит `python3-venv` и `qrencode`
- Создаст virtualenv в `/opt/awg-bot/venv/`
- Установит `python-telegram-bot`
- Создаст и запустит systemd-сервис `awg-bot`

### 5. Проверить

```bash
systemctl status awg-bot
tail -f /var/log/awg-bot.log
```

Открой бота в Telegram → `/start`

---

## Ручная установка (без скрипта)

```bash
# Зависимости
apt-get install -y python3-venv qrencode

# Копируем код
mkdir -p /opt/awg-bot
cp bot.py /opt/awg-bot/

# Virtualenv
python3 -m venv /opt/awg-bot/venv
/opt/awg-bot/venv/bin/pip install "python-telegram-bot>=21.0"

# Systemd-сервис
cat > /etc/systemd/system/awg-bot.service << 'EOF'
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
EOF

systemctl daemon-reload
systemctl enable --now awg-bot
```

---

## Конфигурация

| Ключ | Описание | Пример |
|------|----------|--------|
| `bot_token` | Токен от BotFather | `"1234567890:AAH..."` |
| `admin_ids` | Список Telegram ID с доступом | `[123456789]` |
| `server_ip` | Публичный IP сервера | `"1.2.3.4"` |
| `server_vpn_ip` | IP сервера в VPN-сети | `"10.66.66.1"` |
| `vpn_subnet` | Подсеть VPN | `"10.66.66.0/24"` |
| `dns` | DNS для клиентов | `"1.1.1.1"` |

Пример — в файле `config.example.json`.

---

## Файловая структура

### Проект

```
awg-bot/
├── bot.py                # Основной код бота
├── requirements.txt      # Python-зависимости
├── deploy.sh             # Скрипт деплоя
├── config.example.json   # Пример конфига (без секретов)
├── .gitignore
└── README.md
```

### На сервере

```
/opt/awg-bot/
├── bot.py
└── venv/

/etc/awg-bot/
├── config.json         # ⚠️ Секретный — не коммитить!
├── peers.json          # База клиентов (авто)
└── clients/
    ├── alice.conf
    └── bob.conf

/var/log/
├── awg-bot.log         # Лог процесса
└── awg-bot-audit.log   # Audit log действий
```

---

## Управление

```bash
# Статус
systemctl status awg-bot

# Перезапуск
systemctl restart awg-bot

# Логи
tail -f /var/log/awg-bot.log

# Audit log
tail -f /var/log/awg-bot-audit.log

# Обновить бот
scp bot.py root@SERVER:/opt/awg-bot/bot.py
ssh root@SERVER 'systemctl restart awg-bot'
```

---

## AmneziaWG

Бот разработан для [AmneziaWG](https://github.com/amnezia-vpn/amneziawg-linux-kernel-module) — форка WireGuard с Junk-параметрами (`Jc`, `Jmin`, `Jmax`, `S1`, `S2`, `H1`–`H4`) для обхода DPI.

Junk-параметры бот читает **автоматически** из `/etc/amnezia/amneziawg/awg0.conf` и вставляет в генерируемые клиентские конфиги.

Клиентское приложение: [AmneziaVPN](https://amnezia.org/ru/downloads) — iOS, Android, Windows, macOS, Linux.

---

## Безопасность

- Доступ только по числовому Telegram User ID (не по нику)
- Конфиг с токеном хранится в `/etc/awg-bot/config.json` с правами `600`
- Опасные действия (удаление, рестарт, ротация) требуют кнопки подтверждения
- Все действия фиксируются в audit log с timestamp и user_id

---

## Лицензия

MIT

---

<a name="english"></a>
## 🇬🇧 English

A Telegram bot for managing a VPN server based on [AmneziaWG](https://github.com/amnezia-vpn/amneziawg-linux-kernel-module) — a WireGuard fork with DPI/censorship bypass capabilities.

Fully button-driven interface — no commands to type.

---

## Interface

```
┌─────────────────────────────────┐
│   🛡 AmneziaWG Bot              │
│   Choose an action:             │
│                                 │
│  [📊 Server Status]             │
│  [👥 Clients]  [➕ Add]        │
│  [💾 Backup]   [🔄 Restart]    │
│  [📋 Audit log]                 │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│  👤 ivan                        │
│                                 │
│  📍 VPN IP: 10.66.66.3          │
│  📶 Status: 🟢 Online           │
│  🤝 Handshake: 2026-03-03 18:22 │
│  📥 Rx: 142.3 MB                │
│  📤 Tx: 23.1 MB                 │
│  ⏱ Access: until 2026-03-10    │
│                                 │
│  [📄 .conf]  [📱 QR code]      │
│  [⛔ Disable]  [🔑 Rotate]     │
│  [⏱ Access period]  [🗑 Delete]│
└─────────────────────────────────┘
```

---

## Features

### 👥 Client management
- Add a client — enter `@username` or just a name
- Delete a client with confirmation
- Enable / disable without deleting
- Statistics: Rx/Tx traffic, exact last handshake time, IP

### ⏱ Temporary access
- Grant access for **1 / 7 / 30 days** or make it permanent
- When the period expires the peer is **automatically disabled** and a Telegram notification is sent

### 📱 Client connection
- Download a ready-made `.conf` file with one button
- QR code for mobile devices (iOS/Android)
- Configs are compatible with [AmneziaVPN](https://amnezia.org/en/downloads)
- AmneziaWG junk parameters are added automatically

### 🔑 Key rotation
- Regenerate client keys without changing the IP
- New `.conf` and QR code are sent automatically

### 💾 Backup
- **💾 Backup** button — sends `awg0.conf` with a timestamp directly to Telegram

### 📊 Server monitoring
- CPU, RAM, disk usage in real time
- Number of active clients (by handshake < 3 min)
- Load average, uptime

### 🔔 Automatic notifications

| Event | Alert |
|-------|-------|
| `awg0` interface went down | 🔴 + "Restart" button |
| `awg0` interface came back up | 🟢 |
| CPU > 80% | 🔴 CPU alert |
| RAM > 90% | 🔴 RAM alert |
| Client connected | 🔔 name + IP |
| Access period expired | ⏱ client auto-disabled |

### 📋 Audit log
- All actions are written to `/var/log/awg-bot-audit.log`
- View the last 30 entries directly in the bot

---

## Requirements

- Ubuntu 20.04+ / Debian 11+
- Python 3.10+
- [AmneziaWG](https://github.com/amnezia-vpn/amneziawg-linux-kernel-module) installed with the `awg0` interface up
- `qrencode` (for QR codes — the deploy script installs it automatically)
- Telegram Bot Token from [@BotFather](https://t.me/BotFather)

---

## Installation

### 1. Create a bot

1. Message [@BotFather](https://t.me/BotFather) → `/newbot`
2. Copy the token in the format `1234567890:AAH...`

### 2. Find your Telegram ID

Message [@userinfobot](https://t.me/userinfobot) — it will reply with your numeric ID.

### 3. Create the config on the server

```bash
mkdir -p /etc/awg-bot/clients

cat > /etc/awg-bot/config.json << 'EOF'
{
  "bot_token": "YOUR_TOKEN_FROM_BOTFATHER",
  "admin_ids": [YOUR_TELEGRAM_ID],
  "server_ip": "YOUR_SERVER_IP",
  "server_vpn_ip": "10.66.66.1",
  "vpn_subnet": "10.66.66.0/24",
  "dns": "1.1.1.1"
}
EOF

chmod 600 /etc/awg-bot/config.json
```

> `admin_ids` — only these Telegram User IDs will have access. Everyone else will see `⛔ Access denied`.

### 4. Deploy

```bash
git clone https://github.com/YOUR_USERNAME/awg-bot.git
cd awg-bot
chmod +x deploy.sh
./deploy.sh
```

The script automatically:
- Installs `python3-venv` and `qrencode`
- Creates a virtualenv at `/opt/awg-bot/venv/`
- Installs `python-telegram-bot`
- Creates and starts the `awg-bot` systemd service

### 5. Verify

```bash
systemctl status awg-bot
tail -f /var/log/awg-bot.log
```

Open the bot in Telegram → `/start`

---

## Manual installation (without the script)

```bash
# Dependencies
apt-get install -y python3-venv qrencode

# Copy the code
mkdir -p /opt/awg-bot
cp bot.py /opt/awg-bot/

# Virtualenv
python3 -m venv /opt/awg-bot/venv
/opt/awg-bot/venv/bin/pip install "python-telegram-bot>=21.0"

# Systemd service
cat > /etc/systemd/system/awg-bot.service << 'EOF'
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
EOF

systemctl daemon-reload
systemctl enable --now awg-bot
```

---

## Configuration

| Key | Description | Example |
|-----|-------------|---------|
| `bot_token` | Token from BotFather | `"1234567890:AAH..."` |
| `admin_ids` | List of Telegram IDs with access | `[123456789]` |
| `server_ip` | Public IP of the server | `"1.2.3.4"` |
| `server_vpn_ip` | Server IP inside the VPN network | `"10.66.66.1"` |
| `vpn_subnet` | VPN subnet | `"10.66.66.0/24"` |
| `dns` | DNS for clients | `"1.1.1.1"` |

An example is provided in `config.example.json`.

---

## File structure

### Project

```
awg-bot/
├── bot.py                # Main bot code
├── requirements.txt      # Python dependencies
├── deploy.sh             # Deploy script
├── config.example.json   # Example config (no secrets)
├── .gitignore
└── README.md
```

### On the server

```
/opt/awg-bot/
├── bot.py
└── venv/

/etc/awg-bot/
├── config.json         # ⚠️ Secret — do not commit!
├── peers.json          # Client database (auto-generated)
└── clients/
    ├── alice.conf
    └── bob.conf

/var/log/
├── awg-bot.log         # Process log
└── awg-bot-audit.log   # Audit log
```

---

## Management

```bash
# Status
systemctl status awg-bot

# Restart
systemctl restart awg-bot

# Logs
tail -f /var/log/awg-bot.log

# Audit log
tail -f /var/log/awg-bot-audit.log

# Update the bot
scp bot.py root@SERVER:/opt/awg-bot/bot.py
ssh root@SERVER 'systemctl restart awg-bot'
```

---

## AmneziaWG

The bot is built for [AmneziaWG](https://github.com/amnezia-vpn/amneziawg-linux-kernel-module) — a WireGuard fork with junk parameters (`Jc`, `Jmin`, `Jmax`, `S1`, `S2`, `H1`–`H4`) for bypassing DPI inspection.

The bot reads junk parameters **automatically** from `/etc/amnezia/amneziawg/awg0.conf` and inserts them into the generated client configs.

Client application: [AmneziaVPN](https://amnezia.org/en/downloads) — iOS, Android, Windows, macOS, Linux.

---

## Security

- Access is controlled by numeric Telegram User ID (not by username)
- The config containing the token is stored at `/etc/awg-bot/config.json` with `600` permissions
- Destructive actions (delete, restart, key rotation) require a confirmation button
- All actions are recorded in the audit log with a timestamp and user_id

---

## License

MIT
