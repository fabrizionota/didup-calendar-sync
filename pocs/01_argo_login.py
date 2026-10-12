#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["didupwrapper==0.1.1", "httpx==0.28.1"]
# ///
"""PoC 01 – login Argo didUP su ogni account del config (una scuola/username per login):
versione client, profili disponibili (senza token), mappatura con gli [[alunni]].

  uv run pocs/01_argo_login.py [-c config.toml] [--anonimizza]
"""

import asyncio

from _argo import DiDUPError, client_da_account
from _common import Anon, carica_config, dump, js, parser, raggruppa, tabella, titolo

NASCOSTI = ("token", "opzioni")


async def login(acc: dict, miei: list[dict], anon: Anon) -> dict:
    async with client_da_account(acc) as cli:
        print(f"argo-client-version: {cli.versione}")
        print(f"profili restituiti:  {len(cli.profili)}")
        for i, p in enumerate(cli.profili):
            titolo(f"{acc['codice_scuola']} – profilo [{i}]")
            print("chiavi:", ", ".join(sorted(p)))
            print("opzioni:", len(p.get("opzioni") or []), "voci (non mostrate)")
            print(js(anon({k: v for k, v in p.items() if k not in NASCOSTI})))

        titolo(f"{acc['codice_scuola']} – [[alunni]] del config su questo account")
        tabella([{"nome (config)": anon.pseudonimo(al.get("nome", ""), "alunno") if anon.attivo
                  else al.get("nome"), "profilo": al.get("profilo", 0),
                  "esiste": "sì" if isinstance(al.get("profilo", 0), int)
                  and 0 <= al.get("profilo", 0) < len(cli.profili) else "NO"} for al in miei],
                ["nome (config)", "profilo", "esiste"])
        if liberi := sorted(set(range(len(cli.profili))) - {al.get("profilo", 0) for al in miei}):
            print(f"profili non usati nel config: {liberi}")
        return {"versione": cli.versione,
                "profili": [{k: v for k, v in p.items() if k != "token"} for p in cli.profili]}


async def main() -> None:
    args = parser(__doc__).parse_args()
    cfg, cfg_path = carica_config(args.config)
    anon = Anon(args.anonimizza)
    print(f"config: {cfg_path}")
    out = {}
    for acc, miei in raggruppa(cfg["alunni"]):
        nome_acc = f"{acc['codice_scuola']}/{anon.pseudonimo(acc['username'], 'username') if anon.attivo else acc['username']}"
        titolo(f"Login {nome_acc}")
        try:
            out[f"{acc['codice_scuola']}/{acc['username']}"] = await login(acc, miei, anon)
        except DiDUPError as e:
            print(f"❌ Errore Argo: {e}")
            out[f"{acc['codice_scuola']}/{acc['username']}"] = {"errore": str(e)}
    dump("01_login", out, anon)


if __name__ == "__main__":
    asyncio.run(main())
