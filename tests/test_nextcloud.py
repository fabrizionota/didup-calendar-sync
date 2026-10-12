"""Archivio allegati su Nextcloud: test offline contro un finto server WebDAV in memoria
(httpx.MockTransport), con le stesse risposte di Nextcloud (207, 201, 405, 404, 409, 401)."""
import asyncio
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import didup_calendar_sync as m  # noqa: E402
from didupwrapper.models import DashboardResponse  # noqa: E402
from test_snapshot import CONFIG, ORARIO, OGGI, FakeCli, carica, cfg, dash_allegati, raw  # noqa: E402

URL, UTENTE, PASSWORD = "https://cloud.test", "mario", "app-pass"
DAV = f"/remote.php/dav/files/{UTENTE}"
NCFG = {"url": URL + "/", "utente": UTENTE, "password": PASSWORD, "password_env": "NEXTCLOUD_APP_PASSWORD"}


class FakeDav:
    """Server WebDAV minimo con la semantica di Nextcloud per i metodi usati dallo script."""

    def __init__(self, password=PASSWORD, guasti=()):
        self.password, self.guasti = password, set(guasti)  # guasti: nomi file su cui PUT dà 500
        self.cartelle = {""}
        self.file: dict[str, dict] = {}
        self.chiamate: list[tuple[str, str]] = []
        self.condivisioni: dict[str, list[tuple[str, str | None]]] = {}
        self.password_obbligatoria = False
        self._id = 100

    def aggiungi(self, percorso, dati=b"x", chiave=None):
        """File già presente (es. caricato a mano); le cartelle intermedie vengono create."""
        parti = percorso.split("/")
        for i in range(1, len(parti)):
            self.cartelle.add("/".join(parti[:i]))
        self._id += 1
        self.file[percorso] = {"dati": dati, "id": str(self._id), "argo_key": chiave, "mime": "x"}

    def transport(self):
        return httpx.MockTransport(self.gestisci)

    def gestisci(self, req: httpx.Request) -> httpx.Response:
        assert req.url.host == "cloud.test"
        if req.headers.get("authorization") != httpx.BasicAuth(UTENTE, self.password)._auth_header:
            return httpx.Response(401)
        if req.url.path.startswith("/ocs/"):
            return self.ocs(req)
        assert req.url.raw_path.decode().startswith(DAV), req.url.raw_path
        p = unquote(req.url.raw_path.decode()[len(DAV):]).strip("/")
        self.chiamate.append((req.method, p))
        padre = p.rpartition("/")[0]
        if req.url.path == "/ocs/v2.php/apps/files_sharing/api/v1/shares":
            return self.ocs(req)
        if req.method == "PROPFIND":
            if p in self.cartelle:
                return self._multistatus(None)
            if p in self.file:
                return self._multistatus(self.file[p])
            return httpx.Response(404)
        if req.method == "MKCOL":
            if p in self.cartelle or p in self.file:
                return httpx.Response(405)
            if padre not in self.cartelle:
                return httpx.Response(409)
            self.cartelle.add(p)
            return httpx.Response(201)
        if req.method == "PUT":
            if padre not in self.cartelle:
                return httpx.Response(409)
            if p.rpartition("/")[2] in self.guasti:
                return httpx.Response(500)
            nuovo = p not in self.file
            if nuovo:
                self._id += 1
                self.file[p] = {"id": str(self._id), "argo_key": None}
            self.file[p].update(dati=req.content, mime=req.headers.get("content-type"))
            return httpx.Response(201 if nuovo else 204)
        if req.method == "PROPPATCH":
            if p not in self.file:
                return httpx.Response(404)
            k = re.search(r"<a:argo_key>(.*?)</a:argo_key>", req.content.decode())
            self.file[p]["argo_key"] = k.group(1).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            return self._multistatus(None)
        return httpx.Response(405)

    def ocs(self, req: httpx.Request) -> httpx.Response:
        """API OCS files_sharing: GET elenca le condivisioni di un path, POST ne crea una."""
        self.chiamate.append(("OCS " + req.method, req.url.params.get("path", "")))
        assert req.headers.get("ocs-apirequest") == "true"
        if req.method == "GET":
            path = req.url.params["path"].lstrip("/")
            dati = [{"share_type": 3, "url": u, "expiration": sc} for u, sc in self.condivisioni.get(path, [])]
            return self._ocs_risposta(dati)
        from urllib.parse import parse_qs
        form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        if self.password_obbligatoria:
            return httpx.Response(403, json={"ocs": {"meta": {"statuscode": 403, "message":
                                                              "Password obbligatoria per i link pubblici"},
                                                     "data": []}})
        path = form["path"].lstrip("/")
        assert (form["shareType"], form["permissions"]) == ("3", "1")
        assert path in self.file, path
        url = f"{URL}/s/tok{len(self.condivisioni) + 1}"
        self.condivisioni.setdefault(path, []).append((url, form.get("expireDate")))
        return self._ocs_risposta({"id": 1, "share_type": 3, "url": url})

    @staticmethod
    def _ocs_risposta(dati):
        return httpx.Response(200, json={"ocs": {"meta": {"status": "ok", "statuscode": 200}, "data": dati}})

    @staticmethod
    def _multistatus(f):
        if f is None:  # cartella: nessun fileid/argo_key utile ai test
            props = "<d:propstat><d:prop><oc:fileid>1</oc:fileid></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
        else:
            key = (f"<a:argo_key>{f['argo_key']}</a:argo_key>" if f["argo_key"] else "")
            mancante = "" if f["argo_key"] else (
                "<d:propstat><d:prop><a:argo_key/></d:prop><d:status>HTTP/1.1 404 Not Found</d:status></d:propstat>")
            props = (f"<d:propstat><d:prop><oc:fileid>{f['id']}</oc:fileid>{key}</d:prop>"
                     f"<d:status>HTTP/1.1 200 OK</d:status></d:propstat>{mancante}")
        xml = (f'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:oc="{m.NS_OC}" '
               f'xmlns:a="{m.NS_ARGO}"><d:response><d:href>/x</d:href>{props}</d:response></d:multistatus>')
        return httpx.Response(207, content=xml.encode(), headers={"content-type": "application/xml"})


def dash(*circolari):
    """Dashboard con circolari [(data, messaggio, [(nome file, pk)])]."""
    d = raw()
    d["pk"] = "SCHEDA"
    d["bacheca"] = [{"datEvento": g, "data": g, "messaggio": msg, "autore": "Dir",
                     "listaAllegati": [{"nomeFile": n, "pk": pk} for n, pk in allegati]}
                    for g, msg, allegati in circolari]
    return DashboardResponse.model_validate(d)


class Base(unittest.TestCase):
    def setUp(self):
        self.acfg = {"allegati": {"archivio": "nextcloud", "drive": False, "cartella": "Scuola",
                                  "sottocartella": "Anna", "max_per_giro": 30, "nextcloud": NCFG}}
        self.st = m.State(Path("/nonexistent/state.json"))
        self.dav = FakeDav()
        self._scarica = m.scarica

        async def finta_scarica(url):
            return url.encode(), "application/pdf"
        m.scarica = finta_scarica

    def tearDown(self):
        m.scarica = self._scarica

    def nc(self, dry=False, dav=None, **opz):
        self.acfg["allegati"]["nextcloud"] = {**NCFG, **opz}
        return m.Nextcloud({**NCFG, **opz}, dry, transport=(dav or self.dav).transport())

    def archivia(self, nc=None, d=None, cli=None):
        return asyncio.run(m.archivia_allegati(cli or FakeCli(), d or dash_allegati(), "V", self.acfg,
                                               nc or self.nc(), self.st))


class TestNextcloudArchivio(Base):
    def test_carica_percorso_link_e_chiave(self):
        links = self.archivia()
        self.assertEqual(sorted(self.dav.file), [
            "Scuola/Anna/2026/09 - Settembre/2026-09-30 info__x.pdf",
            "Scuola/Anna/2026/09 - Settembre/2026-09-30 modulo.pdf",
            "Scuola/Anna/2026/10 - Ottobre/2026-10-12 circ83.pdf",
        ])
        f = self.dav.file["Scuola/Anna/2026/10 - Ottobre/2026-10-12 circ83.pdf"]
        self.assertEqual((f["dati"], f["mime"]), (b"https://files/A83", "application/pdf"))
        b = dash_allegati().bacheca[0]
        k = m.chiave_allegato(b, b.lista_allegati[0])
        self.assertEqual(f["argo_key"], k)                       # proprietà WebDAV per ritrovarlo
        self.assertEqual(links[k], f"{URL}/f/{f['id']}")         # link interno, niente share pubblico
        self.assertEqual(set(self.st.data["allegati_nextcloud"]), set(links))
        self.assertNotIn("allegati", self.st.data)               # lo stato di Drive non viene toccato

    def test_cartelle_create_una_volta_per_giro(self):
        self.archivia()
        mkcol = [p for metodo, p in self.dav.chiamate if metodo == "MKCOL"]
        self.assertEqual(len(mkcol), len(set(mkcol)))
        self.assertIn("Scuola/Anna/2026/09 - Settembre", mkcol)

    def test_cartelle_esistenti(self):
        self.dav.aggiungi("Scuola/Anna/2026/10 - Ottobre/altro.pdf")  # albero già creato a mano
        self.archivia()
        self.assertIn("Scuola/Anna/2026/10 - Ottobre/2026-10-12 circ83.pdf", self.dav.file)
        self.assertIn("Scuola/Anna/2026/10 - Ottobre/altro.pdf", self.dav.file)

    def test_secondo_giro_niente_richieste(self):
        self.archivia()
        dav2 = FakeDav()
        self.archivia(self.nc(dav=dav2))
        self.assertEqual(dav2.chiamate, [])                      # tutto già in state.json

    def test_state_perso_non_duplica(self):
        prima = self.archivia()
        self.st.data.clear()
        n_file, n_chiamate = len(self.dav.file), len(self.dav.chiamate)
        dopo = self.archivia(self.nc())                          # stesso server, state.json vuoto
        self.assertEqual(dopo, prima)
        self.assertEqual(len(self.dav.file), n_file)
        self.assertEqual({metodo for metodo, _ in self.dav.chiamate[n_chiamate:]}, {"PROPFIND"})

    def test_omonimi_stesso_giorno(self):
        d = dash(("2026-10-12", "Circ. 1", [("modulo.pdf", "P1")]),
                 ("2026-10-12", "Circ. 2", [("modulo.pdf", "P2")]))
        links = self.archivia(d=d)
        cart = "Scuola/Anna/2026/10 - Ottobre/"
        self.assertEqual(self.dav.file[cart + "2026-10-12 modulo.pdf"]["dati"], b"https://files/P1")
        self.assertEqual(self.dav.file[cart + "2026-10-12 modulo (2).pdf"]["dati"], b"https://files/P2")
        self.assertEqual(len(set(links.values())), 2)
        self.st.data.clear()
        self.assertEqual(self.archivia(self.nc(), d=d), links)  # ritrovati entrambi, giusti

    def test_file_estraneo_non_sovrascritto(self):
        cart = "Scuola/Anna/2026/10 - Ottobre/"
        self.dav.aggiungi(cart + "2026-10-12 circ83.pdf", dati=b"MIO")  # stesso nome, senza argo_key
        self.archivia()
        self.assertEqual(self.dav.file[cart + "2026-10-12 circ83.pdf"]["dati"], b"MIO")
        self.assertEqual(self.dav.file[cart + "2026-10-12 circ83 (2).pdf"]["dati"], b"https://files/A83")

    def test_nomi_con_caratteri_speciali(self):
        d = dash(("2026-10-12", "Circ.", [("Uscita #3 è 100% ok?.pdf", "S1"), ("senza estensione", "S2")]))
        self.archivia(d=d)
        cart = "Scuola/Anna/2026/10 - Ottobre/"
        self.assertIn(cart + "2026-10-12 Uscita #3 è 100% ok_.pdf", self.dav.file)
        self.assertIn(cart + "2026-10-12 senza estensione", self.dav.file)

    def test_dry_run_solo_lettura(self):
        links = self.archivia(self.nc(dry=True))
        self.assertEqual({metodo for metodo, _ in self.dav.chiamate}, {"PROPFIND"})
        self.assertEqual((self.dav.file, links), ({}, {}))
        self.assertEqual(self.st.data["allegati_nextcloud"], {})

    def test_errore_su_un_file_non_blocca_gli_altri(self):
        self.dav.guasti.add("2026-09-30 modulo.pdf")
        links = self.archivia()
        self.assertEqual(len(links), 2)
        self.assertNotIn("Scuola/Anna/2026/09 - Settembre/2026-09-30 modulo.pdf", self.dav.file)
        self.dav.guasti.clear()
        self.assertEqual(len(self.archivia(self.nc())), 3)       # riprovato al giro dopo

    def test_limite_per_giro(self):
        self.acfg["allegati"]["max_per_giro"] = 2
        self.assertEqual(len(self.archivia()), 2)
        self.assertEqual(len(self.archivia(self.nc())), 3)

    def test_link_in_notifica_ed_evento(self):
        d = dash_allegati()
        links = self.archivia(d=d)
        s = m.build_snapshot(d, ORARIO, "V", cfg(), OGGI, link_allegati=links)
        n = next(x for x in s.notifiche if x.kind == "bacheca" and "Circ. 83" in x.message)
        self.assertTrue(n.url.startswith(f"{URL}/f/"))
        ev = next(x for x in s.cal if x.kind == "scadenza")
        self.assertRegex(ev.description, rf"- modulo\.pdf: {re.escape(URL)}/f/\d+")

    def test_stati_drive_e_nextcloud_separati(self):
        self.st.data["allegati"] = {"vecchia": {"id": "d1", "link": "https://drive/1"}}
        links = self.archivia()
        self.assertNotIn("vecchia", links)                       # niente link Drive mescolati
        self.assertEqual(len(self.dav.file), 3)                  # Nextcloud recupera tutto
        self.assertEqual(self.st.data["allegati"], {"vecchia": {"id": "d1", "link": "https://drive/1"}})

    def test_senza_backend_restituisce_link_noti(self):
        self.archivia()
        self.assertEqual(len(asyncio.run(m.archivia_allegati(FakeCli(), dash_allegati(), "V", self.acfg,
                                                             None, self.st))), 3)


class TestNextcloudLinkPubblico(Base):
    CART = "Scuola/Anna/2026/10 - Ottobre/"

    def test_crea_condivisione_in_sola_lettura(self):
        links = self.archivia(self.nc(link="pubblico"))
        self.assertEqual(len(self.dav.condivisioni), 3)
        self.assertTrue(all(u.startswith(f"{URL}/s/tok") for u in links.values()))
        self.assertEqual(self.dav.condivisioni[self.CART + "2026-10-12 circ83.pdf"][0][1], None)  # nessuna scadenza
        self.assertEqual({v["tipo"] for v in self.st.data["allegati_nextcloud"].values()}, {"pubblico"})

    def test_scadenza(self):
        from datetime import date, timedelta
        self.archivia(self.nc(link="pubblico", scadenza_giorni=30))
        scad = self.dav.condivisioni[self.CART + "2026-10-12 circ83.pdf"][0][1]
        self.assertEqual(scad, str(date.today() + timedelta(days=30)))

    def test_riusa_condivisione_esistente(self):
        self.archivia(self.nc(link="pubblico"))
        prima = dict(self.dav.condivisioni)
        self.st.data.clear()                                     # state.json perso
        links = self.archivia(self.nc(link="pubblico"))
        self.assertEqual(self.dav.condivisioni, prima)           # nessuna nuova condivisione
        self.assertEqual(sorted(links.values()), sorted(u for v in prima.values() for u, _ in v))

    def test_da_interno_a_pubblico_senza_ricaricare(self):
        interni = self.archivia()
        n_put = sum(1 for metodo, _ in self.dav.chiamate if metodo == "PUT")
        pubblici = self.archivia(self.nc(link="pubblico"))
        self.assertEqual(sum(1 for metodo, _ in self.dav.chiamate if metodo == "PUT"), n_put)
        self.assertEqual(set(pubblici), set(interni))
        self.assertTrue(all("/s/tok" in u for u in pubblici.values()))
        # e ritorno: di nuovo /f/<id>, stessi file
        self.assertEqual(self.archivia(self.nc()), interni)
        self.assertEqual(sum(1 for metodo, _ in self.dav.chiamate if metodo == "PUT"), n_put)

    def test_cambio_tipo_rispetta_il_limite_per_giro(self):
        self.archivia()
        self.acfg["allegati"]["max_per_giro"] = 2
        links = self.archivia(self.nc(link="pubblico"))
        self.assertEqual(sum("/s/" in u for u in links.values()), 2)
        links = self.archivia(self.nc(link="pubblico"))
        self.assertEqual(sum("/s/" in u for u in links.values()), 3)

    def test_dry_run_non_crea_condivisioni(self):
        self.archivia()
        stato = {k: dict(v) for k, v in self.st.data["allegati_nextcloud"].items()}
        self.archivia(self.nc(dry=True, link="pubblico"))
        self.assertEqual(self.dav.condivisioni, {})
        self.assertEqual(self.st.data["allegati_nextcloud"], stato)

    def test_password_obbligatoria_errore_chiaro(self):
        self.dav.password_obbligatoria = True
        with self.assertLogs(m.log, "WARNING") as cm:
            links = self.archivia(self.nc(link="pubblico"))
        self.assertEqual(links, {})
        self.assertIn("Password obbligatoria", cm.output[0])
        self.assertEqual(len(self.dav.file), 3)                  # file caricati, link al prossimo giro
        self.dav.password_obbligatoria = False
        self.assertEqual(len(self.archivia(self.nc(link="pubblico"))), 3)
        self.assertEqual(sum(1 for metodo, _ in self.dav.chiamate if metodo == "PUT"), 3)


class TestModelliPercorso(unittest.TestCase):
    def acfg(self, **kw):
        return {"allegati": {"cartella": "Scuola", "sottocartella": "Anna", **kw}}

    def p(self, data="2026-10-12", nome="circ83.pdf", **kw):
        b = dash(((data or "") if data else "", "Circ.", [(nome, "X")])).bacheca[0]
        return m.percorso_allegato(self.acfg(**kw), b, b.lista_allegati[0])

    def test_default_uguale_a_prima(self):
        self.assertEqual(self.p(), (["Scuola", "Anna", "2026", "10 - Ottobre"], "2026-10-12 circ83.pdf"))
        self.assertEqual(self.p(percorso=m.PERCORSO_DEFAULT, nome_file=m.NOME_FILE_DEFAULT), self.p())

    def test_modelli_personalizzati(self):
        self.assertEqual(self.p(percorso="{alunno}/{anno}-{mese:02d}", nome_file="{giorno:02d} - {nome}"),
                         (["Anna", "2026-10"], "12 - circ83.pdf"))
        self.assertEqual(self.p(percorso="Argo/{cartella}/{nome_mese} {anno}", nome_file="{nome}"),
                         (["Argo", "Scuola", "Ottobre 2026"], "circ83.pdf"))

    def test_senza_data(self):
        self.assertEqual(self.p(data=None), (["Scuola", "Anna"], "circ83.pdf"))
        self.assertEqual(self.p(data=None, percorso="{alunno}/{anno}/x"), (["Anna", "x"], "circ83.pdf"))

    def test_caratteri_vietati_e_parti_vuote(self):
        self.assertEqual(self.p(percorso="{cartella}//{alunno}: {nome_mese}/ "),
                         (["Scuola", "Anna_ Ottobre"], "2026-10-12 circ83.pdf"))

    def test_archivia_usa_i_modelli(self):
        t = Base("run")
        t.setUp()
        try:
            t.acfg["allegati"] |= {"percorso": "{alunno}/{anno}", "nome_file": "{nome}"}
            t.archivia()
            self.assertIn("Anna/2026/circ83.pdf", t.dav.file)
        finally:
            t.tearDown()


class TestNextcloudConnessione(Base):
    def test_verifica_ok(self):
        self.nc().verifica()
        self.assertEqual(self.dav.chiamate, [("PROPFIND", "")])

    def test_password_sbagliata(self):
        nc = self.nc(dav=FakeDav(password="altra"))
        with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
            nc.verifica()

    def test_credenziali_mancanti(self):
        with self.assertRaisesRegex(ValueError, "NEXTCLOUD_APP_PASSWORD"):
            m.Nextcloud({**NCFG, "password": ""}, False)
        with self.assertRaisesRegex(ValueError, "url"):
            m.Nextcloud({**NCFG, "url": ""}, False)

    def test_url_webdav(self):
        nc = m.Nextcloud({**NCFG, "utente": "mario rossi@x"}, False)
        self.assertEqual(nc.dav, f"{URL}/remote.php/dav/files/mario%20rossi%40x")
        self.assertEqual(nc._url(["10 - Ottobre", "a#b.pdf"]), nc.dav + "/10%20-%20Ottobre/a%23b.pdf")


CONFIG_NC = CONFIG.replace("[orario]", """[allegati]
drive = true
[allegati.nextcloud]
url = "https://cloud.test"
utente = "mario"

[orario]""", 1)


class TestConfigArchivio(unittest.TestCase):
    def archivi(self, c):
        return {al["nome"]: al["cfg"]["allegati"]["archivio"] for al in c["alunni"]}

    def test_default_disattivo(self):
        c = carica(CONFIG)
        self.assertEqual(set(self.archivi(c).values()), {""})
        self.assertEqual(c["alunni"][0]["cfg"]["allegati"]["nextcloud"]["password_env"], "NEXTCLOUD_APP_PASSWORD")
        self.assertNotIn(m.SCOPE_DRIVE, m.scope_richiesti(c))

    def test_drive_true_compatibile(self):
        c = carica(CONFIG_NC)
        self.assertEqual(set(self.archivi(c).values()), {"drive"})
        self.assertTrue(all(al["cfg"]["allegati"]["drive"] for al in c["alunni"]))
        self.assertIn(m.SCOPE_DRIVE, m.scope_richiesti(c))

    def test_archivio_per_alunno(self):
        testo = CONFIG_NC.replace('calendar_id = "c"', 'calendar_id = "c"\n[alunni.allegati]\narchivio = "nextcloud"\n'
                                  '[alunni.allegati.nextcloud]\nutente = "anna"', 1)
        c = carica(testo, {"NEXTCLOUD_APP_PASSWORD": "segreta"})
        self.assertEqual(self.archivi(c), {"A": "drive", "C": "nextcloud", "B": "drive"})
        nc = c["alunni"][1]["cfg"]["allegati"]["nextcloud"]
        self.assertEqual((nc["url"], nc["utente"], nc["password"]), ("https://cloud.test", "anna", "segreta"))
        self.assertEqual(c["alunni"][0]["cfg"]["allegati"]["nextcloud"]["utente"], "mario")  # non toccato
        self.assertEqual(c["alunni"][1]["cfg"]["allegati"]["sottocartella"], "C")

    def test_solo_nextcloud_niente_scope_drive(self):
        c = carica(CONFIG_NC.replace("drive = true", 'archivio = "nextcloud"'))
        self.assertEqual(set(self.archivi(c).values()), {"nextcloud"})
        self.assertNotIn(m.SCOPE_DRIVE, m.scope_richiesti(c))

    def test_alunno_disattiva(self):
        testo = CONFIG_NC.replace('calendar_id = "c"', 'calendar_id = "c"\n[alunni.allegati]\ndrive = false', 1)
        self.assertEqual(self.archivi(carica(testo))["C"], "")

    def test_variabili_ambiente_vincono(self):
        env = {"NEXTCLOUD_URL": "https://altro.test", "NEXTCLOUD_USER": "env-user", "NEXTCLOUD_APP_PASSWORD": "pw"}
        testo = CONFIG_NC.replace("drive = true", 'archivio = "nextcloud"').replace(
            'calendar_id = "c"', 'calendar_id = "c"\n[alunni.allegati.nextcloud]\nutente = "anna"', 1)
        c = carica(testo, env)
        nc_a, nc_c = (c["alunni"][i]["cfg"]["allegati"]["nextcloud"] for i in (0, 1))
        self.assertEqual((nc_a["url"], nc_a["utente"], nc_a["password"]), ("https://altro.test", "env-user", "pw"))
        self.assertEqual((nc_c["url"], nc_c["utente"]), ("https://altro.test", "anna"))  # alunno vince

    def test_solo_variabili_ambiente(self):
        c = carica(CONFIG.replace("[orario]", '[allegati]\narchivio = "nextcloud"\n\n[orario]', 1),
                   {"NEXTCLOUD_URL": "https://e.test", "NEXTCLOUD_USER": "u", "NEXTCLOUD_APP_PASSWORD": "p"})
        nc = c["alunni"][0]["cfg"]["allegati"]["nextcloud"]
        self.assertEqual((nc["url"], nc["utente"], nc["link"], nc["scadenza_giorni"]), ("https://e.test", "u", "interno", 0))

    def test_opzioni_link_e_riepilogo(self):
        testo = CONFIG_NC.replace("drive = true", 'archivio = "nextcloud"').replace(
            'utente = "mario"', 'utente = "mario"\nlink = "pubblico"\nscadenza_giorni = 30')
        c = carica(testo)
        self.assertIn("allegati nextcloud (pubblico, 30 gg)", m.riepilogo_avvio(c))
        with self.assertRaisesRegex(ValueError, "link"):
            carica(testo.replace('"pubblico"', '"aperto"'))
        with self.assertRaisesRegex(ValueError, "scadenza_giorni"):
            carica(testo.replace("= 30", "= -1"))

    def test_modelli_non_validi(self):
        with self.assertRaisesRegex(ValueError, "segnaposto sconosciuto {classe}"):
            carica(CONFIG_NC.replace("drive = true", 'drive = true\npercorso = "{alunno}/{classe}"'))
        with self.assertRaisesRegex(ValueError, "nome_file"):
            carica(CONFIG_NC.replace("drive = true", 'drive = true\nnome_file = "{nome:%Y}"'))
        with self.assertRaisesRegex(ValueError, "percorso"):
            carica(CONFIG_NC.replace("drive = true", 'drive = true\npercorso = "{}"'))

    def test_valore_non_valido(self):
        with self.assertRaisesRegex(ValueError, "archivio"):
            carica(CONFIG_NC.replace("drive = true", 'archivio = "dropbox"'))


if __name__ == "__main__":
    unittest.main()
