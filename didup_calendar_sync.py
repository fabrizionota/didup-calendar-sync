#!/usr/bin/env python3
"""didup-calendar-sync: Argo didUP Famiglia -> Google Calendar + notifiche.

Per ogni figlio:
- Orario scolastico (endpoint ``orario-giorno``) -> eventi lezione su un calendario Google,
  per i prossimi N giorni; ore consecutive della stessa materia vengono unite.
- Compiti -> nella descrizione della lezione di quella materia il giorno di consegna (marcata ✏️);
  se quel giorno la lezione non c'è, evento giornaliero "📚 Materia: testo".
- Promemoria/verifiche e scadenze di adesione in bacheca -> eventi sul calendario.
- Allegati della bacheca (facoltativo) -> Google Drive o Nextcloud, link nella notifica e nell'evento.
- Notifiche (Home Assistant e/o Telegram) per voti, bacheca, note, promemoria (configurabile).

Sincronizzazione a senso unico e idempotente: gli eventi gestiti portano una chiave
stabile e un hash del contenuto; quanto creato a mano non viene toccato.

Uso:
  didup_calendar_sync.py -c config.toml --auth                 # una tantum, su un PC con browser (o pocs/04_google_auth.py --login)
  didup_calendar_sync.py -c config.toml --list-profiles
  didup_calendar_sync.py -c config.toml --debug-orario 2026-10-06
  didup_calendar_sync.py -c config.toml --dry-run
  didup_calendar_sync.py -c config.toml [--loop 1800]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from xml.sax.saxutils import escape

import httpx
from didupwrapper import DiDUPClient
from didupwrapper.client import (  # privati: versione fissata
    _DASHBOARD_PATH, _DATA_INIZIO_DEFAULT, _LOGIN_PATH, _estrai_dashboard, _random_string)
from didupwrapper.models import DashboardResponse
from didupwrapper.exceptions import DiDUPError

log = logging.getLogger("didup-calendar")

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
SCOPE_DRIVE = "https://www.googleapis.com/auth/drive.file"  # solo i file creati dallo script


# --------------------------------------------------------------------------- #
# Config                                                                      #
# --------------------------------------------------------------------------- #
def load_config(path: Path) -> dict:
    cfg = tomllib.loads(path.read_text())
    if "argo" in cfg:
        raise ValueError("La sezione [argo] non è più supportata: ogni [[alunni]] indica "
                         "codice_scuola, username e password_env (vedi config.example.toml)")
    n = cfg.setdefault("notifiche", {})
    if ha := n.get("homeassistant"):
        ha["token"] = os.environ.get("HA_TOKEN", ha.get("token", ""))
        ha["service"] = ha.get("service", "").removeprefix("notify.")  # accetta anche "notify.xxx"
    if tg := n.get("telegram"):
        tg["bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN", tg.get("bot_token", ""))
    n.setdefault("tipi", ["voti", "bacheca", "note", "promemoria"])
    c = cfg.setdefault("calendario", {})
    c.setdefault("timezone", "Europe/Rome")
    o = cfg.setdefault("orario", {})
    o.setdefault("giorni", 14)
    o.setdefault("durata_ora_min", 60)
    o.setdefault("fasce", {})
    cfg.setdefault("compiti", {}).setdefault("giorni_passati", 0)
    cfg.setdefault("colori_materie", {})
    al_cfg = cfg.setdefault("allegati", {})
    al_cfg["archivio"] = archivio_allegati(al_cfg, "")  # "drive", "nextcloud" o "" (disattivo)
    al_cfg["drive"] = al_cfg["archivio"] == "drive"
    al_cfg.setdefault("cartella", "Scuola")  # cartella radice (sottocartella per alunno)
    al_cfg.setdefault("max_per_giro", 30)    # quanti allegati caricare al massimo per giro
    al_cfg.setdefault("percorso", PERCORSO_DEFAULT)    # cartelle, dai segnaposto in SEGNAPOSTO
    al_cfg.setdefault("nome_file", NOME_FILE_DEFAULT)
    nc = al_cfg.setdefault("nextcloud", {})
    nc.setdefault("password_env", "NEXTCLOUD_APP_PASSWORD")
    nc.setdefault("link", "interno")       # "interno" (/f/<id>, con login) | "pubblico" (condivisione)
    nc.setdefault("scadenza_giorni", 0)    # solo per "pubblico": 0 = senza scadenza
    for env, chiave in (("NEXTCLOUD_URL", "url"), ("NEXTCLOUD_USER", "utente")):
        if os.environ.get(env):            # le variabili d'ambiente vincono sul config
            nc[chiave] = os.environ[env]

    alunni = cfg.setdefault("alunni", [])
    if not alunni:
        raise ValueError("Nessun [[alunni]] nel config")
    nomi = [al.get("nome") for al in alunni]
    if len(set(nomi)) != len(nomi):
        raise ValueError(f"Nomi alunni duplicati: {nomi}")
    for al in alunni:
        mancanti = [k for k in ("nome", "codice_scuola", "username", "calendar_id") if not al.get(k)]
        if mancanti:
            raise ValueError(f"[[alunni]] {al.get('nome', '?')}: mancano {', '.join(mancanti)}")
        al.setdefault("profilo", 0)
        al["account"] = account_alunno(al)
        al["cfg"] = config_alunno(cfg, al)
    return cfg


ARCHIVI = ("", "drive", "nextcloud")
SEGNAPOSTO = ("cartella", "alunno", "anno", "mese", "nome_mese", "giorno", "data", "nome")
PERCORSO_DEFAULT = "{cartella}/{alunno}/{anno}/{mese:02d} - {nome_mese}"
NOME_FILE_DEFAULT = "{data} {nome}"


def archivio_allegati(a: dict, default: str) -> str:
    """Dove archiviare gli allegati: ``archivio = "drive" | "nextcloud"``;
    ``drive = true/false`` (config precedenti) resta valido."""
    if "archivio" in a:
        v = a["archivio"] or ""
    elif "drive" in a:
        v = "drive" if a["drive"] else ""
    else:
        v = default
    if v not in ARCHIVI:
        raise ValueError(f"[allegati] archivio = {v!r}: valori ammessi \"drive\", \"nextcloud\" o \"\"")
    return v


def account_alunno(al: dict) -> dict:
    """Credenziali Argo dell'alunno; la password arriva dalla variabile indicata in password_env."""
    env = al.get("password_env", "ARGO_PASSWORD")
    return {"codice_scuola": al["codice_scuola"], "username": al["username"],
            "password": os.environ.get(env, ""), "password_env": env}


def config_alunno(cfg: dict, al: dict) -> dict:
    """Impostazioni effettive dell'alunno: quelle globali sovrascritte dalle sue
    ([alunni.orario], [alunni.compiti], [alunni.colori_materie], notifiche = [...],
    materie_ignorate = [...])."""
    eff = {k: v for k, v in cfg.items() if k != "alunni"}
    eff["orario"] = {**cfg["orario"], **al.get("orario", {})}
    eff["compiti"] = {**cfg["compiti"], **al.get("compiti", {})}
    eff["colori_materie"] = {**cfg["colori_materie"], **al.get("colori_materie", {})}
    eff["notifiche"] = {**cfg["notifiche"], "tipi": al.get("notifiche", cfg["notifiche"]["tipi"])}
    eff["materie_ignorate"] = al.get("materie_ignorate", cfg.get("materie_ignorate", []))
    proprie = al.get("allegati", {})
    a = eff["allegati"] = {**cfg["allegati"], "sottocartella": al["nome"], **proprie}
    a["archivio"] = archivio_allegati(proprie, cfg["allegati"]["archivio"])
    a["drive"] = a["archivio"] == "drive"
    a["nextcloud"] = {**cfg["allegati"]["nextcloud"], **proprie.get("nextcloud", {})}
    a["nextcloud"]["password"] = os.environ.get(a["nextcloud"]["password_env"], "")
    valida_allegati(a, al["nome"])
    return eff


def valida_allegati(a: dict, nome: str) -> None:
    """Modelli di percorso/nome file e opzioni del link: errori chiari all'avvio."""
    prova = {"cartella": "S", "alunno": "A", "anno": 2026, "mese": 10, "nome_mese": "Ottobre",
             "giorno": 12, "data": "2026-10-12", "nome": "x.pdf"}
    for campo in ("percorso", "nome_file"):
        try:
            a[campo].format(**prova)
        except KeyError as e:
            raise ValueError(f"[allegati] {campo} di {nome}: segnaposto sconosciuto {{{e.args[0]}}} "
                             f"(disponibili: {', '.join(SEGNAPOSTO)})") from None
        except (ValueError, IndexError, AttributeError) as e:
            raise ValueError(f"[allegati] {campo} di {nome}: modello non valido {a[campo]!r} ({e})") from None
    nc = a["nextcloud"]
    if nc["link"] not in ("interno", "pubblico"):
        raise ValueError(f"[allegati.nextcloud] link di {nome} = {nc['link']!r}: valori ammessi interno, pubblico")
    if not isinstance(nc["scadenza_giorni"], int) or nc["scadenza_giorni"] < 0:
        raise ValueError(f"[allegati.nextcloud] scadenza_giorni di {nome}: intero >= 0")


def account_key(acc: dict) -> tuple[str, str]:
    return acc["codice_scuola"], acc["username"]


def gruppi_account(cfg: dict) -> list[tuple[dict, list[dict]]]:
    """Alunni raggruppati per account: un solo login per (scuola, username)."""
    out: dict[tuple[str, str], tuple[dict, list[dict]]] = {}
    for al in cfg["alunni"]:
        out.setdefault(account_key(al["account"]), (al["account"], []))[1].append(al)
    return list(out.values())


def state_key(al: dict) -> str:
    acc = al["account"]
    return f"{acc['codice_scuola']}/{acc['username']}/{al['profilo']}"


def migra_state_key(state: "State", al: dict) -> None:
    """Le versioni precedenti usavano 'scuola/profilo': si riprende quello stato
    invece di ripartire con un primo avvio silenzioso."""
    seen, nuova = state.data["seen"], state_key(al)
    vecchia = f"{al['account']['codice_scuola']}/{al['profilo']}"
    if nuova not in seen and vecchia in seen:
        seen[nuova] = seen.pop(vecchia)


# --------------------------------------------------------------------------- #
# Client Argo multi-profilo                                                   #
# --------------------------------------------------------------------------- #
class MultiProfiloClient(DiDUPClient):
    """didupwrapper usa solo il primo profilo del login: qui li teniamo tutti."""

    async def _login_applicativo(self):
        dati = await self._post(_LOGIN_PATH, json={
            "lista-opzioni-notifiche": "{}",
            "lista-x-auth-token": "[]",
            "clientID": _random_string(163),
        })
        self._verifica_success(dati)
        self.profili: list[dict] = (dati or {}).get("data") or []
        if not self.profili:
            raise DiDUPError("Login applicativo: nessun profilo restituito", payload=dati)
        self._login_data = self.profili[0]
        return self._login_data

    dashboard_raw: dict = {}

    async def get_dashboard(self, *, forza_refresh: bool = False) -> DashboardResponse:
        """Come DiDUPClient.get_dashboard, ma tiene anche la risposta grezza: alcune scuole
        usano campi che il modello di didupwrapper scarta (es. note: desDescrizione, datNota)."""
        if self._dashboard_cache is not None and not forza_refresh:
            return self._dashboard_cache
        if self._login_data is None:
            await self.login()
        dati = await self._post(_DASHBOARD_PATH, json={
            "dataultimoaggiornamento": _DATA_INIZIO_DEFAULT,
            "opzioni": self._opzioni_serializzate(),
        })
        self._verifica_success(dati)
        self.dashboard_raw = _estrai_dashboard(dati) or {}
        self._dashboard_cache = DashboardResponse.model_validate(self.dashboard_raw)
        return self._dashboard_cache

    async def url_allegato(self, uid: str, pk_scheda: str) -> str:
        """Link firmato temporaneo (pochi minuti) per scaricare un allegato della bacheca."""
        dati = await self._post("downloadallegatobacheca", json={"uid": uid, "pkScheda": pk_scheda})
        self._verifica_success(dati)
        url = cerca_url(dati)
        if not url:
            raise DiDUPError("downloadallegatobacheca: risposta senza url", payload=dati)
        return url

    def seleziona_profilo(self, idx: int) -> None:
        if idx >= len(self.profili):
            raise DiDUPError(f"Profilo {idx} inesistente (trovati {len(self.profili)})")
        self._login_data = self.profili[idx]
        self.invalida_cache()

    async def orario_raw(self, giorno: date) -> Any:
        dati = await self._post("orario-giorno", json={"datGiorno": f"{giorno} 00:00:00.000"})
        self._verifica_success(dati)
        return dati

    async def orario(self, giorni: list[date]) -> tuple[dict[date, list[dict]], set[date]]:
        """Ore di lezione per giorno + insieme dei giorni scaricati con successo
        (solo su quelli si possono rimuovere lezioni sparite)."""
        out: dict[date, list[dict]] = {}
        ok: set[date] = set()
        for g in giorni:
            try:
                r = await self.orario_raw(g)
            except DiDUPError as e:
                log.warning("orario %s non scaricato: %s", g, e)
                continue
            dati = ((r or {}).get("data") or {}).get("dati") or {}
            ok.add(g)
            if isinstance(dati, list):
                dati = {str(g): dati}
            for k, ore in dati.items():
                giorno = parse_date(k) or g
                ok.add(giorno)
                for o in ore or []:
                    lst = out.setdefault(giorno, [])
                    if not any(x.get("numOra") == o.get("numOra") and x.get("materia") == o.get("materia")
                               for x in lst):
                        lst.append(o)
        return out, ok


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = str(s).strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    return date(int(m[3]), int(m[2]), int(m[1])) if m else None


def parse_hhmm(s: str | None) -> str | None:
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})", s or "")
    return f"{int(m[1]):02d}:{m[2]}" if m else None


def times_in(s: str | None) -> list[str]:
    return [f"{int(a):02d}:{b}" for a, b in re.findall(r"\b(\d{1,2})[:.](\d{2})\b", s or "")]


def add_min(hhmm: str, minutes: int) -> str:
    return (datetime.strptime(hhmm, "%H:%M") + timedelta(minutes=minutes)).strftime("%H:%M")


def norm(s: str) -> str:
    return " ".join((s or "").casefold().split())


def h(*parts: Any) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:20]


def cerca_url(dati: Any) -> str | None:
    """Primo campo "url" http(s) in una risposta JSON annidata."""
    if isinstance(dati, dict):
        for k, v in dati.items():
            if k.lower() == "url" and isinstance(v, str) and v.startswith("http"):
                return v
            if (u := cerca_url(v)):
                return u
    elif isinstance(dati, list):
        for x in dati:
            if (u := cerca_url(x)):
                return u
    return None


def short(s: str, n: int = 70) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


# --------------------------------------------------------------------------- #
# Modello interno                                                             #
# --------------------------------------------------------------------------- #
@dataclass
class CalItem:
    key: str
    kind: str                       # lezione | compito (senza lezione) | promemoria | scadenza
    summary: str
    description: str
    day: date
    start_time: str | None = None   # "HH:MM" -> evento con orario, altrimenti giornaliero
    end_time: str | None = None
    color: str | None = None
    reminders: bool = True          # False = nessun popup (lezioni)

    @property
    def content_hash(self) -> str:
        return h(self.summary, self.description, self.day, self.start_time,
                 self.end_time, self.color, self.reminders)


@dataclass
class Notifica:
    key: str
    kind: str
    title: str
    message: str
    url: str | None = None   # aperto toccando la notifica (es. allegato su Drive/Nextcloud)


@dataclass
class Snapshot:
    cal: list[CalItem] = field(default_factory=list)
    notifiche: list[Notifica] = field(default_factory=list)


@dataclass
class Compito:
    materia: str
    testo: str
    consegna: date
    assegnato: str
    docente: str


# --------------------------------------------------------------------------- #
# Costruzione snapshot                                                        #
# --------------------------------------------------------------------------- #
def estrai_compiti(d) -> list[tuple[str, Compito]]:
    out = []
    for lez in d.registro:
        for i, c in enumerate(lez.compiti):
            day = parse_date(c.data_consegna)
            if day and c.compito:
                key = h("compito", lez.pk_materia or lez.materia, lez.dat_giorno, c.data_consegna, i)
                out.append((key, Compito(lez.materia, c.compito, day, lez.dat_giorno[:10], lez.docente)))
    return out


def ora_lezione(o: dict, cfg: dict) -> tuple[str, str] | None:
    t = times_in(o.get("ora"))
    durata = cfg["orario"]["durata_ora_min"]
    if len(t) >= 2:
        return t[0], t[1]
    if len(t) == 1:
        return t[0], add_min(t[0], durata)
    fascia = cfg["orario"]["fasce"].get(str(o.get("numOra")))
    if fascia:
        t = times_in(fascia)
        if len(t) >= 2:
            return t[0], t[1]
        if t:
            return t[0], add_min(t[0], durata)
    return None


def docente_di(o: dict) -> str:
    return (o.get("docente") or f"{o.get('desNome', '')} {o.get('desCognome', '')}").strip()


def nome_materia(s: str) -> str:
    """Per i titoli: 'LINGUA E CULTURA LATINA' -> 'Lingua e cultura latina'."""
    s = " ".join((s or "").split())
    return s[:1].upper() + s[1:].lower()


def mappa_materie(d) -> dict[str, str]:
    """Nome usato dall'orario (spesso l'abbreviazione di listaMaterie) -> nome completo,
    lo stesso usato da registro e compiti."""
    out: dict[str, str] = {}
    for m in d.lista_materie:
        if m.materia:
            out[norm(m.materia)] = m.materia
            if m.abbreviazione:
                out.setdefault(norm(m.abbreviazione), m.materia)
    return out


def abbreviazioni(d) -> dict[str, str]:
    """Nome completo (registro) -> abbreviazione Argo, la stessa usata dall'orario."""
    return {norm(m.materia): m.abbreviazione for m in d.lista_materie if m.materia and m.abbreviazione}


def testo_compito(c: Compito) -> str:
    return f"- {c.testo}\n  (assegnato il {c.assegnato} da {c.docente})"


def costruisci_lezioni(orario: dict[date, list[dict]], compiti: list[Compito], cfg: dict,
                       materie: dict[str, str] | None = None,
                       usati: set[int] | None = None) -> list[CalItem]:
    """``usati``: se passato, vi aggiunge id() dei compiti finiti nella descrizione di una lezione."""
    materie = materie or {}

    def completo(s: str) -> str:
        return materie.get(norm(s), s)

    per_giorno_materia: dict[tuple[date, str], list[Compito]] = {}
    for c in compiti:
        per_giorno_materia.setdefault((c.consegna, norm(completo(c.materia))), []).append(c)
    colori = {norm(completo(k)): str(v) for k, v in cfg.get("colori_materie", {}).items()}
    ignorate = {norm(completo(x)) for x in cfg.get("materie_ignorate", [])}

    items, senza_orario = [], 0
    for giorno, ore in sorted(orario.items()):
        # Una "fascia" per numOra: più materie nella stessa ora (compresenza) diventano un evento
        fasce: dict[int, dict] = {}
        for o in sorted(ore, key=lambda x: x.get("numOra") or 0):
            if o.get("mostra") is False or not o.get("materia"):
                continue
            mat = completo(o["materia"])
            if norm(mat) in ignorate:
                continue
            f = fasce.setdefault(o.get("numOra") or 0, {"materie": [], "etichette": [], "docenti": [], "ore": []})
            if mat not in f["materie"]:
                f["materie"].append(mat)
                f["etichette"].append(o["materia"])  # nome dell'orario (abbreviazione Argo)
            if (doc := docente_di(o)) and doc not in f["docenti"]:
                f["docenti"].append(doc)
            f["ore"].append(o)

        blocchi: list[dict] = []
        for n, f in sorted(fasce.items()):
            t = next((t for t in (ora_lezione(o, cfg) for o in f["ore"]) if t), None)
            if not t:
                senza_orario += 1
                continue
            prev = blocchi[-1] if blocchi else None
            if (prev and prev["materie"] == f["materie"] and prev["docenti"] == f["docenti"]
                    and (prev["fine"] == t[0] or prev["ultima"] + 1 == n)):
                prev["fine"], prev["ultima"] = t[1], n
                continue
            blocchi.append({"materie": f["materie"], "etichette": f["etichette"],
                            "docenti": f["docenti"], "inizio": t[0],
                            "fine": t[1], "prima": n, "ultima": n})
        for b in blocchi:
            comp = [c for mat in b["materie"] for c in per_giorno_materia.get((giorno, norm(mat)), [])]
            desc = ""
            if [norm(x) for x in b["etichette"]] != [norm(x) for x in b["materie"]]:
                desc = f"Materia: {' / '.join(nome_materia(x) for x in b['materie'])}\n"
            desc += f"Docente: {', '.join(b['docenti'])}" if b["docenti"] else ""
            if comp:
                desc += "\n\nCompiti da consegnare:\n" + "\n".join(testo_compito(c) for c in comp)
                if usati is not None:
                    usati.update(id(c) for c in comp)
            ore_txt = f"{b['prima']}ª" if b["prima"] == b["ultima"] else f"{b['prima']}ª–{b['ultima']}ª"
            items.append(CalItem(
                key=h("lezione", giorno, b["prima"], norm(" / ".join(b["materie"]))),
                kind="lezione",
                summary=" / ".join(nome_materia(x) for x in b["etichette"]) + (" ✏️" if comp else ""),
                description=f"{ore_txt} ora\n{desc}".strip(),
                day=giorno, start_time=b["inizio"], end_time=b["fine"],
                color=next((colori[norm(x)] for x in b["materie"] if norm(x) in colori), None),
                reminders=False,
            ))
    if senza_orario:
        log.warning("%d ore senza orario: aggiungi [orario.fasce] nel config", senza_orario)
    return items


def chiave_bacheca(b) -> str:
    return h("bacheca", b.dat_evento, b.data, b.autore, b.messaggio[:200])


def chiave_allegato(b, a) -> str:
    return h("allegato", chiave_bacheca(b), a.nome_file)


def note_disciplinari(d, raw: dict | None) -> list[dict]:
    """Note normalizzate: dal grezzo se disponibile (campi variabili tra scuole),
    altrimenti dal modello di didupwrapper."""
    if raw is None:
        return [{"data": (n.dat_giorno or n.data)[:10], "ora": "", "docente": n.docente,
                 "testo": n.descrizione} for n in d.note_disciplinari]
    out = []
    for n in raw.get("noteDisciplinari") or []:
        if n.get("flgAnnullata") is True or n.get("isVisibile") is False:
            continue
        out.append({
            "data": str(n.get("datNota") or n.get("datGiorno") or n.get("data") or n.get("datEvento") or "")[:10],
            "ora": n.get("oraNota") or "",
            "docente": (n.get("docente") or "").strip(),
            "testo": (n.get("desDescrizione") or n.get("descrizione") or "").strip(),
        })
    return out


TIPI_APPELLO = {"A": "Assenza", "I": "Ingresso posticipato", "U": "Uscita anticipata"}


def build_snapshot(d, orario: dict[date, list[dict]], nome: str, cfg: dict,
                   oggi: date | None = None, raw: dict | None = None,
                   link_allegati: dict[str, str] | None = None) -> Snapshot:
    """``raw``: dashboard grezza (MultiProfiloClient.dashboard_raw), per i campi che il
    modello di didupwrapper non conosce. ``link_allegati``: chiave_allegato -> link (Drive o Nextcloud)."""
    link_allegati = link_allegati or {}
    snap = Snapshot()
    oggi = oggi or date.today()
    compiti = estrai_compiti(d)

    # Compiti -> dentro la lezione del giorno di consegna; senza lezione, evento giornaliero
    # (solo da oggi - giorni_passati in poi) + notifiche
    limite = oggi - timedelta(days=cfg["compiti"]["giorni_passati"])
    usati: set[int] = set()
    snap.cal += costruisci_lezioni(orario, [c for _, c in compiti], cfg, mappa_materie(d), usati)
    abbr = abbreviazioni(d)
    for key, c in compiti:
        if c.consegna >= limite and id(c) not in usati:
            breve = nome_materia(abbr.get(norm(c.materia), c.materia))  # come nei titoli delle lezioni
            snap.cal.append(CalItem(
                key=key, kind="compito", summary=f"📚 {breve}: {short(c.testo, 60)}",
                description=f"Materia: {nome_materia(c.materia)}\n\nCompiti da consegnare:\n"
                            + testo_compito(c),
                day=c.consegna))
        snap.notifiche.append(Notifica(key, "compiti", f"📚 Compito – {nome}",
                                       f"{c.materia} per il {c.consegna:%d/%m}: {short(c.testo, 200)}"))

    # Promemoria
    contatore: dict[tuple, int] = {}
    for p in d.promemoria:
        day = parse_date(p.dat_giorno)
        if not p.flg_visibile_famiglia or not day:
            continue
        base = (p.dat_giorno, p.pk_docente or p.docente, p.ora_inizio)
        idx = contatore[base] = contatore.get(base, -1) + 1
        key = h("promemoria", *base, idx)
        st, et = parse_hhmm(p.ora_inizio), parse_hhmm(p.ora_fine)
        if st == "00:00" and et in (None, "00:00"):  # nessun orario: evento giornaliero
            st = et = None
        snap.cal.append(CalItem(
            key=key, kind="promemoria", summary=f"📌 {short(p.des_annotazioni, 70)}",
            description=f"{p.des_annotazioni}\n\nDocente: {p.docente}",
            day=day, start_time=st, end_time=et if st else None, color="6"))
        snap.notifiche.append(Notifica(key, "promemoria", f"📌 Promemoria – {nome}",
                                       f"{day:%d/%m} – {short(p.des_annotazioni, 250)} ({p.docente})"))

    # Bacheca
    for b in d.bacheca:
        key = chiave_bacheca(b)
        links = [link_allegati.get(chiave_allegato(b, a)) for a in b.lista_allegati]
        extra = []
        if b.pv_richiesta and not b.is_presa_visione:
            extra.append("presa visione richiesta")
        if b.ad_richiesta and not b.is_presa_adesione_confermata:
            extra.append("adesione richiesta")
        suffix = f" [{', '.join(extra)}]" if extra else ""
        primo = next((x for x in links if x), None)
        n_all = len(b.lista_allegati)
        txt_all = f" 📎 {n_all} allegat{'o' if n_all == 1 else 'i'}" if n_all else ""
        snap.notifiche.append(Notifica(key, "bacheca", f"📢 Bacheca – {nome}",
                                       f"{b.autore}: {short(b.messaggio, 300)}{suffix}{txt_all}",
                                       url=primo))
        # Solo la scadenza di adesione: dataScadenza è la fine pubblicazione della circolare
        # (spesso fine anno scolastico), non una scadenza per la famiglia.
        scad = parse_date(b.data_scad_adesione)
        if scad:
            allegati = "\n".join(f"- {a.nome_file}" + (f": {link}" if link else "")
                                 for a, link in zip(b.lista_allegati, links))
            snap.cal.append(CalItem(
                key=key, kind="scadenza", summary=f"📢 Scadenza: {short(b.messaggio, 60)}",
                description=f"{b.messaggio}\n\nDa: {b.autore}{suffix}"
                            + (f"\n\nAllegati:\n{allegati}" if allegati else ""),
                day=scad, color="11"))

    # Solo notifiche
    for v in d.voti:
        key = h("voto", v.prg_voto) if v.prg_voto is not None else \
            h("voto", v.dat_giorno, v.pk_materia, v.cod_codice, v.descrizione_prova)
        tipo = "scritto" if v.is_scritto else "orale" if v.is_orale else (v.tipo_valutazione or "")
        dettagli = " – ".join(x for x in (v.descrizione_prova, v.des_commento) if x)
        snap.notifiche.append(Notifica(key, "voti", f"🎓 Voto – {nome}",
                                       f"{v.des_materia}: {v.cod_codice or v.valore} {tipo}"
                                       f" ({v.dat_giorno[:10]})" + (f"\n{dettagli}" if dettagli else "")))
    for n in note_disciplinari(d, raw):
        key = h("nota", n["data"], n["ora"], n["docente"], n["testo"])
        quando = n["data"] + (f" {n['ora']}" if n["ora"] else "")
        snap.notifiche.append(Notifica(key, "note", f"⚠️ Nota disciplinare – {nome}",
                                       f"{quando} {n['docente']}: {n['testo'] or '(senza testo)'}"))
    for a in d.appello:
        key = h("appello", a.cod_evento, a.data or a.dat_evento, a.descrizione)
        tipo = TIPI_APPELLO.get(a.cod_evento.upper(), a.cod_evento)
        dettagli = " – ".join(x for x in (a.descrizione, a.nota) if x)
        da_giust = a.da_giustificare and not a.is_giustificata
        snap.notifiche.append(Notifica(key, "assenze", f"🚪 {tipo} – {nome}",
                                       f"{(a.data or a.dat_evento)[:10]}"
                                       + (f": {dettagli}" if dettagli else "")
                                       + (" (da giustificare)" if da_giust else "")))
    return snap


# --------------------------------------------------------------------------- #
# Google: credenziali                                                         #
# --------------------------------------------------------------------------- #
def scope_richiesti(cfg: dict) -> list[str]:
    drive = cfg["allegati"]["drive"] or any(al["cfg"]["allegati"]["drive"] for al in cfg.get("alunni", []))
    return SCOPES + ([SCOPE_DRIVE] if drive else [])


def scope_token(cfg: dict) -> list[str]:
    token = Path(cfg["google"]["token_file"])
    try:
        return json.loads(token.read_text()).get("scopes") or []
    except (OSError, ValueError):
        return []


def google_creds(cfg: dict, interactive: bool = False):
    """Le credenziali usano gli scope concessi nel token (senza restringerli), così attivare
    o disattivare una funzione non fa perdere un permesso già dato."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    g = cfg["google"]
    token = Path(g["token_file"])
    creds = Credentials.from_authorized_user_file(str(token)) if token.exists() else None
    if creds and creds.expired and creds.refresh_token and not interactive:
        creds.refresh(Request())
        token.write_text(creds.to_json())
    if creds and creds.valid and not interactive:
        return creds
    if not interactive:
        raise RuntimeError(f"Token Google assente o non valido ({token}): esegui --auth")
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(g["client_secret_file"], scope_richiesti(cfg))
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    token.write_text(creds.to_json())
    token.chmod(0o600)
    print(f"Token salvato in {token}")
    return creds


def guard(label: str, stale: list, have: int, desired: int) -> list:
    """Se Argo restituisce dati vuoti/parziali non svuotiamo il calendario."""
    if stale and (desired == 0 or len(stale) > max(10, have // 2)):
        log.warning("[%s] %d elementi da rimuovere su %d: troppi, salto la cancellazione",
                    label, len(stale), have)
        return []
    return stale


# --------------------------------------------------------------------------- #
# Google Calendar                                                             #
# --------------------------------------------------------------------------- #
class Calendar:
    def __init__(self, creds, tz: str, dry_run: bool):
        from googleapiclient.discovery import build
        self.svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self.tz, self.dry = tz, dry_run

    def existing(self, cal_id: str) -> dict[str, dict]:
        out, token = {}, None
        while True:
            r = self.svc.events().list(calendarId=cal_id, privateExtendedProperty="argo_sync=1",
                                       maxResults=2500, pageToken=token).execute()
            for ev in r.get("items", []):
                k = ev.get("extendedProperties", {}).get("private", {}).get("argo_key")
                if k:
                    out[k] = ev
            token = r.get("nextPageToken")
            if not token:
                return out

    def body(self, it: CalItem) -> dict:
        if it.start_time:
            end = it.end_time or add_min(it.start_time, 60)
            start = {"dateTime": f"{it.day}T{it.start_time}:00", "timeZone": self.tz}
            endd = {"dateTime": f"{it.day}T{end}:00", "timeZone": self.tz}
        else:
            start, endd = {"date": str(it.day)}, {"date": str(it.day + timedelta(days=1))}
        b = {
            "summary": it.summary, "description": it.description, "start": start, "end": endd,
            "transparency": "transparent",
            "extendedProperties": {"private": {"argo_sync": "1", "argo_key": it.key,
                                               "argo_kind": it.kind, "argo_hash": it.content_hash}},
            "reminders": {"useDefault": True} if it.reminders else {"useDefault": False, "overrides": []},
        }
        if it.color:
            b["colorId"] = it.color
        return b

    @staticmethod
    def event_day(ev: dict) -> date | None:
        s = ev.get("start", {})
        return parse_date(s.get("date") or s.get("dateTime"))

    def sync(self, cal_id: str, items: list[CalItem], label: str,
             gestito: Callable[[str, date | None], bool]) -> None:
        """``gestito(kind, giorno)`` dice se un evento esistente rientra nel perimetro
        di questo giro (es. lezioni solo nei giorni di orario scaricati)."""
        desired = {i.key: i for i in items}
        have = self.existing(cal_id)
        c = u = r = 0
        for k, it in desired.items():
            ev = have.get(k)
            if ev is None:
                c += 1
                log.debug("[%s] + %s %s %s", label, it.day, it.start_time or "", it.summary)
                if not self.dry:
                    self.svc.events().insert(calendarId=cal_id, body=self.body(it)).execute()
            elif ev["extendedProperties"]["private"].get("argo_hash") != it.content_hash:
                u += 1
                log.debug("[%s] ~ %s %s", label, it.day, it.summary)
                if not self.dry:
                    self.svc.events().update(calendarId=cal_id, eventId=ev["id"], body=self.body(it)).execute()
        stale = [ev for k, ev in have.items() if k not in desired and
                 gestito(ev["extendedProperties"]["private"].get("argo_kind", ""), self.event_day(ev))]
        for ev in guard(label, stale, len(have), len(desired)):
            r += 1
            log.debug("[%s] - %s", label, ev.get("summary"))
            if not self.dry:
                self.svc.events().delete(calendarId=cal_id, eventId=ev["id"]).execute()
        log.info("[%s] calendario: %d creati, %d aggiornati, %d rimossi", label, c, u, r)


# --------------------------------------------------------------------------- #
# Allegati della bacheca su Google Drive o Nextcloud                          #
# --------------------------------------------------------------------------- #
MESI = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio", "Agosto",
        "Settembre", "Ottobre", "Novembre", "Dicembre"]
TIPO_CARTELLA = "application/vnd.google-apps.folder"


def pulisci_nome(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", " ".join((s or "").split()))[:180].strip()


def nome_file_sicuro(s: str) -> str:
    return pulisci_nome(s) or "allegato"


def percorso_allegato(acfg: dict, b, a) -> tuple[list[str], str]:
    """Cartelle e nome del file secondo [allegati] percorso e nome_file (default:
    <cartella>/<alunno>/<anno>/<MM - Mese>/<data> <nome>). Senza data della circolare le parti
    che la usano vengono saltate e il file mantiene il nome originale."""
    al = acfg["allegati"]
    giorno = parse_date(b.data) or parse_date(b.dat_evento)
    v = {"cartella": al["cartella"], "alunno": al["sottocartella"], "nome": a.nome_file or "allegato"}
    if giorno:
        v |= {"anno": giorno.year, "mese": giorno.month, "nome_mese": MESI[giorno.month - 1],
              "giorno": giorno.day, "data": str(giorno)}
    cartelle = []
    for parte in al.get("percorso", PERCORSO_DEFAULT).split("/"):
        try:
            parte = pulisci_nome(parte.format(**v))
        except KeyError:  # segnaposto della data, circolare senza data
            continue
        if parte:
            cartelle.append(parte)
    try:
        nome = al.get("nome_file", NOME_FILE_DEFAULT).format(**v)
    except KeyError:
        nome = v["nome"]
    return cartelle, nome_file_sicuro(nome)


class Drive:
    nome = "Drive"

    def __init__(self, creds, dry_run: bool):
        from googleapiclient.discovery import build
        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        self.dry = dry_run
        self._cartelle: dict[tuple[str, ...], str | None] = {}

    @staticmethod
    def _q(s: str) -> str:
        return s.replace("\\", "\\\\").replace("'", "\\'")

    def cartella(self, percorso: list[str]) -> str | None:
        """ID della cartella (creata se manca; None in dry-run se non esiste ancora)."""
        parent = "root"
        for i in range(len(percorso)):
            chiave = tuple(percorso[:i + 1])
            if chiave not in self._cartelle:
                q = (f"mimeType='{TIPO_CARTELLA}' and name='{self._q(percorso[i])}' and trashed=false"
                     f" and '{parent}' in parents")
                trovate = self.svc.files().list(q=q, spaces="drive", fields="files(id)").execute().get("files", [])
                if trovate:
                    self._cartelle[chiave] = trovate[0]["id"]
                elif self.dry:
                    self._cartelle[chiave] = None
                else:
                    corpo = {"name": percorso[i], "mimeType": TIPO_CARTELLA, "parents": [parent]}
                    self._cartelle[chiave] = self.svc.files().create(body=corpo, fields="id").execute()["id"]
            parent = self._cartelle[chiave]
            if parent is None:
                return None
        return parent

    def cerca(self, chiave: str, percorso: list[str] | None = None, nome: str | None = None) -> dict | None:
        """File già caricato con questa chiave (appProperties), anche se state.json è stato perso."""
        q = f"appProperties has {{ key='argo_key' and value='{chiave}' }} and trashed=false"
        f = self.svc.files().list(q=q, spaces="drive", fields="files(id,webViewLink)").execute().get("files", [])
        return {"id": f[0]["id"], "link": f[0]["webViewLink"]} if f else None

    def carica(self, cartella: str, nome: str, dati: bytes, mime: str, chiave: str) -> dict:
        from googleapiclient.http import MediaInMemoryUpload
        f = self.svc.files().create(
            body={"name": nome, "parents": [cartella], "appProperties": {"argo_key": chiave}},
            media_body=MediaInMemoryUpload(dati, mimetype=mime, resumable=False),
            fields="id,webViewLink").execute()
        return {"id": f["id"], "link": f["webViewLink"]}


NS_OC = "http://owncloud.org/ns"
NS_ARGO = "https://argo-gcal-sync/ns"


class Nextcloud:
    """Archivio su Nextcloud via WebDAV (solo httpx). Ogni file porta la proprietà WebDAV
    argo_key: se state.json va perso il file già caricato viene ritrovato, e due allegati
    omonimi nella stessa cartella diventano "nome (2).pdf" invece di sovrascriversi.
    Link: "interno" /f/<fileid> (si apre dopo il login) o "pubblico" (condivisione in sola
    lettura, con scadenza facoltativa)."""
    nome = "Nextcloud"
    PROPFIND = (f'<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:oc="{NS_OC}" xmlns:a="{NS_ARGO}">'
                '<d:prop><oc:fileid/><a:argo_key/></d:prop></d:propfind>')

    def __init__(self, ncfg: dict, dry_run: bool, transport: httpx.BaseTransport | None = None):
        mancanti = [k for k in ("url", "utente", "password") if not ncfg.get(k)]
        if mancanti:
            dove = {"password": f"variabile {ncfg.get('password_env', 'NEXTCLOUD_APP_PASSWORD')}"}
            raise ValueError("[allegati.nextcloud] mancano: " + ", ".join(dove.get(k, k) for k in mancanti))
        self.base = ncfg["url"].rstrip("/")
        self.dav = f"{self.base}/remote.php/dav/files/{quote(ncfg['utente'], safe='')}"
        self.c = httpx.Client(auth=(ncfg["utente"], ncfg["password"]), timeout=60, transport=transport,
                              follow_redirects=False)
        self.dry = dry_run
        self.link = ncfg.get("link", "interno")
        self.scadenza = int(ncfg.get("scadenza_giorni", 0) or 0)
        self._cartelle: set[tuple[str, ...]] = set()

    def _url(self, parti) -> str:
        return self.dav + "/" + "/".join(quote(x, safe="") for x in parti)

    def _richiesta(self, metodo: str, parti, attesi: tuple[int, ...], **kw) -> httpx.Response:
        r = self.c.request(metodo, self._url(parti), **kw)
        if r.status_code not in attesi:
            raise RuntimeError(f"Nextcloud {metodo} {'/'.join(parti)}: HTTP {r.status_code}")
        return r

    def verifica(self) -> None:
        """Login e accesso ai file (PROPFIND sulla radice): fallisce subito se url/utente/password sono sbagliati."""
        self._richiesta("PROPFIND", [], (207,), headers={"Depth": "0"})

    def _props(self, parti) -> dict | None:
        r = self._richiesta("PROPFIND", parti, (207, 404), headers={"Depth": "0"}, content=self.PROPFIND)
        if r.status_code == 404:
            return None
        x = ET.fromstring(r.content)
        return {"fileid": (x.findtext(f".//{{{NS_OC}}}fileid") or "").strip() or None,
                "argo_key": (x.findtext(f".//{{{NS_ARGO}}}argo_key") or "").strip() or None}

    @staticmethod
    def _candidati(nome: str, n: int = 50):
        stem, punto, ext = nome.rpartition(".")
        if not punto or not stem:
            stem, ext = nome, ""
        yield nome
        for i in range(2, n + 1):
            yield f"{stem} ({i})" + (f".{ext}" if ext else "")

    def _voce(self, p: dict, parti) -> dict:
        if self.link == "pubblico":
            return {"id": p["fileid"], "link": self._condividi(parti), "tipo": "pubblico"}
        return {"id": p["fileid"], "link": f"{self.base}/f/{int(p['fileid'])}", "tipo": "interno"}

    def _ocs(self, metodo: str, **kw) -> Any:
        r = self.c.request(metodo, f"{self.base}/ocs/v2.php/apps/files_sharing/api/v1/shares",
                           headers={"OCS-APIRequest": "true", "Accept": "application/json"}, **kw)
        try:
            ocs = r.json()["ocs"]
        except (ValueError, KeyError):
            raise RuntimeError(f"Nextcloud condivisioni {metodo}: HTTP {r.status_code}") from None
        if r.status_code >= 400 or ocs["meta"].get("statuscode") not in (100, 200):
            raise RuntimeError(f"Nextcloud condivisioni {metodo}: {ocs['meta'].get('message') or r.status_code}")
        return ocs["data"]

    def _condividi(self, parti) -> str | None:
        """Link pubblico in sola lettura (riusa quello esistente). In dry-run non crea nulla."""
        path = "/" + "/".join(parti)
        for sh in self._ocs("GET", params={"path": path, "reshares": "false"}) or []:
            if int(sh.get("share_type", -1)) == 3 and sh.get("url"):
                return sh["url"]
        if self.dry:
            return None
        dati = {"path": path, "shareType": 3, "permissions": 1}
        if self.scadenza:
            dati["expireDate"] = str(date.today() + timedelta(days=self.scadenza))
        return self._ocs("POST", data=dati)["url"]

    def _trova(self, percorso: list[str], nome: str, chiave: str) -> tuple[dict | None, str]:
        """(file già caricato con questa chiave, primo nome libero)."""
        for n in self._candidati(nome):
            p = self._props([*percorso, n])
            if p is None:
                return None, n
            if p["argo_key"] == chiave and p["fileid"]:
                return self._voce(p, [*percorso, n]), n
        raise RuntimeError(f"troppi file omonimi di {nome!r} in {'/'.join(percorso)}")

    def cerca(self, chiave: str, percorso: list[str], nome: str) -> dict | None:
        return self._trova(percorso, nome, chiave)[0]

    def cartella(self, percorso: list[str]) -> list[str]:
        for i in range(len(percorso)):
            parti = tuple(percorso[:i + 1])
            if parti not in self._cartelle:
                self._richiesta("MKCOL", parti, (201, 405))  # 405: esiste già
                self._cartelle.add(parti)
        return list(percorso)

    def carica(self, cartella: list[str], nome: str, dati: bytes, mime: str, chiave: str) -> dict:
        esistente, libero = self._trova(cartella, nome, chiave)
        if esistente:
            return esistente
        parti = [*cartella, libero]
        self._richiesta("PUT", parti, (201, 204), content=dati, headers={"Content-Type": mime})
        patch = (f'<?xml version="1.0"?><d:propertyupdate xmlns:d="DAV:" xmlns:a="{NS_ARGO}"><d:set><d:prop>'
                 f'<a:argo_key>{escape(chiave)}</a:argo_key></d:prop></d:set></d:propertyupdate>')
        try:
            self._richiesta("PROPPATCH", parti, (207,), content=patch)
        except Exception as e:  # noqa: BLE001 - il file c'è: lo registriamo comunque in state.json
            log.warning("argo_key non impostata su %s: %s", "/".join(parti), e)
        p = self._props(parti)
        if not p or not p["fileid"]:
            raise RuntimeError(f"fileid non trovato dopo il caricamento di {'/'.join(parti)}")
        return self._voce(p, parti)


async def scarica(url: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "application/octet-stream").split(";")[0]


STATO_ALLEGATI = {"drive": "allegati", "nextcloud": "allegati_nextcloud"}  # chiave in state.json


async def archivia_allegati(cli: "MultiProfiloClient", d, nome: str, acfg: dict,
                            drive: "Drive | Nextcloud | None", state: "State") -> dict[str, str]:
    """Carica sull'archivio (Drive o Nextcloud) gli allegati della bacheca non ancora archiviati.
    Ritorna chiave_allegato -> link (anche quelli dei giri precedenti). Ogni archivio ha il suo
    elenco in state.json: cambiando archivio quello nuovo recupera tutto."""
    tipo = acfg["allegati"].get("archivio", "drive")
    arch = state.data.setdefault(STATO_ALLEGATI.get(tipo, "allegati"), {})
    if drive is None:
        return {k: v["link"] for k, v in arch.items()}
    tipo_link = getattr(drive, "link", None)  # Nextcloud: "interno" | "pubblico"

    def da_rifare(k: str) -> bool:  # nuovo, o con un link del tipo non più configurato
        return k not in arch or (tipo_link is not None and arch[k].get("tipo", "interno") != tipo_link)
    da_fare = [(b, a, chiave_allegato(b, a)) for b in d.bacheca for a in b.lista_allegati
               if a.pk and da_rifare(chiave_allegato(b, a))]
    massimo = acfg["allegati"]["max_per_giro"]
    caricati = ricollegati = errori = 0
    for b, a, k in da_fare[:massimo]:
        try:
            percorso, nome_drive = percorso_allegato(acfg, b, a)
            if drive.dry and k in arch:
                log.debug("[%s] ~ link %s di %s/%s", nome, tipo_link, "/".join(percorso), nome_drive)
                continue
            if (esistente := drive.cerca(k, percorso, nome_drive)):
                ricollegati += k in arch
                arch[k] = esistente
                continue
            if drive.dry:
                log.debug("[%s] + allegato %s/%s", nome, "/".join(percorso), nome_drive)
                continue
            cartella = drive.cartella(percorso)
            dati, mime = await scarica(await cli.url_allegato(a.pk, d.pk))
            arch[k] = drive.carica(cartella, nome_drive, dati, mime, k)
            caricati += 1
        except Exception as e:  # noqa: BLE001 - un allegato non deve fermare la sync
            errori += 1
            log.warning("[%s] allegato '%s' non archiviato: %s", nome, a.nome_file, e)
    if da_fare:
        log.info("[%s] allegati: %d da archiviare, %d caricati su %s, %d link aggiornati, %d errori, "
                 "%d al prossimo giro", nome, len(da_fare), caricati, getattr(drive, "nome", "archivio"),
                 ricollegati, errori, max(0, len(da_fare) - massimo))
    return {k: v["link"] for k, v in arch.items()}


# --------------------------------------------------------------------------- #
# Notifiche                                                                   #
# --------------------------------------------------------------------------- #
class Notifier:
    def __init__(self, cfg: dict, dry_run: bool):
        self.ha, self.tg, self.dry = cfg.get("homeassistant"), cfg.get("telegram"), dry_run

    @staticmethod
    def payload_ha(title: str, message: str, url: str | None) -> dict:
        p: dict = {"title": title, "message": message}
        if url:  # app Home Assistant: toccando la notifica si apre l'URL (iOS: url, Android: clickAction)
            p["data"] = {"url": url, "clickAction": url,
                         "actions": [{"action": "URI", "title": "Apri allegato", "uri": url}]}
        return p

    def send(self, title: str, message: str, url: str | None = None) -> None:
        if self.dry:
            log.info("NOTIFICA %s | %s%s", title, message.replace("\n", " / "), f" | {url}" if url else "")
            return
        with httpx.Client(timeout=15) as c:
            if self.ha:
                try:
                    c.post(f"{self.ha['url'].rstrip('/')}/api/services/notify/{self.ha['service']}",
                           headers={"Authorization": f"Bearer {self.ha['token']}"},
                           json=self.payload_ha(title, message, url)).raise_for_status()
                except httpx.HTTPError as e:
                    log.error("Notifica HA fallita: %s", e)
            if self.tg:
                try:
                    c.post(f"https://api.telegram.org/bot{self.tg['bot_token']}/sendMessage",
                           json={"chat_id": self.tg["chat_id"],
                                 "text": f"{title}\n{message}" + (f"\n{url}" if url else "")}).raise_for_status()
                except httpx.HTTPError as e:
                    log.error("Notifica Telegram fallita: %s", e)


class State:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {"seen": {}, "error": False}

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        tmp.replace(self.path)


MAX_PER_TIPO = 8


def notify_new(snap: Snapshot, who: str, nome: str, state: State, notifier, tipi: list[str]) -> None:
    prev = state.data["seen"].get(who)
    current: dict[str, list[str]] = {}
    for n in snap.notifiche:
        current.setdefault(n.kind, []).append(n.key)
    if prev is None:
        log.info("[%s] primo avvio: memorizzo %d elementi senza notificare", nome, len(snap.notifiche))
    else:
        by_kind: dict[str, list[Notifica]] = {}
        for n in snap.notifiche:
            if n.kind in tipi and n.key not in set(prev.get(n.kind, [])):
                by_kind.setdefault(n.kind, []).append(n)
        for kind, nuove in by_kind.items():
            for n in nuove[:MAX_PER_TIPO]:
                notifier.send(n.title, n.message, url=n.url)
            if len(nuove) > MAX_PER_TIPO:
                notifier.send(f"Argo – {nome}", f"…e altri {len(nuove) - MAX_PER_TIPO} elementi ({kind})")
    state.data["seen"][who] = {k: sorted(set(current.get(k, [])) | set((prev or {}).get(k, [])))
                               for k in set(current) | set(prev or {})}


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #
def giorni_orario(cfg: dict, oggi: date) -> list[date]:
    return [oggi + timedelta(days=i) for i in range(cfg["orario"]["giorni"])
            if (oggi + timedelta(days=i)).weekday() < 6]  # niente domeniche


def client_argo(acc: dict) -> "MultiProfiloClient":
    if not acc["password"]:
        raise RuntimeError(f"Password Argo mancante per {acc['codice_scuola']}/{acc['username']} "
                           f"(variabile {acc['password_env']})")
    return MultiProfiloClient(acc["codice_scuola"], acc["username"], acc["password"],
                              auto_versione=True)


async def sync_alunno(cli: "MultiProfiloClient", al: dict, cal: "Calendar",
                      state: "State", notifier, oggi: date, drive: "Drive | Nextcloud | None" = None) -> None:
    nome, acfg = al["nome"], al["cfg"]
    cli.seleziona_profilo(al["profilo"])
    d = await cli.get_dashboard(forza_refresh=True)
    if d.profilo_disabilitato:
        log.warning("[%s] profilo disabilitato, salto", nome)
        return
    orario, scaricati = await cli.orario(giorni_orario(acfg, oggi))
    log.info("[%s] orario: %d giorni scaricati, %d con lezioni", nome, len(scaricati), len(orario))
    link_allegati = await archivia_allegati(cli, d, nome, acfg, drive, state)
    snap = build_snapshot(d, orario, nome, acfg, oggi, raw=cli.dashboard_raw, link_allegati=link_allegati)

    limite_compiti = oggi - timedelta(days=acfg["compiti"]["giorni_passati"])

    def gestito(kind: str, giorno: date | None) -> bool:
        if kind == "lezione":  # lezioni passate restano, si toccano solo i giorni scaricati
            return giorno in scaricati
        if kind == "compito":  # compiti passati restano come storico
            return giorno is not None and giorno >= limite_compiti
        return True

    cal.sync(al["calendar_id"], snap.cal, nome, gestito)
    migra_state_key(state, al)
    notify_new(snap, state_key(al), nome, state, notifier, acfg["notifiche"]["tipi"])


async def run_once(cfg: dict, args, state: State, notifier: Notifier) -> None:
    if args.list_profiles:
        for acc, _ in gruppi_account(cfg):
            print(f"=== {acc['codice_scuola']} / {acc['username']}")
            try:
                async with client_argo(acc) as cli:
                    print(f"argo-client-version {cli.versione}")
                    for i, p in enumerate(cli.profili):
                        visibile = {k: v for k, v in p.items() if k not in ("token", "opzioni")}
                        print(f"[{i}] {json.dumps(visibile, ensure_ascii=False)[:400]}")
            except Exception as e:  # noqa: BLE001
                print(f"ERRORE: {type(e).__name__}: {e}")
        return
    gruppi = gruppi_account(cfg)
    if args.debug_orario:
        for acc, als in gruppi:
            async with client_argo(acc) as cli:
                for al in als:
                    cli.seleziona_profilo(al["profilo"])
                    raw = await cli.orario_raw(date.fromisoformat(args.debug_orario))
                    print(f"--- {al['nome']}\n{json.dumps(raw, ensure_ascii=False, indent=1)}")
        return

    creds = google_creds(cfg)
    cal = Calendar(creds, cfg["calendario"]["timezone"], args.dry_run)
    drive = None
    if any(al["cfg"]["allegati"]["archivio"] == "drive" for al in cfg["alunni"]):
        if SCOPE_DRIVE in (creds.scopes or []):
            drive = Drive(creds, args.dry_run)
        else:
            log.error("Allegati su Drive attivi ma il token non ha lo scope drive.file: rifai il login "
                      "(pocs/04_google_auth.py --login) e ricopia token.json. Allegati saltati.")
    nextcloud: dict[tuple, Nextcloud | None] = {}

    def archivio(al: dict) -> "Drive | Nextcloud | None":
        a = al["cfg"]["allegati"]
        if a["archivio"] == "drive":
            return drive
        if a["archivio"] != "nextcloud":
            return None
        nc = a["nextcloud"]
        k = (nc.get("url"), nc.get("utente"))
        if k not in nextcloud:
            try:
                nextcloud[k] = Nextcloud(nc, args.dry_run)
                nextcloud[k].verifica()
            except Exception as e:  # noqa: BLE001
                log.error("[%s] Nextcloud non utilizzabile (%s): controlla url, utente e app password. "
                          "Allegati saltati.", al["nome"], e)
                nextcloud[k] = None
        return nextcloud[k]
    oggi = date.today()
    errori = []
    for acc, als in gruppi:  # un account che fallisce non blocca gli altri
        try:
            async with client_argo(acc) as cli:
                log.info("[%s] argo-client-version %s, %d profili",
                         acc["codice_scuola"], cli.versione, len(cli.profili))
                for al in als:
                    await sync_alunno(cli, al, cal, state, notifier, oggi, archivio(al))
        except Exception as e:  # noqa: BLE001
            log.exception("[%s] sync fallita", acc["codice_scuola"])
            errori.append(f"{acc['codice_scuola']}: {type(e).__name__}: {e}")
    if errori:
        raise RuntimeError("; ".join(errori))


def versione() -> str:
    """APP_VERSION dell'immagine (AAAA.MM.GG-sha, impostata dalla CI); in locale dev-<commit git>."""
    if v := os.environ.get("APP_VERSION"):
        return v
    try:
        import subprocess
        sha = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=Path(__file__).resolve().parent,
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha = ""
    return f"dev-{sha}" if sha else "dev"


def riepilogo_avvio(cfg: dict) -> str:
    """Una riga per alunno: cosa è attivo (utile a capire se il config sul server è quello giusto)."""
    righe = []
    for al in cfg["alunni"]:
        a = al["cfg"]["allegati"]
        archivio = a.get("archivio") or ("drive" if a.get("drive") else "")
        if archivio == "nextcloud":
            nc = a["nextcloud"]
            scad = f", {nc['scadenza_giorni']} gg" if nc["link"] == "pubblico" and nc["scadenza_giorni"] else ""
            archivio += f" ({nc['link']}{scad})"
        righe.append(f"{al['nome']} ({al['codice_scuola']}/{al['profilo']}): notifiche "
                     f"{','.join(al['cfg']['notifiche']['tipi']) or 'nessuna'}, allegati {archivio or 'no'}")
    return "; ".join(righe)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="config.toml", type=Path)
    ap.add_argument("--state", default=os.environ.get("ARGO_STATE", "state.json"), type=Path)
    ap.add_argument("--auth", action="store_true", help="autorizza l'accesso a Google (una tantum)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list-profiles", action="store_true")
    ap.add_argument("--debug-orario", metavar="AAAA-MM-GG", help="stampa la risposta grezza di orario-giorno")
    ap.add_argument("--loop", type=int, metavar="SECONDI", help="ripete ogni N secondi")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose or args.dry_run else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("httpx", "httpcore", "hpack", "googleapiclient", "google", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    from importlib.metadata import version as versione_pacchetto
    log.info("didup-calendar-sync %s (Python %s, didupwrapper %s)", versione(), sys.version.split()[0],
             versione_pacchetto("didupwrapper"))
    try:
        cfg = load_config(args.config)
    except ValueError as e:
        sys.exit(f"Config {args.config}: {e}")
    log.info("config %s: %s", args.config, riepilogo_avvio(cfg))
    if args.auth:
        google_creds(cfg, interactive=True)
        return
    state = State(args.state)
    notifier = Notifier(cfg["notifiche"], args.dry_run)
    una_tantum = args.dry_run or args.list_profiles or args.debug_orario

    while True:
        try:
            asyncio.run(run_once(cfg, args, state, notifier))
            if state.data.get("error") and not una_tantum:
                notifier.send("Argo sync", "✅ Sincronizzazione tornata a funzionare")
            state.data["error"] = False
        except Exception as e:  # noqa: BLE001
            log.exception("Sync fallita")
            if not state.data.get("error") and not una_tantum:
                notifier.send("Argo sync", f"❌ Sync fallita: {type(e).__name__}: {short(str(e), 300)}")
            state.data["error"] = True
        if not una_tantum:
            state.save()
        if not args.loop or una_tantum:
            break
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
