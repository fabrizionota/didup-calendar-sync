#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["didupwrapper==0.1.1", "httpx==0.28.1"]
# ///
"""PoC 03 – orario Argo (endpoint orario-giorno): risposta grezza + tabella numOra/materia/ora,
poi come la interpreta lo script principale (MultiProfiloClient.orario + costruisci_lezioni).

  uv run pocs/03_argo_orario.py [--giorno AAAA-MM-GG] [--giorni N] [--profilo N]
                                [--alunno NOME] [--grezzo] [--anonimizza]
"""

import asyncio
import json
import re
from datetime import date, timedelta

from _argo import DiDUPError, client_da_account, estrai_dashboard
from _common import (Anon, argomenti_argo, carica_config, config_principale, dump, js, parser,
                     principale, selezione, tabella, titolo)


GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def prossimo_giorno_scuola(oggi: date) -> date:
    g = oggi + timedelta(days=1)
    return g + timedelta(days=1) if g.weekday() == 6 else g


def righe_grezze(raw, giorno: date) -> list[dict]:
    """Lettura indipendente: data.dati è un dict (chiavi = numero d'ora, o data) di liste di ore,
    oppure direttamente una lista."""
    dati = ((raw or {}).get("data") or {}).get("dati") or {}
    if isinstance(dati, list):
        dati = {"": dati}
    out = []
    for k, ore in dati.items():
        g = str(k)[:10] if re.match(r"\d{4}-\d{2}-\d{2}", str(k)) else str(giorno)
        for o in ore or []:
            out.append({"giorno": g, "chiave": k, **o})
    return out


class StubOrario:
    """Al posto di MultiProfiloClient: restituisce le risposte già scaricate, senza chiamare Argo."""

    def __init__(self, risposte: dict):
        self.risposte = risposte

    async def orario_raw(self, giorno: date):
        r = self.risposte[giorno]
        if isinstance(r, Exception):
            raise r
        return r


async def confronto(main, cfg_path, al: dict, risposte: dict, giorni: list[date], d,
                    anon: Anon) -> dict:
    """``d``: dashboard (modello) dello stesso profilo, per nomi completi delle materie e compiti."""
    mcfg = config_principale(main, cfg_path, al["nome"])  # fasce/colori/materie_ignorate dell'alunno
    orario, scaricati = await main.MultiProfiloClient.orario(StubOrario(risposte), giorni)
    compiti = [c for _, c in main.estrai_compiti(d)]
    materie = main.mappa_materie(d)

    titolo("Parsing dello script principale – ore per giorno")
    print(f"giorni scaricati: {sorted(str(g) for g in scaricati)}")
    righe = []
    for g, ore in sorted(orario.items()):
        for o in sorted(ore, key=lambda x: x.get("numOra") or 0):
            t = main.ora_lezione(o, mcfg)
            righe.append({"giorno": g, "numOra": o.get("numOra"), "materia": o.get("materia"),
                          "nome completo": materie.get(main.norm(o.get("materia") or ""), "—"),
                          "docente": main.docente_di(o), "mostra": o.get("mostra"),
                          "orario": f"{t[0]}-{t[1]}" if t else "⚠️ nessuno (serve [orario.fasce])"})
    tabella(anon(json.loads(js([r for r in righe if r["mostra"] is not False], None))),
            ["giorno", "numOra", "materia", "nome completo", "orario", "docente"])

    lezioni = main.costruisci_lezioni(orario, compiti, mcfg, materie)
    titolo("Parsing dello script principale – eventi lezione (ore consecutive e compresenze unite)")
    print(f"compiti considerati per ✏️: {len(compiti)}"
          + (f" | materie ignorate: {mcfg['materie_ignorate']}" if mcfg.get("materie_ignorate") else ""))
    tabella([{"giorno": i.day, "inizio": i.start_time, "fine": i.end_time, "lezione": i.summary,
              "ore": i.description.splitlines()[0], "colore": i.color} for i in lezioni],
            ["giorno", "inizio", "fine", "lezione", "ore", "colore"])
    return {"giorni_scaricati": sorted(scaricati), "ore": righe, "eventi": lezioni}


async def main() -> None:
    ap = parser(__doc__)
    ap.add_argument("--giorno", type=date.fromisoformat,
                    help="primo giorno (default: prossimo giorno di scuola)")
    ap.add_argument("--giorni", type=int, default=1, help="quanti giorni da --giorno (domeniche escluse)")
    argomenti_argo(ap)
    ap.add_argument("--grezzo", action="store_true", help="stampa anche la risposta JSON grezza")
    args = ap.parse_args()
    cfg, cfg_path = carica_config(args.config)
    anon = Anon(args.anonimizza)
    inizio = args.giorno or prossimo_giorno_scuola(date.today())
    giorni = [g for g in (inizio + timedelta(days=i) for i in range(args.giorni)) if g.weekday() != 6]
    main_mod = principale()
    out = {}

    for acc, als in selezione(cfg, args):
        try:
            async with client_da_account(acc) as cli:
                for al in als:
                    nome, idx = al["nome"], al.get("profilo", 0)
                    etichetta = anon.pseudonimo(nome, "alunno") if anon.attivo else nome
                    cli.seleziona(idx)
                    risposte, voce = {}, {}
                    titolo(f"{etichetta} ({acc['codice_scuola']}, profilo {idx}) – orario-giorno grezzo")
                    for g in giorni:
                        try:
                            risposte[g] = await cli.orario_raw(g)
                        except DiDUPError as e:
                            risposte[g] = e
                            print(f"{g}: ERRORE {e}")
                            continue
                        righe = righe_grezze(risposte[g], g)
                        print(f"\n{g} ({GIORNI[g.weekday()]}): {len(righe)} ore")
                        if righe:
                            print("chiavi:", ", ".join(sorted(righe[0])))
                        tabella(anon(righe), ["giorno", "chiave", "numOra", "materia", "ora", "mostra", "docente"])
                        if args.grezzo:
                            print(js(anon(risposte[g])))
                    voce["raw"] = {str(g): (r if not isinstance(r, Exception) else f"ERRORE: {r}")
                                   for g, r in risposte.items()}

                    if main_mod:
                        from didupwrapper.models import DashboardResponse
                        d = DashboardResponse.model_validate(
                            estrai_dashboard(await cli.dashboard_raw()) or {})
                        voce["script_principale"] = await confronto(main_mod, cfg_path, al, risposte,
                                                                    giorni, d, anon)
                    out[f"{acc['codice_scuola']}/profilo_{idx}"] = voce
        except DiDUPError as e:
            print(f"❌ {acc['codice_scuola']}: errore Argo: {e}")
            out[acc["codice_scuola"]] = {"errore": str(e)}
    dump("03_orario", out, anon)


if __name__ == "__main__":
    asyncio.run(main())
