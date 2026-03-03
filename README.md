# awg-bot 🛡

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
