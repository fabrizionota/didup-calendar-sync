#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["didupwrapper==0.1.1", "httpx==0.28.1"]
# ///
"""PoC 08 – allegati della bacheca Argo: come ottenere il link di download.

Il portale web (famiglia) chiede un link firmato temporaneo con
  POST https://didattica.portaleargo.it/famiglia/api/famiglia/downloadallegatobacheca
       {"uid": <pk allegato>, "pkScheda": <pk scheda alunno>}  → {"url": "..."}
Lo script principale usa invece l'API dell'app (www.portaleargo.it/appfamiglia/api/rest/).
Questo PoC prova più varianti, con la sessione dell'app, su UN allegato e riporta quali funzionano.

Solo lettura: non chiama presa visione né adesione. Con --scarica salva il file in pocs/out/.

  uv run pocs/08_argo_allegati.py --alunno Anna [--indice N] [--scarica] [--anonimizza]
"""

import asyncio
import json
import re

import httpx

from _argo import DiDUPError, client_da_account, estrai_dashboard
from _common import OUT, Anon, argomenti_argo, carica_config, dump, parser, selezione, tabella, titolo

WEB_API = "https://didattica.portaleargo.it/famiglia/api"


def candidati(uid: str, pk_scheda: str) -> list[tuple[str, str, dict]]:
    """(api, path, body): 'app' = API dell'app (sessione di didupwrapper), 'web' = API del portale."""
    return [
        ("app", "downloadallegatobacheca", {"uid": uid, "pkScheda": pk_scheda}),
        ("app", "downloadallegatobacheca", {"uid": uid}),
        ("app", "famiglia/downloadallegatobacheca", {"uid": uid, "pkScheda": pk_scheda}),
        ("web", "/famiglia/downloadallegatobacheca", {"uid": uid, "pkScheda": pk_scheda}),
    ]


def cerca_url(dati) -> str | None:
    """Il link può essere in data.url, url o annidato: lo cerca ovunque."""
    if isinstance(dati, dict):
        for k, v in dati.items():
            if k.lower() == "url" and isinstance(v, str) and v.startswith("http"):
                return v
            if (u := cerca_url(v)):
                return u
    if isinstance(dati, list):
        for x in dati:
            if (u := cerca_url(x)):
                return u
    return None


async def prova(cli, api: str, path: str, body: dict) -> tuple[str, object]:
    try:
        if api == "app":
            r = await cli._http.post(path, json=body, headers=cli._headers())
        else:
            async with httpx.AsyncClient(timeout=30) as h:
                r = await h.post(WEB_API + path, json=body,
                                 headers={"Authorization": f"Bearer {cli._auth.sessione.access_token}",
                                          "Content-Type": "application/json"})
        try:
            corpo = r.json()
        except ValueError:
            corpo = r.text[:300]
        return f"HTTP {r.status_code}", corpo
    except httpx.HTTPError as e:
        return f"errore {type(e).__name__}", str(e)[:200]


async def main() -> None:
    ap = parser(__doc__)
    argomenti_argo(ap)
    ap.add_argument("--indice", type=int, default=0, help="quale comunicazione con allegati (0 = la più recente)")
    ap.add_argument("--scarica", action="store_true", help="scarica l'allegato in pocs/out/ se il link si ottiene")
    args = ap.parse_args()
    cfg, _ = carica_config(args.config)
    anon = Anon(args.anonimizza)
    out = {}

    for acc, als in selezione(cfg, args):
        try:
            async with client_da_account(acc) as cli:
                for al in als:
                    nome = anon.pseudonimo(al["nome"], "alunno") if anon.attivo else al["nome"]
                    cli.seleziona(al.get("profilo", 0))
                    inner = estrai_dashboard(await cli.dashboard_raw()) or {}
                    pk_scheda = inner.get("pk", "")
                    con_allegati = [b for b in inner.get("bacheca") or [] if b.get("listaAllegati")]
                    file_alunno = inner.get("bachecaAlunno") or []
                    titolo(f"{nome} – bacheca: {len(con_allegati)} comunicazioni con allegati, "
                           f"{len(file_alunno)} file personali")
                    if not con_allegati:
                        continue
                    b = con_allegati[min(args.indice, len(con_allegati) - 1)]
                    a = b["listaAllegati"][0]
                    print(f"comunicazione del {b.get('data')}: "
                          f"{anon.testo(b.get('messaggio', '')) if anon.attivo else b.get('messaggio', '')[:80]}")
                    print(f"allegato: {anon.testo(a.get('nomeFile', '')) if anon.attivo else a.get('nomeFile')}"
                          f" (pk {a.get('pk', '')[:12]}…, path {a.get('path', '')[:40]}…)")

                    righe, url = [], None
                    for api, path, body in candidati(a.get("pk", ""), pk_scheda):
                        stato, corpo = await prova(cli, api, path, body)
                        trovato = cerca_url(corpo)
                        url = url or trovato
                        righe.append({"api": api, "chiamata": path, "body": ",".join(body),
                                      "esito": stato, "link": "✅" if trovato else "",
                                      "risposta": "" if trovato else json.dumps(corpo, ensure_ascii=False)[:90]})
                        if trovato:
                            break
                    tabella(righe, ["api", "chiamata", "body", "esito", "link", "risposta"], larghezza=90)

                    voce = {"comunicazione": b, "tentativi": righe,
                            "link_ottenuto": bool(url), "dominio_link": re.sub(r"^https?://([^/]+).*", r"\1", url or "")}
                    if url:
                        print(f"\n✅ link ottenuto (dominio {voce['dominio_link']}, valido pochi minuti)")
                        if args.scarica:
                            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as h:
                                r = await h.get(url)
                            nome_file = re.sub(r"[^\w.\- ]", "_", a.get("nomeFile") or "allegato")[:120]
                            OUT.mkdir(exist_ok=True)
                            dest = OUT / f"08_{nome_file}"
                            dest.write_bytes(r.content)
                            dest.chmod(0o600)
                            print(f"scaricato: {dest.name} ({len(r.content)} byte, "
                                  f"{r.headers.get('content-type', '?')}, HTTP {r.status_code})")
                            voce["scaricato"] = {"file": dest.name, "byte": len(r.content),
                                                 "content_type": r.headers.get("content-type")}
                    else:
                        print("\n❌ nessuna variante ha restituito un link: vedi la colonna risposta")
                    out[f"{acc['codice_scuola']}/{al.get('profilo', 0)}"] = voce
        except DiDUPError as e:
            print(f"❌ {acc['codice_scuola']}: errore Argo: {e}")
    dump("08_allegati", out, anon)


if __name__ == "__main__":
    asyncio.run(main())
