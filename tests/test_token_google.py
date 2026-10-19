"""Token Google scaduto o revocato: una riga chiara nel log e avviso subito, senza aspettare la soglia."""
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from google.auth.exceptions import RefreshError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import didup_calendar_sync as m  # noqa: E402

TOKEN = {"token": "x", "refresh_token": "r", "client_id": "c", "client_secret": "s",
         "token_uri": "https://oauth2.googleapis.com/token",
         "scopes": ["https://www.googleapis.com/auth/calendar.events"], "expiry": "2020-01-01T00:00:00Z"}


class TestGoogleCreds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.token = Path(self.tmp.name) / "token.json"
        self.cfg = {"google": {"token_file": str(self.token), "client_secret_file": "x"}}

    def test_token_revocato(self):
        self.token.write_text(json.dumps(TOKEN))
        errore = RefreshError("invalid_grant: Token has been expired or revoked.", {"error": "invalid_grant"})
        with mock.patch("google.oauth2.credentials.Credentials.refresh", side_effect=errore), \
                self.assertRaises(m.TokenGoogleNonValido) as cm:
            m.google_creds(self.cfg)
        msg = str(cm.exception)
        self.assertIn("token Google scaduto o revocato (invalid_grant: Token has been expired or revoked.)", msg)
        self.assertIn("pocs/04_google_auth.py --login", msg)
        self.assertIn("stato Test", msg)
        self.assertIsNone(cm.exception.__cause__)
        self.assertEqual(json.loads(self.token.read_text()), TOKEN)   # token non sovrascritto

    def test_token_assente(self):
        with self.assertRaisesRegex(m.TokenGoogleNonValido, "assente o non valido"):
            m.google_creds(self.cfg)


class TestMain(unittest.TestCase):
    def giri(self, n):
        async def run_once(*a):
            raise m.TokenGoogleNonValido("token Google scaduto o revocato (invalid_grant): rifai il login")
        with mock.patch.object(m, "run_once", run_once), mock.patch.object(m, "load_config", return_value={
                "alunni": [], "notifiche": {"dopo_fallimenti": 3}, "monitoraggio": {}}), \
                mock.patch.object(m, "riepilogo_avvio", return_value=""), \
                mock.patch.object(m, "State") as st, mock.patch.object(m, "Notifier") as nt, \
                mock.patch.object(m, "kuma_push"), mock.patch.object(m, "registra_giro"), \
                mock.patch.object(m.time, "sleep"), \
                mock.patch.object(sys, "argv", ["x", "--loop", "60"]), \
                mock.patch.dict(m.os.environ, {}, clear=True), \
                mock.patch.object(m, "avvia_server_metriche"), \
                self.assertLogs(m.log, logging.ERROR) as lg:
            st.return_value.data = {"seen": {}, "error": False}
            stop = mock.Mock(side_effect=[None] * (n - 1) + [KeyboardInterrupt])
            st.return_value.save = stop
            with self.assertRaises(KeyboardInterrupt):
                m.main()
        return lg, nt.return_value.send

    def test_avviso_al_primo_giro_senza_traceback(self):
        lg, send = self.giri(2)
        self.assertEqual([r.getMessage() for r in lg.records],
                         ["Sync fallita: token Google scaduto o revocato (invalid_grant): rifai il login"] * 2)
        self.assertTrue(all(r.exc_info is None for r in lg.records))
        send.assert_called_once_with("Argo sync", "❌ Sync fallita: token Google scaduto o revocato "
                                                  "(invalid_grant): rifai il login")


if __name__ == "__main__":
    unittest.main()
