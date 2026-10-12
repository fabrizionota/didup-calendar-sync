"""Credenziali Google per i PoC: stesso token/scope dello script principale, ma il token
rinnovato resta in memoria (token.json di produzione mai riscritto)."""

from __future__ import annotations

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from _common import SCOPES, risolvi


def aggiungi_argomenti(ap) -> None:
    ap.add_argument("--token", type=Path,
                    help="token OAuth da usare (default: google.token_file del config)")


def percorso_token(cfg: dict, cfg_path: Path, token: Path | None) -> Path:
    if token:
        return token
    g = cfg.get("google") or {}
    if "token_file" not in g:
        raise SystemExit("[google] token_file mancante nel config (o usa --token)")
    return risolvi(g["token_file"], cfg_path)


def credenziali(path: Path, forza_refresh: bool = False) -> Credentials:
    if not path.is_file():
        raise SystemExit(f"Token Google non trovato: {path} (crealo con 04_google_auth.py --login)")
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if (forza_refresh or not creds.valid) and creds.refresh_token:
        creds.refresh(Request())   # solo in memoria
    if not creds.valid:
        raise SystemExit("Token Google non valido e non rinnovabile: rifai l'autorizzazione")
    return creds


def scope_concessi(path: Path) -> list[str]:
    return json.loads(path.read_text()).get("scopes") or []


def servizio(nome: str, versione: str, creds):
    return build(nome, versione, credentials=creds, cache_discovery=False)
