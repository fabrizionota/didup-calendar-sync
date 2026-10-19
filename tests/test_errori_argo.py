"""Errori temporanei di Argo: retry nello stesso giro, avviso dopo N giri falliti, log in una riga."""
import asyncio
import logging
import sys
import unittest
from pathlib import Path
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import didup_calendar_sync as m  # noqa: E402
from didupwrapper.client import DiDUPClient  # noqa: E402
from test_snapshot import CONFIG, carica  # noqa: E402

PAGINA_500 = "<!DOCTYPE html><html><body><h1>500 Internal Server Error</h1></body></html>"


def err(status, msg=PAGINA_500, url="https://www.portaleargo.it/appfamiglia/api/rest/login?x=1"):
    return m.DiDUPError(msg, status_code=status, request_url=url)


class TestErrori(unittest.TestCase):
    def test_temporanei(self):
        for e in (err(500), err(502), err(503), err(504), httpx.ReadTimeout("t"), httpx.ConnectError("c")):
            self.assertTrue(m.errore_temporaneo(e), e)
        for e in (err(401), err(404), err(None), ValueError("x"), RuntimeError("x")):
            self.assertFalse(m.errore_temporaneo(e), e)

    def test_descrizione_in_una_riga(self):
        self.assertEqual(m.descrivi_errore(err(500)), "HTTP 500 su login")
        self.assertEqual(m.descrivi_errore(err(401, "Credenziali\n errate")), "HTTP 401 Credenziali errate su login")
        self.assertEqual(m.descrivi_errore(httpx.ReadTimeout("t")), "ReadTimeout (rete)")
        self.assertEqual(m.descrivi_errore(ValueError("boh")), "ValueError: boh")
        self.assertNotIn("x=1", m.descrivi_errore(err(503)))


class FintoClient(m.MultiProfiloClient):
    def __init__(self, risposte, tentativi=3, attesa=30):  # niente login, niente rete
        self.risposte, self.chiamate = list(risposte), 0
        self.tentativi, self.attesa_secondi = tentativi, attesa


class TestRetry(unittest.TestCase):
    def setUp(self):
        self.attese = []

        async def dormi(s):
            self.attese.append(s)
        p = mock.patch.object(m.asyncio, "sleep", dormi)
        p.start()
        self.addCleanup(p.stop)

    def chiama(self, cli):
        async def finto(_self, method, path, **kw):
            cli.chiamate += 1
            r = cli.risposte.pop(0)
            if isinstance(r, BaseException):
                raise r
            return r
        with mock.patch.object(DiDUPClient, "_request", finto):
            return asyncio.run(cli._request("POST", "login"))

    def test_riesce_dopo_un_errore(self):
        cli = FintoClient([err(500), {"ok": 1}])
        with self.assertLogs(m.log, logging.WARNING) as lg:
            self.assertEqual(self.chiama(cli), {"ok": 1})
        self.assertEqual((cli.chiamate, self.attese), (2, [30]))
        self.assertIn("HTTP 500 su login, nuovo tentativo tra 30 s (2/3)", lg.output[0])
        self.assertTrue(cli._riprova)

    def test_attesa_crescente_poi_fallisce_subito(self):
        cli = FintoClient([err(503), httpx.ReadTimeout("t"), err(500), err(500)])
        with self.assertRaises(m.DiDUPError), self.assertLogs(m.log, logging.WARNING):
            self.chiama(cli)
        self.assertEqual((cli.chiamate, self.attese), (3, [30, 90]))
        self.assertFalse(cli._riprova)
        with self.assertRaises(m.DiDUPError):  # resto del giro: nessun nuovo tentativo
            self.chiama(cli)
        self.assertEqual((cli.chiamate, self.attese), (4, [30, 90]))

    def test_errori_non_temporanei_non_ripetuti(self):
        for e in (err(401), err(404), ValueError("x")):
            cli = FintoClient([e, {"ok": 1}])
            with self.assertRaises(type(e)):
                self.chiama(cli)
            self.assertEqual(cli.chiamate, 1)
        self.assertEqual(self.attese, [])

    def test_un_solo_tentativo(self):
        cli = FintoClient([err(500), {"ok": 1}], tentativi=1)
        with self.assertRaises(m.DiDUPError):
            self.chiama(cli)
        self.assertEqual(cli.chiamate, 1)

    def test_client_argo_usa_config_rete(self):
        acc = {"codice_scuola": "SC1", "username": "u", "password": "p", "password_env": "PW"}
        cli = m.client_argo(acc, {"tentativi": 5, "attesa_secondi": 7})
        self.assertEqual((cli.tentativi, cli.attesa_secondi), (5, 7))
        self.assertEqual(m.client_argo(acc).tentativi, 3)


class FintoNotifier:
    def __init__(self):
        self.inviati = []

    def send(self, title, message, **kw):
        self.inviati.append(message)


class TestAvvisoDopoNGiri(unittest.TestCase):
    def setUp(self):
        self.state = mock.Mock(data={"seen": {}, "error": False})
        self.n = FintoNotifier()

    def giro(self, errore, soglia=2):
        m.aggiorna_errori(self.state, self.n, errore, soglia)

    def test_un_giro_fallito_non_avvisa(self):
        self.giro("SC1: HTTP 500 su login")
        self.giro(None)
        self.assertEqual(self.n.inviati, [])
        self.assertEqual((self.state.data["error"], self.state.data["fallimenti"]), (False, 0))

    def test_avviso_alla_soglia_una_volta_e_ripristino(self):
        self.giro("e1")
        self.assertTrue(self.state.data["error"])        # l'healthcheck vede subito l'errore
        self.giro("e2")
        self.giro("e3")
        self.assertEqual(self.n.inviati, ["❌ Sync fallita (2 giri di fila): e2"])
        self.giro(None)
        self.assertEqual(self.n.inviati[-1], "✅ Sincronizzazione tornata a funzionare")
        self.assertEqual(len(self.n.inviati), 2)
        self.giro(None)
        self.assertEqual(len(self.n.inviati), 2)

    def test_soglia_uno_avvisa_subito(self):
        self.giro("e1", soglia=1)
        self.assertEqual(self.n.inviati, ["❌ Sync fallita: e1"])

    def test_state_vecchio_con_errore_gia_notificato(self):
        self.state.data = {"seen": {}, "error": True}    # versione precedente: avviso già partito
        self.giro("ancora")
        self.assertEqual(self.n.inviati, [])
        self.giro(None)
        self.assertEqual(self.n.inviati, ["✅ Sincronizzazione tornata a funzionare"])


class TestConfig(unittest.TestCase):
    def test_default(self):
        c = carica(CONFIG)
        self.assertEqual(c["notifiche"]["dopo_fallimenti"], 2)
        self.assertEqual(c["rete"], {"tentativi": 3, "attesa_secondi": 30})

    def test_valori(self):
        c = carica("[notifiche]\ndopo_fallimenti = 4\n[rete]\ntentativi = 1\nattesa_secondi = 0\n" + CONFIG)
        self.assertEqual(c["notifiche"]["dopo_fallimenti"], 4)
        self.assertEqual(c["rete"], {"tentativi": 1, "attesa_secondi": 0})

    def test_valori_non_validi(self):
        for testo, chiave in (("[notifiche]\ndopo_fallimenti = 0\n", "dopo_fallimenti"),
                              ('[notifiche]\ndopo_fallimenti = "2"\n', "dopo_fallimenti"),
                              ("[rete]\ntentativi = 0\n", "tentativi"),
                              ("[rete]\nattesa_secondi = -1\n", "attesa_secondi")):
            with self.assertRaisesRegex(ValueError, chiave):
                carica(testo + CONFIG)


class TestLogMain(unittest.TestCase):
    def test_sync_fallita_senza_traceback(self):
        async def run_once(*a):
            raise m.SyncFallita("SC1: HTTP 500 su login")
        with mock.patch.object(m, "run_once", run_once), mock.patch.object(m, "load_config", return_value={
                "alunni": [], "notifiche": {"dopo_fallimenti": 2}, "monitoraggio": {}}), \
                mock.patch.object(m, "riepilogo_avvio", return_value=""), \
                mock.patch.object(m, "State") as st, mock.patch.object(m, "Notifier"), \
                mock.patch.object(m, "kuma_push"), mock.patch.object(m, "registra_giro"), \
                mock.patch.object(sys, "argv", ["x"]), mock.patch.dict(m.os.environ, {}, clear=True), \
                self.assertLogs(m.log, logging.ERROR) as lg:
            st.return_value.data = {"seen": {}, "error": False}
            m.main()
        self.assertEqual([r.getMessage() for r in lg.records], ["Sync fallita: SC1: HTTP 500 su login"])
        self.assertIsNone(lg.records[0].exc_info)
        self.assertEqual(st.return_value.data["fallimenti"], 1)


if __name__ == "__main__":
    unittest.main()
