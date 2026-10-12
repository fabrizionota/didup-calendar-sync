#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["didupwrapper==0.1.1", "httpx==0.28.1"]
# ///
"""PoC 02 – dashboard Argo: conteggi per tipo + un elemento grezzo per tipo,
poi come la interpreta lo script principale (build_snapshot).

  uv run pocs/02_argo_dashboard.py [-c config.toml] [--profilo N] [--anonimizza] [--tutti]
"""

import asyncio
import json
from collections import Counter
from datetime import date

from _argo import DiDUPError, client_da_account, estrai_dashboard
from _common import (Anon, argomenti_argo, carica_config, config_principale, dump, js, parser,
                     principale, selezione, tabella, titolo)


def confronto(main, cfg_path, inner: dict, al: dict, nome: str, anon: Anon, tutti: bool) -> dict:
    """Stessi dati grezzi -> modello didupwrapper -> build_snapshot dello script principale."""
    from didupwrapper.models import DashboardResponse

    mcfg = config_principale(main, cfg_path, al["nome"])  # impostazioni effettive dell'alunno
    d = DashboardResponse.model_validate(inner)
    snap = main.build_snapshot(d, {}, nome, mcfg, date.today(), raw=inner)
    compiti = main.estrai_compiti(d)

    titolo(f"{nome} – parsing dello script principale (build_snapshot, senza orario)")
    print(f"profilo_disabilitato: {d.profilo_disabilitato}")
    print(f"compiti estratti dal registro: {len(compiti)} (senza orario qui: quelli da oggi in poi "
          f"diventano eventi 📚; nella sync vera finiscono nelle lezioni quando ci sono)")
    righe = ([{"output": f"evento:{k}", "n": n} for k, n in Counter(i.kind for i in snap.cal).items()]
             + [{"output": f"notifica:{k}", "n": n}
                for k, n in Counter(x.kind for x in snap.notifiche).items()])
    tabella(righe, ["output", "n"])

    esempi = {}
    for kind in dict.fromkeys(i.kind for i in snap.cal):
        esempi[f"evento:{kind}"] = next(i for i in snap.cal if i.kind == kind)
    for kind in dict.fromkeys(x.kind for x in snap.notifiche):
        esempi[f"notifica:{kind}"] = next(x for x in snap.notifiche if x.kind == kind)
    for k, v in esempi.items():
        print(f"\n— esempio {k}")
        print(js(anon(json.loads(js(v, None))), limite=None if tutti else 1200))
    return {"cal": snap.cal, "notifiche": snap.notifiche}


async def main() -> None:
    ap = parser(__doc__)
    argomenti_argo(ap)
    ap.add_argument("--tutti", action="store_true", help="non troncare gli elementi a schermo")
    args = ap.parse_args()
    cfg, cfg_path = carica_config(args.config)
    anon = Anon(args.anonimizza)
    limite = None if args.tutti else 1500
    main_mod = principale()
    out = {}

    for acc, als in selezione(cfg, args):
        try:
            async with client_da_account(acc) as cli:
                for al in als:
                    nome, idx = al["nome"], al.get("profilo", 0)
                    etichetta = anon.pseudonimo(nome, "alunno") if anon.attivo else nome
                    cli.seleziona(idx)
                    raw = await cli.dashboard_raw()
                    inner = estrai_dashboard(raw) or {}

                    titolo(f"{etichetta} ({acc['codice_scuola']}, profilo {idx}) – dashboard grezza")
                    liste = {k: v for k, v in inner.items() if isinstance(v, list)}
                    scalari = {k: v for k, v in inner.items() if not isinstance(v, (list, dict))}
                    print("scalari:", js(anon(scalari), indent=None))
                    tabella([{"tipo": k, "n": len(v)} for k, v in sorted(liste.items())], ["tipo", "n"])
                    for k, v in sorted(liste.items()):
                        if v:
                            print(f"\n— {k}[0] (chiavi: {', '.join(sorted(v[0])) if isinstance(v[0], dict) else '-'})")
                            print(js(anon(v[0]), limite=limite))

                    voce = {"raw": raw}
                    if main_mod:
                        voce["script_principale"] = confronto(main_mod, cfg_path, inner, al, etichetta,
                                                              anon, args.tutti)
                    out[f"{acc['codice_scuola']}/profilo_{idx}"] = voce
        except DiDUPError as e:
            print(f"❌ {acc['codice_scuola']}: errore Argo: {e}")
            out[acc["codice_scuola"]] = {"errore": str(e)}
    dump("02_dashboard", out, anon)


if __name__ == "__main__":
    asyncio.run(main())
