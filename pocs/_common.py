"""Helper condivisi dai PoC: config/.env, anonimizzazione, dump, import dello script principale.

Non è uno script: i PoC lo importano perché ``uv run`` mette la loro cartella in ``sys.path``.
Solo libreria standard, così vale per tutti i PoC qualunque siano le loro dipendenze.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
import tomllib
from datetime import date, datetime
from pathlib import Path
from typing import Any

POCS = Path(__file__).resolve().parent
ROOT = POCS.parent
OUT = POCS / "out"

SCOPES = ["https://www.googleapis.com/auth/calendar.events",
          "https://www.googleapis.com/auth/drive.file"]   # Drive: solo per [allegati] drive = true


# --------------------------------------------------------------------------- #
# Argomenti, .env, config                                                     #
# --------------------------------------------------------------------------- #
def parser(descrizione: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=descrizione)
    ap.add_argument("-c", "--config", type=Path,
                    help="config.toml (default: ./config.toml, ../config.toml, ../data/config.toml)")
    ap.add_argument("--anonimizza", action="store_true",
                    help="nomi e testi liberi mascherati, a schermo e nel dump")
    return ap


def carica_env() -> None:
    """KEY=VALUE da .env (radice repo, pocs/, cwd); le variabili già esportate vincono."""
    for p in dict.fromkeys((ROOT / ".env", POCS / ".env", Path.cwd() / ".env")):
        if not p.is_file():
            continue
        for riga in p.read_text().splitlines():
            riga = riga.strip()
            if not riga or riga.startswith("#") or "=" not in riga:
                continue
            k, v = riga.removeprefix("export ").split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            os.environ.setdefault(k.strip(), v)


def trova_config(path: Path | None) -> Path:
    candidati = [path] if path else [Path.cwd() / "config.toml", ROOT / "config.toml",
                                     ROOT / "data" / "config.toml"]
    for p in candidati:
        if p and p.is_file():
            return p.resolve()
    sys.exit("config.toml non trovato, cercato in: " + ", ".join(str(p) for p in candidati)
             + "\n→ passalo con -c")


def carica_config(path: Path | None) -> tuple[dict, Path]:
    """Lettura indipendente dallo script principale (stessi override da env)."""
    carica_env()
    p = trova_config(path)
    cfg = tomllib.loads(p.read_text())
    if "argo" in cfg:
        sys.exit("La sezione [argo] non è più supportata: ogni [[alunni]] indica codice_scuola, "
                 "username e password_env (vedi config.example.toml)")
    n = cfg.setdefault("notifiche", {})
    if ha := n.get("homeassistant"):
        ha["token"] = os.environ.get("HA_TOKEN", ha.get("token", ""))
        ha["service"] = ha.get("service", "").removeprefix("notify.")  # accetta anche "notify.xxx"
    if tg := n.get("telegram"):
        tg["bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN", tg.get("bot_token", ""))
    cfg.setdefault("alunni", [])
    return cfg, p


def risolvi(percorso: str, cfg_path: Path) -> Path:
    """Path dal config: com'è, poi relativo al config, poi solo il nome accanto al config
    (utile quando il config punta a /data/... del container)."""
    p = Path(percorso).expanduser()
    for c in (p, cfg_path.parent / p, cfg_path.parent / p.name):
        if c.exists():
            return c
    return p


def account(al: dict) -> dict:
    """Credenziali Argo dell'alunno (password dalla variabile in password_env)."""
    env = al.get("password_env", "ARGO_PASSWORD")
    return {"codice_scuola": al.get("codice_scuola", ""), "username": al.get("username", ""),
            "password": os.environ.get(env, ""), "password_env": env}


def chiave(acc: dict) -> tuple[str, str]:
    return acc["codice_scuola"], acc["username"]


def raggruppa(als: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Un login per (scuola, username)."""
    out: dict = {}
    for al in als:
        acc = account(al)
        out.setdefault(chiave(acc), (acc, []))[1].append(al)
    return list(out.values())


def argomenti_argo(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--alunno", help="solo questo alunno (nome nel config)")
    ap.add_argument("--scuola", help="solo gli alunni di questa scuola (codice_scuola)")
    ap.add_argument("--profilo", type=int,
                    help="solo questo indice di profilo; se non è nel config, l'account è quello "
                         "di --alunno o --scuola")


def selezione(cfg: dict, args) -> list[tuple[dict, list[dict]]]:
    """Alunni scelti con --alunno/--scuola/--profilo, raggruppati per account (un login ciascuno)."""
    als = cfg["alunni"]
    if args.alunno:
        als = [al for al in als if al.get("nome", "").casefold() == args.alunno.casefold()]
    if args.scuola:
        als = [al for al in als if al.get("codice_scuola") == args.scuola]
    if args.profilo is not None:
        sel = [al for al in als if al.get("profilo", 0) == args.profilo]
        if not sel and als and (args.alunno or args.scuola):
            # profilo non nel config: stesso account dell'alunno/scuola scelti
            base = als[0]
            sel = [{**{k: base[k] for k in ("codice_scuola", "username", "password_env") if k in base},
                    "profilo": args.profilo, "nome": f"profilo-{args.profilo}"}]
        als = sel
    if not als:
        sys.exit("Nessun alunno selezionato: controlla [[alunni]] e --alunno/--scuola/--profilo "
                 "(per un profilo fuori config serve --alunno o --scuola per scegliere l'account)")
    return raggruppa(als)


def config_principale(main, cfg_path: Path, nome: str) -> dict:
    """Impostazioni effettive dell'alunno secondo lo script principale (per il confronto)."""
    mcfg = main.load_config(cfg_path)
    return next((al["cfg"] for al in mcfg["alunni"] if al["nome"] == nome),
                main.config_alunno(mcfg, {}))


# --------------------------------------------------------------------------- #
# Anonimizzazione                                                             #
# --------------------------------------------------------------------------- #
# Sempre mascherati, con o senza --anonimizza
SEGRETI = re.compile(r"^(x-auth-token|token|access_token|refresh_token|id_token|password|"
                     r"client_secret|bot_token|codmin|authorization|clientid)$", re.I)
# Con --anonimizza: persone -> pseudonimo stabile
PERSONE = re.compile(r"(nome|cognome|nominativo|docente|autore|alunno|genitore|utente|username|"
                     r"email|mail|codicefiscale|codfiscale)", re.I)
# Con --anonimizza: testi liberi -> "[testo, N car.]"
TESTI = re.compile(r"^(compito|compiti_testo|desannotazioni|annotazioni|messaggio|descrizione|"
                   r"descrizioneprova|descrizionevoto|descommento|commento|commentogiustificazione|"
                   r"nota|attivita|nomefile|descrizionefile|url|path|desurl|summary|description|"
                   r"title|notes|message|testo|dettagli)$", re.I)
NON_PERSONE = re.compile(r"^(pk|prg|cod|num|flg|is|dat|data)", re.I)  # pkDocente ecc.


def _sale() -> bytes:
    """Sale locale (pocs/out/.sale): pseudonimi stabili tra i run ma non invertibili."""
    f = OUT / ".sale"
    if not f.exists():
        OUT.mkdir(exist_ok=True)
        f.write_text(secrets.token_hex(16))
        f.chmod(0o600)
    return f.read_bytes()


class Anon:
    def __init__(self, attivo: bool):
        self.attivo = attivo
        self._sale = _sale() if attivo else b""

    def pseudonimo(self, valore: str, chiave: str = "") -> str:
        if not valore:
            return valore
        k = chiave.lower()
        prefisso = ("Email" if "mail" in k else "Docente" if "docente" in k or "autore" in k
                    else "Alunno" if "alunno" in k else "CF" if "fiscale" in k else "Persona")
        return f"{prefisso}-{hashlib.sha256(self._sale + valore.encode()).hexdigest()[:4]}"

    @staticmethod
    def testo(valore: str) -> str:
        return f"[testo, {len(valore)} car.]" if valore else valore

    def __call__(self, obj: Any, chiave: str = "") -> Any:
        if isinstance(obj, dict):
            return {k: self._campo(k, v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self(x, chiave) for x in obj]
        return obj

    def _campo(self, k: str, v: Any) -> Any:
        if SEGRETI.match(k) and v not in (None, ""):
            return "***"
        if not self.attivo:
            return self(v, k)
        if isinstance(v, str):
            if TESTI.match(k):
                return self.testo(v)
            if PERSONE.search(k) and not NON_PERSONE.match(k):
                return self.pseudonimo(v, k)
            return v
        if isinstance(v, list) and v and all(isinstance(x, str) for x in v) and PERSONE.search(k):
            return [self.pseudonimo(x, k) for x in v]
        return self(v, k)


# --------------------------------------------------------------------------- #
# Output                                                                      #
# --------------------------------------------------------------------------- #
def _json_default(o: Any) -> Any:
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if hasattr(o, "model_dump"):
        return o.model_dump(by_alias=True)
    if hasattr(o, "__dataclass_fields__"):
        return {k: getattr(o, k) for k in o.__dataclass_fields__}
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def js(obj: Any, indent: int | None = 1, limite: int | None = None) -> str:
    s = json.dumps(obj, ensure_ascii=False, indent=indent, default=_json_default)
    return s if not limite or len(s) <= limite else s[:limite] + f"… (+{len(s) - limite} car.)"


def dump(nome: str, dati: Any, anon: Anon) -> Path:
    """pocs/out/<nome>_<timestamp>.json, permessi 600. Dati reali se non --anonimizza
    (i segreti sono comunque mascherati)."""
    OUT.mkdir(exist_ok=True)
    p = OUT / f"{nome}_{datetime.now():%Y%m%d-%H%M%S}.json"
    p.write_text(js(anon(json.loads(js(dati, None)))))
    p.chmod(0o600)
    print(f"\n→ dump: {p.relative_to(ROOT)}{' (anonimizzato)' if anon.attivo else ' (DATI REALI)'}")
    return p


def titolo(s: str) -> None:
    print(f"\n=== {s} " + "=" * max(0, 74 - len(s)))


def tabella(righe: list[dict], colonne: list[str], larghezza: int = 40) -> None:
    if not righe:
        print("  (nessuna riga)")
        return
    cel = [[str("" if r.get(c) is None else r.get(c)).replace("\n", " ⏎ ")[:larghezza] for c in colonne]
           for r in righe]
    w = [max(len(c), *(len(x[i]) for x in cel)) for i, c in enumerate(colonne)]
    print("  " + " │ ".join(c.ljust(w[i]) for i, c in enumerate(colonne)))
    print("  " + "─┼─".join("─" * x for x in w))
    for x in cel:
        print("  " + " │ ".join(v.ljust(w[i]) for i, v in enumerate(x)))


# --------------------------------------------------------------------------- #
# Script principale (solo per il confronto)                                   #
# --------------------------------------------------------------------------- #
def principale():
    """Importa didup_calendar_sync dalla radice del repo; None (con avviso) se non riesce."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        import didup_calendar_sync
        return didup_calendar_sync
    except Exception as e:  # noqa: BLE001
        print(f"\n⚠️  confronto con lo script principale saltato: import fallito ({type(e).__name__}: {e})")
        return None
