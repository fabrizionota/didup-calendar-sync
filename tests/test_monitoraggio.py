"""Monitoraggio: formato Prometheus, /healthz, push Uptime Kuma, contatori agganciati al codice."""
import json
import socket
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import didup_calendar_sync as m  # noqa: E402


def nuove_metriche():
    m.METRICHE = m.Metriche()
    return m.METRICHE


class TestMetriche(unittest.TestCase):
    def setUp(self):
        self.mt = nuove_metriche()

    def test_formato_prometheus(self):
        self.mt.set("didup_up", 1)
        self.mt.inc("didup_notifications_total", alunno="Anna", tipo="voti")
        self.mt.inc("didup_notifications_total", 2, alunno="Anna", tipo="voti")
        self.mt.set("didup_items", 0, alunno='A "x"\\y', tipo="voti")
        t = self.mt.testo()
        self.assertIn("# TYPE didup_up gauge\ndidup_up 1\n", t)
        self.assertIn("# TYPE didup_notifications_total counter", t)
        self.assertIn('didup_notifications_total{alunno="Anna",tipo="voti"} 3', t)
        self.assertIn(r'didup_items{alunno="A \"x\"\\y",tipo="voti"} 0', t)
        self.assertNotIn("didup_runs_total", t)            # metriche mai valorizzate: assenti
        for riga in t.splitlines():                          # ogni metrica dichiarata
            if not riga.startswith("#"):
                self.assertIn(riga.split("{")[0].split(" ")[0], m.METRICHE_DEF)

    def test_inc_zero_non_crea_serie_e_azzera(self):
        self.mt.inc("didup_attachments_total", 0, alunno="A", archivio="drive", esito="errore")
        self.assertIsNone(self.mt.get("didup_attachments_total", alunno="A", archivio="drive", esito="errore"))
        self.mt.set("didup_argo_client_version_info", 1, scuola="SC1", versione="1.30.2")
        self.mt.azzera("didup_argo_client_version_info", scuola="SC1")
        self.mt.set("didup_argo_client_version_info", 1, scuola="SC1", versione="1.31.0")
        self.assertNotIn("1.30.2", self.mt.testo())

    def test_registra_giro(self):
        m.registra_giro(100.0, 103.5, True)
        m.registra_giro(200.0, 201.0, False)
        self.assertEqual(self.mt.get("didup_up"), 0)
        self.assertEqual(self.mt.get("didup_last_success_timestamp_seconds"), 103.5)
        self.assertEqual(self.mt.get("didup_last_run_timestamp_seconds"), 201.0)
        self.assertEqual((self.mt.get("didup_runs_total", result="ok"), self.mt.get("didup_runs_total", result="error")), (1, 1))


class TestSalute(unittest.TestCase):
    def setUp(self):
        self.mt = nuove_metriche()
        self.mt.intervallo = 1800

    def test_avvio_poi_nessun_giro(self):
        self.assertEqual(self.mt.salute(self.mt.avvio + 60)[1]["stato"], "avvio")
        self.assertTrue(self.mt.salute(self.mt.avvio + 60)[0])
        self.assertFalse(self.mt.salute(self.mt.avvio + 4000)[0])

    def test_ok_fallito_vecchio(self):
        ora = time.time()
        m.registra_giro(ora - 10, ora, True)
        self.assertEqual(self.mt.salute(ora + 60), (True, self.mt.salute(ora + 60)[1]))
        self.assertFalse(self.mt.salute(ora + 2 * 1800 + 400)[0])          # troppo vecchio
        self.assertEqual(self.mt.salute(ora + 2 * 1800 + 400)[1]["stato"], "giro troppo vecchio")
        m.registra_giro(ora, ora + 5, False)
        ok, info = self.mt.salute(ora + 60)
        self.assertEqual((ok, info["stato"]), (False, "ultimo giro fallito"))


class TestServer(unittest.TestCase):
    def test_metrics_healthz_404(self):
        mt = nuove_metriche()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            porta = s.getsockname()[1]
        srv = m.avvia_server_metriche(porta, "127.0.0.1")
        try:
            base = f"http://127.0.0.1:{porta}"
            mt.set("didup_up", 1)
            with urllib.request.urlopen(base + "/metrics") as r:
                self.assertIn("text/plain", r.headers["Content-Type"])
                self.assertIn("didup_up 1", r.read().decode())
            with urllib.request.urlopen(base + "/healthz") as r:              # in avvio: 200
                self.assertEqual(json.loads(r.read())["stato"], "avvio")
            m.registra_giro(time.time() - 1, time.time(), False)
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(base + "/healthz")
            self.assertEqual(cm.exception.code, 503)
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(base + "/altro")
            self.assertEqual(cm.exception.code, 404)
        finally:
            srv.shutdown()
            srv.server_close()


class TestPorta(unittest.TestCase):
    def setUp(self):
        import tempfile
        from test_snapshot import CONFIG
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Path(self.tmp.name) / "config.toml"
        self.config.write_text(CONFIG)   # niente file del repo: nell'immagine ci sono solo i test

    def tearDown(self):
        self.tmp.cleanup()

    def avvia(self, valore):
        import os
        from unittest import mock
        argv = ["didup_calendar_sync.py", "-c", str(self.config), "--list-profiles"]
        with mock.patch.dict(os.environ, {"METRICS_PORT": valore}), mock.patch.object(sys, "argv", argv), \
                mock.patch.object(m, "run_once", lambda *a: _vuoto()), \
                mock.patch.object(m, "avvia_server_metriche") as srv, self.assertLogs(m.log, "INFO"):
            m.main()
        return srv

    def test_porta_non_valida(self):
        for v in ("abc", "70000", "-1"):
            with self.assertRaises(SystemExit) as cm:
                self.avvia(v)
            self.assertIn("METRICS_PORT non valida", str(cm.exception))

    def avvia_loop(self, env, extra=""):
        import os
        from unittest import mock
        if extra:
            self.config.write_text(self.config.read_text().replace("[orario]", extra + "\n[orario]", 1))
        argv = ["didup_calendar_sync.py", "-c", str(self.config), "--state", str(self.config.parent / "s.json")]
        spinte = []
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sys, "argv", argv), \
                mock.patch.object(m, "run_once", lambda *a: _vuoto()), \
                mock.patch.object(m, "avvia_server_metriche") as srv, \
                mock.patch.object(m, "kuma_push", lambda url, *a, **k: spinte.append(url)), \
                self.assertLogs(m.log, "INFO"):
            m.main()
        return srv, spinte

    def test_config_usato_se_manca_la_variabile(self):
        srv, spinte = self.avvia_loop({}, '[monitoraggio]\nporta = 9300\nkuma_push_url = "http://k/api/push/C"')
        self.assertEqual(srv.call_args.args[0], 9300)
        self.assertEqual(spinte, ["http://k/api/push/C"])

    def test_variabili_vincono_sul_config(self):
        srv, spinte = self.avvia_loop({"METRICS_PORT": "9400", "KUMA_PUSH_URL": "http://k/api/push/E"},
                                      '[monitoraggio]\nporta = 9300\nkuma_push_url = "http://k/api/push/C"')
        self.assertEqual(srv.call_args.args[0], 9400)
        self.assertEqual(spinte, ["http://k/api/push/E"])

    def test_variabile_vuota_usa_il_config(self):   # stack con KUMA_PUSH_URL: ${KUMA_PUSH_URL:-}
        _, spinte = self.avvia_loop({"KUMA_PUSH_URL": ""}, '[monitoraggio]\nkuma_push_url = "http://k/api/push/C"')
        self.assertEqual(spinte, ["http://k/api/push/C"])

    def test_porta_valida_ma_una_tantum_non_avvia(self):
        self.assertFalse(self.avvia("9200").called)   # --list-profiles: niente server


async def _vuoto():
    return None


class TestConfigMonitoraggio(unittest.TestCase):
    def carica(self, extra, env=None):
        from test_snapshot import CONFIG, carica
        return carica(CONFIG.replace("[orario]", extra + "\n[orario]", 1), env)

    def test_default_e_valori(self):
        self.assertEqual(self.carica("")["monitoraggio"], {})
        c = self.carica('[monitoraggio]\nporta = 9200\nkuma_push_url = "http://k/api/push/T"')
        self.assertEqual(c["monitoraggio"], {"porta": 9200, "kuma_push_url": "http://k/api/push/T"})

    def test_validazione(self):
        with self.assertRaisesRegex(ValueError, "porta"):
            self.carica('[monitoraggio]\nporta = "9105"')
        with self.assertRaisesRegex(ValueError, "porta"):
            self.carica("[monitoraggio]\nporta = 70000")
        with self.assertRaisesRegex(ValueError, "chiavi sconosciute"):
            self.carica('[monitoraggio]\nkuma = "x"')


class TestKuma(unittest.TestCase):
    def setUp(self):
        self.chiamate = []

        def gestisci(req):
            self.chiamate.append(dict(req.url.params))
            return httpx.Response(200 if "boom" not in str(req.url) else 500, json={"ok": True})
        self.transport = httpx.MockTransport(gestisci)

    def test_up_e_down(self):
        url = "https://kuma.test/api/push/TOKEN123"
        m.kuma_push(url, True, 2.345, "OK 2026.10.14, 2 alunni", self.transport)
        m.kuma_push(url, False, 1.0, "RuntimeError: " + "x" * 500, self.transport)
        self.assertEqual(self.chiamate[0], {"status": "up", "msg": "OK 2026.10.14, 2 alunni", "ping": "2345"})
        self.assertEqual(self.chiamate[1]["status"], "down")
        self.assertLessEqual(len(self.chiamate[1]["msg"]), 200)

    def test_url_copiato_da_kuma_con_query(self):
        m.kuma_push("https://kuma.test/api/push/T?status=up&msg=OK&ping=", False, 0.5, "errore", self.transport)
        self.assertEqual(self.chiamate[0], {"status": "down", "msg": "errore", "ping": "500"})

    def test_senza_url_e_errore_non_blocca_ne_logga_il_token(self):
        m.kuma_push(None, True, 1, "x", self.transport)
        self.assertEqual(self.chiamate, [])
        with self.assertLogs(m.log, "WARNING") as cm:
            m.kuma_push("https://kuma.test/api/push/SEGRETO/boom", True, 1, "x", self.transport)
        self.assertNotIn("SEGRETO", "".join(cm.output))


class TestAgganci(unittest.TestCase):
    def test_notifiche_ed_errori_contati(self):
        mt = nuove_metriche()

        def gestisci(req):
            return httpx.Response(500 if req.url.path.endswith("rotto") else 200, json=[])
        cfg = {"homeassistant": {"url": "http://ha.test", "token": "t", "service": "ok",
                                 "destinatari": [{"service": "ok", "tipi": None, "alunni": None},
                                                 {"service": "rotto", "tipi": ["voti"], "alunni": None}]}}
        n = m.Notifier(cfg, False, transport=httpx.MockTransport(gestisci))
        with self.assertLogs(m.log, "INFO"):
            n.send("T", "M", kind="voti", alunno="Anna")
            n.send("T", "M")
        self.assertEqual(mt.get("didup_notifications_total", alunno="Anna", tipo="voti"), 1)
        self.assertEqual(mt.get("didup_notifications_total", alunno="-", tipo="sistema"), 1)
        self.assertEqual(mt.get("didup_notification_errors_total", servizio="notify.rotto"), 1)

    def test_dry_run_non_conta(self):
        mt = nuove_metriche()
        n = m.Notifier({"homeassistant": {"url": "http://ha.test", "token": "t", "service": "ok"}}, True)
        with self.assertLogs(m.log, "INFO"):
            n.send("T", "M", kind="voti", alunno="Anna")
        self.assertIsNone(mt.get("didup_notifications_total", alunno="Anna", tipo="voti"))


if __name__ == "__main__":
    unittest.main()
