"""Test offline (niente rete né account): costruiscono i modelli veri di
didupwrapper, così un cambio di nomi dei campi nella libreria fa fallire i test."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import didup_calendar_sync as m  # noqa: E402
from didupwrapper.models import DashboardResponse  # noqa: E402

OGGI = date(2026, 10, 5)


def cfg(**orario):
    return {"orario": {"giorni": 14, "durata_ora_min": 60, "fasce": {}, **orario},
            "compiti": {"giorni_passati": 0}, "calendario": {"timezone": "Europe/Rome"}}


def raw():
    return {
        "voti": [{"prgVoto": 1, "datGiorno": "2026-10-01", "desMateria": "MATEMATICA",
                  "codCodice": "7+", "codVotoPratico": "S", "descrizioneProva": "Equazioni"}],
        "registro": [
            {"datGiorno": "2026-10-02", "materia": "ITALIANO", "pkMateria": "ab", "docente": "ROSSI",
             "compiti": [{"compito": "Pag. 34 es 1-5", "dataConsegna": "2026-10-06"}]},
            {"datGiorno": "2026-09-20", "materia": "STORIA", "pkMateria": "cd", "docente": "VERDI",
             "compiti": [{"compito": "Vecchio compito", "dataConsegna": "2026-09-25"}]},
        ],
        "promemoria": [
            {"datGiorno": "2026-10-08", "desAnnotazioni": "Verifica di storia", "docente": "BIANCHI",
             "oraInizio": "09:00", "oraFine": "10:00", "flgVisibileFamiglia": "S"},
            {"datGiorno": "2026-10-10", "desAnnotazioni": "Nascosto", "docente": "X",
             "flgVisibileFamiglia": "N"},
        ],
        "bacheca": [{"datEvento": "2026-10-01", "data": "2026-10-01", "messaggio": "Autorizzazione gita",
                     "autore": "Dirigente", "pvRichiesta": True, "adRichiesta": True,
                     "dataScadAdesione": "2026-10-15"},
                    {"datEvento": "2026-10-05", "data": "2026-10-05", "messaggio": "Circolare progetto",
                     "autore": "Direzione/Segreteria", "pvRichiesta": True,
                     "dataScadenza": "2027-08-31"}],  # fine pubblicazione: nessun evento
        "noteDisciplinari": None,
        "appello": [{"codEvento": "I", "data": "2026-10-03", "descrizione": "Ritardo"}],
    }


def ora(n, materia, docente="ROSSI", ora=None):
    return {"numOra": n, "materia": materia, "docente": docente, "mostra": True, "ora": ora}


ORARIO = {date(2026, 10, 6): [
    ora(1, "ITALIANO", ora="08:00-09:00"), ora(2, "ITALIANO", ora="09:00-10:00"),
    ora(3, "MATEMATICA", "BIANCHI", ora="10:00-11:00"),
]}


def snap(data=None, orario=None, c=None):
    return m.build_snapshot(DashboardResponse.model_validate(data or raw()),
                            ORARIO if orario is None else orario, "Test", c or cfg(), OGGI)


class TestParse(unittest.TestCase):
    def test_date(self):
        self.assertEqual(m.parse_date("2026-10-06 00:00:00.000"), date(2026, 10, 6))
        self.assertEqual(m.parse_date("6/10/2026"), date(2026, 10, 6))
        self.assertIsNone(m.parse_date(""))

    def test_orari(self):
        self.assertEqual(m.times_in("8.00 - 9:05"), ["08:00", "09:05"])
        self.assertEqual(m.parse_hhmm("9:05:00"), "09:05")


class TestLezioni(unittest.TestCase):
    def lezioni(self, s):
        return [c for c in s.cal if c.kind == "lezione"]

    def test_ore_consecutive_unite(self):
        lez = self.lezioni(snap())
        self.assertEqual(len(lez), 2)
        ita = next(x for x in lez if x.summary.startswith("Italiano"))
        self.assertEqual((ita.start_time, ita.end_time), ("08:00", "10:00"))
        self.assertFalse(ita.reminders)

    def test_compito_sulla_lezione_della_materia(self):
        lez = self.lezioni(snap())
        ita = next(x for x in lez if x.summary.startswith("Italiano"))
        mat = next(x for x in lez if x.summary.startswith("Matematica"))
        self.assertIn("✏️", ita.summary)
        self.assertIn("Pag. 34", ita.description)
        self.assertNotIn("✏️", mat.summary)

    def test_fasce_da_config(self):
        o = {date(2026, 10, 7): [ora(1, "STORIA")]}
        lez = self.lezioni(snap(orario=o, c=cfg(fasce={"1": "08:10-09:05"})))
        self.assertEqual((lez[0].start_time, lez[0].end_time), ("08:10", "09:05"))

    def test_senza_orario_saltata(self):
        o = {date(2026, 10, 7): [ora(1, "STORIA")]}
        self.assertEqual(self.lezioni(snap(orario=o)), [])

    def test_mostra_false(self):
        o = {date(2026, 10, 7): [{**ora(1, "STORIA", ora="08:00-09:00"), "mostra": False}]}
        self.assertEqual(self.lezioni(snap(orario=o)), [])


class TestCompiti(unittest.TestCase):
    """I compiti vanno nella lezione del giorno di consegna; senza lezione, evento giornaliero."""

    def compiti(self, s):
        return [c for c in s.cal if c.kind == "compito"]

    def test_nella_lezione_nessun_evento_a_parte(self):
        s = snap()
        ita = next(x for x in s.cal if x.kind == "lezione" and x.summary.startswith("Italiano"))
        self.assertIn("- Pag. 34 es 1-5\n  (assegnato il 2026-10-02 da ROSSI)", ita.description)
        self.assertEqual(self.compiti(s), [])

    def test_senza_lezione_evento_giornaliero(self):
        s = snap(orario={})  # nessuna lezione scaricata
        ev = self.compiti(s)
        self.assertEqual([(e.day, e.start_time, e.summary) for e in ev],
                         [(date(2026, 10, 6), None, "📚 Italiano: Pag. 34 es 1-5")])  # settembre escluso
        self.assertIn("(assegnato il 2026-10-02 da ROSSI)", ev[0].description)

    def test_modifica_testo_aggiorna_lezione(self):
        d = raw()
        d["registro"][0]["compiti"][0]["compito"] = "Pag. 35"
        a = next(x for x in snap().cal if x.summary.startswith("Italiano"))
        b = next(x for x in snap(d).cal if x.summary.startswith("Italiano"))
        self.assertEqual(a.key, b.key)
        self.assertNotEqual(a.content_hash, b.content_hash)


class TestAltriEventi(unittest.TestCase):
    def test_promemoria_e_scadenze(self):
        kinds = sorted((c.kind, c.day) for c in snap().cal if c.kind not in ("lezione", "compito"))
        self.assertEqual(kinds, [("promemoria", date(2026, 10, 8)), ("scadenza", date(2026, 10, 15))])

    def test_body_con_orario(self):
        cal = m.Calendar.__new__(m.Calendar)
        cal.tz = "Europe/Rome"
        b = cal.body(next(c for c in snap().cal if c.kind == "lezione"))
        self.assertEqual(b["start"]["dateTime"], "2026-10-06T08:00:00")
        self.assertEqual(b["reminders"], {"useDefault": False, "overrides": []})
        self.assertEqual(b["extendedProperties"]["private"]["argo_kind"], "lezione")


class TestDatiReali(unittest.TestCase):
    """Casi visti sulle scuole reali (ottobre 2026)."""

    def dash(self, **extra):
        d = raw()
        d["listaMaterie"] = [
            {"materia": "MATEMATICA CON INFORMATICA", "abbreviazione": "MATEM. CON INFORM."},
            {"materia": "SCIENZE NATURALI (BIOLOGIA, CHIMICA, SCIENZE DELLA TERRA)",
             "abbreviazione": "SCIENZE NATURALI"},
            {"materia": "EDUCAZIONE CIVICA", "abbreviazione": "EDUCAZIONE CIVICA"},
        ]
        d["registro"].append({"datGiorno": "2026-10-01", "materia": "MATEMATICA CON INFORMATICA",
                              "pkMateria": "mi", "docente": "SARRA",
                              "compiti": [{"compito": "Es. 4 pag. 20", "dataConsegna": "2026-10-06"}]})
        d.update(extra)
        return d

    def test_abbreviazioni_e_compresenza(self):
        orario = {date(2026, 10, 6): [
            ora(1, "MATEM. CON INFORM.", "SARRA", "08:00-09:00"),
            ora(2, "MATEM. CON INFORM.", "SARRA", "09:00-10:00"),
            ora(3, "SCIENZE NATURALI", "CAMPOLONGO", "10:00-11:00"),
            ora(3, "EDUCAZIONE CIVICA", "CAMPOLONGO", "10:00-11:00"),
            ora(4, "SOSTEGNO", "PERETTI", "11:00-12:00"),
            {"numOra": 5, "materia": "", "mostra": False},
        ]}
        c = cfg()
        c["materie_ignorate"] = ["SOSTEGNO"]
        lez = [x for x in snap(self.dash(), orario, c).cal if x.kind == "lezione"]
        self.assertEqual([(x.summary, x.start_time, x.end_time) for x in lez], [
            ("Matem. con inform. ✏️", "08:00", "10:00"),   # titolo con l'abbreviazione dell'orario,
            ("Scienze naturali / Educazione civica", "10:00", "11:00"),  # compresenza: un solo evento
        ])
        self.assertIn("Es. 4 pag. 20", lez[0].description)  # compito agganciato via nome completo
        self.assertIn("Materia: Matematica con informatica", lez[0].description)
        self.assertIn("Materia: Scienze naturali (biologia, chimica, scienze della terra) / Educazione civica",
                      lez[1].description)

    def test_compito_senza_lezione_titolo_con_abbreviazione(self):
        s = snap(self.dash(), orario={})
        e = next(x for x in s.cal if x.kind == "compito" and "Es. 4" in x.summary)
        self.assertEqual(e.summary, "📚 Matem. con inform.: Es. 4 pag. 20")
        self.assertIn("Materia: Matematica con informatica", e.description)

    def test_promemoria_senza_orario_giornaliero(self):
        d = self.dash(promemoria=[{"datGiorno": "2026-10-19", "desAnnotazioni": "Verifica fisica",
                                   "docente": "ALLOATTI", "oraInizio": "00:00", "oraFine": "00:00",
                                   "flgVisibileFamiglia": "S"}])
        p = next(x for x in snap(d).cal if x.kind == "promemoria")
        self.assertEqual((p.start_time, p.end_time), (None, None))

    def test_note_campi_grezzi(self):
        nota = {"datNota": "2026-09-29", "oraNota": "13:10", "docente": "S. CAMPOLONGO",
                "desDescrizione": "senza quaderno", "flgAnnullata": False, "isVisibile": True}
        annullata = {**nota, "desDescrizione": "annullata", "flgAnnullata": True}
        d = self.dash(noteDisciplinari=[nota, annullata])
        s = m.build_snapshot(DashboardResponse.model_validate(d), ORARIO, "Test", cfg(), OGGI, raw=d)
        note = [n for n in s.notifiche if n.kind == "note"]
        self.assertEqual([n.message for n in note], ["2026-09-29 13:10 S. CAMPOLONGO: senza quaderno"])

    def test_appello_giustificato_e_nota(self):
        d = self.dash(appello=[{"codEvento": "I", "data": "2026-10-01", "descrizione": "",
                                "nota": "Ingresso in 1^ ora alle ore 08:02",
                                "daGiustificare": True, "giustificata": "S"}])
        a = next(n for n in snap(d).notifiche if n.kind == "assenze")
        self.assertEqual(a.title, "🚪 Ingresso posticipato – Test")
        self.assertEqual(a.message, "2026-10-01: Ingresso in 1^ ora alle ore 08:02")


def dash_allegati():
    d = raw()
    d["pk"] = "SCHEDA"
    d["bacheca"] = [
        {"datEvento": "2026-10-12", "data": "2026-10-12", "messaggio": "Circ. 83 sciopero", "autore": "Dir",
         "listaAllegati": [{"nomeFile": "circ83.pdf", "pk": "A83"}]},
        {"datEvento": "2026-09-30", "data": "2026-09-30", "messaggio": "Uscita", "autore": "Dir",
         "adRichiesta": True, "dataScadAdesione": "2026-10-20",
         "listaAllegati": [{"nomeFile": "modulo.pdf", "pk": "A1"}, {"nomeFile": "info:/x.pdf", "pk": "A2"}]},
    ]
    return DashboardResponse.model_validate(d)


class FakeDrive:
    def __init__(self, dry=False, esistenti=None):
        self.dry, self.caricati, self.esistenti = dry, [], esistenti or {}

    def cerca(self, k, percorso=None, nome=None):
        return self.esistenti.get(k)

    def cartella(self, percorso):
        return "/".join(percorso)

    def carica(self, cartella, nome, dati, mime, k):
        self.caricati.append((cartella, nome, dati, mime))
        return {"id": f"id{len(self.caricati)}", "link": f"https://drive/{len(self.caricati)}"}


class FakeCli:
    def __init__(self, fallisce=()):
        self.fallisce, self.chiesti = fallisce, []

    async def url_allegato(self, uid, pk_scheda):
        self.chiesti.append((uid, pk_scheda))
        if uid in self.fallisce:
            raise RuntimeError("boom")
        return f"https://files/{uid}"


class TestAllegati(unittest.TestCase):
    def setUp(self):
        self.acfg = {"allegati": {"drive": True, "cartella": "Scuola", "sottocartella": "Anna",
                                  "max_per_giro": 30}}
        self.st = m.State(Path("/nonexistent/state.json"))
        self._scarica = m.scarica

        async def finta_scarica(url):
            return url.encode(), "application/pdf"
        m.scarica = finta_scarica

    def tearDown(self):
        m.scarica = self._scarica

    def archivia(self, drive, cli=None, d=None):
        import asyncio
        return asyncio.run(m.archivia_allegati(cli or FakeCli(), d or dash_allegati(), "V", self.acfg,
                                               drive, self.st))

    def test_percorso_utente_anno_mese(self):
        d = dash_allegati()
        b0, b1 = d.bacheca
        self.assertEqual(m.percorso_allegato(self.acfg, b0, b0.lista_allegati[0]),
                         (["Scuola", "Anna", "2026", "10 - Ottobre"], "2026-10-12 circ83.pdf"))
        self.assertEqual(m.percorso_allegato(self.acfg, b1, b1.lista_allegati[0])[0][-1], "09 - Settembre")

    def test_carica_una_volta_sola(self):
        drv, cli = FakeDrive(), FakeCli()
        links = self.archivia(drv, cli)
        self.assertEqual([(c, n) for c, n, _, _ in drv.caricati], [
            ("Scuola/Anna/2026/10 - Ottobre", "2026-10-12 circ83.pdf"),
            ("Scuola/Anna/2026/09 - Settembre", "2026-09-30 modulo.pdf"),
            ("Scuola/Anna/2026/09 - Settembre", "2026-09-30 info__x.pdf"),
        ])
        self.assertEqual(cli.chiesti[0], ("A83", "SCHEDA"))
        self.assertEqual(len(links), 3)
        drv2 = FakeDrive()
        self.archivia(drv2)  # secondo giro: tutto già in state.json
        self.assertEqual(drv2.caricati, [])

    def test_limite_errori_dry_e_esistenti(self):
        self.acfg["allegati"]["max_per_giro"] = 2
        drv = FakeDrive()
        self.archivia(drv, FakeCli(fallisce={"A83"}))
        self.assertEqual(len(drv.caricati), 1)            # A83 fallito, A1 ok, A2 al prossimo giro
        self.assertEqual(len(self.st.data["allegati"]), 1)
        self.acfg["allegati"]["max_per_giro"] = 30
        drv = FakeDrive(dry=True)
        self.archivia(drv)
        self.assertEqual(drv.caricati, [])                # dry-run: niente upload
        b = dash_allegati().bacheca[0]
        k = m.chiave_allegato(b, b.lista_allegati[0])
        drv = FakeDrive(esistenti={k: {"id": "x", "link": "https://drive/esistente"}})
        links = self.archivia(drv)
        self.assertEqual(links[k], "https://drive/esistente")  # già su Drive: non ricaricato
        self.assertEqual(len(drv.caricati), 1)            # resta solo A2

    def test_link_in_notifica_ed_evento(self):
        d = dash_allegati()
        links = self.archivia(FakeDrive(), d=d)
        s = m.build_snapshot(d, ORARIO, "V", cfg(), OGGI, link_allegati=links)
        n = {x.message.split(":")[1].strip()[:9]: x for x in s.notifiche if x.kind == "bacheca"}
        self.assertEqual(n["Circ. 83 "].url, "https://drive/1")
        self.assertIn("📎 1 allegato", n["Circ. 83 "].message)
        ev = next(x for x in s.cal if x.kind == "scadenza")
        self.assertIn("- modulo.pdf: https://drive/2", ev.description)

    def test_payload_home_assistant(self):
        p = m.Notifier.payload_ha("T", "M", "https://drive/1")
        self.assertEqual(p["data"]["url"], "https://drive/1")
        self.assertEqual(p["data"]["clickAction"], "https://drive/1")
        self.assertEqual(p["data"]["actions"][0]["uri"], "https://drive/1")
        self.assertEqual(m.Notifier.payload_ha("T", "M", None), {"title": "T", "message": "M"})

    def test_config_default(self):
        a = carica(CONFIG)["alunni"][2]["cfg"]["allegati"]
        self.assertEqual((a["drive"], a["cartella"], a["sottocartella"]), (False, "Scuola", "B"))


class TestAvvio(unittest.TestCase):
    def test_versione(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"APP_VERSION": "2026.10.12-4684a37"}):
            self.assertEqual(m.versione(), "2026.10.12-4684a37")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(m.versione().startswith("dev"))

    def test_riepilogo(self):
        r = m.riepilogo_avvio(carica(CONFIG))
        self.assertIn("A (SC1/0): notifiche voti,bacheca,note,promemoria, allegati no", r)
        self.assertIn("B (SC2/0): notifiche voti, allegati no", r)


class TestGuard(unittest.TestCase):
    def test_svuotamento_bloccato(self):
        self.assertEqual(m.guard("x", list(range(30)), 40, 10), [])
        self.assertEqual(m.guard("x", [1], 40, 0), [])
        self.assertEqual(m.guard("x", [1, 2], 40, 38), [1, 2])


class TestOrarioClient(unittest.TestCase):
    def test_parsing_risposta(self):
        import asyncio
        from didupwrapper.exceptions import DiDUPError
        cli = m.MultiProfiloClient.__new__(m.MultiProfiloClient)
        risposte = {
            date(2026, 10, 6): {"success": True, "data": {"dati": {"2026-10-06": [ora(1, "ITALIANO")]}}},
            date(2026, 10, 7): {"success": True, "data": {"dati": {}}},  # festivo
        }

        async def fake(g):
            if g not in risposte:
                raise DiDUPError("boom")
            return risposte[g]
        cli.orario_raw = fake
        out, ok = asyncio.run(cli.orario([date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8)]))
        self.assertEqual(list(out), [date(2026, 10, 6)])
        self.assertEqual(ok, {date(2026, 10, 6), date(2026, 10, 7)})  # l'8 fallito: non gestito


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, title, message, url=None, kind=None, alunno=None):
        self.sent.append((title, message))
        self.urls = getattr(self, "urls", []) + [url]


class TestNotifiche(unittest.TestCase):
    TIPI = ["voti", "bacheca", "promemoria"]

    def test_primo_avvio_silenzioso_poi_solo_novita(self):
        st, n = m.State(Path("/nonexistent/state.json")), FakeNotifier()
        m.notify_new(snap(), "x", "Test", st, n, self.TIPI)
        self.assertEqual(n.sent, [])
        d = raw()
        d["voti"].append({"prgVoto": 2, "datGiorno": "2026-10-04", "desMateria": "INGLESE",
                          "codCodice": "8", "codVotoPratico": "N"})
        m.notify_new(snap(d), "x", "Test", st, n, self.TIPI)
        self.assertEqual(len(n.sent), 1)
        self.assertIn("INGLESE", n.sent[0][1])


CONFIG = """
[orario]
durata_ora_min = 60
[orario.fasce]
1 = "08:00-09:00"

[[alunni]]
nome = "A"
codice_scuola = "SC1"
username = "papa"
password_env = "PW_A"
calendar_id = "a"

[[alunni]]
nome = "C"
codice_scuola = "SC1"
username = "papa"
password_env = "PW_A"
profilo = 1
calendar_id = "c"

[[alunni]]
nome = "B"
codice_scuola = "SC2"
username = "papa2"
password_env = "PW_B"
calendar_id = "b"
notifiche = ["voti"]
[alunni.orario]
durata_ora_min = 55
[alunni.orario.fasce]
1 = "08:10-09:05"
"""


def carica(testo: str, env: dict | None = None) -> dict:
    import os
    import tempfile
    from unittest import mock
    with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, env or {}, clear=True):
        p = Path(d) / "c.toml"
        p.write_text(testo)
        return m.load_config(p)


class TestAccount(unittest.TestCase):
    def test_gruppi_e_password(self):
        c = carica(CONFIG, {"PW_A": "p1"})
        g = m.gruppi_account(c)
        self.assertEqual([(a["codice_scuola"], a["username"], [x["nome"] for x in als]) for a, als in g],
                         [("SC1", "papa", ["A", "C"]), ("SC2", "papa2", ["B"])])
        self.assertEqual([a["password"] for a, _ in g], ["p1", ""])
        with self.assertRaisesRegex(RuntimeError, "PW_B"):
            m.client_argo(g[1][0])

    def test_impostazioni_per_alunno(self):
        a, _, b = carica(CONFIG)["alunni"]
        self.assertEqual(a["cfg"]["orario"]["fasce"], {"1": "08:00-09:00"})
        self.assertEqual(b["cfg"]["orario"]["fasce"], {"1": "08:10-09:05"})
        self.assertEqual((a["cfg"]["orario"]["durata_ora_min"], b["cfg"]["orario"]["durata_ora_min"]), (60, 55))
        self.assertEqual(b["cfg"]["orario"]["giorni"], 14)  # default globale ereditato
        self.assertEqual(b["cfg"]["notifiche"]["tipi"], ["voti"])
        self.assertEqual(a["cfg"]["notifiche"]["tipi"], ["voti", "bacheca", "note", "promemoria"])
        self.assertEqual(a["profilo"], 0)
        self.assertEqual(m.ora_lezione({"numOra": 1}, b["cfg"]), ("08:10", "09:05"))

    def test_servizio_notify_con_prefisso(self):
        c = carica(CONFIG + '\n[notifiche.homeassistant]\nurl = "https://ha"\nservice = "notify.telefono"\n')
        self.assertEqual(c["notifiche"]["homeassistant"]["service"], "telefono")

    def test_config_non_valido(self):
        with self.assertRaisesRegex(ValueError, r"\[argo\]"):
            carica('[argo]\ncodice_scuola = "SC1"\n' + CONFIG)
        with self.assertRaisesRegex(ValueError, "username"):
            carica('[[alunni]]\nnome = "X"\ncodice_scuola = "SC1"\ncalendar_id = "x"\n')
        with self.assertRaisesRegex(ValueError, "duplicati"):
            carica(CONFIG.replace('nome = "C"', 'nome = "A"'))

    def test_state_key_e_migrazione(self):
        c = carica(CONFIG)
        self.assertEqual([m.state_key(al) for al in c["alunni"]], ["SC1/papa/0", "SC1/papa/1", "SC2/papa2/0"])
        st = m.State(Path("/nonexistent/state.json"))
        st.data["seen"]["SC1/0"] = {"voti": ["k"]}
        m.migra_state_key(st, c["alunni"][0])
        self.assertEqual(st.data["seen"], {"SC1/papa/0": {"voti": ["k"]}})


if __name__ == "__main__":
    unittest.main()
