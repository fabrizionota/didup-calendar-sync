"""Telegram: più chat con filtri per tipo e alunno, token mai nel log, variabili vuote ignorate."""
import json
import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import didup_calendar_sync as m  # noqa: E402
from test_snapshot import CONFIG, carica  # noqa: E402

TOKEN = "123456:SEGRETO-del-bot"
TG = f"""
[notifiche.telegram]
bot_token = "{TOKEN}"
chat_id = 111111111
[[notifiche.telegram.destinatari]]
chat_id = "-1002222"
tipi = ["voti"]
[[notifiche.telegram.destinatari]]
chat_id = "333333"
tipi = ["voti", "bacheca"]
alunni = ["A"]
"""


def config(extra=TG, env=None):
    return carica(CONFIG.replace("[orario]", extra + "\n[orario]", 1), env)


class FakeTelegram:
    def __init__(self, rifiuta=()):
        self.inviati, self.rifiuta = [], set(rifiuta)

    def transport(self):
        def gestisci(req):
            assert req.url.host == "api.telegram.org"
            corpo = json.loads(req.content)
            self.inviati.append((req.url.path, corpo["chat_id"], corpo["text"]))
            if corpo["chat_id"] in self.rifiuta:
                return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})
            return httpx.Response(200, json={"ok": True})
        return httpx.MockTransport(gestisci)


class TestConfigTelegram(unittest.TestCase):
    def test_chat_singola_compatibile(self):
        c = config(f'[notifiche.telegram]\nbot_token = "{TOKEN}"\nchat_id = "42"\n')
        self.assertEqual(c["notifiche"]["telegram"]["destinatari"], [{"chat_id": "42", "tipi": None, "alunni": None}])

    def test_piu_chat_e_id_numerico(self):
        d = config()["notifiche"]["telegram"]["destinatari"]
        self.assertEqual([x["chat_id"] for x in d], ["111111111", "-1002222", "333333"])
        self.assertEqual((d[2]["tipi"], d[2]["alunni"]), (["voti", "bacheca"], ["A"]))

    def test_validazione(self):
        base = f'[notifiche.telegram]\nbot_token = "{TOKEN}"\n[[notifiche.telegram.destinatari]]\n'
        with self.assertRaisesRegex(ValueError, "alunni sconosciuti"):
            config(base + 'chat_id = "1"\nalunni = ["Z"]\n')
        with self.assertRaisesRegex(ValueError, "tipi sconosciuti"):
            config(base + 'chat_id = "1"\ntipi = ["pagelle"]\n')
        with self.assertRaisesRegex(ValueError, "chiavi: chat_id, tipi, alunni"):
            config(base + 'chat = "1"\n')
        with self.assertRaisesRegex(ValueError, "manca il token del bot"):
            config('[notifiche.telegram]\nchat_id = "1"\n')

    def test_variabili_vuote_non_cancellano_il_config(self):
        extra = TG + '\n[notifiche.homeassistant]\nurl = "http://ha"\nservice = "x"\ntoken = "tok-config"\n'
        c = config(extra, {"TELEGRAM_BOT_TOKEN": "", "HA_TOKEN": ""})
        self.assertEqual(c["notifiche"]["telegram"]["bot_token"], TOKEN)
        self.assertEqual(c["notifiche"]["homeassistant"]["token"], "tok-config")
        c = config(extra, {"TELEGRAM_BOT_TOKEN": "env-tok", "HA_TOKEN": "env-ha"})
        self.assertEqual((c["notifiche"]["telegram"]["bot_token"], c["notifiche"]["homeassistant"]["token"]),
                         ("env-tok", "env-ha"))


class TestInvioTelegram(unittest.TestCase):
    def setUp(self):
        self.tg = FakeTelegram()
        self.n = m.Notifier(config()["notifiche"], False, transport=self.tg.transport())

    def chi(self, kind, alunno):
        self.tg.inviati.clear()
        with self.assertLogs(m.log, "INFO"):
            self.n.send("T", "M", kind=kind, alunno=alunno)
        return [c for _, c, _ in self.tg.inviati]

    def test_filtri(self):
        self.assertEqual(self.chi("voti", "A"), ["111111111", "-1002222", "333333"])
        self.assertEqual(self.chi("voti", "B"), ["111111111", "-1002222"])
        self.assertEqual(self.chi("bacheca", "A"), ["111111111", "333333"])
        self.assertEqual(self.chi(None, None), ["111111111"])          # sistema: solo senza filtri

    def test_testo_link_e_percorso(self):
        with self.assertLogs(m.log, "INFO") as cm:
            self.n.send("🎓 Voto – A", "Matematica: 8", url="https://x/f/1", kind="voti", alunno="B")
        percorso, _, testo = self.tg.inviati[0]
        self.assertEqual(percorso, f"/bot{TOKEN}/sendMessage")
        self.assertEqual(testo, "🎓 Voto – A\nMatematica: 8\nhttps://x/f/1")
        self.assertIn("telegram:…1111, telegram:…2222", cm.output[0])   # id mascherati nel log
        self.assertNotIn("111111111", "".join(cm.output))

    def test_testo_troppo_lungo_troncato(self):
        self.n.send("T", "x" * 5000, kind="voti", alunno="B")
        self.assertLessEqual(len(self.tg.inviati[0][2]), 4000)

    def test_errore_senza_token_nel_log_e_metrica(self):
        m.METRICHE = m.Metriche()
        tg = FakeTelegram(rifiuta={"-1002222"})
        n = m.Notifier(config()["notifiche"], False, transport=tg.transport())
        with self.assertLogs(m.log, "INFO") as cm:
            n.send("T", "M", kind="voti", alunno="B")
        log = "".join(cm.output)
        self.assertIn("Notifica Telegram fallita (telegram:…2222): HTTP 400 Bad Request: chat not found", log)
        self.assertNotIn("SEGRETO", log)
        self.assertEqual(len(tg.inviati), 2)                                  # le altre chat ricevono comunque
        self.assertEqual(m.METRICHE.get("didup_notification_errors_total", servizio="telegram:…2222"), 1)

    def test_errore_di_rete_senza_token_nel_log(self):
        def rete(req):
            raise httpx.ConnectError(f"impossibile raggiungere {req.url}")
        n = m.Notifier(config()["notifiche"], False, transport=httpx.MockTransport(rete))
        with self.assertLogs(m.log, "INFO") as cm:
            n.send("T", "M", kind="voti", alunno="B")
        self.assertNotIn("SEGRETO", "".join(cm.output))
        self.assertIn("ConnectError", "".join(cm.output))

    def test_dry_run(self):
        n = m.Notifier(config()["notifiche"], True, transport=self.tg.transport())
        with self.assertLogs(m.log, "INFO") as cm:
            n.send("T", "M", kind="voti", alunno="A")
        self.assertEqual(self.tg.inviati, [])
        self.assertIn("telegram:…3333", cm.output[0])


if __name__ == "__main__":
    unittest.main()
