"""Media della materia e media generale nella notifica di un voto."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import didup_calendar_sync as m  # noqa: E402
from didupwrapper.models import DashboardResponse  # noqa: E402
from test_snapshot import OGGI, ORARIO, cfg, raw  # noqa: E402


def voto(pk, materia, giorno, prg, codice, valore, **extra):
    return {"pkMateria": pk, "desMateria": materia, "datGiorno": giorno, "prgVoto": prg, "codCodice": codice,
            "valore": valore, "codVotoPratico": "N", **extra}


def dash(media_materie=None, media_generale=None):
    d = raw()
    d["voti"] = [
        voto("MAT", "MATEMATICA", "2026-10-05", 1, "8", 8.0),
        voto("MAT", "MATEMATICA", "2026-10-20", 2, "5", 5.0),
        voto("MAT", "MATEMATICA", "2026-10-27", 3, "8½", 8.5),
        voto("ING", "INGLESE", "2026-10-08", 1, "9-", 8.75),
        voto("ING", "INGLESE", "2026-10-09", 2, "g", None),                       # giudizio: niente media
        voto("ING", "INGLESE", "2026-10-10", 3, "4", 4.0, faMenoMedia="S"),      # non fa media
    ]
    if media_materie is not None:
        d["mediaMaterie"] = media_materie
    if media_generale is not None:
        d["mediaGenerale"] = media_generale
    return d


def messaggio(d, materia, giorno):
    s = m.build_snapshot(DashboardResponse.model_validate(d), ORARIO, "Test", cfg(), OGGI, raw=d)
    return next(n.message for n in s.notifiche if n.kind == "voti" and materia in n.message and giorno in n.message)


class TestMedie(unittest.TestCase):
    def test_dai_dati_di_argo(self):
        d = dash({"MAT": {"sommaValutazioniOrale": 13, "numValutazioniOrale": 2,
                          "sommaValutazioniScritto": 8.5, "numValutazioniScritto": 1.0}}, 7.9)
        msg = messaggio(d, "MATEMATICA", "2026-10-27")
        self.assertTrue(msg.startswith("MATEMATICA: 8½ orale (2026-10-27)"))
        self.assertTrue(msg.endswith("\n📊 media matematica: 7,25 · media generale: 8,00"))

    def test_media_esplicita_di_argo(self):
        d = dash({"MAT": {"mediaMateria": 6.4, "sommaValutazioniOrale": 1, "numValutazioniOrale": 1}}, 7.9)
        self.assertIn("media matematica: 6,50", messaggio(d, "MATEMATICA", "2026-10-05"))

    def test_senza_dati_di_argo_calcola_dai_voti(self):
        d = dash()
        self.assertIn("media matematica: 7,25", messaggio(d, "MATEMATICA", "2026-10-20"))
        # inglese: solo il 9- (il giudizio non è numerico, il 4 non fa media)
        self.assertIn("media inglese: 8,75", messaggio(d, "INGLESE", "2026-10-08"))
        # generale: 8, 5, 8½, 9- → 7,5625 → 7,50
        self.assertIn("media generale: 7,50", messaggio(d, "INGLESE", "2026-10-08"))

    def test_materia_senza_voti_numerici(self):
        d = raw()
        d["voti"] = [voto("REL", "RELIGIONE", "2026-10-05", 1, "ottimo", None)]
        msg = messaggio(d, "RELIGIONE", "2026-10-05")
        self.assertNotIn("📊", msg)

    def test_formato(self):
        self.assertEqual([m.fmt_media(x) for x in (7, 7.1, 7.125, 7.37, 7.4, 7.6, 7.874, 7.875, 9.99, None)],
                         ["7,00", "7,00", "7,25", "7,25", "7,50", "7,50", "7,75", "8,00", "10,00", "–"])


if __name__ == "__main__":
    unittest.main()
