"""Comunicazioni della bacheca senza allegati: archiviate come PDF (generato con la libreria standard)."""
import asyncio
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import didup_calendar_sync as m  # noqa: E402
from didupwrapper.models import DashboardResponse  # noqa: E402
from test_snapshot import OGGI, ORARIO, FakeCli, FakeDrive, cfg, raw  # noqa: E402

TESTO = ("<p>Oggetto: uscita didattica del 30 ottobre (classi terze)</p><p>Gentili famiglie,<br>"
         "l&#39;uscita “didattica” è rinviata – costo 5 €.</p><ul><li>punto uno</li><li>punto due</li></ul>")


def dash():
    d = raw()
    d["pk"] = "SCHEDA"
    d["bacheca"] = [
        {"datEvento": "2026-10-26", "data": "2026-10-26", "messaggio": TESTO, "autore": "Segreteria",
         "categoria": "Comunicazioni", "pvRichiesta": True, "url": "https://example.com/modulo", "listaAllegati": []},
        {"datEvento": "2026-10-12", "data": "2026-10-12", "messaggio": "Circ. 83 sciopero", "autore": "Dir",
         "listaAllegati": [{"nomeFile": "circ83.pdf", "pk": "A83"}]},
    ]
    return DashboardResponse.model_validate(d)


def oggetti_pdf(pdf: bytes) -> dict[int, int]:
    return {int(n): x.start() for x in re.finditer(rb"(\d+) 0 obj", pdf) for n in [x.group(1)]}


class TestTesto(unittest.TestCase):
    def test_html_in_testo(self):
        self.assertEqual(m.testo_semplice(TESTO),
                         "Oggetto: uscita didattica del 30 ottobre (classi terze)\n\nGentili famiglie,\n"
                         "l'uscita “didattica” è rinviata – costo 5 €.\n\n- punto uno\n- punto due")
        self.assertEqual(m.testo_semplice("riga 1\r\nriga 2\n\n\n\nfine"), "riga 1\nriga 2\n\nfine")

    def test_nome_file(self):
        b = dash().bacheca[0]
        self.assertEqual(m.nome_pdf_comunicazione(b), "uscita didattica del 30 ottobre (classi terze).pdf")
        b.messaggio = "parola " * 30
        nome = m.nome_pdf_comunicazione(b)
        self.assertLessEqual(len(nome), 75)
        self.assertTrue(nome.endswith("parola.pdf"))
        b.messaggio, b.categoria = "", "Avvisi"
        self.assertEqual(m.nome_pdf_comunicazione(b), "Avvisi.pdf")


class TestPdf(unittest.TestCase):
    def test_struttura_valida(self):
        pdf = m.pdf_testo("Titolo (prova)", ["Alunno: Anna"], "Testo con \\ e ) e €")
        self.assertTrue(pdf.startswith(b"%PDF-1.4\n"))
        self.assertTrue(pdf.endswith(b"%%EOF\n"))
        xref = int(re.search(rb"startxref\n(\d+)", pdf).group(1))
        self.assertTrue(pdf[xref:].startswith(b"xref\n"))
        voci = re.findall(rb"(\d{10}) 00000 n ", pdf[xref:])
        pos = oggetti_pdf(pdf)
        self.assertEqual([int(v) for v in voci], [pos[i] for i in range(1, len(voci) + 1)])  # offset esatti
        for lung, flusso in re.findall(rb"/Length (\d+) >>\nstream\n(.*?)\nendstream", pdf, re.S):
            self.assertEqual(int(lung), len(flusso))
        self.assertIn(rb"(Titolo \(prova\))", pdf)
        self.assertIn(b"(Testo con \\\\ e \\) e \x80)", pdf)       # € in Windows-1252

    def test_piu_pagine(self):
        pdf = m.pdf_testo("T", [], "\n".join(f"riga {i}" for i in range(200)), "piede")
        self.assertIn(b"/Count 4", pdf)
        self.assertIn(b"(piede - pagina 4/4)", pdf)

    def test_contenuto_comunicazione(self):
        pdf = m.pdf_comunicazione(dash().bacheca[0], "Anna")
        for t in (b"(Alunno: Anna)", b"(Data: 26/10/2026)", b"(Da: Segreteria)", b"(Categoria: Comunicazioni)",
                  b"(Presa visione: richiesta \\(da dare sul registro\\))", b"(Link: https://example.com/modulo)",
                  b"(- punto due)"):
            self.assertIn(t, pdf)


class TestArchivio(unittest.TestCase):
    def setUp(self):
        self.acfg = {"allegati": {"drive": True, "cartella": "Scuola", "sottocartella": "Anna", "max_per_giro": 30}}
        self.st = m.State(Path("/nonexistent/state.json"))
        self._scarica = m.scarica

        async def finta_scarica(url):
            return url.encode(), "application/pdf"
        m.scarica = finta_scarica
        self.addCleanup(setattr, m, "scarica", self._scarica)

    def archivia(self, drv):
        return asyncio.run(m.archivia_allegati(FakeCli(), dash(), "Anna", self.acfg, drv, self.st))

    def test_comunicazione_senza_allegati_in_pdf(self):
        drv = FakeDrive()
        with self.assertLogs(m.log) as lg:
            links = self.archivia(drv)
        nomi = {n: (c, mime, dati) for c, n, dati, mime in drv.caricati}
        c, mime, dati = nomi["2026-10-26 uscita didattica del 30 ottobre (classi terze).pdf"]
        self.assertEqual((c, mime), ("Scuola/Anna/2026/10 - Ottobre", "application/pdf"))
        self.assertTrue(dati.startswith(b"%PDF"))
        self.assertIn("2026-10-12 circ83.pdf", nomi)
        b = dash().bacheca[0]
        self.assertIn(m.chiave_comunicazione(b), links)
        self.assertIn("(di cui 1 comunicazioni in PDF)", lg.output[0])
        drv2 = FakeDrive()
        self.archivia(drv2)                                      # secondo giro: niente da rifare
        self.assertEqual(drv2.caricati, [])

    def test_disattivabile(self):
        self.acfg["allegati"]["comunicazioni_pdf"] = False
        drv = FakeDrive()
        self.archivia(drv)
        self.assertEqual([n for _, n, _, _ in drv.caricati], ["2026-10-12 circ83.pdf"])

    def test_link_nella_notifica(self):
        d = dash()
        k = m.chiave_comunicazione(d.bacheca[0])
        s = m.build_snapshot(d, ORARIO, "Anna", cfg(), OGGI, raw=raw(), link_allegati={k: "https://drive/pdf"})
        n = next(x for x in s.notifiche if x.kind == "bacheca" and "Segreteria" in x.message)
        self.assertEqual(n.url, "https://drive/pdf")
        self.assertNotIn("📎", n.message)


class TestConfig(unittest.TestCase):
    def test_default_e_validazione(self):
        from test_snapshot import CONFIG, carica
        self.assertTrue(carica(CONFIG)["allegati"]["comunicazioni_pdf"])
        self.assertFalse(carica("[allegati]\ncomunicazioni_pdf = false\n" + CONFIG)["alunni"][0]["cfg"]["allegati"]["comunicazioni_pdf"])
        with self.assertRaisesRegex(ValueError, "comunicazioni_pdf"):
            carica('[allegati]\ncomunicazioni_pdf = "si"\n' + CONFIG)


if __name__ == "__main__":
    unittest.main()


class TestNotificaCompleta(unittest.TestCase):
    def test_bacheca_con_testo_intero(self):
        d = dash()
        d.bacheca[0].messaggio = TESTO + "<p>" + "lungo " * 200 + "</p>"
        s = m.build_snapshot(d, ORARIO, "Anna", cfg(), OGGI, raw=raw())
        n = next(x for x in s.notifiche if x.kind == "bacheca" and "Segreteria" in x.message)
        self.assertLess(len(n.message), 400)                       # Home Assistant: riassunto
        self.assertTrue(n.completo.startswith("Segreteria [presa visione richiesta]\n\nOggetto: uscita"))
        self.assertIn("- punto due", n.completo)
        self.assertTrue(n.completo.rstrip().endswith("lungo"))     # Telegram: tutto il testo
        self.assertNotIn("<p>", n.completo)

    def test_notify_new_passa_il_testo_intero(self):
        inviati = []

        class Notif:
            def send(self, title, message, url=None, kind=None, alunno=None, **kw):
                inviati.append(kw.get("completo"))
        snap = m.build_snapshot(dash(), ORARIO, "Anna", cfg(), OGGI, raw=raw())
        st = m.State(Path("/nonexistent/state.json"))
        st.data["seen"]["k"] = {"bacheca": []}
        m.notify_new(snap, "k", "Anna", st, Notif(), ["bacheca"])
        self.assertTrue(any(c and "Gentili famiglie" in c for c in inviati))
