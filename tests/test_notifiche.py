"""Destinatari delle notifiche Home Assistant: filtri per tipo e alunno, compatibilità con
il vecchio `service` singolo, chiamate HTTP e riga di log per ogni notifica inviata."""
import json
import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import didup_calendar_sync as m  # noqa: E402
from test_snapshot import CONFIG, carica, raw, snap  # noqa: E402

HA = """
[notifiche.homeassistant]
url = "http://ha.test:8123/"
service = "notify.mobile_app_papa"
[[notifiche.homeassistant.destinatari]]
service = "mobile_app_mamma"
tipi = ["voti"]
[[notifiche.homeassistant.destinatari]]
service = "mobile_app_nonna"
tipi = ["voti", "bacheca"]
alunni = ["A"]
"""


def config(extra=HA, env=None):
    return carica(CONFIG.replace("[orario]", extra + "\n[orario]", 1), env)


class FakeHA:
    def __init__(self, falliscono=()):
        self.chiamate, self.falliscono = [], set(falliscono)

    def transport(self):
        def gestisci(req):
            servizio = req.url.path.rsplit("/", 1)[1]
            self.chiamate.append((servizio, json.loads(req.content), req.headers.get("authorization")))
            return httpx.Response(500 if servizio in self.falliscono else 200, json=[])
        return httpx.MockTransport(gestisci)


class TestDestinatari(unittest.TestCase):
    def test_service_singolo_compatibile(self):
        c = config('[notifiche.homeassistant]\nurl = "http://ha.test"\nservice = "notify.mobile_app_papa"\n')
        self.assertEqual(c["notifiche"]["homeassistant"]["destinatari"],
                         [{"service": "mobile_app_papa", "tipi": None, "alunni": None}])

    def test_service_piu_destinatari(self):
        d = config()["notifiche"]["homeassistant"]["destinatari"]
        self.assertEqual([x["service"] for x in d], ["mobile_app_papa", "mobile_app_mamma", "mobile_app_nonna"])
        self.assertEqual((d[1]["tipi"], d[1]["alunni"]), (["voti"], None))

    def test_solo_destinatari(self):
        c = config('[notifiche.homeassistant]\nurl = "http://ha.test"\n'
                   '[[notifiche.homeassistant.destinatari]]\nservice = "notify.mobile_app_mamma"\n')
        self.assertEqual(c["notifiche"]["homeassistant"]["destinatari"],
                         [{"service": "mobile_app_mamma", "tipi": None, "alunni": None}])

    def test_validazione(self):
        base = '[notifiche.homeassistant]\nurl = "http://ha.test"\n[[notifiche.homeassistant.destinatari]]\n'
        with self.assertRaisesRegex(ValueError, "tipi sconosciuti \\['pagelle'\\]"):
            config(base + 'service = "x"\ntipi = ["pagelle"]\n')
        with self.assertRaisesRegex(ValueError, "alunni sconosciuti \\['Z'\\]"):
            config(base + 'service = "x"\nalunni = ["Z"]\n')
        with self.assertRaisesRegex(ValueError, "chiavi: service, tipi, alunni"):
            config(base + 'servizio = "x"\n')
        with self.assertRaisesRegex(ValueError, "service vuoto"):
            config(base + 'service = "notify."\n')


class TestInstradamento(unittest.TestCase):
    def setUp(self):
        self.ha = FakeHA()
        self.n = m.Notifier(config(HA, {"HA_TOKEN": "tok"})["notifiche"], False,
                            transport=self.ha.transport())

    def chi(self, kind, alunno):
        self.ha.chiamate.clear()
        self.n.send("T", "M", kind=kind, alunno=alunno)
        return [s for s, _, _ in self.ha.chiamate]

    def test_per_tipo_e_alunno(self):
        self.assertEqual(self.chi("voti", "A"), ["mobile_app_papa", "mobile_app_mamma", "mobile_app_nonna"])
        self.assertEqual(self.chi("voti", "B"), ["mobile_app_papa", "mobile_app_mamma"])
        self.assertEqual(self.chi("bacheca", "A"), ["mobile_app_papa", "mobile_app_nonna"])
        self.assertEqual(self.chi("note", "A"), ["mobile_app_papa"])

    def test_messaggi_di_sistema_solo_senza_filtri(self):
        self.assertEqual(self.chi(None, None), ["mobile_app_papa"])

    def test_payload_token_e_link(self):
        self.n.send("🎓 Voto – A", "Matematica: 8", url="https://x/f/1", kind="voti", alunno="A")
        servizio, corpo, auth = self.ha.chiamate[0]
        self.assertEqual((servizio, auth), ("mobile_app_papa", "Bearer tok"))
        self.assertEqual((corpo["title"], corpo["data"]["url"]), ("🎓 Voto – A", "https://x/f/1"))

    def test_un_destinatario_fallito_non_blocca_gli_altri(self):
        self.ha.falliscono.add("mobile_app_papa")
        with self.assertLogs(m.log, "INFO") as cm:
            self.n.send("T", "M", kind="voti", alunno="B")
        self.assertEqual([s for s, _, _ in self.ha.chiamate], ["mobile_app_papa", "mobile_app_mamma"])
        self.assertTrue(any("Notifica HA fallita (notify.mobile_app_papa)" in r for r in cm.output))

    def test_riga_di_log_per_ogni_notifica(self):
        with self.assertLogs(m.log, "INFO") as cm:
            self.n.send("🎓 Voto – B", "Matematica: 8", kind="voti", alunno="B")
        self.assertIn("notifica voti → notify.mobile_app_papa, notify.mobile_app_mamma: 🎓 Voto – B", cm.output[0])
        self.assertNotIn("Matematica", cm.output[0])   # nel log solo il titolo, non il contenuto

    def test_dry_run_non_chiama(self):
        n = m.Notifier(config()["notifiche"], True, transport=self.ha.transport())
        with self.assertLogs(m.log, "INFO") as cm:
            n.send("T", "M", kind="voti", alunno="A")
        self.assertEqual(self.ha.chiamate, [])
        self.assertIn("NOTIFICA voti → notify.mobile_app_papa, notify.mobile_app_mamma, notify.mobile_app_nonna", cm.output[0])


class TestNotifyNew(unittest.TestCase):
    def test_voto_nuovo_va_a_tipo_e_alunno(self):
        ricevute = []

        class N:
            def send(self, title, message, url=None, kind=None, alunno=None):
                ricevute.append((kind, alunno, title))
        st = m.State(Path("/nonexistent/state.json"))
        m.notify_new(snap(), "x", "Test", st, N(), ["voti", "bacheca"])
        d = raw()
        d["voti"].append({"prgVoto": 9, "datGiorno": "2026-10-04", "desMateria": "INGLESE",
                          "codCodice": "8", "codVotoPratico": "N"})
        m.notify_new(snap(d), "x", "Test", st, N(), ["voti", "bacheca"])
        self.assertEqual(ricevute, [("voti", "Test", "🎓 Voto – Test")])


if __name__ == "__main__":
    unittest.main()
