"""Login SSO di Argo rifiutato: avvisi della pagina nel log (senza credenziali), un solo nuovo tentativo."""
import asyncio
import logging
import sys
import unittest
from pathlib import Path
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import didup_calendar_sync as m  # noqa: E402
from didupwrapper.client import DiDUPClient  # noqa: E402

PAGINA = """<!DOCTYPE html><html><head><title>Argo - Accedi</title>
<style>.alert{color:red}</style><script>var err = "non questo";</script></head><body>
<form><input name="username" value="papa"><input type="password" name="password" value="segreta1">
<label>Codice scuola</label></form>
<div class="alert alert-danger" role="alert"><strong>Attenzione:</strong> troppi tentativi per papa,
riprova più tardi<br></div><p id="help">Hai dimenticato la password?</p>
<span class="invalid-feedback"></span></body></html>"""

SSO_FALLITO = "Login SSO fallito: credenziali errate o flusso cambiato"


class TestAvvisi(unittest.TestCase):
    def test_estrae_titolo_e_avvisi(self):
        self.assertEqual(m.avvisi_pagina(PAGINA),
                         "Argo - Accedi | Attenzione: | troppi tentativi per papa, riprova più tardi")

    def test_niente_valori_del_modulo(self):
        t = m.avvisi_pagina(PAGINA)
        for x in ("segreta1", "non questo", "Codice scuola", "dimenticato"):
            self.assertNotIn(x, t)

    def test_html_rotto(self):
        self.assertEqual(m.avvisi_pagina("<div class='error'>Credenziali non valide"), "Credenziali non valide")
        self.assertEqual(m.avvisi_pagina(""), "")


class TestClientSSO(unittest.TestCase):
    def chiama(self, gestore, method="POST"):
        async def run():
            async with m._ClientSSO(transport=httpx.MockTransport(gestore)) as c:
                return await c.request(method, "https://www.portaleargo.it/auth/sso/login")
        m._SSO["avviso"] = None
        asyncio.run(run())
        return m._SSO["avviso"]

    def test_post_rifiutato_registra_avvisi(self):
        self.assertIn("troppi tentativi", self.chiama(lambda r: httpx.Response(200, text=PAGINA)))

    def test_post_rifiutato_senza_avvisi(self):
        self.assertEqual(self.chiama(lambda r: httpx.Response(200, text="<p>boh</p>")),
                         "pagina senza avvisi (HTTP 200)")

    def test_redirect_e_get_ignorati(self):
        self.assertIsNone(self.chiama(lambda r: httpx.Response(302, headers={"location": "/ok"})))
        self.assertIsNone(self.chiama(lambda r: httpx.Response(200, text=PAGINA), method="GET"))

    def test_didupwrapper_usa_il_client_sso(self):
        self.assertIs(m._auth_argo.httpx.AsyncClient, m._ClientSSO)
        self.assertIs(m._auth_argo.httpx.Response, httpx.Response)


class TestRitentaLogin(unittest.TestCase):
    def setUp(self):
        self.attese = []

        async def dormi(s):
            self.attese.append(s)
        p = mock.patch.object(m.asyncio, "sleep", dormi)
        p.start()
        self.addCleanup(p.stop)
        self.cli = m.MultiProfiloClient("SC1", "papa", "segreta1")
        self.chiamate = 0

    def login(self, esiti, avviso="troppi tentativi per papa (segreta1)"):
        async def finto(_self):
            self.chiamate += 1
            e = esiti.pop(0)
            if isinstance(e, BaseException):
                m._SSO["avviso"] = avviso
                raise e
        with mock.patch.object(DiDUPClient, "login", finto):
            return asyncio.run(self.cli.login())

    def test_riesce_al_secondo_tentativo(self):
        with self.assertLogs(m.log, logging.WARNING) as lg:
            self.login([m.AuthError(SSO_FALLITO, status_code=200), None])
        self.assertEqual((self.chiamate, self.attese), (2, [60]))
        self.assertEqual(lg.records[0].getMessage(), "Argo: login SSO rifiutato (troppi tentativi per *** "
                                                     "(***)), nuovo tentativo tra 60 s")

    def test_due_rifiuti_con_avviso_nel_messaggio(self):
        with self.assertLogs(m.log, logging.WARNING), self.assertRaises(m.AuthError) as cm:
            self.login([m.AuthError(SSO_FALLITO, status_code=200)] * 2)
        self.assertEqual(self.chiamate, 2)
        self.assertEqual(m.descrivi_errore(cm.exception),
                         f"login Argo fallito: {SSO_FALLITO} (Argo: troppi tentativi per *** (***))")
        self.assertNotIn("segreta1", m.descrivi_errore(cm.exception))

    def test_altri_errori_non_ritentati(self):
        for e in (m.AuthError("Credenziali assenti"), m.DiDUPError("x", status_code=401)):
            self.chiamate = 0
            with self.assertRaises(type(e)):
                self.login([e, None])
            self.assertEqual(self.chiamate, 1)
        self.assertEqual(self.attese, [])


if __name__ == "__main__":
    unittest.main()


class TestSsoInterrotto(unittest.TestCase):
    def setUp(self):
        self.attese = []

        async def dormi(s):
            self.attese.append(s)
        p = mock.patch.object(m.asyncio, "sleep", dormi)
        p.start()
        self.addCleanup(p.stop)
        self.cli = m.MultiProfiloClient("SC1", "papa", "segreta1")
        self.cli.tentativi, self.cli.attesa_secondi = 3, 30
        self.chiamate = 0

    def login(self, esiti):
        async def finto(_self):
            self.chiamate += 1
            e = esiti.pop(0)
            if isinstance(e, BaseException):
                raise e
        with mock.patch.object(DiDUPClient, "login", finto):
            return asyncio.run(self.cli.login())

    def test_classificazione(self):
        for msg in ("Catena OAuth interrotta (redirect 3)", "Avvio OAuth: redirect mancante",
                    "Avvio OAuth: 'login_challenge' non trovato"):
            e = m.AuthError(msg)
            self.assertTrue(m.errore_temporaneo(e), msg)
            self.assertEqual(m.descrivi_errore(e), f"login SSO di Argo interrotto: {msg}")
        for msg in (SSO_FALLITO, "Credenziali assenti: impossibile effettuare il login"):
            self.assertFalse(m.errore_temporaneo(m.AuthError(msg, status_code=500)), msg)

    def test_ritentato_come_5xx(self):
        with self.assertLogs(m.log, logging.WARNING) as lg:
            self.login([m.AuthError("Catena OAuth interrotta (redirect 3)")] * 2 + [None])
        self.assertEqual((self.chiamate, self.attese), (3, [30, 90]))
        self.assertIn("Argo: login SSO di Argo interrotto: Catena OAuth interrotta (redirect 3), "
                      "nuovo tentativo tra 30 s (2/3)", lg.output[0])

    def test_esauriti_i_tentativi_il_giro_non_riprova(self):
        with self.assertLogs(m.log, logging.WARNING), self.assertRaises(m.AuthError):
            self.login([m.AuthError("Catena OAuth interrotta (redirect 3)")] * 3)
        self.assertEqual(self.chiamate, 3)
        self.assertFalse(self.cli._riprova)

    def test_log_account_senza_consiglio_credenziali(self):
        try:
            raise m.AuthError("Catena OAuth interrotta (redirect 3)")
        except m.AuthError as e:
            with self.assertLogs(m.log, logging.DEBUG) as lg:
                m.registra_errore_account("SC1", e)
        self.assertEqual(lg.records[0].getMessage(),
                         "[SC1] sync fallita, Argo non raggiungibile: login SSO di Argo interrotto: "
                         "Catena OAuth interrotta (redirect 3)")


PAGINA_CONFERMA = """<!DOCTYPE html><html><head><title>Accedi con Argo Software</title></head><body>
<div class="card" data-auth-completed>
  <p data-auth-completed-status>Autenticazione riuscita. Ti stiamo riportando all'applicazione…</p>
  <a
     class="btn" data-auth-app-redirect
     href="https://auth.portaleargo.it/oauth2/auth?client_id=x&amp;consent_verifier=VER123">Continua</a>
</div><a href="https://www.portaleargo.it">home</a></body></html>"""


class TestPaginaConferma(unittest.TestCase):
    def test_estrae_il_link(self):
        self.assertEqual(m.redirect_pagina_conferma(PAGINA_CONFERMA, "https://www.portaleargo.it/auth/sso/consent/"),
                         "https://auth.portaleargo.it/oauth2/auth?client_id=x&consent_verifier=VER123")
        self.assertEqual(m.redirect_pagina_conferma('<a data-auth-app-redirect href="/oauth2/auth?a=1">x</a>',
                                                    "https://auth.portaleargo.it/x/y"),
                         "https://auth.portaleargo.it/oauth2/auth?a=1")
        self.assertIsNone(m.redirect_pagina_conferma(PAGINA, "https://x/"))
        self.assertIsNone(m.redirect_pagina_conferma("", "https://x/"))

    def chiama(self, gestore, method="GET"):
        async def run():
            async with m._ClientSSO(transport=httpx.MockTransport(gestore)) as c:
                return await c.request(method, "https://www.portaleargo.it/auth/sso/consent/?consent_challenge=c")
        return asyncio.run(run())

    def test_pagina_diventa_redirect(self):
        r = self.chiama(lambda req: httpx.Response(200, text=PAGINA_CONFERMA, headers={"set-cookie": "a=1; Path=/"}))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["location"], "https://auth.portaleargo.it/oauth2/auth?client_id=x&consent_verifier=VER123")
        self.assertEqual(r.headers.get_list("set-cookie"), ["a=1; Path=/"])

    def test_altre_pagine_invariate(self):
        r = self.chiama(lambda req: httpx.Response(200, text=PAGINA))
        self.assertEqual(r.status_code, 200)
        r = self.chiama(lambda req: httpx.Response(302, headers={"location": "https://x/ok"}))
        self.assertEqual(r.headers["location"], "https://x/ok")

    def test_flusso_completo_di_didupwrapper(self):
        """Il vero Autenticatore._ottieni_code contro un SSO che si comporta come quello di Argo oggi."""
        passi = []

        def sso(req):
            u = str(req.url)
            passi.append(f"{req.method} {req.url.host}{req.url.path}")
            if req.url.host == "auth.portaleargo.it" and "consent_verifier" in u:      # passo 4
                return httpx.Response(302, headers={"location": "it.argosoft.didup.famiglia.new://login-callback?code=CODICE&state=s"})
            if req.url.host == "auth.portaleargo.it" and "login_verifier" in u:        # passo 2
                return httpx.Response(302, headers={"location": "https://www.portaleargo.it/auth/sso/consent/?consent_challenge=cc",
                                                    "set-cookie": "oauth2_consent_csrf=z; Path=/"})
            if req.url.host == "auth.portaleargo.it":                                  # passo 0
                return httpx.Response(302, headers={"location": "https://www.portaleargo.it/auth/sso/login/?login_challenge=LC",
                                                    "set-cookie": "oauth2_authentication_csrf=y; Path=/"})
            if req.url.path == "/auth/sso/login":                                      # passo 1: credenziali
                return httpx.Response(302, headers={"location": "https://auth.portaleargo.it/oauth2/auth?login_verifier=LV"})
            if req.url.path == "/auth/sso/consent/":                                   # passo 3: la pagina nuova
                return httpx.Response(200, text=PAGINA_CONFERMA.replace("client_id=x&amp;", ""))
            return httpx.Response(404)

        class ClientFinto(m._ClientSSO):
            def __init__(self, *a, **kw):
                super().__init__(*a, transport=httpx.MockTransport(sso), **kw)

        from didupwrapper.auth import ArgoConfig, Autenticatore, Credenziali
        aut = Autenticatore(Credenziali("SC1", "papa", "segreta1"), ArgoConfig())
        with mock.patch.object(m._auth_argo.httpx, "AsyncClient", ClientFinto):
            code = asyncio.run(aut._ottieni_code(aut._genera_login_link()))
        self.assertEqual(code, "CODICE")
        self.assertEqual(len(passi), 5)
