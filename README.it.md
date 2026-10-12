# didup-calendar-sync

🇬🇧 [English](README.md) · 🇮🇹 Italiano

Sincronizza il registro elettronico **Argo didUP Famiglia** dei figli con **Google Calendar**
(un calendario per figlio) e manda le novità come notifiche **Home Assistant** e/o **Telegram**.
Funziona con più figli e più scuole: ogni alunno ha il suo account Argo.

| Da Argo | In Google Calendar / notifiche |
| --- | --- |
| Orario scolastico (prossimi N giorni) | Eventi lezione: ore consecutive della stessa materia unite, materie in compresenza nello stesso evento. Titolo con l'abbreviazione Argo (`Matem. con inform.`), nome completo in descrizione |
| Compiti | Nella descrizione della **lezione** di quella materia il giorno di consegna (titolo marcato ✏️), con data e docente di assegnazione. Se quel giorno la lezione non c'è: **evento giornaliero** `📚 Materia: testo` |
| Promemoria / verifiche | Eventi con orario; giornalieri se Argo non dà l'ora (`00:00`) |
| Bacheca con adesione (`dataScadAdesione`) | Evento giornaliero di scadenza. `dataScadenza` è la fine pubblicazione della circolare e viene ignorata |
| Allegati della bacheca (facoltativo) | PDF archiviati su **Google Drive** o **Nextcloud** in `Scuola/<alunno>/<anno>/<MM - Mese>/`; il link apre il file dalla notifica e dall'evento di scadenza |
| Voti, bacheca, note, promemoria (+ opz. assenze, compiti) | Notifiche Home Assistant e/o Telegram, solo per le novità |

> **Progetto non ufficiale**, non affiliato né approvato da Argo Software. Usa API non documentate
> dell'app Argo didUP Famiglia, che possono cambiare senza preavviso; ognuno lo usa con le proprie
> credenziali e sotto la propria responsabilità. Licenza [MIT](LICENSE).

## Come è fatto
```
README.md / README.it.md   questa documentazione (inglese / italiano)
CHANGELOG.md / .it.md      modifiche, per data
didup_calendar_sync.py     script unico (Argo → snapshot → Google Calendar + notifiche)
config.example.toml        modello di configurazione (la vera sta in data/config.toml)
.env.example               modello dei segreti (password Argo, token notifiche)
Dockerfile                 immagine; lo stage "test" esegue gli unit test in CI
tests/                     test offline, nessun account necessario
pocs/                      script esplorativi per verificare ogni integrazione (vedi pocs/README.md)
deploy/compose.yml         installazione con Docker Compose (o stack Portainer)
.github/workflows/ci.yml   CI: test, immagine multi-arch su GHCR
LICENSE, SECURITY.md       licenza MIT, segnalazioni di sicurezza
```
`data/`, `.env`, `pocs/out/` sono in `.gitignore`: contengono credenziali e dati dei figli.

## Configurazione

### Alunni e account
Non c'è un account principale: ogni `[[alunni]]` ha `codice_scuola`, `username`, `password_env`
(nome della variabile d'ambiente con la password), `profilo` (indice dentro quell'account, default 0)
e `calendar_id`. Alunni con lo stesso account (scuola + username) condividono un solo login; se un
account fallisce gli altri vengono sincronizzati comunque. Gli indici dei profili si vedono con
`uv run pocs/01_argo_login.py`.

Le sezioni globali `[orario]`, `[compiti]`, `[colori_materie]`, `[notifiche] tipi` valgono per tutti;
ogni alunno può sovrascriverle con `[alunni.orario]` / `[alunni.orario.fasce]`, `[alunni.compiti]`,
`[alunni.colori_materie]`, `notifiche = [...]`, `materie_ignorate = [...]` (es. `["SOSTEGNO"]`).

### Fasce orarie
Argo di solito **non dà gli orari delle ore** (campo `ora` vuoto), solo il numero d'ora: senza
`[orario.fasce]` (globale o per alunno) le lezioni non vengono create e nel log compare
`N ore senza orario`. Le fasce si ricavano dall'orario della scuola (circolare o sito):
```toml
[alunni.orario.fasce]
1 = "08:00-09:00"
2 = "09:00-10:00"
```

### Segreti
Password Argo (una variabile per ogni `password_env`), `HA_TOKEN` (token a lunga durata di Home
Assistant), `TELEGRAM_BOT_TOKEN`, e per gli allegati su Nextcloud `NEXTCLOUD_APP_PASSWORD` (più,
facoltative, `NEXTCLOUD_URL` e `NEXTCLOUD_USER`): in `.env` per l'uso locale (vedi `.env.example`),
nelle *Environment variables* dello stack in Portainer.

### Notifiche
Cosa notificare si sceglie con `[notifiche] tipi` (o `notifiche = [...]` nel singolo alunno). Valori:
`voti`, `bacheca`, `note`, `promemoria`, `assenze`, `compiti`. Default:
`["voti", "bacheca", "note", "promemoria"]`: i compiti sono già nel calendario, quindi non vengono
notificati se non li aggiungi.

`[notifiche.homeassistant]`: `url` (va bene l'IP interno, es. `http://192.168.1.x:8123`) e `service`,
il nome del servizio notify del telefono, es. `mobile_app_<telefono>` (il prefisso `notify.` è
accettato). Verifica con `uv run pocs/07_notify.py`, che elenca i servizi disponibili se il nome
non esiste.

Le notifiche di bacheca con un allegato archiviato portano il link: toccando la notifica si
apre il file su Drive o Nextcloud (non Home Assistant); tenendola premuta compare il pulsante "Apri allegato".

### Allegati (Google Drive o Nextcloud)
Gli allegati della bacheca vengono scaricati con la stessa sessione dell'app (chiamata
`downloadallegatobacheca`, che **non** segna la presa visione) e caricati in un archivio, scelto con
`[allegati] archivio` (o per singolo alunno in `[alunni.allegati]`):

| `archivio` | Dove | Link nella notifica e nell'evento |
| --- | --- | --- |
| `""` (default) | disattivato | — |
| `"drive"` (o il vecchio `drive = true`) | Google Drive dell'account dei calendari | pagina Drive del file (login Google) |
| `"nextcloud"` | Nextcloud via WebDAV | `<url>/f/<id>` (login Nextcloud) oppure condivisione pubblica |

Ogni allegato viene caricato una volta sola: registro in `state.json` (separato per Drive e
Nextcloud, così cambiando archivio quello nuovo recupera tutto) e una proprietà `argo_key` sul file,
che evita doppioni anche se `state.json` va perso. Al primo avvio vengono recuperati anche gli
allegati già pubblicati, al massimo `max_per_giro` per giro. Un errore su un allegato non ferma la
sync: viene riprovato al giro dopo.

**Cartelle e nomi** si decidono con `percorso` e `nome_file`; i default danno:
```
Scuola/Anna/2026/10 - Ottobre/2026-10-12 Circ. n. 012 - Uscita didattica….pdf
```
```toml
[allegati]
archivio = "drive"
cartella = "Scuola"
percorso = "{cartella}/{alunno}/{anno}/{mese:02d} - {nome_mese}"
nome_file = "{data} {nome}"
max_per_giro = 30
```
Segnaposto: `{cartella}` `{alunno}` (nome dell'alunno o `sottocartella`) `{anno}` `{mese}`
`{nome_mese}` `{giorno}` `{data}` (AAAA-MM-GG) `{nome}` (nome originale del file), con i formati di
Python come `{mese:02d}`. Se la circolare non ha data, le cartelle che la usano vengono saltate e il
file tiene il nome originale. Un segnaposto sconosciuto blocca l'avvio con un errore. Cambiarli non
sposta i file già caricati.

**Google Drive.** Serve il permesso `drive.file` (lo script vede solo i file che crea) e la Google
Drive API abilitata nel progetto: `uv run pocs/04_google_auth.py --login`, poi ricopia `token.json`
sul server. Se il permesso manca, il log lo segnala e gli allegati vengono saltati; il calendario
continua a funzionare.

**Nextcloud.** WebDAV con una app password (Impostazioni personali → Sicurezza → Crea nuova password
per l'app) in `NEXTCLOUD_APP_PASSWORD`, o nella variabile indicata da `password_env`. URL e utente
vengono da `[allegati.nextcloud]` o dalle variabili `NEXTCLOUD_URL` / `NEXTCLOUD_USER`, che vincono
(comodo nello stack Portainer); un `[alunni.allegati.nextcloud]` dell'alunno vince comunque.
```toml
[allegati]
archivio = "nextcloud"
[allegati.nextcloud]
url = "https://cloud.esempio.it"
utente = "nome.utente"
link = "interno"        # oppure "pubblico"
scadenza_giorni = 0     # solo "pubblico": 0 = non scade
```
- `link = "interno"` (default): `<url>/f/<id>`, si apre solo dopo il login su Nextcloud.
- `link = "pubblico"`: condivisione in sola lettura (riusa quella già presente sul file), apribile
  da chiunque abbia il link. Con `scadenza_giorni` smette di funzionare dopo N giorni, anche negli
  eventi già creati. Se il server richiede una password per i link pubblici, il log lo segnala e
  il link viene riprovato al giro dopo.
- Cambiare `link` non ricarica nulla: i link degli allegati ancora in bacheca vengono rifatti,
  `max_per_giro` per giro.
- Due allegati con lo stesso nome nella stessa cartella diventano `nome (2).pdf`; un file messo a
  mano con lo stesso nome non viene sovrascritto.
- Verifica con `uv run pocs/09_nextcloud.py` (sola lettura) e `--scrivi` (file di prova). Se
  Nextcloud non risponde o la password è sbagliata, il log lo segnala e gli allegati vengono saltati.

Il config viene letto **all'avvio**: dopo una modifica a `config.toml` sul server riavvia il
container (`docker compose restart`).

## Setup Google (una tantum)
1. Google Cloud Console, con l'account dei calendari → nuovo progetto → abilita **Google Calendar API**
   (e **Google Drive API** se archivi gli allegati su Drive).
2. *Google Auth Platform → Pubblico* (schermata consenso OAuth): tipo Esterno, poi **Pubblica app**
   (*In produzione*). In stato *Test* il login è bloccato per chi non è tester (403 `access_denied`)
   e il refresh token scade dopo 7 giorni. La verifica Google non serve: al consenso compare
   "app non verificata" → Avanzate → Vai a … .
3. *Credenziali* → ID client OAuth → **App desktop** → scarica il JSON in `data/client_secret.json`.
4. Da un PC con browser:
   ```bash
   uv run pocs/04_google_auth.py --login        # crea pocs/out/token-poc.json
   cp pocs/out/token-poc.json data/token.json && chmod 600 data/token.json
   uv run pocs/04_google_auth.py                # verifica scope, refresh e accesso ai calendari
   ```
5. In Google Calendar crea un calendario per figlio; l'ID (Impostazioni → Integra calendario,
   `…@group.calendar.google.com`) va in `calendar_id`. Lo scope `calendar.events` non permette di
   creare calendari, quindi va fatto a mano. Un 404 dal PoC 04 vuol dire ID sbagliato.

## Prova in locale
```bash
mkdir -p data && cp config.example.toml data/config.toml     # e modifica
cp .env.example .env && chmod 600 .env                       # e compila
uv run pocs/01_argo_login.py                                 # login e profili Argo
uv run pocs/03_argo_orario.py --giorni 6                     # orario e lezioni risultanti
docker build -t didup-calendar .
E="-v $PWD/data:/data --env-file .env"
docker run --rm $E didup-calendar --dry-run                       # cosa farebbe, senza scrivere né notificare
docker run --rm $E didup-calendar -v                              # un giro reale
```
Il primo giro reale memorizza tutto senza notificare; dal secondo arrivano solo le novità.
Un secondo giro subito dopo deve dare `0 creati, 0 aggiornati, 0 rimossi`.

Una volta in produzione **non** lanciare lo script anche dal PC: due istanze si contendono
`token.json` e `state.json` e le notifiche partono due volte.

## Installazione
L'immagine è pubblica e multi-architettura (amd64, arm64: va anche su Raspberry Pi):
`ghcr.io/fabrizionota/didup-calendar-sync`, con tag `latest` e uno per versione (es. `2026.10.13`).

### Docker Compose
```bash
mkdir didup-calendar-sync && cd didup-calendar-sync
curl -fsSLO https://raw.githubusercontent.com/fabrizionota/didup-calendar-sync/main/deploy/compose.yml
mkdir -p data      # config.toml, client_secret.json, token.json (vedi Configurazione e Setup Google)
curl -fsSL -o .env https://raw.githubusercontent.com/fabrizionota/didup-calendar-sync/main/.env.example
chmod 600 .env     # e compila
sudo chown -R 1000:1000 data && sudo chmod 700 data
docker compose up -d && docker compose logs -f
```
`deploy/compose.yml` fa un giro ogni 30 minuti (`SYNC_INTERVAL`), con healthcheck (il container è
*healthy* solo se l'ultimo giro è riuscito ed è recente), utente non root e filesystem in sola
lettura tranne `/data`.

- **Aggiornare**: `docker compose pull && docker compose up -d`. Per decidere tu quando aggiornare,
  fissa una versione al posto di `latest` (vedi [CHANGELOG](CHANGELOG.it.md)).
- **Config modificato**: viene letto all'avvio, quindi `docker compose restart`.
- **Portainer**: crea uno stack con lo stesso compose e metti i segreti nelle *Environment
  variables*; `env_file` può essere sostituito da `environment:`.

### Dove farlo girare
Richiede pochissimo: circa 150 MB di RAM, qualche secondo di CPU ogni 30 minuti, meno di 1 MB su
disco, nessuna porta in ingresso.

- **A casa** (Raspberry Pi, NAS, mini PC): la scelta più semplice, raggiunge Home Assistant in rete locale.
- **VM gratuita** (es. Google Compute Engine e2-micro "Always Free", regioni USA): stesso compose.
  Per notificare un Home Assistant di casa serve un URL pubblico di HA o una VPN (Tailscale, WireGuard).
- **Job pianificato** (Cloud Run Job + Cloud Scheduler, cron, Kubernetes CronJob): avvia il container
  con `--loop 0` (un giro e termina) e `/data` persistente.

Una sola istanza per configurazione: due istanze si contendono `token.json` e `state.json` e le
notifiche partono due volte.

## Rilasci
GitHub Actions esegue i test a ogni push e pull request. Un push su `main` pubblica l'immagine
`edge`; un tag `vAAAA.MM.GG` pubblica `AAAA.MM.GG` e `latest`. La versione compare nel log all'avvio.

## Test
```bash
uv run --no-project --python 3.12 --with-requirements requirements.txt \
  python -m unittest discover -s tests -v       # offline, nessun account
docker build --target test .                    # come in CI
```

## PoC
`pocs/` contiene uno script per integrazione (login, dashboard, orario e allegati Argo, auth
Google, Calendar, notifiche, Nextcloud), eseguibili con `uv run`, che riusano `data/config.toml` e `.env`. Sola
lettura di default, scritture solo con `--scrivi` su un calendario di test, `--anonimizza` per
condividere l'output. Mostrano anche come lo script principale interpreta gli stessi dati.
Dettagli in [pocs/README.md](pocs/README.md).

## Comportamento
- Gli eventi gestiti sono marcati (extended property `argo_sync=1`): quanto creato a mano non
  viene toccato.
- Lezioni: si aggiornano o rimuovono solo nei giorni di orario scaricati con successo; quelle
  passate restano.
- Compiti: un compito modificato dal docente aggiorna la lezione (o l'evento 📚); gli eventi 📚
  passati restano come storico.
- Protezione: se in un giro Argo non restituisce nulla, o sparirebbero più di metà degli eventi
  esistenti (e più di 10), la cancellazione viene saltata.
- Se la sync fallisce arriva **una** notifica di errore, e una quando torna a funzionare.
- `argo-client-version` viene letto dall'App Store a ogni giro, per evitare il 410 da client obsoleto.
- All'avvio il log mostra la versione e una riga per alunno con notifiche attive e archivio degli
  allegati, es. `didup-calendar-sync 2026.10.13-abc1234 …` e `config /data/config.toml: Anna
  (SC67890/0): notifiche voti,bacheca,note,promemoria, allegati drive`: utile per capire se il
  container gira con l'immagine e il config giusti.
- Allegati: lo script non chiama mai presa visione né adesione; scaricare un allegato non le segna.

## Limiti noti
- API Argo non ufficiali (reverse engineering): possono cambiare senza preavviso.
- L'orario Argo può essere incompleto rispetto a quello della scuola (es. ore di un docente non
  ancora inserito): quelle ore non compaiono e i relativi compiti diventano eventi 📚.
- Il link Drive di un allegato si apre solo con l'account Google proprietario dei file (quello dei
  calendari) o con chi ha accesso alla cartella: per altri telefoni condividi la cartella `Scuola`
  da Drive, o usa Nextcloud con `link = "pubblico"`.
- Le scuole usano campi diversi (es. note disciplinari con `desDescrizione`/`datNota`): se un tipo
  arriva vuoto, i PoC 02/03 mostrano la risposta grezza per capire quali campi usare.
