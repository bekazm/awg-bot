#!/usr/bin/env python3
"""
AmneziaWG Telegram Bot
Фичи: кнопки, временные конфиги, backup, audit log, CPU/RAM алёрты,
       уведомления о новых подключениях, ротация ключей
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ─── Пути ─────────────────────────────────────────────────────────────────────

CONFIG_FILE = Path("/etc/awg-bot/config.json")
PEERS_FILE  = Path("/etc/awg-bot/peers.json")
CLIENTS_DIR = Path("/etc/awg-bot/clients")
AWG_CONF    = Path("/etc/amnezia/amneziawg/awg0.conf")
AUDIT_FILE  = Path("/var/log/awg-bot-audit.log")
INTERFACE   = "awg0"
SERVER_PORT = 51820

# ─── Логирование ──────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("/var/log/awg-bot.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ─── Конфиг ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)

def load_peers() -> dict:
    if PEERS_FILE.exists():
        with open(PEERS_FILE) as f:
            return json.load(f)
    return {}

def save_peers(peers: dict):
    with open(PEERS_FILE, "w") as f:
        json.dump(peers, f, indent=2, ensure_ascii=False)

CFG             = load_config()
ADMIN_IDS: set[int] = set(CFG.get("admin_ids", []))
BOT_TOKEN: str  = CFG["bot_token"]
SERVER_IP: str  = CFG.get("server_ip", "YOUR_SERVER_IP")
SERVER_VPN_IP: str = CFG.get("server_vpn_ip", "10.66.66.1")
DNS: str        = CFG.get("dns", "1.1.1.1")

def get_junk_params() -> dict:
    params = {"Jc": "4", "Jmin": "40", "Jmax": "70", "S1": "0", "S2": "0",
              "H1": "4665", "H2": "19774", "H3": "17391", "H4": "14857"}
    try:
        conf = AWG_CONF.read_text()
        for k in params:
            m = re.search(rf'^{k}\s*=\s*(.+)', conf, re.MULTILINE)
            if m:
                params[k] = m.group(1).strip()
    except Exception:
        pass
    return params

# ─── Audit log ────────────────────────────────────────────────────────────────

def audit(user_id: int, action: str, details: str = ""):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}  uid={user_id}  {action}"
    if details:
        line += f"  {details}"
    try:
        with open(AUDIT_FILE, "a") as f:
            f.write(line + "\n")
    except Exception as e:
        log.error(f"audit write error: {e}")

# ─── Хелперы ──────────────────────────────────────────────────────────────────

def run(cmd: str | list, capture=True, timeout=15) -> tuple[int, str]:
    if isinstance(cmd, str):
        cmd = cmd.split()
    r = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()

def is_admin(update: Update) -> bool:
    return update.effective_user.id in ADMIN_IDS

async def deny(update: Update):
    await update.effective_message.reply_text("⛔ Нет доступа.")

def human_bytes(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"

def ago(ts: int) -> str:
    if not ts:
        return "никогда"
    diff = int(time.time()) - ts
    if diff < 60:    return f"{diff}с назад"
    if diff < 3600:  return f"{diff // 60}м назад"
    if diff < 86400: return f"{diff // 3600}ч назад"
    return f"{diff // 86400}д назад"

def fmt_ts(ts: int) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")

def fmt_expires(expires_str: str | None) -> str:
    if not expires_str:
        return "♾ Бессрочно"
    try:
        exp = datetime.fromisoformat(expires_str)
        now = datetime.now()
        if exp < now:
            return f"⛔ Истёк ({exp.strftime('%Y-%m-%d %H:%M')})"
        diff = exp - now
        days = diff.days
        hours = diff.seconds // 3600
        if days > 0:
            return f"⏱ {exp.strftime('%Y-%m-%d %H:%M')} (осталось {days}д)"
        return f"⏱ {exp.strftime('%Y-%m-%d %H:%M')} (осталось {hours}ч)"
    except Exception:
        return expires_str

def next_vpn_ip(peers: dict) -> str:
    used = set()
    for p in peers.values():
        ip = p.get("ip", "").split("/")[0]
        if ip:
            used.add(int(ip.split(".")[-1]))
    base   = int(SERVER_VPN_IP.split(".")[-1])
    prefix = ".".join(SERVER_VPN_IP.split(".")[:3])
    for i in range(2, 255):
        if i != base and i not in used:
            return f"{prefix}.{i}"
    raise ValueError("Нет свободных IP")

# ─── AWG операции ─────────────────────────────────────────────────────────────

def parse_awg_show() -> dict:
    code, out = run(f"awg show {INTERFACE} dump")
    if code != 0:
        return {}
    result = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 6 or parts[0] == "private":
            continue
        pubkey = parts[0]
        result[pubkey] = {
            "endpoint":       parts[2] if parts[2] != "(none)" else None,
            "allowed_ips":    parts[3],
            "last_handshake": int(parts[4]) if parts[4].isdigit() else 0,
            "rx":             int(parts[5]) if parts[5].isdigit() else 0,
            "tx":             int(parts[6]) if len(parts) > 6 and parts[6].isdigit() else 0,
        }
    return result

def get_server_pubkey() -> str:
    code, out = run(f"awg show {INTERFACE} public-key")
    return out.strip() if code == 0 else ""

def gen_keys() -> tuple[str, str, str]:
    _, priv = run("awg genkey")
    _, pub  = run(["sh", "-c", f"echo '{priv}' | awg pubkey"])
    _, psk  = run("awg genpsk")
    return priv.strip(), pub.strip(), psk.strip()

def add_peer_to_awg(pubkey: str, psk: str, ip: str) -> bool:
    cmd  = ["awg", "set", INTERFACE, "peer", pubkey,
            "preshared-key", "/dev/stdin", "allowed-ips", f"{ip}/32"]
    proc = subprocess.run(cmd, input=psk, capture_output=True, text=True)
    if proc.returncode != 0:
        log.error(f"awg set failed: {proc.stderr}")
        return False
    run(f"awg-quick save {INTERFACE}")
    return True

def remove_peer_from_awg(pubkey: str) -> bool:
    code, _ = run(f"awg set {INTERFACE} peer {pubkey} remove")
    run(f"awg-quick save {INTERFACE}")
    return code == 0

def disable_peer(pubkey: str) -> bool:
    code, _ = run(f"awg set {INTERFACE} peer {pubkey} allowed-ips 0.0.0.0/32")
    run(f"awg-quick save {INTERFACE}")
    return code == 0

def enable_peer(pubkey: str, ip: str) -> bool:
    code, _ = run(f"awg set {INTERFACE} peer {pubkey} allowed-ips {ip}/32")
    run(f"awg-quick save {INTERFACE}")
    return code == 0

# ─── Генерация конфига ────────────────────────────────────────────────────────

def make_client_conf(name: str, privkey: str, psk: str, client_ip: str) -> str:
    server_pubkey = get_server_pubkey()
    jp = get_junk_params()
    return (
        f"[Interface]\n"
        f"PrivateKey = {privkey}\n"
        f"Address = {client_ip}/24\n"
        f"DNS = {DNS}\n"
        f"Jc={jp['Jc']} Jmin={jp['Jmin']} Jmax={jp['Jmax']} "
        f"S1={jp['S1']} S2={jp['S2']}\n"
        f"H1={jp['H1']} H2={jp['H2']} H3={jp['H3']} H4={jp['H4']}\n\n"
        f"[Peer]\n"
        f"PublicKey = {server_pubkey}\n"
        f"PresharedKey = {psk}\n"
        f"Endpoint = {SERVER_IP}:{SERVER_PORT}\n"
        f"AllowedIPs = 0.0.0.0/0, ::/0\n"
        f"PersistentKeepalive = 25\n"
    )

def make_qr_image(conf_text: str) -> bytes | None:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
    code, _ = run(["qrencode", "-o", tmp_path, "-t", "PNG", "-s", "8", conf_text])
    if code != 0:
        return None
    data = Path(tmp_path).read_bytes()
    os.unlink(tmp_path)
    return data

# ─── Состояние для уведомлений ────────────────────────────────────────────────

# pubkey → последний known last_handshake
_prev_handshakes: dict[str, int] = {}
# флаги для избежания спама алёртов CPU/RAM
_cpu_alert_sent  = False
_ram_alert_sent  = False
_iface_up        = True

# ─── Клавиатуры ───────────────────────────────────────────────────────────────

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статус сервера",      callback_data="menu:status")],
        [
            InlineKeyboardButton("👥 Клиенты",          callback_data="menu:peers"),
            InlineKeyboardButton("➕ Добавить",          callback_data="menu:add"),
        ],
        [
            InlineKeyboardButton("💾 Бэкап конфига",    callback_data="menu:backup"),
            InlineKeyboardButton("🔄 Рестарт awg0",     callback_data="menu:restart"),
        ],
        [InlineKeyboardButton("📋 Audit log",            callback_data="menu:auditlog")],
    ])

def back_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("« Главное меню", callback_data="back:menu"),
    ]])

def status_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Обновить", callback_data="menu:status"),
        InlineKeyboardButton("« Меню",      callback_data="back:menu"),
    ]])

def peers_list_kb(peers: dict) -> InlineKeyboardMarkup:
    awg_data = parse_awg_show()
    rows = []
    for name, info in sorted(peers.items()):
        pubkey  = info.get("pubkey", "")
        stats   = awg_data.get(pubkey, {})
        last_hs = stats.get("last_handshake", 0)
        allowed = stats.get("allowed_ips", "")
        expires = info.get("expires")
        if expires and datetime.fromisoformat(expires) < datetime.now():
            icon = "⛔"
        elif last_hs and (time.time() - last_hs) < 180:
            icon = "🟢"
        elif allowed == "0.0.0.0/32":
            icon = "⛔"
        elif last_hs:
            icon = "🟡"
        else:
            icon = "⚪"
        rows.append([InlineKeyboardButton(
            f"{icon} {name}", callback_data=f"peer:view:{name}"
        )])
    rows.append([
        InlineKeyboardButton("➕ Добавить", callback_data="menu:add"),
        InlineKeyboardButton("« Меню",     callback_data="back:menu"),
    ])
    return InlineKeyboardMarkup(rows)

def peer_actions_kb(name: str, disabled: bool) -> InlineKeyboardMarkup:
    toggle_lbl = "✅ Включить" if disabled else "⛔ Отключить"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📄 .conf",      callback_data=f"peer:config:{name}"),
            InlineKeyboardButton("📱 QR-код",     callback_data=f"peer:qr:{name}"),
        ],
        [
            InlineKeyboardButton(toggle_lbl,      callback_data=f"peer:toggle:{name}"),
            InlineKeyboardButton("🔑 Ротация",    callback_data=f"peer:rotate:{name}"),
        ],
        [
            InlineKeyboardButton("⏱ Срок доступа", callback_data=f"peer:expire:{name}"),
        ],
        [
            InlineKeyboardButton("🗑 Удалить",    callback_data=f"peer:remove:{name}"),
        ],
        [
            InlineKeyboardButton("« К клиентам",  callback_data="back:peers"),
            InlineKeyboardButton("« Меню",        callback_data="back:menu"),
        ],
    ])

def expire_kb(name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1 день",   callback_data=f"expire:set:{name}:1"),
            InlineKeyboardButton("7 дней",   callback_data=f"expire:set:{name}:7"),
            InlineKeyboardButton("30 дней",  callback_data=f"expire:set:{name}:30"),
        ],
        [
            InlineKeyboardButton("♾ Бессрочно", callback_data=f"expire:set:{name}:0"),
        ],
        [
            InlineKeyboardButton("« Назад", callback_data=f"peer:view:{name}"),
        ],
    ])

def cancel_add_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Отмена", callback_data="back:menu"),
    ]])

def after_add_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("« К клиентам", callback_data="back:peers"),
        InlineKeyboardButton("« Меню",       callback_data="back:menu"),
    ]])

# ─── Тексты ───────────────────────────────────────────────────────────────────

def build_status_text() -> str:
    _, iface = run(f"ip link show {INTERFACE}")
    is_up = "UP" in iface and "NO-CARRIER" not in iface

    _, meminfo = run("free -m")
    mem: dict = {}
    for line in meminfo.splitlines():
        if line.startswith("Mem:"):
            p   = line.split()
            mem = {"total": int(p[1]), "used": int(p[2])}

    ram_pct = int(mem.get("used", 0) / max(mem.get("total", 1), 1) * 100)

    _, disk = run("df -h /")
    dl   = disk.splitlines()[-1].split()
    disk_info = f"{dl[2]} / {dl[1]} ({dl[4]})"

    _, uptime = run("uptime -p")
    _, load   = run("cat /proc/loadavg")
    load_vals = load.split()
    load_1    = load_vals[0]

    awg_data  = parse_awg_show()
    active    = sum(1 for p in awg_data.values() if p["last_handshake"] > time.time() - 180)
    total_rx  = sum(p["rx"] for p in awg_data.values())
    total_tx  = sum(p["tx"] for p in awg_data.values())

    # CPU: используем /proc/stat для расчёта
    try:
        _, stat1 = run("cat /proc/stat")
        cpu_line = stat1.splitlines()[0].split()
        idle1, total1 = int(cpu_line[4]), sum(int(x) for x in cpu_line[1:])
        time.sleep(0.2)
        _, stat2 = run("cat /proc/stat")
        cpu_line2 = stat2.splitlines()[0].split()
        idle2, total2 = int(cpu_line2[4]), sum(int(x) for x in cpu_line2[1:])
        cpu_pct = round(100 * (1 - (idle2 - idle1) / max(total2 - total1, 1)))
    except Exception:
        cpu_pct = 0

    cpu_icon = "🔴" if cpu_pct > 80 else ("🟡" if cpu_pct > 50 else "🟢")
    ram_icon = "🔴" if ram_pct > 90 else ("🟡" if ram_pct > 70 else "🟢")
    iface_icon = "🟢" if is_up else "🔴"

    peers    = load_peers()
    expired  = sum(1 for p in peers.values()
                   if p.get("expires") and
                   datetime.fromisoformat(p["expires"]) < datetime.now())

    return (
        f"{iface_icon} *AmneziaWG сервер*\n\n"
        f"🔌 Интерфейс: `{INTERFACE}` {'UP' if is_up else 'DOWN'}\n"
        f"🌐 Порт: `{SERVER_PORT}/UDP`\n"
        f"👥 Активных: `{active}` / `{len(awg_data)}`"
        + (f" · ⛔ Истёкших: `{expired}`" if expired else "") + "\n\n"
        f"📥 Rx: `{human_bytes(total_rx)}`\n"
        f"📤 Tx: `{human_bytes(total_tx)}`\n\n"
        f"{cpu_icon} CPU: `{cpu_pct}%`\n"
        f"{ram_icon} RAM: `{mem.get('used',0)}/{mem.get('total',0)} MB` ({ram_pct}%)\n"
        f"💿 Диск: `{disk_info}`\n"
        f"⚡ Load: `{load_1}`\n"
        f"⏱ Uptime: `{uptime.replace('up ', '')}`\n"
    )

def build_peers_text(peers: dict, awg_data: dict) -> str:
    if not peers:
        return "👥 *Клиентов нет*\n\nНажми ➕ Добавить."
    lines = [f"👥 *Клиенты* ({len(peers)}):\n"]
    for name, info in sorted(peers.items()):
        pubkey  = info.get("pubkey", "")
        ip      = info.get("ip", "?")
        stats   = awg_data.get(pubkey, {})
        last_hs = stats.get("last_handshake", 0)
        rx      = stats.get("rx", 0)
        tx      = stats.get("tx", 0)
        allowed = stats.get("allowed_ips", "")
        expires = info.get("expires")

        expired = expires and datetime.fromisoformat(expires) < datetime.now()

        if expired or allowed == "0.0.0.0/32":
            icon = "⛔"
        elif last_hs and (time.time() - last_hs) < 180:
            icon = "🟢"
        elif last_hs:
            icon = "🟡"
        else:
            icon = "⚪"

        exp_str = f" · ⏱ до {datetime.fromisoformat(expires).strftime('%m-%d')}" if expires and not expired else ""
        lines.append(
            f"{icon} *{name}* `{ip}`{exp_str}\n"
            f"   {ago(last_hs)} · 📥 {human_bytes(rx)} · 📤 {human_bytes(tx)}"
        )
    return "\n".join(lines)

def build_peer_detail(name: str, info: dict, stats: dict) -> str:
    ip       = info.get("ip", "?")
    created  = info.get("created", "?")
    expires  = info.get("expires")
    last_hs  = stats.get("last_handshake", 0)
    rx       = stats.get("rx", 0)
    tx       = stats.get("tx", 0)
    endpoint = stats.get("endpoint")
    allowed  = stats.get("allowed_ips", "")

    expired = expires and datetime.fromisoformat(expires) < datetime.now()

    if expired or allowed == "0.0.0.0/32":
        status = "⛔ Отключён" + (" (истёк)" if expired else "")
    elif last_hs and (time.time() - last_hs) < 180:
        status = "🟢 Онлайн"
    elif last_hs:
        status = f"🟡 Виден {ago(last_hs)}"
    else:
        status = "⚪ Никогда не подключался"

    text = (
        f"👤 *{name}*\n\n"
        f"📍 VPN IP: `{ip}`\n"
        f"📶 Статус: {status}\n"
        f"🤝 Handshake: `{fmt_ts(last_hs)}`\n"
        f"📥 Rx: `{human_bytes(rx)}`\n"
        f"📤 Tx: `{human_bytes(tx)}`\n"
        f"📅 Создан: `{created}`\n"
        f"⏱ Доступ: {fmt_expires(expires)}\n"
    )
    if endpoint:
        text += f"🌍 `{endpoint}`\n"
    return text

# ─── /start  ──────────────────────────────────────────────────────────────────

async def show_main_menu(message: Message, edit: bool = False):
    text = "🛡 *AmneziaWG Bot*\nВыбери действие:"
    if edit:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())
    else:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await deny(update)
    ctx.user_data.pop("waiting_add", None)
    audit(update.effective_user.id, "start")
    await show_main_menu(update.message)

# ─── Callbacks ────────────────────────────────────────────────────────────────

async def cb_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    data    = query.data
    user_id = update.effective_user.id

    if not is_admin(update):
        await query.edit_message_text("⛔ Нет доступа.")
        return

    # ── back ──────────────────────────────────────────────────────────────────
    if data == "back:menu":
        ctx.user_data.pop("waiting_add", None)
        await show_main_menu(query.message, edit=True)
        return

    if data == "back:peers":
        peers    = load_peers()
        awg_data = parse_awg_show()
        await query.edit_message_text(
            build_peers_text(peers, awg_data),
            parse_mode="Markdown",
            reply_markup=peers_list_kb(peers),
        )
        return

    # ── status ────────────────────────────────────────────────────────────────
    if data == "menu:status":
        await query.edit_message_text(
            build_status_text(), parse_mode="Markdown", reply_markup=status_kb()
        )
        return

    # ── peers ─────────────────────────────────────────────────────────────────
    if data == "menu:peers":
        peers    = load_peers()
        awg_data = parse_awg_show()
        await query.edit_message_text(
            build_peers_text(peers, awg_data),
            parse_mode="Markdown",
            reply_markup=peers_list_kb(peers),
        )
        return

    # ── add ───────────────────────────────────────────────────────────────────
    if data == "menu:add":
        ctx.user_data["waiting_add"] = True
        await query.edit_message_text(
            "✏️ *Введи имя нового клиента:*\n\nМожно написать @никнейм или просто имя.",
            parse_mode="Markdown",
            reply_markup=cancel_add_kb(),
        )
        return

    # ── backup ────────────────────────────────────────────────────────────────
    if data == "menu:backup":
        audit(user_id, "backup")
        if not AWG_CONF.exists():
            await query.answer("❌ Файл конфига не найден", show_alert=True)
            return
        ts       = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"awg0_backup_{ts}.conf"
        await query.message.reply_document(
            document=AWG_CONF.open("rb"),
            filename=filename,
            caption=f"💾 Бэкап `{INTERFACE}` · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="Markdown",
        )
        await query.answer("💾 Бэкап отправлен")
        return

    # ── audit log ─────────────────────────────────────────────────────────────
    if data == "menu:auditlog":
        audit(user_id, "view_auditlog")
        try:
            lines = AUDIT_FILE.read_text().splitlines()
            last  = lines[-30:] if len(lines) > 30 else lines
            text  = "📋 *Audit log (последние 30 записей):*\n\n```\n" + "\n".join(last) + "\n```"
        except FileNotFoundError:
            text = "📋 Audit log пуст."
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=back_menu_kb()
        )
        return

    # ── restart ───────────────────────────────────────────────────────────────
    if data == "menu:restart":
        await query.edit_message_text(
            f"⚠️ Перезапустить `{INTERFACE}`?\nVPN клиенты отключатся на ~5 сек.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Да", callback_data="restart:confirm"),
                InlineKeyboardButton("❌ Отмена", callback_data="back:menu"),
            ]]),
        )
        return

    if data == "restart:confirm":
        audit(user_id, "restart", INTERFACE)
        await query.edit_message_text("⏳ Перезапускаю...")
        run(f"awg-quick down {INTERFACE}")
        await asyncio.sleep(2)
        code, out = run(f"awg-quick up {INTERFACE}")
        if code == 0:
            await query.edit_message_text(
                f"✅ `{INTERFACE}` перезапущен.", parse_mode="Markdown",
                reply_markup=back_menu_kb()
            )
        else:
            await query.edit_message_text(
                f"❌ Ошибка:\n```{out[:300]}```", parse_mode="Markdown",
                reply_markup=back_menu_kb()
            )
        return

    # ── peer:view ─────────────────────────────────────────────────────────────
    if data.startswith("peer:view:"):
        name     = data[len("peer:view:"):]
        peers    = load_peers()
        awg_data = parse_awg_show()
        if name not in peers:
            await query.edit_message_text("❌ Клиент не найден.", reply_markup=back_menu_kb())
            return
        info     = peers[name]
        stats    = awg_data.get(info["pubkey"], {})
        allowed  = stats.get("allowed_ips", "")
        expires  = info.get("expires")
        expired  = expires and datetime.fromisoformat(expires) < datetime.now()
        disabled = allowed == "0.0.0.0/32" or bool(expired)
        await query.edit_message_text(
            build_peer_detail(name, info, stats),
            parse_mode="Markdown",
            reply_markup=peer_actions_kb(name, disabled),
        )
        return

    # ── peer:config ───────────────────────────────────────────────────────────
    if data.startswith("peer:config:"):
        name  = data[len("peer:config:"):]
        peers = load_peers()
        if name not in peers:
            await query.answer("❌ Клиент не найден", show_alert=True)
            return
        audit(user_id, "get_config", name)
        p         = peers[name]
        conf_path = CLIENTS_DIR / f"{name}.conf"
        if not conf_path.exists():
            conf_path.write_text(make_client_conf(name, p["privkey"], p["psk"], p["ip"]))
        await query.message.reply_document(
            document=conf_path.open("rb"),
            filename=f"{name}.conf",
            caption=f"📄 Конфиг *{name}*",
            parse_mode="Markdown",
        )
        await query.answer("📄 Конфиг отправлен")
        return

    # ── peer:qr ───────────────────────────────────────────────────────────────
    if data.startswith("peer:qr:"):
        name  = data[len("peer:qr:"):]
        peers = load_peers()
        if name not in peers:
            await query.answer("❌ Клиент не найден", show_alert=True)
            return
        audit(user_id, "get_qr", name)
        p         = peers[name]
        conf_text = make_client_conf(name, p["privkey"], p["psk"], p["ip"])
        qr_data   = make_qr_image(conf_text)
        if not qr_data:
            await query.answer("❌ Ошибка генерации QR (установлен qrencode?)", show_alert=True)
            return
        await query.message.reply_photo(
            photo=qr_data, caption=f"📱 QR для *{name}*", parse_mode="Markdown"
        )
        await query.answer("📱 QR отправлен")
        return

    # ── peer:toggle ───────────────────────────────────────────────────────────
    if data.startswith("peer:toggle:"):
        name     = data[len("peer:toggle:"):]
        peers    = load_peers()
        awg_data = parse_awg_show()
        if name not in peers:
            await query.answer("❌ Клиент не найден", show_alert=True)
            return
        info     = peers[name]
        pubkey   = info["pubkey"]
        ip       = info["ip"]
        allowed  = awg_data.get(pubkey, {}).get("allowed_ips", f"{ip}/32")
        disabled = allowed == "0.0.0.0/32"

        if disabled:
            ok           = enable_peer(pubkey, ip)
            new_disabled = False
            alert_text   = f"✅ {name} включён"
            audit(user_id, "enable_peer", name)
        else:
            ok           = disable_peer(pubkey)
            new_disabled = True
            alert_text   = f"⛔ {name} отключён"
            audit(user_id, "disable_peer", name)

        if not ok:
            await query.answer("❌ Ошибка операции", show_alert=True)
            return

        fresh = parse_awg_show().get(pubkey, {})
        await query.edit_message_text(
            build_peer_detail(name, info, fresh),
            parse_mode="Markdown",
            reply_markup=peer_actions_kb(name, new_disabled),
        )
        await query.answer(alert_text)
        return

    # ── peer:expire ───────────────────────────────────────────────────────────
    if data.startswith("peer:expire:"):
        name  = data[len("peer:expire:"):]
        peers = load_peers()
        if name not in peers:
            await query.answer("❌ Клиент не найден", show_alert=True)
            return
        expires = peers[name].get("expires")
        await query.edit_message_text(
            f"⏱ *Срок доступа: {name}*\n\nСейчас: {fmt_expires(expires)}\n\nВыбери новый срок:",
            parse_mode="Markdown",
            reply_markup=expire_kb(name),
        )
        return

    # ── expire:set ────────────────────────────────────────────────────────────
    if data.startswith("expire:set:"):
        parts = data.split(":")
        name  = parts[2]
        days  = int(parts[3])
        peers = load_peers()
        if name not in peers:
            await query.answer("❌ Клиент не найден", show_alert=True)
            return

        pubkey = peers[name]["pubkey"]
        ip     = peers[name]["ip"]

        if days == 0:
            peers[name]["expires"] = None
            enable_peer(pubkey, ip)
            label = "♾ Бессрочно"
            audit(user_id, "set_expire", f"{name} -> permanent")
        else:
            exp = datetime.now() + timedelta(days=days)
            peers[name]["expires"] = exp.isoformat(timespec="minutes")
            enable_peer(pubkey, ip)
            label = exp.strftime("%Y-%m-%d %H:%M")
            audit(user_id, "set_expire", f"{name} -> {label}")

        save_peers(peers)

        fresh   = parse_awg_show().get(pubkey, {})
        allowed = fresh.get("allowed_ips", "")
        await query.edit_message_text(
            build_peer_detail(name, peers[name], fresh),
            parse_mode="Markdown",
            reply_markup=peer_actions_kb(name, allowed == "0.0.0.0/32"),
        )
        await query.answer(f"✅ Срок доступа: {label}")
        return

    # ── peer:rotate ───────────────────────────────────────────────────────────
    if data.startswith("peer:rotate:"):
        name = data[len("peer:rotate:"):]
        await query.edit_message_text(
            f"🔑 *Ротация ключей: {name}*\n\nСтарые ключи будут удалены. Клиенту нужен новый конфиг.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔑 Да, обновить",  callback_data=f"rotate:confirm:{name}"),
                InlineKeyboardButton("❌ Отмена",         callback_data=f"peer:view:{name}"),
            ]]),
        )
        return

    if data.startswith("rotate:confirm:"):
        name  = data[len("rotate:confirm:"):]
        peers = load_peers()
        if name not in peers:
            await query.edit_message_text("❌ Клиент не найден.", reply_markup=back_menu_kb())
            return
        await query.edit_message_text(f"⏳ Обновляю ключи *{name}*...", parse_mode="Markdown")
        audit(user_id, "rotate_keys", name)
        try:
            old_pubkey = peers[name]["pubkey"]
            ip         = peers[name]["ip"]
            remove_peer_from_awg(old_pubkey)
            privkey, pubkey, psk = gen_keys()
            ok = add_peer_to_awg(pubkey, psk, ip)
            if not ok:
                await query.edit_message_text("❌ Ошибка.", reply_markup=back_menu_kb())
                return
            peers[name].update({"pubkey": pubkey, "privkey": privkey, "psk": psk})
            save_peers(peers)
            conf_text = make_client_conf(name, privkey, psk, ip)
            conf_path = CLIENTS_DIR / f"{name}.conf"
            conf_path.write_text(conf_text)
            await query.edit_message_text(
                f"✅ Ключи *{name}* обновлены · `{ip}`", parse_mode="Markdown"
            )
            await query.message.reply_document(
                document=conf_path.open("rb"),
                filename=f"{name}.conf",
                caption=f"📄 Новый конфиг *{name}*",
                parse_mode="Markdown",
            )
            qr_data = make_qr_image(conf_text)
            if qr_data:
                await query.message.reply_photo(
                    photo=qr_data, caption=f"📱 Новый QR для *{name}*",
                    parse_mode="Markdown", reply_markup=after_add_kb()
                )
        except Exception as e:
            log.exception("rotate error")
            await query.edit_message_text(f"❌ Ошибка: {e}", reply_markup=back_menu_kb())
        return

    # ── peer:remove ───────────────────────────────────────────────────────────
    if data.startswith("peer:remove:"):
        name = data[len("peer:remove:"):]
        await query.edit_message_text(
            f"⚠️ *Удалить клиента {name}?*\nОтменить нельзя.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🗑 Да, удалить", callback_data=f"remove:confirm:{name}"),
                InlineKeyboardButton("❌ Отмена",      callback_data=f"peer:view:{name}"),
            ]]),
        )
        return

    if data.startswith("remove:confirm:"):
        name  = data[len("remove:confirm:"):]
        peers = load_peers()
        if name not in peers:
            await query.edit_message_text("❌ Клиент не найден.", reply_markup=back_menu_kb())
            return
        audit(user_id, "remove_peer", name)
        pubkey    = peers[name]["pubkey"]
        ok        = remove_peer_from_awg(pubkey)
        conf_path = CLIENTS_DIR / f"{name}.conf"
        if conf_path.exists():
            conf_path.unlink()
        del peers[name]
        save_peers(peers)
        await query.edit_message_text(
            f"{'✅' if ok else '⚠️'} Клиент *{name}* удалён.",
            parse_mode="Markdown", reply_markup=back_menu_kb()
        )
        return

# ─── Текстовый обработчик — ввод имени клиента ────────────────────────────────

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    if not ctx.user_data.get("waiting_add"):
        await update.message.reply_text("Отправь /start для главного меню.")
        return

    name = update.message.text.strip().lstrip("@").lower()

    if not re.match(r'^[a-z0-9_-]{1,32}$', name):
        await update.message.reply_text(
            "❌ Только латиница, цифры, дефис, подчёркивание (макс 32 символа).\nПопробуй ещё:",
            reply_markup=cancel_add_kb(),
        )
        return

    peers = load_peers()
    if name in peers:
        await update.message.reply_text(
            f"❌ Клиент `{name}` уже существует.",
            parse_mode="Markdown",
            reply_markup=cancel_add_kb(),
        )
        return

    ctx.user_data.pop("waiting_add", None)
    msg = await update.message.reply_text(f"⏳ Создаю *{name}*...", parse_mode="Markdown")

    try:
        client_ip            = next_vpn_ip(peers)
        privkey, pubkey, psk = gen_keys()
        ok                   = add_peer_to_awg(pubkey, psk, client_ip)
        if not ok:
            await msg.edit_text("❌ Ошибка добавления.", reply_markup=back_menu_kb())
            return

        peers[name] = {
            "pubkey":  pubkey,
            "privkey": privkey,
            "psk":     psk,
            "ip":      client_ip,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "expires": None,
        }
        save_peers(peers)
        audit(update.effective_user.id, "add_peer", f"{name} ip={client_ip}")

        conf_text = make_client_conf(name, privkey, psk, client_ip)
        conf_path = CLIENTS_DIR / f"{name}.conf"
        CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
        conf_path.write_text(conf_text)

        await msg.edit_text(f"✅ *{name}* создан · `{client_ip}`", parse_mode="Markdown")

        await update.message.reply_document(
            document=conf_path.open("rb"),
            filename=f"{name}.conf",
            caption=f"📄 Конфиг *{name}*",
            parse_mode="Markdown",
        )
        qr_data = make_qr_image(conf_text)
        if qr_data:
            await update.message.reply_photo(
                photo=qr_data,
                caption=f"📱 QR-код для *{name}*",
                parse_mode="Markdown",
                reply_markup=after_add_kb(),
            )
        else:
            await update.message.reply_text("✅ Готово!", reply_markup=after_add_kb())

    except Exception as e:
        log.exception("add_peer error")
        await msg.edit_text(f"❌ Ошибка: {e}", reply_markup=back_menu_kb())

# ─── Монитор ──────────────────────────────────────────────────────────────────

async def monitor_loop(app: Application):
    global _cpu_alert_sent, _ram_alert_sent, _iface_up

    await asyncio.sleep(30)

    while True:
        try:
            # ── 1. Интерфейс awg0 ─────────────────────────────────────────────
            _, out = run(f"ip link show {INTERFACE}")
            is_up  = "UP" in out and "NO-CARRIER" not in out

            if not is_up and _iface_up:
                _iface_up = False
                for aid in ADMIN_IDS:
                    try:
                        await app.bot.send_message(
                            aid,
                            f"🔴 *АЛЁРТ*: `{INTERFACE}` упал!",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("🔄 Перезапустить", callback_data="menu:restart"),
                            ]]),
                        )
                    except Exception:
                        pass
            elif is_up and not _iface_up:
                _iface_up = True
                for aid in ADMIN_IDS:
                    try:
                        await app.bot.send_message(
                            aid, f"🟢 `{INTERFACE}` снова работает.",
                            parse_mode="Markdown", reply_markup=main_menu_kb()
                        )
                    except Exception:
                        pass

            # ── 2. CPU/RAM ────────────────────────────────────────────────────
            try:
                _, stat1 = run("cat /proc/stat")
                l1 = stat1.splitlines()[0].split()
                idle1, tot1 = int(l1[4]), sum(int(x) for x in l1[1:])
                await asyncio.sleep(1)
                _, stat2 = run("cat /proc/stat")
                l2 = stat2.splitlines()[0].split()
                idle2, tot2 = int(l2[4]), sum(int(x) for x in l2[1:])
                cpu_pct = round(100 * (1 - (idle2 - idle1) / max(tot2 - tot1, 1)))
            except Exception:
                cpu_pct = 0

            _, meminfo = run("free -m")
            ram_pct = 0
            for line in meminfo.splitlines():
                if line.startswith("Mem:"):
                    p = line.split()
                    ram_pct = int(int(p[2]) / max(int(p[1]), 1) * 100)

            if cpu_pct > 80 and not _cpu_alert_sent:
                _cpu_alert_sent = True
                for aid in ADMIN_IDS:
                    try:
                        await app.bot.send_message(
                            aid, f"🔴 *CPU алёрт*: `{cpu_pct}%` загрузка!",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass
            elif cpu_pct <= 70:
                _cpu_alert_sent = False

            if ram_pct > 90 and not _ram_alert_sent:
                _ram_alert_sent = True
                for aid in ADMIN_IDS:
                    try:
                        await app.bot.send_message(
                            aid, f"🔴 *RAM алёрт*: `{ram_pct}%` занята!",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass
            elif ram_pct <= 80:
                _ram_alert_sent = False

            # ── 3. Новые подключения ──────────────────────────────────────────
            peers    = load_peers()
            awg_data = parse_awg_show()
            now      = time.time()

            for name, info in peers.items():
                pubkey  = info.get("pubkey", "")
                stats   = awg_data.get(pubkey, {})
                cur_hs  = stats.get("last_handshake", 0)
                prev_hs = _prev_handshakes.get(pubkey, 0)

                # подключился: handshake стал свежим (< 3 мин), а до этого был старый или отсутствовал
                if cur_hs and (now - cur_hs) < 180 and (not prev_hs or (now - prev_hs) > 180):
                    endpoint = stats.get("endpoint", "неизвестно")
                    for aid in ADMIN_IDS:
                        try:
                            await app.bot.send_message(
                                aid,
                                f"🔔 *{name}* подключился\n🌍 `{endpoint}`",
                                parse_mode="Markdown",
                            )
                        except Exception:
                            pass

                _prev_handshakes[pubkey] = cur_hs

            # ── 4. Проверка истёкших пиров ────────────────────────────────────
            changed = False
            for name, info in peers.items():
                expires = info.get("expires")
                if not expires:
                    continue
                if datetime.fromisoformat(expires) < datetime.now():
                    pubkey    = info.get("pubkey", "")
                    allowed   = awg_data.get(pubkey, {}).get("allowed_ips", "")
                    if allowed != "0.0.0.0/32":
                        disable_peer(pubkey)
                        changed = True
                        for aid in ADMIN_IDS:
                            try:
                                await app.bot.send_message(
                                    aid,
                                    f"⏱ *{name}*: срок доступа истёк, клиент отключён.",
                                    parse_mode="Markdown",
                                )
                            except Exception:
                                pass

            if changed:
                save_peers(load_peers())

        except Exception as e:
            log.error(f"monitor error: {e}")

        await asyncio.sleep(60)

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    CLIENTS_DIR.mkdir(parents=True, exist_ok=True)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_start))
    app.add_handler(CommandHandler("menu",  cmd_start))

    app.add_handler(CallbackQueryHandler(cb_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    log.info("AmneziaWG Bot запущен")

    async def post_init(application: Application):
        asyncio.create_task(monitor_loop(application))

    app.post_init = post_init
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
