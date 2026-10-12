#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["google-api-python-client==2.201.0", "google-auth==2.59.1",
#                 "google-auth-oauthlib==1.5.0"]
# ///
"""PoC 04 – autorizzazione Google: stato del token, refresh (solo in memoria), accesso a
Calendar con gli scope dello script principale.

  uv run pocs/04_google_auth.py [-c config.toml] [--token PATH] [--anonimizza]
  uv run pocs/04_google_auth.py --login     # flusso OAuth nel browser → pocs/out/token-poc.json
"""

from datetime import datetime, timezone

from googleapiclient.errors import HttpError

from _common import OUT, SCOPES, Anon, carica_config, dump, parser, risolvi, tabella, titolo
from _google import aggiungi_argomenti, credenziali, percorso_token, scope_concessi, servizio


def login(cfg: dict, cfg_path) -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    g = cfg.get("google") or {}
    secret = risolvi(g.get("client_secret_file", "client_secret.json"), cfg_path)
    if not secret.is_file():
        raise SystemExit(f"client_secret non trovato: {secret}")
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    OUT.mkdir(exist_ok=True)
    dest = OUT / "token-poc.json"
    dest.write_text(creds.to_json())
    dest.chmod(0o600)
    print(f"Token salvato in {dest} (quello di produzione non è stato toccato).\n"
          f"Usalo negli altri PoC con --token {dest}")


def main() -> None:
    ap = parser(__doc__)
    aggiungi_argomenti(ap)
    ap.add_argument("--login", action="store_true", help="nuova autorizzazione in pocs/out/token-poc.json")
    args = ap.parse_args()
    cfg, cfg_path = carica_config(args.config)
    anon = Anon(args.anonimizza)
    if args.login:
        return login(cfg, cfg_path)

    path = percorso_token(cfg, cfg_path, args.token)
    titolo("Token")
    print(f"file: {path}")
    if not path.is_file():
        raise SystemExit(f"Token Google non trovato: {path} (usa --token o --login)")
    concessi = scope_concessi(path)
    for s in SCOPES:
        print(f"  {'✅' if s in concessi else '❌'} {s}")
    if extra := sorted(set(concessi) - set(SCOPES)):
        print(f"  scope in più: {extra}")

    creds = credenziali(path, forza_refresh=True)
    scad = creds.expiry.replace(tzinfo=timezone.utc) if creds.expiry else None
    print(f"refresh token: {'presente' if creds.refresh_token else 'ASSENTE'}")
    print(f"refresh: ok, access token valido fino a {scad:%Y-%m-%d %H:%M %Z} "
          f"({int((scad - datetime.now(timezone.utc)).total_seconds() // 60)} min)" if scad else "refresh: ok")

    esito = {"token": str(path), "scopes": concessi, "calendari": []}

    titolo("Calendar (calendar.events: niente calendarList, provo i calendar_id del config)")
    cal = servizio("calendar", "v3", creds)
    righe = []
    for al in cfg.get("alunni", []):
        cid = al.get("calendar_id", "")
        try:
            r = cal.events().list(calendarId=cid, maxResults=1).execute()
            nome_cal = "" if anon.attivo else f"{r.get('summary', '')}, "
            stato = f"ok ({nome_cal}tz {r.get('timeZone', '?')})"
        except HttpError as e:
            stato = f"ERRORE {e.status_code}: {e.reason}"
        righe.append({"alunno": al.get("nome"), "calendar_id": cid, "accesso": stato})
    righe = anon(righe)
    tabella(righe, ["alunno", "calendar_id", "accesso"], larghezza=60)
    esito["calendari"] = righe

    dump("04_google_auth", esito, anon)


if __name__ == "__main__":
    main()
