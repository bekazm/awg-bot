"""
Тесты для awg-bot / Tests for awg-bot
Покрывают чистые утилитарные функции и функции с моками I/O.
"""

import importlib
import json
import sys
import time
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch


# ─── Настройка фейковых модулей telegram ──────────────────────────────────────

def _install_fake_telegram():
    """Вставляет заглушки telegram/* в sys.modules до импорта bot."""
    tg = types.ModuleType("telegram")
    tg.Update = MagicMock()
    tg.InlineKeyboardButton = MagicMock(side_effect=lambda text, **kw: (text, kw))
    tg.InlineKeyboardMarkup = MagicMock(side_effect=lambda rows: rows)
    tg.Message = MagicMock()

    tg_ext = types.ModuleType("telegram.ext")
    for cls in ("Application", "CommandHandler", "CallbackQueryHandler",
                "ContextTypes", "MessageHandler", "filters"):
        setattr(tg_ext, cls, MagicMock())

    sys.modules["telegram"] = tg
    sys.modules["telegram.ext"] = tg_ext


_install_fake_telegram()

# ─── Фейковый конфиг, который «читает» load_config() ─────────────────────────

FAKE_CONFIG = {
    "bot_token": "1234567890:FAKE_TOKEN",
    "admin_ids": [111111111],
    "server_ip": "1.2.3.4",
    "server_vpn_ip": "10.66.66.1",
    "vpn_subnet": "10.66.66.0/24",
    "dns": "1.1.1.1",
}

_fake_config_json = json.dumps(FAKE_CONFIG)

# Подменяем файл конфига и лог-хендлер до первого импорта bot
with (
    patch("builtins.open", mock_open(read_data=_fake_config_json)),
    patch("pathlib.Path.exists", return_value=False),
    patch("logging.FileHandler", return_value=MagicMock()),
):
    import bot  # noqa: E402  — импортируем после настройки моков


# ─── Вспомогательные данные ───────────────────────────────────────────────────

def _now_ts() -> int:
    return int(time.time())


def _ts_ago(seconds: int) -> int:
    return _now_ts() - seconds


# ══════════════════════════════════════════════════════════════════════════════
# 1. human_bytes
# ══════════════════════════════════════════════════════════════════════════════

class TestHumanBytes(unittest.TestCase):

    def test_bytes(self):
        self.assertEqual(bot.human_bytes(0), "0.0 B")
        self.assertEqual(bot.human_bytes(512), "512.0 B")
        self.assertEqual(bot.human_bytes(1023), "1023.0 B")

    def test_kilobytes(self):
        self.assertEqual(bot.human_bytes(1024), "1.0 KB")
        self.assertEqual(bot.human_bytes(1536), "1.5 KB")

    def test_megabytes(self):
        self.assertEqual(bot.human_bytes(1024 ** 2), "1.0 MB")
        self.assertIn("MB", bot.human_bytes(1024 ** 2 * 142))

    def test_gigabytes(self):
        self.assertIn("GB", bot.human_bytes(1024 ** 3 * 2))

    def test_terabytes(self):
        self.assertIn("TB", bot.human_bytes(1024 ** 4 * 5))


# ══════════════════════════════════════════════════════════════════════════════
# 2. ago
# ══════════════════════════════════════════════════════════════════════════════

class TestAgo(unittest.TestCase):

    def test_zero_returns_never(self):
        self.assertEqual(bot.ago(0), "никогда")

    def test_seconds(self):
        result = bot.ago(_ts_ago(30))
        self.assertRegex(result, r"\d+с назад")

    def test_minutes(self):
        result = bot.ago(_ts_ago(120))
        self.assertRegex(result, r"\d+м назад")

    def test_hours(self):
        result = bot.ago(_ts_ago(7200))
        self.assertRegex(result, r"\d+ч назад")

    def test_days(self):
        result = bot.ago(_ts_ago(86400 * 3))
        self.assertRegex(result, r"\d+д назад")


# ══════════════════════════════════════════════════════════════════════════════
# 3. fmt_ts
# ══════════════════════════════════════════════════════════════════════════════

class TestFmtTs(unittest.TestCase):

    def test_zero_returns_dash(self):
        self.assertEqual(bot.fmt_ts(0), "—")

    def test_valid_timestamp(self):
        ts = int(datetime(2026, 3, 3, 18, 22).timestamp())
        result = bot.fmt_ts(ts)
        self.assertEqual(result, "2026-03-03 18:22")

    def test_format_pattern(self):
        ts = _now_ts()
        result = bot.fmt_ts(ts)
        self.assertRegex(result, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")


# ══════════════════════════════════════════════════════════════════════════════
# 4. fmt_expires
# ══════════════════════════════════════════════════════════════════════════════

class TestFmtExpires(unittest.TestCase):

    def test_none_is_unlimited(self):
        self.assertEqual(bot.fmt_expires(None), "♾ Бессрочно")

    def test_expired(self):
        past = (datetime.now() - timedelta(days=1)).isoformat(timespec="minutes")
        result = bot.fmt_expires(past)
        self.assertIn("⛔", result)
        self.assertIn("Истёк", result)

    def test_future_days(self):
        future = (datetime.now() + timedelta(days=5)).isoformat(timespec="minutes")
        result = bot.fmt_expires(future)
        self.assertIn("⏱", result)
        self.assertIn("д", result)

    def test_future_hours(self):
        future = (datetime.now() + timedelta(hours=3)).isoformat(timespec="minutes")
        result = bot.fmt_expires(future)
        self.assertIn("⏱", result)

    def test_invalid_string_passthrough(self):
        result = bot.fmt_expires("not-a-date")
        self.assertEqual(result, "not-a-date")


# ══════════════════════════════════════════════════════════════════════════════
# 5. next_vpn_ip
# ══════════════════════════════════════════════════════════════════════════════

class TestNextVpnIp(unittest.TestCase):

    def test_empty_peers_gives_first_available(self):
        ip = bot.next_vpn_ip({})
        # Сервер на 10.66.66.1, первый клиент — .2
        self.assertEqual(ip, "10.66.66.2")

    def test_skips_existing_ips(self):
        peers = {
            "alice": {"ip": "10.66.66.2/32"},
            "bob":   {"ip": "10.66.66.3/32"},
        }
        ip = bot.next_vpn_ip(peers)
        self.assertEqual(ip, "10.66.66.4")

    def test_skips_server_ip(self):
        # Заполняем .2–.253; сервер .1 пропускается, .254 станет первым свободным
        peers = {str(i): {"ip": f"10.66.66.{i}/32"} for i in range(2, 254)}
        ip = bot.next_vpn_ip(peers)
        self.assertEqual(ip, "10.66.66.254")

    def test_no_free_ip_raises(self):
        peers = {str(i): {"ip": f"10.66.66.{i}/32"} for i in range(2, 255)}
        with self.assertRaises(ValueError):
            bot.next_vpn_ip(peers)

    def test_ip_without_mask(self):
        peers = {"alice": {"ip": "10.66.66.2"}}
        ip = bot.next_vpn_ip(peers)
        self.assertEqual(ip, "10.66.66.3")


# ══════════════════════════════════════════════════════════════════════════════
# 6. get_junk_params
# ══════════════════════════════════════════════════════════════════════════════

class TestGetJunkParams(unittest.TestCase):

    AWG_CONF_TEXT = (
        "[Interface]\n"
        "PrivateKey = SERVERKEY\n"
        "Jc = 7\n"
        "Jmin = 50\n"
        "Jmax = 80\n"
        "S1 = 10\n"
        "S2 = 20\n"
        "H1 = 1111\n"
        "H2 = 2222\n"
        "H3 = 3333\n"
        "H4 = 4444\n"
    )

    def test_reads_custom_values(self):
        # Патчим Path.read_text через замену bot.AWG_CONF на MagicMock
        with patch("bot.AWG_CONF") as mock_conf:
            mock_conf.read_text.return_value = self.AWG_CONF_TEXT
            params = bot.get_junk_params()
        self.assertEqual(params["Jc"], "7")
        self.assertEqual(params["Jmin"], "50")
        self.assertEqual(params["H1"], "1111")

    def test_fallback_defaults_on_error(self):
        with patch("bot.AWG_CONF") as mock_conf:
            mock_conf.read_text.side_effect = FileNotFoundError
            params = bot.get_junk_params()
        self.assertIn("Jc", params)
        self.assertEqual(params["Jc"], "4")   # дефолт из кода

    def test_partial_conf_uses_defaults_for_missing(self):
        partial = "[Interface]\nJc = 9\n"
        with patch("bot.AWG_CONF") as mock_conf:
            mock_conf.read_text.return_value = partial
            params = bot.get_junk_params()
        self.assertEqual(params["Jc"], "9")
        self.assertEqual(params["Jmin"], "40")  # дефолт


# ══════════════════════════════════════════════════════════════════════════════
# 7. parse_awg_show
# ══════════════════════════════════════════════════════════════════════════════

class TestParseAwgShow(unittest.TestCase):
    # awg show <iface> dump формат:
    # Строка сервера (4 поля):  <priv>\t<pub>\t<port>\t<fwmark>
    # Строка пира   (8 полей):  <pub>\t<psk>\t<endpoint>\t<allowed-ips>\t<last-hs>\t<rx>\t<tx>\t<ka>
    DUMP_OUTPUT = (
        "SERVERPRIVKEY\tSERVERPUBKEY\t51820\toff\n"                              # 4 поля — skipped (<6)
        "PUBKEY1\tPSK1\t1.2.3.4:51820\t10.66.66.2/32\t1709481722\t1048576\t262144\toff\n"
        "PUBKEY2\tPSK2\t(none)\t10.66.66.3/32\t0\t0\t0\toff\n"
    )

    def test_parses_peer_data(self):
        with patch.object(bot, "run", return_value=(0, self.DUMP_OUTPUT)):
            result = bot.parse_awg_show()
        self.assertIn("PUBKEY1", result)
        self.assertEqual(result["PUBKEY1"]["rx"], 1048576)
        self.assertEqual(result["PUBKEY1"]["tx"], 262144)
        self.assertEqual(result["PUBKEY1"]["last_handshake"], 1709481722)
        self.assertEqual(result["PUBKEY1"]["endpoint"], "1.2.3.4:51820")

    def test_no_endpoint_is_none(self):
        with patch.object(bot, "run", return_value=(0, self.DUMP_OUTPUT)):
            result = bot.parse_awg_show()
        self.assertIsNone(result["PUBKEY2"]["endpoint"])

    def test_skips_server_private_line(self):
        with patch.object(bot, "run", return_value=(0, self.DUMP_OUTPUT)):
            result = bot.parse_awg_show()
        # Строка сервера имеет только 4 поля — пропускается условием len(parts)<6
        self.assertNotIn("SERVERPRIVKEY", result)

    def test_returns_empty_on_error(self):
        with patch.object(bot, "run", return_value=(1, "error")):
            result = bot.parse_awg_show()
        self.assertEqual(result, {})


# ══════════════════════════════════════════════════════════════════════════════
# 8. audit
# ══════════════════════════════════════════════════════════════════════════════

class TestAudit(unittest.TestCase):

    def test_writes_expected_fields(self):
        m = mock_open()
        with patch("builtins.open", m):
            bot.audit(123456, "test_action", "detail=xyz")
        written = "".join(call.args[0] for call in m().write.call_args_list)
        self.assertIn("uid=123456", written)
        self.assertIn("test_action", written)
        self.assertIn("detail=xyz", written)

    def test_no_details(self):
        m = mock_open()
        with patch("builtins.open", m):
            bot.audit(1, "action_only")
        written = "".join(call.args[0] for call in m().write.call_args_list)
        self.assertIn("action_only", written)

    def test_io_error_does_not_raise(self):
        with (
            patch("builtins.open", side_effect=PermissionError("denied")),
            patch.object(bot.log, "error"),   # глушим логгер, чтобы не упасть на MagicMock-хендлере
        ):
            bot.audit(1, "action")  # не должно бросить исключение


# ══════════════════════════════════════════════════════════════════════════════
# 9. build_peers_text
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildPeersText(unittest.TestCase):

    def test_empty_peers(self):
        text = bot.build_peers_text({}, {})
        self.assertIn("Клиентов нет", text)

    def test_peer_shown(self):
        peers = {
            "alice": {"pubkey": "PK1", "ip": "10.66.66.2"},
        }
        awg = {
            "PK1": {"last_handshake": 0, "rx": 0, "tx": 0, "allowed_ips": "10.66.66.2/32"},
        }
        text = bot.build_peers_text(peers, awg)
        self.assertIn("alice", text)
        self.assertIn("10.66.66.2", text)

    def test_online_icon(self):
        peers = {"bob": {"pubkey": "PK2", "ip": "10.66.66.3"}}
        awg   = {"PK2": {
            "last_handshake": _now_ts() - 60,  # 1 мин назад — онлайн
            "rx": 0, "tx": 0,
            "allowed_ips": "10.66.66.3/32",
        }}
        text = bot.build_peers_text(peers, awg)
        self.assertIn("🟢", text)

    def test_expired_peer_shows_disabled_icon(self):
        past = (datetime.now() - timedelta(days=1)).isoformat(timespec="minutes")
        peers = {"eve": {"pubkey": "PK3", "ip": "10.66.66.4", "expires": past}}
        awg   = {"PK3": {"last_handshake": 0, "rx": 0, "tx": 0, "allowed_ips": "10.66.66.4/32"}}
        text = bot.build_peers_text(peers, awg)
        self.assertIn("⛔", text)

    def test_multiple_peers_count(self):
        peers = {f"user{i}": {"pubkey": f"PK{i}", "ip": f"10.66.66.{i+2}"} for i in range(5)}
        awg   = {f"PK{i}": {"last_handshake": 0, "rx": 0, "tx": 0, "allowed_ips": ""} for i in range(5)}
        text = bot.build_peers_text(peers, awg)
        self.assertIn("5", text)


# ══════════════════════════════════════════════════════════════════════════════
# 10. build_peer_detail
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildPeerDetail(unittest.TestCase):

    BASE_INFO = {
        "ip":      "10.66.66.2",
        "created": "2026-01-01 00:00",
        "expires": None,
    }
    BASE_STATS = {
        "last_handshake": 0,
        "rx": 0,
        "tx": 0,
        "endpoint": None,
        "allowed_ips": "10.66.66.2/32",
    }

    def test_contains_name_and_ip(self):
        text = bot.build_peer_detail("alice", self.BASE_INFO, self.BASE_STATS)
        self.assertIn("alice", text)
        self.assertIn("10.66.66.2", text)

    def test_never_connected_status(self):
        text = bot.build_peer_detail("alice", self.BASE_INFO, self.BASE_STATS)
        self.assertIn("Никогда не подключался", text)

    def test_online_status(self):
        stats = {**self.BASE_STATS, "last_handshake": _now_ts() - 30}
        text = bot.build_peer_detail("alice", self.BASE_INFO, stats)
        self.assertIn("🟢 Онлайн", text)

    def test_disabled_status(self):
        stats = {**self.BASE_STATS, "allowed_ips": "0.0.0.0/32"}
        text = bot.build_peer_detail("alice", self.BASE_INFO, stats)
        self.assertIn("⛔ Отключён", text)

    def test_expired_status(self):
        past = (datetime.now() - timedelta(hours=2)).isoformat(timespec="minutes")
        info = {**self.BASE_INFO, "expires": past}
        text = bot.build_peer_detail("alice", info, self.BASE_STATS)
        self.assertIn("истёк", text)

    def test_unlimited_access(self):
        text = bot.build_peer_detail("alice", self.BASE_INFO, self.BASE_STATS)
        self.assertIn("♾ Бессрочно", text)

    def test_endpoint_shown_when_present(self):
        stats = {**self.BASE_STATS, "endpoint": "5.6.7.8:51820"}
        text = bot.build_peer_detail("alice", self.BASE_INFO, stats)
        self.assertIn("5.6.7.8:51820", text)

    def test_endpoint_not_shown_when_none(self):
        text = bot.build_peer_detail("alice", self.BASE_INFO, self.BASE_STATS)
        self.assertNotIn("endpoint", text.lower())


# ══════════════════════════════════════════════════════════════════════════════
# 11. make_client_conf
# ══════════════════════════════════════════════════════════════════════════════

class TestMakeClientConf(unittest.TestCase):

    JUNK = {
        "Jc": "4", "Jmin": "40", "Jmax": "70",
        "S1": "0", "S2": "0",
        "H1": "4665", "H2": "19774", "H3": "17391", "H4": "14857",
    }

    def _make(self, name="alice", privkey="PRIV", psk="PSK", ip="10.66.66.2"):
        with (
            patch.object(bot, "get_server_pubkey", return_value="SERVERPUB"),
            patch.object(bot, "get_junk_params",   return_value=self.JUNK),
        ):
            return bot.make_client_conf(name, privkey, psk, ip)

    def test_contains_interface_section(self):
        conf = self._make()
        self.assertIn("[Interface]", conf)
        self.assertIn("[Peer]", conf)

    def test_private_key_in_conf(self):
        conf = self._make(privkey="MYPRIVKEY")
        self.assertIn("PrivateKey = MYPRIVKEY", conf)

    def test_address_in_conf(self):
        conf = self._make(ip="10.66.66.5")
        self.assertIn("Address = 10.66.66.5/24", conf)

    def test_server_pubkey_in_peer_section(self):
        conf = self._make()
        self.assertIn("PublicKey = SERVERPUB", conf)

    def test_psk_in_conf(self):
        conf = self._make(psk="MYPSK")
        self.assertIn("PresharedKey = MYPSK", conf)

    def test_endpoint_format(self):
        conf = self._make()
        self.assertIn(f"Endpoint = {bot.SERVER_IP}:{bot.SERVER_PORT}", conf)

    def test_dns_in_conf(self):
        conf = self._make()
        self.assertIn(f"DNS = {bot.DNS}", conf)

    def test_junk_params_present(self):
        conf = self._make()
        self.assertIn("Jc=4", conf)
        self.assertIn("H1=4665", conf)

    def test_allowed_ips_is_full_tunnel(self):
        conf = self._make()
        self.assertIn("AllowedIPs = 0.0.0.0/0", conf)

    def test_keepalive_present(self):
        conf = self._make()
        self.assertIn("PersistentKeepalive = 25", conf)


# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
