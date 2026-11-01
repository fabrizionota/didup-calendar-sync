"""Chiave dei voti: prgVoto non è univoco. Passaggio alle nuove chiavi senza valanga di notifiche."""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace as N

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import didup_calendar_sync as m  # noqa: E402
from test_snapshot import FakeNotifier  # noqa: E402

OGGI = date.today()


def voto(materia, giorno, prg, codice="8"):
    return N(pk_materia=materia, dat_giorno=f"{giorno} 00:00:00", prg_voto=prg, cod_codice=codice,
             descrizione_prova="")


def snapshot(*voti):
    s = m.Snapshot()
    for v in voti:
        s.notifiche.append(m.Notifica(m.chiave_voto(v), "voti", "🎓 Voto – A", f"{v.pk_materia} {v.cod_codice}",
                                      giorno=m.parse_date(v.dat_giorno)))
    return s


class TestChiave(unittest.TestCase):
    def test_prg_ripetuto_non_collide(self):
        # caso reale: prg 2 su materie e giorni diversi
        chiavi = {m.chiave_voto(voto("MAT", "2026-10-05", 2)), m.chiave_voto(voto("ING", "2026-10-08", 2)),
                  m.chiave_voto(voto("STO", "2026-10-27", 2))}
        self.assertEqual(len(chiavi), 3)

    def test_stabile_se_cambia_il_voto(self):
        self.assertEqual(m.chiave_voto(voto("MAT", "2026-10-05", 2, "8")), m.chiave_voto(voto("MAT", "2026-10-05", 2, "8+")))

    def test_senza_prg(self):
        self.assertNotEqual(m.chiave_voto(voto("MAT", "2026-10-05", None, "8")),
                            m.chiave_voto(voto("MAT", "2026-10-05", None, "6")))


class TestPassaggio(unittest.TestCase):
    def setUp(self):
        self.state = N(data={"seen": {}})
        self.n = FakeNotifier()

    def giro(self, snap):
        m.notify_new(snap, "SC1/u/0", "A", self.state, self.n, ["voti"])
        return self.n.sent

    def test_recupera_solo_gli_ultimi_giorni(self):
        vecchio = voto("MAT", OGGI - timedelta(days=30), 2)
        perso = voto("STO", OGGI, 2)                       # con la chiave vecchia era "già visto"
        self.state.data["seen"]["SC1/u/0"] = {"voti": [m.h("voto", 2)]}   # state.json vecchio
        with self.assertLogs(m.log) as lg:
            sent = self.giro(snapshot(vecchio, perso))
        self.assertEqual([s[1] for s in sent], ["STO 8"])
        self.assertIn("1 voti memorizzati senza notifica, 1 degli ultimi 10 giorni", lg.output[0])
        self.assertIn(m.MIGRAZIONE_VOTI, self.state.data["seen"]["SC1/u/0"]["_migrazioni"])
        self.assertEqual(self.giro(snapshot(vecchio, perso)), sent)   # niente di nuovo
        nuovo = voto("MAT", OGGI, 2)                       # stesso prg, altra materia: ora notificato
        self.assertEqual([s[1] for s in self.giro(snapshot(vecchio, perso, nuovo))][-1], "MAT 8")

    def test_primo_avvio_non_migra(self):
        with self.assertLogs(m.log) as lg:
            self.assertEqual(self.giro(snapshot(voto("MAT", OGGI, 1))), [])
        self.assertIn("primo avvio", lg.output[0])
        self.assertIn(m.MIGRAZIONE_VOTI, self.state.data["seen"]["SC1/u/0"]["_migrazioni"])


if __name__ == "__main__":
    unittest.main()
