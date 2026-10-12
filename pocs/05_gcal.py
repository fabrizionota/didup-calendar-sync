#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["google-api-python-client==2.201.0", "google-auth==2.59.1",
#                 "google-auth-oauthlib==1.5.0"]
# ///
"""PoC 05 – Google Calendar.

Default (sola lettura): per ogni calendario degli [[alunni]] conta gli eventi gestiti
(argo_sync=1) per tipo, con intervallo date e un esempio.
Con --scrivi --calendario ID (calendario di TEST, non uno dei figli): crea un evento con orario
e uno giornaliero, li rilegge, verifica i campi e li cancella.

  uv run pocs/05_gcal.py [-c config.toml] [--token PATH] [--anonimizza]
  uv run pocs/05_gcal.py --scrivi --calendario xxxx@group.calendar.google.com
"""

import secrets
from collections import defaultdict
from datetime import date, timedelta

from googleapiclient.errors import HttpError

from _common import Anon, carica_config, dump, js, parser, tabella, titolo
from _google import aggiungi_argomenti, credenziali, percorso_token, servizio


def eventi_gestiti(svc, cal_id: str) -> list[dict]:
    out, token = [], None
    while True:
        r = svc.events().list(calendarId=cal_id, privateExtendedProperty="argo_sync=1",
                              maxResults=2500, pageToken=token).execute()
        out += r.get("items", [])
        if not (token := r.get("nextPageToken")):
            return out


def giorno(ev: dict) -> str:
    s = ev.get("start", {})
    return (s.get("date") or s.get("dateTime") or "")[:10]


def lettura(svc, cfg: dict, anon: Anon) -> dict:
    esito = {}
    for al in cfg.get("alunni", []):
        nome = anon.pseudonimo(al["nome"], "alunno") if anon.attivo else al["nome"]
        cid = al.get("calendar_id", "")
        titolo(f"{nome} – {'(calendar_id)' if anon.attivo else cid}")
        try:
            evs = eventi_gestiti(svc, cid)
        except HttpError as e:
            print(f"ERRORE {e.status_code}: {e.reason}")
            continue
        per_tipo = defaultdict(list)
        for ev in evs:
            per_tipo[ev.get("extendedProperties", {}).get("private", {}).get("argo_kind", "?")].append(ev)
        tabella([{"tipo": k, "n": len(v), "dal": min(map(giorno, v)), "al": max(map(giorno, v))}
                 for k, v in sorted(per_tipo.items())], ["tipo", "n", "dal", "al"])
        for k, v in sorted(per_tipo.items()):
            print(f"\n— esempio {k}")
            print(js(anon(v[0]), limite=1200))
        esito[f"profilo_{al.get('profilo')}"] = evs
    return esito


def corpo(summary: str, inizio: dict, fine: dict, tag: str) -> dict:
    return {"summary": summary, "description": "Evento di prova didup-calendar-sync PoC 05, da cancellare",
            "start": inizio, "end": fine, "transparency": "transparent",
            "extendedProperties": {"private": {"argo_poc": "1", "argo_poc_run": tag}},
            "reminders": {"useDefault": False, "overrides": []}}


def scrittura(svc, cal_id: str, tz: str) -> dict:
    domani = date.today() + timedelta(days=1)
    tag = f"{date.today():%Y%m%d}-{secrets.token_hex(3)}"
    attesi = {
        "orario": corpo("🧪 PoC 05 – con orario",
                        {"dateTime": f"{domani}T10:00:00", "timeZone": tz},
                        {"dateTime": f"{domani}T11:00:00", "timeZone": tz}, tag),
        "giornaliero": corpo("🧪 PoC 05 – giornaliero", {"date": str(domani)},
                             {"date": str(domani + timedelta(days=1))}, tag),
    }
    creati, esito = {}, {}
    try:
        titolo("Creazione")
        for k, b in attesi.items():
            creati[k] = svc.events().insert(calendarId=cal_id, body=b).execute()
            print(f"+ {k}: id {creati[k]['id']}")

        titolo("Rilettura e verifica")
        for k, ev in creati.items():
            r = svc.events().get(calendarId=cal_id, eventId=ev["id"]).execute()
            b = attesi[k]
            controlli = {
                "summary": r.get("summary") == b["summary"],
                "start": r["start"].get("date") == b["start"].get("date") if "date" in b["start"]
                else r["start"].get("dateTime", "").startswith(b["start"]["dateTime"]),
                "timeZone": r["start"].get("timeZone") == b["start"].get("timeZone"),
                "extendedProperties": r.get("extendedProperties", {}).get("private", {}).get("argo_poc") == "1",
                "reminders off": r.get("reminders", {}).get("useDefault") is False,
            }
            print(f"{k}: start={js(r['start'], indent=None)} end={js(r['end'], indent=None)}")
            for c, ok in controlli.items():
                print(f"   {'✅' if ok else '❌'} {c}")
            esito[k] = {"evento": r, "controlli": controlli}

        trovati = svc.events().list(calendarId=cal_id,
                                    privateExtendedProperty=f"argo_poc_run={tag}").execute().get("items", [])
        print(f"ricerca per extended property: {len(trovati)}/{len(creati)} trovati")
    finally:
        titolo("Pulizia")
        for k, ev in creati.items():
            try:
                svc.events().delete(calendarId=cal_id, eventId=ev["id"]).execute()
                stato = svc.events().get(calendarId=cal_id, eventId=ev["id"]).execute().get("status")
                print(f"- {k}: cancellato (status ora: {stato})")
            except HttpError as e:
                print(f"- {k}: {'cancellato' if e.status_code in (404, 410) else f'ERRORE {e}'}")
    return esito


def main() -> None:
    ap = parser(__doc__)
    aggiungi_argomenti(ap)
    ap.add_argument("--scrivi", action="store_true", help="crea/rilegge/cancella eventi di prova")
    ap.add_argument("--calendario", help="ID del calendario di TEST (obbligatorio con --scrivi)")
    args = ap.parse_args()
    cfg, cfg_path = carica_config(args.config)
    anon = Anon(args.anonimizza)
    if args.scrivi:
        if not args.calendario:
            raise SystemExit("--scrivi richiede --calendario ID (un calendario di test)")
        if args.calendario in {al.get("calendar_id") for al in cfg.get("alunni", [])}:
            raise SystemExit("Rifiutato: è il calendario di uno dei figli. Usa un calendario di test.")
    svc = servizio("calendar", "v3", credenziali(percorso_token(cfg, cfg_path, args.token)))

    if not args.scrivi:
        dump("05_gcal", lettura(svc, cfg, anon), anon)
        return
    tz = (cfg.get("calendario") or {}).get("timezone", "Europe/Rome")
    dump("05_gcal_scrivi", scrittura(svc, args.calendario, tz), anon)


if __name__ == "__main__":
    main()
