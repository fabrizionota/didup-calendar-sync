# PoC

Script esplorativi, uno per integrazione, eseguibili con `uv run` (dipendenze inline PEP 723,
stesse versioni di `requirements.txt`). Riusano `config.toml` e `.env` dello script principale.

## Prerequisiti
- [`uv`](https://docs.astral.sh/uv/): `brew install uv` oppure
  `curl -LsSf https://astral.sh/uv/install.sh | sh` (poi nuovo terminale o `source ~/.local/bin/env`).
- **Nessun venv da creare**: `uv run` legge le dipendenze dall'header `# /// script` di ogni PoC,
  crea un ambiente isolato nella sua cache (`~/.cache/uv`, fuori dal repo) e lo riusa ai lanci
  successivi; se serve scarica anche Python ≥ 3.11. Il primo lancio è più lento.
- Config: `data/config.toml` (o `-c PATH`), partendo da `config.example.toml`. Per 01–03 bastano
  gli `[[alunni]]` con `nome`, `codice_scuola`, `username`, `password_env`.
- Segreti in `.env` nella radice del repo (gitignored), partendo da `.env.example`: una variabile per
  ogni `password_env` (es. `ARGO_PASSWORD_PRIMO=...`), più `HA_TOKEN`/`TELEGRAM_BOT_TOKEN` e, per il
  09, `NEXTCLOUD_APP_PASSWORD` (ed eventualmente `NEXTCLOUD_URL`/`NEXTCLOUD_USER`).
- Per il 09: almeno un alunno con `[allegati] archivio = "nextcloud"`; il PoC usa la classe
  `Nextcloud` e la config effettiva dello script principale.

## Uso
Dalla radice del repo (o da `pocs/` togliendo il prefisso `pocs/`):

```bash
uv run pocs/01_argo_login.py          # login su ogni account, profili (senza token), mappatura con [[alunni]]
uv run pocs/02_argo_dashboard.py      # conteggi + un elemento grezzo per tipo; build_snapshot a confronto
uv run pocs/03_argo_orario.py --giorno 2026-10-06 --giorni 6 [--alunno NOME] [--grezzo]
uv run pocs/08_argo_allegati.py --alunno NOME [--scarica]   # come ottenere il link di un allegato di bacheca
uv run pocs/04_google_auth.py         # token, scope, refresh (in memoria), accesso ai calendari
uv run pocs/04_google_auth.py --login # autorizzazione Google (Calendar + Drive) → pocs/out/token-poc.json
uv run pocs/05_gcal.py                # eventi gestiti per calendario
uv run pocs/05_gcal.py --scrivi --calendario <ID test>   # crea, rilegge e cancella 2 eventi di prova
uv run pocs/07_notify.py              # verifica HA/Telegram senza inviare (elenca i servizi notify)
uv run pocs/07_notify.py --scrivi     # invia una notifica di prova
uv run pocs/09_nextcloud.py           # allegati su Nextcloud: login WebDAV e cartelle, sola lettura
uv run pocs/09_nextcloud.py --scrivi  # carica un file di prova in <cartella>-test/, lo ritrova e stampa il link
```

## Opzioni comuni
- `-c PATH`: config. Default: `./config.toml`, `../config.toml`, `../data/config.toml`.
  I path Google del config (es. `/data/token.json` del container) se non esistono vengono cercati
  accanto al config.
- `.env` (radice repo, `pocs/`, cwd): password Argo (`password_env` di ogni alunno), `HA_TOKEN`,
  `TELEGRAM_BOT_TOKEN`, `NEXTCLOUD_*`.
  Le variabili già esportate hanno la precedenza.
- PoC Argo: un login per ogni account (scuola + username) degli `[[alunni]]`; il PoC 01 li prova
  tutti. Filtri per 02/03: `--alunno NOME`, `--scuola CODICE`, `--profilo N` (un profilo fuori config
  usa l'account dell'alunno/scuola scelti con `--alunno`/`--scuola`).
- `--anonimizza`: nomi → pseudonimi stabili (`Docente-3f2a`), testi liberi → `[testo, N car.]`,
  a schermo e nel dump. Token, password, `codMin` sono **sempre** mascherati.

## Sicurezza
- Di default tutto è in **sola lettura**.
- Scritture Google solo con `--scrivi`, e solo su un calendario di **test**:
  - `05_gcal.py --scrivi --calendario <ID test>`: crea un evento con orario e uno giornaliero, li
    rilegge e li cancella (anche in caso di errore).
  - Rifiuta i `calendar_id` dei figli presenti nel config.
- `07_notify.py --scrivi [--solo ha|telegram]` invia una notifica di prova.
- `08_argo_allegati.py` non chiama mai presa visione né adesione; `--scarica` salva il file in `pocs/out/`.
- `09_nextcloud.py --scrivi` carica un file di prova in `<cartella>-test/<alunno>/` (con link pubblico
  se `link = "pubblico"`) e lo lascia lì: va cancellato a mano.
- `04_google_auth.py` rinnova il token solo in memoria; `--login` salva in `pocs/out/token-poc.json`
  (usabile negli altri PoC con `--token`), mai sul token di produzione.

## Dump
Ogni PoC scrive `pocs/out/<NN>_<timestamp>.json` (permessi 600). **Senza `--anonimizza` contengono
dati reali dei figli**: `pocs/out/` è in `.gitignore` e `pocs/` in `.dockerignore`.

## Confronto con lo script principale
I PoC Argo scaricano da soli (`_argo.py`, sottoclasse minima di `DiDUPClient`), poi importano
`didup_calendar_sync.py` e gli passano **gli stessi dati grezzi**, senza nuove chiamate:
- 02: `DashboardResponse` → `build_snapshot` (eventi/notifiche per tipo, un esempio ciascuno);
- 03: `MultiProfiloClient.orario` (con uno stub che restituisce le risposte già scaricate) →
  `ora_lezione` per ogni ora → `costruisci_lezioni` (ore consecutive e compresenze unite, nomi
  completi delle materie e compiti presi dalla dashboard dello stesso profilo).

Se l'import fallisce il PoC continua e salta il confronto.
