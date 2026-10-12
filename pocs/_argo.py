"""Client Argo dei PoC: sottoclasse minima di DiDUPClient, indipendente dallo script principale.

Tiene tutti i profili del login applicativo e restituisce le risposte grezze.
Usa API private di didupwrapper: va bene finché la versione è fissata (0.1.1).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from didupwrapper import DiDUPClient
from didupwrapper.client import (_DASHBOARD_PATH, _DATA_INIZIO_DEFAULT, _LOGIN_PATH,
                                 _estrai_dashboard, _random_string)
from didupwrapper.exceptions import DiDUPError

__all__ = ["PocClient", "DiDUPError", "estrai_dashboard", "client_da_account"]

estrai_dashboard = _estrai_dashboard


class PocClient(DiDUPClient):
    login_raw: Any = None
    profili: list[dict] = []

    async def _login_applicativo(self):
        dati = await self._post(_LOGIN_PATH, json={
            "lista-opzioni-notifiche": "{}",
            "lista-x-auth-token": "[]",
            "clientID": _random_string(163),
        })
        self.login_raw = dati
        self._verifica_success(dati)
        self.profili = (dati or {}).get("data") or []
        if not self.profili:
            raise DiDUPError("Login applicativo: nessun profilo restituito", payload=dati)
        self._login_data = self.profili[0]
        return self._login_data

    def seleziona(self, idx: int) -> None:
        if not 0 <= idx < len(self.profili):
            raise DiDUPError(f"Profilo {idx} inesistente (trovati {len(self.profili)})")
        self._login_data = self.profili[idx]
        self.invalida_cache()

    async def dashboard_raw(self) -> Any:
        dati = await self._post(_DASHBOARD_PATH, json={
            "dataultimoaggiornamento": _DATA_INIZIO_DEFAULT,
            "opzioni": self._opzioni_serializzate(),
        })
        self._verifica_success(dati)
        return dati

    async def orario_raw(self, giorno: date) -> Any:
        dati = await self._post("orario-giorno", json={"datGiorno": f"{giorno} 00:00:00.000"})
        self._verifica_success(dati)
        return dati


def client_da_account(acc: dict) -> PocClient:
    mancanti = [k for k in ("codice_scuola", "username") if not acc.get(k)]
    if not acc.get("password"):
        mancanti.append(f"password (variabile {acc['password_env']})")
    if mancanti:
        raise SystemExit(f"Account Argo {acc.get('codice_scuola')}/{acc.get('username')}: "
                         f"mancano {', '.join(mancanti)}")
    return PocClient(acc["codice_scuola"], acc["username"], acc["password"], auto_versione=True)
