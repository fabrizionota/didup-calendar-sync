# didup-calendar-sync

🇮🇹 [Italiano](#italiano) · 🇬🇧 [English](#english)

<a id="italiano"></a>

## 🇮🇹 Italiano

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

### Come è fatto
```
README.md                  questa documentazione (italiano e inglese)
CHANGELOG.md               modifiche, per data
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

### Configurazione

#### Alunni e account
Non c'è un account principale: ogni `[[alunni]]` ha `codice_scuola`, `username`, `password_env`
(nome della variabile d'ambiente con la password), `profilo` (indice dentro quell'account, default 0)
e `calendar_id`. Alunni con lo stesso account (scuola + username) condividono un solo login; se un
account fallisce gli altri vengono sincronizzati comunque. Gli indici dei profili si vedono con
`uv run pocs/01_argo_login.py`.

Le sezioni globali `[orario]`, `[compiti]`, `[colori_materie]`, `[notifiche] tipi` valgono per tutti;
ogni alunno può sovrascriverle con `[alunni.orario]` / `[alunni.orario.fasce]`, `[alunni.compiti]`,
`[alunni.colori_materie]`, `notifiche = [...]`, `materie_ignorate = [...]` (es. `["SOSTEGNO"]`).

#### Fasce orarie
Argo di solito **non dà gli orari delle ore** (campo `ora` vuoto), solo il numero d'ora: senza
`[orario.fasce]` (globale o per alunno) le lezioni non vengono create e nel log compare
`N ore senza orario`. Le fasce si ricavano dall'orario della scuola (circolare o sito):
```toml
[alunni.orario.fasce]
1 = "08:00-09:00"
2 = "09:00-10:00"
```

#### Segreti
Password Argo (una variabile per ogni `password_env`), `HA_TOKEN` (token a lunga durata di Home
Assistant), `TELEGRAM_BOT_TOKEN`, e per gli allegati su Nextcloud `NEXTCLOUD_APP_PASSWORD` (più,
facoltative, `NEXTCLOUD_URL` e `NEXTCLOUD_USER`): in `.env` per l'uso locale (vedi `.env.example`),
nelle *Environment variables* dello stack in Portainer. Per il monitoraggio: `KUMA_PUSH_URL` (segreto), `METRICS_PORT`, `METRICS_BIND`.

#### Notifiche
Cosa notificare si sceglie con `[notifiche] tipi` (o `notifiche = [...]` nel singolo alunno). Valori:
`voti`, `bacheca`, `note`, `promemoria`, `assenze`, `compiti`. Default:
`["voti", "bacheca", "note", "promemoria"]`: i compiti sono già nel calendario, quindi non vengono
notificati se non li aggiungi.

`[notifiche.homeassistant]`: `url` (va bene l'IP interno, es. `http://192.168.1.x:8123`) e `service`,
il nome del servizio notify del telefono, es. `mobile_app_<telefono>` (il prefisso `notify.` è
accettato), che riceve tutto. Altri telefoni si aggiungono come destinatari, ognuno con filtri
facoltativi per tipo e alunno:
```toml
[[notifiche.homeassistant.destinatari]]
service = "mobile_app_altro_telefono"
tipi = ["voti"]          # solo i voti (tra quelli di [notifiche] tipi)
alunni = ["Primo"]       # facoltativo: solo questo alunno
```
Gli avvisi di sync fallita o ripristinata vanno solo ai destinatari senza filtri. Ogni notifica
inviata compare nel log (`notifica voti → notify.…: 🎓 Voto – …`, solo il titolo). Verifica con
`uv run pocs/07_notify.py`, che controlla ogni servizio e, se un nome non esiste, elenca quelli
disponibili; con `--scrivi` manda una prova a tutti.

Le notifiche di bacheca con un allegato archiviato portano il link: toccando la notifica si
apre il file su Drive o Nextcloud (non Home Assistant); tenendola premuta compare il pulsante "Apri allegato".

#### Allegati (Google Drive o Nextcloud)
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

### Setup Google (una tantum)
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

### Prova in locale
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

### Installazione
L'immagine è pubblica e multi-architettura (amd64, arm64: va anche su Raspberry Pi):
`ghcr.io/fabrizionota/didup-calendar-sync`, con tag `latest` e uno per versione (es. `2026.10.13`).

#### Docker Compose
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
  fissa una versione al posto di `latest` (vedi [CHANGELOG](CHANGELOG.md#italiano)).
- **Config modificato**: viene letto all'avvio, quindi `docker compose restart`.
- **Portainer**: crea uno stack con lo stesso compose e metti i segreti nelle *Environment
  variables*; `env_file` può essere sostituito da `environment:`.

#### Dove farlo girare
Richiede pochissimo: circa 150 MB di RAM, qualche secondo di CPU ogni 30 minuti, meno di 1 MB su
disco, nessuna porta in ingresso.

- **A casa** (Raspberry Pi, NAS, mini PC): la scelta più semplice, raggiunge Home Assistant in rete locale.
- **VM gratuita** (es. Google Compute Engine e2-micro "Always Free", regioni USA): stesso compose.
  Per notificare un Home Assistant di casa serve un URL pubblico di HA o una VPN (Tailscale, WireGuard).
- **Job pianificato** (Cloud Run Job + Cloud Scheduler, cron, Kubernetes CronJob): avvia il container
  con `--loop 0` (un giro e termina) e `/data` persistente.

Una sola istanza per configurazione: due istanze si contendono `token.json` e `state.json` e le
notifiche partono due volte.

### Monitoraggio
Con `METRICS_PORT` (porta a scelta, 1-65535; nel compose è `9105` se non la imposti, `0` spegne tutto)
lo script espone due endpoint HTTP:

- `/metrics`: metriche per **Prometheus**;
- `/healthz`: `200` se l'ultimo giro è riuscito ed è recente (entro due intervalli), `503` se è
  fallito o troppo vecchio; nel corpo un JSON con lo stato. All'avvio, prima del primo giro, è `200`.

Nel compose la porta del container segue `METRICS_PORT`; sull'host è pubblicata su `METRICS_BIND`
(indirizzo:porta, di default `127.0.0.1:9105`, cioè solo in locale). Se Prometheus o Uptime Kuma
sono su un altro host usa `METRICS_BIND=0.0.0.0:9105`. Se sono container sullo stesso host, aggiungi
`deploy/compose.monitoraggio.yml` (in Portainer: *Additional paths*): collega il servizio alle reti Docker di Prometheus e Kuma, configurabili con `PROMETHEUS_NETWORK` e
`KUMA_NETWORK` (default `monitoring`; i nomi con `docker network ls`). La destinazione diventa
`didup-calendar-sync:<METRICS_PORT>`.
```bash
docker compose -f compose.yml -f compose.monitoraggio.yml up -d
``` Negli esempi sotto la porta è 9105.

| Metrica | Significato |
| --- | --- |
| `didup_up` | 1 se l'ultimo giro è riuscito |
| `didup_last_success_timestamp_seconds`, `didup_last_run_timestamp_seconds` | fine dell'ultimo giro riuscito e dell'ultimo giro |
| `didup_run_duration_seconds` | durata dell'ultimo giro |
| `didup_runs_total{result}` | giri `ok` / `error` |
| `didup_calendar_changes_total{alunno,op}` | eventi `created` / `updated` / `deleted` |
| `didup_notifications_total{alunno,tipo}` | notifiche inviate |
| `didup_notification_errors_total{servizio}` | invii falliti per destinatario |
| `didup_attachments_total{alunno,archivio,esito}` | allegati `caricato` / `errore` |
| `didup_items{alunno,tipo}` | voti, bacheca, note, promemoria, assenze, compiti, lezioni visti nell'ultimo giro |
| `didup_argo_client_version_info{scuola,versione}` | versione dell'app Argo usata |
| `didup_build_info{versione}` | versione di didup-calendar-sync |

Le etichette contengono solo il nome dell'alunno, mai voti o testi.

```yaml
# prometheus.yml
scrape_configs:
  - job_name: didup-calendar-sync
    static_configs:
      - targets: ["host-docker:9105"]
```
Regole di allerta d'esempio:
```yaml
groups:
  - name: didup-calendar-sync
    rules:
      - alert: DidupSyncFallita
        expr: didup_up == 0
        for: 1h
      - alert: DidupNessunGiroRiuscito
        expr: time() - didup_last_success_timestamp_seconds > 7200
      - alert: DidupLezioniSparite        # Argo potrebbe aver cambiato qualcosa (o sono vacanze)
        expr: max_over_time(didup_items{tipo="lezione"}[3d]) == 0
      - alert: DidupVersioneArgoCambiata  # più versioni viste nelle ultime 24 ore
        expr: count by (scuola) (last_over_time(didup_argo_client_version_info[1d])) > 1
```

**Uptime Kuma**, due modi (anche insieme):

- **Push** (consigliato): crea un monitor *Push* con intervallo poco più lungo di `SYNC_INTERVAL`
  (es. 35 minuti) e metti il suo URL in `KUMA_PUSH_URL` (va bene anche con `?status=up&msg=OK&ping=`
  copiato da Kuma). A fine giro lo script invia `up` con durata e versione, o `down` con l'errore;
  se non arriva nulla (container fermo o bloccato) Kuma avvisa da sé. L'URL contiene un token: tienilo
  nel `.env` o nelle variabili dello stack.
- **HTTP**: monitor *HTTP(s)* su `http://host-docker:9105/healthz`: rosso con `503` o se il container
  non risponde.

### Rilasci
GitHub Actions esegue i test a ogni push e pull request. Un push su `main` pubblica l'immagine
`edge`; un tag `vAAAA.MM.GG` pubblica `AAAA.MM.GG` e `latest`. La versione compare nel log all'avvio.

Per una copia ospitata su Gitea o Forgejo c'è `.gitea/workflows/ci.yml`: stessi test e immagine nel
registry dell'istanza (`edge`, `sha-<commit>` a ogni push, versione e `latest` sui tag), con il
secret `REGISTRY_TOKEN`.

### Test
```bash
uv run --no-project --python 3.12 --with-requirements requirements.txt \
  python -m unittest discover -s tests -v       # offline, nessun account
docker build --target test .                    # come in CI
```

### PoC
`pocs/` contiene uno script per integrazione (login, dashboard, orario e allegati Argo, auth
Google, Calendar, notifiche, Nextcloud), eseguibili con `uv run`, che riusano `data/config.toml` e `.env`. Sola
lettura di default, scritture solo con `--scrivi` su un calendario di test, `--anonimizza` per
condividere l'output. Mostrano anche come lo script principale interpreta gli stessi dati.
Dettagli in [pocs/README.md](pocs/README.md).

### Comportamento
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

### Limiti noti
- API Argo non ufficiali (reverse engineering): possono cambiare senza preavviso.
- L'orario Argo può essere incompleto rispetto a quello della scuola (es. ore di un docente non
  ancora inserito): quelle ore non compaiono e i relativi compiti diventano eventi 📚.
- Il link Drive di un allegato si apre solo con l'account Google proprietario dei file (quello dei
  calendari) o con chi ha accesso alla cartella: per altri telefoni condividi la cartella `Scuola`
  da Drive, o usa Nextcloud con `link = "pubblico"`.
- Le scuole usano campi diversi (es. note disciplinari con `desDescrizione`/`datNota`): se un tipo
  arriva vuoto, i PoC 02/03 mostrano la risposta grezza per capire quali campi usare.

---

<a id="english"></a>

## 🇬🇧 English

Syncs the **Argo didUP Famiglia** school register (the Italian electronic register used by many
schools) with **Google Calendar**, one calendar per child, and sends new items as **Home Assistant**
and/or **Telegram** notifications. Works with several children and several schools: each pupil has
its own Argo account.

| From Argo | In Google Calendar / notifications |
| --- | --- |
| Timetable (next N days) | Lesson events: consecutive hours of the same subject merged, co-taught subjects in the same event. Title with the Argo abbreviation (`Matem. con inform.`), full name in the description |
| Homework | In the description of that subject's **lesson** on the due date (title marked ✏️), with assignment date and teacher. If there is no such lesson that day: **all-day event** `📚 Subject: text` |
| Reminders / tests (promemoria) | Timed events; all-day when Argo gives no time (`00:00`) |
| Notice board items requiring sign-up (`dataScadAdesione`) | All-day deadline event. `dataScadenza` is just the end of the notice's publication and is ignored |
| Notice board attachments (optional) | PDFs archived on **Google Drive** or **Nextcloud** in `Scuola/<pupil>/<year>/<MM - Month>/`; the link opens the file from the notification and from the deadline event |
| Grades, notice board, disciplinary notes, reminders (+ optional absences, homework) | Home Assistant and/or Telegram notifications, only for new items |

> **Unofficial project**, not affiliated with or endorsed by Argo Software. It uses undocumented APIs
> of the Argo didUP Famiglia app, which may change without notice; everyone uses it with their own
> credentials and at their own risk. [MIT](LICENSE) licence.

### Layout
```
README.md                  this documentation (Italian and English)
CHANGELOG.md               changes, by date
didup_calendar_sync.py     single script (Argo → snapshot → Google Calendar + notifications)
config.example.toml        configuration template (the real one lives in data/config.toml)
.env.example               secrets template (Argo passwords, notification tokens)
Dockerfile                 image; the "test" stage runs the unit tests in CI
tests/                     offline tests, no account needed
pocs/                      exploratory scripts to check each integration (see pocs/README.md)
deploy/compose.yml         Docker Compose install (or Portainer stack)
.github/workflows/ci.yml   CI: tests, multi-arch image on GHCR
LICENSE, SECURITY.md       MIT licence, security reports
```
`data/`, `.env`, `pocs/out/` are git-ignored: they hold credentials and the children's data.

Configuration keys and log messages are in Italian (`alunni` = pupils, `orario` = timetable,
`compiti` = homework, `notifiche` = notifications, `fasce` = time slots).

### Configuration

#### Pupils and accounts
There is no main account: each `[[alunni]]` block has `codice_scuola` (school code), `username`,
`password_env` (name of the environment variable holding the password), `profilo` (index within that
account, default 0) and `calendar_id`. Pupils sharing an account (school + username) share a single
login; if one account fails, the others are still synced. Profile indexes are shown by
`uv run pocs/01_argo_login.py`.

The global sections `[orario]`, `[compiti]`, `[colori_materie]`, `[notifiche] tipi` apply to everyone;
each pupil can override them with `[alunni.orario]` / `[alunni.orario.fasce]`, `[alunni.compiti]`,
`[alunni.colori_materie]`, `notifiche = [...]`, `materie_ignorate = [...]` (subjects to skip,
e.g. `["SOSTEGNO"]`).

#### Time slots
Argo usually **does not provide lesson times** (empty `ora` field), only the hour number: without
`[orario.fasce]` (global or per pupil) no lessons are created and the log says `N ore senza orario`.
Take the slots from the school timetable (school circular or website):
```toml
[alunni.orario.fasce]
1 = "08:00-09:00"
2 = "09:00-10:00"
```

#### Secrets
Argo passwords (one variable per `password_env`), `HA_TOKEN` (Home Assistant long-lived token),
`TELEGRAM_BOT_TOKEN`, and for attachments on Nextcloud `NEXTCLOUD_APP_PASSWORD` (plus the optional
`NEXTCLOUD_URL` and `NEXTCLOUD_USER`): in `.env` for local use (see `.env.example`), in the stack's
*Environment variables* in Portainer.

#### Notifications
What gets notified is set by `[notifiche] tipi` (or `notifiche = [...]` on a single pupil). Values:
`voti` (grades), `bacheca` (notice board), `note` (disciplinary notes), `promemoria` (reminders),
`assenze` (absences/late entries), `compiti` (homework). Default:
`["voti", "bacheca", "note", "promemoria"]`: homework is already in the calendar, so it is not
notified unless you add it.

`[notifiche.homeassistant]`: `url` (the internal IP is fine, e.g. `http://192.168.1.x:8123`) and
`service`, the phone's notify service, e.g. `mobile_app_<phone>` (a `notify.` prefix is accepted),
which receives everything. More phones are added as recipients, each with optional filters by type
and pupil:
```toml
[[notifiche.homeassistant.destinatari]]
service = "mobile_app_other_phone"
tipi = ["voti"]          # grades only (among those in [notifiche] tipi)
alunni = ["Primo"]       # optional: this pupil only
```
Sync failed/recovered alerts go only to recipients without filters. Every notification sent is
logged (`notifica voti → notify.…: 🎓 Voto – …`, title only). Check with `uv run pocs/07_notify.py`,
which checks every service and lists the available ones if a name is wrong; `--scrivi` sends a test
to all of them.

Notice board notifications whose attachment is archived carry its link: tapping the notification
opens the file in Drive or Nextcloud (not Home Assistant); long-press shows an "Apri allegato" button.

#### Attachments (Google Drive or Nextcloud)
Notice board attachments are downloaded through the same app session (call
`downloadallegatobacheca`, which does **not** mark the notice as read) and uploaded to an archive,
chosen with `[allegati] archivio` (or per pupil in `[alunni.allegati]`):

| `archivio` | Where | Link in the notification and the event |
| --- | --- | --- |
| `""` (default) | disabled | — |
| `"drive"` (or the older `drive = true`) | Google Drive of the calendars' account | the file's Drive page (Google login) |
| `"nextcloud"` | Nextcloud over WebDAV | `<url>/f/<id>` (Nextcloud login) or a public share |

Each attachment is uploaded once: tracked in `state.json` (separately for Drive and Nextcloud, so
switching archive re-uploads everything to the new one) and by an `argo_key` property on the file,
which prevents duplicates even if `state.json` is lost. The first runs also fetch attachments already
published, at most `max_per_giro` per run. A failure on one attachment does not stop the sync: it is
retried at the next run.

**Folders and names** are set by `percorso` and `nome_file`; the defaults give:
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
Placeholders: `{cartella}` (root folder) `{alunno}` (pupil name or `sottocartella`) `{anno}` (year)
`{mese}` (month) `{nome_mese}` (Italian month name) `{giorno}` (day) `{data}` (YYYY-MM-DD) `{nome}`
(original file name), with Python format specs such as `{mese:02d}`. When a notice has no date,
folders using it are skipped and the file keeps its original name. An unknown placeholder stops the
startup with an error. Changing them does not move files already uploaded.

**Google Drive.** Needs the `drive.file` permission (the script only sees files it creates) and the
Google Drive API enabled in the project: `uv run pocs/04_google_auth.py --login`, then copy
`token.json` to the server again. If the permission is missing, the log says so and attachments are
skipped; the calendar keeps working.

**Nextcloud.** WebDAV with an app password (Personal settings → Security → Create new app password)
in `NEXTCLOUD_APP_PASSWORD`, or the variable named in `password_env`. URL and user come from
`[allegati.nextcloud]` or from `NEXTCLOUD_URL` / `NEXTCLOUD_USER`, which win (handy in the Portainer
stack); a pupil's own `[alunni.allegati.nextcloud]` still wins over both.
```toml
[allegati]
archivio = "nextcloud"
[allegati.nextcloud]
url = "https://cloud.example.org"
utente = "my.user"
link = "interno"        # or "pubblico"
scadenza_giorni = 0     # "pubblico" only: 0 = never expires
```
- `link = "interno"` (default): `<url>/f/<id>`, opens only after logging in to Nextcloud.
- `link = "pubblico"`: read-only public share (reusing the file's existing one), openable by anyone
  with the link. With `scadenza_giorni` it stops working after N days, also in the calendar events
  already created. If the server requires a password for public links, the log says so and the link
  is retried at the next run.
- Switching `link` doesn't re-upload anything: links of the attachments still on the notice board
  are rebuilt, `max_per_giro` per run.
- Two attachments with the same name in the same folder become `name (2).pdf`; a file you put there
  by hand with the same name is never overwritten.
- Check with `uv run pocs/09_nextcloud.py` (read-only) and `--scrivi` (test file). If Nextcloud is
  unreachable or the password is wrong, the log says so and attachments are skipped.

The config is read **at startup**: after editing `config.toml` on the server, restart the container
(`docker compose restart`).

### Google setup (one-off)
1. Google Cloud Console, with the calendars' account → new project → enable **Google Calendar API**
   (and **Google Drive API** if attachments are archived on Drive).
2. *Google Auth Platform → Audience* (OAuth consent screen): External, then **Publish app**
   (*In production*). In *Testing* the login is blocked for non-testers (403 `access_denied`) and the
   refresh token expires after 7 days. Google verification is not needed: the consent screen shows
   "app not verified" → Advanced → Go to … .
3. *Credentials* → OAuth client ID → **Desktop app** → download the JSON to `data/client_secret.json`.
4. From a computer with a browser:
   ```bash
   uv run pocs/04_google_auth.py --login        # creates pocs/out/token-poc.json
   cp pocs/out/token-poc.json data/token.json && chmod 600 data/token.json
   uv run pocs/04_google_auth.py                # checks scopes, refresh and calendar access
   ```
5. In Google Calendar create one calendar per child; its ID (Settings → Integrate calendar,
   `…@group.calendar.google.com`) goes into `calendar_id`. The `calendar.events` scope cannot create
   calendars, so this is manual. A 404 from PoC 04 means a wrong ID.

### Local trial
```bash
mkdir -p data && cp config.example.toml data/config.toml     # then edit
cp .env.example .env && chmod 600 .env                       # then fill in
uv run pocs/01_argo_login.py                                 # Argo login and profiles
uv run pocs/03_argo_orario.py --giorni 6                     # timetable and resulting lessons
docker build -t didup-calendar .
E="-v $PWD/data:/data --env-file .env"
docker run --rm $E didup-calendar --dry-run                       # what it would do, no writes or notifications
docker run --rm $E didup-calendar -v                              # one real run
```
The first real run stores everything without notifying; from the second one only new items are
notified. A second run right after must report `0 creati, 0 aggiornati, 0 rimossi`.

Once in production do **not** also run the script from your computer: two instances fight over
`token.json` and `state.json` and notifications are sent twice.

### Installation
The image is public and multi-arch (amd64, arm64: it runs on a Raspberry Pi too):
`ghcr.io/fabrizionota/didup-calendar-sync`, tagged `latest` and per version (e.g. `2026.10.13`).

#### Docker Compose
```bash
mkdir didup-calendar-sync && cd didup-calendar-sync
curl -fsSLO https://raw.githubusercontent.com/fabrizionota/didup-calendar-sync/main/deploy/compose.yml
mkdir -p data      # config.toml, client_secret.json, token.json (see Configuration and Google setup)
curl -fsSL -o .env https://raw.githubusercontent.com/fabrizionota/didup-calendar-sync/main/.env.example
chmod 600 .env     # then fill in
sudo chown -R 1000:1000 data && sudo chmod 700 data
docker compose up -d && docker compose logs -f
```
`deploy/compose.yml` runs every 30 minutes (`SYNC_INTERVAL`), with a healthcheck (the container is
*healthy* only if the last run succeeded and is recent), a non-root user and a read-only filesystem
except `/data`.

- **Update**: `docker compose pull && docker compose up -d`. To choose when to update, pin a version
  instead of `latest` (see the [CHANGELOG](CHANGELOG.md#english)).
- **Config changed**: it is read at startup, so `docker compose restart`.
- **Portainer**: create a stack with the same compose and put the secrets in *Environment variables*;
  `env_file` can be replaced by `environment:`.

#### Where to run it
It needs very little: about 150 MB of RAM, a few CPU seconds every 30 minutes, under 1 MB of disk,
no inbound port.

- **At home** (Raspberry Pi, NAS, mini PC): the simplest choice, it reaches Home Assistant on the LAN.
- **Free VM** (e.g. Google Compute Engine e2-micro "Always Free", US regions): same compose. To
  notify a Home Assistant at home you need a public HA URL or a VPN (Tailscale, WireGuard).
- **Scheduled job** (Cloud Run Job + Cloud Scheduler, cron, Kubernetes CronJob): start the container
  with `--loop 0` (one run, then exit) and a persistent `/data`.

One instance per configuration: two instances fight over `token.json` and `state.json` and
notifications are sent twice.

### Monitoring
With `METRICS_PORT` (any port 1-65535; the compose uses `9105` if unset, `0` turns it all off) the
script exposes two HTTP endpoints:

- `/metrics`: **Prometheus** metrics;
- `/healthz`: `200` if the last run succeeded and is recent (within two intervals), `503` if it
  failed or is too old; the body is a JSON status. At startup, before the first run, it is `200`.

In the compose the container port follows `METRICS_PORT`; on the host it is published on
`METRICS_BIND` (address:port, default `127.0.0.1:9105`, i.e. local only). If Prometheus or Uptime
Kuma run on another host use `METRICS_BIND=0.0.0.0:9105`. If they are containers on the same host,
add `deploy/compose.monitoraggio.yml` (in Portainer: *Additional paths*): it attaches the service to the Prometheus and Kuma Docker networks, set with `PROMETHEUS_NETWORK` and
`KUMA_NETWORK` (default `monitoring`; names from `docker network ls`). The target becomes
`didup-calendar-sync:<METRICS_PORT>`.
```bash
docker compose -f compose.yml -f compose.monitoraggio.yml up -d
``` The examples below use port 9105.

| Metric | Meaning |
| --- | --- |
| `didup_up` | 1 if the last run succeeded |
| `didup_last_success_timestamp_seconds`, `didup_last_run_timestamp_seconds` | end of the last successful run and of the last run |
| `didup_run_duration_seconds` | duration of the last run |
| `didup_runs_total{result}` | `ok` / `error` runs |
| `didup_calendar_changes_total{alunno,op}` | `created` / `updated` / `deleted` events |
| `didup_notifications_total{alunno,tipo}` | notifications sent |
| `didup_notification_errors_total{servizio}` | failed sends per recipient |
| `didup_attachments_total{alunno,archivio,esito}` | attachments `caricato` (uploaded) / `errore` |
| `didup_items{alunno,tipo}` | grades, notices, notes, reminders, absences, homework, lessons seen in the last run |
| `didup_argo_client_version_info{scuola,versione}` | Argo app version in use |
| `didup_build_info{versione}` | didup-calendar-sync version |

Labels only carry the pupil's name, never grades or texts. Prometheus scrape config and example
alert rules (failed sync, no successful run for 2 hours, lessons gone, Argo version changed) are in
the Italian section above: the YAML is the same.

**Uptime Kuma**, two ways (also together):

- **Push** (recommended): create a *Push* monitor with an interval slightly longer than
  `SYNC_INTERVAL` (e.g. 35 minutes) and put its URL in `KUMA_PUSH_URL` (the `?status=up&msg=OK&ping=`
  form copied from Kuma is fine). After each run the script sends `up` with duration and version, or
  `down` with the error; if nothing arrives (container stopped or stuck) Kuma alerts by itself. The
  URL contains a token: keep it in `.env` or the stack variables.
- **HTTP**: an *HTTP(s)* monitor on `http://docker-host:9105/healthz`: red on `503` or when the
  container doesn't answer.

### Releases
GitHub Actions runs the tests on every push and pull request. A push to `main` publishes the `edge`
image; a `vYYYY.MM.DD` tag publishes `YYYY.MM.DD` and `latest`. The version is logged at startup.

For a copy hosted on Gitea or Forgejo there is `.gitea/workflows/ci.yml`: same tests and an image in
the instance registry (`edge`, `sha-<commit>` on every push, version and `latest` on tags), with the
`REGISTRY_TOKEN` secret.

### Tests
```bash
uv run --no-project --python 3.12 --with-requirements requirements.txt \
  python -m unittest discover -s tests -v       # offline, no account
docker build --target test .                    # same as CI
```

### PoCs
`pocs/` holds one script per integration (Argo login, dashboard, timetable and attachments, Google
auth, Calendar, notifications, Nextcloud), run with `uv run`, reusing `data/config.toml` and `.env`. Read-only by default,
writes only with `--scrivi` on a test calendar, `--anonimizza` to share output safely. They also show
how the main script interprets the same data. Details (in Italian) in [pocs/README.md](pocs/README.md).

### Behaviour
- Managed events are tagged (extended property `argo_sync=1`): anything created by hand is left alone.
- Lessons: updated or removed only on days whose timetable was downloaded successfully; past ones stay.
- Homework: a change by the teacher updates the lesson (or the 📚 event); past 📚 events stay as history.
- Safety net: if Argo returns nothing in a run, or more than half of the existing events (and more
  than 10) would disappear, deletion is skipped.
- When a sync fails you get **one** error notification, and one when it recovers.
- `argo-client-version` is read from the App Store on every run, to avoid the 410 for outdated clients.
- At startup the log shows the version and one line per pupil with active notifications and the
  attachment archive, e.g. `didup-calendar-sync 2026.10.13-abc1234 …` and `config /data/config.toml:
  Anna (SC67890/0): notifiche voti,bacheca,note,promemoria, allegati drive`: handy to check that
  the container runs the right image and config.
- Attachments: the script never calls "presa visione" (read receipt) or sign-up; downloading an
  attachment doesn't set them.

### Known limitations
- Unofficial Argo APIs (reverse engineered): they can change without notice.
- The Argo timetable can be incomplete compared with the school's (e.g. hours of a teacher not yet
  entered): those hours are missing and their homework becomes 📚 events.
- A Drive attachment link opens only for the Google account owning the files (the calendars' one)
  or whoever has access to the folder: for other phones share the `Scuola` folder in Drive, or use
  Nextcloud with `link = "pubblico"`.
- Schools use different fields (e.g. disciplinary notes with `desDescrizione`/`datNota`): if a type
  comes through empty, PoCs 02/03 show the raw response to see which fields to use.
