#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx==0.28.1"]
# ///
"""PoC 07 – notifiche Home Assistant / Telegram.

Default (sola lettura): mostra la configurazione e il messaggio di prova, verifica che HA
risponda (GET /api/, ogni servizio notify esistente: service e [[destinatari]], con i loro
filtri) e che il bot Telegram sia valido (getMe). Con --scrivi: invia davvero la notifica di prova a
tutti i destinatari.

  uv run pocs/07_notify.py [-c config.toml] [--solo ha|telegram] [--scrivi]
"""

from datetime import datetime

import httpx

from _common import Anon, carica_config, dump, parser, titolo


def destinatari(ha: dict) -> list[tuple[str, str]]:
    """(servizio, filtri) per service e ogni [[notifiche.homeassistant.destinatari]]."""
    out = [(ha["service"].removeprefix("notify."), "tutto")] if ha.get("service") else []
    for d in ha.get("destinatari", []):
        filtri = ", ".join(f"{k}={'/'.join(d[k])}" for k in ("tipi", "alunni") if d.get(k)) or "tutto"
        out.append((str(d.get("service", "")).removeprefix("notify."), filtri))
    return out


def verifica_ha(c: httpx.Client, ha: dict) -> dict:
    base, hdr = ha["url"].rstrip("/"), {"Authorization": f"Bearer {ha.get('token', '')}"}
    r = c.get(f"{base}/api/", headers=hdr)
    print(f"GET /api/: {r.status_code} {r.text[:100]}")
    r.raise_for_status()
    servizi = c.get(f"{base}/api/services", headers=hdr).raise_for_status().json()
    notify = sorted(next((d["services"] for d in servizi if d["domain"] == "notify"), {}))
    esito = {}
    for servizio, filtri in destinatari(ha):
        esito[servizio] = servizio in notify
        print(f"{'✅' if esito[servizio] else '❌'} notify.{servizio} ({filtri})"
              + ("" if esito[servizio] else " non esiste"))
    if not all(esito.values()) or not esito:
        print(f"servizi notify disponibili: {', '.join(notify)}")
    return {"api": "ok", "servizi": esito, "notify": notify}


def verifica_tg(c: httpx.Client, tg: dict) -> dict:
    r = c.get(f"https://api.telegram.org/bot{tg.get('bot_token', '')}/getMe")
    dati = r.json()
    if not dati.get("ok"):
        raise SystemExit(f"Telegram getMe: {r.status_code} {dati.get('description')}")
    bot = dati["result"]
    print(f"✅ bot @{bot.get('username')} (id {bot.get('id')}), chat_id configurato: {tg.get('chat_id')}")
    return {"bot": bot.get("username")}


def main() -> None:
    ap = parser(__doc__)
    ap.add_argument("--solo", choices=["ha", "telegram"])
    ap.add_argument("--scrivi", action="store_true", help="invia davvero la notifica di prova")
    args = ap.parse_args()
    cfg, _ = carica_config(args.config)
    anon = Anon(args.anonimizza)
    n = cfg.get("notifiche") or {}
    canali = {"ha": n.get("homeassistant"), "telegram": n.get("telegram")}
    if args.solo:
        canali = {args.solo: canali[args.solo]}
    canali = {k: v for k, v in canali.items() if v}
    if not canali:
        raise SystemExit("Nessun canale configurato in [notifiche.homeassistant] / [notifiche.telegram]")

    titolo("Configurazione")
    print(f"tipi notificati: {n.get('tipi')}")
    for k, v in canali.items():
        print(f"{k}: {anon(v)}")
    for k, campo, env in (("ha", "token", "HA_TOKEN"), ("telegram", "bot_token", "TELEGRAM_BOT_TOKEN")):
        if k in canali and not canali[k].get(campo):
            raise SystemExit(f"{k}: manca {campo} (variabile {env})")

    titolo_msg = "🧪 Argo sync – prova"
    messaggio = f"Notifica di prova dal PoC 07 ({datetime.now():%d/%m %H:%M})"
    print(f"\nmessaggio di prova: {titolo_msg} | {messaggio}")

    esito = {}
    try:
        invia_e_verifica(canali, args.scrivi, titolo_msg, messaggio, esito)
    except httpx.HTTPError as e:
        msg = str(e)
        for segreto in (v.get("bot_token") or v.get("token") for v in canali.values()):
            if segreto:
                msg = msg.replace(segreto, "***")
        raise SystemExit(f"Errore HTTP: {type(e).__name__}: {msg}")
    if not args.scrivi:
        print("\n(sola lettura: nessuna notifica inviata, usa --scrivi)")
    dump("07_notify", esito, anon)


def invia_e_verifica(canali: dict, scrivi: bool, titolo_msg: str, messaggio: str, esito: dict) -> None:
    with httpx.Client(timeout=15) as c:
        if "ha" in canali:
            titolo("Home Assistant")
            esito["ha"] = verifica_ha(c, canali["ha"])
            if scrivi:
                ha = canali["ha"]
                for servizio, _ in destinatari(ha):
                    r = c.post(f"{ha['url'].rstrip('/')}/api/services/notify/{servizio}",
                               headers={"Authorization": f"Bearer {ha['token']}"},
                               json={"title": titolo_msg, "message": messaggio})
                    print(f"POST notify.{servizio}: {r.status_code}")
                    r.raise_for_status()
                esito["ha"]["inviata"] = True
        if "telegram" in canali:
            titolo("Telegram")
            tg = canali["telegram"]
            esito["telegram"] = verifica_tg(c, tg)
            if scrivi:
                r = c.post(f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage",
                           json={"chat_id": tg["chat_id"], "text": f"{titolo_msg}\n{messaggio}"})
                print(f"sendMessage: {r.status_code} {r.json().get('description', 'ok')}")
                r.raise_for_status()
                esito["telegram"]["inviata"] = True


if __name__ == "__main__":
    main()
