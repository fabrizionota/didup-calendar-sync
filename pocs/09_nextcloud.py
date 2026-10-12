#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["didupwrapper==0.1.1", "httpx==0.28.1"]
# ///
"""PoC 09 – archivio allegati su Nextcloud (WebDAV).

Usa la classe Nextcloud dello script principale, con la config effettiva di ogni alunno che ha
[allegati] archivio = "nextcloud" (url, utente e app password da NEXTCLOUD_APP_PASSWORD o dalla
variabile in password_env).

Default (sola lettura): login WebDAV, esistenza della cartella radice e di quella dell'alunno.
Con --scrivi: carica un file di prova in <cartella>-test/<alunno>/ con la proprietà argo_key,
lo ritrova con un secondo client (come dopo la perdita di state.json) e stampa il link /f/<id>.
Il file resta su Nextcloud: cancellalo a mano.

  uv run pocs/09_nextcloud.py [-c config.toml] [--alunno NOME] [--scrivi]
"""

from datetime import datetime

from _common import carica_env, parser, principale, titolo, trova_config


def main() -> None:
    ap = parser(__doc__.splitlines()[0])
    ap.add_argument("--alunno", help="solo questo alunno")
    ap.add_argument("--scrivi", action="store_true", help="carica un file di prova")
    args = ap.parse_args()
    carica_env()
    m = principale()
    if m is None:
        raise SystemExit("serve lo script principale (didup_calendar_sync.py) per questo PoC")
    cfg = m.load_config(trova_config(args.config))
    als = [al for al in cfg["alunni"] if not args.alunno or al["nome"] == args.alunno]
    nc_als = [al for al in als if al["cfg"]["allegati"]["archivio"] == "nextcloud"]
    for al in als:
        print(f"{al['nome']}: archivio = {al['cfg']['allegati']['archivio'] or '(disattivo)'}")
    if not nc_als:
        raise SystemExit("\nNessun alunno con [allegati] archivio = \"nextcloud\"")

    for al in nc_als:
        a = al["cfg"]["allegati"]
        nc = a["nextcloud"]
        titolo(f"{al['nome']} → {nc.get('url', '?')} (utente {nc.get('utente', '?')}, link {nc['link']}, "
               f"password da {nc['password_env']}: {'presente' if nc.get('password') else 'MANCANTE'})")
        try:
            cli = m.Nextcloud(nc, dry_run=not args.scrivi)
            cli.verifica()
        except Exception as e:  # noqa: BLE001
            print(f"❌ {e}")
            continue
        print(f"✅ login WebDAV ok ({cli.dav})")
        for parti in ([a["cartella"]], [a["cartella"], a["sottocartella"]]):
            esiste = cli._props(parti) is not None
            print(f"{'✅' if esiste else '➖'} {'/'.join(parti)}: {'esiste' if esiste else 'non ancora creata'}")
        if not args.scrivi:
            print("(sola lettura: --scrivi per caricare un file di prova)")
            continue
        percorso = [f"{a['cartella']}-test", a["sottocartella"]]
        chiave = f"poc09:{datetime.now():%Y%m%d%H%M%S}"
        nome = f"prova didup-calendar-sync {datetime.now():%Y-%m-%d %H.%M.%S}.txt"
        cartella = cli.cartella(percorso)
        voce = cli.carica(cartella, nome, f"PoC 09 {chiave}\n".encode(), "text/plain", chiave)
        print(f"✅ caricato {'/'.join(percorso)}/{nome}\n   link: {voce['link']}")
        ritrovato = m.Nextcloud(nc, dry_run=True).cerca(chiave, percorso, nome)
        print(f"{'✅' if ritrovato == voce else '❌'} ritrovato da un nuovo client tramite argo_key: {ritrovato}")
        if cli.link == "pubblico":
            print("Apri il link dal telefono: deve aprirsi senza login (condivisione pubblica in sola lettura).")
        else:
            print("Apri il link dal telefono: deve chiedere il login Nextcloud (link interno, non pubblico).")


if __name__ == "__main__":
    main()
